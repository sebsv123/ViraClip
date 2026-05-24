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
        return {"codec": "nvenc_h264", "preset": "slow", "extra_args": ["-crf", "18"]}


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
    """
    Aplica smoothstep easing: 3t² - 2t³.

    Parámetros
    ----------
    t : float
        Valor de progreso entre 0 y 1.

    Returns
    -------
    float
        Valor con easing smoothstep.
    """
    return t * t * (3 - 2 * t)


def _ease_out_cubic(t: float) -> float:
    """
    Aplica ease-out cúbico: 1 - (1 - t)³.

    Parámetros
    ----------
    t : float
        Valor de progreso entre 0 y 1.

    Returns
    -------
    float
        Valor con easing ease-out cúbico.
    """
    return 1 - (1 - t) ** 3


def _resample_contour(contour: np.ndarray, n_points: int = 64) -> np.ndarray:
    """
    Remuestrea un contorno a exactamente *n_points* puntos equidistantes.

    Parámetros
    ----------
    contour : np.ndarray
        Contorno de entrada (N, 2).
    n_points : int
        Número de puntos de salida (default 64).

    Returns
    -------
    np.ndarray
        Contorno remuestreado (n_points, 2).
    """
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
    """
    Obtiene un frame como array numpy (H, W, 3).

    Parámetros
    ----------
    clip : VideoFileClip
        Clip de video.
    t : float
        Tiempo en segundos.

    Returns
    -------
    np.ndarray
        Frame como array numpy.
    """
    frame = clip.get_frame(t)
    return np.array(frame)


def _darkest_region(frame: np.ndarray) -> tuple[int, int, int, int]:
    """
    Detecta la región más oscura del frame promediando luminancia por bloques.

    Parámetros
    ----------
    frame : np.ndarray
        Frame de entrada (H, W, 3).

    Returns
    -------
    tuple[int, int, int, int]
        Región más oscura como ``(x, y, w, h)``.
    """
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
    """
    Alinea dos contornos mediante análisis Procrustes (centrado + escala).

    Ambos contornos se centran en el origen y se escalan a norma unitaria.

    Parámetros
    ----------
    contour_a : np.ndarray
        Primer contorno (N, 2).
    contour_b : np.ndarray
        Segundo contorno (N, 2).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Contornos alineados (N, 2) y (N, 2).
    """
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
    """
    Transición match cut con smoothstep easing y motion blur opcional.

    En los últimos N frames de *clip_a* escala y desplaza el contenido hacia
    *obj_center_a*. En los primeros N frames de *clip_b* escala y desplaza
    desde *obj_center_b* hasta la posición original. Luego concatena ambos
    segmentos modificados con el resto de metraje sin cambios.

    Parámetros
    ----------
    clip_a : VideoFileClip
        Primer clip (el que termina).
    clip_b : VideoFileClip
        Segundo clip (el que comienza).
    obj_center_a : tuple[float, float] | None
        Coordenadas (x, y) del objeto dominante en el último frame de clip_a.
        Si es ``None``, usa el centro del frame.
    obj_center_b : tuple[float, float] | None
        Coordenadas (x, y) del objeto dominante en el primer frame de clip_b.
        Si es ``None``, usa el centro del frame.
    duration : float
        Duración en segundos de la transición (default 0.08).
    motion_blur : bool
        Si es ``True``, aplica motion blur (default True).
    n_blur_frames : int
        Número de frames de blur (default 5).

    Returns
    -------
    VideoFileClip
        Clip concatenado con la transición aplicada.
    """
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

        # Últimos N frames de clip_a → zoom hacia obj_center_a
        tail_a = clip_a.subclipped(max(0, clip_a.duration - duration), clip_a.duration)
        tail_a_modified = tail_a.transform(
            lambda t, img: _match_cut_transform_frame(
                img, t, duration, w, h, cx_a, cy_a, scale_to=1.08
            )
        )

        # Primeros N frames de clip_b → zoom desde obj_center_b
        head_b = clip_b.subclipped(0, duration)
        head_b_modified = head_b.transform(
            lambda t, img: _match_cut_transform_frame(
                img, t, duration, w, h, cx_b, cy_b, scale_from=1.08, scale_to=1.0
            )
        )

        # Aplicar motion blur si está habilitado
        if motion_blur and n_blur_frames > 0:
            blur_seq = generate_blur_keyframes(n_blur_frames, base_value=10)
            tail_a_modified = apply_motion_blur_to_transition(tail_a_modified, blur_seq)
            head_b_modified = apply_motion_blur_to_transition(head_b_modified, blur_seq)

        # Armar resultado
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
    """
    Aplica transformación de escala+traslación con smoothstep a un frame.

    Parámetros
    ----------
    img : np.ndarray
        Frame de entrada.
    t : float
        Tiempo actual dentro de la transición.
    duration : float
        Duración total de la transición.
    w : int
        Ancho del frame.
    h : int
        Alto del frame.
    cx : float
        Centro X del objeto.
    cy : float
        Centro Y del objeto.
    scale_from : float
        Escala inicial (default 1.0).
    scale_to : float
        Escala final (default 1.08).

    Returns
    -------
    np.ndarray
        Frame transformado.
    """
    progress = min(t / duration, 1.0)
    eased = _smoothstep(progress)
    scale = scale_from + (scale_to - scale_from) * eased
    center_w, center_h = w / 2, h / 2
    dx = (center_w - cx) * eased * 0.15
    dy = (center_h - cy) * eased * 0.15

    M = cv2.getRotationMatrix2D((cx, cy), 0, scale)
    M[0, 2] += dx
    M[1, 2] += dy
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LANCZOS4)


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 2 — glitch_transition
# ══════════════════════════════════════════════════════════════════════════


