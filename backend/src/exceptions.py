"""
Custom exceptions for ViraClip.

Provides typed exceptions with error codes for better error tracking and debugging.
Each exception type maps to a specific failure scenario, enabling:
- Targeted retry logic (retry transcription errors, but not video corruption)
- Better logging and metrics (count errors by type)
- Clear error messages to users
"""

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    """Error codes for tracking failure types."""
    
    # Download errors (1xxx)
    DOWNLOAD_FAILED = "E1001"
    VIDEO_NOT_FOUND = "E1002"
    VIDEO_TOO_LARGE = "E1003"
    DOWNLOAD_TIMEOUT = "E1004"
    
    # Transcription errors (2xxx)
    TRANSCRIPTION_FAILED = "E2001"
    ASSEMBLY_AI_ERROR = "E2002"
    WHISPER_ERROR = "E2003"
    NO_AUDIO_TRACK = "E2004"
    
    # AI Analysis errors (3xxx)
    AI_ANALYSIS_FAILED = "E3001"
    LLM_TIMEOUT = "E3002"
    LLM_INVALID_RESPONSE = "E3003"
    NO_SEGMENTS_FOUND = "E3004"
    ALL_SEGMENTS_INVALID = "E3005"
    
    # Render errors (4xxx)
    RENDER_FAILED = "E4001"
    VIDEO_CODEC_ERROR = "E4002"
    GPU_ERROR = "E4003"
    FACE_DETECTION_FAILED = "E4004"
    SUBTITLE_GENERATION_FAILED = "E4005"
    OUTPUT_FILE_WRITE_ERROR = "E4006"
    
    # Resource errors (5xxx)
    OUT_OF_MEMORY = "E5001"
    OUT_OF_DISK_SPACE = "E5002"
    GPU_OUT_OF_MEMORY = "E5003"
    
    # Database errors (6xxx)
    DATABASE_ERROR = "E6001"
    DATABASE_CONNECTION_FAILED = "E6002"
    
    # Configuration errors (7xxx)
    INVALID_CONFIGURATION = "E7001"
    MISSING_API_KEY = "E7002"
    
    # Unknown
    UNKNOWN_ERROR = "E9999"


class ViraClipException(Exception):
    """
    Base exception for all ViraClip errors.
    
    Attributes:
        error_code: Unique error code for tracking
        message: Human-readable error message
        retryable: Whether this error should trigger a retry
        context: Additional context (task_id, file path, etc.)
    """
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        retryable: bool = False,
        context: Optional[dict] = None
    ):
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.context = context or {}
        super().__init__(f"[{error_code.value}] {message}")
    
    def to_dict(self) -> dict:
        """Convert to dict for logging/API responses."""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "error_message": self.message,
            "retryable": self.retryable,
            "context": self.context,
        }


# ── Download Exceptions ──────────────────────────────────────────────────────

class DownloadException(ViraClipException):
    """Base class for download-related errors."""
    pass


class VideoNotFoundError(DownloadException):
    """Video URL is invalid or video has been deleted."""
    
    def __init__(self, url: str, message: Optional[str] = None):
        super().__init__(
            message=message or f"Video not found: {url}",
            error_code=ErrorCode.VIDEO_NOT_FOUND,
            retryable=False,  # Don't retry missing videos
            context={"url": url}
        )


class DownloadTimeoutError(DownloadException):
    """Download took too long (network issues)."""
    
    def __init__(self, url: str, timeout_seconds: int):
        super().__init__(
            message=f"Download timeout after {timeout_seconds}s: {url}",
            error_code=ErrorCode.DOWNLOAD_TIMEOUT,
            retryable=True,  # Network issues are transient
            context={"url": url, "timeout": timeout_seconds}
        )


class VideoTooLargeError(DownloadException):
    """Video exceeds maximum allowed size."""
    
    def __init__(self, url: str, size_mb: int, max_size_mb: int):
        super().__init__(
            message=f"Video too large: {size_mb}MB (max {max_size_mb}MB)",
            error_code=ErrorCode.VIDEO_TOO_LARGE,
            retryable=False,
            context={"url": url, "size_mb": size_mb, "max_size_mb": max_size_mb}
        )


# ── Transcription Exceptions ─────────────────────────────────────────────────

class TranscriptionException(ViraClipException):
    """Base class for transcription-related errors."""
    pass


class TranscriptionFailedError(TranscriptionException):
    """Transcription service failed (AssemblyAI/Whisper)."""
    
    def __init__(self, service: str, reason: str, video_path: str):
        super().__init__(
            message=f"{service} transcription failed: {reason}",
            error_code=ErrorCode.TRANSCRIPTION_FAILED,
            retryable=True,  # API errors are often transient
            context={"service": service, "reason": reason, "video_path": video_path}
        )


class NoAudioTrackError(TranscriptionException):
    """Video has no audio track."""
    
    def __init__(self, video_path: str):
        super().__init__(
            message=f"No audio track found in video: {video_path}",
            error_code=ErrorCode.NO_AUDIO_TRACK,
            retryable=False,  # Can't transcribe silence
            context={"video_path": video_path}
        )


# ── AI Analysis Exceptions ───────────────────────────────────────────────────

