"""Tests for aspect ratio detection in preflight."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_landscape_16_9_uses_smart_crop():
    """16:9 landscape → smart_crop."""
    from src.domains.video._pipeline import detect_aspect_ratio
    with patch("src.domains.video._pipeline.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b'{"streams": [{"width": 1920, "height": 1080}]}'
        mock_proc.return_value = proc
        result = await detect_aspect_ratio("/tmp/test.mp4")
        assert result["strategy"] == "smart_crop"
        assert result["ratio"] == pytest.approx(1.778, rel=0.01)


@pytest.mark.asyncio
async def test_vertical_9_16_uses_no_crop():
    """9:16 vertical → no_crop."""
    from src.domains.video._pipeline import detect_aspect_ratio
    with patch("src.domains.video._pipeline.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b'{"streams": [{"width": 1080, "height": 1920}]}'
        mock_proc.return_value = proc
        result = await detect_aspect_ratio("/tmp/test.mp4")
        assert result["strategy"] == "no_crop"


@pytest.mark.asyncio
async def test_square_uses_letterbox():
    """1:1 square → letterbox."""
    from src.domains.video._pipeline import detect_aspect_ratio
    with patch("src.domains.video._pipeline.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b'{"streams": [{"width": 1080, "height": 1080}]}'
        mock_proc.return_value = proc
        result = await detect_aspect_ratio("/tmp/test.mp4")
        assert result["strategy"] == "letterbox"


@pytest.mark.asyncio
async def test_ffprobe_failure_returns_smart_crop_default():
    """ffprobe failure → smart_crop default."""
    from src.domains.video._pipeline import detect_aspect_ratio
    with patch("src.domains.video._pipeline.asyncio.create_subprocess_exec", side_effect=Exception("ffprobe not found")):
        result = await detect_aspect_ratio("/tmp/test.mp4")
        assert result["strategy"] == "smart_crop"
        assert result["width"] == 0
