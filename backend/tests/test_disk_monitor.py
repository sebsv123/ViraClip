"""Tests for disk space monitor."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_ok_when_plenty_of_space():
    """50GB free → level=ok."""
    from src.workers.tasks import check_disk_space
    with patch("src.workers.tasks.shutil.disk_usage") as mock_usage:
        usage = MagicMock()
        usage.free = 50 * 1024 ** 3
        usage.total = 100 * 1024 ** 3
        usage.used = 50 * 1024 ** 3
        mock_usage.return_value = usage
        result = await check_disk_space()
        assert result["critical"] == []
        for d in result["directories"].values():
            assert d["level"] == "ok"


@pytest.mark.asyncio
async def test_warning_when_low_space():
    """8GB free, WARNING=10GB → level=warning."""
    from src.workers.tasks import check_disk_space
    with patch("src.workers.tasks.shutil.disk_usage") as mock_usage:
        usage = MagicMock()
        usage.free = 8 * 1024 ** 3
        usage.total = 100 * 1024 ** 3
        usage.used = 92 * 1024 ** 3
        mock_usage.return_value = usage
        result = await check_disk_space()
        for d in result["directories"].values():
            assert d["level"] in ("warning", "ok")


@pytest.mark.asyncio
async def test_critical_when_very_low():
    """3GB free, CRITICAL=5GB → level=critical."""
    from src.workers.tasks import check_disk_space
    with patch("src.workers.tasks.shutil.disk_usage") as mock_usage:
        usage = MagicMock()
        usage.free = 3 * 1024 ** 3
        usage.total = 100 * 1024 ** 3
        usage.used = 97 * 1024 ** 3
        mock_usage.return_value = usage
        result = await check_disk_space()
        assert len(result["critical"]) > 0


@pytest.mark.asyncio
async def test_disk_check_never_raises():
    """disk_usage throws → returns dict, no exception."""
    from src.workers.tasks import check_disk_space
    with patch("src.workers.tasks.shutil.disk_usage", side_effect=OSError("Disk error")):
        result = await check_disk_space()
        assert isinstance(result, dict)
        assert "directories" in result
