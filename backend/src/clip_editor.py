"""
Clip editing helpers for trim/split/merge/caption/export workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Iterable, List, Any, Optional
import io
import logging
import uuid
import subprocess

import cv2
import numpy as np
import requests
from moviepy import (
    VideoFileClip,
    concatenate_videoclips,
    CompositeVideoClip,
    TextClip,
    ImageClip,
)

logger = logging.getLogger(__name__)

# ── Redis cache for IconScout (TAREA 5) ─────────────────────────────────────
try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

# ── render3d service URL (TAREA 4) ──────────────────────────────────────────
_RENDER3D_URL: str | None = None
_REDIS_CLIENT: "aioredis.Redis | None" = None
_IN_MEMORY_FALLBACK: dict[str, str] = {}

try:
    from gpu_utils import get_ffmpeg_video_codec_args
except ImportError:
    def get_ffmpeg_video_codec_args(q="high"):
        return {"codec": "libx264", "preset": "ultrafast", "extra_args": ["-crf", "22"]}


@dataclass
class ExportPreset:
    name: str
    width: int
    height: int
    video_bitrate: str
    audio_bitrate: str


EXPORT_PRESETS = {
    "tiktok": ExportPreset("tiktok", 1080, 1920, "10M", "192k"),
    "reels": ExportPreset("reels", 1080, 1920, "12M", "192k"),
    "shorts": ExportPreset("shorts", 1080, 1920, "10M", "192k"),
}


def _safe_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}.mp4"


def _double_bitrate(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.endswith("m"):
        return f"{int(float(normalized[:-1]) * 2)}M"
    if normalized.endswith("k"):
        return f"{int(float(normalized[:-1]) * 2)}k"
    return value


def _source_fps(clip: VideoFileClip) -> float:
    fps = clip.fps if clip.fps and clip.fps > 0 else 30
    return float(fps)


def _high_quality_encode_options(fps: float) -> dict[str, object]:
    enc = get_ffmpeg_video_codec_args("high")
    return {
        "codec": enc["codec"],
        "audio_codec": "aac",
        "audio_bitrate": "256k",
        "preset": enc["preset"],
        "logger": None,
        "fps": fps,
        "ffmpeg_params": enc["extra_args"] + [
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-movflags",
            "+faststart",
            "-sws_flags",
            "lanczos",
        ],
    }


def trim_clip_file(
    input_path: Path, output_dir: Path, start_offset: float, end_offset: float
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _safe_name("trim")

    clip = VideoFileClip(str(input_path))
    try:
        end_time = max(start_offset + 0.1, clip.duration - max(end_offset, 0.0))
        trimmed = clip.subclipped(max(0.0, start_offset), min(end_time, clip.duration))
        trimmed.write_videofile(str(output_path), **_high_quality_encode_options(_source_fps(clip)))
        trimmed.close()
    finally:
        clip.close()

    return output_path


def split_clip_file(
    input_path: Path, output_dir: Path, split_time: float
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    first_path = output_dir / _safe_name("split_a")
    second_path = output_dir / _safe_name("split_b")

    clip = VideoFileClip(str(input_path))
    try:
        source_fps = _source_fps(clip)
        s = max(0.2, min(split_time, clip.duration - 0.2))
        part_a = clip.subclipped(0, s)
        part_b = clip.subclipped(s, clip.duration)
        part_a.write_videofile(str(first_path), **_high_quality_encode_options(source_fps))
        part_b.write_videofile(str(second_path), **_high_quality_encode_options(source_fps))
        part_a.close()
        part_b.close()
    finally:
        clip.close()

    return first_path, second_path


def merge_clip_files(
    paths: Iterable[Path],
    output_dir: Path,
    strategy: str = "none",
) -> Path:
    """
    Merge multiple clip files into a single video.

    Parameters
    ----------
    paths : Iterable[Path]
        Ordered list of clip paths to merge.
    output_dir : Path
        Directory where the merged output will be written.
    strategy : str
        Transition strategy:
          - "none" (default): simple concatenation (legacy behavior).
          - "auto": intelligently select transitions based on content analysis.
          - "random": weighted random transition selection.
          - "match_cut", "glitch", "sweep_mask", "mask_reveal", "shape_morph":
            force a specific transition type.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _safe_name("merge")

    # If strategy is not "none", use transition_selector for smart merging
    if strategy != "none":
        try:
            from transition_selector import merge_with_transitions

            clip_paths = [Path(p) if not isinstance(p, Path) else p for p in paths]
            result = merge_with_transitions(
                clip_paths=clip_paths,
                output_dir=output_dir,
                strategy=strategy,
            )
            if result is not None:
                logger.info(
                    "merge_clip_files — transition merge applied (strategy=%s): %s",
                    strategy, result.name,
                )
                return result
            logger.warning(
                "merge_clip_files — transition merge returned None, "
                "falling back to simple concatenation (strategy=%s)",
                strategy,
            )
        except Exception as exc:
            logger.warning(
                "merge_clip_files — transition merge failed (%s), "
                "falling back to simple concatenation",
                exc,
            )

    # Legacy behavior: simple concatenation
    logger.info("merge_clip_files — simple concatenation (strategy=%s)", strategy)
    clips = [VideoFileClip(str(p)) for p in paths]
    try:
        source_fps = next((_source_fps(clip) for clip in clips if clip.fps and clip.fps > 0), 30.0)
        merged = concatenate_videoclips(clips, method="compose")
        merged.write_videofile(str(output_path), **_high_quality_encode_options(source_fps))
        merged.close()
    finally:
        for clip in clips:
            clip.close()

    return output_path


