"""
Flagging, Compression & Analytics Aggregation API Routes — Phase 27

Flagging/Moderation:
  POST   /clips/{clip_id}/report         → submit user report
  GET    /clips/{clip_id}/reports        → list reports (moderator only)
  GET    /clips/{clip_id}/flag-meta      → get flag summary
  POST   /clips/{clip_id}/resolve        → resolve all reports (moderator)
  GET    /users/{user_id}/reported       → check clips reported by user

Smart Compression:
  GET    /clips/{clip_id}/compression     → get recommendation
  DELETE /clips/{clip_id}/compression     → clear cache
  POST   /clips/{clip_id}/compress       → run compression (async)

Analytics Aggregation:
  POST   /clips/{clip_id}/analytics/view  → record a view
  GET    /clips/{clip_id}/analytics/daily → daily stats
  GET    /clips/{clip_id}/analytics/weekly → weekly stats
  GET    /clips/{clip_id}/analytics/range → date range query
  GET    /clips/{clip_id}/analytics/periods → available dates/weeks
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["flagging-compression-analytics"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

class ReportCreate(BaseModel):
    reporter_id: str
    reason: str
    details: str = ""


class ResolveReports(BaseModel):
    moderator_id: str
    resolution: str  # e.g., "dismissed", "content_removed", "user_warned"


class ViewRecord(BaseModel):
    viewer_id: str
    watch_seconds: float
    completed: bool = False


class CompressRequest(BaseModel):
    target_size_mb: Optional[float] = None
    force: bool = False


# ── Flagging/Moderation ──────────────────────────────────────────────────────

@router.post("/clips/{clip_id}/report")
async def submit_report(clip_id: str, body: ReportCreate):
    from src.services.clip_flagging_service import submit_report as svc, has_user_reported
    if await has_user_reported(body.reporter_id, clip_id):
        raise HTTPException(status_code=409, detail="User already reported this clip")
    try:
        return await svc(clip_id, body.reporter_id, body.reason, body.details)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/clips/{clip_id}/reports")
async def get_clip_reports(clip_id: str, limit: int = Query(50, ge=1, le=100)):
    from src.services.clip_flagging_service import get_clip_reports as svc
    reports = await svc(clip_id, limit=limit)
    return {"clip_id": clip_id, "count": len(reports), "reports": reports}


@router.get("/clips/{clip_id}/flag-meta")
async def get_flag_meta(clip_id: str):
    from src.services.clip_flagging_service import get_clip_flag_meta as svc
    meta = await svc(clip_id)
    if meta is None:
        return {"clip_id": clip_id, "flags_count": 0, "auto_action": None}
    return meta


@router.post("/clips/{clip_id}/resolve")
async def resolve_reports(clip_id: str, body: ResolveReports):
    from src.services.clip_flagging_service import resolve_reports as svc
    return await svc(clip_id, body.moderator_id, body.resolution)


@router.get("/users/{user_id}/reported")
async def get_user_reported_clips(user_id: str, clip_id: Optional[str] = Query(None)):
    from src.services.clip_flagging_service import has_user_reported
    if clip_id:
        reported = await has_user_reported(user_id, clip_id)
        return {"user_id": user_id, "clip_id": clip_id, "reported": reported}
    return {"user_id": user_id, "reported": []}


# ── Smart Compression ────────────────────────────────────────────────────────

@router.get("/clips/{clip_id}/compression")
async def get_compression_profile(clip_id: str):
    from src.services.smart_compression_service import get_compression_profile
    profile = await get_compression_profile(clip_id)
    return profile


@router.delete("/clips/{clip_id}/compression")
async def clear_compression_profile(clip_id: str):
    from src.services.smart_compression_service import clear_compression_profile
    await clear_compression_profile(clip_id)
    return {"cleared": True, "clip_id": clip_id}


# ── Analytics Aggregation ────────────────────────────────────────────────────

@router.post("/clips/{clip_id}/analytics/view")
async def record_view(clip_id: str, body: ViewRecord):
    from src.services.clip_analytics_aggregation_service import record_view as svc
    return await svc(clip_id, body.viewer_id, body.watch_seconds, body.completed)


@router.get("/clips/{clip_id}/analytics/daily")
async def get_daily_stats(clip_id: str, date: Optional[str] = Query(None)):
    from src.services.clip_analytics_aggregation_service import get_daily_stats as svc
    stats = await svc(clip_id, date)
    return stats


@router.get("/clips/{clip_id}/analytics/weekly")
async def get_weekly_stats(clip_id: str, week: Optional[str] = Query(None)):
    from src.services.clip_analytics_aggregation_service import get_weekly_stats as svc
    stats = await svc(clip_id, week)
    return stats


@router.get("/clips/{clip_id}/analytics/range")
async def get_analytics_range(
    clip_id: str,
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)"),
):
    from src.services.clip_analytics_aggregation_service import get_analytics_range as svc
    results = await svc(clip_id, start, end)
    return {"clip_id": clip_id, "start": start, "end": end, "count": len(results), "data": results}


@router.get("/clips/{clip_id}/analytics/periods")
async def get_available_periods(clip_id: str):
    from src.services.clip_analytics_aggregation_service import get_available_periods as svc
    return await svc(clip_id)
