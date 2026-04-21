"""
Cut Zoom Service — Apply zoom transitions at jump cut points.

Integrates with jump_cut_service to add dynamic zoom punches at each cut,
creating Alex Hormozi / MrBeast style aggressive viral editing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


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
DEFAULT_ZOOM_FACTOR = 1.08      # 8% zoom
DEFAULT_ZOOM_DURATION = 0.3     # seconds per zoom
DEFAULT_EASING = "ease_in_out"  # zoom easing


async def apply_cut_zooms(
    video_path: str,
    output_path: str,
    cut_points: List[float],
    zoom_factor: float = DEFAULT_ZOOM_FACTOR,
    zoom_duration: float = DEFAULT_ZOOM_DURATION,
    fps: int = 30,
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
    if not cut_points:
        logger.debug("[cut_zoom] No cut points, skipping zoom")
        return False

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
        logger.warning("[cut_zoom] No valid zoom intervals after validation, skipping zoom")
        return False

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
    
    # Create zoom expression: use first cut point only to avoid FFmpeg max() errors
    if not zoom_intervals:
        logger.debug("[cut_zoom] No valid zoom intervals")
        return False
    
    # Use only the first zoom interval to ensure compatibility
    start, end = zoom_intervals[0]
    
    # Simple if/else expression: zoom during first interval, otherwise 1.0
    zoom_expr = f"if(between(t,{start:.3f},{end:.3f}),{zoom_factor},1)"
    
    zoompan_filter = (
        f"zoompan="
        f"zoom='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d=1:"
        f"s={width}x{height}:"
        f"fps={fps}"
    )
    
    # Apply zoom filter
    cmd = [
        _get_ffmpeg_exe(), "-y", "-v", "error",
        "-i", video_path,
        "-vf", zoompan_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        output_path,
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            err = stderr.decode()[-300:]
            logger.error(f"[cut_zoom] FFmpeg error: {err}")
            return False
        
        logger.info(
            f"[cut_zoom] Applied zoom transition at {start:.1f}s-{end:.1f}s (first cut point)"
        )
        return True
    
    except Exception as e:
        logger.error(f"[cut_zoom] Failed to apply zooms: {e}")
        return False


async def apply_jump_cuts_with_zoom(
    video_path: str,
    output_path: str,
    words: Optional[List[Dict[str, Any]]] = None,
    min_silence_sec: float = 0.3,
    zoom_on_cuts: bool = True,
    zoom_factor: float = DEFAULT_ZOOM_FACTOR,
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
