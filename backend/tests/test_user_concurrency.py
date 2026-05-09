"""Tests for per-user concurrency limiter."""
from unittest.mock import AsyncMock

import pytest

from src.core.user_concurrency import acquire_user_slot, release_user_slot


@pytest.mark.asyncio
async def test_first_task_acquires_slot():
    """First task → slot acquired."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    acquired, count = await acquire_user_slot("user_1", redis)
    assert acquired is True
    assert count == 1


@pytest.mark.asyncio
async def test_second_task_acquires_slot():
    """Second task, max=2 → slot acquired."""
    redis = AsyncMock()
    redis.incr.return_value = 2
    acquired, count = await acquire_user_slot("user_1", redis)
    assert acquired is True
    assert count == 2


@pytest.mark.asyncio
async def test_third_task_blocked():
    """Third task, max=2 → blocked."""
    redis = AsyncMock()
    redis.incr.return_value = 3
    acquired, count = await acquire_user_slot("user_1", redis)
    assert acquired is False
    assert count == 2
    redis.decr.assert_called_once()


@pytest.mark.asyncio
async def test_release_decrements_counter():
    """Release → DECR called."""
    redis = AsyncMock()
    redis.decr.return_value = 0
    await release_user_slot("user_1", redis)
    redis.decr.assert_called_once()


@pytest.mark.asyncio
async def test_redis_unavailable_allows():
    """Redis down → allowed (degraded)."""
    redis = AsyncMock()
    redis.incr.side_effect = Exception("Redis connection refused")
    acquired, count = await acquire_user_slot("user_1", redis)
    assert acquired is True
    assert count == 1
