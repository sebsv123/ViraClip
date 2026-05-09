"""
Dry-run mode for pipeline simulation without cost or file generation.
Propagated via ContextVar — no parameter pollution.
"""
import contextvars
import logging
from typing import Optional

_dry_run_var: contextvars.ContextVar[bool] = contextvars.ContextVar("dry_run", default=False)
_actions_skipped: contextvars.ContextVar[list] = contextvars.ContextVar("actions_skipped", default=[])


def set_dry_run(enabled: bool) -> None:
    _dry_run_var.set(enabled)
    if enabled:
        _actions_skipped.set([])


def is_dry_run() -> bool:
    return _dry_run_var.get()


def dry_run_skip(action: str, **details) -> None:
    """Loguea qué acción se saltaría en modo dry_run."""
    logger = logging.getLogger("dry_run")
    detail_str = " | ".join(f"{k}={v}" for k, v in details.items())
    msg = f"[DRY RUN] SKIP {action} — {detail_str}"
    logger.info(msg)
    actions = _actions_skipped.get()
    actions.append(msg)
    _actions_skipped.set(actions)


def get_dry_run_report() -> dict:
    """Retorna el reporte de acciones saltadas."""
    return {
        "actions_skipped": _actions_skipped.get(),
        "estimated_cost_usd": 0.0,
        "would_generate_clips": 0,
        "pipeline_gates_passed": ["preflight"],
    }


def _mock_transcript() -> dict:
    return {
        "text": "[DRY RUN] Mock transcript",
        "segments": [{"start": 0, "end": 10, "text": "Mock segment"}],
        "language": "es",
    }


def _mock_segments() -> list:
    return [
        {"start": 0, "end": 30, "score": 0.85, "heading": "[DRY RUN] Mock segment 1"},
        {"start": 60, "end": 90, "score": 0.72, "heading": "[DRY RUN] Mock segment 2"},
    ]
