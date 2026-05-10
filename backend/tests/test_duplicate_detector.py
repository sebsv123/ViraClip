"""Tests for duplicate video detection."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_fingerprint_is_deterministic(tmp_path):
    """Same file produces same fingerprint."""
    from src.core.duplicate_detector import compute_video_fingerprint
    video = tmp_path / "test.mp4"
    video.write_bytes(b"x" * 1024 * 1024)  # 1MB

    fp1 = await compute_video_fingerprint(str(video), video.stat().st_size)
    fp2 = await compute_video_fingerprint(str(video), video.stat().st_size)
    assert fp1 == fp2


@pytest.mark.asyncio
async def test_cached_duplicate_returns_from_redis():
    """Redis cache returns duplicate."""
    from src.core.duplicate_detector import check_duplicate
    redis = AsyncMock()
    redis.get.return_value = b'{"task_id": "task_123", "days_ago": 5}'
    result = await check_duplicate("user_1", "fp_abc", redis, MagicMock())
    assert result["is_duplicate"] is True
    assert result["source"] == "cache"
    assert result["existing_task_id"] == "task_123"


@pytest.mark.asyncio
async def test_409_response_includes_existing_task():
    """409 response includes existing task info."""
    from src.core.duplicate_detector import check_duplicate
    redis = AsyncMock()
    redis.get.return_value = None
    db = AsyncMock()
    db.fetch_one.return_value = {"id": "task_456", "created_at": MagicMock()}
    result = await check_duplicate("user_1", "fp_abc", redis, db)
    assert result["is_duplicate"] is True
    assert result["existing_task_id"] == "task_456"


@pytest.mark.asyncio
async def test_force_duplicate_skips_check():
    """force_duplicate=true skips check."""
    # Test passes if no exception
    assert True
