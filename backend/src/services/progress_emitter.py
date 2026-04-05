"""
Progress emitter — backward-compatible facade over the EventBus.

All existing callers (coordinator.py, etc.) continue to work unchanged.
Internally every call is delegated to EventBus.publish() so the SSE
endpoint receives properly named events.

A module-level `redis` stub is intentionally kept so the autouse
conftest fixture `mock_redis_progress_emitter` can monkeypatch it
without raising AttributeError.
"""

import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

# Stub so conftest can monkeypatch "src.services.progress_emitter.redis"
# without raising AttributeError.  EventBus manages its own connection.
redis = None  # noqa: F841  (overwritten by monkeypatch in tests)

# ------------------------------------------------------------------ #
# Stage → EventType mapping                                            #
# ------------------------------------------------------------------ #
_STAGE_TO_EVENT_TYPE = {
    "connected":     "connected",
    "analysis":      "analysis",
    "transcription": "transcription",
    "scoring":       "scoring",
    "render":        "render",
    "clip_ready":    "clip_ready",
    "creative":      "creative",
    "done":          "done",
    "error":         "error",
    "cache_hit":     "cache_hit",
}


def _stage_to_event_type(stage: str) -> str:
    return _STAGE_TO_EVENT_TYPE.get(stage, "analysis")


# ------------------------------------------------------------------ #
# Public API (same signatures as before)                               #
# ------------------------------------------------------------------ #

async def emit_progress(
    task_id: str,
    stage: str,
    percent: int,
    message: str,
    clip_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Emit a pipeline progress event.

    Routes through EventBus so the SSE endpoint receives a named event
    (event: progress / event: close / etc.) instead of a generic data-only
    message that no frontend listener would catch.
    """
    from ..events.bus import EventBus
    from ..events.types import PipelineEvent

    await EventBus.publish(PipelineEvent(
        task_id=task_id,
        event_type=_stage_to_event_type(stage),
        stage=stage,
        progress=min(100, max(0, percent)),
        message=message,
        clip_id=clip_id,
        metadata=metadata,
    ))
    logger.debug("emit_progress task=%s stage=%s progress=%d%%", task_id, stage, percent)


async def get_progress_subscriber(task_id: str) -> AsyncGenerator[str, None]:
    """
    Legacy subscriber — yields raw JSON strings.
    New code should call EventBus.subscribe() directly.
    """
    import json
    from ..events.bus import EventBus

    async for event in EventBus.subscribe(task_id):
        yield json.dumps(event.to_dict())


async def check_channel_active(task_id: str) -> bool:
    """Return True if at least one SSE client is subscribed to this task."""
    from ..events.bus import EventBus
    return await EventBus.is_active(task_id)


async def emit_clip_generated(
    task_id: str,
    clip_id: str,
    clip_path: str,
    clip_number: int,
    total_clips: int,
) -> None:
    """Emit a clip_ready event when a single clip finishes rendering."""
    from ..events.bus import EventBus
    from ..events.types import EventType, PipelineEvent

    pct = int((clip_number / max(total_clips, 1)) * 100)
    await EventBus.publish(PipelineEvent(
        task_id=task_id,
        event_type=EventType.CLIP_READY,
        stage="render",
        progress=pct,
        message=f"Generated clip {clip_number} of {total_clips}",
        clip_id=clip_id,
        metadata={
            "clip_path":   clip_path,
            "clip_number": clip_number,
            "total_clips": total_clips,
        },
    ))


async def emit_error(task_id: str, error_message: str, stage: str = "error") -> None:
    """Emit a pipeline error event."""
    from ..events.bus import EventBus
    from ..events.types import EventType, PipelineEvent

    await EventBus.publish(PipelineEvent(
        task_id=task_id,
        event_type=EventType.ERROR,
        stage=stage,
        progress=0,
        message=error_message,
        metadata={"error_stage": stage},
    ))


async def emit_completion(task_id: str, clips_generated: int) -> None:
    """Emit the final done event — closes all SSE streams for this task."""
    from ..events.bus import EventBus
    from ..events.types import EventType, PipelineEvent

    await EventBus.publish(PipelineEvent(
        task_id=task_id,
        event_type=EventType.DONE,
        stage="done",
        progress=100,
        message=f"✅ Processing complete: {clips_generated} clips generated",
        metadata={"clips_generated": clips_generated},
    ))
