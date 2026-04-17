"""
Structured Logging and Observability Module
Advanced logging with correlation IDs, performance tracking, and distributed tracing.
"""

import logging
import json
import time
import uuid
from typing import Dict, Any, Optional, Callable
from functools import wraps
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

# Context variables for request tracking
request_id_var: ContextVar[str] = ContextVar('request_id', default='')
user_id_var: ContextVar[str] = ContextVar('user_id', default='')
task_id_var: ContextVar[str] = ContextVar('task_id', default='')


class StructuredLogFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
            "task_id": task_id_var.get(),
        }
        
        # Add extra fields if present
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class ObservabilityManager:
    """
    Manages observability, distributed tracing, and performance monitoring.
    """
    
    def __init__(self, service_name: str = "viraclip"):
        self.service_name = service_name
        self._spans: Dict[str, Dict[str, Any]] = {}
        self._metrics: Dict[str, list] = {}
    
    def start_request(self, request_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """Start tracking a new request."""
        if not request_id:
            request_id = str(uuid.uuid4())
        
        request_id_var.set(request_id)
        if user_id:
            user_id_var.set(user_id)
        
        return request_id
    
    def start_span(self, span_name: str, parent_span_id: Optional[str] = None) -> str:
        """Start a new trace span."""
        span_id = str(uuid.uuid4())
        
        self._spans[span_id] = {
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": span_name,
            "start_time": time.time(),
            "request_id": request_id_var.get(),
            "attributes": {}
        }
        
        return span_id
    
    def end_span(self, span_id: str, attributes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """End a trace span and return span data."""
        if span_id not in self._spans:
            return {}
        
        span = self._spans[span_id]
        span["end_time"] = time.time()
        span["duration_ms"] = (span["end_time"] - span["start_time"]) * 1000
        
        if attributes:
            span["attributes"].update(attributes)
        
        # Log span
        logger.info(
            f"Span completed: {span['name']}",
            extra={"extra_data": {
                "span_id": span_id,
                "duration_ms": span["duration_ms"],
                "span_name": span["name"]
            }}
        )
        
        return span
    
    def record_metric(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a metric value."""
        if metric_name not in self._metrics:
            self._metrics[metric_name] = []
        
        self._metrics[metric_name].append({
            "timestamp": datetime.utcnow().isoformat(),
            "value": value,
            "labels": labels or {}
        })
    
    def get_span_tree(self, request_id: str) -> list:
        """Get all spans for a request as a tree."""
        request_spans = [
            s for s in self._spans.values()
            if s.get("request_id") == request_id
        ]
        
        # Build tree structure
        span_map = {s["span_id"]: s for s in request_spans}
        roots = []
        
        for span in request_spans:
            parent_id = span.get("parent_span_id")
            if parent_id and parent_id in span_map:
                if "children" not in span_map[parent_id]:
                    span_map[parent_id]["children"] = []
                span_map[parent_id]["children"].append(span)
            else:
                roots.append(span)
        
        return roots


class PerformanceMonitor:
    """Monitor performance of operations."""
    
    def __init__(self):
        self._operation_times: Dict[str, list] = {}
    
    def time_operation(self, operation_name: str):
        """Decorator to time an operation."""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.time()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    duration = time.time() - start
                    self._record_time(operation_name, duration)
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.time()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    duration = time.time() - start
                    self._record_time(operation_name, duration)
            
            return async_wrapper if hasattr(func, '__code__') and func.__code__.co_flags & 0x80 else sync_wrapper
        return decorator
    
    def _record_time(self, operation_name: str, duration: float):
        """Record operation timing."""
        if operation_name not in self._operation_times:
            self._operation_times[operation_name] = []
        
        self._operation_times[operation_name].append({
            "timestamp": datetime.utcnow().isoformat(),
            "duration_seconds": duration
        })
        
        # Keep only last 1000 entries
        if len(self._operation_times[operation_name]) > 1000:
            self._operation_times[operation_name] = self._operation_times[operation_name][-1000:]
        
        # Log slow operations
        if duration > 30:  # 30 seconds
            logger.warning(
                f"Slow operation: {operation_name} took {duration:.2f}s",
                extra={"extra_data": {
                    "operation": operation_name,
                    "duration_seconds": duration,
                    "slow": True
                }}
            )
    
    def get_stats(self, operation_name: str) -> Dict[str, float]:
        """Get statistics for an operation."""
        times = self._operation_times.get(operation_name, [])
        
        if not times:
            return {}
        
        durations = [t["duration_seconds"] for t in times]
        
        return {
            "count": len(durations),
            "avg": sum(durations) / len(durations),
            "min": min(durations),
            "max": max(durations),
            "p95": sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else max(durations)
        }


def setup_logging(log_level: str = "INFO", log_file: Optional[Path] = None):
    """Setup structured logging."""
    # Create formatter
    formatter = StructuredLogFormatter()
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # File handler if specified
    handlers = [console_handler]
    
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        handlers=handlers,
        force=True
    )
    
    # Reduce noise from libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def log_with_context(
    level: str,
    message: str,
    extra_data: Optional[Dict[str, Any]] = None
):
    """Log with structured context."""
    logger_method = getattr(logger, level.lower())
    
    extra = {"extra_data": extra_data or {}}
    logger_method(message, extra=extra)


def get_logger_with_context(name: str) -> logging.Logger:
    """Get logger that includes context in all messages."""
    return logging.getLogger(name)


# Global observability manager
_observability: Optional[ObservabilityManager] = None
_performance: Optional[PerformanceMonitor] = None


def get_observability() -> ObservabilityManager:
    """Get global observability manager."""
    global _observability
    if _observability is None:
        _observability = ObservabilityManager()
    return _observability


def get_performance_monitor() -> PerformanceMonitor:
    """Get global performance monitor."""
    global _performance
    if _performance is None:
        _performance = PerformanceMonitor()
    return _performance


# Convenience decorators
def timed(operation_name: str):
    """Decorator to time operations."""
    return get_performance_monitor().time_operation(operation_name)


def traced(span_name: str):
    """Decorator to add distributed tracing."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            obs = get_observability()
            span_id = obs.start_span(span_name)
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                obs.end_span(span_id)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            obs = get_observability()
            span_id = obs.start_span(span_name)
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                obs.end_span(span_id)
        
        return async_wrapper if hasattr(func, '__code__') and func.__code__.co_flags & 0x80 else sync_wrapper
    return decorator
