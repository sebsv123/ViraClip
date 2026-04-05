"""
Auto-Scheduler API — ViraClip

Endpoints for scheduling recurring video processing jobs and
setting up keyword trend-triggers that auto-process matching content.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.auto_scheduler import (
    AutoSchedulerService,
    ScheduleFrequency,
    TriggerType,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scheduler", tags=["scheduler"])

# Module-level singleton so state is shared across requests
_scheduler: Optional[AutoSchedulerService] = None


def get_scheduler() -> AutoSchedulerService:
    global _scheduler
    if _scheduler is None:
        _scheduler = AutoSchedulerService()
    return _scheduler


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateScheduleRequest(BaseModel):
    name: str
    source_type: str                         # youtube_channel, rss_feed, podcast
    source_url: str
    frequency: str = "daily"                 # hourly | daily | weekly | monthly | custom
    cron_expression: Optional[str] = None    # only for frequency=custom
    processing_config: Dict[str, Any] = {}
    publish_config: Dict[str, Any] = {}


class CreateTrendTriggerRequest(BaseModel):
    keywords: List[str]
    min_virality_score: float = 70.0
    processing_config: Dict[str, Any] = {}
    publish_config: Dict[str, Any] = {}


# ------------------------------------------------------------------
# Recurring schedule endpoints
# ------------------------------------------------------------------

@router.post("/schedules")
async def create_schedule(request: Request, body: CreateScheduleRequest):
    """
    Create a recurring job that automatically processes a content source
    (YouTube channel, RSS feed, podcast URL) at the given frequency.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    try:
        freq = ScheduleFrequency(body.frequency)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid frequency '{body.frequency}'. "
                   f"Choose: {[f.value for f in ScheduleFrequency]}",
        )

    svc = get_scheduler()
    try:
        job = await svc.schedule_recurring_source(
            user_id=user_id,
            name=body.name,
            source_type=body.source_type,
            source_url=body.source_url,
            frequency=freq,
            processing_config=body.processing_config,
            publish_config=body.publish_config,
            cron_expression=body.cron_expression,
        )
        return {
            "status": "scheduled",
            "job_id": job.job_id,
            "name": job.name,
            "frequency": freq.value,
            "next_run": job.next_run.isoformat() if job.next_run else None,
            "source_url": body.source_url,
        }
    except Exception as e:
        logger.error(f"[Scheduler] create_schedule failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedules")
async def list_schedules(request: Request):
    """List all recurring schedule jobs for the current user."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_scheduler()
    try:
        jobs = await svc.get_user_schedules(user_id)
        return {
            "status": "success",
            "count": len(jobs),
            "schedules": [
                {
                    "job_id": j.job_id,
                    "name": j.name,
                    "frequency": j.frequency.value if j.frequency else None,
                    "source_url": j.source_config.get("url"),
                    "source_type": j.source_config.get("type"),
                    "is_active": j.is_active,
                    "run_count": j.run_count,
                    "total_clips_generated": j.total_clips_generated,
                    "last_run": j.last_run.isoformat() if j.last_run else None,
                    "next_run": j.next_run.isoformat() if j.next_run else None,
                    "created_at": j.created_at.isoformat(),
                }
                for j in jobs
            ],
        }
    except Exception as e:
        logger.error(f"[Scheduler] list_schedules failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/schedules/{job_id}")
async def deactivate_schedule(request: Request, job_id: str):
    """Deactivate (pause) a recurring schedule without deleting it."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_scheduler()
    try:
        success = await svc.deactivate_job(user_id=user_id, job_id=job_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Schedule '{job_id}' not found")
        return {"status": "deactivated", "job_id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Trend trigger endpoints
# ------------------------------------------------------------------

@router.post("/triggers")
async def create_trend_trigger(request: Request, body: CreateTrendTriggerRequest):
    """
    Create a trigger that fires automatically when any of the given keywords
    appear in trending content above the virality threshold.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    if not body.keywords:
        raise HTTPException(status_code=400, detail="At least one keyword is required")

    svc = get_scheduler()
    try:
        trigger = await svc.create_trend_trigger(
            user_id=user_id,
            keywords=body.keywords,
            min_virality_score=body.min_virality_score,
            processing_config=body.processing_config,
            publish_config=body.publish_config,
        )
        return {
            "status": "created",
            "trigger_id": trigger.trigger_id,
            "keywords": trigger.keywords,
            "min_virality_score": trigger.min_virality_score,
            "is_active": trigger.is_active,
        }
    except Exception as e:
        logger.error(f"[Scheduler] create_trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Manual run endpoint
# ------------------------------------------------------------------

@router.post("/schedules/{job_id}/run-now")
async def run_schedule_now(request: Request, job_id: str):
    """
    Manually trigger an immediate run of a scheduled job,
    regardless of its next_run time.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_scheduler()
    try:
        await svc.process_scheduled_job(job_id=job_id, user_id=user_id)
        return {"status": "triggered", "job_id": job_id}
    except Exception as e:
        logger.error(f"[Scheduler] run-now failed for {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Frequencies helper
# ------------------------------------------------------------------

@router.get("/frequencies")
def list_frequencies():
    """List all valid schedule frequencies."""
    return {
        "frequencies": [f.value for f in ScheduleFrequency],
        "note": "Use 'custom' with a cron_expression for full control",
    }