class AIAnalysisException(ViraClipException):
    """Base class for AI analysis errors."""
    pass


class LLMTimeoutError(AIAnalysisException):
    """LLM request timed out."""
    
    def __init__(self, model: str, timeout_seconds: int):
        super().__init__(
            message=f"LLM timeout ({model}) after {timeout_seconds}s",
            error_code=ErrorCode.LLM_TIMEOUT,
            retryable=True,
            context={"model": model, "timeout": timeout_seconds}
        )


class LLMInvalidResponseError(AIAnalysisException):
    """LLM returned invalid/unparseable response."""
    
    def __init__(self, model: str, response: str, reason: str):
        super().__init__(
            message=f"Invalid LLM response ({model}): {reason}",
            error_code=ErrorCode.LLM_INVALID_RESPONSE,
            retryable=True,  # Retry with different temperature/prompt
            context={"model": model, "response": response[:200], "reason": reason}
        )


class NoSegmentsFoundError(AIAnalysisException):
    """AI did not find any valid segments in the transcript."""
    
    def __init__(self, reason: str, transcript_length: int):
        super().__init__(
            message=f"No valid segments found: {reason}",
            error_code=ErrorCode.NO_SEGMENTS_FOUND,
            retryable=False,  # Content issue, not transient
            context={"reason": reason, "transcript_length": transcript_length}
        )


# ── Render Exceptions ────────────────────────────────────────────────────────

class RenderException(ViraClipException):
    """Base class for render-related errors."""
    pass


class RenderFailedError(RenderException):
    """Generic render failure."""
    
    def __init__(self, clip_path: str, reason: str, segment_index: Optional[int] = None):
        super().__init__(
            message=f"Render failed: {reason}",
            error_code=ErrorCode.RENDER_FAILED,
            retryable=False,  # Video corruption or codec issues rarely self-resolve
            context={"clip_path": clip_path, "reason": reason, "segment_index": segment_index}
        )


class VideoCodecError(RenderException):
    """Video codec error (corrupt frames, unsupported codec)."""
    
    def __init__(self, video_path: str, codec: str, reason: str):
        super().__init__(
            message=f"Codec error ({codec}): {reason}",
            error_code=ErrorCode.VIDEO_CODEC_ERROR,
            retryable=False,
            context={"video_path": video_path, "codec": codec, "reason": reason}
        )


class GPUError(RenderException):
    """GPU-related error (driver crash, CUDA error)."""
    
    def __init__(self, reason: str, gpu_type: Optional[str] = None):
        super().__init__(
            message=f"GPU error: {reason}",
            error_code=ErrorCode.GPU_ERROR,
            retryable=True,  # GPU errors can be transient
            context={"reason": reason, "gpu_type": gpu_type}
        )


class FaceDetectionFailedError(RenderException):
    """Face detection failed (no faces found, or detector crashed)."""
    
    def __init__(self, video_path: str, reason: str):
        super().__init__(
            message=f"Face detection failed: {reason}",
            error_code=ErrorCode.FACE_DETECTION_FAILED,
            retryable=False,  # Not a transient issue
            context={"video_path": video_path, "reason": reason}
        )


# ── Resource Exceptions ──────────────────────────────────────────────────────

class ResourceException(ViraClipException):
    """Base class for resource exhaustion errors."""
    pass


class OutOfMemoryError(ResourceException):
    """System ran out of RAM."""
    
    def __init__(self, required_mb: Optional[int] = None, available_mb: Optional[int] = None):
        super().__init__(
            message="Out of memory",
            error_code=ErrorCode.OUT_OF_MEMORY,
            retryable=True,  # May resolve after cleanup
            context={"required_mb": required_mb, "available_mb": available_mb}
        )


class OutOfDiskSpaceError(ResourceException):
    """Disk is full."""
    
    def __init__(self, path: str, required_mb: int, available_mb: int):
        super().__init__(
            message=f"Out of disk space: {available_mb}MB available, {required_mb}MB required",
            error_code=ErrorCode.OUT_OF_DISK_SPACE,
            retryable=False,  # Need manual intervention
            context={"path": path, "required_mb": required_mb, "available_mb": available_mb}
        )


# ── Database Exceptions ──────────────────────────────────────────────────────

class DatabaseException(ViraClipException):
    """Base class for database errors."""
    pass


class DatabaseConnectionError(DatabaseException):
    """Cannot connect to database."""
    
    def __init__(self, reason: str):
        super().__init__(
            message=f"Database connection failed: {reason}",
            error_code=ErrorCode.DATABASE_CONNECTION_FAILED,
            retryable=True,
            context={"reason": reason}
        )


# ── Configuration Exceptions ─────────────────────────────────────────────────

class ConfigurationException(ViraClipException):
    """Base class for configuration errors."""
    pass


class MissingAPIKeyError(ConfigurationException):
    """Required API key is missing."""
    
    def __init__(self, service: str, env_var: str):
        super().__init__(
            message=f"Missing API key for {service}: {env_var} not set",
            error_code=ErrorCode.MISSING_API_KEY,
            retryable=False,
            context={"service": service, "env_var": env_var}
        )
