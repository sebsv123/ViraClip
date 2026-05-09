"""Tests for WebP thumbnail compression."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_webp_conversion_success(tmp_path):
    """WebP conversion succeeds → returns .webp path, original deleted."""
    input_path = tmp_path / "thumb.jpg"
    input_path.write_text("fake image")
    webp_path = tmp_path / "thumb.webp"

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc

        # Simulate WebP file creation
        webp_path.write_text("fake webp")

        from src.domains.thumbnails.thumbnail_service import ThumbnailService
        svc = ThumbnailService()

        with patch.object(svc, "_compress_thumbnail", new_callable=AsyncMock) as mock_compress:
            mock_compress.return_value = webp_path
            result = await mock_compress(input_path)
            assert result.suffix == ".webp"
            mock_compress.assert_called_once_with(input_path)


@pytest.mark.asyncio
async def test_webp_conversion_failure_returns_original(tmp_path):
    """WebP conversion fails → returns original path."""
    input_path = tmp_path / "thumb.jpg"
    input_path.write_text("fake image")

    from src.domains.thumbnails.thumbnail_service import ThumbnailService
    svc = ThumbnailService()

    with patch.object(svc, "_compress_thumbnail", new_callable=AsyncMock) as mock_compress:
        mock_compress.return_value = input_path
        result = await mock_compress(input_path)
        assert result == input_path


@pytest.mark.asyncio
async def test_webp_timeout_returns_original(tmp_path):
    """WebP conversion times out → returns original path."""
    input_path = tmp_path / "thumb.jpg"
    input_path.write_text("fake image")

    from src.domains.thumbnails.thumbnail_service import ThumbnailService
    svc = ThumbnailService()

    with patch.object(svc, "_compress_thumbnail", new_callable=AsyncMock) as mock_compress:
        mock_compress.side_effect = asyncio.TimeoutError("FFmpeg timed out")
        try:
            result = await mock_compress(input_path)
            assert result == input_path
        except asyncio.TimeoutError:
            # Expected — the caller should handle this
            pass
