"""Performance Feedback Webhook API routes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/performance-webhook", tags=["performance-webhook"])


class ManualEventRequest(BaseModel):
    clip_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    avg_view_duration_pct: float = 0.0
    caption_template: Optional[str] = None
    music_genre: Optional[str] = None


@router.post("/tiktok")
async def receive_tiktok_webhook(request: Request):
    """Receive TikTok performance webhook and record event."""
    payload = await request.json()
    from ...services.performance_webhook_service import (
        parse_tiktok_webhook, record_performance_event
    )
    event = parse_tiktok_webhook(payload)
    if not event:
        raise HTTPException(status_code=400, detail="Could not parse TikTok webhook payload")
    recorded = record_performance_event(event)
    return {"status": "recorded", "event": recorded}


@router.post("/instagram")
async def receive_instagram_webhook(request: Request):
    """Receive Instagram performance webhook and record event."""
    payload = await request.json()
    from ...services.performance_webhook_service import (
        parse_instagram_webhook, record_performance_event
    )
    event = parse_instagram_webhook(payload)
    if not event:
        raise HTTPException(status_code=400, detail="Could not parse Instagram webhook payload")
    recorded = record_performance_event(event)
    return {"status": "recorded", "event": recorded}


@router.post("/youtube")
async def receive_youtube_webhook(request: Request):
    """Receive YouTube performance webhook and record event."""
    payload = await request.json()
    from ...services.performance_webhook_service import (
        parse_youtube_webhook, record_performance_event
    )
    event = parse_youtube_webhook(payload)
    if not event:
        raise HTTPException(status_code=400, detail="Could not parse YouTube webhook payload")
    recorded = record_performance_event(event)
    return {"status": "recorded", "event": recorded}


@router.post("/manual")
async def record_manual_event(body: ManualEventRequest):
    """Manually record a performance event (for testing or manual sync)."""
    from ...services.performance_webhook_service import (
        PerformanceEvent, record_performance_event
    )
    event = PerformanceEvent(
        clip_id=body.clip_id,
        platform=body.platform,
        views=body.views,
        likes=body.likes,
        comments=body.comments,
        shares=body.shares,
        saves=body.saves,
        avg_view_duration_pct=body.avg_view_duration_pct,
    )
    recorded = record_performance_event(
        event,
        caption_template=body.caption_template,
        music_genre=body.music_genre,
    )
    return {"status": "recorded", "event": recorded}


@router.get("/top-templates")
def get_top_templates(limit: int = 10):
    """Return top-performing caption templates ranked by viral rate."""
    from ...services.performance_webhook_service import get_top_templates
    return {"templates": get_top_templates(limit)}


@router.get("/summary")
def get_summary(clip_id: Optional[str] = None):
    """Return overall performance summary, optionally filtered by clip."""
    from ...services.performance_webhook_service import get_performance_summary
    return get_performance_summary(clip_id)