def glitch_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    style: str = "rgb",
    duration: float = 0.1,
    motion_blur: bool = True,
    n_blur_frames: int = 5,
) -> VideoFileClip:
    """
    Transición glitch usando FFmpeg filter_complex con motion blur opcional.

    Aplica rgbashift (desplazamiento de canales RGB) en los últimos frames de
    *clip_a* y luego cruza a *clip_b* con xfade. El parámetro *style* controla
    el tipo de glitch:

    - ``"rgb"``: desplazamiento de canales rojo/azul (rh=3, bh=-3).
    - ``"scan"``: rgbashift + desaturación + scanlines.
    - ``"freeze"``: congela el último frame 4 frames + ruido + hard cut.

    Parámetros
    ----------
    clip_a : VideoFileClip
        Primer clip.
    clip_b : VideoFileClip
        Segundo clip.
    style : str
        Estilo de glitch: ``"rgb"``, ``"scan"`` o ``"freeze"``.
    duration : float
        Duración total de la transición (default 0.1).
    motion_blur : bool
        Si es ``True``, aplica motion blur (default True).
    n_blur_frames : int
        Número de frames de blur (default 5).

    Returns
    -------
    VideoFileClip
        Clip concatenado con transición glitch.
    """
    logger.info(
        "glitch_transition — style=%s duration=%.2f motion_blur=%s",
        style, duration, motion_blur,
    )
    try:
        fps = _source_fps(clip_a)
        w, h = clip_a.w, clip_a.h

        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="glitch_"))
        path_a = tmpdir / "glitch_a.mp4"
        path_b = tmpdir / "glitch_b.mp4"
        path_out = tmpdir / "glitch_out.mp4"

        tail_a = clip_a.subclipped(max(0, clip_a.duration - duration), clip_a.duration)
        head_b = clip_b.subclipped(0, duration)

        tail_a.write_videofile(str(path_a), **_high_quality_encode_options(fps))
        head_b.write_videofile(str(path_b), **_high_quality_encode_options(fps))

        # Construir filter_complex según estilo
        if style == "scan":
            filter_chain = (
                f"[0:v]rgbashift=rh=2:bh=-2:rv=0:bv=0,hue=s=0[glitched];"
                f"[glitched]drawbox=y=0:h=2:c=black@0.15:t=fill[scan];"
                f"[scan][1:v]xfade=transition=slideleft:duration={duration}:offset=0"
            )
        elif style == "freeze":
            filter_chain = (
                f"[0:v]loop=loop={int(fps * duration)}:size=1:start=0,"
                f"noise=alls=20:allf=t+u,"
                f"rgbashift=rh=1:bh=-1[glitched];"
                f"[glitched][1:v]xfade=transition=fade:duration={duration}:offset=0"
            )
        else:  # "rgb"
            filter_chain = (
                f"[0:v]rgbashift=rh=3:bh=-3[glitched];"
                f"[glitched][1:v]xfade=transition=slideleft:duration={duration}:offset=0"
            )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(path_a),
            "-i", str(path_b),
            "-filter_complex", filter_chain,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(path_out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        result = VideoFileClip(str(path_out))

        # Aplicar motion blur si está habilitado
        if motion_blur and n_blur_frames > 0:
            blur_seq = generate_blur_keyframes(n_blur_frames, base_value=10)
            result = apply_motion_blur_to_transition(result, blur_seq)

        # Concatenar con el resto de metraje sin modificar
        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, result, after])
    except Exception as exc:
        logger.error("glitch_transition falló: %s", exc)
        return concatenate_videoclips([clip_a, clip_b])


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 3 — sweep_mask_transition
# ══════════════════════════════════════════════════════════════════════════


