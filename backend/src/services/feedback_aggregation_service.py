"""
Feedback Aggregation Service — Phase 23

Collects and aggregates user feedback on clips: thumbs up/down and 1-5 star ratings.
Uses Redis hashes per clip.

Key schema:
  clip_feedback:{clip_id}          → HASH: thumbs_up, thumbs_down, rating_sum, rating_count
  clip_feedback_users:{clip_id}    → HASH: user_id → "thumbs_up"|"thumbs_down"|"<rating>"
    (prevents duplicate votes per user)
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

_KEY_PREFIX = "clip_feedback"
_USERS_PREFIX = "clip_feedback_users"

_VALID_THUMBS = {"thumbs_up", "thumbs_down"}
_RATING_MIN = 1
_RATING_MAX = 5


def _stats_key(clip_id: str) -> str:
    return f"{_KEY_PREFIX}:{clip_id}"


def _users_key(clip_id: str) -> str:
    return f"{_USERS_PREFIX}:{clip_id}"


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def submit_thumbs(clip_id: str, user_id: str, vote: str) -> Dict:
    """
    Submit a thumbs_up or thumbs_down vote for a clip.
    Overwrites the user's previous vote (if any).
    Returns updated aggregate stats.
    """
    if vote not in _VALID_THUMBS:
        raise ValueError(f"vote must be one of {_VALID_THUMBS}")

    r = await _redis()
    prev_raw = await r.hget(_users_key(clip_id), user_id)
    prev = prev_raw.decode() if isinstance(prev_raw, bytes) else prev_raw

    pipe = r.pipeline()
    if prev in _VALID_THUMBS and prev != vote:
        pipe.hincrby(_stats_key(clip_id), prev, -1)
    if prev != vote:
        pipe.hincrby(_stats_key(clip_id), vote, 1)
    pipe.hset(_users_key(clip_id), user_id, vote)
    await pipe.execute()

    return await get_feedback_stats(clip_id)


async def submit_rating(clip_id: str, user_id: str, rating: int) -> Dict:
    """
    Submit a 1-5 star rating for a clip.
    Overwrites the user's previous rating (if any).
    """
    if not (_RATING_MIN <= rating <= _RATING_MAX):
        raise ValueError(f"rating must be {_RATING_MIN}-{_RATING_MAX}, got {rating}")

    r = await _redis()
    prev_raw = await r.hget(_users_key(clip_id), f"rating:{user_id}")
    prev_str = prev_raw.decode() if isinstance(prev_raw, bytes) else prev_raw

    pipe = r.pipeline()
    if prev_str and prev_str.isdigit():
        prev_val = int(prev_str)
        pipe.hincrby(_stats_key(clip_id), "rating_sum", rating - prev_val)
    else:
        pipe.hincrby(_stats_key(clip_id), "rating_sum", rating)
        pipe.hincrby(_stats_key(clip_id), "rating_count", 1)
    pipe.hset(_users_key(clip_id), f"rating:{user_id}", str(rating))
    await pipe.execute()

    return await get_feedback_stats(clip_id)


async def get_feedback_stats(clip_id: str) -> Dict:
    """Return aggregate feedback stats for a clip."""
    try:
        r = await _redis()
        raw = await r.hgetall(_stats_key(clip_id))
        data = {
            (k.decode() if isinstance(k, bytes) else k): int(v)
            for k, v in raw.items()
        }
        thumbs_up = data.get("thumbs_up", 0)
        thumbs_down = data.get("thumbs_down", 0)
        rating_sum = data.get("rating_sum", 0)
        rating_count = data.get("rating_count", 0)
        avg_rating = round(rating_sum / rating_count, 2) if rating_count else None
        return {
            "clip_id": clip_id,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "rating_count": rating_count,
            "avg_rating": avg_rating,
        }
    except Exception as exc:
        logger.warning("[feedback] get_stats failed clip=%s: %s", clip_id, exc)
        return {"clip_id": clip_id, "thumbs_up": 0, "thumbs_down": 0,
                "rating_count": 0, "avg_rating": None}


async def get_user_feedback(clip_id: str, user_id: str) -> Dict:
    """Return what a specific user has submitted for a clip."""
    try:
        r = await _redis()
        thumbs_raw = await r.hget(_users_key(clip_id), user_id)
        rating_raw = await r.hget(_users_key(clip_id), f"rating:{user_id}")
        thumbs = (thumbs_raw.decode() if isinstance(thumbs_raw, bytes) else thumbs_raw) or None
        rating_str = (rating_raw.decode() if isinstance(rating_raw, bytes) else rating_raw) or None
        return {
            "clip_id": clip_id,
            "user_id": user_id,
            "thumbs": thumbs,
            "rating": int(rating_str) if rating_str else None,
        }
    except Exception as exc:
        logger.warning("[feedback] get_user_feedback failed: %s", exc)
        return {"clip_id": clip_id, "user_id": user_id, "thumbs": None, "rating": None}
