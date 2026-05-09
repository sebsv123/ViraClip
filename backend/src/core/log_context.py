"""
Correlation ID for task-level log tracing.
Uses contextvars — thread-safe and asyncio-safe.
"""
import contextvars
import logging
from typing import Optional

_task_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("task_id", default=None)


def set_task_id(task_id: str) -> None:
    _task_id_var.set(task_id)


def get_task_id() -> Optional[str]:
    return _task_id_var.get()


def clear_task_id() -> None:
    _task_id_var.set(None)


class TaskIdFilter(logging.Filter):
    """Injects task_id into every log record as %(task_id)s."""

    def filter(self, record: logging.LogRecord) -> bool:
        task_id = _task_id_var.get()
        record.task_id = f"[{task_id[:8]}]" if task_id else "[--------]"
        return True


def configure_worker_logging():
    """Add TaskIdFilter to all root handlers and update format."""
    task_filter = TaskIdFilter()
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(task_filter)
    formatter = logging.Formatter(
        "%(asctime)s %(task_id)s %(name)s %(levelname)s %(message)s"
    )
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
