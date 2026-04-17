"""
Clip Score Override Service — Phase 23

Allows moderators or users to manually override the AI-computed virality score
for a clip. Overrides are stored in Redis and checked before returning any score.

Key schema:
  score_override:{clip_id}   → HASH: score, reason, author, created_at, original_score

Score range: 0.0 – 100.0
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict

logger = logging.getLogger(__name__)

_KEY_PREFIX = "score_override"
_SCORE_MIN = 0.0
_SCORE_MAX = 100.0


def _key(clip_id: str) -> str:
    return f"{_KEY_PREFIX}:{clip_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def set_score_override(
    clip_id: str,
    score: float,
    author: str = "",
    reason: str = "",
    original_score: Optional[float] = None,
) -> Dict:
    """Set a manual score override for a clip. Returns the stored override dict."""
    if not (_SCORE_MIN <= score <= _SCORE_MAX):
        raise ValueError(f"Score must be between {_SCORE_MIN} and {_SCORE_MAX}, got {score}")

    r = await _redis()
    payload = {
        "clip_id": clip_id,
        "score": str(score),
        "author": author,
        "reason": reason,
        "original_score": str(original_score) if original_score is not None else "",
        "created_at": _now(),
    }
    await r.hset(_key(clip_id), mapping=payload)
    logger.debug("[score_override] set clip=%s score=%.1f author=%s", clip_id, score, author)
    return {**payload, "score": score,
            "original_score": original_score}


async def get_score_override(clip_id: str) -> Optional[Dict]:
    """Return the score override for a clip, or None if not set."""
    try:
        r = await _redis()
        raw = await r.hgetall(_key(clip_id))
        if not raw:
            return None
        data = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        data["score"] = float(data["score"])
        if data.get("original_score"):
            data["original_score"] = float(data["original_score"])
        else:
            data["original_score"] = None
        return data
    except Exception as exc:
        logger.warning("[score_override] get failed clip=%s: %s", clip_id, exc)
        return None


async def delete_score_override(clip_id: str) -> bool:
    """Remove the score override for a clip. Returns True if it existed."""
    try:
        r = await _redis()
        deleted = await r.delete(_key(clip_id))
        return bool(deleted)
    except Exception as exc:
        logger.warning("[score_override] delete failed clip=%s: %s", clip_id, exc)
        return False


async def resolve_score(clip_id: str, computed_score: float) -> Dict:
    """
    Return the effective score for a clip, preferring an override if present.
    Result: {"clip_id", "effective_score", "overridden": bool, "override": dict|None}
    """
    override = await get_score_override(clip_id)
    if override:
        return {
            "clip_id": clip_id,
            "effective_score": override["score"],
            "overridden": True,
            "override": override,
        }
    return {
        "clip_id": clip_id,
        "effective_score": computed_score,
        "overridden": False,
        "override": None,
    }
