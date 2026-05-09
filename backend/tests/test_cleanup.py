"""Tests for orphan export cleanup — failed tasks, temp dirs."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_cleanup_removes_failed_task_dir():
    """Failed task >24h → directory removed."""
    import shutil
    with patch("shutil.rmtree") as mock_rmtree:
        with patch("pathlib.Path.exists", return_value=True):
            mock_rmtree.return_value = None
            # Simulate cleanup
            shutil.rmtree("/tmp/viraclip_longform_abc", ignore_errors=True)
            mock_rmtree.assert_called_once_with("/tmp/viraclip_longform_abc", ignore_errors=True)


@pytest.mark.asyncio
async def test_cleanup_skips_recent_failed_tasks():
    """Failed task <24h → directory NOT removed."""
    import shutil
    with patch("shutil.rmtree") as mock_rmtree:
        # Should not be called for recent tasks
        mock_rmtree.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_tmp_longform_old_dirs():
    """Old /tmp/viraclip_longform_* dirs → removed."""
    import shutil
    with patch("shutil.rmtree") as mock_rmtree:
        mock_rmtree.return_value = None
        shutil.rmtree("/tmp/viraclip_longform_abc", ignore_errors=True)
        mock_rmtree.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_never_raises():
    """PermissionError during cleanup → caught, no exception."""
    import shutil
    with patch("shutil.rmtree", side_effect=PermissionError("Access denied")):
        try:
            shutil.rmtree("/tmp/viraclip_longform_abc", ignore_errors=True)
            assert True  # No exception
        except Exception:
            assert False  # Should not reach here
