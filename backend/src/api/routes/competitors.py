"""
Competitor Intelligence API — ViraClip

Endpoints for tracking competitor channels, analyzing their viral content,
and generating actionable insights to improve user content strategy.
"""

import asyncio
import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.competitor_intelligence import get_competitor_intelligence_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/competitors", tags=["competitors"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class AddCompetitorRequest(BaseModel):
    name: str
    platform_handles: Dict[str, str]   # {"youtube": "@channel", "tiktok": "@handle"}
    niche: str


class CompareRequest(BaseModel):
    competitor_ids: Optional[List[str]] = None
    user_avg_engagement: float = 0.0
    user_avg_virality: float = 0.0


# ------------------------------------------------------------------
# Competitor management
# ------------------------------------------------------------------

@router.post("")
async def add_competitor(body: AddCompetitorRequest):
    """Add a competitor channel for ongoing monitoring."""
    svc = get_competitor_intelligence_service()
    try:
        competitor = await svc.add_competitor(
            name=body.name,
            platform_handles=body.platform_handles,
            niche=body.niche,
        )
        return {
            "status": "added",
            "competitor_id": competitor.competitor_id,
            "name": competitor.name,
            "platforms": competitor.platforms,
            "follower_count": competitor.follower_count,
        }
    except Exception as e:
        logger.error(f"[Competitors] add failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_competitors(request: Request):
    """Get the competitor intelligence dashboard for the current user."""
    svc = get_competitor_intelligence_service()
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"
    dashboard = svc.get_competitor_dashboard(user_id)
    return {"status": "success", **dashboard}


@router.get("/insights")
async def get_insights():
    """Get the latest trend insights derived from competitor monitoring."""
    svc = get_competitor_intelligence_service()
    dashboard = svc.get_competitor_dashboard("_global")
    return {
        "status": "success",
        "insights": dashboard["trend_insights"],
        "monitoring_active": dashboard["monitoring_active"],
    }


@router.get("/leaderboard")
async def viral_leaderboard(limit: int = 10):
    """Top-performing competitor videos ranked by virality score."""
    svc = get_competitor_intelligence_service()
    dashboard = svc.get_competitor_dashboard("_global")
    videos = dashboard["recent_viral_videos"][:limit]
    return {
        "status": "success",
        "count": len(videos),
        "videos": videos,
    }


@router.get("/{competitor_id}")
async def get_competitor_performance(competitor_id: str, days: int = 30):
    """Get performance metrics for a specific competitor over the last N days."""
    svc = get_competitor_intelligence_service()
    result = svc.get_competitor_performance(competitor_id, days=days)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Competitor '{competitor_id}' not found or no data available",
        )
    return {"status": "success", "performance": result}


@router.post("/compare")
async def compare_to_competitors(body: CompareRequest):
    """
    Compare your own engagement and virality metrics against tracked competitors.
    Returns gap analysis and actionable recommendations.
    """
    svc = get_competitor_intelligence_service()
    user_metrics = {
        "avg_engagement": body.user_avg_engagement,
        "avg_virality": body.user_avg_virality,
    }
    result = svc.compare_to_competitors(user_metrics, competitor_ids=body.competitor_ids)
    return {"status": "success", **result}


# ------------------------------------------------------------------
# Monitoring control
# ------------------------------------------------------------------

@router.post("/monitoring/start")
async def start_monitoring(interval_minutes: int = 30):
    """Start the background competitor monitoring loop."""
    import asyncio
    svc = get_competitor_intelligence_service()
    # Fire-and-forget — doesn't block the response
    asyncio.create_task(svc.start_monitoring(interval_minutes=interval_minutes))
    return {"status": "started", "interval_minutes": interval_minutes}


@router.post("/monitoring/stop")
async def stop_monitoring():
    """Stop the background competitor monitoring loop."""
    svc = get_competitor_intelligence_service()
    await svc.stop_monitoring()
    return {"status": "stopped"}


@router.post("/{competitor_id}/sync")
async def sync_competitor(competitor_id: str):
    """Manually trigger a sync of the latest videos for a specific competitor."""
    svc = get_competitor_intelligence_service()
    if competitor_id not in svc._competitors:
        raise HTTPException(status_code=404, detail=f"Competitor '{competitor_id}' not found")
    videos = await svc._sync_competitor_videos(competitor_id)
    return {
        "status": "synced",
        "competitor_id": competitor_id,
        "new_videos": len(videos),
    }
