"""
Batch Processing API — ViraClip

Endpoints for creating, starting, monitoring, and cancelling
batch video processing jobs (multiple URLs → clips in one operation).
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.batch_processor import (
    BatchStatus,
    get_batch_processor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batch", tags=["batch"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateBatchRequest(BaseModel):
    video_urls: List[str]
    name: Optional[str] = None
    settings: Dict[str, Any] = {}   # target_platform, processing_mode, etc.
    auto_start: bool = True


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_status(value: Optional[str]) -> Optional[BatchStatus]:
    if value is None:
        return None
    try:
        return BatchStatus(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{value}'. Choose: {[s.value for s in BatchStatus]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("")
async def create_batch(request: Request, body: CreateBatchRequest):
    """
    Create a new batch job from a list of video URLs and optionally start it immediately.

    `settings` keys (all optional):
    - `target_platform`: tiktok | reels | youtube_shorts (default tiktok)
    - `processing_mode`: fast | quality
    - `max_clips_per_video`: int
    """
    if not body.video_urls:
        raise HTTPException(status_code=400, detail="video_urls must not be empty")

    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    proc = get_batch_processor()
    try:
        job = await proc.create_batch_job(
            user_id=user_id,
            video_urls=body.video_urls,
            settings=body.settings,
            name=body.name,
        )

        started = False
        if body.auto_start:
            started = await proc.start_batch_processing(job.batch_id)

        status_data = proc.get_batch_status(job.batch_id)
        return {
            "status": "created",
            "auto_started": started,
            "batch": status_data,
        }
    except Exception as e:
        logger.error(f"[Batch] create failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def list_batches(request: Request, status: Optional[str] = None, limit: int = 50):
    """List batch jobs for the current user, optionally filtered by status."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    proc = get_batch_processor()
    batches = proc.list_user_batches(
        user_id=user_id,
        status=_parse_status(status),
        limit=limit,
    )
    return {"status": "success", "count": len(batches), "batches": batches}


@router.get("/{batch_id}")
def get_batch_status(batch_id: str):
    """Get the current status, progress, and per-video results of a batch job."""
    proc = get_batch_processor()
    data = proc.get_batch_status(batch_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found")
    return {"status": "success", "batch": data}


@router.get("/{batch_id}/results")
def get_batch_results(batch_id: str):
    """Get detailed results including clip lists for each video in the batch."""
    proc = get_batch_processor()
    data = proc.get_batch_results(batch_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found")
    return {"status": "success", "results": data}


@router.post("/{batch_id}/start")
async def start_batch(batch_id: str):
    """Manually start a batch job that is in `pending` state."""
    proc = get_batch_processor()
    success = await proc.start_batch_processing(batch_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start batch '{batch_id}': not found or not in pending state",
        )
    return {"status": "started", "batch_id": batch_id}


@router.post("/{batch_id}/cancel")
async def cancel_batch(batch_id: str):
    """Cancel a running batch job. Pending videos will be skipped."""
    proc = get_batch_processor()
    success = await proc.cancel_batch(batch_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel batch '{batch_id}': not found or not in processing state",
        )
    return {"status": "cancelled", "batch_id": batch_id}


@router.get("/statuses/list")
def list_statuses():
    """List all valid batch job statuses."""
    return {"statuses": [s.value for s in BatchStatus]}
