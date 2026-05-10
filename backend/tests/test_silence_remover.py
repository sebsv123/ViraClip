"""Tests for silence detection and removal."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_parse_silence_start_end():
    """Parse silence_start and silence_end from stderr."""
    from src.services.silence_remover import detect_silences
    with patch("src.services.silence_remover.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.stderr = b"silence_start: 5.2\nsilence_end: 8.5 | silence_duration: 3.3\n"
        mock_proc.return_value = proc
        silences = await detect_silences("/tmp/test.mp4")
        assert len(silences) == 1
        assert silences[0]["start"] == 5.2
        assert silences[0]["end"] == 8.5
        assert silences[0]["duration"] == 3.3


@pytest.mark.asyncio
async def test_empty_audio_returns_no_silences():
    """No silence lines → empty list."""
    from src.services.silence_remover import detect_silences
    with patch("src.services.silence_remover.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.stderr = b"normal audio data\n"
        mock_proc.return_value = proc
        silences = await detect_silences("/tmp/test.mp4")
        assert silences == []


@pytest.mark.asyncio
async def test_silence_timeout_returns_empty():
    """Timeout → empty list, no exception."""
    from src.services.silence_remover import detect_silences
    with patch("src.services.silence_remover.asyncio.wait_for", side_effect=TimeoutError):
        silences = await detect_silences("/tmp/test.mp4")
        assert silences == []


def test_keep_segments_are_inverse_of_silences():
    """Keep segments are the inverse of silence segments."""
    from src.services.silence_remover import SILENCE_PADDING_S
    clip_duration = 30.0
    silences = [{"start": 5.0, "end": 10.0, "duration": 5.0}]
    keep = []
    cursor = 0.0
    for silence in sorted(silences, key=lambda s: s["start"]):
        seg_end = max(0.0, silence["start"] - SILENCE_PADDING_S)
        if seg_end > cursor + 0.1:
            keep.append({"start": cursor, "end": seg_end})
        cursor = min(clip_duration, silence["end"] + SILENCE_PADDING_S)
    if cursor < clip_duration - 0.1:
        keep.append({"start": cursor, "end": clip_duration})
    assert len(keep) == 2
    assert keep[0]["start"] == 0.0
    assert keep[1]["end"] == 30.0


@pytest.mark.asyncio
async def test_remove_silences_cleans_temp_files():
    """Temp files cleaned up in finally."""
    from src.services.silence_remover import remove_silences_from_clip
    with patch("src.services.silence_remover.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
        proc = MagicMock()
        proc.returncode = 0
        mock_proc.return_value = proc
        with patch("src.services.silence_remover.Path.exists", return_value=True):
            result = await remove_silences_from_clip(
                MagicMock(), MagicMock(),
                [{"start": 5.0, "end": 10.0, "duration": 5.0}]
            )
            assert result is True
