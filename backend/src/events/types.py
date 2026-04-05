"""
Typed domain events for the ViraClip processing pipeline.

Every pipeline stage emits a PipelineEvent. The EventBus serialises it to
Redis pub/sub; the SSE bridge deserialises it back and formats it as a
properly-named SSE message so the frontend's addEventListener("progress", ...)
etc. actually fires.
"""
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class EventType:
    """All pipeline event type constants."""
    CONNECTED     = "connected"
    ANALYSIS      = "analysis"
    TRANSCRIPTION = "transcription"
    SCORING       = "scoring"
    RENDER        = "render"
    CLIP_READY    = "clip_ready"
    CREATIVE      = "creative"
    DONE          = "done"
    ERROR         = "error"
    CACHE_HIT     = "cache_hit"

    # Terminal event types — the SSE stream closes after receiving one
    TERMINAL = frozenset({DONE, ERROR, CACHE_HIT})


# Map each EventType → the SSE named event the frontend listens for.
#
# Frontend listeners (page.tsx):
#   eventSource.addEventListener("status",    handler)  ← initial connection
#   eventSource.addEventListener("progress",  handler)  ← analysis/scoring/render progress
#   eventSource.addEventListener("clip_ready",handler)  ← individual clip ready
#   eventSource.addEventListener("close",     handler)  ← task finished
#   eventSource.addEventListener("error",     handler)  ← pipeline error
SSE_EVENT_NAME: Dict[str, str] = {
    EventType.CONNECTED:     "status",
    EventType.ANALYSIS:      "progress",
    EventType.TRANSCRIPTION: "progress",
    EventType.SCORING:       "progress",
    EventType.RENDER:        "progress",
    EventType.CLIP_READY:    "clip_ready",
    EventType.CREATIVE:      "progress",
    EventType.DONE:          "close",
    EventType.ERROR:         "error",
    EventType.CACHE_HIT:     "close",
}


@dataclass
class PipelineEvent:
    """
    Single unit flowing through the event bus.

    Required fields (no default):
        task_id, event_type, stage, progress, message

    Optional fields carry extra payload for clip_ready and error events.
    """
    task_id:     str
    event_type:  str
    stage:       str
    progress:    int
    message:     str

    # Clip-level payload (clip_ready events)
    clip_id:     Optional[str]           = None
    clip_index:  Optional[int]           = None
    total_clips: Optional[int]           = None
    clip_data:   Optional[Dict[str, Any]]= None

    # Error payload
    error_code:  Optional[str]           = None

    # Generic extra metadata
    metadata:    Optional[Dict[str, Any]]= None

    # Legacy compatibility — mirrors "status" field from old ProgressTracker
    status:      Optional[str]           = None

    timestamp:   float = field(default_factory=time.time)

    # ------------------------------------------------------------------ #
    # Derived properties                                                    #
    # ------------------------------------------------------------------ #

    @property
    def sse_event_name(self) -> str:
        """The SSE event name the frontend addEventListener expects."""
        return SSE_EVENT_NAME.get(self.event_type, "progress")

    @property
    def is_terminal(self) -> bool:
        """True → this event ends the SSE stream."""
        return self.event_type in EventType.TERMINAL

    # ------------------------------------------------------------------ #
    # Serialisation                                                         #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        """Compact dict — None values omitted for a lean SSE payload."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineEvent":
        """
        Deserialise from a Redis pub/sub message.

        Handles both the new format (event_type + stage) and the legacy
        ProgressTracker format (status, no event_type / stage).
        """
        valid = {f.name for f in dataclasses.fields(cls)}
        filtered: Dict[str, Any] = {k: v for k, v in data.items() if k in valid}

        # --- Legacy compat: infer event_type from status ---
        if "event_type" not in filtered:
            legacy_status = data.get("status", "processing")
            legacy_evt_type = data.get("event_type")  # might be in raw data
            if legacy_evt_type:
                filtered["event_type"] = legacy_evt_type
            elif legacy_status == "completed":
                filtered["event_type"] = EventType.DONE
            elif legacy_status in ("error", "failed"):
                filtered["event_type"] = EventType.ERROR
            elif data.get("event_type") == EventType.CLIP_READY:
                filtered["event_type"] = EventType.CLIP_READY
            else:
                filtered["event_type"] = EventType.ANALYSIS

        # stage defaults to event_type when missing
        if "stage" not in filtered:
            filtered["stage"] = filtered["event_type"]

        # Guarantee required numeric / string fields have defaults
        filtered.setdefault("progress", 0)
        filtered.setdefault("message", "")

        return cls(**filtered)
