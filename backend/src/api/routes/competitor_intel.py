"""
Competitor Intelligence API — ViraClip

Endpoints for adding competitors, fetching dashboards, comparing
performance, and generating trend insights from monitored content.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.competitor_intelligence import (
    CompetitorPlatform,
    get_competitor_intelligence_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/competitor-intel", tags=["competitor-intel"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class AddCompetitorRequest(BaseModel):
    name: str
    platform_handles: Dict[str, str]    # {"youtube": "@handle", "tiktok": "@handle"}
    niche: str


class CompareRequest(BaseModel):
    user_metrics: Dict[str, Any]        # {"avg_engagement": 5.2, "avg_virality": 70.0}
    competitor_ids: Optional[List[str]] = None


class PerformanceRequest(BaseModel):
    competitor_id: str
    days: int = 30


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/competitors")
async def add_competitor(body: AddCompetitorRequest):
    """
    Add a competitor to the monitoring system.
    Fetches initial follower counts and syncs recent videos immediately.
    """
    if not body.platform_handles:
        raise HTTPException(status_code=400, detail="platform_handles must not be empty")

    svc = get_competitor_intelligence_service()
    try:
        competitor = await svc.add_competitor(
            body.name, body.platform_handles, body.niche
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "added",
        "competitor_id": competitor.competitor_id,
        "name": competitor.name,
        "platforms": competitor.platforms,
        "follower_count": competitor.follower_count,
        "added_at": competitor.added_at,
    }


@router.get("/dashboard")
def get_dashboard(user_id: str = "default"):
    """
    Competitor intelligence dashboard: all tracked competitors,
    their 10 highest-virality videos, and latest trend insights.
    """
    svc = get_competitor_intelligence_service()
    return {"status": "success", "dashboard": svc.get_competitor_dashboard(user_id)}


@router.get("/competitors/{competitor_id}")
def get_performance(competitor_id: str, days: int = 30):
    """
    Performance breakdown for a single competitor over the last N days.
    Returns video count, total views, avg engagement, avg virality,
    best-performing video, and per-platform breakdown.
    """
    svc = get_competitor_intelligence_service()
    data = svc.get_competitor_performance(competitor_id, days)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Competitor '{competitor_id}' not found or has no recent videos",
        )
    return {"status": "success", "performance": data}


@router.post("/compare")
def compare_to_competitors(body: CompareRequest):
    """
    Compare your own metrics against tracked competitors.

    Pass `user_metrics` with at least `avg_engagement` and `avg_virality`
    (both 0-100). Optionally specify `competitor_ids`; omit for all tracked.

    Returns per-competitor engagement/virality gaps and actionable recommendations.
    """
    if not body.user_metrics:
        raise HTTPException(status_code=400, detail="user_metrics must not be empty")

    svc = get_competitor_intelligence_service()
    result = svc.compare_to_competitors(body.user_metrics, body.competitor_ids)
    return {"status": "success", "comparison": result}


@router.post("/monitoring/start")
async def start_monitoring(interval_minutes: int = 30):
    """
    Start continuous background monitoring of all tracked competitors.
    Syncs new videos and generates trend insights every `interval_minutes` minutes.
    """
    if interval_minutes < 1:
        raise HTTPException(status_code=400, detail="interval_minutes must be >= 1")

    svc = get_competitor_intelligence_service()
    if svc._is_monitoring:
        return {"status": "already_running", "interval_minutes": interval_minutes}

    import asyncio
    asyncio.create_task(svc.start_monitoring(interval_minutes))
    return {"status": "started", "interval_minutes": interval_minutes}


@router.post("/monitoring/stop")
async def stop_monitoring():
    """Stop the background competitor monitoring loop."""
    svc = get_competitor_intelligence_service()
    await svc.stop_monitoring()
    return {"status": "stopped"}


@router.get("/platforms")
def list_platforms():
    """List all supported competitor monitoring platforms."""
    return {"platforms": [p.value for p in CompetitorPlatform]}
