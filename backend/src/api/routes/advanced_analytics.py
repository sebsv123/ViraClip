"""
Advanced Analytics API — ViraClip

Endpoints for clip performance metrics, user engagement analytics,
system health reporting, and comprehensive report generation.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.advanced_analytics import (
    AdvancedAnalyticsService,
    get_analytics_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics/advanced", tags=["advanced-analytics"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class RecordClipMetricsRequest(BaseModel):
    clip_id: str
    task_id: str
    platform: str
    views: int = 0
    likes: int = 0
    shares: int = 0
    comments: int = 0
    watch_time_sec: float = 0.0
    completion_rate: float = 0.0
    ctr: float = 0.0
    virality_score: float = 0.0


class RecordUserActivityRequest(BaseModel):
    user_id: str
    activity_type: str   # video_processed | clips_generated | export | niche_selected
    metadata: Dict[str, Any] = {}


class RecordSystemMetricsRequest(BaseModel):
    task_completed: bool = False
    task_failed: bool = False
    niche: Optional[str] = None


class ComprehensiveReportRequest(BaseModel):
    start_date: Optional[str] = None   # YYYY-MM-DD
    end_date: Optional[str] = None


# ------------------------------------------------------------------
# Clip analytics
# ------------------------------------------------------------------

@router.post("/clips/record")
def record_clip_metrics(body: RecordClipMetricsRequest):
    """
    Record or update performance metrics for a clip.
    Call this when you receive engagement data from a publishing platform.
    """
    svc = get_analytics_service()
    svc.record_clip_performance(
        clip_id=body.clip_id,
        task_id=body.task_id,
        platform=body.platform,
        metrics={
            "views": body.views,
            "likes": body.likes,
            "shares": body.shares,
            "comments": body.comments,
            "watch_time_sec": body.watch_time_sec,
            "completion_rate": body.completion_rate,
            "ctr": body.ctr,
            "virality_score": body.virality_score,
        },
    )
    return {"status": "recorded", "clip_id": body.clip_id}


@router.get("/clips")
def get_clip_analytics(
    clip_id: Optional[str] = None,
    task_id: Optional[str] = None,
    days: int = 30,
):
    """
    Get aggregated clip performance analytics.

    - Filter by `clip_id` for a single clip, `task_id` for all clips from a task.
    - `days` controls the lookback window.

    Returns totals, averages, top-performing clips, and platform breakdown.
    """
    svc = get_analytics_service()
    data = svc.get_clip_analytics(clip_id=clip_id, task_id=task_id, days=days)
    return {"status": "success", "analytics": data}


# ------------------------------------------------------------------
# User analytics
# ------------------------------------------------------------------

@router.post("/users/record")
def record_user_activity(body: RecordUserActivityRequest):
    """Record a user activity event for engagement tracking."""
    svc = get_analytics_service()
    svc.record_user_activity(body.user_id, body.activity_type, body.metadata)
    return {"status": "recorded", "user_id": body.user_id, "activity_type": body.activity_type}


@router.get("/users")
def get_user_analytics(user_id: Optional[str] = None, days: int = 30):
    """
    Get user engagement analytics.

    Omit `user_id` for platform-wide aggregate (active users, tier distribution,
    power users, retention estimate). Provide `user_id` for individual stats.
    """
    svc = get_analytics_service()
    data = svc.get_user_analytics(user_id=user_id, days=days)
    return {"status": "success", "analytics": data}


# ------------------------------------------------------------------
# System health
# ------------------------------------------------------------------

@router.post("/system/record")
def record_system_metrics(body: RecordSystemMetricsRequest):
    """Record a system metric event (task completed/failed, active niche)."""
    svc = get_analytics_service()
    svc.record_system_metrics({
        "task_completed": body.task_completed,
        "task_failed": body.task_failed,
        "niche": body.niche,
    })
    return {"status": "recorded"}


@router.get("/system/health")
def get_system_health(days: int = 7):
    """
    System health report for the last N days.

    Returns task success/failure counts, daily breakdown, success trend,
    and an overall status label (`healthy | degraded | critical`).
    """
    svc = get_analytics_service()
    report = svc.get_system_health_report(days=days)
    return {"status": "success", "report": report}


# ------------------------------------------------------------------
# Comprehensive report
# ------------------------------------------------------------------

@router.post("/report")
def generate_report(body: ComprehensiveReportRequest):
    """
    Generate a full analytics report covering clip performance,
    user engagement, system health, growth metrics, and recommendations.

    Defaults to the last 30 days if no date range is provided.
    """
    svc = get_analytics_service()
    report = svc.generate_comprehensive_report(
        start_date=body.start_date,
        end_date=body.end_date,
    )
    return {"status": "success", "report": report}


@router.post("/report/export")
def export_report(body: ComprehensiveReportRequest):
    """Generate and export the comprehensive report to a JSON file on the server."""
    svc = get_analytics_service()
    report = svc.generate_comprehensive_report(
        start_date=body.start_date,
        end_date=body.end_date,
    )
    output_path = svc.export_report_to_file(report)
    return {
        "status": "exported",
        "path": str(output_path),
        "period": report.get("report_period"),
    }
