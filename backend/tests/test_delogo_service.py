"""Tests for watermark removal service."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.delogo_service import (
    build_delogo_filter,
    remove_watermarks,
    _zone_has_non_black_content,
)


@pytest.mark.asyncio
async def test_build_delogo_filter_single_target():
    """Single target builds correct filter."""
    vf = await build_delogo_filter(["tiktok_br"])
    assert vf is not None
    assert "delogo=x=780:y=1780" in vf


@pytest.mark.asyncio
async def test_build_delogo_filter_multiple_targets():
    """Multiple targets chained with comma."""
    vf = await build_delogo_filter(["tiktok_br", "tiktok_bc"])
    assert vf is not None
    assert vf.count("delogo=") == 2


@pytest.mark.asyncio
async def test_build_delogo_filter_unknown_target_returns_none():
    """Unknown target returns None."""
    vf = await build_delogo_filter(["unknown_platform"])
    assert vf is None


@pytest.mark.asyncio
async def test_remove_watermarks_disabled_by_default():
    """DELOGO_ENABLED=false returns False."""
    with patch("src.core.delogo_service.DELOGO_ENABLED", False):
        result = await remove_watermarks(MagicMock(), MagicMock())
        assert result is False


@pytest.mark.asyncio
async def test_zone_brightness_above_30_detected():
    """Brightness > 30 returns True."""
    with patch("src.core.delogo_service.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.stdout = b"\x80" * 100  # avg = 128 > 30
        mock_proc.return_value = proc
        result = await _zone_has_non_black_content(MagicMock(), 0, 0, 100, 100)
        assert result is True
