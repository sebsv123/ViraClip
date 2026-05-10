"""Tests for audio loudness normalization."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_muted_clip_detected():
    """input_i=-55 → is_muted=True."""
    from src.services.audio_normalizer import measure_audio_loudness
    with patch("src.services.audio_normalizer.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.stderr = b'{"input_i": -55.0, "input_tp": -60.0}\n'
        mock_proc.return_value = proc
        result = await measure_audio_loudness(MagicMock())
        assert result["is_muted"] is True


@pytest.mark.asyncio
async def test_loud_clip_needs_normalization():
    """input_i=-6 → needs_normalization=True."""
    from src.services.audio_normalizer import measure_audio_loudness
    with patch("src.services.audio_normalizer.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.stderr = b'{"input_i": -6.0, "input_tp": -2.0}\n'
        mock_proc.return_value = proc
        result = await measure_audio_loudness(MagicMock())
        assert result["needs_normalization"] is True


@pytest.mark.asyncio
async def test_correct_volume_no_normalization():
    """input_i=-14.5 → needs_normalization=False."""
    from src.services.audio_normalizer import measure_audio_loudness
    with patch("src.services.audio_normalizer.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.stderr = b'{"input_i": -14.5, "input_tp": -2.0}\n'
        mock_proc.return_value = proc
        result = await measure_audio_loudness(MagicMock())
        assert result["needs_normalization"] is False


@pytest.mark.asyncio
async def test_loudnorm_timeout_returns_safe_defaults():
    """Timeout → safe defaults."""
    from src.services.audio_normalizer import measure_audio_loudness
    with patch("src.services.audio_normalizer.asyncio.wait_for", side_effect=TimeoutError):
        result = await measure_audio_loudness(MagicMock())
        assert result["is_muted"] is False
        assert result["needs_normalization"] is False


@pytest.mark.asyncio
async def test_normalize_audio_success():
    """Normalize audio succeeds."""
    from src.services.audio_normalizer import normalize_audio
    with patch("src.services.audio_normalizer.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        with patch("src.services.audio_normalizer.Path.exists", return_value=True):
            with patch("src.services.audio_normalizer.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 10000
                result = await normalize_audio(MagicMock(), MagicMock())
                assert result is True
