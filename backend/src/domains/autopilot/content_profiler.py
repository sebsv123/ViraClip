"""
Content Profiler — classifies video content type using simple heuristics.

Returns a profile dict that downstream services (cut_zoom, jump_cut, hook_reorder)
use to decide whether to activate. No ML models, no external APIs.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _count_scene_changes(video_path: str, threshold: float = 0.3) -> int:
    """
    Count scene changes using FFmpeg scene detection filter.
    Returns the number of detected scene transitions.

    Uses ffmpeg's `select='gt(scene,threshold)'` filter which compares
    consecutive frames and counts transitions above the threshold.
    Lower threshold = more sensitive (0.3 = moderate).
    """
    try:
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        # Count "pts_time:" lines in stderr (each = one scene change)
        stderr = result.stderr or ""
        changes = stderr.count("pts_time:")
        logger.debug(f"[content_profiler] Scene changes detected: {changes}")
        return changes
    except Exception as e:
        logger.debug(f"[content_profiler] Scene detection failed: {e}")
        return 0


def _calc_speech_ratio(words: List[Dict[str, Any]], duration: float) -> float:
    """
    Calculate the proportion of time where speech is active.

    Sums (word.end - word.start) for all words and divides by total duration.
    A talking_head has speech_ratio > 0.5 (someone speaking most of the time).
    A tutorial has speech_ratio 0.3-0.5 (speaking + pauses for demonstration).
    A vlog has speech_ratio < 0.3 (lots of ambient/B-roll time).
    """
    if not words or duration <= 0:
        return 0.0
    total_speech = sum(
        max(0.0, float(w.get("end", 0)) - float(w.get("start", 0)))
        for w in words
    )
    ratio = min(1.0, total_speech / duration)
    logger.debug(f"[content_profiler] Speech ratio: {ratio:.2f} ({total_speech:.1f}s / {duration:.1f}s)")
    return ratio


def profile_content(
    video_path: str,
    words: List[Dict[str, Any]],
    duration: float = 0.0,
) -> Dict[str, Any]:
    """
    Classify video content type using simple heuristics.

    Args:
        video_path: Path to the video file.
        words: List of word dicts with 'start' and 'end' keys.
        duration: Clip duration in seconds. If 0, probed from video.

    Returns:
        {
            "type": "talking_head" | "tutorial" | "vlog",
            "speech_ratio": float,       # 0.0-1.0
            "scene_changes": int,        # number of detected scene transitions
            "recommended_zoom": bool,    # True for talking_head (face emphasis)
            "recommended_jump_cuts": bool,  # True for talking_head (remove pauses)
        }
    """
    # Probe duration if not provided
    if duration <= 0:
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            duration = float(result.stdout.strip() or 0)
        except Exception:
            duration = 30.0

    scene_changes = _count_scene_changes(video_path)
    speech_ratio = _calc_speech_ratio(words, duration)

    # Heuristic classification
    # talking_head: high speech ratio, few scene changes (face talking to camera)
    # tutorial: moderate speech ratio, moderate scene changes (screen recording + face)
    # vlog: low speech ratio, many scene changes (B-roll heavy)
    if speech_ratio > 0.5 and scene_changes <= 3:
        content_type = "talking_head"
    elif speech_ratio > 0.3 and scene_changes <= 8:
        content_type = "tutorial"
    else:
        content_type = "vlog"

    # Recommendations based on type
    recommended_zoom = (content_type == "talking_head")
    recommended_jump_cuts = (content_type == "talking_head")

    profile = {
        "type": content_type,
        "speech_ratio": round(speech_ratio, 3),
        "scene_changes": scene_changes,
        "recommended_zoom": recommended_zoom,
        "recommended_jump_cuts": recommended_jump_cuts,
    }

    logger.info(
        "[content_profiler] %s | speech=%.2f scenes=%d zoom=%s jump=%s",
        content_type, speech_ratio, scene_changes,
        recommended_zoom, recommended_jump_cuts,
    )
    return profile
