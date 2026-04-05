"""
Tests for ClipValidator and retry logic.

Ensures validation catches errors before they reach users and provides
helpful error messages for debugging.
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.clip_validator import ClipValidator, ValidationResult, get_clip_validator
from src.utils.retry_helper import (
    retry_async,
    retry_sync,
    RetryExhausted,
    FFmpegRetryHelper,
    retry_ffmpeg_operation,
)


# ══════════════════════════════════════════════════════════════════════════════
# ClipValidator Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestClipValidator:
    """Tests for ClipValidator input/output validation."""

    @pytest.fixture
    def validator(self):
        return ClipValidator()

    @pytest.mark.asyncio
    async def test_validate_input_success(self, validator, tmp_path):
        """Valid input should pass validation."""
        # Create mock video file
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake video data" * 1000)

        # Mock ffprobe response
        with patch.object(validator, '_probe_video') as mock_probe:
            mock_probe.return_value = (1920, 1080, 30.0, 60.0, True, True)
            
            result = await validator.validate_input(
                video_path=video_file,
                start_time=10.0,
                end_time=25.0,
            )

        assert result.passed
        assert len(result.issues) == 0
        assert result.metadata["clip_duration"] == 15.0

    @pytest.mark.asyncio
    async def test_validate_input_missing_file(self, validator):
        """Missing file should fail validation."""
        result = await validator.validate_input(
            video_path=Path("/nonexistent/video.mp4"),
            start_time=0.0,
            end_time=10.0,
        )

        assert not result.passed
        assert any("not found" in issue.lower() for issue in result.issues)

    @pytest.mark.asyncio
    async def test_validate_input_invalid_timestamps(self, validator, tmp_path):
        """Invalid timestamps should fail validation."""
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake video data" * 1000)

        with patch.object(validator, '_probe_video') as mock_probe:
            mock_probe.return_value = (1920, 1080, 30.0, 60.0, True, True)
            
            # End before start
            result = await validator.validate_input(
                video_path=video_file,
                start_time=20.0,
                end_time=10.0,
            )

        assert not result.passed
        assert any("invalid end time" in issue.lower() for issue in result.issues)

    @pytest.mark.asyncio
    async def test_validate_input_clip_too_short(self, validator, tmp_path):
        """Clip shorter than minimum should fail."""
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake video data" * 1000)

        with patch.object(validator, '_probe_video') as mock_probe:
            mock_probe.return_value = (1920, 1080, 30.0, 60.0, True, True)
            
            result = await validator.validate_input(
                video_path=video_file,
                start_time=0.0,
                end_time=1.0,  # 1s < 3s minimum
            )

        assert not result.passed
        assert any("too short" in issue.lower() for issue in result.issues)

    @pytest.mark.asyncio
    async def test_validate_input_no_audio_warning(self, validator, tmp_path):
        """Missing audio should produce warning."""
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"fake video data" * 1000)

        with patch.object(validator, '_probe_video') as mock_probe:
            # has_audio=False
            mock_probe.return_value = (1920, 1080, 30.0, 60.0, False, True)
            
            result = await validator.validate_input(
                video_path=video_file,
                start_time=0.0,
                end_time=10.0,
            )

        assert result.passed  # Not a failure, just warning
        assert any("no audio" in warn.lower() for warn in result.warnings)

    @pytest.mark.asyncio
    async def test_validate_output_success(self, validator, tmp_path):
        """Valid output should pass validation."""
        output_file = tmp_path / "output.mp4"
        output_file.write_bytes(b"fake output data" * 1000)

        with patch.object(validator, '_probe_video') as mock_probe:
            mock_probe.return_value = (1080, 1920, 30.0, 15.0, True, True)
            
            with patch.object(validator, '_check_bitrates') as mock_bitrates:
                mock_bitrates.return_value = (128.0, 2000.0)
                
                result = await validator.validate_output(
                    output_path=output_file,
                    expected_duration=15.0,
                )

        assert result.passed
        assert result.metadata["output_duration"] == 15.0
        assert result.metadata["audio_bitrate_kbps"] == 128.0

    @pytest.mark.asyncio
    async def test_validate_output_duration_mismatch(self, validator, tmp_path):
        """Duration mismatch should fail validation."""
        output_file = tmp_path / "output.mp4"
        output_file.write_bytes(b"fake output data" * 1000)

        with patch.object(validator, '_probe_video') as mock_probe:
            # Actual duration 10s, expected 15s
            mock_probe.return_value = (1080, 1920, 30.0, 10.0, True, True)
            
            result = await validator.validate_output(
                output_path=output_file,
                expected_duration=15.0,
            )

        assert not result.passed
        assert any("duration mismatch" in issue.lower() for issue in result.issues)

    @pytest.mark.asyncio
    async def test_validate_subtitle_sync_success(self, validator):
        """Valid word timestamps should pass."""
        words = [
            {"text": "Hello", "start": 0, "end": 500},
            {"text": "world", "start": 500, "end": 1000},
        ]

        result = await validator.validate_subtitle_sync(
            words=words,
            clip_start=0.0,
            clip_duration=2.0,
        )

        assert result.passed
        assert result.metadata["total_words"] == 2

    @pytest.mark.asyncio
    async def test_validate_subtitle_sync_out_of_bounds(self, validator):
        """Words outside clip bounds should produce warning."""
        words = [
            {"text": "Before", "start": -500, "end": 0},  # Before clip
            {"text": "Hello", "start": 0, "end": 1000},
            {"text": "After", "start": 3000, "end": 4000},  # After clip
        ]

        result = await validator.validate_subtitle_sync(
            words=words,
            clip_start=0.0,
            clip_duration=2.0,
        )

        assert not result.passed
        assert len(result.issues) > 0

    @pytest.mark.asyncio
    async def test_validate_subtitle_sync_overlapping(self, validator):
        """Overlapping words should produce warning."""
        words = [
            {"text": "Hello", "start": 0, "end": 1000},
            {"text": "world", "start": 500, "end": 1500},  # Overlaps with "Hello"
        ]

        result = await validator.validate_subtitle_sync(
            words=words,
            clip_start=0.0,
            clip_duration=2.0,
        )

        assert result.passed  # Warnings, not errors
        assert len(result.warnings) > 0


# ══════════════════════════════════════════════════════════════════════════════
# Retry Logic Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestRetryDecorators:
    """Tests for retry decorators."""

    @pytest.mark.asyncio
    async def test_retry_async_success_first_attempt(self):
        """Successful operation should not retry."""
        call_count = 0

        @retry_async(max_attempts=3, delay=0.01)
        async def successful_op():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_op()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_async_success_after_retries(self):
        """Should retry and eventually succeed."""
        call_count = 0

        @retry_async(max_attempts=3, delay=0.01)
        async def flaky_op():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary failure")
            return "success"

        result = await flaky_op()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_async_exhausted(self):
        """Should raise RetryExhausted after max attempts."""
        @retry_async(max_attempts=3, delay=0.01)
        async def always_fails():
            raise ValueError("Permanent failure")

        with pytest.raises(RetryExhausted):
            await always_fails()

    @pytest.mark.asyncio
    async def test_retry_async_specific_exceptions(self):
        """Should only retry specified exceptions."""
        @retry_async(max_attempts=3, delay=0.01, exceptions=(ValueError,))
        async def wrong_exception():
            raise TypeError("Not retryable")

        with pytest.raises(TypeError):
            await wrong_exception()

    def test_retry_sync_success(self):
        """Sync retry should work similarly."""
        call_count = 0

        @retry_sync(max_attempts=3, delay=0.01)
        def flaky_op():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Temporary failure")
            return "success"

        result = flaky_op()
        assert result == "success"
        assert call_count == 2


class TestFFmpegRetryHelper:
    """Tests for FFmpeg-specific retry logic."""

    def test_is_transient_error_true(self):
        """Should identify transient errors."""
        transient_messages = [
            "Resource temporarily unavailable",
            "Connection reset by peer",
            "Broken pipe",
            "I/O error occurred",
        ]

        for msg in transient_messages:
            assert FFmpegRetryHelper.is_transient_error(msg)

    def test_is_transient_error_false(self):
        """Should identify fatal errors."""
        fatal_messages = [
            "Invalid data found when processing input",
            "Codec not found",
            "Option not found 'invalid_opt'",
            "does not contain any stream",
        ]

        for msg in fatal_messages:
            assert not FFmpegRetryHelper.is_transient_error(msg)

    def test_should_retry_signal_kill(self):
        """Should retry when process killed by signal."""
        # Signal 9 (SIGKILL) = exit code 137 (128 + 9)
        assert FFmpegRetryHelper.should_retry(137, "")

    def test_should_retry_transient_stderr(self):
        """Should retry on transient error in stderr."""
        assert FFmpegRetryHelper.should_retry(
            1, "Resource temporarily unavailable"
        )

    def test_should_not_retry_fatal_stderr(self):
        """Should not retry on fatal error."""
        assert not FFmpegRetryHelper.should_retry(
            1, "Invalid data found when processing input"
        )

    @pytest.mark.asyncio
    async def test_retry_ffmpeg_operation_success(self):
        """Should execute FFmpeg operation successfully."""
        async def successful_operation():
            return "output.mp4"

        result = await retry_ffmpeg_operation(
            successful_operation,
            "Test operation",
            max_attempts=3,
        )
        assert result == "output.mp4"

    @pytest.mark.asyncio
    async def test_retry_ffmpeg_operation_transient_then_success(self):
        """Should retry transient FFmpeg errors."""
        call_count = 0

        class MockCalledProcessError(Exception):
            def __init__(self):
                self.returncode = 1
                self.stderr = "Resource temporarily unavailable"

        async def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise MockCalledProcessError()
            return "output.mp4"

        result = await retry_ffmpeg_operation(
            flaky_operation,
            "Flaky FFmpeg",
            max_attempts=3,
        )
        assert result == "output.mp4"
        assert call_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# Integration Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestValidationIntegration:
    """Integration tests for validation in real workflow."""

    @pytest.mark.asyncio
    async def test_validator_singleton(self):
        """get_clip_validator should return singleton."""
        v1 = get_clip_validator()
        v2 = get_clip_validator()
        assert v1 is v2

    @pytest.mark.asyncio
    async def test_full_validation_workflow(self, tmp_path):
        """Test complete validation workflow."""
        validator = ClipValidator()
        
        # Create mock source video
        source = tmp_path / "source.mp4"
        source.write_bytes(b"source video data" * 1000)
        
        # Mock probe to return valid metadata
        with patch.object(validator, '_probe_video') as mock_probe:
            mock_probe.return_value = (1920, 1080, 30.0, 120.0, True, True)
            
            # 1. Validate input
            input_result = await validator.validate_input(
                video_path=source,
                start_time=10.0,
                end_time=25.0,
            )
            
            assert input_result.passed
            assert input_result.metadata["clip_duration"] == 15.0
            
            # 2. Simulate clip creation (create output file)
            output = tmp_path / "clip.mp4"
            output.write_bytes(b"rendered clip data" * 1000)
            
            # 3. Validate output
            mock_probe.return_value = (1080, 1920, 30.0, 15.0, True, True)
            
            with patch.object(validator, '_check_bitrates') as mock_bitrates:
                mock_bitrates.return_value = (128.0, 2000.0)
                
                output_result = await validator.validate_output(
                    output_path=output,
                    expected_duration=15.0,
                    source_path=source,
                )
            
            assert output_result.passed
            assert output_result.metadata["output_duration"] == 15.0
