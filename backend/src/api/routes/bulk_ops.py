"""
Bulk Operations API — ViraClip

Create and manage bulk video processing jobs: submit multiple source
URLs, start/cancel jobs, track progress, and validate sources.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...services.bulk_operations import BulkOperationsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bulk", tags=["bulk"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SourceItem(BaseModel):
    url: str
    title: Optional[str] = None
    platform: Optional[str] = None     # "youtube", "tiktok", etc.


class CreateJobRequest(BaseModel):
    user_id: str
    sources: List[SourceItem]
    clip_settings: Optional[Dict[str, Any]] = None


class ValidateRequest(BaseModel):
    sources: List[Dict[str, str]]


# ------------------------------------------------------------------
# Singleton helper
# ------------------------------------------------------------------

def _get_service() -> BulkOperationsService:
    return BulkOperationsService()


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/validate")
async def validate_sources(body: ValidateRequest):
    """
    Pre-validate a list of source URLs before creating a bulk job.

    Returns valid/invalid counts and per-source error details.
    """
    if not body.sources:
        raise HTTPException(status_code=400, detail="sources must not be empty")
    svc = _get_service()
    result = await svc.validate_sources(body.sources)
    return {"status": "validated", "result": result}


@router.post("/jobs")
async def create_job(body: CreateJobRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a new bulk processing job for multiple video sources.

    Returns the job ID and initial status.
    """
    if not body.sources:
        raise HTTPException(status_code=400, detail="sources must not be empty")
    svc = _get_service()
    sources = [{"url": s.url, "title": s.title, "platform": s.platform} for s in body.sources]
    try:
        job = await svc.create_bulk_job(db, body.user_id, sources, body.clip_settings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "created",
        "job": {
            "job_id": job.job_id,
            "user_id": job.user_id,
            "status": job.status.value,
            "total_sources": len(job.sources),
        },
    }


@router.post("/jobs/{job_id}/start")
async def start_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Start processing a bulk job."""
    svc = _get_service()
    success = await svc.start_bulk_job(db, job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or already started")
    return {"status": "started", "job_id": job_id}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel an in-progress bulk job."""
    svc = _get_service()
    success = await svc.cancel_job(db, job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or cannot be cancelled")
    return {"status": "cancelled", "job_id": job_id}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get status and progress of a bulk job."""
    svc = _get_service()
    status = await svc.get_job_status(db, job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "success", "job": status}


@router.get("/jobs/user/{user_id}")
async def list_user_jobs(user_id: str, db: AsyncSession = Depends(get_db)):
    """List all bulk jobs for a user."""
    svc = _get_service()
    jobs = await svc.list_user_jobs(db, user_id)
    return {"count": len(jobs), "jobs": jobs}
