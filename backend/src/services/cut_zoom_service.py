"""
Cut Zoom Service — Apply zoom transitions at jump cut points.

Integrates with jump_cut_service to add dynamic zoom punches at each cut,
creating Alex Hormozi / MrBeast style aggressive viral editing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import subprocess

from .vpi_gpu_runtime import select_ffmpeg_video_encoder


def _get_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# Note: imageio_ffmpeg only bundles ffmpeg, not ffprobe
# We use ffmpeg to probe video properties instead


logger = logging.getLogger(__name__)

# Zoom parameters
DEFAULT_ZOOM_FACTOR = 1.06      # 6% zoom
DEFAULT_ZOOM_DURATION = 0.5     # seconds per zoom
DEFAULT_EASING = "ease_in_out"  # zoom easing


def _ffprobe_video_ok(path: str) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return False
        values = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        if len(values) < 2:
            return False
        duration = float(values[0])
        size = int(float(values[1]))
        return duration > 0.05 and size > 0
    except Exception:
        return False


def _probe_video_meta(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists() or p.stat().st_size <= 0:
        return {}
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(p),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout or "{}")
    except Exception:
        return {}
    streams = list(data.get("streams") or [])
    fmt = data.get("format") or {}
    vstream = next((s for s in streams if str(s.get("codec_type")) == "video"), {})
    has_audio = any(str(s.get("codec_type")) == "audio" for s in streams)
    try:
        width = int(vstream.get("width") or 0)
        height = int(vstream.get("height") or 0)
    except Exception:
        width = height = 0
    try:
        duration = float(fmt.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    return {
        "width": width,
        "height": height,
        "duration": duration,
        "has_audio": has_audio,
        "size": int(p.stat().st_size),
    }


def _even(value: int, minimum: int = 2) -> int:
    value = max(minimum, int(value or 0))
    if value % 2:
        value -= 1
    return max(minimum, value)


def _build_ffmpeg_cmd(
    *,
    input_path: str,
    output_path: str,
    vf: str | None,
    width: int,
    height: int,
    has_audio: bool,
    encoder_info: Optional[Dict[str, Any]] = None,
    copy_video: bool = False,
) -> List[str]:
    cmd = [
        _get_ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]
    if copy_video:
        cmd += ["-c:v", "copy", "-c:a", "copy"]
    else:
        encoder = str((encoder_info or {}).get("encoder") or "libx264")
        preset = str((encoder_info or {}).get("preset") or "fast")
        extra_args = list((encoder_info or {}).get("extra_args") or [])
        cmd += ["-vf", vf or "", "-c:v", encoder, "-pix_fmt", "yuv420p", "-preset", preset, *extra_args]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        else:
            cmd += ["-an"]
    cmd += ["-movflags", "+faststart", "-shortest", output_path]
    return cmd


async def _run_ffmpeg(cmd: List[str], timeout: int = 300) -> Tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0, ((stdout or b"") + b"\n" + (stderr or b"")).decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await proc.communicate()
        except Exception:
            pass
        return False, "timeout"


def _output_is_valid(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0 and _ffprobe_video_ok(str(path))


def _validate_zoom_inputs(
    video_path: str,
    cut_points: List[float],
    zoom_duration: float,
) -> Tuple[bool, str, Dict[str, Any]]:
    meta = _probe_video_meta(video_path)
    if not Path(video_path).exists():
        return False, "input_missing", meta
    if Path(video_path).stat().st_size <= 0:
        return False, "input_empty", meta
    if not cut_points:
        return False, "no_cut_points", meta
    duration = float(meta.get("duration") or 0.0)
    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    if duration < 0.5:
        return False, f"duration_too_short:{duration:.3f}", meta
    if zoom_duration <= 0:
        return False, f"invalid_zoom_duration:{zoom_duration}", meta
    if width <= 0 or height <= 0:
        return False, "invalid_dimensions", meta
    if width % 2 or height % 2:
        meta["width"] = _even(width)
        meta["height"] = _even(height)
        meta["dimensions_evened"] = True
    valid_points = [float(t) for t in cut_points if isinstance(t, (int, float)) and float(t) >= 0.0 and float(t) <= duration + 0.5]
    if not valid_points:
        return False, "no_valid_cut_points", meta
    meta["valid_cut_points"] = valid_points
    return True, "", meta


async def _render_with_fallbacks(
    *,
    input_path: str,
    output_path: str,
    meta: Dict[str, Any],
    zoom_factor: float,
    zoom_interval: Tuple[float, float],
) -> Tuple[bool, str]:
    tmp_output = Path(output_path).with_suffix(".tmp.mp4")
    tmp_output.unlink(missing_ok=True)
    Path(output_path).unlink(missing_ok=True)
    width = _even(int(meta.get("width") or 1080))
    height = _even(int(meta.get("height") or 1920))
    has_audio = bool(meta.get("has_audio"))
    fps = max(1.0, float(meta.get("fps") or 30.0))
    start, end = zoom_interval
    prefer_nvenc = os.environ.get("VIRACLIP_ENABLE_NVENC", "false").strip().lower() in {"1", "true", "yes", "on"}
    nvenc_failed = False

    attempts: List[Tuple[str, List[str]]] = []
    zoom_expr = f"if(between(on/{fps:.3f},{start:.3f},{end:.3f}),{zoom_factor},1)"
    zoompan_filter = (
        f"zoompan="
        f"zoom='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d=1:"
        f"s={width}x{height}:"
        f"fps={int(fps)}"
    )
    attempts.append(
        ("zoom", _build_ffmpeg_cmd(
            input_path=input_path,
            output_path=str(tmp_output),
            vf=zoompan_filter,
            width=width,
            height=height,
            has_audio=has_audio,
            copy_video=False,
        ))
    )
    attempts.append(
        ("safe_center_crop", _build_ffmpeg_cmd(
            input_path=input_path,
            output_path=str(tmp_output),
            vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            width=1080,
            height=1920,
            has_audio=has_audio,
            copy_video=False,
        ))
    )
    attempts.append(
        ("safe_scale_pad", _build_ffmpeg_cmd(
            input_path=input_path,
            output_path=str(tmp_output),
            vf="scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            width=1080,
            height=1920,
            has_audio=has_audio,
            copy_video=False,
        ))
    )
    if width == 1080 and height == 1920 and meta.get("size", 0) > 0:
        attempts.append(
            ("emergency_copy", _build_ffmpeg_cmd(
                input_path=input_path,
                output_path=str(tmp_output),
                vf=None,
                width=width,
                height=height,
                has_audio=has_audio,
                copy_video=True,
            ))
        )

    for label, cmd in attempts:
        if label == "emergency_copy":
            encoder_info = {"encoder": "copy", "preset": "", "extra_args": [], "nvenc_used": False, "reason": "copy_passthrough"}
        else:
            encoder_info = select_ffmpeg_video_encoder(
                stage="rhythm",
                quality="high",
                prefer_nvenc=prefer_nvenc and not nvenc_failed,
            )
            cmd = _build_ffmpeg_cmd(
                input_path=input_path,
                output_path=str(tmp_output),
                vf=cmd[cmd.index("-vf") + 1] if "-vf" in cmd else None,
                width=width,
                height=height,
                has_audio=has_audio,
                encoder_info=encoder_info,
                copy_video=False,
            )
        logger.info("CUT_ZOOM_FFMPEG_CMD_SAFE label=%s cmd=%s", label, shlex.join(cmd)[:900])
        logger.info(
            "FFMPEG_ENCODER_SELECTED stage=rhythm encoder=%s nvenc_available=%s nvenc_enabled=%s",
            encoder_info.get("encoder"),
            str(encoder_info.get("nvenc_available", False)).lower(),
            str(encoder_info.get("nvenc_enabled", False)).lower(),
        )
        ok, stderr = await _run_ffmpeg(cmd, timeout=300)
        if not ok:
            logger.warning("CUT_ZOOM_FFMPEG_FAILED reason=%s stderr=%s", label, stderr[-400:])
            if str(encoder_info.get("encoder")) == "h264_nvenc":
                nvenc_failed = True
                logger.warning(
                    "FFMPEG_GPU_PATH_USED stage=rhythm used_nvenc=false reason=nvenc_failed_fallback_to_cpu"
                )
            tmp_output.unlink(missing_ok=True)
            continue
        if not _output_is_valid(tmp_output):
            logger.warning("CUT_ZOOM_FFMPEG_FAILED reason=%s output_invalid=%s", label, str(tmp_output))
            tmp_output.unlink(missing_ok=True)
            continue
        tmp_output.replace(output_path)
        logger.info(
            "CUT_ZOOM_FFMPEG_SUCCESS output=%s mode=%s encoder=%s",
            output_path,
            label,
            encoder_info.get("encoder"),
        )
        if label != "zoom":
            logger.warning("CUT_ZOOM_FALLBACK_USED mode=%s output=%s", label, output_path)
        return True, label

    tmp_output.unlink(missing_ok=True)
    return False, "all_attempts_failed"


async def apply_cut_zooms(
    video_path: str,
    output_path: str,
    cut_points: List[float],
    zoom_factor: float = DEFAULT_ZOOM_FACTOR,
    zoom_duration: float = DEFAULT_ZOOM_DURATION,
    fps: int = 30,
    framing_profile: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Apply zoom transitions at cut points.
    
    Args:
        video_path: Input video file
        output_path: Output video file
        cut_points: List of timestamps where cuts occur
        zoom_factor: Zoom intensity (1.0 = no zoom, 1.1 = 10% zoom)
        zoom_duration: Duration of each zoom in seconds
        fps: Frame rate
        
    Returns:
        True if successful, False otherwise
    """
    framing_profile = framing_profile if isinstance(framing_profile, dict) else {}
    framing_profile_name = str(framing_profile.get("framing_profile") or "").strip().lower()
    if framing_profile_name in {"no_reframe", "static_safe", "sensitive_stable"}:
        logger.info(
            "[cut_zoom] skipped reason=framing_profile_suppressed profile=%s",
            framing_profile_name or "none",
        )
        return False
    if framing_profile_name in {"speaker_centered", "speaker_upper_safe"}:
        zoom_factor = min(zoom_factor, 1.03 if framing_profile_name == "speaker_upper_safe" else 1.04)
        zoom_duration = min(zoom_duration, 0.45 if framing_profile_name == "speaker_upper_safe" else 0.50)
    elif framing_profile_name == "subtle_push_in":
        zoom_factor = min(zoom_factor, 1.055)
        zoom_duration = min(zoom_duration, 0.46)
    if not cut_points:
        logger.debug("[cut_zoom] No cut points, skipping zoom")
        return False

    ok_inputs, invalid_reason, meta = _validate_zoom_inputs(video_path, cut_points, zoom_duration)
    if not ok_inputs:
        logger.warning("CUT_ZOOM_INVALID_SEGMENT reason=%s video_path=%s", invalid_reason, video_path)
        if invalid_reason in {"input_missing", "input_empty", "invalid_dimensions"}:
            logger.warning("CUT_ZOOM_FFMPEG_FAILED reason=invalid_input")
            return False
        meta = meta or _probe_video_meta(video_path)
        if not meta:
            logger.warning("CUT_ZOOM_FFMPEG_FAILED reason=no_probe_metadata")
            return False
        cut_points = list(meta.get("valid_cut_points") or cut_points)

    # ── VALIDACIÓN: obtener duración real del video con ffprobe ────────────
    video_duration = None
    try:
        ffprobe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *ffprobe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        video_duration = float(stdout.decode().strip())
    except Exception as e:
        logger.warning(f"[cut_zoom] Could not get video duration: {e}")

    # ── VALIDACIÓN: filtrar timestamps inválidos ───────────────────────────
    zoom_intervals = []
    for t in cut_points[:10]:  # Limit to 10 zooms max
        start = max(0, t - zoom_duration / 2)
        end = t + zoom_duration / 2

        # Validar contra duración real del video si está disponible
        if video_duration is not None:
            if start < 0 or end > video_duration or end <= start:
                logger.warning(
                    f"[cut_zoom] Invalid zoom interval discarded: "
                    f"start={start:.3f}, end={end:.3f}, duration={video_duration:.3f}"
                )
                continue
        else:
            # Fallback: solo validar que end > start
            if end <= start:
                logger.warning(
                    f"[cut_zoom] Invalid zoom interval (duration unknown): "
                    f"start={start:.3f}, end={end:.3f}"
                )
                continue

        zoom_intervals.append((start, end))

    if not zoom_intervals:
        logger.warning("[cut_zoom] No valid zoom intervals after validation, falling back to safe ffmpeg export")

    # Get video dimensions using ffmpeg -i (imageio_ffmpeg doesn't bundle ffprobe)
    # Parse dimensions from stderr output like: "Stream #0:0: Video: h264 ... 1920x1080"
    probe_cmd = [
        _get_ffmpeg_exe(), "-i", video_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode('utf-8', errors='replace')

        # Look for pattern like "1920x1080" or "1080x1920"
        import re
        match = re.search(r'(\d{3,4})x(\d{3,4})', stderr_text)
        if match:
            width, height = int(match.group(1)), int(match.group(2))
        else:
            raise ValueError("Could not parse dimensions from ffmpeg output")
    except Exception as e:
        logger.warning(f"[cut_zoom] Could not get dimensions: {e}")
        width, height = 1080, 1920
    meta.setdefault("width", width)
    meta.setdefault("height", height)
    meta.setdefault("duration", video_duration or 0.0)
    meta.setdefault("has_audio", True)
    meta.setdefault("size", Path(video_path).stat().st_size if Path(video_path).exists() else 0)

    # Create zoom expression: use first cut point only to avoid FFmpeg max() errors
    if not zoom_intervals:
        zoom_intervals = [(0.0, min(float(video_duration or 0.0), zoom_duration))]

    # Prefer a zoom point outside the hook zone when possible.
    start, end = next(
        ((s, e) for s, e in zoom_intervals if s >= 3.0),
        zoom_intervals[0],
    )

    ok, mode = await _render_with_fallbacks(
        input_path=video_path,
        output_path=output_path,
        meta={**meta, "width": width, "height": height, "fps": fps},
        zoom_factor=zoom_factor,
        zoom_interval=(start, end),
    )
    if not ok:
        logger.warning("CUT_ZOOM_SKIPPED reason=render_failed")
        return False

    if mode != "zoom":
        logger.info("[cut_zoom] Applied safe fallback export instead of zoom render: %s", mode)
        return True

    logger.info(
        f"[cut_zoom] Applied zoom transition at {start:.1f}s-{end:.1f}s (first cut point)"
    )
    return True


async def apply_jump_cuts_with_zoom(
    video_path: str,
    output_path: str,
    words: Optional[List[Dict[str, Any]]] = None,
    min_silence_sec: float = 0.3,
    zoom_on_cuts: bool = True,
    zoom_factor: float = DEFAULT_ZOOM_FACTOR,
    framing_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Apply jump cuts AND zoom transitions in one pass.
    
    This is optimized for viral editing: aggressive silence removal (0.3s min)
    with zoom punches at every cut point.
    
    Args:
        video_path: Source video
        output_path: Output video
        words: Word-level transcript for filler detection
        min_silence_sec: Minimum silence gap to remove (0.3s = aggressive)
        zoom_on_cuts: Whether to add zoom at cut points
        zoom_factor: Zoom intensity
        
    Returns:
        Dict with cut_count, zoom_count, time_saved, error
    """
    from .jump_cut_service import apply_jump_cuts
    
    # Step 1: Apply jump cuts
    temp_cut = Path(output_path).with_suffix(".temp.mp4")
    
    result = await apply_jump_cuts(
        video_path=video_path,
        output_path=str(temp_cut),
        words=words,
        remove_fillers=True,
        remove_silence=True,
        silence_min_duration=min_silence_sec,
    )
    
    if result.error or not temp_cut.exists():
        return {
            "success": False,
            "error": result.error or "Jump cut failed",
            "cut_count": 0,
            "zoom_count": 0,
            "time_saved": 0,
        }
    
    # Step 2: Extract cut points from cut_list
    cut_points = []
    if result.cut_list:
        # Cut points are at the end of each kept segment
        for i, segment in enumerate(result.cut_list):
            if i < len(result.cut_list) - 1:  # Not last segment
                cut_points.append(segment["end"])
    
    # Step 3: Apply zoom transitions at cuts
    zoom_success = False
    if zoom_on_cuts and cut_points:
        zoom_success = await apply_cut_zooms(
            video_path=str(temp_cut),
            output_path=output_path,
            cut_points=cut_points,
            zoom_factor=zoom_factor,
            framing_profile=framing_profile,
        )
    
    # If zoom failed or not requested, just use the jump-cut output
    if not zoom_success:
        temp_cut.rename(output_path)
    else:
        temp_cut.unlink(missing_ok=True)
    
    return {
        "success": True,
        "cut_count": result.segments_removed,
        "zoom_count": len(cut_points) if zoom_success else 0,
        "time_saved": result.time_saved,
        "filler_words_removed": result.filler_words_removed,
        "silence_gaps_removed": result.silence_gaps_removed,
        "zoom_applied": zoom_success,
        "error": None,
    }
