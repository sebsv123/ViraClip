"""Tests for longform rate limiter — Redis-based daily quota."""
from unittest.mock import AsyncMock

import pytest

from src.api.routes.longform import check_longform_rate_limit


@pytest.mark.asyncio
async def test_first_request_allowed():
    """First request of the day → allowed, remaining=4."""
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.expire.return_value = True

    allowed, remaining = await check_longform_rate_limit("user_1", redis)
    assert allowed is True
    assert remaining == 4
    redis.incr.assert_called_once()
    redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_fifth_request_allowed():
    """5th request → allowed, remaining=0."""
    redis = AsyncMock()
    redis.incr.return_value = 5

    allowed, remaining = await check_longform_rate_limit("user_1", redis)
    assert allowed is True
    assert remaining == 0


@pytest.mark.asyncio
async def test_sixth_request_blocked():
    """6th request → blocked, remaining=0."""
    redis = AsyncMock()
    redis.incr.return_value = 6

    allowed, remaining = await check_longform_rate_limit("user_1", redis)
    assert allowed is False
    assert remaining == 0
    redis.decr.assert_called_once()  # no cuenta el intento fallido


@pytest.mark.asyncio
async def test_rate_limit_resets_next_day():
    """Next day → new window, allowed."""
    redis = AsyncMock()
    redis.incr.return_value = 1  # fresh counter for new day

    allowed, remaining = await check_longform_rate_limit("user_1", redis)
    assert allowed is True
    assert remaining == 4


@pytest.mark.asyncio
async def test_redis_unavailable_allows_request():
    """Redis down → allowed (degraded)."""
    redis = AsyncMock()
    redis.incr.side_effect = Exception("Redis connection refused")

    allowed, remaining = await check_longform_rate_limit("user_1", redis)
    assert allowed is True
    assert remaining == 5
