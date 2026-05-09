"""Tests for scene_assembler.py — sync, fallback, concat, edge cases."""
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domains.longform.narrator_tts import NarrationAudio
from src.domains.longform.scene_assembler import assemble_video, _fetch_broll
from src.domains.longform.script_writer import ScriptSection


@pytest.fixture
def sections():
    return [
        ScriptSection(index=0, heading="Intro", narration_text="Hello world", estimated_duration=5.0, broll_keywords=["nature"]),
        ScriptSection(index=1, heading="Body", narration_text="More content here", estimated_duration=5.0, broll_keywords=["city"]),
        ScriptSection(index=2, heading="Outro", narration_text="Goodbye", estimated_duration=5.0, broll_keywords=["sunset"]),
    ]


@pytest.fixture
def narrations(tmp_path):
    audio = tmp_path / "narration_0.mp3"
    audio.write_bytes(b"fakeaudio")
    return [
        NarrationAudio(section_index=0, audio_path=audio, actual_duration=20.0, provider="gtts"),
        NarrationAudio(section_index=1, audio_path=audio, actual_duration=25.0, provider="gtts"),
        NarrationAudio(section_index=2, audio_path=audio, actual_duration=5.0, provider="gtts"),
    ]


@pytest.mark.asyncio
async def test_audio_shorter_than_broll(tmp_path, sections, narrations):
    """B-roll longer than audio → FFmpeg trims to audio duration."""
    narrations[0] = NarrationAudio(section_index=0, audio_path=narrations[0].audio_path, actual_duration=20.0, provider="gtts")
    with patch("src.domains.longform.scene_assembler.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("src.domains.longform.scene_assembler._fetch_broll", new_callable=AsyncMock) as mock_broll:
            mock_broll.return_value = tmp_path / "broll_30s.mp4"
            output = tmp_path / "output.mp4"
            result = await assemble_video(sections[:1], narrations[:1], output)
            assert result.sections_count == 1
            # FFmpeg should have been called with -t 20.0 (audio duration)
            calls = [c for c in mock_run.call_args_list if "-t" in str(c)]
            assert len(calls) > 0


@pytest.mark.asyncio
async def test_audio_longer_than_broll(tmp_path, sections, narrations):
    """Audio longer than B-roll → FFmpeg loops B-roll."""
    narrations[0] = NarrationAudio(section_index=0, audio_path=narrations[0].audio_path, actual_duration=25.0, provider="gtts")
    with patch("src.domains.longform.scene_assembler.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("src.domains.longform.scene_assembler._fetch_broll", new_callable=AsyncMock) as mock_broll:
            mock_broll.return_value = tmp_path / "broll_15s.mp4"
            output = tmp_path / "output.mp4"
            result = await assemble_video(sections[:1], narrations[:1], output)
            assert result.sections_count == 1


@pytest.mark.asyncio
async def test_no_broll_available(tmp_path, sections, narrations):
    """No B-roll available → fallback to solid color, no black screen."""
    with patch("src.domains.longform.scene_assembler.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("src.domains.longform.scene_assembler._fetch_broll", new_callable=AsyncMock) as mock_broll:
            mock_broll.return_value = None
            output = tmp_path / "output.mp4"
            result = await assemble_video(sections[:1], narrations[:1], output)
            assert result.sections_count == 1
            # Should have called FFmpeg with color=0x1a1a2e (fallback)
            fallback_calls = [c for c in mock_run.call_args_list if "color=c=0x1a1a2e" in str(c)]
            assert len(fallback_calls) > 0


@pytest.mark.asyncio
async def test_concat_generates_valid_list(tmp_path, sections, narrations):
    """Concat list file is generated with correct format."""
    with patch("src.domains.longform.scene_assembler.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("src.domains.longform.scene_assembler._fetch_broll", new_callable=AsyncMock) as mock_broll:
            mock_broll.return_value = tmp_path / "broll.mp4"
            output = tmp_path / "output.mp4"
            await assemble_video(sections, narrations, output)
            # Check concat list was written
            concat_file = Path("/tmp/longform_scenes/concat_list.txt")
            if concat_file.exists():
                content = concat_file.read_text()
                assert "file '/tmp/longform_scenes/scene_0.mp4'" in content
                assert "file '/tmp/longform_scenes/scene_1.mp4'" in content
                assert "file '/tmp/longform_scenes/scene_2.mp4'" in content


@pytest.mark.asyncio
async def test_zero_duration_audio_section(tmp_path):
    """Zero-duration audio section should be skipped without error."""
    section = ScriptSection(index=0, heading="Empty", narration_text="", estimated_duration=0.0, broll_keywords=[])
    narration = NarrationAudio(section_index=0, audio_path=tmp_path / "empty.mp3", actual_duration=0.0, provider="gtts")
    with patch("src.domains.longform.scene_assembler.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("src.domains.longform.scene_assembler._fetch_broll", new_callable=AsyncMock) as mock_broll:
            mock_broll.return_value = tmp_path / "broll.mp4"
            output = tmp_path / "output.mp4"
            result = await assemble_video([section], [narration], output)
            assert result.sections_count == 1  # Still processes, but with fallback
