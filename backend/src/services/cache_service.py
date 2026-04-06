"""
Cache Service — Phase 18

Thin Redis-backed response cache for expensive read-only API calls.

Usage (in an API route handler):
    from src.services.cache_service import cached_response, invalidate_cache

    @router.get("/trend-intelligence/niche/{niche}")
    async def get_niche_trends(niche: str):
        cache_key = f"trend:{niche}"
        cached = await cached_response(cache_key)
        if cached is not None:
            return cached
        data = await _compute_expensive_thing(niche)
        await set_cached_response(cache_key, data, ttl=3600)
        return data
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 3600  # 1 hour


async def _get_redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


# ── Public API ────────────────────────────────────────────────────────────────

async def cached_response(key: str) -> Optional[Any]:
    """
    Return the cached JSON value for `key`, or None if not present / expired.
    Fails open on Redis errors.
    """
    try:
        redis = await _get_redis()
        raw = await redis.get(f"cache:{key}")
        if raw:
            logger.debug("[cache] HIT  key=%s", key)
            return json.loads(raw)
    except Exception as exc:
        logger.warning("[cache] GET failed for key=%s: %s", key, exc)
    return None


async def set_cached_response(key: str, value: Any, ttl: int = _DEFAULT_TTL) -> None:
    """
    Persist `value` (JSON-serialisable) under `key` with a TTL in seconds.
    Fails open on Redis errors.
    """
    try:
        redis = await _get_redis()
        serialised = json.dumps(value)
        await redis.setex(f"cache:{key}", ttl, serialised)
        logger.debug("[cache] SET  key=%s ttl=%ds", key, ttl)
    except Exception as exc:
        logger.warning("[cache] SET failed for key=%s: %s", key, exc)


async def invalidate_cache(key: str) -> bool:
    """
    Delete a cache entry.  Returns True if the key existed.
    """
    try:
        redis = await _get_redis()
        deleted = await redis.delete(f"cache:{key}")
        logger.debug("[cache] DEL  key=%s deleted=%s", key, bool(deleted))
        return bool(deleted)
    except Exception as exc:
        logger.warning("[cache] DEL failed for key=%s: %s", key, exc)
        return False


async def invalidate_prefix(prefix: str) -> int:
    """
    Delete all cache entries whose key starts with `prefix`.
    Returns the number of keys removed.
    """
    try:
        redis = await _get_redis()
        keys = await redis.keys(f"cache:{prefix}*")
        if not keys:
            return 0
        deleted = await redis.delete(*keys)
        logger.debug("[cache] DEL prefix=%s count=%d", prefix, deleted)
        return deleted
    except Exception as exc:
        logger.warning("[cache] DEL prefix failed for prefix=%s: %s", prefix, exc)
        return 0


async def get_cache_stats(prefixes: Optional[list] = None) -> dict:
    """
    Return simple stats: key count per prefix (for monitoring).
    """
    try:
        redis = await _get_redis()
        pattern = "cache:*"
        all_keys = await redis.keys(pattern)
        total = len(all_keys)
        stats: dict = {"total_keys": total, "by_prefix": {}}
        if prefixes:
            for p in prefixes:
                matching = [k for k in all_keys if k.decode("utf-8").startswith(f"cache:{p}")]
                stats["by_prefix"][p] = len(matching)
        return stats
    except Exception as exc:
        logger.warning("[cache] stats failed: %s", exc)
        return {"total_keys": 0, "by_prefix": {}, "error": str(exc)}
