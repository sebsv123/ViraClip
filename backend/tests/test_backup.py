"""Tests for PostgreSQL backup worker."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_backup_success_returns_dict():
    """Successful backup returns dict with success=True."""
    from src.workers.backup_worker import backup_postgresql
    with patch("src.workers.backup_worker.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        with patch("src.workers.backup_worker._upload_backup", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = True
            result = await backup_postgresql()
            assert result["success"] is True
            assert "filename" in result
            assert result["size_mb"] >= 0


@pytest.mark.asyncio
async def test_backup_pgdump_failure_returns_dict():
    """pg_dump failure returns dict with success=False."""
    from src.workers.backup_worker import backup_postgresql
    with patch("src.workers.backup_worker.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 1
        proc.stderr = b"pg_dump: error: connection failed"
        mock_proc.return_value = proc
        result = await backup_postgresql()
        assert result["success"] is False
        assert "error" in result


@pytest.mark.asyncio
async def test_backup_timeout_returns_dict():
    """pg_dump timeout returns dict with success=False."""
    from src.workers.backup_worker import backup_postgresql
    with patch("src.workers.backup_worker.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await backup_postgresql()
        assert result["success"] is False
        assert result["error"] == "timeout"


@pytest.mark.asyncio
async def test_cleanup_removes_old_backups(tmp_path):
    """Old backups (>7 days) are removed."""
    from src.workers.backup_worker import _cleanup_old_backups, BACKUP_RETENTION_DAYS
    old_file = tmp_path / "viraclip_old.sql.gz"
    old_file.write_text("old")
    # Set mtime to 8 days ago
    old_mtime = (datetime.utcnow() - timedelta(days=BACKUP_RETENTION_DAYS + 1)).timestamp()
    old_file.stat()  # touch
    import os
    os.utime(str(old_file), (old_mtime, old_mtime))

    with patch("src.workers.backup_worker.BACKUP_DIR", tmp_path):
        await _cleanup_old_backups()
        assert not old_file.exists()


@pytest.mark.asyncio
async def test_cleanup_keeps_recent_backups(tmp_path):
    """Recent backups (<7 days) are kept."""
    from src.workers.backup_worker import _cleanup_old_backups
    recent_file = tmp_path / "viraclip_recent.sql.gz"
    recent_file.write_text("recent")

    with patch("src.workers.backup_worker.BACKUP_DIR", tmp_path):
        await _cleanup_old_backups()
        assert recent_file.exists()
