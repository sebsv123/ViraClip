"""
Retry Helper — Automatic retry logic for transient failures.

Provides decorators and utilities for retrying operations that may fail
due to transient issues (filesystem, network, FFmpeg timeouts, etc.).
"""

import asyncio
import functools
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


# ── Retry Configuration ───────────────────────────────────────────────────────

@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.
    
    Allows per-operation customization of retry parameters.
    """
    max_attempts: int = 3
    initial_delay: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay: float = 30.0
    
    @classmethod
    def from_env(cls, prefix: str = "RETRY") -> "RetryConfig":
        """
        Load retry config from environment variables.
        
        Args:
            prefix: Environment variable prefix (e.g., "RETRY_FFMPEG")
            
        Example:
            RETRY_FFMPEG_MAX_ATTEMPTS=5
            RETRY_FFMPEG_INITIAL_DELAY=2.0
        """
        return cls(
            max_attempts=int(os.getenv(f"{prefix}_MAX_ATTEMPTS", "3")),
            initial_delay=float(os.getenv(f"{prefix}_INITIAL_DELAY", "1.0")),
            backoff_multiplier=float(os.getenv(f"{prefix}_BACKOFF_MULTIPLIER", "2.0")),
            max_delay=float(os.getenv(f"{prefix}_MAX_DELAY", "30.0")),
        )
    
    @classmethod
    def aggressive(cls) -> "RetryConfig":
        """Aggressive retry config (more attempts, faster retries)."""
        return cls(max_attempts=5, initial_delay=0.5, backoff_multiplier=1.5, max_delay=10.0)
    
    @classmethod
    def conservative(cls) -> "RetryConfig":
        """Conservative retry config (fewer attempts, longer delays)."""
        return cls(max_attempts=2, initial_delay=2.0, backoff_multiplier=3.0, max_delay=60.0)
    
    @classmethod
    def default(cls) -> "RetryConfig":
        """Default retry config."""
        return cls()


# ── Predefined Retry Configurations ──────────────────────────────────────────

# Load from environment or use defaults
RETRY_CONFIG_FFMPEG = RetryConfig.from_env("RETRY_FFMPEG")
RETRY_CONFIG_NETWORK = RetryConfig.from_env("RETRY_NETWORK")
RETRY_CONFIG_FILESYSTEM = RetryConfig.from_env("RETRY_FILESYSTEM")
RETRY_CONFIG_DEFAULT = RetryConfig.default()


class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""
    pass


def retry_async(
    max_attempts: Optional[int] = None,
    delay: Optional[float] = None,
    backoff: Optional[float] = None,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    config: Optional[RetryConfig] = None,
):
    """
    Decorator for async functions with exponential backoff retry.
    
    Args:
        max_attempts: Maximum number of attempts (overrides config)
        delay: Initial delay between retries (overrides config)
        backoff: Multiplier for delay after each retry (overrides config)
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback called on each retry: (exception, attempt_num)
        config: RetryConfig to use (defaults to RETRY_CONFIG_DEFAULT)
    
    Example:
        @retry_async(config=RETRY_CONFIG_FFMPEG)
        async def run_ffmpeg(...):
            ...
    """
    # Use provided config or default
    if config is None:
        config = RETRY_CONFIG_DEFAULT
    
    # Override config with explicit parameters
    final_max_attempts = max_attempts if max_attempts is not None else config.max_attempts
    final_delay = delay if delay is not None else config.initial_delay
    final_backoff = backoff if backoff is not None else config.backoff_multiplier
    max_delay = config.max_delay
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            current_delay = final_delay
            last_exception = None
            
            for attempt in range(1, final_max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except exceptions as exc:
                    last_exception = exc
                    
                    if attempt == final_max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {final_max_attempts} attempts: {exc}"
                        )
                        raise RetryExhausted(
                            f"Failed after {final_max_attempts} attempts"
                        ) from exc
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{final_max_attempts}): {exc}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    
                    if on_retry:
                        try:
                            on_retry(exc, attempt)
                        except Exception as cb_exc:
                            logger.debug(f"on_retry callback failed: {cb_exc}")
                    
                    await asyncio.sleep(current_delay)
                    current_delay = min(current_delay * final_backoff, max_delay)
            
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
    config: Optional[RetryConfig] = None,
) -> Any:
    """
    Retry an FFmpeg operation with smart error detection.
    
    Args:
        operation: Async callable that performs FFmpeg operation
        operation_name: Description for logging
        config: RetryConfig to use (defaults to RETRY_CONFIG_FFMPEG)
        
    Returns:
        Result of successful operation
        
    Raises:
        RetryExhausted: If all attempts fail
    """
    if config is None:
        config = RETRY_CONFIG_FFMPEG
    
    delay = config.initial_delay
    last_error = None
    
    for attempt in range(1, config.max_attempts + 1):
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
            
            if not should_retry or attempt == config.max_attempts:
                logger.error(
                    f"{operation_name} failed after {attempt} attempt(s): {exc}"
                )
                raise RetryExhausted(
                    f"{operation_name} failed after {attempt} attempts"
                ) from exc
            
            logger.warning(
                f"{operation_name} failed (attempt {attempt}/{config.max_attempts}), "
                f"retrying in {delay}s: {exc}"
            )
            
            await asyncio.sleep(delay)
            delay = min(delay * config.backoff_multiplier, config.max_delay)
    
    raise last_error or RetryExhausted(f"{operation_name} failed unexpectedly")
