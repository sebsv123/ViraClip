"""
Content Calendar API — ViraClip

Endpoints for scheduling clips at optimal times, managing the publishing queue,
and viewing the full content calendar.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.content_calendar import (
    ContentCalendarService,
    ContentType,
    get_calendar_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calendar", tags=["calendar"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    clip_id: str
    platforms: List[str]
    preferred_time: Optional[str] = None   # ISO-8601 or None for auto-optimal
    content_type: str = "short_form"
    caption: str = ""
    hashtags: List[str] = []
    thumbnail_url: str = ""
    auto_optimize: bool = True


class RescheduleRequest(BaseModel):
    new_time: str    # ISO-8601
    reason: str = ""


class BulkScheduleItem(BaseModel):
    clip_id: str
    platforms: List[str]
    content_type: str = "short_form"
    caption: str = ""
    hashtags: List[str] = []
    thumbnail_url: str = ""


class BulkScheduleRequest(BaseModel):
    items: List[BulkScheduleItem]
    spacing_hours: int = 4


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _content_type(value: str) -> ContentType:
    try:
        return ContentType(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content_type '{value}'. "
                   f"Choose: {[ct.value for ct in ContentType]}",
        )


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid datetime '{value}'. Use ISO-8601.")


def _fmt_scheduled(c) -> Dict[str, Any]:
    return {
        "schedule_id": c.schedule_id,
        "clip_id": c.clip_id,
        "platforms": c.platforms,
        "scheduled_time": c.scheduled_time,
        "caption": c.caption,
        "hashtags": c.hashtags,
        "thumbnail_url": c.thumbnail_url,
        "content_type": c.content_type.value,
        "status": c.status.value,
        "optimal_score": c.optimal_score,
        "timezone": c.timezone,
        "created_at": c.created_at,
    }


# ------------------------------------------------------------------
# Schedule CRUD
# ------------------------------------------------------------------

@router.post("/schedule")
async def schedule_clip(request: Request, body: ScheduleRequest):
    """
    Schedule a clip for publication.
    Omit `preferred_time` to let the service choose the optimal posting window.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc: ContentCalendarService = get_calendar_service()
    preferred = _parse_dt(body.preferred_time) if body.preferred_time else None

    try:
        scheduled = await svc.schedule_content(
            user_id=user_id,
            clip_id=body.clip_id,
            platforms=body.platforms,
            preferred_time=preferred,
            content_type=_content_type(body.content_type),
            caption=body.caption,
            hashtags=body.hashtags,
            thumbnail_url=body.thumbnail_url,
            auto_optimize=body.auto_optimize,
        )
        return {"status": "scheduled", "item": _fmt_scheduled(scheduled)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Calendar] schedule failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule/bulk")
async def bulk_schedule(request: Request, body: BulkScheduleRequest):
    """Bulk-schedule multiple clips with automatic time spacing."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_calendar_service()
    items_dicts = [i.model_dump() for i in body.items]

    try:
        scheduled_list = await svc.bulk_schedule(
            user_id=user_id,
            items=items_dicts,
            spacing_hours=body.spacing_hours,
        )
        return {
            "status": "scheduled",
            "count": len(scheduled_list),
            "items": [_fmt_scheduled(s) for s in scheduled_list],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/schedule/{schedule_id}/reschedule")
async def reschedule_clip(schedule_id: str, body: RescheduleRequest):
    """Move a scheduled item to a new time."""
    svc = get_calendar_service()
    success = await svc.reschedule_content(
        schedule_id=schedule_id,
        new_time=_parse_dt(body.new_time),
        reason=body.reason,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found or already published")
    return {"status": "rescheduled", "schedule_id": schedule_id, "new_time": body.new_time}


@router.delete("/schedule/{schedule_id}")
async def cancel_scheduled(schedule_id: str):
    """Cancel a scheduled item (reverts to draft)."""
    svc = get_calendar_service()
    success = await svc.cancel_scheduled(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found or cannot be cancelled")
    return {"status": "cancelled", "schedule_id": schedule_id}


# ------------------------------------------------------------------
# Calendar views
# ------------------------------------------------------------------

@router.get("/view")
async def get_calendar_view(
    request: Request,
    start: str,
    end: str,
):
    """
    Get all scheduled content in a date range.
    Returns events + suggested optimal posting slots for empty windows.
    `start` and `end` are ISO-8601 datetimes.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_calendar_service()
    try:
        view = await svc.get_calendar_view(
            user_id=user_id,
            start_date=_parse_dt(start),
            end_date=_parse_dt(end),
        )
        return {"status": "success", **view}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue")
async def get_publishing_queue(request: Request, limit: int = 20):
    """Get the upcoming publishing queue sorted by scheduled time."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_calendar_service()
    queue = await svc.get_publishing_queue(user_id=user_id, limit=limit)
    return {"status": "success", "count": len(queue), "queue": queue}


@router.get("/stats")
async def get_scheduling_stats(request: Request):
    """Get summary stats: total scheduled, published, failed, avg optimal score."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_calendar_service()
    stats = svc.get_scheduling_stats(user_id=user_id)
    return {"status": "success", "stats": stats}