def sweep_mask_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    cx: int | None = None,
    cy: int | None = None,
    shape: str = "circle",
    duration: float = 0.4,
    motion_blur: bool = True,
    n_blur_frames: int = 5,
) -> VideoFileClip:
    """
    Transición con máscara expansiva (sweep) con motion blur opcional.

    Genera una máscara que crece desde el punto *(cx, cy)* usando FFmpeg ``geq``
    con ease-out. *clip_b* se revela debajo de la máscara creciente mientras
    *clip_a* se desvanece.

    Shapes disponibles:
    - ``"circle"``: máscara circular expansiva.
    - ``"diagonal"``: plano diagonal animado.
    - ``"wipe"``: barrido horizontal.

    Parámetros
    ----------
    clip_a : VideoFileClip
        Primer clip.
    clip_b : VideoFileClip
        Segundo clip.
    cx : int | None
        Coordenada X del centro de expansión. Si es ``None``, usa el centro del frame.
    cy : int | None
        Coordenada Y del centro de expansión. Si es ``None``, usa el centro del frame.
    shape : str
        Forma de la máscara: ``"circle"``, ``"diagonal"`` o ``"wipe"``.
    duration : float
        Duración de la transición (default 0.4).
    motion_blur : bool
        Si es ``True``, aplica motion blur en los primeros frames de clip_b (default True).
    n_blur_frames : int
        Número de frames de blur (default 5).

    Returns
    -------
    VideoFileClip
        Clip con transición sweep mask.
    """
    logger.info(
        "sweep_mask_transition — shape=%s duration=%.2f motion_blur=%s",
        shape, duration, motion_blur,
    )
    try:
        fps = _source_fps(clip_a)
        w, h = clip_a.w, clip_a.h
        cx = cx if cx is not None else w // 2
        cy = cy if cy is not None else h // 2

        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="sweep_"))
        path_a = tmpdir / "sweep_a.mp4"
        path_b = tmpdir / "sweep_b.mp4"
        path_mask = tmpdir / "sweep_mask.mp4"
        path_out = tmpdir / "sweep_out.mp4"

        tail_a = clip_a.subclipped(max(0, clip_a.duration - duration), clip_a.duration)
        head_b = clip_b.subclipped(0, duration)

        tail_a.write_videofile(str(path_a), **_high_quality_encode_options(fps))
        head_b.write_videofile(str(path_b), **_high_quality_encode_options(fps))

        max_r = int(np.sqrt(w ** 2 + h ** 2))

        if shape == "diagonal":
            # Plano diagonal animado
            filter_mask = (
                f"[0:v][1:v]blend=all_mode=addition[blended];"
                f"[blended]geq=lum='255*gt(X+Y,{w}+{h}*(1-T/{duration}))':"
                f"a='255*gt(X+Y,{w}+{h}*(1-T/{duration}))'[mask];"
                f"[0:v][1:v][mask]overlay[out]"
            )
        elif shape == "wipe":
            # Barrido horizontal
            filter_mask = (
                f"[0:v][1:v]blend=all_mode=addition[blended];"
                f"[blended]geq=lum='255*gt(X,{w}*(1-T/{duration}))':"
                f"a='255*gt(X,{w}*(1-T/{duration}))'[mask];"
                f"[0:v][1:v][mask]overlay[out]"
            )
        else:  # "circle"
            # Máscara circular expansiva con ease-out
            filter_mask = (
                f"[0:v][1:v]blend=all_mode=addition[blended];"
                f"[blended]geq=lum='255*lt(sqrt((X-{cx})^2+(Y-{cy})^2),"
                f"{max_r}*(1-(1-T/{duration})^3))':"
                f"a='255*lt(sqrt((X-{cx})^2+(Y-{cy})^2),"
                f"{max_r}*(1-(1-T/{duration})^3))'[mask];"
                f"[0:v][1:v][mask]overlay[out]"
            )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(path_a),
            "-i", str(path_b),
            "-filter_complex", filter_mask,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(path_out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        result = VideoFileClip(str(path_out))

        # Aplicar motion blur en los primeros n_blur_frames de clip_b
        if motion_blur and n_blur_frames > 0:
            blur_seq = generate_blur_keyframes(n_blur_frames, base_value=10)
            result = apply_motion_blur_to_transition(result, blur_seq)

        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, result, after])
    except Exception as exc:
        logger.error("sweep_mask_transition falló: %s", exc)
        return concatenate_videoclips([clip_a, clip_b])


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 4 — mask_reveal_transition (auto-detección + semántica)
# ══════════════════════════════════════════════════════════════════════════