def overlay_custom_captions(
    input_path: Path,
    output_dir: Path,
    caption_text: str,
    position: str,
    highlight_words: List[str],
    icon_keywords: dict[str, str] | None = None,
) -> Path:
    """
    Superpone subtítulos con palabras resaltadas e iconos opcionales.

    *icon_keywords* es un diccionario ``{palabra: url_png}``. Para cada palabra
    que aparezca en el texto y tenga una entrada en *icon_keywords*, se descarga
    el PNG, se crea un ``ImageClip`` de 80×80 px y se posiciona centrado 95 px
    por encima de la palabra durante la misma duración que ésta, con un pop-in
    suave (opacidad 0→1 en 0.1 s).

    Parámetros
    ----------
    input_path : Path
        Ruta al video de entrada.
    output_dir : Path
        Directorio donde se guardará el video de salida.
    caption_text : str
        Texto de los subtítulos.
    position : str
        Posición vertical: ``"top"``, ``"middle"`` o ``"bottom"``.
    highlight_words : list[str]
        Palabras a resaltar en dorado.
    icon_keywords : dict[str, str] | None
        Mapa de palabra → URL de PNG. Si es ``None``, no se añaden iconos.

    Returns
    -------
    Path
        Ruta al video generado.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _safe_name("caption")

    base_clip = VideoFileClip(str(input_path))
    try:
        words = [w for w in caption_text.split() if w.strip()]
        source_fps = _source_fps(base_clip)
        if not words:
            base_clip.write_videofile(str(output_path), **_high_quality_encode_options(source_fps))
            return output_path

        y_position = {
            "top": int(base_clip.h * 0.18),
            "middle": int(base_clip.h * 0.52),
            "bottom": int(base_clip.h * 0.78),
        }.get(position, int(base_clip.h * 0.78))

        highlighted = {w.strip().lower() for w in highlight_words if w.strip()}
        word_duration = max(base_clip.duration / max(len(words), 1), 0.1)

        layers: list = []
        icon_cache: dict[str, ImageClip] = {}

        for idx, word in enumerate(words):
            word_clean = word.lower().strip(".,!?;:")
            color = "#FFD700" if word_clean in highlighted else "#FFFFFF"

            text_layer = (
                TextClip(
                    text=word,
                    font_size=64,
                    color=color,
                    stroke_color="black",
                    stroke_width=2,
                    method="label",
                )
                .with_start(idx * word_duration)
                .with_duration(word_duration)
                .with_position(("center", y_position))
            )
            layers.append(text_layer)

            # Añadir icono si existe en icon_keywords
            if icon_keywords and word_clean in icon_keywords:
                icon_url = icon_keywords[word_clean]
                if word_clean not in icon_cache:
                    try:
                        resp = requests.get(icon_url, timeout=10)
                        resp.raise_for_status()
                        img_arr = cv2.imdecode(
                            np.frombuffer(resp.content, np.uint8),
                            cv2.IMREAD_UNCHANGED,
                        )
                        if img_arr is None:
                            continue
                        img_rgb = cv2.cvtColor(img_arr, cv2.COLOR_BGRA2RGBA)
                        icon_clip = (
                            ImageClip(img_rgb)
                            .resized(width=80, height=80)
                            .with_start(idx * word_duration)
                            .with_duration(word_duration)
                            .with_position(("center", y_position - 95))
                            .with_opacity(lambda t: min(t / 0.1, 1.0))
                        )
                        icon_cache[word_clean] = icon_clip
                        layers.append(icon_clip)
                    except Exception as exc:
                        logger.warning("No se pudo cargar icono para '%s': %s", word_clean, exc)

        composite = CompositeVideoClip([base_clip] + layers)
        composite.write_videofile(str(output_path), **_high_quality_encode_options(source_fps))
        composite.close()
        for layer in layers:
            layer.close()
    finally:
        base_clip.close()

    return output_path


def export_with_preset(input_path: Path, output_dir: Path, preset_name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    preset = EXPORT_PRESETS.get(preset_name)
    if not preset:
        raise ValueError(f"Unknown export preset: {preset_name}")

    output_path = output_dir / _safe_name(preset.name)
    scale_filter = (
        f"scale={preset.width}:{preset.height}:"
        "force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={preset.width}:{preset.height}:(ow-iw)/2:(oh-ih)/2"
    )
    enc = get_ffmpeg_video_codec_args("high")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        scale_filter,
        "-c:v",
        enc["codec"],
        "-preset",
        enc["preset"],
        *enc["extra_args"],
        "-maxrate",
        preset.video_bitrate,
        "-bufsize",
        _double_bitrate(preset.video_bitrate),
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-c:a",
        "aac",
        "-b:a",
        preset.audio_bitrate,
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return output_path


# ══════════════════════════════════════════════════════════════════════════
# MÓDULO 0 — Motion Blur helper (base para todos los efectos)
# ══════════════════════════════════════════════════════════════════════════


def generate_blur_keyframes(n_frames: int, base_value: int = 10) -> list[int]:
    """
    Genera una secuencia de valores de blur con forma de campana.

    La secuencia sube desde *base_value* hasta un pico de ``base_value * 4``
    en la mitad y luego vuelve a bajar. Útil para motion blur en transiciones.

    Parámetros
    ----------
    n_frames : int
        Número total de frames de la secuencia.
    base_value : int
        Valor base de blur (default 10).

    Returns
    -------
    list[int]
        Lista de valores de blur con forma de campana.
    """
    if n_frames <= 1:
        return [base_value]
    half = n_frames // 2
    result = []
    for i in range(n_frames):
        if i < half:
            t = i / max(half, 1)
        else:
            t = (n_frames - 1 - i) / max(n_frames - 1 - half, 1)
        # Campana suave: base → pico → base
        val = base_value + (base_value * 3) * (t * (2 - t))
        result.append(int(round(val)))
    return result


def apply_motion_blur_to_transition(
    clip: VideoFileClip, blur_frames: list[int]
) -> VideoFileClip:
    """
    Aplica motion blur (boxblur) frame a frame mediante FFmpeg subprocess.

    Cada frame del clip recibe un valor de blur distinto según la lista
    *blur_frames*. Si la lista tiene menos elementos que frames, se repite
    el último valor.

    Parámetros
    ----------
    clip : VideoFileClip
        Clip de entrada.
    blur_frames : list[int]
        Lista de valores de blur (radio de boxblur) por frame.

    Returns
    -------
    VideoFileClip
        Clip con motion blur aplicado.
    """
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="mblur_"))
    in_path = tmpdir / "mblur_in.mp4"
    out_path = tmpdir / "mblur_out.mp4"

    fps = _source_fps(clip)
    clip.write_videofile(str(in_path), **_high_quality_encode_options(fps))

    n_frames_total = int(clip.duration * fps)
    # Construir filter per frame: select + boxblur
    filter_parts = []
    for i in range(n_frames_total):
        bv = blur_frames[i] if i < len(blur_frames) else blur_frames[-1]
        filter_parts.append(
            f"[0:v]select=eq(n\\,{i}),boxblur={bv}:{bv}:enable='eq(n,{i})'[f{i}]"
        )

    # Concatenar todos los frames procesados
    concat_input = "".join(f"[f{i}]" for i in range(n_frames_total))
    filter_complex = ";".join(filter_parts)
    filter_complex += f";{concat_input}concat=n={n_frames_total}:v=1:a=0[out]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    result = VideoFileClip(str(out_path))
    return result


# ══════════════════════════════════════════════════════════════════════════
# Funciones helper internas para transiciones
# ══════════════════════════════════════════════════════════════════════════


def _smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _resample_contour(contour: np.ndarray, n_points: int = 64) -> np.ndarray:
    contour = contour.squeeze().astype(np.float64)
    if contour.ndim != 2 or contour.shape[1] != 2:
        return np.zeros((n_points, 2), dtype=np.float64)
    diffs = np.diff(contour, axis=0)
    seg_lens = np.sqrt((diffs ** 2).sum(axis=1))
    cum_len = np.concatenate([[0], seg_lens.cumsum()])
    total_len = cum_len[-1]
    if total_len < 1e-8:
        return np.zeros((n_points, 2), dtype=np.float64)
    sample_pos = np.linspace(0, total_len, n_points)
    return np.column_stack([np.interp(sample_pos, cum_len, contour[:, i]) for i in range(2)])


def _get_frame_array(clip: VideoFileClip, t: float) -> np.ndarray:
    frame = clip.get_frame(t)
    return np.array(frame)


def _darkest_region(frame: np.ndarray) -> tuple[int, int, int, int]:
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    block_size = max(8, min(h, w) // 16)
    best_mean = 255
    best_rect = (0, 0, w // 2, h // 2)
    for y in range(0, h - block_size, block_size // 2):
        for x in range(0, w - block_size, block_size // 2):
            block = gray[y:y + block_size, x:x + block_size]
            mean_val = block.mean()
            if mean_val < best_mean:
                best_mean = mean_val
                best_rect = (x, y, block_size * 2, block_size * 2)
    return best_rect


def _procrustes_align(
    contour_a: np.ndarray, contour_b: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    ca = contour_a - contour_a.mean(axis=0)
    cb = contour_b - contour_b.mean(axis=0)
    norm_a = np.linalg.norm(ca)
    norm_b = np.linalg.norm(cb)
    if norm_a > 1e-8:
        ca = ca / norm_a
    if norm_b > 1e-8:
        cb = cb / norm_b
    return ca, cb


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 1 — match_cut_transition
# ══════════════════════════════════════════════════════════════════════════


def match_cut_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    obj_center_a: tuple[float, float] | None = None,
    obj_center_b: tuple[float, float] | None = None,
    duration: float = 0.08,
    motion_blur: bool = True,
    n_blur_frames: int = 5,
) -> VideoFileClip:
    logger.info(
        "match_cut_transition — duration=%.2f motion_blur=%s n_blur_frames=%d",
        duration, motion_blur, n_blur_frames,
    )
    try:
        fps = _source_fps(clip_a)
        n_frames = max(1, int(duration * fps))

        w, h = clip_a.w, clip_a.h
        cx_a = obj_center_a[0] if obj_center_a is not None else w / 2
        cy_a = obj_center_a[1] if obj_center_a is not None else h / 2
        cx_b = obj_center_b[0] if obj_center_b is not None else w / 2
        cy_b = obj_center_b[1] if obj_center_b is not None else h / 2

        tail_a = clip_a.subclipped(max(0, clip_a.duration - duration), clip_a.duration)
        tail_a_modified = tail_a.transform(
            lambda t, img: _match_cut_transform_frame(
                img, t, duration, w, h, cx_a, cy_a, scale_to=1.08
            )
        )

        head_b = clip_b.subclipped(0, duration)
        head_b_modified = head_b.transform(
            lambda t, img: _match_cut_transform_frame(
                img, t, duration, w, h, cx_b, cy_b, scale_from=1.08, scale_to=1.0
            )
        )

        if motion_blur and n_blur_frames > 0:
            blur_seq = generate_blur_keyframes(n_blur_frames, base_value=10)
            tail_a_modified = apply_motion_blur_to_transition(tail_a_modified, blur_seq)
            head_b_modified = apply_motion_blur_to_transition(head_b_modified, blur_seq)

        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)

        return concatenate_videoclips([before, tail_a_modified, head_b_modified, after])
    except Exception as exc:
        logger.error("match_cut_transition falló: %s", exc)
        return concatenate_videoclips([clip_a, clip_b])


def _match_cut_transform_frame(
    img: np.ndarray,
    t: float,
    duration: float,
    w: int,
    h: int,
    cx: float,
    cy: float,
    scale_from: float = 1.0,
    scale_to: float = 1.08,
) -> np.ndarray:
    progress = min(t / duration, 1.0)
    eased = _smoothstep(progress)
    scale = scale_from + (scale_to - scale_from) * eased
    center_w = w / 2
    center_h = h / 2
    tx = (cx - center_w) * (scale - 1.0) * eased
    ty = (cy - center_h) * (scale - 1.0) * eased
    M = np.float32([
        [scale, 0, center_w * (1 - scale) - tx],
        [0, scale, center_h * (1 - scale) - ty],
    ])
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR)


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 2 — glitch_transition
# ══════════════════════════════════════════════════════════════════════════


def glitch_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    duration: float = 0.4,
    n_slices: int = 8,
    max_offset_ratio: float = 0.08,
    seed: int = 42,
) -> VideoFileClip:
    logger.info("glitch_transition — duration=%.2f n_slices=%d", duration, n_slices)
    try:
        rng = np.random.default_rng(seed)
        fps = _source_fps(clip_a)
        n_frames = max(1, int(duration * fps))
        w, h = clip_a.w, clip_a.h

        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="glitch_"))
        frames_dir = tmpdir / "frames"
        frames_dir.mkdir()

        slice_heights = [h // n_slices] * n_slices
        slice_heights[-1] += h - sum(slice_heights)
        slice_offsets_x = rng.integers(-int(w * max_offset_ratio), int(w * max_offset_ratio) + 1, size=(n_frames, n_slices))

        for i in range(n_frames):
            t_a = clip_a.duration - duration + i / fps
            t_b = i / fps
            progress = i / max(n_frames - 1, 1)
            frame_a = _get_frame_array(clip_a, min(t_a, clip_a.duration - 1 / fps))
            frame_b = _get_frame_array(clip_b, min(t_b, clip_b.duration - 1 / fps))
            out = np.zeros_like(frame_a)
            y = 0
            for s, sh in enumerate(slice_heights):
                blend = _smoothstep(progress + rng.uniform(-0.1, 0.1))
                blend = float(np.clip(blend, 0.0, 1.0))
                row_a = frame_a[y:y + sh]
                row_b = frame_b[y:y + sh]
                blended = (row_a * (1 - blend) + row_b * blend).astype(np.uint8)
                ox = int(slice_offsets_x[i, s] * (1 - progress))
                blended_shifted = np.roll(blended, ox, axis=1)
                out[y:y + sh] = blended_shifted
                y += sh
            cv2.imwrite(str(frames_dir / f"frame_{i:05d}.png"), cv2.cvtColor(out, cv2.COLOR_RGB2BGR))

        morph_path = tmpdir / "glitch.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%05d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(morph_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        transition_clip = VideoFileClip(str(morph_path))
        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, transition_clip, after])
    except Exception as exc:
        logger.error("glitch_transition falló: %s", exc)
        return concatenate_videoclips([clip_a, clip_b])


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 3 — sweep_mask_transition
# ══════════════════════════════════════════════════════════════════════════


def sweep_mask_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    duration: float = 0.5,
    direction: str = "left",
    feather: int = 40,
) -> VideoFileClip:
    logger.info("sweep_mask_transition — duration=%.2f direction=%s", duration, direction)
    try:
        fps = _source_fps(clip_a)
        n_frames = max(1, int(duration * fps))
        w, h = clip_a.w, clip_a.h

        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="sweep_"))
        frames_dir = tmpdir / "frames"
        frames_dir.mkdir()

        for i in range(n_frames):
            t_a = clip_a.duration - duration + i / fps
            t_b = i / fps
            progress = _smoothstep(i / max(n_frames - 1, 1))
            frame_a = _get_frame_array(clip_a, min(t_a, clip_a.duration - 1 / fps))
            frame_b = _get_frame_array(clip_b, min(t_b, clip_b.duration - 1 / fps))

            mask = np.zeros((h, w), dtype=np.float32)
            if direction == "left":
                edge = int(progress * (w + feather)) - feather
                for x in range(w):
                    v = np.clip((x - edge) / max(feather, 1), 0.0, 1.0)
                    mask[:, x] = v
            elif direction == "right":
                edge = int((1 - progress) * (w + feather))
                for x in range(w):
                    v = np.clip((edge - x) / max(feather, 1), 0.0, 1.0)
                    mask[:, x] = v
            elif direction == "down":
                edge = int(progress * (h + feather)) - feather
                for y in range(h):
                    v = np.clip((y - edge) / max(feather, 1), 0.0, 1.0)
                    mask[y, :] = v
            else:  # up
                edge = int((1 - progress) * (h + feather))
                for y in range(h):
                    v = np.clip((edge - y) / max(feather, 1), 0.0, 1.0)
                    mask[y, :] = v

            mask3 = mask[:, :, np.newaxis]
            out = (frame_a * (1 - mask3) + frame_b * mask3).astype(np.uint8)
            cv2.imwrite(str(frames_dir / f"frame_{i:05d}.png"), cv2.cvtColor(out, cv2.COLOR_RGB2BGR))

        morph_path = tmpdir / "sweep.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%05d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(morph_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        transition_clip = VideoFileClip(str(morph_path))
        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, transition_clip, after])
    except Exception as exc:
        logger.error("sweep_mask_transition falló: %s", exc)
        return concatenate_videoclips([clip_a, clip_b])


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 4 — mask_reveal_transition
# ══════════════════════════════════════════════════════════════════════════


def mask_reveal_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    duration: float = 0.6,
    shape: str = "circle",
) -> VideoFileClip:
    logger.info("mask_reveal_transition — duration=%.2f shape=%s", duration, shape)
    try:
        fps = _source_fps(clip_a)
        n_frames = max(1, int(duration * fps))
        w, h = clip_a.w, clip_a.h
        cx, cy = w / 2, h / 2
        max_r = float(np.sqrt(cx ** 2 + cy ** 2)) * 1.05

        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="reveal_"))
        frames_dir = tmpdir / "frames"
        frames_dir.mkdir()

        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)

        for i in range(n_frames):
            t_a = clip_a.duration - duration + i / fps
            t_b = i / fps
            progress = _ease_out_cubic(i / max(n_frames - 1, 1))
            frame_a = _get_frame_array(clip_a, min(t_a, clip_a.duration - 1 / fps))
            frame_b = _get_frame_array(clip_b, min(t_b, clip_b.duration - 1 / fps))

            if shape == "circle":
                r = progress * max_r
                dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
                feather = max_r * 0.05
                mask = np.clip((r - dist) / feather, 0.0, 1.0)
            else:  # diamond
                r = progress * max_r
                dist = np.abs(xs - cx) + np.abs(ys - cy)
                feather = max_r * 0.05
                mask = np.clip((r - dist) / feather, 0.0, 1.0)

            mask3 = mask[:, :, np.newaxis]
            out = (frame_a * (1 - mask3) + frame_b * mask3).astype(np.uint8)
            cv2.imwrite(str(frames_dir / f"frame_{i:05d}.png"), cv2.cvtColor(out, cv2.COLOR_RGB2BGR))

        morph_path = tmpdir / "reveal.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%05d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(morph_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        transition_clip = VideoFileClip(str(morph_path))
        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, transition_clip, after])
    except Exception as exc:
        logger.error("mask_reveal_transition falló: %s", exc)
        return concatenate_videoclips([clip_a, clip_b])


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 5 — shape_morph_transition  (cv2.VideoWriter → libx264 via FFmpeg)
# ══════════════════════════════════════════════════════════════════════════


def shape_morph_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    duration: float = 0.7,
    n_contour_points: int = 64,
    use_sam: bool = False,
) -> VideoFileClip:
    logger.info("shape_morph_transition — duration=%.2f use_sam=%s", duration, use_sam)
    try:
        fps = _source_fps(clip_a)
        n_frames = max(1, int(duration * fps))
        w, h = clip_a.w, clip_a.h

        last_frame_a = _get_frame_array(clip_a, clip_a.duration - 1 / fps)
        first_frame_b = _get_frame_array(clip_b, 0.0)

        # Obtener contornos dominantes
        def _dominant_contour(frame: np.ndarray) -> np.ndarray:
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if not contours:
                return np.array([[w // 2, h // 2]] * n_contour_points, dtype=np.float64)
            largest = max(contours, key=cv2.contourArea)
            return _resample_contour(largest, n_contour_points)

        contour_a = _dominant_contour(last_frame_a)
        contour_b = _dominant_contour(first_frame_b)
        ca_aligned, cb_aligned = _procrustes_align(contour_a, contour_b)

        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="morph_"))
        frames_dir = tmpdir / "frames"
        frames_dir.mkdir()

        for i in range(n_frames):
            t_a = clip_a.duration - duration + i / fps
            t_b = i / fps
            progress = _smoothstep(i / max(n_frames - 1, 1))

            frame_a = _get_frame_array(clip_a, min(t_a, clip_a.duration - 1 / fps))
            frame_b = _get_frame_array(clip_b, min(t_b, clip_b.duration - 1 / fps))

            # Interpolar contorno
            interp_c = (ca_aligned * (1 - progress) + cb_aligned * progress)
            # Re-escalar al tamaño del frame
            scale_x = w / 2
            scale_y = h / 2
            pts = (interp_c * min(scale_x, scale_y) + np.array([w / 2, h / 2])).astype(np.int32)

            # Máscara del contorno interpolado
            mask_img = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(mask_img, [pts], 255)
            mask = mask_img.astype(np.float32) / 255.0
            feather_k = max(3, int(min(w, h) * 0.02)) | 1  # impar
            mask = cv2.GaussianBlur(mask, (feather_k, feather_k), 0)
            mask3 = mask[:, :, np.newaxis]

            out = (frame_a * (1 - mask3) + frame_b * mask3).astype(np.uint8)
            cv2.imwrite(str(frames_dir / f"frame_{i:05d}.png"), cv2.cvtColor(out, cv2.COLOR_RGB2BGR))

        morph_path = tmpdir / "morph.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%05d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(morph_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        transition_clip = VideoFileClip(str(morph_path))
        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, transition_clip, after])
    except Exception as exc:
        logger.error("shape_morph_transition falló: %s", exc)
        return concatenate_videoclips([clip_a, clip_b])
