"""
Long-form video creation API routes.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
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


async def check_longform_rate_limit(user_id: str, redis) -> tuple[bool, int]:
    """
    Max LONGFORM_DAILY_LIMIT longform videos por usuario por día.
    Retorna (allowed: bool, remaining: int).
    """
    env = os.getenv("APP_ENV", "production")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"{env}:longform:ratelimit:{user_id}:{today}"

    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 86400)
        limit = int(os.getenv("LONGFORM_DAILY_LIMIT", "5"))
        allowed = current <= limit
        remaining = max(0, limit - current)
        if not allowed:
            await redis.decr(key)
        return allowed, remaining
    except Exception:
        logger.warning("[Longform] Redis unavailable, rate limit disabled")
        return True, 5


@router.post("/create", summary="Create a long-form YouTube video")
async def create_longform(body: LongformCreateRequest, request: Request):
    """Enqueue a long-form video creation job."""
    # Input validation (pre-flight, before enqueue)
    if len(body.topic.strip()) < 10:
        raise HTTPException(400, "Topic must be at least 10 characters")
    if len(body.topic) > 500:
        raise HTTPException(400, "Topic must be under 500 characters")
    if body.duration_seconds < 60:
        raise HTTPException(400, "Minimum duration is 60 seconds")
    max_dur = int(os.getenv("LONGFORM_MAX_DURATION_SECONDS", "1800"))
    if body.duration_seconds > max_dur:
        raise HTTPException(400, f"Maximum duration is {max_dur // 60} minutes")

    # Rate limiting
    user_id = request.headers.get("X-User-Id", "anonymous")
    try:
        import redis.asyncio as aioredis
        from ...config import get_config
        cfg = get_config()
        r = aioredis.Redis(host=cfg.redis_host, port=cfg.redis_port, password=cfg.redis_password or None, decode_responses=True)
        allowed, remaining = await check_longform_rate_limit(user_id, r)
        await r.aclose()
    except Exception:
        allowed, remaining = True, 5

    if not allowed:
        now = datetime.utcnow()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        retry_seconds = int((midnight - now).total_seconds())
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Daily limit reached",
                "message": "Maximum 5 longform videos per day. Resets at midnight UTC.",
                "retry_after_seconds": retry_seconds,
            },
        )

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "queued", "progress": "Waiting to start...", "result": None}

    try:
        from ...domains.longform.longform_coordinator import create_longform_video

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
