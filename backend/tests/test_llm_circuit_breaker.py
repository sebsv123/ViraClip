"""Tests for llm_router circuit breaker — trigger, reset, memory, namespace, expiry."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domains.ai.llm_router import (
    _cb_record_failure,
    _cb_record_success,
    _cb_is_bypassed,
    _cb_failures_mem,
    _cb_bypassed_until_mem,
)


@pytest.fixture(autouse=True)
def reset_cb():
    """Reset circuit breaker state before each test."""
    import src.domains.ai.llm_router as cb
    cb._cb_failures_mem = 0
    cb._cb_bypassed_until_mem = 0.0
    yield


@pytest.mark.asyncio
async def test_circuit_breaker_triggers_after_3_failures():
    """3 failures → circuit breaker activates."""
    redis = AsyncMock()
    redis.incr.return_value = 3
    redis.expire.return_value = True

    await _cb_record_failure(redis)
    await _cb_record_failure(redis)
    await _cb_record_failure(redis)

    assert await _cb_is_bypassed(redis) is True
    redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success():
    """After circuit breaker activates, success resets it."""
    redis = AsyncMock()
    redis.incr.return_value = 3

    await _cb_record_failure(redis)
    await _cb_record_failure(redis)
    await _cb_record_failure(redis)
    assert await _cb_is_bypassed(redis) is True

    await _cb_record_success(redis)
    assert await _cb_is_bypassed(redis) is False
    redis.delete.assert_called()


@pytest.mark.asyncio
async def test_circuit_breaker_memory_fallback():
    """Redis unavailable → memory fallback works."""
    redis = AsyncMock()
    redis.incr.side_effect = Exception("Redis down")

    await _cb_record_failure(redis)
    await _cb_record_failure(redis)
    await _cb_record_failure(redis)

    assert await _cb_is_bypassed(redis) is True


@pytest.mark.asyncio
async def test_circuit_breaker_namespace():
    """APP_ENV prefixes Redis keys correctly."""
    with patch.dict("os.environ", {"APP_ENV": "staging"}):
        # Re-import to pick up new _ENV
        import importlib
        import src.domains.ai.llm_router as cb
        importlib.reload(cb)

        redis = AsyncMock()
        redis.incr.return_value = 1
        await cb._cb_record_failure(redis)
        # Key should be "staging:llm:deepseek:failures"
        call_key = redis.incr.call_args[0][0]
        assert call_key.startswith("staging:")


@pytest.mark.asyncio
async def test_bypass_expires_after_timeout():
    """Circuit breaker expires after bypass timeout."""
    redis = AsyncMock()
    redis.incr.return_value = 3

    await _cb_record_failure(redis)
    await _cb_record_failure(redis)
    await _cb_record_failure(redis)
    assert await _cb_is_bypassed(redis) is True

    # Simulate 601 seconds passing
    with patch("src.domains.ai.llm_router._time.time", return_value=time.time() + 601):
        assert await _cb_is_bypassed(redis) is False
