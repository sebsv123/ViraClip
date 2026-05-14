"""
Unit tests for BUG 3 fix: has_clean_audio detection in confidence_subtitle_service.py.

BUG 3: When a clip has already been processed (B-roll, music, SFX added), re-transcribing
it with faster-whisper produces inaccurate timestamps because the audio is contaminated.
The fix adds a `has_clean_audio` parameter and `_detect_clean_audio()` method with 3
heuristics: filename check, audio stream count check, and codec mix detection.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
import pytest


class TestDetectCleanAudio:
    """Tests for the _detect_clean_audio heuristic method."""

    @pytest.fixture
    def service(self):
        """Create a ConfidenceSubtitleGenerator instance with mocked dependencies."""
        from src.domains.captions.confidence_subtitle_service import (
            ConfidenceSubtitleGenerator,
        )
        svc = ConfidenceSubtitleGenerator.__new__(ConfidenceSubtitleGenerator)
        svc.logger = MagicMock()
        svc.model = None
        return svc

    def test_filename_broll_indicators(self, service):
        """Filenames containing _broll should be detected as NOT clean."""
        assert service._detect_clean_audio("/tmp/test_broll.mp4") is False

    def test_filename_composite_indicators(self, service):
        """Filenames containing _composite should be detected as NOT clean."""
        assert service._detect_clean_audio("/tmp/test_composite.mp4") is False

    def test_filename_final_indicators(self, service):
        """Filenames containing _final should be detected as NOT clean."""
        assert service._detect_clean_audio("/tmp/test_final.mp4") is False

    def test_filename_polished_indicators(self, service):
        """Filenames containing _polished should be detected as NOT clean."""
        assert service._detect_clean_audio("/tmp/test_polished.mp4") is False

    def test_filename_with_music_indicators(self, service):
        """Filenames containing _with_music should be detected as NOT clean."""
        assert service._detect_clean_audio("/tmp/test_with_music.mp4") is False

    def test_filename_with_sfx_indicators(self, service):
        """Filenames containing _with_sfx should be detected as NOT clean."""
        assert service._detect_clean_audio("/tmp/test_with_sfx.mp4") is False

    def test_filename_enhanced_indicators(self, service):
        """Filenames containing _enhanced should be detected as NOT clean."""
        assert service._detect_clean_audio("/tmp/test_enhanced.mp4") is False

    def test_clean_filename(self, service):
        """Clean filenames (raw uploads) should return True (clean)."""
        result = service._detect_clean_audio("/tmp/raw_upload.mp4")
        assert result is True

    def test_clean_filename_with_uuid(self, service):
        """Clean filenames with UUIDs should return True (clean)."""
        result = service._detect_clean_audio("/tmp/abc123-def456.mp4")
        assert result is True

    @patch("src.domains.captions.confidence_subtitle_service._get_ffmpeg_exe")
    def test_audio_stream_count_contaminated(self, mock_get_ffmpeg, service):
        """Files with >1 audio stream should be detected as NOT clean."""
        mock_get_ffmpeg.return_value = "ffmpeg"
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            # Simulate ffprobe output with 2 audio streams
            mock_result.stderr = (
                "Stream #0:0: Video: h264\n"
                "Stream #0:1: Audio: aac\n"
                "Stream #0:2: Audio: aac\n"
            )
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = service._detect_clean_audio("/tmp/test.mp4")
            assert result is False, "Multiple audio streams should indicate contaminated audio"

    @patch("src.domains.captions.confidence_subtitle_service._get_ffmpeg_exe")
    def test_audio_stream_count_single(self, mock_get_ffmpeg, service):
        """Files with exactly 1 audio stream should return True (clean)."""
        mock_get_ffmpeg.return_value = "ffmpeg"
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stderr = (
                "Stream #0:0: Video: h264\n"
                "Stream #0:1: Audio: aac\n"
            )
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = service._detect_clean_audio("/tmp/test.mp4")
            assert result is True, "Single audio stream should be clean"

    @patch("src.domains.captions.confidence_subtitle_service._get_ffmpeg_exe")
    def test_codec_mix_detected(self, mock_get_ffmpeg, service):
        """Mixed codecs (aac + pcm) should be detected as NOT clean."""
        mock_get_ffmpeg.return_value = "ffmpeg"
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stderr = (
                "Stream #0:0: Video: h264\n"
                "Stream #0:1: Audio: aac\n"
                "Stream #0:2: Audio: pcm_s16le\n"
            )
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = service._detect_clean_audio("/tmp/test.mp4")
            assert result is False, "Mixed aac + pcm codecs should indicate contaminated audio"

    @patch("src.domains.captions.confidence_subtitle_service._get_ffmpeg_exe")
    def test_ffmpeg_error_returns_true(self, mock_get_ffmpeg, service):
        """If ffprobe fails, should return True (assume clean) gracefully."""
        mock_get_ffmpeg.return_value = "ffmpeg"
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("ffmpeg not available")

            result = service._detect_clean_audio("/tmp/test.mp4")
            assert result is True, "Should gracefully handle ffmpeg errors"


class TestRealignOnSegment:
    """Tests for the realign_on_segment method with has_clean_audio parameter."""

    @pytest.fixture
    def service(self):
        """Create a ConfidenceSubtitleGenerator instance with mocked dependencies."""
        from src.domains.captions.confidence_subtitle_service import (
            ConfidenceSubtitleGenerator,
        )
        svc = ConfidenceSubtitleGenerator.__new__(ConfidenceSubtitleGenerator)
        svc.logger = MagicMock()
        svc.model = MagicMock()
        svc._detect_clean_audio = MagicMock(return_value=True)
        return svc

    @patch("src.domains.captions.confidence_subtitle_service.ConfidenceSubtitleGenerator._load_model")
    @patch("subprocess.run")
    def test_has_clean_audio_false_skips_transcription(
        self, mock_subprocess, mock_load_model, service
    ):
        """When has_clean_audio=False, should skip re-transcription and return original words."""
        original_words = [
            {"word": "hello", "start": 0.0, "end": 0.5, "confidence": 0.9},
            {"word": "world", "start": 0.5, "end": 1.0, "confidence": 0.8},
        ]

        result = service.realign_on_segment(
            segment_video_path="/tmp/test.mp3",
            original_words=original_words,
            has_clean_audio=False,
        )

        # Should return original words unchanged
        assert result == original_words
        # Should NOT have called _load_model or subprocess
        mock_load_model.assert_not_called()
        mock_subprocess.assert_not_called()

    @patch("src.domains.captions.confidence_subtitle_service.ConfidenceSubtitleGenerator._load_model")
    @patch("subprocess.run")
    def test_has_clean_audio_true_does_transcribe(
        self, mock_subprocess, mock_load_model, service
    ):
        """When has_clean_audio=True, should proceed with re-transcription."""
        # Mock ffmpeg extraction to succeed
        mock_ffmpeg_result = MagicMock()
        mock_ffmpeg_result.returncode = 0
        mock_subprocess.return_value = mock_ffmpeg_result

        # Mock whisper transcription
        mock_segment = MagicMock()
        mock_word1 = MagicMock()
        mock_word1.word = "hello"
        mock_word1.start = 0.0
        mock_word1.end = 0.5
        mock_word1.probability = 0.95
        mock_word2 = MagicMock()
        mock_word2.word = "world"
        mock_word2.start = 0.5
        mock_word2.end = 1.0
        mock_word2.probability = 0.92
        mock_segment.words = [mock_word1, mock_word2]

        mock_info = MagicMock()
        service.model.transcribe.return_value = ([mock_segment], mock_info)

        original_words = [
            {"word": "hello", "start": 0.0, "end": 0.5, "confidence": 0.9},
            {"word": "world", "start": 0.5, "end": 1.0, "confidence": 0.8},
        ]

        result = service.realign_on_segment(
            segment_video_path="/tmp/test.mp3",
            original_words=original_words,
            has_clean_audio=True,
        )

        # Should have called _load_model
        mock_load_model.assert_called_once()
        # Should return new transcription (not original)
        assert result != original_words
        assert len(result) == 2

    @patch("src.domains.captions.confidence_subtitle_service.ConfidenceSubtitleGenerator._load_model")
    @patch("subprocess.run")
    def test_has_clean_audio_none_auto_detects(
        self, mock_subprocess, mock_load_model, service
    ):
        """When has_clean_audio=None, should auto-detect via _detect_clean_audio."""
        service._detect_clean_audio = MagicMock(return_value=True)

        mock_ffmpeg_result = MagicMock()
        mock_ffmpeg_result.returncode = 0
        mock_subprocess.return_value = mock_ffmpeg_result

        mock_segment = MagicMock()
        mock_word1 = MagicMock()
        mock_word1.word = "hello"
        mock_word1.start = 0.0
        mock_word1.end = 0.5
        mock_word1.probability = 0.95
        mock_segment.words = [mock_word1]
        mock_info = MagicMock()
        service.model.transcribe.return_value = ([mock_segment], mock_info)

        original_words = [
            {"word": "hello", "start": 0.0, "end": 0.5, "confidence": 0.9},
        ]

        result = service.realign_on_segment(
            segment_video_path="/tmp/test.mp3",
            original_words=original_words,
            has_clean_audio=None,
        )

        # Should have called _load_model since audio is clean
        mock_load_model.assert_called_once()

    @patch("src.domains.captions.confidence_subtitle_service.ConfidenceSubtitleGenerator._load_model")
    def test_has_clean_audio_none_detects_contaminated(
        self, mock_load_model, service
    ):
        """When auto-detect finds contaminated audio, should skip transcription."""
        service._detect_clean_audio = MagicMock(return_value=False)

        original_words = [
            {"word": "hello", "start": 0.0, "end": 0.5, "confidence": 0.9},
        ]

        result = service.realign_on_segment(
            segment_video_path="/tmp/test.mp3",
            original_words=original_words,
            has_clean_audio=None,
        )

        # Should NOT have called _load_model
        mock_load_model.assert_not_called()
        # Should return original words
        assert result == original_words
