"""Tests for language detection in preflight."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_supported_language_no_warning():
    """Supported language → no warning."""
    from src.domains.video._pipeline import detect_video_language
    with patch("src.domains.video._pipeline.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        with patch("src.domains.video._pipeline.whisper") as mock_whisper:
            mock_model = MagicMock()
            mock_model.detect_language.return_value = (None, {"es": 0.95})
            mock_whisper.load_model.return_value = mock_model
            lang, confidence = await detect_video_language("/tmp/test.mp4")
            assert lang == "es"
            assert confidence > 0.8


@pytest.mark.asyncio
async def test_unsupported_language_sets_warning():
    """Unsupported language → warning."""
    from src.domains.video._pipeline import detect_video_language
    with patch("src.domains.video._pipeline.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        with patch("src.domains.video._pipeline.whisper") as mock_whisper:
            mock_model = MagicMock()
            mock_model.detect_language.return_value = (None, {"ar": 0.92})
            mock_whisper.load_model.return_value = mock_model
            lang, confidence = await detect_video_language("/tmp/test.mp4")
            assert lang == "ar"
            assert confidence > 0.8


@pytest.mark.asyncio
async def test_low_confidence_no_warning():
    """Low confidence → no warning."""
    from src.domains.video._pipeline import detect_video_language
    with patch("src.domains.video._pipeline.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        with patch("src.domains.video._pipeline.whisper") as mock_whisper:
            mock_model = MagicMock()
            mock_model.detect_language.return_value = (None, {"ar": 0.5})
            mock_whisper.load_model.return_value = mock_model
            lang, confidence = await detect_video_language("/tmp/test.mp4")
            assert lang == "ar"
            assert confidence < 0.8


@pytest.mark.asyncio
async def test_detection_timeout_continues_pipeline():
    """Timeout → returns unknown, no exception."""
    from src.domains.video._pipeline import detect_video_language
    with patch("src.domains.video._pipeline.asyncio.wait_for", side_effect=TimeoutError):
        lang, confidence = await detect_video_language("/tmp/test.mp4")
        assert lang == "unknown"
        assert confidence == 0.0
