"""
SSE bridge — converts PipelineEvent objects into properly-named SSE messages.

SSE wire format:
    event: <name>\n
    data: <json>\n
    \n

Named events are required so the frontend's EventSource.addEventListener()
calls fire correctly.  A generic  "data: ...\n\n"  (no event: line) only
triggers the "message" handler which the page.tsx does NOT use.

Frontend listeners wired in page.tsx:
    eventSource.addEventListener("status",     handler)  ← connection ack
    eventSource.addEventListener("progress",   handler)  ← analysis / scoring / render
    eventSource.addEventListener("clip_ready", handler)  ← single clip ready
    eventSource.addEventListener("close",      handler)  ← pipeline finished
    eventSource.addEventListener("error",      handler)  ← pipeline error
"""
from __future__ import annotations

import json
from typing import Any, Dict

from .types import PipelineEvent


def event_to_sse(event: PipelineEvent) -> str:
    """
    Serialize *event* to a named SSE message string.

    Example output:
        event: progress\n
        data: {"task_id": "abc", "stage": "scoring", "progress": 55, ...}\n
        \n
    """
    return f"event: {event.sse_event_name}\ndata: {json.dumps(event.to_dict())}\n\n"


def make_connected_sse(task_id: str) -> str:
    """
    Initial handshake event sent immediately after the client connects.
    Maps to the frontend "status" listener.
    """
    payload: Dict[str, Any] = {
        "task_id": task_id,
        "event_type": "connected",
        "stage": "connected",
        "progress": 0,
        "message": "Stream connected — waiting for pipeline events",
        "status": "processing",
    }
    return f"event: status\ndata: {json.dumps(payload)}\n\n"


def make_error_sse(task_id: str, message: str) -> str:
    """
    Format a pipeline / connection error as a named SSE error event.
    Maps to the frontend "error" listener.
    """
    payload: Dict[str, Any] = {
        "task_id": task_id,
        "event_type": "error",
        "stage": "error",
        "progress": 0,
        "error": message,
        "message": message,
    }
    return f"event: error\ndata: {json.dumps(payload)}\n\n"


def make_heartbeat_sse() -> str:
    """
    SSE comment line — keeps the connection alive through proxies.
    Not received by JS listeners; ignored by EventSource.
    """
    return ": heartbeat\n\n"
