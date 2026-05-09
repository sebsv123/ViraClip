"""
Clip analytics — retention heatmap via Redis sorted sets.
"""
import logging
import os

logger = logging.getLogger(__name__)


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
