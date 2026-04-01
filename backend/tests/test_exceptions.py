"""
Tests for custom exceptions and error handling.

Validates exception hierarchy, error codes, and retryability logic.
"""

import pytest
from src.exceptions import (
    ViraClipException,
    ErrorCode,
    VideoNotFoundError,
    DownloadTimeoutError,
    TranscriptionFailedError,
    LLMTimeoutError,
    NoSegmentsFoundError,
    RenderFailedError,
    GPUError,
    OutOfMemoryError,
    DatabaseConnectionError,
    MissingAPIKeyError,
)


def test_viraclip_exception_base():
    """Test base ViraClipException."""
    exc = ViraClipException(
        message="Test error",
        error_code=ErrorCode.UNKNOWN_ERROR,
        retryable=True,
        context={"key": "value"}
    )
    
    assert exc.error_code == ErrorCode.UNKNOWN_ERROR
    assert exc.message == "Test error"
    assert exc.retryable is True
    assert exc.context == {"key": "value"}
    assert str(exc) == "[E9999] Test error"


def test_exception_to_dict():
    """Test exception serialization to dict."""
    exc = VideoNotFoundError("https://youtube.com/watch?v=invalid")
    
    result = exc.to_dict()
    
    assert result["error_code"] == "E1002"
    assert "not found" in result["error_message"].lower()
    assert result["retryable"] is False
    assert "url" in result["context"]


def test_video_not_found_error():
    """Test VideoNotFoundError is not retryable."""
    exc = VideoNotFoundError("https://youtube.com/watch?v=test")
    
    assert exc.error_code == ErrorCode.VIDEO_NOT_FOUND
    assert exc.retryable is False
    assert exc.context["url"] == "https://youtube.com/watch?v=test"


def test_download_timeout_error():
    """Test DownloadTimeoutError is retryable."""
    exc = DownloadTimeoutError("https://youtube.com/watch?v=test", timeout_seconds=30)
    
    assert exc.error_code == ErrorCode.DOWNLOAD_TIMEOUT
    assert exc.retryable is True  # Network issues are transient
    assert exc.context["timeout"] == 30


def test_transcription_failed_error():
    """Test TranscriptionFailedError is retryable."""
    exc = TranscriptionFailedError(
        service="AssemblyAI",
        reason="API rate limit",
        video_path="/tmp/video.mp4"
    )
    
    assert exc.error_code == ErrorCode.TRANSCRIPTION_FAILED
    assert exc.retryable is True  # API errors often transient
    assert "AssemblyAI" in exc.message


def test_llm_timeout_error():
    """Test LLM timeout is retryable."""
    exc = LLMTimeoutError(model="gpt-4", timeout_seconds=60)
    
    assert exc.error_code == ErrorCode.LLM_TIMEOUT
    assert exc.retryable is True
    assert exc.context["model"] == "gpt-4"


def test_no_segments_found_error():
    """Test NoSegmentsFoundError is NOT retryable."""
    exc = NoSegmentsFoundError(reason="Video too short", transcript_length=10)
    
    assert exc.error_code == ErrorCode.NO_SEGMENTS_FOUND
    assert exc.retryable is False  # Content issue, not transient
    assert exc.context["transcript_length"] == 10


def test_render_failed_error():
    """Test RenderFailedError is NOT retryable."""
    exc = RenderFailedError(
        clip_path="/tmp/clip.mp4",
        reason="Codec error",
        segment_index=3
    )
    
    assert exc.error_code == ErrorCode.RENDER_FAILED
    assert exc.retryable is False  # Corruption rarely self-resolves
    assert exc.context["segment_index"] == 3


def test_gpu_error():
    """Test GPUError is retryable."""
    exc = GPUError(reason="CUDA out of memory", gpu_type="nvidia")
    
    assert exc.error_code == ErrorCode.GPU_ERROR
    assert exc.retryable is True  # GPU errors can be transient
    assert exc.context["gpu_type"] == "nvidia"


def test_out_of_memory_error():
    """Test OutOfMemoryError is retryable."""
    exc = OutOfMemoryError(required_mb=2048, available_mb=512)
    
    assert exc.error_code == ErrorCode.OUT_OF_MEMORY
    assert exc.retryable is True  # May resolve after cleanup
    assert exc.context["required_mb"] == 2048


def test_database_connection_error():
    """Test DatabaseConnectionError is retryable."""
    exc = DatabaseConnectionError(reason="Connection pool exhausted")
    
    assert exc.error_code == ErrorCode.DATABASE_CONNECTION_FAILED
    assert exc.retryable is True
    assert "pool" in exc.message.lower()


def test_missing_api_key_error():
    """Test MissingAPIKeyError is NOT retryable."""
    exc = MissingAPIKeyError(service="AssemblyAI", env_var="ASSEMBLY_AI_API_KEY")
    
    assert exc.error_code == ErrorCode.MISSING_API_KEY
    assert exc.retryable is False  # Config issue needs manual fix
    assert exc.context["service"] == "AssemblyAI"


def test_error_code_values():
    """Test that error codes follow expected format."""
    # Download errors
    assert ErrorCode.DOWNLOAD_FAILED.value.startswith("E1")
    assert ErrorCode.VIDEO_NOT_FOUND.value == "E1002"
    
    # Transcription errors
    assert ErrorCode.TRANSCRIPTION_FAILED.value.startswith("E2")
    
    # AI errors
    assert ErrorCode.AI_ANALYSIS_FAILED.value.startswith("E3")
    
    # Render errors
    assert ErrorCode.RENDER_FAILED.value.startswith("E4")
    
    # Resource errors
    assert ErrorCode.OUT_OF_MEMORY.value.startswith("E5")
    
    # Database errors
    assert ErrorCode.DATABASE_ERROR.value.startswith("E6")
    
    # Config errors
    assert ErrorCode.INVALID_CONFIGURATION.value.startswith("E7")
    
    # Unknown
    assert ErrorCode.UNKNOWN_ERROR.value == "E9999"


def test_exception_inheritance():
    """Test exception class hierarchy."""
    from src.exceptions import (
        DownloadException,
        TranscriptionException,
        AIAnalysisException,
        RenderException,
        ResourceException,
    )
    
    assert issubclass(VideoNotFoundError, DownloadException)
    assert issubclass(DownloadException, ViraClipException)
    
    assert issubclass(TranscriptionFailedError, TranscriptionException)
    assert issubclass(LLMTimeoutError, AIAnalysisException)
    assert issubclass(RenderFailedError, RenderException)
    assert issubclass(OutOfMemoryError, ResourceException)