def mask_reveal_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    semantic_category: str | None = None,
    duration: float = 0.5,
    motion_blur: bool = True,
    n_blur_frames: int = 5,
) -> VideoFileClip:
    """
    Transición con máscara de revelado automático y selección semántica.

    Detecta automáticamente la región con mayor densidad de bordes (Canny)
    en el último frame de *clip_a*. Si la densidad máxima supera 0.3, usa
    esa región como apertura para la máscara. Si no, degrada a
    ``sweep_mask_transition`` con forma circular.

    El parámetro *semantic_category* permite elegir la forma de la máscara:

    - ``"tranquilidad"``, ``"salud"``, ``"naturaleza"`` → círculo.
    - ``"familia"``, ``"personas"`` → círculo grande centrado.
    - ``"prevención"``, ``"protección"``, ``"seguro"`` → wipe desde la izquierda.
    - ``None`` / desconocido → círculo desde la apertura detectada.

    Parámetros
    ----------
    clip_a : VideoFileClip
        Primer clip.
    clip_b : VideoFileClip
        Segundo clip.
    semantic_category : str | None
        Categoría semántica para elegir la forma de la máscara.
    duration : float
        Duración de la transición (default 0.5).
    motion_blur : bool
        Si es ``True``, aplica motion blur (default True).
    n_blur_frames : int
        Número de frames de blur (default 5).

    Returns
    -------
    VideoFileClip
        Clip con transición mask reveal.
    """
    logger.info(
        "mask_reveal_transition — semantic_category=%s duration=%.2f motion_blur=%s",
        semantic_category, duration, motion_blur,
    )
    try:
        fps = _source_fps(clip_a)
        w, h = clip_a.w, clip_a.h

        # Obtener último frame de clip_a para detección de bordes
        last_frame = _get_frame_array(clip_a, clip_a.duration - 0.04)
        gray = cv2.cvtColor(last_frame, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        # Sliding window 64×64 para encontrar región con mayor densidad de bordes
        best_density = 0.0
        best_bbox = (0, 0, w // 2, h // 2)
        step = 16
        for y in range(0, h - 64, step):
            for x in range(0, w - 64, step):
                tile = edges[y:y + 64, x:x + 64]
                density = tile.mean() / 255.0
                if density > best_density:
                    best_density = density
                    best_bbox = (x, y, 64, 64)

        logger.info("mask_reveal — densidad máxima de bordes: %.3f", best_density)

        if best_density <= 0.3:
            logger.info("mask_reveal — densidad baja, degradando a sweep_mask_transition")
            return sweep_mask_transition(
                clip_a, clip_b,
                shape="circle",
                duration=duration,
                motion_blur=motion_blur,
                n_blur_frames=n_blur_frames,
            )

        # Determinar forma según categoría semántica
        cat = (semantic_category or "").lower().strip()
        if cat in ("tranquilidad", "salud", "naturaleza"):
            shape = "circle"
            cx, cy = best_bbox[0] + 32, best_bbox[1] + 32
        elif cat in ("familia", "personas"):
            shape = "circle"
            cx, cy = w // 2, h // 2
        elif cat in ("prevención", "protección", "seguro"):
            shape = "wipe"
            cx, cy = 0, h // 2
        else:
            shape = "circle"
            cx, cy = best_bbox[0] + 32, best_bbox[1] + 32

        logger.info("mask_reveal — forma=%s centro=(%d,%d)", shape, cx, cy)

        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="mask_reveal_"))
        path_a = tmpdir / "mr_a.mp4"
        path_b = tmpdir / "mr_b.mp4"
        path_out = tmpdir / "mr_out.mp4"

        tail_a = clip_a.subclipped(max(0, clip_a.duration - duration), clip_a.duration)
        head_b = clip_b.subclipped(0, duration)

        tail_a.write_videofile(str(path_a), **_high_quality_encode_options(fps))
        head_b.write_videofile(str(path_b), **_high_quality_encode_options(fps))

        max_r = int(np.sqrt(w ** 2 + h ** 2))

        if shape == "wipe":
            filter_mask = (
                f"[0:v][1:v]blend=all_mode=addition[blended];"
                f"[blended]geq=lum='255*gt(X,{w}*(1-T/{duration}))':"
                f"a='255*gt(X,{w}*(1-T/{duration}))'[mask];"
                f"[0:v][1:v][mask]overlay[out]"
            )
        else:
            # clip_b escala desde aperture_bbox → full frame con ease-out
            filter_mask = (
                f"[0:v][1:v]blend=all_mode=addition[blended];"
                f"[blended]geq=lum='255*lt(sqrt((X-{cx})^2+(Y-{cy})^2),"
                f"{max_r}*(1-(1-T/{duration})^3))':"
                f"a='255*lt(sqrt((X-{cx})^2+(Y-{cy})^2),"
                f"{max_r}*(1-(1-T/{duration})^3))'[mask];"
                f"[0:v][1:v][mask]overlay[out]"
            )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(path_a),
            "-i", str(path_b),
            "-filter_complex", filter_mask,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(path_out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        result = VideoFileClip(str(path_out))

        # Opacidad: fade-in rápido en 0.12 s
        result = result.with_opacity(lambda t: min(t / 0.12, 1.0))

        if motion_blur and n_blur_frames > 0:
            blur_seq = generate_blur_keyframes(n_blur_frames, base_value=10)
            result = apply_motion_blur_to_transition(result, blur_seq)

        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, result, after])
    except Exception as exc:
        logger.error("mask_reveal_transition falló: %s", exc)
        return sweep_mask_transition(
            clip_a, clip_b,
            shape="circle",
            duration=duration,
            motion_blur=motion_blur,
            n_blur_frames=n_blur_frames,
        )


