"""
Retry Helper — Automatic retry logic for transient failures.

Provides decorators and utilities for retrying operations that may fail
due to transient issues (filesystem, network, FFmpeg timeouts, etc.).
"""

import asyncio
import functools
import logging
import time
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""
    pass


def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator for async functions with exponential backoff retry.
    
    Args:
        max_attempts: Maximum number of attempts (including initial)
        delay: Initial delay between retries (seconds)
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback called on each retry: (exception, attempt_num)
    
    Example:
        @retry_async(max_attempts=3, delay=1.0, exceptions=(subprocess.CalledProcessError,))
        async def run_ffmpeg(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except exceptions as exc:
                    last_exception = exc
                    
                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise RetryExhausted(
                            f"Failed after {max_attempts} attempts"
                        ) from exc
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {exc}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    
                    if on_retry:
                        try:
                            on_retry(exc, attempt)
                        except Exception as cb_exc:
                            logger.debug(f"on_retry callback failed: {cb_exc}")
                    
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            
            # Should never reach here, but just in case
            raise last_exception or RetryExhausted("Retry logic failed unexpectedly")
        
        return wrapper
    return decorator


def retry_sync(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator for sync functions with exponential backoff retry.
    
    Args:
        max_attempts: Maximum number of attempts (including initial)
        delay: Initial delay between retries (seconds)
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback called on each retry: (exception, attempt_num)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                    
                except exceptions as exc:
                    last_exception = exc
                    
                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise RetryExhausted(
                            f"Failed after {max_attempts} attempts"
                        ) from exc
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {exc}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    
                    if on_retry:
                        try:
                            on_retry(exc, attempt)
                        except Exception as cb_exc:
                            logger.debug(f"on_retry callback failed: {cb_exc}")
                    
                    time.sleep(current_delay)
                    current_delay *= backoff
            
            raise last_exception or RetryExhausted("Retry logic failed unexpectedly")
        
        return wrapper
    return decorator


class FFmpegRetryHelper:
    """Helper for retrying FFmpeg operations with smart error detection."""
    
    # Known transient FFmpeg errors
    TRANSIENT_ERRORS = [
        "Resource temporarily unavailable",
        "Connection reset by peer",
        "Broken pipe",
        "I/O error",
        "Timeout",
        "Device or resource busy",
        "No space left on device",  # Might clear up
    ]
    
    # Fatal errors that should not be retried
    FATAL_ERRORS = [
        "Invalid data found",
        "Codec not found",
        "Option not found",
        "Invalid argument",
        "does not contain any stream",
        "Unrecognized option",
    ]
    
    @classmethod
    def is_transient_error(cls, error_message: str) -> bool:
        """Check if error message indicates a transient failure."""
        error_lower = error_message.lower()
        
        # Check if it's a known fatal error
        if any(fatal.lower() in error_lower for fatal in cls.FATAL_ERRORS):
            return False
        
        # Check if it's a known transient error
        return any(trans.lower() in error_lower for trans in cls.TRANSIENT_ERRORS)
    
    @classmethod
    def should_retry(cls, returncode: int, stderr: str) -> bool:
        """
        Determine if FFmpeg failure should be retried.
        
        Args:
            returncode: FFmpeg exit code
            stderr: FFmpeg stderr output
            
        Returns:
            True if should retry, False otherwise
        """
        # Exit code 0 = success
        if returncode == 0:
            return False
        
        # Exit code 1 = typical error (check stderr)
        # Exit codes > 128 often indicate signal/kill (transient)
        if returncode > 128:
            logger.debug(f"FFmpeg killed by signal {returncode - 128}, may retry")
            return True
        
        # Check stderr for transient error patterns
        if stderr:
            return cls.is_transient_error(stderr)
        
        # Unknown error, default to no retry
        return False


async def retry_ffmpeg_operation(
    operation: Callable[[], Any],
    operation_name: str = "FFmpeg operation",
    max_attempts: int = 3,
) -> Any:
    """
    Retry an FFmpeg operation with smart error detection.
    
    Args:
        operation: Async callable that performs FFmpeg operation
        operation_name: Description for logging
        max_attempts: Maximum retry attempts
        
    Returns:
        Result of successful operation
        
    Raises:
        RetryExhausted: If all attempts fail
    """
    delay = 2.0
    last_error = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
            
        except Exception as exc:
            last_error = exc
            
            # Check if error is retryable
            error_msg = str(exc)
            should_retry = False
            
            # Check for subprocess.CalledProcessError with FFmpeg details
            if hasattr(exc, 'returncode') and hasattr(exc, 'stderr'):
                stderr = exc.stderr
                if isinstance(stderr, bytes):
                    stderr = stderr.decode(errors='ignore')
                should_retry = FFmpegRetryHelper.should_retry(
                    exc.returncode, stderr or ""
                )
            elif FFmpegRetryHelper.is_transient_error(error_msg):
                should_retry = True
            
            if not should_retry or attempt == max_attempts:
                logger.error(
                    f"{operation_name} failed after {attempt} attempt(s): {exc}"
                )
                raise RetryExhausted(
                    f"{operation_name} failed after {attempt} attempts"
                ) from exc
            
            logger.warning(
                f"{operation_name} failed (attempt {attempt}/{max_attempts}), "
                f"retrying in {delay}s: {exc}"
            )
            
            await asyncio.sleep(delay)
            delay *= 1.5  # Exponential backoff
    
    raise last_error or RetryExhausted(f"{operation_name} failed unexpectedly")
