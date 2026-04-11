"""
B-Roll Compositor — Format-Adaptive Overlay Engine

Single source of truth for all B-roll compositing in ViraClip.
Replaces the three hardcoded scale=1080:1920 blocks scattered across
broll_service.py, pexels_service.py and video_effects.py.

Supported output formats (auto-probed from main clip):
  9:16  portrait  — 1080×1920, 720×1280
  1:1   square    — 1080×1080
  16:9  landscape — 1920×1080  (rare, kept for completeness)
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_FFPROBE_TIMEOUT = 15   # seconds
_FFMPEG_TIMEOUT  = 180  # seconds per overlay


# ── Dimension probing ─────────────────────────────────────────────────────────

def probe_dimensions(video_path: Path | str) -> Tuple[int, int, float]:
    """
    Return (width, height, fps) of *video_path* using ffprobe.
    Falls back to (1080, 1920, 30.0) if probing fails.
    """
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
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
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT)
        return float(result.stdout.strip())
    except Exception:
        return 30.0


# ── B-roll normalisation ──────────────────────────────────────────────────────

def normalize_broll(
    broll_path: Path | str,
    target_w: int,
    target_h: int,
    duration: float,
    fade: float = 0.3,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Produce a normalised B-roll clip:
      - Scaled and center-cropped to target_w × target_h
      - Trimmed to *duration* seconds
      - Fade-in and fade-out of *fade* seconds
      - Audio muted (B-roll is silent by design)

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

    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},"
        f"setsar=1,"
        f"fade=t=in:st=0:d={fade},"
        f"fade=t=out:st={fade_out_start:.3f}:d={fade}"
    )

    if is_image:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(broll_path),
            "-t", str(duration),
            "-vf", vf,
            "-an",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(broll_path),
            "-t", str(duration),
            "-vf", vf,
            "-an",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
        if result.returncode != 0:
            logger.error("[BrollCompositor] normalize_broll failed: %s",
                         result.stderr.decode()[-400:])
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
    duration: float = 3.0,
    fade: float = 0.3,
) -> bool:
    """
    Overlay *broll_path* on *main_path* starting at *timestamp* for *duration* seconds.

    Steps:
      1. Probe main clip dimensions
      2. Normalise B-roll to those exact dimensions
      3. Composite with FFmpeg overlay filter

    Returns True on success.
    """
    main_path   = Path(main_path)
    broll_path  = Path(broll_path)
    output_path = Path(output_path)

    w, h, _fps = probe_dimensions(main_path)

    # Normalise B-roll to a temp file
    norm_path = normalize_broll(broll_path, w, h, duration=duration + 0.5, fade=fade)
    if norm_path is None:
        logger.error("[BrollCompositor] compose_overlay: normalise step failed")
        return False

    end_ts = timestamp + duration
    filter_complex = (
        f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB[bv];"
        f"[0:v][bv]overlay=enable='between(t,{timestamp:.3f},{end_ts:.3f})'"
        f":x=0:y=0[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(main_path),
        "-i", str(norm_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
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


# ── Async multi-overlay (used by video_effects.py) ────────────────────────────

async def compose_overlay_multi(
    main_path: Path | str,
    broll_pairs: list,          # [(timestamp, broll_path, duration), ...]
    output_path: Path | str,
    fade: float = 0.3,
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

    # Normalise each B-roll clip
    norm_paths: list[Path] = []
    valid_pairs: list[tuple] = []
    for ts, bp, dur in broll_pairs:
        np_ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda bp=bp, dur=dur: normalize_broll(Path(bp), w, h, duration=dur + 0.5, fade=fade),
        )
        if np_:
            norm_paths.append(np_)
            valid_pairs.append((ts, np_, dur))

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
        filter_parts.append(
            f"[{prev}][{idx + 1}:v]"
            f"overlay=enable='between(t,{ts:.3f},{end_ts:.3f})':x=0:y=0"
            f"[{out_tag}]"
        )
        prev = out_tag

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{prev}]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _err = await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT)
        for np_ in norm_paths:
            np_.unlink(missing_ok=True)
        if proc.returncode != 0:
            logger.error("[BrollCompositor] compose_overlay_multi failed: %s",
                         _err.decode()[-400:])
            return False
        return output_path.exists() and output_path.stat().st_size > 0
    except (asyncio.TimeoutError, Exception) as exc:
        logger.error("[BrollCompositor] compose_overlay_multi exception: %s", exc)
        for np_ in norm_paths:
            np_.unlink(missing_ok=True)
        return False
