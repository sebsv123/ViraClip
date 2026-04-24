"""Pure utility helpers for video domain.

These are stateless functions used across the video pipeline.
Kept separate so `video_service.py` stays focused on orchestration.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

UPLOAD_URL_PREFIX = "upload://"

# Module-level singleton for service config (lazy-loaded)
_config = None


def get_ffmpeg_exe() -> str:
    """Return ffmpeg binary path (imageio_ffmpeg if not in system PATH)."""
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def get_service_config():
    """Return the cached service config singleton (loaded once)."""
    global _config
    if _config is None:
        from ...config import get_config
        _config = get_config()
    return _config


def seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format (H:MM:SS.cc)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def get_file_duration(path: Path) -> Optional[float]:
    """Return video duration in seconds via ffmpeg, or None on failure."""
    try:
        result = subprocess.run(
            [get_ffmpeg_exe(), "-v", "error", "-i", str(path)],
            capture_output=True,
            text=True,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        return None
    except Exception as e:
        logger.warning(f"[VIDEO_DURATION] Failed to get duration for {path}: {e}")
        return None


def resolve_local_video_path(url: str) -> Path:
    """Resolve uploaded-video references without exposing server filesystem paths."""
    cfg = get_service_config()
    if url.startswith(UPLOAD_URL_PREFIX):
        filename = Path(url.removeprefix(UPLOAD_URL_PREFIX)).name
        return Path(cfg.temp_dir) / "uploads" / filename
    return Path(url)


def adjust_words_for_cuts(
    words: List[Dict[str, Any]],
    keep_intervals: List[Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """
    Remap word start/end timestamps to the new timeline produced after
    silence/jump-cut removal. Words that fall entirely inside a removed
    gap are dropped; words that straddle a gap boundary are clamped.
    """
    if not keep_intervals:
        return words

    # Pre-compute cumulative base offset for each kept interval
    cum: List[Tuple[float, float, float]] = []  # (interval_start, interval_end, new_base)
    base = 0.0
    for s, e in keep_intervals:
        cum.append((s, e, base))
        base += e - s

    def remap(t: float) -> float:
        """Map original time t into the post-cut timeline."""
        for s, e, b in cum:
            if t <= e:
                return b + max(0.0, t - s)
        # Past the last interval — clamp to end
        s, e, b = cum[-1]
        return b + (e - s)

    adjusted: List[Dict[str, Any]] = []
    for word in words:
        w_start = float(word.get("start", 0))
        w_end = float(word.get("end", 0))
        # Drop words entirely inside a removed gap
        in_kept = any(s <= w_start < e for s, e, _ in cum)
        if not in_kept:
            continue
        new_start = remap(w_start)
        new_end = remap(w_end)
        if new_end > new_start:
            adjusted.append({**word, "start": new_start, "end": new_end})
    return adjusted
