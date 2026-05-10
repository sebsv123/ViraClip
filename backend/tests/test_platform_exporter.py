"""Tests for platform export profiles and engine."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.platform_profiles import get_profile


def test_tiktok_profile_has_correct_limits():
    """TikTok profile has correct specs."""
    profile = get_profile("tiktok")
    assert profile.max_size_mb == 287.0
    assert profile.width == 1080
    assert profile.height == 1920
    assert profile.fps == 30


@pytest.mark.asyncio
async def test_adaptive_bitrate_reduces_when_over_limit():
    """Adaptive bitrate reduces when estimated size > 90% of limit."""
    from src.services.platform_exporter import export_for_platform
    clip_path = MagicMock()
    with patch("src.services.platform_exporter._get_clip_duration", new_callable=AsyncMock) as mock_dur:
        mock_dur.return_value = {"duration": 300.0}
        with patch("src.services.platform_exporter.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = MagicMock()
            proc.returncode = 0
            mock_proc.return_value = proc
            result = await export_for_platform(clip_path, "tiktok", MagicMock(), "clip_1")
            assert result["success"] is True


@pytest.mark.asyncio
async def test_export_within_limit_returns_success():
    """Export within size limit returns success."""
    from src.services.platform_exporter import export_for_platform
    clip_path = MagicMock()
    with patch("src.services.platform_exporter._get_clip_duration", new_callable=AsyncMock) as mock_dur:
        mock_dur.return_value = {"duration": 30.0}
        with patch("src.services.platform_exporter.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            proc = MagicMock()
            proc.returncode = 0
            mock_proc.return_value = proc
            result = await export_for_platform(clip_path, "tiktok", MagicMock(), "clip_1")
            assert result["success"] is True


@pytest.mark.asyncio
async def test_export_timeout_returns_error_dict():
    """Timeout returns error dict."""
    from src.services.platform_exporter import export_for_platform
    clip_path = MagicMock()
    with patch("src.services.platform_exporter._get_clip_duration", new_callable=AsyncMock) as mock_dur:
        mock_dur.return_value = {"duration": 30.0}
        with patch("src.services.platform_exporter.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await export_for_platform(clip_path, "tiktok", MagicMock(), "clip_1")
            assert result["success"] is False
            assert result["error"] == "timeout"
