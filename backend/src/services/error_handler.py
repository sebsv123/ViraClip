"""
Enhanced Error Handling and Retry System
Provides robust error handling with exponential backoff and circuit breaker patterns.
"""

import asyncio
import logging
import random
from typing import Callable, Any, Optional, Type, List, Dict
from dataclasses import dataclass
from enum import Enum
from functools import wraps
import time

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors for appropriate handling."""
    TRANSIENT = "transient"      # Retryable (network, rate limits)
    PERMANENT = "permanent"      # Not retryable (bad input, auth)
    TIMEOUT = "timeout"          # Timeout errors
    RESOURCE = "resource"        # Resource exhaustion (OOM, disk)
    UNKNOWN = "unknown"          # Unclassified


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)
    on_retry: Optional[Callable[[int, Exception], None]] = None
    on_fail: Optional[Callable[[Exception], None]] = None


class CircuitBreaker:
    """
    Circuit breaker pattern to prevent cascading failures.
    
    States:
    - CLOSED: Normal operation
    - OPEN: Failing, rejecting requests
    - HALF_OPEN: Testing if service recovered
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self._state = "CLOSED"
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
    
    @property
    def state(self) -> str:
        """Get current circuit state."""
        if self._state == "OPEN":
            # Check if recovery timeout elapsed
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed > self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    self._half_open_calls = 0
                    self._success_count = 0
                    logger.info("Circuit breaker entering HALF_OPEN state")
        
        return self._state
    
    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        state = self.state
        
        if state == "CLOSED":
            return True
        
        if state == "OPEN":
            return False
        
        if state == "HALF_OPEN":
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        
        return True
    
    def record_success(self):
        """Record successful execution."""
        if self._state == "HALF_OPEN":
            self._success_count += 1
            
            # If enough successes, close the circuit
            if self._success_count >= self.half_open_max_calls:
                self._state = "CLOSED"
                self._failure_count = 0
                self._half_open_calls = 0
                logger.info("Circuit breaker CLOSED (recovered)")
        
        elif self._state == "CLOSED":
            # Reset failure count on success
            if self._failure_count > 0:
                self._failure_count = max(0, self._failure_count - 1)
    
    def record_failure(self):
        """Record failed execution."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == "HALF_OPEN":
            # Back to open on failure in half-open
            self._state = "OPEN"
            logger.warning("Circuit breaker OPEN (failure in HALF_OPEN)")
        
        elif self._state == "CLOSED":
            if self._failure_count >= self.failure_threshold:
                self._state = "OPEN"
                logger.warning(f"Circuit breaker OPEN ({self._failure_count} failures)")


class RetryHandler:
    """Handles retry logic with exponential backoff and jitter."""
    
    @staticmethod
    def calculate_delay(
        attempt: int,
        base_delay: float,
        max_delay: float,
        exponential_base: float,
        jitter: bool
    ) -> float:
        """Calculate delay for retry attempt."""
        # Exponential backoff
        delay = base_delay * (exponential_base ** attempt)
        delay = min(delay, max_delay)
        
        # Add jitter (±20%)
        if jitter:
            delay *= (0.8 + 0.4 * random.random())
        
        return delay
    
    @staticmethod
    async def execute_with_retry(
        func: Callable[..., Any],
        config: RetryConfig,
        *args,
        **kwargs
    ) -> Any:
        """Execute function with retry logic."""
        last_exception = None
        
        for attempt in range(config.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                # Success
                if attempt > 0:
                    logger.info(f"Function succeeded after {attempt} retries")
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # Check if exception is retryable
                if not isinstance(e, config.retryable_exceptions):
                    logger.debug(f"Non-retryable exception: {e}")
                    raise
                
                # Check if we should retry
                if attempt >= config.max_retries:
                    logger.warning(f"Max retries ({config.max_retries}) exceeded")
                    break
                
                # Calculate delay
                delay = RetryHandler.calculate_delay(
                    attempt,
                    config.base_delay,
                    config.max_delay,
                    config.exponential_base,
                    config.jitter
                )
                
                logger.warning(
                    f"Attempt {attempt + 1}/{config.max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                
                # Callback
                if config.on_retry:
                    config.on_retry(attempt, e)
                
                await asyncio.sleep(delay)
        
        # All retries exhausted
        if config.on_fail:
            config.on_fail(last_exception)
        
        raise last_exception


# Decorator for retry logic
def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple = (Exception,),
    circuit_breaker: Optional[CircuitBreaker] = None
):
    """Decorator to add retry logic to async functions."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Check circuit breaker
            if circuit_breaker and not circuit_breaker.can_execute():
                raise Exception(f"Circuit breaker is OPEN for {func.__name__}")
            
            config = RetryConfig(
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                retryable_exceptions=retryable_exceptions,
            )
            
            try:
                result = await RetryHandler.execute_with_retry(
                    func, config, *args, **kwargs
                )
                
                # Record success for circuit breaker
                if circuit_breaker:
                    circuit_breaker.record_success()
                
                return result
                
            except Exception as e:
                # Record failure for circuit breaker
                if circuit_breaker:
                    circuit_breaker.record_failure()
                raise
        
        return wrapper
    return decorator


