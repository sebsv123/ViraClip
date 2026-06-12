"""Pure helpers for reconciling worker source arguments with task DB state."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def resolve_task_source_contract(
    *,
    task_record: Dict[str, Any] | None,
    url: str,
    source_type: str,
) -> Tuple[str, str, Dict[str, Any]]:
    """Return the canonical source URL/type for a task.

    The task record is treated as authoritative when it contains a source URL
    and source type.  This protects the worker from malformed enqueue argument
    order or stale queue payloads.
    """

    supplied_url = str(url or "").strip()
    supplied_source_type = str(source_type or "").strip()
    task_source_url = ""
    task_source_type = ""

    if isinstance(task_record, dict):
        task_source_url = str(task_record.get("source_url") or "").strip()
        task_source_type = str(task_record.get("source_type") or "").strip()

    resolved_url = task_source_url or supplied_url
    resolved_source_type = task_source_type or supplied_source_type

    if not resolved_source_type and resolved_url:
        lowered = resolved_url.lower()
        if "youtu.be/" in lowered or "youtube.com/" in lowered or "youtube-nocookie.com/" in lowered:
            resolved_source_type = "youtube"
        else:
            resolved_source_type = "video_url"

    if not resolved_url:
        resolved_url = supplied_url

    diagnostics = {
        "task_source_url": task_source_url,
        "task_source_type": task_source_type,
        "supplied_url": supplied_url,
        "supplied_source_type": supplied_source_type,
        "resolved_url": resolved_url,
        "resolved_source_type": resolved_source_type,
        "used_task_record": bool(task_source_url or task_source_type),
        "mismatch_detected": bool(
            (task_source_url and supplied_url and task_source_url != supplied_url)
            or (task_source_type and supplied_source_type and task_source_type != supplied_source_type)
        ),
    }
    return resolved_url, resolved_source_type, diagnostics
