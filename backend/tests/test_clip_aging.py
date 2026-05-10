"""Tests for clip aging and archive system."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_active_clips_old_enough_get_archived():
    """Clips without access for 35 days get archived."""
    from src.services.clip_aging_service import run_aging_job
    db = AsyncMock()
    db.fetch_all.return_value = [
        {"id": "clip_1", "file_path": "/tmp/test1.mp4", "user_id": "u1", "title": "Test 1"},
        {"id": "clip_2", "file_path": "/tmp/test2.mp4", "user_id": "u1", "title": "Test 2"},
    ]
    with patch("src.services.clip_aging_service._archive_clip", new_callable=AsyncMock) as mock_archive:
        mock_archive.return_value = True
        stats = await run_aging_job(db)
        assert stats["archived"] == 2


@pytest.mark.asyncio
async def test_archive_local_backend_marks_without_moving():
    """Local backend marks as archived without moving files."""
    from src.services.clip_aging_service import _archive_clip
    clip = {"id": "clip_1", "file_path": "/tmp/test.mp4", "user_id": "u1", "title": "Test"}
    with patch("src.services.clip_aging_service.Path.exists", return_value=True):
        with patch("src.services.clip_aging_service.ARCHIVE_BACKEND", "local"):
            result = await _archive_clip(clip, None)
            assert result is True


@pytest.mark.asyncio
async def test_restore_sets_status_restoring():
    """Restore sets status to restoring."""
    from src.api.routes.clips import restore_clip
    clip = MagicMock()
    clip.storage_status = "archived"
    clip.user_id = "user_1"
    clip.id = "clip_1"

    with patch("src.api.routes.clips.Path.exists", return_value=True):
        result = await restore_clip("clip_1", MagicMock(), MagicMock(), MagicMock(), MagicMock())
        assert result["status"] == "restoring"


@pytest.mark.asyncio
async def test_restore_active_clip_returns_immediately():
    """Active clip returns immediately."""
    from src.api.routes.clips import restore_clip
    clip = MagicMock()
    clip.storage_status = "active"
    clip.user_id = "user_1"

    result = await restore_clip("clip_1", MagicMock(), MagicMock(), MagicMock(), MagicMock())
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_deleted_clip_restore_returns_410():
    """Deleted clip returns 410."""
    from src.api.routes.clips import restore_clip
    clip = MagicMock()
    clip.storage_status = "deleted"
    clip.user_id = "user_1"

    with pytest.raises(Exception):
        await restore_clip("clip_1", MagicMock(), MagicMock(), MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_expired_restore_cleaned_in_job():
    """Expired restore cleaned in aging job."""
    from src.services.clip_aging_service import run_aging_job
    db = AsyncMock()
    db.fetch_all.side_effect = [
        [],  # clips to archive
        [],  # clips to delete
        [{"id": "clip_1", "file_path": "/tmp/restored.mp4"}],  # expired restores
    ]
    with patch("src.services.clip_aging_service.Path") as mock_path:
        mock_path.return_value.exists.return_value = True
        stats = await run_aging_job(db)
        assert stats["archived"] == 0
