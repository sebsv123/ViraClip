"""
Scheduled Publish API Routes — Phase 17

POST /scheduled-publish/schedule    → queue a clip for future publishing
GET  /scheduled-publish/list        → list pending scheduled jobs
DELETE /scheduled-publish/{job_id}  → cancel a pending job
POST /scheduled-publish/{job_id}/publish-now → publish immediately
POST /scheduled-publish/execute-due → run all jobs whose time has arrived
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/scheduled-publish", tags=["scheduled-publish"])
logger = logging.getLogger(__name__)


class ScheduleRequest(BaseModel):
    user_id: str
    clip_id: str
    task_id: str
    platform: str = Field(..., pattern="^(tiktok|instagram|youtube)$")
    publish_at: float = Field(..., description="Unix timestamp (must be in the future)")
    title: str = ""
    description: str = ""
    hashtags: List[str] = []


@router.post("/schedule")
async def schedule_clip(body: ScheduleRequest):
    """Queue a clip for deferred publishing at a specific Unix timestamp."""
    from src.services.scheduled_publish_service import schedule_publish
    try:
        job = await schedule_publish(
            user_id=body.user_id,
            clip_id=body.clip_id,
            task_id=body.task_id,
            platform=body.platform,
            publish_at=body.publish_at,
            title=body.title,
            description=body.description,
            hashtags=body.hashtags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job": job, "message": "Scheduled successfully"}


@router.get("/list")
async def list_jobs(
    user_id: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    include_past: bool = Query(False),
):
    """List pending (and optionally past) scheduled publish jobs for a user."""
    from src.services.scheduled_publish_service import list_scheduled
    jobs = await list_scheduled(user_id, limit=limit, include_past=include_past)
    return {"jobs": jobs, "count": len(jobs)}


@router.delete("/{job_id}")
async def cancel_job(job_id: str, user_id: str = Query(...)):
    """Cancel a scheduled job by job_id."""
    from src.services.scheduled_publish_service import cancel_scheduled
    removed = await cancel_scheduled(user_id, job_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "Cancelled", "job_id": job_id}


@router.post("/{job_id}/publish-now")
async def publish_now(job_id: str, user_id: str = Query(...)):
    """Immediately publish a specific scheduled job regardless of its scheduled time."""
    from src.services.scheduled_publish_service import execute_now
    result = await execute_now(user_id, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if result.get("status") == "failed":
        raise HTTPException(status_code=502, detail=result.get("error", "Publish failed"))
    return {"message": "Published", "job": result}


@router.post("/execute-due")
async def execute_due(user_id: str = Query(...)):
    """
    Execute all jobs whose publish_at ≤ now.
    Intended to be called by a cron/worker process.
    """
    from src.services.scheduled_publish_service import execute_due_jobs
    results = await execute_due_jobs(user_id)
    published = [r for r in results if r.get("status") == "published"]
    failed = [r for r in results if r.get("status") == "failed"]
    return {
        "executed": len(results),
        "published": len(published),
        "failed": len(failed),
        "results": results,
    }
