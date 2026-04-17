"""
Tests for intelligent retry policy.

Validates that retry logic correctly handles different error types.
"""

import pytest
from src.workers.retry_policy import (
    should_retry_task,
    get_max_attempts_for_error,
    format_error_for_storage,
)
from src.exceptions import (
    VideoNotFoundError,
    DownloadTimeoutError,
    TranscriptionFailedError,
    LLMTimeoutError,
    NoSegmentsFoundError,
    RenderFailedError,
    GPUError,
    OutOfMemoryError,
)


def test_should_retry_retryable_exception():
    """Test that retryable exceptions trigger retry."""
    exc = DownloadTimeoutError("https://youtube.com/watch?v=test", timeout_seconds=30)
    
    should_retry, delay = should_retry_task(exc, attempt=1, max_attempts=3)
    
    assert should_retry is True
    assert delay is not None
    assert delay > 0  # Should have exponential backoff


def test_should_not_retry_non_retryable_exception():
    """Test that non-retryable exceptions don't trigger retry."""
    exc = VideoNotFoundError("https://youtube.com/watch?v=missing")
    
    should_retry, delay = should_retry_task(exc, attempt=1, max_attempts=3)
    
    assert should_retry is False
    assert delay is None


def test_should_not_retry_at_max_attempts():
    """Test that retry stops at max attempts."""
    exc = TranscriptionFailedError("AssemblyAI", "Rate limit", "/tmp/video.mp4")
    
    should_retry, delay = should_retry_task(exc, attempt=3, max_attempts=3)
    
    assert should_retry is False
    assert delay is None


def test_exponential_backoff_for_download_timeout():
    """Test exponential backoff for download timeouts."""
    exc = DownloadTimeoutError("https://youtube.com/watch?v=test", timeout_seconds=30)
    
    _, delay1 = should_retry_task(exc, attempt=1, max_attempts=3)
    _, delay2 = should_retry_task(exc, attempt=2, max_attempts=3)
    
    # Exponential: 2^1 = 2s, 2^2 = 4s
    assert delay2 > delay1


def test_longer_delay_for_transcription_errors():
    """Test that transcription errors use longer delays (API rate limits)."""
    exc = TranscriptionFailedError("AssemblyAI", "Rate limit", "/tmp/video.mp4")
    
    _, delay = should_retry_task(exc, attempt=1, max_attempts=3)
    
    # Transcription errors: 10s, 20s, 30s
    assert delay >= 10


def test_short_delay_for_gpu_errors():
    """Test GPU errors use short delays."""
    exc = GPUError(reason="CUDA error", gpu_type="nvidia")
    
    _, delay = should_retry_task(exc, attempt=1, max_attempts=2)
    
    # GPU errors: fixed 5s
    assert delay == 5


def test_get_max_attempts_transcription():
    """Test max attempts for transcription errors."""
    exc = TranscriptionFailedError("AssemblyAI", "Error", "/tmp/video.mp4")
    
    max_attempts = get_max_attempts_for_error(exc)
    
    assert max_attempts == 3  # Aggressive retries for API


def test_get_max_attempts_render():
    """Test max attempts for render errors."""
    exc = RenderFailedError("/tmp/clip.mp4", "Codec error")
    
    max_attempts = get_max_attempts_for_error(exc)
    
    # Render errors shouldn't retry much (default 3)
    assert max_attempts == 3


def test_get_max_attempts_gpu():
    """Test max attempts for GPU errors."""
    exc = GPUError("Driver crash")
    
    max_attempts = get_max_attempts_for_error(exc)
    
    assert max_attempts == 2  # Single retry for GPU


def test_format_error_for_storage_viraclip_exception():
    """Test error formatting for ViraClip exceptions."""
    exc = LLMTimeoutError(model="gpt-4", timeout_seconds=60)
    
    result = format_error_for_storage(exc, task_id="task123", stage="ai_analysis")
    
    assert result["error_code"] == "E3002"
    assert "timeout" in result["error_message"].lower()
    assert result["stage"] == "ai_analysis"
    assert result["retryable"] is True
    assert "model" in result["context"]


def test_format_error_for_storage_generic_exception():
    """Test error formatting for generic exceptions."""
    exc = ValueError("Invalid value")
    
    result = format_error_for_storage(exc, task_id="task123", stage="unknown")
    
    assert result["error_code"] == "E9999"
    assert "Invalid value" in result["error_message"]
    assert result["stage"] == "unknown"
    assert result["retryable"] is False
    assert result["context"]["exception_type"] == "ValueError"


def test_retry_transient_network_error():
    """Test that network errors are retried even if not ViraClipException."""
    exc = ConnectionError("Connection timeout")
    
    should_retry, delay = should_retry_task(exc, attempt=1, max_attempts=3)
    
    assert should_retry is True
    assert delay > 0


def test_no_retry_unknown_exception():
    """Test that unknown exceptions don't retry."""
    exc = RuntimeError("Some unknown error")
    
    should_retry, delay = should_retry_task(exc, attempt=1, max_attempts=3)
    
    assert should_retry is False  # Conservative: don't retry unknown errors


def test_retry_policy_logging(caplog):
    """Test that retry policy logs decisions."""
    import logging
    caplog.set_level(logging.INFO)
    
    exc = DownloadTimeoutError("https://test.com", 30)
    should_retry_task(exc, attempt=1, max_attempts=3)
    
    # Should log the retry decision
    assert any("retryable" in record.message.lower() for record in caplog.records)
