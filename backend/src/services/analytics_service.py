"""
Clip analytics — retention heatmap via Redis sorted sets and B-roll feedback via JSON storage.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── B-roll feedback storage ────────────────────────────────────────────────────

_BROLL_FEEDBACK_DIR = Path(os.getenv("BROLL_FEEDBACK_DIR", "/tmp/viraclip_broll_feedback"))
_BROLL_FEEDBACK_FILE = _BROLL_FEEDBACK_DIR / "broll_feedback.json"


def _ensure_feedback_dir() -> None:
    """Ensure the feedback storage directory exists."""
    _BROLL_FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


def _load_broll_feedback() -> Dict[str, Dict[str, float]]:
    """
    Load B-roll feedback data from JSON file.

    Returns a dict mapping broll_type → {used: int, avg_watch_pct: float}.
    If the file doesn't exist or is corrupt, returns an empty dict.
    """
    _ensure_feedback_dir()
    if not _BROLL_FEEDBACK_FILE.exists():
        return {}
    try:
        data = json.loads(_BROLL_FEEDBACK_FILE.read_text())
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[Analytics] Failed to load B-roll feedback: %s", e)
        return {}


def _save_broll_feedback(data: Dict[str, Dict[str, float]]) -> None:
    """Save B-roll feedback data to JSON file."""
    _ensure_feedback_dir()
    try:
        _BROLL_FEEDBACK_FILE.write_text(json.dumps(data, indent=2))
    except OSError as e:
        logger.warning("[Analytics] Failed to save B-roll feedback: %s", e)


def record_broll_feedback(
    broll_type: str,
    watch_pct: float,
    used: int = 1,
) -> None:
    """
    Record feedback for a B-roll type.

    This is an offline/batch operation: it loads the existing feedback data,
    updates the rolling average for the given broll_type, and saves back to disk.

    Args:
        broll_type: The B-roll type/keyword (e.g., "city_skyline").
        watch_pct: The watch percentage for this instance (0.0 to 1.0).
        used: How many times this type was used (default 1).
    """
    data = _load_broll_feedback()
    existing = data.get(broll_type, {"used": 0, "avg_watch_pct": 0.0})

    # Rolling average: new_avg = (old_avg * old_count + new_value * new_count) / (old_count + new_count)
    old_used = existing["used"]
    old_avg = existing["avg_watch_pct"]
    new_used = old_used + used
    new_avg = (old_avg * old_used + watch_pct * used) / new_used if new_used > 0 else watch_pct

    data[broll_type] = {
        "used": new_used,
        "avg_watch_pct": round(new_avg, 4),
    }

    _save_broll_feedback(data)
    logger.info(
        "[Analytics] Recorded B-roll feedback: %s (used=%d, avg_watch_pct=%.4f)",
        broll_type, new_used, new_avg,
    )


def get_broll_feedback() -> Dict[str, Dict[str, float]]:
    """
    Get all B-roll feedback data.

    Returns a dict mapping broll_type → {used: int, avg_watch_pct: float}.
    This data can be passed directly to AiBrollRecommender as task_feedback.
    """
    return _load_broll_feedback()


def reset_broll_feedback() -> None:
    """Clear all B-roll feedback data (useful for testing)."""
    _ensure_feedback_dir()
    _save_broll_feedback({})
    logger.info("[Analytics] B-roll feedback reset")


# ── Retention heatmap (existing) ───────────────────────────────────────────────

async def track_playback_position(
    clip_id: str,
    position_seconds: float,
    redis,
) -> None:
    """
    Track at which second the user stopped watching.
    Accumulates in Redis for retention heatmap.
    """
    try:
        env = os.getenv("APP_ENV", "production")
        bucket = int(position_seconds // 5) * 5
        key = f"{env}:analytics:retention:{clip_id}"
        await redis.zincrby(key, 1, str(bucket))
        await redis.expire(key, 86400 * 30)
    except Exception:
        pass


async def get_retention_heatmap(clip_id: str, redis) -> list[dict]:
    """
    Return retention heatmap for a clip.
    [{second: 0, views: 150}, {second: 5, views: 142}, ...]
    """
    try:
        env = os.getenv("APP_ENV", "production")
        key = f"{env}:analytics:retention:{clip_id}"
        data = await redis.zrange(key, 0, -1, withscores=True)
        return [
            {"second": int(bucket), "views": int(score)}
            for bucket, score in data
        ]
    except Exception:
        return []
