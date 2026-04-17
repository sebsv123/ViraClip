import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


TRACE_HEADER = "x-trace-id"
_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")


def get_trace_id() -> str:
    return _trace_id_ctx.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id_ctx.set(trace_id)


def clear_trace_id() -> None:
    _trace_id_ctx.set("-")


def generate_trace_id() -> str:
    return uuid4().hex


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        
        # Add structured context fields if present
        for field in ["task_id", "user_id", "stage", "clip_index", "error_code"]:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        
        # Add custom extra fields
        if hasattr(record, "extra_context"):
            payload["context"] = record.extra_context

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


class StructuredLogger:
    """
    Helper for structured logging with task context.
    
    Usage:
        logger = StructuredLogger("my_module", task_id="abc123")
        logger.info("Processing started", stage="download")
        logger.error("Download failed", error_code="E1001", extra={"url": url})
    """
    
    def __init__(self, name: str, **default_context):
        self.logger = logging.getLogger(name)
        self.default_context = default_context
    
    def _log(self, level: int, message: str, **kwargs):
        """Internal log with structured context."""
        # Merge default context with call-specific context
        context = {**self.default_context, **kwargs}
        
        # Create log record with extra fields
        extra = {}
        for key, value in context.items():
            if key not in ["exc_info", "stack_info", "stacklevel", "extra"]:
                extra[key] = value
        
        self.logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)


def _get_utf8_stdout():
    """Return a UTF-8 wrapped stdout, replacing unmappable chars instead of crashing."""
    import sys as _sys, io as _io
    if hasattr(_sys.stdout, 'buffer'):
        return _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    return _sys.stdout


def configure_logging() -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    formatter = JsonLogFormatter()
    trace_filter = TraceIdFilter()

    stream_handler = logging.StreamHandler(_get_utf8_stdout())
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(trace_filter)

    app_file_handler = logging.FileHandler(logs_dir / "backend.log", encoding='utf-8')
    app_file_handler.setLevel(log_level)
    app_file_handler.setFormatter(formatter)
    app_file_handler.addFilter(trace_filter)

    error_file_handler = logging.FileHandler(logs_dir / "backend-error.log", encoding='utf-8')
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)
    error_file_handler.addFilter(trace_filter)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(app_file_handler)
    root_logger.addHandler(error_file_handler)
