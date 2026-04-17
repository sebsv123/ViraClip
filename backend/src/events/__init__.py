"""
ViraClip Event System
=====================
Typed, Redis-backed pub/sub events that power real-time SSE progress streaming.

Public API:
    from src.events import EventBus, EventType, PipelineEvent, event_to_sse
"""
from .bus import EventBus
from .sse_bridge import event_to_sse, make_connected_sse, make_error_sse
from .types import EventType, PipelineEvent

__all__ = [
    "EventBus",
    "EventType",
    "PipelineEvent",
    "event_to_sse",
    "make_connected_sse",
    "make_error_sse",
]
