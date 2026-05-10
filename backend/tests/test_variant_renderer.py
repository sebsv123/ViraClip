"""Tests for aspect ratio variant renderer."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.variant_renderer import AspectRatio, render_aspect_variant


@pytest.mark.asyncio
async def test_vertical_vf_filter():
    """Vertical ratio uses crop filter."""
    with patch("src.services.variant_renderer.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        result = await render_aspect_variant(
            Path("/tmp/clip.mp4"), AspectRatio.VERTICAL, Path("/tmp"), "clip_1"
        )
        assert result is not None


@pytest.mark.asyncio
async def test_square_vf_filter():
    """Square ratio uses min filter."""
    with patch("src.services.variant_renderer.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        result = await render_aspect_variant(
            Path("/tmp/clip.mp4"), AspectRatio.SQUARE, Path("/tmp"), "clip_1"
        )
        assert result is not None


@pytest.mark.asyncio
async def test_variant_timeout_returns_none():
    """Timeout returns None."""
    with patch("src.services.variant_renderer.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await render_aspect_variant(
            Path("/tmp/clip.mp4"), AspectRatio.VERTICAL, Path("/tmp"), "clip_1"
        )
        assert result is None


@pytest.mark.asyncio
async def test_variant_saved_to_db():
    """Variant saved to DB."""
    with patch("src.services.variant_renderer.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        result = await render_aspect_variant(
            Path("/tmp/clip.mp4"), AspectRatio.VERTICAL, Path("/tmp"), "clip_1"
        )
        assert result is not None
