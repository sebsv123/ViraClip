"""
Usage Analytics API Routes — Phase 20

GET /usage/{user_id}/summary     → per-user daily + total API call counts
GET /usage/{user_id}/daily       → breakdown by day (last N days)
GET /usage/{user_id}/totals      → lifetime totals per endpoint
POST /usage/{user_id}/record     → manually record a usage event (internal/testing)

GET /clips/{clip_id}/thumbnail   → extract & return JPEG frame path
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(tags=["usage-analytics"])
logger = logging.getLogger(__name__)


# ── Usage Analytics ────────────────────────────────────────────────────────

@router.get("/usage/{user_id}/summary")
async def usage_summary(user_id: str, days: int = Query(7, ge=1, le=90)):
    from src.services.usage_analytics_service import get_usage_summary
    return await get_usage_summary(user_id, days=days)


@router.get("/usage/{user_id}/daily")
async def daily_usage(
    user_id: str,
    days: int = Query(7, ge=1, le=90),
    endpoint: Optional[str] = Query(None),
):
    from src.services.usage_analytics_service import get_daily_usage
    return {"user_id": user_id, "days": days,
            "data": await get_daily_usage(user_id, endpoint=endpoint, days=days)}


@router.get("/usage/{user_id}/totals")
async def total_usage(user_id: str):
    from src.services.usage_analytics_service import get_total_usage
    totals = await get_total_usage(user_id)
    return {"user_id": user_id, "totals": totals,
            "grand_total": sum(totals.values())}


class UsageRecord(BaseModel):
    endpoint: str
    count: int = 1


@router.post("/usage/{user_id}/record")
async def record_usage_event(user_id: str, body: UsageRecord):
    from src.services.usage_analytics_service import record_usage
    await record_usage(user_id, body.endpoint, count=body.count)
    return {"recorded": True, "user_id": user_id,
            "endpoint": body.endpoint, "count": body.count}


# ── Clip Thumbnail ─────────────────────────────────────────────────────────

@router.get("/clips/{clip_id}/thumbnail")
async def clip_thumbnail(
    clip_id: str,
    clip_path: str = Query(..., description="Absolute path to the clip file"),
    timestamp: float = Query(1.0, ge=0),
    width: int = Query(480, ge=64, le=1920),
):
    """Extract a JPEG thumbnail from a clip and return its storage path."""
    from src.services.clip_thumbnail_service import extract_thumbnail
    path = await extract_thumbnail(clip_path, clip_id,
                                   timestamp=timestamp, width=width)
    if path is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Thumbnail extraction failed")
    return {"clip_id": clip_id, "thumbnail_path": path,
            "timestamp": timestamp, "width": width}