# ══════════════════════════════════════════════════════════════════════════
# EFECTO 5 — shape_morph_transition (SAM / rembg + Procrustes)
# ══════════════════════════════════════════════════════════════════════════


def shape_morph_transition(
    clip_a: VideoFileClip,
    clip_b: VideoFileClip,
    quality: str = "fast",
    duration: float = 0.6,
    motion_blur: bool = True,
    n_blur_frames: int = 5,
) -> VideoFileClip:
    """
    Transición morphing de contornos usando SAM o rembg con Procrustes.

    Segmenta el objeto dominante en el último frame de *clip_a* y el primero
    de *clip_b*, extrae sus contornos, los alinea con Procrustes y genera
    N frames intermedios morphing.

    *quality* controla el segmentador:
    - ``"fast"``: rembg u2netp (rápido, menor precisión).
    - ``"high"``: SAM vit_b (precisión media).
    - ``"ultra"``: SAM vit_h (máxima precisión).

    Cadena de degradación: SAM → rembg → sweep_mask_transition.

    Parámetros
    ----------
    clip_a : VideoFileClip
        Primer clip.
    clip_b : VideoFileClip
        Segundo clip.
    quality : str
        Calidad del segmentador: ``"fast"``, ``"high"`` o ``"ultra"``.
    duration : float
        Duración de la transición (default 0.6).
    motion_blur : bool
        Si es ``True``, aplica motion blur (default True).
    n_blur_frames : int
        Número de frames de blur (default 5).

    Returns
    -------
    VideoFileClip
        Clip con transición shape morph.
    """
    logger.info(
        "shape_morph_transition — quality=%s duration=%.2f motion_blur=%s",
        quality, duration, motion_blur,
    )
    actual_quality = quality
    try:
        fps = _source_fps(clip_a)
        w, h = clip_a.w, clip_a.h

        frame_a = _get_frame_array(clip_a, clip_a.duration - 0.04)
        frame_b = _get_frame_array(clip_b, 0.04)

        # Segmentar frame_a
        mask_a = _segment_frame(frame_a, quality)
        if mask_a is None:
            logger.warning("shape_morph — segmentación frame_a falló, degradando")
            actual_quality = _degrade_quality(quality)
            mask_a = _segment_frame(frame_a, actual_quality)

        # Segmentar frame_b
        mask_b = _segment_frame(frame_b, quality)
        if mask_b is None:
            logger.warning("shape_morph — segmentación frame_b falló, degradando")
            actual_quality = _degrade_quality(quality)
            mask_b = _segment_frame(frame_b, actual_quality)

        if mask_a is None or mask_b is None:
            logger.warning("shape_morph — segmentación falló completamente, degradando a sweep_mask")
            return sweep_mask_transition(
                clip_a, clip_b,
                shape="circle",
                duration=duration,
                motion_blur=motion_blur,
                n_blur_frames=n_blur_frames,
            )

        logger.info("shape_morph — calidad real usada: %s", actual_quality)

        # Extraer contornos
        contours_a, _ = cv2.findContours(mask_a, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours_b, _ = cv2.findContours(mask_b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours_a or not contours_b:
            logger.warning("shape_morph — sin contornos, degradando a sweep_mask")
            return sweep_mask_transition(
                clip_a, clip_b,
                shape="circle",
                duration=duration,
                motion_blur=motion_blur,
                n_blur_frames=n_blur_frames,
            )

        # Tomar el contorno más grande de cada uno
        c_a = max(contours_a, key=cv2.contourArea)
        c_b = max(contours_b, key=cv2.contourArea)

        # Remuestrear a 64 puntos
        n_pts = 64
        c_a_resampled = _resample_contour(c_a, n_pts)
        c_b_resampled = _resample_contour(c_b, n_pts)

        # Alineación Procrustes
        c_a_aligned, c_b_aligned = _procrustes_align(c_a_resampled, c_b_resampled)

        # Generar N frames intermedios
        N = max(2, int(duration * fps))
        morph_frames = []
        for i in range(N):
            t = i / (N - 1) if N > 1 else 0.5
            eased = _smoothstep(t)

            # Interpolar contorno
            interp_contour = (1 - eased) * c_a_aligned + eased * c_b_aligned

            # Re-escalar al tamaño del frame
            scale_x = w / 2
            scale_y = h / 2
            interp_contour[:, 0] = interp_contour[:, 0] * scale_x + w / 2
            interp_contour[:, 1] = interp_contour[:, 1] * scale_y + h / 2

            # Background: linear blend de frame_a y frame_b
            bg = ((1 - t) * frame_a.astype(np.float32) + t * frame_b.astype(np.float32)).astype(np.uint8)

            # Morph mask: fillPoly con contorno interpolado
            morph_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(morph_mask, [interp_contour.astype(np.int32)], 255)

            # Componer: morph_mask revela frame_b, fondo es bg
            frame_bgr = cv2.cvtColor(frame_b, cv2.COLOR_RGB2BGR)
            bg_bgr = cv2.cvtColor(bg, cv2.COLOR_RGB2BGR)
            composite = np.where(morph_mask[:, :, None] > 0, frame_bgr, bg_bgr)
            composite_rgb = cv2.cvtColor(composite, cv2.COLOR_BGR2RGB)
            morph_frames.append(composite_rgb)

        # Escribir frames morph como video temporal
        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="morph_"))
        morph_path = tmpdir / "morph.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(morph_path), fourcc, fps, (w, h))
        for f in morph_frames:
            writer.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
        writer.release()

        morph_clip = VideoFileClip(str(morph_path))

        if motion_blur and n_blur_frames > 0:
            blur_seq = generate_blur_keyframes(n_blur_frames, base_value=10)
            morph_clip = apply_motion_blur_to_transition(morph_clip, blur_seq)

        before = clip_a.subclipped(0, max(0, clip_a.duration - duration))
        after = clip_b.subclipped(duration, clip_b.duration)
        return concatenate_videoclips([before, morph_clip, after])
    except Exception as exc:
        logger.error("shape_morph_transition falló: %s", exc)
        return sweep_mask_transition(
            clip_a, clip_b,
            shape="circle",
            duration=duration,
            motion_blur=motion_blur,
            n_blur_frames=n_blur_frames,
        )


