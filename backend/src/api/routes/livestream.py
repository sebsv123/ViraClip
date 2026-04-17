"""
Live Streaming API — ViraClip

Endpoints for monitoring live streams, extracting viral clips
in real-time, and publishing them to social platforms.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.live_streaming import (
    ClipTriggerType,
    StreamStatus,
    get_live_stream_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/livestream", tags=["livestream"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class StartMonitoringRequest(BaseModel):
    stream_id: Optional[str] = None
    stream_url: str
    platform: str = "youtube"
    auto_clip: bool = True
    clip_duration: int = 30
    viral_threshold: float = 75.0
    chat_monitoring: bool = True
    format: str = "vertical"


class ExtractClipRequest(BaseModel):
    duration: int = 30
    trigger: str = "manual"     # manual | auto_viral | chat | scheduled | event


class PublishClipRequest(BaseModel):
    platforms: List[str]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_trigger(value: str) -> ClipTriggerType:
    try:
        return ClipTriggerType(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trigger '{value}'. Choose: {[t.value for t in ClipTriggerType]}",
        )


# ------------------------------------------------------------------
# Stream management
# ------------------------------------------------------------------

@router.post("/start")
async def start_monitoring(body: StartMonitoringRequest):
    """
    Start monitoring a live stream for viral moment detection and clip extraction.
    Monitoring runs in the background and auto-extracts clips when the viral
    threshold is reached (if `auto_clip` is enabled).
    """
    import uuid
    stream_id = body.stream_id or f"stream_{uuid.uuid4().hex[:8]}"

    svc = get_live_stream_service()
    started = await svc.start_stream_monitoring(
        stream_id=stream_id,
        stream_url=body.stream_url,
        platform=body.platform,
        config={
            "auto_clip": body.auto_clip,
            "clip_duration": body.clip_duration,
            "viral_threshold": body.viral_threshold,
            "chat_monitoring": body.chat_monitoring,
            "format": body.format,
        },
    )
    if not started:
        raise HTTPException(
            status_code=409,
            detail=f"Stream '{stream_id}' is already being monitored",
        )
    return {"status": "monitoring", "stream_id": stream_id, "platform": body.platform}


@router.delete("/{stream_id}/stop")
async def stop_monitoring(stream_id: str):
    """Stop monitoring a live stream."""
    svc = get_live_stream_service()
    stopped = await svc.stop_stream_monitoring(stream_id)
    if not stopped:
        raise HTTPException(status_code=404, detail=f"Stream '{stream_id}' not found")
    return {"status": "stopped", "stream_id": stream_id}


@router.get("")
def list_active_streams():
    """List all currently monitored live streams."""
    svc = get_live_stream_service()
    streams = svc.get_active_streams()
    return {"status": "success", "count": len(streams), "streams": streams}


@router.get("/{stream_id}")
def get_stream_status(stream_id: str):
    """Get the current status, clip count, and config of a monitored stream."""
    svc = get_live_stream_service()
    status = svc.get_stream_status(stream_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Stream '{stream_id}' not found")
    return {"status": "success", "stream": status}


# ------------------------------------------------------------------
# Clip extraction
# ------------------------------------------------------------------

@router.post("/{stream_id}/clip")
async def extract_clip(stream_id: str, body: ExtractClipRequest):
    """
    Manually extract a clip from the last N seconds of a live stream.

    `trigger` options: `manual | auto_viral | chat | scheduled | event`
    """
    svc = get_live_stream_service()
    clip = await svc.extract_clip(
        stream_id=stream_id,
        duration=body.duration,
        trigger=_parse_trigger(body.trigger),
    )
    if clip is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stream '{stream_id}' not found or not active",
        )
    return {
        "status": "extracting",
        "clip_id": clip.clip_id,
        "stream_id": clip.stream_id,
        "duration": clip.duration_seconds,
        "trigger": clip.trigger_type.value,
        "clip_status": clip.status,
    }


@router.get("/{stream_id}/clips")
def get_stream_clips(stream_id: str, status: Optional[str] = None):
    """
    Get all clips extracted from a stream, sorted newest-first.
    Optionally filter by `status`: `pending | processing | ready | published`.
    """
    svc = get_live_stream_service()
    clips = svc.get_stream_clips(stream_id, status=status)
    return {"status": "success", "count": len(clips), "clips": clips}


@router.post("/clips/{clip_id}/publish")
async def publish_clip(clip_id: str, body: PublishClipRequest):
    """Publish a ready live clip to one or more social platforms."""
    if not body.platforms:
        raise HTTPException(status_code=400, detail="platforms must not be empty")

    svc = get_live_stream_service()
    result = await svc.publish_clip(clip_id, body.platforms)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return {"status": "published", **result}


# ------------------------------------------------------------------
# Metadata
# ------------------------------------------------------------------

@router.get("/statuses/list")
def list_statuses():
    """List all stream statuses and clip trigger types."""
    return {
        "stream_statuses": [s.value for s in StreamStatus],
        "clip_triggers": [t.value for t in ClipTriggerType],
    }
