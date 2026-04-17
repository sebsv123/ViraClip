"""
Clip Comparison Service — Phase 26

Side-by-side metric comparison between two clips.
Reads clip metadata stored in Redis hashes (set by task processing pipeline)
and computes diffs across common numeric metrics.

Key schema (read-only): clip_meta:{clip_id} → HASH (set by other services)

If clip metadata is not available in Redis, accepts inline metric dicts.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_NUMERIC_METRICS = [
    "viral_score", "hook_score", "pacing_score", "emotion_score",
    "duration", "word_count", "thumbs_up", "thumbs_down",
    "views", "click_through_rate",
]


def _to_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def compare_metrics(
    clip_a_id: str,
    clip_b_id: str,
    metrics_a: Dict[str, Any],
    metrics_b: Dict[str, Any],
) -> Dict:
    """
    Compare two clips side-by-side across all shared numeric metrics.

    Returns:
      {
        "clip_a": clip_a_id,
        "clip_b": clip_b_id,
        "metrics": {
          "viral_score": {"a": 75.0, "b": 60.0, "diff": 15.0, "winner": "a"},
          ...
        },
        "overall_winner": "a" | "b" | "tie",
        "wins_a": 3,
        "wins_b": 2,
      }
    """
    comparison: Dict[str, Dict] = {}
    wins_a = wins_b = 0

    all_keys = set(metrics_a.keys()) | set(metrics_b.keys())
    for key in sorted(all_keys):
        val_a = _to_float(metrics_a.get(key))
        val_b = _to_float(metrics_b.get(key))
        if val_a is None and val_b is None:
            continue

        entry: Dict = {"a": val_a, "b": val_b, "diff": None, "winner": None}
        if val_a is not None and val_b is not None:
            diff = round(val_a - val_b, 4)
            entry["diff"] = diff
            if diff > 0:
                entry["winner"] = "a"
                wins_a += 1
            elif diff < 0:
                entry["winner"] = "b"
                wins_b += 1
            else:
                entry["winner"] = "tie"
        comparison[key] = entry

    if wins_a > wins_b:
        overall = "a"
    elif wins_b > wins_a:
        overall = "b"
    else:
        overall = "tie"

    return {
        "clip_a": clip_a_id,
        "clip_b": clip_b_id,
        "metrics": comparison,
        "overall_winner": overall,
        "wins_a": wins_a,
        "wins_b": wins_b,
    }


async def compare_clips_from_redis(
    clip_a_id: str,
    clip_b_id: str,
    extra_a: Optional[Dict] = None,
    extra_b: Optional[Dict] = None,
) -> Dict:
    """
    Load clip metadata from Redis and compare.
    Falls back gracefully if keys are missing.
    """
    try:
        from src.workers.job_queue import JobQueue
        r = await JobQueue.get_pool()

        raw_a = await r.hgetall(f"clip_meta:{clip_a_id}")
        raw_b = await r.hgetall(f"clip_meta:{clip_b_id}")

        def _decode(raw: Dict) -> Dict:
            return {
                (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                for k, v in raw.items()
            }

        meta_a = {**_decode(raw_a), **(extra_a or {})}
        meta_b = {**_decode(raw_b), **(extra_b or {})}

    except Exception as exc:
        logger.warning("[clip_comparison] Redis load failed: %s", exc)
        meta_a = extra_a or {}
        meta_b = extra_b or {}

    return compare_metrics(clip_a_id, clip_b_id, meta_a, meta_b)