def _segment_frame(frame: np.ndarray, quality: str) -> np.ndarray | None:
    """
    Segmenta el objeto dominante en un frame usando SAM (singleton) o rembg.

    Usa ``sam_singleton.get_sam_predictor()`` para reutilizar el modelo SAM
    cargado una vez al arrancar el worker, en lugar de instanciarlo en cada
    llamada (ahorro de 3-8s por transición).

    Parámetros
    ----------
    frame : np.ndarray
        Frame de entrada (H, W, 3).
    quality : str
        Calidad del segmentador: ``"fast"``, ``"high"`` o ``"ultra"``.

    Returns
    -------
    np.ndarray | None
        Máscara binaria (H, W) o ``None`` si falla.
    """
    try:
        if quality in ("high", "ultra"):
            # Intentar SAM singleton
            try:
                from .sam_singleton import get_sam_predictor, is_sam_available, get_sam_model_type

                if not is_sam_available():
                    logger.warning(
                        "SAM no disponible (singleton), degradando a rembg"
                    )
                    return None

                predictor = get_sam_predictor()
                if predictor is None:
                    logger.warning("SAM predictor es None, degradando a rembg")
                    return None

                # Verificar que el modelo cargado coincide con la calidad solicitada
                loaded_type = get_sam_model_type()
                if quality == "ultra" and loaded_type != "vit_h":
                    logger.warning(
                        "Se solicitó quality='ultra' pero solo hay %s cargado — "
                        "usando vit_h del singleton igualmente",
                        loaded_type,
                    )

                predictor.set_image(frame)
                # Segmentar con punto central
                h, w = frame.shape[:2]
                masks, _, _ = predictor.predict(
                    point_coords=np.array([[w // 2, h // 2]]),
                    point_labels=np.array([1]),
                    multimask_output=False,
                )
                mask = (masks[0] > 0.5).astype(np.uint8) * 255
                return mask
            except Exception as exc:
                logger.warning("SAM singleton falló: %s", exc)
                return None
        else:
            # rembg fast
            try:
                from rembg import remove
                from PIL import Image

                img_pil = Image.fromarray(frame)
                output = remove(img_pil, alpha_matting=False)
                mask = np.array(output)[:, :, 3]  # canal alpha
                mask = (mask > 128).astype(np.uint8) * 255
                return mask
            except Exception as exc:
                logger.warning("rembg falló: %s", exc)
                return None
    except Exception as exc:
        logger.error("_segment_frame falló: %s", exc)
        return None


def _degrade_quality(quality: str) -> str:
    """
    Degrada la calidad al siguiente nivel en la cadena.

    ``"ultra"`` → ``"high"`` → ``"fast"`` → ``None``

    Parámetros
    ----------
    quality : str
        Calidad actual.

    Returns
    -------
    str
        Calidad degradada.
    """
    chain = {"ultra": "high", "high": "fast", "fast": "fast"}
    return chain.get(quality, "fast")


# ══════════════════════════════════════════════════════════════════════════
# render3d helper — request_3d_render (TAREA 4)
# ══════════════════════════════════════════════════════════════════════════


def _get_render3d_url() -> str:
    """Return the render3d service URL, resolving lazily from config."""
    global _RENDER3D_URL
    if _RENDER3D_URL is None:
        try:
            from config import get_config
            cfg = get_config()
            _RENDER3D_URL = getattr(cfg, "render3d_url", "http://render3d:7890")
        except Exception:
            _RENDER3D_URL = "http://render3d:7890"
    return _RENDER3D_URL


def request_3d_render(
    glb_url: str,
    output_format: str = "png",
    resolution_x: int = 1920,
    resolution_y: int = 1080,
) -> str | None:
    """
    Renderiza un asset 3D (GLB) mediante el servicio render3d.

    Envía una petición POST a ``{render3d_url}/render`` con la URL del GLB.
    Si el render es exitoso, devuelve la ruta local del PNG renderizado.
    Si falla, devuelve ``None`` (degradación suave).

    Parámetros
    ----------
    glb_url : str
        URL del archivo .glb a renderizar.
    output_format : str
        Formato de salida: ``"png"`` (default) o ``"jpg"``.
    resolution_x : int
        Ancho de salida en píxeles (default 1920).
    resolution_y : int
        Alto de salida en píxeles (default 1080).

    Returns
    -------
    str | None
        Ruta local del PNG renderizado, o ``None`` si falla.
    """
    render3d_url = _get_render3d_url()
    logger.info(
        "request_3d_render — POST %s/render glb_url=%s fmt=%s res=%dx%d",
        render3d_url, glb_url, output_format, resolution_x, resolution_y,
    )
    try:
        payload = {
            "glb_url": glb_url,
            "output_format": output_format,
            "resolution_x": resolution_x,
            "resolution_y": resolution_y,
        }
        resp = requests.post(
            f"{render3d_url}/render",
            json=payload,
            timeout=600,  # 10 min max
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ok":
            output_path = data.get("output_path")
            logger.info("request_3d_render — render exitoso: %s", output_path)
            return output_path
        logger.warning("request_3d_render — render3d respondió con error: %s", data)
        return None
    except requests.exceptions.Timeout:
        logger.warning("request_3d_render — render3d timed out after 600s")
        return None
    except Exception as exc:
        logger.warning("request_3d_render — falló: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════
# Redis cache helpers for IconScout (TAREA 5)
# ══════════════════════════════════════════════════════════════════════════

_ICONSCOUT_CACHE_TTL: int = 86400  # 24 hours


def _get_redis_client():
    """Lazy-init and return the global Redis client (or None if unavailable)."""
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    if aioredis is None:
        logger.info("_get_redis_client — redis.asyncio no disponible, usando fallback en memoria")
        return None
    try:
        from config import get_config
        cfg = get_config()
        _REDIS_CLIENT = aioredis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            password=cfg.redis_password or None,
            db=1,  # separate DB for cache
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        logger.info("_get_redis_client — Redis client creado (host=%s, port=%s)", cfg.redis_host, cfg.redis_port)
        return _REDIS_CLIENT
    except Exception as exc:
        logger.warning("_get_redis_client — falló al crear Redis client: %s", exc)
        return None


async def _cache_get_async(key: str) -> str | None:
    """Async get from Redis cache, falling back to in-memory dict."""
    client = _get_redis_client()
    if client is not None:
        try:
            val = await client.get(key)
            if val is not None:
                logger.info("_cache_get_async — Redis cache hit para '%s'", key)
                return val
        except Exception as exc:
            logger.warning("_cache_get_async — Redis get falló: %s", exc)
    # Fallback: in-memory dict
    val = _IN_MEMORY_FALLBACK.get(key)
    if val is not None:
        logger.info("_cache_get_async — in-memory fallback hit para '%s'", key)
    return val


async def _cache_set_async(key: str, value: str, ttl: int = _ICONSCOUT_CACHE_TTL) -> None:
    """Async set to Redis cache, falling back to in-memory dict."""
    client = _get_redis_client()
    if client is not None:
        try:
            await client.setex(key, ttl, value)
            logger.info("_cache_set_async — Redis set para '%s' (TTL=%ds)", key, ttl)
            return
        except Exception as exc:
            logger.warning("_cache_set_async — Redis set falló: %s", exc)
    # Fallback: in-memory dict
    _IN_MEMORY_FALLBACK[key] = value
    logger.info("_cache_set_async — in-memory fallback set para '%s'", key)


# ══════════════════════════════════════════════════════════════════════════
# IconScout helper — fetch_iconscout_asset (TAREA 4 + TAREA 5)
# ══════════════════════════════════════════════════════════════════════════


def fetch_iconscout_asset(
    keyword: str,
    client_id: str = "",
    asset_type: str = "3d",
) -> str | None:
    """
    Busca un asset en IconScout y devuelve la URL del PNG.

    Primero busca en Redis (o fallback en memoria). Si no encuentra,
    hace una petición GET a la API de IconScout con el *keyword* dado.
    Si falla con ``asset_type="3d"``, reintenta con ``asset_type="illustration"``.

    Cuando el asset es de tipo ``"3d"`` y la API devuelve una URL de GLB,
    se invoca ``request_3d_render()`` para obtener un PNG renderizado.
    Si el render 3D falla, se degrada a la URL thumbnail de IconScout.

    Parámetros
    ----------
    keyword : str
        Palabra clave a buscar.
    client_id : str
        Client-ID de IconScout (opcional, se puede pasar por config).
    asset_type : str
        Tipo de asset: ``"3d"`` o ``"illustration"`` (default ``"3d"``).

    Returns
    -------
    str | None
        URL del PNG o ``None`` si no se encuentra.
    """
    cache_key = f"iconscout:{keyword}:{asset_type}"

    # 1. Intentar cache (síncrono: usar in-memory fallback directamente)
    cached = _IN_MEMORY_FALLBACK.get(cache_key)
    if cached is not None:
        logger.info("fetch_iconscout_asset — cache hit (in-memory) para '%s'", cache_key)
        return cached

    logger.info("fetch_iconscout_asset — buscando '%s' tipo=%s", keyword, asset_type)
    try:
        headers = {"Client-ID": client_id} if client_id else {}
        params = {
            "query": keyword,
            "asset_type": asset_type,
            "per_page": 1,
        }
        resp = requests.get(
            "https://api.iconscout.com/v3/search",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("response", {}).get("items", [])
        if items:
            item = items[0]
            # Para 3D: intentar obtener GLB URL y renderizar
            if asset_type == "3d":
                glb_url = item.get("url") or ""
                thumbnail_url = item.get("thumbnail") or ""
                if glb_url and glb_url.endswith(".glb"):
                    logger.info("fetch_iconscout_asset — GLB encontrado, solicitando render 3D")
                    rendered = request_3d_render(glb_url=glb_url)
                    if rendered:
                        _IN_MEMORY_FALLBACK[cache_key] = rendered
                        return rendered
                    logger.warning("fetch_iconscout_asset — render 3D falló, usando thumbnail como fallback")
                # Fallback: usar thumbnail PNG
                if thumbnail_url:
                    _IN_MEMORY_FALLBACK[cache_key] = thumbnail_url
                    return thumbnail_url
            else:
                # Illustration: devolver URL directa
                url = item.get("url") or item.get("thumbnail", "")
                if url:
                    _IN_MEMORY_FALLBACK[cache_key] = url
                    return url

        # Reintentar con illustration si 3d falló
        if asset_type == "3d":
            logger.info("fetch_iconscout_asset — reintentando con illustration")
            return fetch_iconscout_asset(keyword, client_id, asset_type="illustration")

        return None
    except Exception as exc:
        logger.error("fetch_iconscout_asset falló para '%s': %s", keyword, exc)
        return None
