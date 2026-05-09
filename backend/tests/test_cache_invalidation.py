"""Tests for Redis cache invalidation on clip delete."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_delete_clip_invalidates_cache():
    """SCAN finds keys → DELETE called."""
    redis = AsyncMock()
    redis.scan.return_value = (0, ["cache:clip:abc:meta", "cache:clip:abc:file"])
    redis.delete.return_value = 2

    from src.api.routes.clips import _invalidate_clip_cache
    await _invalidate_clip_cache("abc", "task_1", redis)
    redis.delete.assert_called_once()
    redis.scan.assert_called()


@pytest.mark.asyncio
async def test_invalidation_never_raises():
    """Redis error → no exception."""
    redis = AsyncMock()
    redis.scan.side_effect = Exception("Redis connection lost")

    from src.api.routes.clips import _invalidate_clip_cache
    try:
        await _invalidate_clip_cache("abc", "task_1", redis)
        assert True
    except Exception:
        assert False


@pytest.mark.asyncio
async def test_scan_uses_cursor_pagination():
    """SCAN paginates through all results."""
    redis = AsyncMock()
    redis.scan.side_effect = [
        (5, ["key1", "key2"]),   # cursor=5, has more
        (0, ["key3"]),            # cursor=0, done
    ]

    from src.api.routes.clips import _invalidate_clip_cache
    await _invalidate_clip_cache("abc", "task_1", redis)
    assert redis.scan.call_count == 2
    assert redis.delete.call_count == 2
