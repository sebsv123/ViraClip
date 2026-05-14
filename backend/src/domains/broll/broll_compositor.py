"""
B-Roll Compositor — Format-Adaptive Overlay Engine con Efectos Inteligentes

Single source of truth for all B-roll compositing in ViraClip.
Integra sistema de efectos variados para evitar repetición.

Supported output formats (auto-probed from main clip):
  9:16  portrait  — 1080×1920, 720×1280
  1:1   square    — 1080×1080
  16:9  landscape — 1920×1080  (rare, kept for completeness)

Efectos inteligentes:
  - 13 tipos de efectos diferentes (Ken Burns, Pan, Rotate, Pulse, etc.)
  - Selección automática basada en contexto
  - Rotación para evitar repetición
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
sys.path.insert(0, "/app/src") if "/app/src" not in sys.path else None
from src import gpu_utils
try:
    from gpu_utils import ffmpeg_codec_flags as _gpu_codec
except ImportError:
    def _gpu_codec(quality="high"):
        return gpu_utils.ffmpeg_codec_flags(quality)
import tempfile
from pathlib import Path
from typing import Optional, Tuple


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


logger = logging.getLogger(__name__)

# Importar motor de efectos inteligentes
try:
    from .broll_effects_engine import get_smart_broll_effect, build_broll_effect_filter
    SMART_EFFECTS_AVAILABLE = True
except ImportError:
    SMART_EFFECTS_AVAILABLE = False
    logger.warning("Smart effects engine not available, using classic Ken Burns")

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_FFPROBE_TIMEOUT = 15   # seconds
_FFMPEG_TIMEOUT  = 300  # seconds per overlay


# ── Dimension probing ─────────────────────────────────────────────────────────

def probe_dimensions(video_path: Path | str) -> Tuple[int, int, float]:
    """
    Return (width, height, fps) of *video_path* using ffprobe.
    Falls back to (1080, 1920, 30.0) if probing fails.
    """
    try:
        cmd = [
            _get_ffmpeg_exe(), "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT)
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = int(stream.get("width", 1080))
                h = int(stream.get("height", 1920))
                # fps expressed as "30/1" or "30000/1001"
                fps_str = stream.get("r_frame_rate", "30/1")
                try:
                    num, den = fps_str.split("/")
                    fps = round(float(num) / float(den), 3)
                except Exception:
                    fps = 30.0
                return w, h, fps
    except Exception as exc:
        logger.debug("[BrollCompositor] probe_dimensions failed for %s: %s", video_path, exc)
    return 1080, 1920, 30.0


def probe_duration(video_path: Path | str) -> float:
    """Return duration in seconds. Falls back to 30.0."""
    try:
        cmd = [
            _get_ffmpeg_exe(), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT)
        return float(result.stdout.strip())
    except Exception:
        return 30.0


def _build_overlay_alpha_expr(ts: float, end_ts: float, fade: float) -> str:
    """
    Build FFmpeg alpha expression for dissolve in/out around [ts, end_ts].
    Uses plain commas (no backslashes) — FFmpeg accepts them inside if().
    """
    safe_fade = max(0.05, float(fade))
    if (end_ts - ts) < (safe_fade * 2):
        safe_fade = max(0.05, (end_ts - ts) / 2.0)
    return (
        f"if(lt(t,{ts + safe_fade:.3f})"
        f",(t-{ts:.3f})/{safe_fade:.3f}"
        f",if(lt(t,{end_ts - safe_fade:.3f})"
        f",1"
        f",if(lt(t,{end_ts:.3f})"
        f",({end_ts:.3f}-t)/{safe_fade:.3f}"
        f",0)))"
    )


# ── B-roll normalisation ──────────────────────────────────────────────────────

def normalize_broll(
    broll_path: Path | str,
    target_w: int,
    target_h: int,
    duration: float,
    fade: float = 0.6,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Produce a normalised B-roll clip:
      - Scaled and center-cropped to target_w × target_h
      - Trimmed to *duration* seconds
      - Fade-in and fade-out of *fade* seconds (default 0.6s for smooth transitions)
      - Audio muted (B-roll is silent by design)
      - Ken Burns effect for static images (subtle zoom + pan)

    Works for both video files and static images (image → looped video).
    Returns the output Path on success, None on failure.
    """
    broll_path = Path(broll_path)
    is_image = broll_path.suffix.lower() in _IMAGE_EXTS

    if output_path is None:
        suffix = ".mp4"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False,
                                          dir=broll_path.parent)
        output_path = Path(tmp.name)
        tmp.close()

    fade_out_start = max(0.0, duration - fade)

    # Sistema de efectos inteligentes - varía automáticamente
    if is_image and SMART_EFFECTS_AVAILABLE:
        # Seleccionar efecto inteligente
        effect_type = get_smart_broll_effect(is_image=True, context=None)
        effect_filter = build_broll_effect_filter(
            effect_type=effect_type,
            width=target_w,
            height=target_h,
            duration=duration,
            fps=30
        )
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1,"
            f"{effect_filter}"
        )
        logger.info(f"🎨 B-roll effect applied: {effect_type.value}")
    elif is_image:
        # Fallback: Ken Burns clásico sin fade negro
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1,"
            f"zoompan=z='min(zoom+0.0008,1.08)':d={int(duration*30)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={target_w}x{target_h}"
        )
    else:
        # Videos: sin fade negro, imagen limpia
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1"
        )

    if is_image:
        cmd = [
            _get_ffmpeg_exe(), "-y",
            "-loop", "1", "-i", str(broll_path),
            "-t", str(duration),
            "-vf", vf,
            "-an",
            *_gpu_codec("medium"),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        # CPU decode for video inputs (ComfyUI LTX outputs use nv12/cuda hwframes
        # that break hwdownload→yuv420p. Force software decode with -hwaccel none.)
        cmd = [
            _get_ffmpeg_exe(), "-y",
            "-hwaccel", "none",
            "-i", str(broll_path),
            "-t", str(duration),
            "-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1",
            "-pix_fmt", "yuv420p",
            *gpu_utils.ffmpeg_codec_flags("high"),
            "-an",
            "-movflags", "+faststart",
            str(output_path),
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
        if result.returncode != 0:
            stderr_text = result.stderr.decode()
            # Retry with libx264 on ANY encoder error (nvenc, hwaccel, codec init, etc.)
            _encoder_keywords = ("nvenc", "CUDA_ERROR", "cuInit", "Error initializing output stream",
                                 "Error while opening encoder", "encoder setup failed")
            if any(k in stderr_text for k in _encoder_keywords):
                try:
                    from gpu_utils import clear_nvenc_cache
                    clear_nvenc_cache()
                except Exception:
                    pass
                logger.warning("[BrollCompositor] encoder failed, retrying with libx264 (%s…)",
                               stderr_text[:120])
                cpu_cmd: list = []
                i = 0
                while i < len(cmd):
                    if cmd[i] == "-c:v" and i + 1 < len(cmd) and "nvenc" in cmd[i + 1]:
                        cpu_cmd += gpu_utils.ffmpeg_codec_flags("medium")
                        i += 2
                        while i < len(cmd) and cmd[i] in ("-preset", "-rc", "-cq", "-qp", "-b:v"):
                            i += 2
                    else:
                        cpu_cmd.append(cmd[i])
                        i += 1
                result = subprocess.run(cpu_cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
            if result.returncode != 0:
                logger.error("[BrollCompositor] normalize_broll failed (retcode=%d): %s",
                             result.returncode, result.stderr.decode()[-400:])
                output_path.unlink(missing_ok=True)
                return None
        if not output_path.exists() or output_path.stat().st_size < 1000:
            output_path.unlink(missing_ok=True)
            return None
        return output_path
    except subprocess.TimeoutExpired:
        logger.error("[BrollCompositor] normalize_broll timed out")
        output_path.unlink(missing_ok=True)
        return None
    except Exception as exc:
        logger.error("[BrollCompositor] normalize_broll exception: %s", exc)
        output_path.unlink(missing_ok=True)
        return None


# ── Single overlay composition ────────────────────────────────────────────────

def compose_overlay(
    main_path: Path | str,
    broll_path: Path | str,
    output_path: Path | str,
    timestamp: float,
    duration: float = 4.5,
    fade: float = 0.6,
    transition_type: str = "dissolve",
    lut_vf: str = "",
) -> bool:
    """
    Overlay *broll_path* on *main_path* starting at *timestamp* for *duration* seconds.

    Steps:
      1. Probe main clip dimensions
      2. Normalise B-roll to those exact dimensions
      3. Apply same LUT grade to B-roll (if provided) for visual consistency
      4. Composite with FFmpeg overlay filter

    Returns True on success.
    """
    main_path   = Path(main_path)
    broll_path  = Path(broll_path)
    output_path = Path(output_path)

    w, h, _fps = probe_dimensions(main_path)

    # Normalise B-roll — sin fade negro para no oscurecer la imagen
    norm_path = normalize_broll(broll_path, w, h, duration=duration, fade=fade)
    if norm_path is None:
        logger.error("[BrollCompositor] compose_overlay: normalise step failed")
        return False

    end_ts = timestamp + duration
    fade_in_d  = min(fade, (end_ts - timestamp) / 2)
    fade_out_d = min(fade, (end_ts - timestamp) / 2)
    fade_out_st = end_ts - fade_out_d

    # CPU overlay pipeline: fade on CPU → overlay → yuv420p
    # Avoids hwupload_cuda/overlay_cuda/hwdownload which can fail with
    # incompatible hwframe formats from ComfyUI LTX outputs.
    _broll_prep = (
        f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB,"
        f"fade=t=in:st={timestamp:.3f}:d={fade_in_d:.3f}:alpha=1,"
        f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1,"
        f"format=yuva420p[bv_faded]"
    )
    filter_complex = (
        f"{_broll_prep};"
        f"[0:v][bv_faded]overlay="
        f"enable='between(t,{timestamp:.3f},{end_ts:.3f})':"
        f"x=0:y=0:format=auto,"
        f"format=yuv420p[out]"
    )

    cmd = [
        _get_ffmpeg_exe(), "-y",
        "-i", str(main_path),
        "-i", str(norm_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        *_gpu_codec("high"),
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
        norm_path.unlink(missing_ok=True)
        if result.returncode != 0:
            logger.error("[BrollCompositor] compose_overlay FFmpeg failed: %s",
                         result.stderr.decode()[-400:])
            return False
        return output_path.exists() and output_path.stat().st_size > 0
    except subprocess.TimeoutExpired:
        logger.error("[BrollCompositor] compose_overlay timed out")
        norm_path.unlink(missing_ok=True)
        return False
    except Exception as exc:
        logger.error("[BrollCompositor] compose_overlay exception: %s", exc)
        norm_path.unlink(missing_ok=True)
        return False


# ── Editable items overlay composition ─────────────────────────────────────────

async def compose_overlay_items(
    main_path: Path | str,
    items: list,  # [{id, video_url/path, start_time, duration, position, opacity, scale}, ...]
    output_path: Path | str,
    fade: float = 0.6,
    transition_type: str = "dissolve",
) -> bool:
    """Apply multiple B-roll overlays from editable items.

    *items* is a list of dicts with:
      - video_url/path: path or URL to B-roll video
      - start_time: timestamp in seconds to place overlay
      - duration: how long to show
      - position: "fullscreen" | "corner" | "split"
      - opacity: 0.0-1.0
      - scale: 0.0-2.0

    Returns True on success.
    """
    if not items:
        return False

    main_path = Path(main_path)
    output_path = Path(output_path)

    w, h, _fps = probe_dimensions(main_path)

    # Build broll_pairs with position info
    broll_pairs = []
    for item in items:
        path = item.get("video_url") or item.get("path") or item.get("broll_path")
        if not path:
            continue
        broll_pairs.append({
            "timestamp": item.get("start_time", 0),
            "path": path,
            "duration": item.get("duration", 3.0),
            "position": item.get("position", "fullscreen"),
            "opacity": item.get("opacity", 1.0),
            "scale": item.get("scale", 1.0),
            "x": item.get("x", 0),
            "y": item.get("y", 0),
        })

    if not broll_pairs:
        return False

    # Import here to avoid circular imports
    from .multi_compositor import compose_multi_with_positions
    return await compose_multi_with_positions(
        main_path, broll_pairs, output_path, fade, transition_type, w, h
    )


# ── Async multi-overlay (used by video_effects.py) ────────────────────────────

async def compose_overlay_multi(
    main_path: Path | str,
    broll_pairs: list,          # [(timestamp, broll_path, duration), ...]
    output_path: Path | str,
    fade: float = 0.6,
    transition_type: str = "dissolve",
) -> bool:
    """
    Apply multiple B-roll overlays in a single FFmpeg pass.

    *broll_pairs* is a list of (timestamp_s, broll_path, duration_s).
    Probes main clip dimensions once, normalises each B-roll, then
    chains overlays in one filter_complex.

    Returns True on success.
    """
    if not broll_pairs:
        return False

    main_path   = Path(main_path)
    output_path = Path(output_path)

    w, h, _fps = probe_dimensions(main_path)

    # Normalise all B-rolls in parallel with semaphore (max 3 concurrent FFmpeg processes)
    _NORMALIZE_SEM = asyncio.Semaphore(3)
    async def _normalize_with_sem(bp, dur):
        async with _NORMALIZE_SEM:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: normalize_broll(Path(bp), w, h, duration=dur, fade=fade)
            )

    norm_tasks = [
        _normalize_with_sem(bp, dur) for ts, bp, dur in broll_pairs
    ]
    norm_results = await asyncio.gather(*norm_tasks, return_exceptions=True)
    norm_paths: list[Path] = []
    valid_pairs: list[tuple] = []
    for i, (ts, bp, dur) in enumerate(broll_pairs):
        result = norm_results[i]
        if isinstance(result, Exception) or result is None:
            logger.warning(f"[BrollCompositor] normalize failed for {bp}: {result}")
            continue
        norm_paths.append(result)
        valid_pairs.append((ts, result, dur))

    if not valid_pairs:
        logger.warning("[BrollCompositor] compose_overlay_multi: no valid B-rolls after normalise")
        return False

    inputs: list[str] = ["-i", str(main_path)]
    for _, np_, _ in valid_pairs:
        inputs += ["-i", str(np_)]

    filter_parts: list[str] = []
    prev = "0:v"
    for idx, (ts, _, dur) in enumerate(valid_pairs):
        end_ts = ts + dur
        out_tag = f"vout{idx}"
        fade_in_d  = min(fade, dur / 2)
        fade_out_d = min(fade, dur / 2)
        fade_out_st = end_ts - fade_out_d
        # CPU fade on B-roll stream before overlay (avoids broken alpha= expression)
        filter_parts.append(
            f"[{idx + 1}:v]setpts=PTS-STARTPTS+{ts:.3f}/TB,"
            f"fade=t=in:st={ts:.3f}:d={fade_in_d:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1,"
            f"format=yuva420p[bv{idx}_faded]"
        )
        filter_parts.append(
            f"[{prev}][bv{idx}_faded]"
            f"overlay="
            f"enable='between(t,{ts:.3f},{end_ts:.3f})':"
            f"x=0:y=0:format=auto"
            f"[{out_tag}]"
        )
        prev = out_tag

    filter_complex = ";".join(filter_parts)

    cmd = [
        _get_ffmpeg_exe(), "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{prev}]",
        "-map", "0:a?",
        *_gpu_codec("high"),
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    async def _run_cmd(run_cmd: list) -> tuple:
        p = await asyncio.create_subprocess_exec(
            *run_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(p.communicate(), timeout=_FFMPEG_TIMEOUT)
        return p.returncode, err

    try:
        rc, _err = await _run_cmd(cmd)
        if rc != 0:
            err_text = _err.decode()
            if any(k in err_text for k in ("nvenc", "CUDA_ERROR", "cuInit")):
                try:
                    from gpu_utils import clear_nvenc_cache
                    clear_nvenc_cache()
                except Exception:
                    pass
                logger.warning("[BrollCompositor] nvenc failed in multi-overlay, retrying with libx264")
                cpu_cmd: list = []
                j = 0
                while j < len(cmd):
                    if cmd[j] == "-c:v" and j + 1 < len(cmd) and "nvenc" in cmd[j + 1]:
                        cpu_cmd += gpu_utils.ffmpeg_codec_flags("high")
                        j += 2
                        while j < len(cmd) and cmd[j] in ("-preset", "-rc", "-cq", "-qp", "-b:v"):
                            j += 2
                    else:
                        cpu_cmd.append(cmd[j])
                        j += 1
                rc, _err = await _run_cmd(cpu_cmd)
        for np_ in norm_paths:
            np_.unlink(missing_ok=True)
        if rc != 0:
            logger.error("[BrollCompositor] compose_overlay_multi failed: %s",
                         _err.decode()[-400:])
            return False
        return output_path.exists() and output_path.stat().st_size > 0
    except (asyncio.TimeoutError, Exception) as exc:
        logger.error("[BrollCompositor] compose_overlay_multi exception: %s", exc)
        for np_ in norm_paths:
            np_.unlink(missing_ok=True)
        return False
