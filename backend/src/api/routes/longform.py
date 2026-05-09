"""
Long-form video creation API routes.
"""
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/longform", tags=["longform"])


class LongformCreateRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    duration_seconds: int = Field(default=600, ge=60, le=3600)


class LongformStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: str = ""
    result: dict = {}


# In-memory job store (replace with Redis in production)
_jobs: dict = {}


@router.post("/create", summary="Create a long-form YouTube video")
async def create_longform(body: LongformCreateRequest):
    """Enqueue a long-form video creation job."""
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "queued", "progress": "Waiting to start...", "result": None}

    # Enqueue as ARQ task
    try:
        from ...workers.tasks import process_video_task
        # For now, run inline (in production, enqueue to ARQ)
        from ...domains.longform.longform_coordinator import create_longform_video
        from pathlib import Path

        _jobs[job_id]["status"] = "processing"
        _jobs[job_id]["progress"] = "Generating script..."

        result = await create_longform_video(
            topic=body.topic,
            duration_seconds=body.duration_seconds,
            output_dir=Path("/app/exports/longform"),
        )

        _jobs[job_id]["status"] = result.status
        _jobs[job_id]["progress"] = "Completed" if result.status == "completed" else f"Failed: {result.error}"
        _jobs[job_id]["result"] = {
            "video_path": str(result.video_path) if result.video_path else None,
            "total_duration": result.total_duration,
            "sections_count": result.sections_count,
            "estimated_cost_usd": result.estimated_cost_usd,
            "metadata": {
                "title": result.metadata.title if result.metadata else None,
                "description": result.metadata.description if result.metadata else None,
                "tags": result.metadata.tags if result.metadata else [],
                "category": result.metadata.category if result.metadata else None,
                "chapters": result.metadata.chapters if result.metadata else [],
            } if result.metadata else None,
        }

    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["progress"] = f"Error: {e}"
        _jobs[job_id]["result"] = {"error": str(e)}

    return {"job_id": job_id, "status": _jobs[job_id]["status"]}


@router.get("/{job_id}/status", summary="Get long-form video creation status")
async def get_longform_status(job_id: str):
    """Get the status and result of a long-form video creation job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "result": job["result"],
    }
