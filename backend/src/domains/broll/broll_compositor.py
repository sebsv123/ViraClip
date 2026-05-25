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

# ── B-roll quality guards ──────────────────────────────────────────────────────
from .broll_config import (
    MIN_OVERLAY_DURATION_S,
    FADE_DURATION_S,
    MIN_GAP_BETWEEN_OVERLAYS_S,
)

MIN_BROLL_DURATION = MIN_OVERLAY_DURATION_S  # skip B-roll clips shorter than canonical minimum
MAX_BROLL_DENSITY = 20.0   # at most 1 B-roll per 20s of clip duration
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

def _find_stable_frame_range(
    video_path: Path,
    sample_interval: float = 0.5,
    motion_threshold: float = 0.15,
) -> Tuple[float, float]:
    """
    Find the first stable frame and last stable frame in a video.
    
    Uses FFmpeg scene detection to find frames with low motion.
    Returns (stable_start, stable_end) in seconds.
    If the entire clip is unstable, returns (0, 0) to signal skip.
    """
    try:
        import subprocess as _sp
        import json as _json
        
        # Use ffmpeg scene detection to find motion changes
        _cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_entries", "format=duration",
            str(video_path),
        ]
        _result = _sp.run(_cmd, capture_output=True, text=True, timeout=10)
        _data = _json.loads(_result.stdout)
        _total_dur = float(_data.get("format", {}).get("duration", 0))
        if _total_dur <= 0:
            return (0.0, _total_dur)
        
        # Sample frames at intervals and check for motion via scene detection
        _cmd2 = [
            "ffmpeg", "-v", "quiet", "-i", str(video_path),
            "-filter:v", f"select='gt(scene,{motion_threshold})',showinfo",
            "-f", "null", "-",
        ]
        _result2 = _sp.run(_cmd2, capture_output=True, text=True, timeout=30)
        _output = _result2.stderr
        
        # Parse scene change timestamps
        _scene_changes = []
        import re as _re
        for _line in _output.splitlines():
            _m = _re.search(r"pts_time:([0-9.]+)", _line)
            if _m:
                _scene_changes.append(float(_m.group(1)))
        
        if not _scene_changes:
            # No significant motion — entire clip is stable
            return (0.0, _total_dur)
        
        # First stable frame: after the first scene change + 0.3s buffer
        _stable_start = _scene_changes[0] + 0.3 if _scene_changes[0] < _total_dur * 0.3 else 0.0
        
        # Last stable frame: before the last scene change - 0.3s buffer
        _stable_end = _scene_changes[-1] - 0.3 if _scene_changes[-1] > _total_dur * 0.7 else _total_dur
        
        # If the stable window is too small (< 1s), the clip is too unstable
        if _stable_end - _stable_start < 1.0:
            logger.warning(
                "[BrollCompositor] B-roll too unstable: %s (stable window=%.1fs)",
                video_path.name, _stable_end - _stable_start,
            )
            return (0.0, 0.0)
        
        logger.debug(
            "[BrollCompositor] Stable frame range: %.1f-%.1fs (total=%.1fs, changes=%d)",
            _stable_start, _stable_end, _total_dur, len(_scene_changes),
        )
        return (_stable_start, _stable_end)
        
    except Exception as _e:
        logger.debug("[BrollCompositor] Frame stability check failed: %s", _e)
        return (0.0, probe_duration(video_path))


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
      - Frame stability check: skips unstable start/end frames

    Works for both video files and static images (image → looped video).
    Returns the output Path on success, None on failure.
    """
    broll_path = Path(broll_path)
    is_image = broll_path.suffix.lower() in _IMAGE_EXTS
    
    # Skip B-roll clips shorter than MIN_BROLL_DURATION
    if not is_image:
        actual_dur = probe_duration(broll_path)
        if actual_dur < MIN_BROLL_DURATION:
            logger.warning(
                "[BrollCompositor] Skipping B-roll shorter than %.1fs: %s (%.1fs)",
                MIN_BROLL_DURATION, broll_path.name, actual_dur,
            )
            return None
        
        # Frame stability check: find stable start/end
        _stable_start, _stable_end = _find_stable_frame_range(broll_path)
        if _stable_end <= _stable_start:
            logger.warning(
                "[BrollCompositor] Skipping unstable B-roll: %s",
                broll_path.name,
            )
            return None

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
        # If the requested duration exceeds the asset's actual duration, loop it
        # seamlessly with -stream_loop -1 so FFmpeg never runs out of frames.
        loop_flag: list[str] = []
        if duration > actual_dur:
            loop_flag = ["-stream_loop", "-1"]
            logger.info(
                "[BrollCompositor] Looping B-roll %s (dur=%.1fs) to cover requested %.1fs",
                broll_path.name, actual_dur, duration,
            )
        cmd = [
            _get_ffmpeg_exe(), "-y",
            "-hwaccel", "none",
            *loop_flag,
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

    # ── Select transition effect based on asset index for variety ──────────────
    # Cycles through: fade, slide_left, slide_right, zoom_in, ken_burns
    # Uses hash of broll_path to get deterministic variety per asset.
    _effect_idx = abs(hash(str(broll_path))) % 5
    _effects = ["fade", "slide_left", "slide_right", "zoom_in", "ken_burns"]
    _effect = _effects[_effect_idx]
    
    # CPU overlay pipeline: fade on CPU → overlay → yuv420p
    # Avoids hwupload_cuda/overlay_cuda/hwdownload which can fail with
    # incompatible hwframe formats from ComfyUI LTX outputs.
    if _effect == "fade":
        _broll_prep = (
            f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB,"
            f"fade=t=in:st={timestamp:.3f}:d={fade_in_d:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1,"
            f"format=yuva420p[bv_faded]"
        )
    elif _effect == "slide_left":
        _slide_dur = min(fade * 2, duration * 0.3)
        _broll_prep = (
            f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB,"
            f"fade=t=in:st={timestamp:.3f}:d={fade_in_d:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1,"
            f"crop=iw*min(1,(t-{timestamp:.3f})/{_slide_dur:.3f}):ih:0:0,"
            f"format=yuva420p[bv_faded]"
        )
    elif _effect == "slide_right":
        _slide_dur = min(fade * 2, duration * 0.3)
        _broll_prep = (
            f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB,"
            f"fade=t=in:st={timestamp:.3f}:d={fade_in_d:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1,"
            f"crop=iw*min(1,(t-{timestamp:.3f})/{_slide_dur:.3f}):ih:iw-iw*min(1,(t-{timestamp:.3f})/{_slide_dur:.3f}):0,"
            f"format=yuva420p[bv_faded]"
        )
    elif _effect == "zoom_in":
        _zoom_dur = min(fade * 2, duration * 0.3)
        _broll_prep = (
            f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB,"
            f"fade=t=in:st={timestamp:.3f}:d={fade_in_d:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1,"
            f"scale=iw*1.15:ih*1.15:eval=frame,"
            f"crop=iw/1.15:ih/1.15:(iw-iw/1.15)*0.5:(ih-ih/1.15)*0.5,"
            f"format=yuva420p[bv_faded]"
        )
    elif _effect == "ken_burns":
        _broll_prep = (
            f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB,"
            f"fade=t=in:st={timestamp:.3f}:d={fade_in_d:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1,"
            f"scale=iw*1.04:ih*1.04:eval=frame,"
            f"crop=iw/1.04:ih/1.04:"
            f"(iw-iw/1.04)*0.5*(t-{timestamp:.3f})/{duration:.3f}:"
            f"(ih-ih/1.04)*0.5*(t-{timestamp:.3f})/{duration:.3f},"
            f"format=yuva420p[bv_faded]"
        )
    
    # ── Color matching: apply eq to match B-roll brightness/contrast to main clip ──
    # Uses a subtle normalization to prevent jarring color shifts between sources.
    # The eq values are fixed (not probed per-clip) to avoid extra ffprobe calls.
    _color_match = "eq=saturation=0.95:brightness=0.01:contrast=1.02,"
    
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

    # ── Overlap check: ensure no two B-rolls overlap in time ────────────────
    # Sort by timestamp, then skip any cue that overlaps with the previous one.
    # Also enforce minimum 0.5s gap between end of one and start of next.
    # If two cues are closer than 0.5s, merge or drop the shorter one.
    valid_pairs.sort(key=lambda x: x[0])  # sort by timestamp
    _MIN_GAP = 0.5
    _filtered_pairs = []
    _last_end = -999.0
    for ts, np_, dur in valid_pairs:
        cue_end = ts + dur
        # Check overlap with previous cue
        if ts < _last_end:
            logger.warning(
                "[BrollGate] DROPPED ts=%.1f dur=%.1f reason=overlap_with_previous_ending_at_%.1f",
                ts, dur, _last_end,
            )
            continue
        # Check minimum gap — if closer than 0.5s, merge or drop the shorter one
        _gap = ts - _last_end
        if _gap < _MIN_GAP and _last_end > 0:
            # Try to merge: extend previous cue's end to this cue's end
            if _filtered_pairs:
                _prev_ts, _prev_np, _prev_dur = _filtered_pairs[-1]
                _merged_dur = (ts + dur) - _prev_ts
                logger.warning(
                    "[BrollGate] MERGED ts=%.1f dur=%.1f into previous cue at ts=%.1f "
                    "(gap=%.1fs < min %.1fs) — new duration=%.1fs",
                    ts, dur, _prev_ts, _gap, _MIN_GAP, _merged_dur,
                )
                _filtered_pairs[-1] = (_prev_ts, _prev_np, _merged_dur)
                _last_end = _prev_ts + _merged_dur
                continue
        _filtered_pairs.append((ts, np_, dur))
        _last_end = cue_end
    valid_pairs = _filtered_pairs

    if not valid_pairs:
        logger.warning("[BrollCompositor] compose_overlay_multi: all B-rolls filtered by overlap check")
        return False

    inputs: list[str] = ["-i", str(main_path)]
    for _, np_, _ in valid_pairs:
        inputs += ["-i", str(np_)]

    # ── Enforce minimum 4s duration for fade in/out to work ────────────────
    _FADE_DUR = 0.4  # fixed 0.4s fade in and fade out
    _MIN_BROLL_DUR = 4.0  # minimum 4s to allow 0.4s fade in + content + 0.4s fade out
    _filtered_pairs = []
    for ts, np_, dur in valid_pairs:
        if dur < _MIN_BROLL_DUR:
            logger.info(
                "[BROLL] Skipped b-roll at t=%.1fs (dur=%.1fs < min %.1fs for fade in/out)",
                ts, dur, _MIN_BROLL_DUR,
            )
            continue
        _filtered_pairs.append((ts, np_, dur))
    valid_pairs = _filtered_pairs

    if not valid_pairs:
        logger.warning("[BrollCompositor] compose_overlay_multi: all B-rolls too short for fade in/out")
        return False

    # ── Crossfade transition between consecutive B-roll overlays ──
    # When two overlays are close together (gap < 1.0s), use a soft
    # crossfade instead of separate fade-out/fade-in. This creates a
    # smooth visual flow between related scenes.
    # The crossfade works by extending the first overlay's enable window
    # slightly into the second overlay's start, and fading the first out
    # while the second fades in.
    _XFADE_DUR = 0.3  # 0.3s crossfade — subtle and clean
    filter_parts: list[str] = []
    prev = "0:v"
    for idx, (ts, _, dur) in enumerate(valid_pairs):
        end_ts = ts + dur
        out_tag = f"vout{idx}"
        fade_out_st = dur - _FADE_DUR

        # Check if this overlay is close to the next one
        _next_ts = valid_pairs[idx + 1][0] if idx + 1 < len(valid_pairs) else None
        _gap_to_next = _next_ts - end_ts if _next_ts is not None else None
        _use_crossfade = _gap_to_next is not None and 0 < _gap_to_next < 1.0

        if _use_crossfade:
            # Crossfade: extend this overlay's end into the next overlay's start
            # by _XFADE_DUR seconds. The fade-out starts earlier so it overlaps
            # with the next overlay's fade-in.
            _cross_end = end_ts + _XFADE_DUR
            _cross_fade_out_st = dur - _XFADE_DUR  # start fading out earlier
            logger.info(
                "[BROLL] Crossfade: overlay %d→%d (gap=%.2fs, xfade=%.1fs)",
                idx, idx + 1, _gap_to_next, _XFADE_DUR,
            )
            filter_parts.append(
                f"[{idx + 1}:v]setpts=PTS-STARTPTS+{ts:.3f}/TB,"
                f"format=rgba,"
                f"fade=t=in:st=0:d={_FADE_DUR:.3f}:alpha=1,"
                f"fade=t=out:st={_cross_fade_out_st:.3f}:d={_XFADE_DUR:.3f}:alpha=1,"
                f"format=yuva420p[bv{idx}_faded]"
            )
            filter_parts.append(
                f"[{prev}][bv{idx}_faded]"
                f"overlay="
                f"enable='between(t,{ts:.3f},{_cross_end:.3f})':"
                f"eof_action=endall:"
                f"x=0:y=0:format=auto"
                f"[{out_tag}]"
            )
        else:
            # Standard fade in/out (no crossfade)
            logger.info(
                "[BROLL] Fade applied: in=%.1fs out=%.1fs duration=%.1fs",
                _FADE_DUR, _FADE_DUR, dur,
            )
            filter_parts.append(
                f"[{idx + 1}:v]setpts=PTS-STARTPTS+{ts:.3f}/TB,"
                f"format=rgba,"
                f"fade=t=in:st=0:d={_FADE_DUR:.3f}:alpha=1,"
                f"fade=t=out:st={fade_out_st:.3f}:d={_FADE_DUR:.3f}:alpha=1,"
                f"format=yuva420p[bv{idx}_faded]"
            )
            filter_parts.append(
                f"[{prev}][bv{idx}_faded]"
                f"overlay="
                f"enable='between(t,{ts:.3f},{end_ts:.3f})':"
                f"eof_action=endall:"
                f"x=0:y=0:format=auto"
                f"[{out_tag}]"
            )
        prev = out_tag

    filter_complex = ";".join(filter_parts)
    
    # ── Validate filtergraph before execution ────────────────────────────────
    # Log the full filtergraph string so invalid syntax can be debugged.
    # If the filtergraph is empty or malformed, raise immediately.
    if not filter_complex or len(filter_complex) < 10:
        error_msg = f"[BrollCompositor] Invalid filtergraph (empty or too short): {filter_complex[:200]}"
        logger.error(error_msg)
        raise ValueError(error_msg)

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
