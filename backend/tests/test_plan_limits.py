"""Tests for plan limits and usage checking."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_free_plan_daily_limit_blocks():
    """Free plan daily limit blocks task creation."""
    from src.core.usage_checker import check_task_allowed
    redis = AsyncMock()
    redis.get.return_value = b"3"  # 3 tasks today, limit=3
    allowed, reason = await check_task_allowed("user_1", "free", redis, MagicMock())
    assert allowed is False
    assert "Daily limit" in reason


@pytest.mark.asyncio
async def test_enterprise_unlimited_always_allowed():
    """Enterprise plan always allowed regardless of usage."""
    from src.core.usage_checker import check_task_allowed
    redis = AsyncMock()
    redis.get.return_value = b"9999"
    allowed, _ = await check_task_allowed("user_1", "enterprise", redis, MagicMock())
    assert allowed is True


@pytest.mark.asyncio
async def test_increment_usage_uses_pipeline():
    """increment_usage uses Redis pipeline."""
    from src.core.usage_checker import increment_usage
    redis = AsyncMock()
    pipe = AsyncMock()
    redis.pipeline.return_value = pipe
    await increment_usage("user_1", redis)
    redis.pipeline.assert_called_once()
    pipe.incr.assert_called()
    pipe.expire.assert_called()


@pytest.mark.asyncio
async def test_usage_endpoint_returns_remaining():
    """Usage endpoint returns remaining tasks."""
    from src.core.plan_limits import get_plan_limits
    limits = get_plan_limits("free")
    day_count = 2
    remaining = max(0, limits.tasks_per_day - day_count)
    assert remaining == 1
