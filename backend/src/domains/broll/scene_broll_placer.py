"""
Scene-Aware B-Roll Placement — PySceneDetect Integration

Detects natural scene boundaries in a clip and returns the best
timestamps for B-roll insertion, replacing the previous heuristics
(fixed t=5s or "30-60% of clip duration").

Falls back gracefully if scenedetect is not installed or no scenes
are detected.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MIN_SCENE_S   = 1.5   # scenes shorter than this are skipped
_MAX_SCENE_S   = 8.0   # scenes longer are still valid but scored lower
_IDEAL_RANGE   = (2.0, 6.0)


# ── Scene detection ───────────────────────────────────────────────────────────

def detect_scenes(
    video_path: Path | str,
    threshold: float = 27.0,
) -> List[Tuple[float, float]]:
    """
    Detect scene boundaries using PySceneDetect ContentDetector.

    Returns list of (scene_start_s, scene_end_s).
    Returns [] if scenedetect is unavailable or no scenes are found.
    """
    try:
        from scenedetect import VideoManager, SceneManager
        from scenedetect.detectors import ContentDetector
    except ImportError:
        logger.debug("[SceneBroll] scenedetect not installed; falling back to silence heuristic")
        return []

    try:
        video_manager = VideoManager([str(video_path)])
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold))

        video_manager.set_downscale_factor()
        video_manager.start()
        scene_manager.detect_scenes(frame_source=video_manager)

        scene_list = scene_manager.get_scene_list()
        video_manager.release()

        result = []
        for start_tc, end_tc in scene_list:
            s = start_tc.get_seconds()
            e = end_tc.get_seconds()
            if (e - s) >= _MIN_SCENE_S:
                result.append((s, e))

        logger.info("[SceneBroll] %d scenes detected in %s", len(result), Path(video_path).name)
        return result

    except Exception as exc:
        logger.debug("[SceneBroll] detect_scenes error: %s", exc)
        return []


# ── Silence fallback ──────────────────────────────────────────────────────────

def _detect_silences_ffmpeg(
    video_path: Path | str,
    min_duration: float = 1.0,
) -> List[float]:
    """
    Use FFmpeg silencedetect filter to find silence midpoints.
    Returns a list of timestamps (seconds) where silence occurs.
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-af", f"silencedetect=noise=-35dB:d={min_duration}",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stderr
        starts = []
        ends   = []
        for line in output.splitlines():
            if "silence_start" in line:
                try:
                    starts.append(float(line.split("silence_start:")[1].strip().split()[0]))
                except (IndexError, ValueError):
                    pass
            elif "silence_end" in line:
                try:
                    ends.append(float(line.split("silence_end:")[1].strip().split("|")[0].strip()))
                except (IndexError, ValueError):
                    pass
        midpoints = [(s + e) / 2 for s, e in zip(starts, ends)]
        return midpoints
    except Exception as exc:
        logger.debug("[SceneBroll] silence fallback failed: %s", exc)
        return []


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_scene(start: float, end: float) -> float:
    """
    Score a scene for B-roll candidacy.
    Higher = better insertion candidate.
    Scenes in _IDEAL_RANGE get the highest score.
    """
    duration = end - start
    if duration < _MIN_SCENE_S:
        return 0.0
    lo, hi = _IDEAL_RANGE
    if lo <= duration <= hi:
        return 1.0
    if duration < lo:
        return duration / lo
    # longer scenes: score falls off slowly
    return hi / duration


# ── Public API ────────────────────────────────────────────────────────────────

def get_insert_timestamps(
    video_path: Path | str,
    max_n: int = 3,
    clip_duration: Optional[float] = None,
    transcript_segments: Optional[List[Dict[str, Any]]] = None,
) -> List[float]:
    """
    Return up to *max_n* timestamps (seconds) for B-roll insertion.

    Strategy:
      1. Try PySceneDetect → pick start of best-scored scenes
      2. Try FFmpeg silencedetect midpoints
      3. Fall back to evenly-spaced intervals

    If *transcript_segments* is provided, only emit timestamps that fall
    within a segment where the speaker has said at least 5 words.
    Timestamps in silence or before speech starts are dropped.
    """
    video_path = Path(video_path)

    def _filter_by_transcript(ts_list: List[float]) -> List[float]:
        """Keep only timestamps that fall within transcript segments with ≥5 words."""
        if not transcript_segments:
            return ts_list
        _filtered = []
        for ts in ts_list:
            for seg in transcript_segments:
                seg_start = seg.get("start", 0) if isinstance(seg, dict) else getattr(seg, "start", 0)
                seg_end = seg.get("end", 0) if isinstance(seg, dict) else getattr(seg, "end", 0)
                seg_text = seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")
                word_count = len(seg_text.split())
                if seg_start <= ts <= seg_end and word_count >= 5:
                    _filtered.append(ts)
                    break
        if len(_filtered) < len(ts_list):
            logger.info(
                "[SceneBroll] Transcript filter: %d/%d timestamps kept (min 5 words per segment)",
                len(_filtered), len(ts_list),
            )
        return _filtered

    # 1 — Scene detection
    scenes = detect_scenes(video_path)
    if scenes:
        scored = sorted(scenes, key=lambda s: _score_scene(s[0], s[1]), reverse=True)
        # Take top-N, return start time (insert B-roll at the scene's opening frame)
        timestamps = sorted([s for s, _ in scored[:max_n]])
        # Don't insert B-roll in the first 0.5s (keep hook)
        timestamps = [t for t in timestamps if t >= 0.5]
        timestamps = _filter_by_transcript(timestamps)
        if not timestamps:
            logger.warning(
                "[SceneBroll] Transcript filter emptied scene-based timestamps — falling through to silence"
            )
        if timestamps:
            logger.info("[SceneBroll] Scene-based timestamps: %s", timestamps)
            return timestamps[:max_n]

    # 2 — Silence midpoints
    silences = _detect_silences_ffmpeg(video_path)
    if silences:
        silences = _filter_by_transcript(silences)
        if not silences:
            logger.warning(
                "[SceneBroll] Transcript filter emptied silence-based timestamps — falling through to even-spacing"
            )
        if silences:
            logger.info("[SceneBroll] Silence-based timestamps: %s", silences[:max_n])
            return silences[:max_n]

    # 3 — Even spacing fallback
    if clip_duration is None:
        try:
            from .broll_compositor import probe_duration
            clip_duration = probe_duration(video_path)
        except Exception:
            clip_duration = 30.0

    step = clip_duration / (max_n + 1)
    fallback = [round(step * (i + 1), 2) for i in range(max_n)]
    fallback = _filter_by_transcript(fallback)
    if fallback:
        logger.info("[SceneBroll] Even-spacing fallback timestamps: %s", fallback)
        return fallback[:max_n]
    logger.info("[SceneBroll] Even-spacing fallback produced no timestamps after transcript filter — returning empty")
    return []
