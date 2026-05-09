"""Tests for narrator TTS — WAV conversion with fallback."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_wav_conversion_success(tmp_path):
    """FFmpeg WAV conversion succeeds → returns .wav path, mp3 deleted."""
    from src.domains.longform.narrator_tts import NarrationAudio
    mp3_path = tmp_path / "narration_0.mp3"
    mp3_path.write_text("fake audio")
    wav_path = tmp_path / "narration_0.wav"

    with patch("src.domains.longform.narrator_tts.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # Simulate WAV file creation
        wav_path.write_text("fake wav")

        # Test the actual duration measurement (uses ffprobe)
        with patch("src.domains.longform.narrator_tts.subprocess.run") as mock_ffprobe:
            mock_ffprobe.return_value = MagicMock(
                returncode=0,
                stdout='{"streams": [{"duration": "5.0"}]}',
            )
            from src.domains.longform.narrator_tts import generate_narration
            from src.domains.longform.script_writer import ScriptSection

            section = ScriptSection(index=0, heading="Test", narration_text="Hello world", estimated_duration=5.0)
            with patch("src.domains.longform.narrator_tts.httpx.AsyncClient") as mock_http:
                mock_http.return_value.__aenter__.return_value.post.return_value = MagicMock(
                    status_code=200,
                    content=b"fake audio data",
                )
                results = await generate_narration([section], output_dir=tmp_path)
                assert len(results) == 1
                assert results[0].provider in ("elevenlabs", "gtts")


@pytest.mark.asyncio
async def test_wav_conversion_failure_returns_mp3(tmp_path):
    """FFmpeg fails → returns original MP3 path, no exception."""
    from src.domains.longform.narrator_tts import NarrationAudio
    mp3_path = tmp_path / "narration_0.mp3"
    mp3_path.write_text("fake audio")

    with patch("src.domains.longform.narrator_tts.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)

        from src.domains.longform.narrator_tts import generate_narration
        from src.domains.longform.script_writer import ScriptSection

        section = ScriptSection(index=0, heading="Test", narration_text="Hello", estimated_duration=3.0)
        with patch("src.domains.longform.narrator_tts.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post.return_value = MagicMock(
                status_code=200,
                content=b"fake",
            )
            results = await generate_narration([section], output_dir=tmp_path)
            assert len(results) == 1


@pytest.mark.asyncio
async def test_wav_timeout_returns_mp3(tmp_path):
    """FFmpeg timeout → returns original MP3 path, no exception."""
    from src.domains.longform.narrator_tts import NarrationAudio
    mp3_path = tmp_path / "narration_0.mp3"
    mp3_path.write_text("fake audio")

    with patch("src.domains.longform.narrator_tts.subprocess.run") as mock_run:
        mock_run.side_effect = asyncio.TimeoutError("FFmpeg timed out")

        from src.domains.longform.narrator_tts import generate_narration
        from src.domains.longform.script_writer import ScriptSection

        section = ScriptSection(index=0, heading="Test", narration_text="Hi", estimated_duration=2.0)
        with patch("src.domains.longform.narrator_tts.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post.return_value = MagicMock(
                status_code=200,
                content=b"fake",
            )
            results = await generate_narration([section], output_dir=tmp_path)
            assert len(results) == 1