def classify_error(error: Exception) -> ErrorCategory:
    """Classify error for appropriate handling."""
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Timeout errors
    if any(x in error_str or x in error_type for x in [
        "timeout", "timed out", "deadline", "asyncio.wait_for"
    ]):
        return ErrorCategory.TIMEOUT
    
    # Resource errors
    if any(x in error_str or x in error_type for x in [
        "memory", "disk", "space", "quota", "limit"
    ]):
        return ErrorCategory.RESOURCE
    
    # Permanent errors
    if any(x in error_str or x in error_type for x in [
        "invalid", "auth", "forbidden", "not found", "bad request"
    ]):
        return ErrorCategory.PERMANENT
    
    # Transient errors
    if any(x in error_str or x in error_type for x in [
        "network", "connection", "temporarily", "unavailable",
        "rate limit", "too many requests", "busy"
    ]):
        return ErrorCategory.TRANSIENT
    
    return ErrorCategory.UNKNOWN


class ErrorRecoveryStrategy:
    """Strategies for recovering from different error types."""
    
    @staticmethod
    async def handle_transient_error(error: Exception, context: Dict) -> bool:
        """Handle transient error - typically retry."""
        logger.info(f"Transient error detected, will retry: {error}")
        return True  # Retry
    
    @staticmethod
    async def handle_resource_error(error: Exception, context: Dict) -> bool:
        """Handle resource error - may need to wait or reduce load."""
        logger.warning(f"Resource error: {error}")
        
        # Wait a bit for resources to free up
        await asyncio.sleep(5)
        
        # Check if we should continue
        import psutil
        memory = psutil.virtual_memory()
        if memory.percent > 90:
            logger.error("Memory still critical, aborting")
            return False
        
        return True  # Retry with caution
    
    @staticmethod
    async def handle_timeout_error(error: Exception, context: Dict) -> bool:
        """Handle timeout - may need to adjust timeout or split work."""
        logger.warning(f"Timeout error: {error}")
        
        # Increase timeout for next attempt
        current_timeout = context.get("timeout", 30)
        context["timeout"] = current_timeout * 1.5
        
        return True  # Retry with longer timeout
    
    @staticmethod
    async def handle_permanent_error(error: Exception, context: Dict) -> bool:
        """Handle permanent error - no retry."""
        logger.error(f"Permanent error, not retrying: {error}")
        return False  # Don't retry


# Circuit breaker instances for different services
circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    """Get or create circuit breaker for a service."""
    if service_name not in circuit_breakers:
        circuit_breakers[service_name] = CircuitBreaker()
    return circuit_breakers[service_name]


async def execute_with_recovery(
    func: Callable[..., Any],
    *args,
    max_retries: int = 3,
    context: Optional[Dict] = None,
    **kwargs
) -> Any:
    """
    Execute function with comprehensive error handling and recovery.
    
    This combines:
    - Error classification
    - Retry logic
    - Circuit breaker
    - Recovery strategies
    """
    context = context or {}
    
    for attempt in range(max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
                
        except Exception as e:
            category = classify_error(e)
            
            if attempt >= max_retries:
                logger.error(f"All retries exhausted for {func.__name__}: {e}")
                raise
            
            # Apply recovery strategy
            should_retry = False
            if category == ErrorCategory.TRANSIENT:
                should_retry = await ErrorRecoveryStrategy.handle_transient_error(e, context)
            elif category == ErrorCategory.RESOURCE:
                should_retry = await ErrorRecoveryStrategy.handle_resource_error(e, context)
            elif category == ErrorCategory.TIMEOUT:
                should_retry = await ErrorRecoveryStrategy.handle_timeout_error(e, context)
            elif category == ErrorCategory.PERMANENT:
                should_retry = await ErrorRecoveryStrategy.handle_permanent_error(e, context)
            else:
                should_retry = True  # Unknown - try once more
            
            if not should_retry:
                raise
            
            # Exponential backoff
            delay = min(2 ** attempt, 30)  # Cap at 30s
            logger.info(f"Retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
            await asyncio.sleep(delay)


# Utility for batch error handling
async def process_with_fallback(
    items: List[Any],
    processor: Callable[[Any], Any],
    fallback: Callable[[Any], Any],
    error_handler: Optional[Callable[[Any, Exception], None]] = None
) -> List[Any]:
    """
    Process items with fallback for failed items.
    
    Returns results with None for items that failed even after fallback.
    """
    results = []
    
    for item in items:
        try:
            # Try primary processor
            result = await processor(item)
            results.append(result)
        except Exception as e:
            logger.warning(f"Primary processor failed for {item}: {e}")
            
            try:
                # Try fallback
                result = await fallback(item)
                results.append(result)
            except Exception as e2:
                logger.error(f"Fallback also failed for {item}: {e2}")
                if error_handler:
                    error_handler(item, e2)
                results.append(None)
    
    return results
