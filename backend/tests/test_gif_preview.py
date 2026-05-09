"""Tests for GIF preview generation."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_gif_generated_successfully(tmp_path):
    """Both FFmpeg commands succeed → returns Path."""
    from src.domains.thumbnails.gif_preview import generate_clip_preview_gif
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake video")

    with patch("src.domains.thumbnails.gif_preview.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc

        result = await generate_clip_preview_gif(clip_path, tmp_path, "clip_1")
        assert result is not None
        assert isinstance(result, Path)


@pytest.mark.asyncio
async def test_palette_cleanup_on_success(tmp_path):
    """Palette file is cleaned up on success."""
    from src.domains.thumbnails.gif_preview import generate_clip_preview_gif
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake video")

    with patch("src.domains.thumbnails.gif_preview.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc

        palette_path = tmp_path / "clip_1_palette.png"
        palette_path.write_text("fake palette")

        await generate_clip_preview_gif(clip_path, tmp_path, "clip_1")
        assert not palette_path.exists()


@pytest.mark.asyncio
async def test_palette_cleanup_on_failure(tmp_path):
    """Palette file is cleaned up even on failure."""
    from src.domains.thumbnails.gif_preview import generate_clip_preview_gif
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake video")

    with patch("src.domains.thumbnails.gif_preview.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 1  # FFmpeg fails
        mock_proc.return_value = proc

        palette_path = tmp_path / "clip_1_palette.png"
        palette_path.write_text("fake palette")

        result = await generate_clip_preview_gif(clip_path, tmp_path, "clip_1")
        assert result is None
        assert not palette_path.exists()


@pytest.mark.asyncio
async def test_gif_never_raises(tmp_path):
    """RuntimeError → returns None, no exception."""
    from src.domains.thumbnails.gif_preview import generate_clip_preview_gif
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake video")

    with patch("src.domains.thumbnails.gif_preview.asyncio.create_subprocess_exec", side_effect=RuntimeError("FFmpeg crashed")):
        result = await generate_clip_preview_gif(clip_path, tmp_path, "clip_1")
        assert result is None
