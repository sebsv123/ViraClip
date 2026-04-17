"""
Intelligent retry policy for worker tasks.

Determines whether to retry a task based on exception type and failure history.
"""

import logging
from typing import Optional, Tuple
from ..exceptions import (
    ViraClipException,
    TranscriptionException,
    AIAnalysisException,
    DownloadTimeoutError,
    GPUError,
    DatabaseException,
    RenderException,
    VideoCodecError,
    NoSegmentsFoundError,
    VideoNotFoundError,
)

logger = logging.getLogger(__name__)


def should_retry_task(
    exception: Exception,
    attempt: int,
    max_attempts: int = 3
) -> Tuple[bool, Optional[int]]:
    """
    Determine if a task should be retried based on exception type.
    
    Args:
        exception: The exception that caused the failure
        attempt: Current attempt number (1-indexed)
        max_attempts: Maximum number of attempts allowed
        
    Returns:
        (should_retry, delay_seconds)
        - should_retry: True if task should be retried
        - delay_seconds: How long to wait before retry (None = use default)
        
    Retry Logic:
        - Transcription errors: Retry up to 3 times (API issues are transient)
        - Download timeouts: Retry up to 2 times with exponential backoff
        - GPU errors: Retry once (driver might recover)
        - Database errors: Retry up to 3 times
        - Render failures: DON'T retry (likely video corruption)
        - Video not found: DON'T retry (permanent issue)
        - AI analysis failures: Retry once (might be model loading)
    """
    
    # Already at max attempts
    if attempt >= max_attempts:
        logger.info(f"Max attempts ({max_attempts}) reached, not retrying")
        return False, None
    
    # ViraClip custom exceptions have retryable flag
    if isinstance(exception, ViraClipException):
        if not exception.retryable:
            logger.info(
                f"Exception {exception.error_code} is not retryable: {exception.message}"
            )
            return False, None
        
        # Determine delay based on exception type
        delay = _calculate_retry_delay(exception, attempt)
        
        logger.info(
            f"Exception {exception.error_code} is retryable, "
            f"scheduling retry in {delay}s (attempt {attempt + 1}/{max_attempts})"
        )
        return True, delay
    
    # For non-ViraClip exceptions, use conservative policy
    # Only retry network/transient errors
    exception_name = type(exception).__name__
    
    if any(keyword in exception_name.lower() for keyword in [
        "timeout", "connection", "network", "unavailable"
    ]):
        delay = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s
        logger.info(
            f"Transient error detected ({exception_name}), "
            f"retrying in {delay}s (attempt {attempt + 1}/{max_attempts})"
        )
        return True, delay
    
    # Unknown exception - don't retry to avoid infinite loops
    logger.warning(
        f"Unknown exception type ({exception_name}), not retrying: {exception}"
    )
    return False, None


def _calculate_retry_delay(exception: ViraClipException, attempt: int) -> int:
    """
    Calculate retry delay based on exception type and attempt number.
    
    Returns:
        Delay in seconds
    """
    # Transcription: longer delays (API rate limits)
    if isinstance(exception, TranscriptionException):
        return min(30, 10 * attempt)  # 10s, 20s, 30s
    
    # Download: exponential backoff
    if isinstance(exception, DownloadTimeoutError):
        return 2 ** attempt  # 2s, 4s, 8s
    
    # GPU: short delay (driver recovery)
    if isinstance(exception, GPUError):
        return 5  # Fixed 5s
    
    # Database: short delay (connection pool)
    if isinstance(exception, DatabaseException):
        return 2  # Fixed 2s
    
    # AI Analysis: medium delay (model loading)
    if isinstance(exception, AIAnalysisException):
        return 5 * attempt  # 5s, 10s, 15s
    
    # Default: exponential backoff
    return 2 ** attempt


def get_max_attempts_for_error(exception: Exception) -> int:
    """
    Get maximum retry attempts for a specific error type.
    
    Some errors should be retried more aggressively than others.
    """
    if isinstance(exception, ViraClipException):
        # Transcription: aggressive retries (API flakiness)
        if isinstance(exception, TranscriptionException):
            return 3
        
        # Download timeouts: moderate retries
        if isinstance(exception, DownloadTimeoutError):
            return 2
        
        # GPU errors: single retry
        if isinstance(exception, GPUError):
            return 2
        
        # Database: aggressive retries
        if isinstance(exception, DatabaseException):
            return 3
        
        # AI Analysis: moderate retries
        if isinstance(exception, AIAnalysisException):
            return 2
    
    # Default
    return 3


def format_error_for_storage(
    exception: Exception,
    task_id: str,
    stage: Optional[str] = None
) -> dict:
    """
    Format exception for storage in database.
    
    Returns dict with error details for tasks.error_code and tasks.error_message.
    """
    if isinstance(exception, ViraClipException):
        return {
            "error_code": exception.error_code.value,
            "error_message": exception.message,
            "stage": stage or "unknown",
            "context": exception.context,
            "retryable": exception.retryable,
        }
    
    # Generic exception
    return {
        "error_code": "E9999",
        "error_message": str(exception),
        "stage": stage or "unknown",
        "context": {"exception_type": type(exception).__name__},
        "retryable": False,
    }
