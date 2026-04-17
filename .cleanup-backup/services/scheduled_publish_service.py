"""
Scheduled Publish Service — Phase 17

Queues clips for deferred social publishing using a Redis sorted set.
The score is the Unix timestamp at which the clip should be published.

Key schema:
  scheduled_publish:{user_id}   — sorted set of job JSON strings keyed by publish_at

Each job is a JSON blob:
{
  "job_id":        "<uuid>",
  "user_id":       "<str>",
  "clip_id":       "<str>",
  "task_id":       "<str>",
  "platform":      "tiktok"|"instagram"|"youtube",
  "title":         "<str>",
  "description":   "<str>",
  "hashtags":      ["#tag", ...],
  "publish_at":    <unix_float>,
  "created_at":    <unix_float>,
  "status":        "pending"|"published"|"failed",
  "error":         "<str|None>"
}
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "scheduled_publish"
_MAX_JOBS_PER_USER = 50


def _user_key(user_id: str) -> str:
    return f"{_REDIS_KEY_PREFIX}:{user_id}"


async def _get_redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


# ── Schedule ──────────────────────────────────────────────────────────────────

async def schedule_publish(
    *,
    user_id: str,
    clip_id: str,
    task_id: str,
    platform: str,
    publish_at: float,
    title: str = "",
    description: str = "",
    hashtags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Add a clip to the publish schedule.

    Args:
        user_id:    Owner
        clip_id:    ID of the GeneratedClip
        task_id:    Parent task
        platform:   'tiktok' | 'instagram' | 'youtube'
        publish_at: Unix timestamp (future)
        title, description, hashtags: Optional social copy override

    Returns:
        The created job dict.

    Raises:
        ValueError: If publish_at is in the past or quota exceeded.
    """
    if publish_at <= time.time():
        raise ValueError("publish_at must be a future Unix timestamp")

    redis = await _get_redis()
    key = _user_key(user_id)

    existing = await redis.zcard(key)
    if existing >= _MAX_JOBS_PER_USER:
        raise ValueError(f"Schedule full: maximum {_MAX_JOBS_PER_USER} pending jobs per user")

    job: Dict[str, Any] = {
        "job_id": str(uuid.uuid4()),
        "user_id": user_id,
        "clip_id": clip_id,
        "task_id": task_id,
        "platform": platform,
        "title": title,
        "description": description,
        "hashtags": hashtags or [],
        "publish_at": publish_at,
        "created_at": time.time(),
        "status": "pending",
        "error": None,
    }
    await redis.zadd(key, {json.dumps(job): publish_at})
    logger.info("[schedule_publish] Scheduled job %s for user=%s clip=%s at=%s",
                job["job_id"], user_id, clip_id, publish_at)
    return job


# ── List ──────────────────────────────────────────────────────────────────────

async def list_scheduled(
    user_id: str,
    limit: int = 20,
    include_past: bool = False,
) -> List[Dict[str, Any]]:
    """
    Return up to `limit` scheduled jobs for a user, sorted by publish_at ascending.
    When include_past=False (default), only future jobs are returned.
    """
    redis = await _get_redis()
    key = _user_key(user_id)
    min_score = "-inf" if include_past else str(time.time())

    raw_jobs = await redis.zrangebyscore(key, min_score, "+inf", start=0, num=limit)
    jobs = []
    for raw in raw_jobs:
        try:
            jobs.append(json.loads(raw))
        except Exception:
            pass
    return jobs


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel_scheduled(user_id: str, job_id: str) -> bool:
    """
    Remove a pending job by job_id.
    Returns True if the job was found and removed.
    """
    redis = await _get_redis()
    key = _user_key(user_id)

    all_raw = await redis.zrange(key, 0, -1)
    for raw in all_raw:
        try:
            job = json.loads(raw)
        except Exception:
            continue
        if job.get("job_id") == job_id:
            removed = await redis.zrem(key, raw)
            if removed:
                logger.info("[schedule_publish] Cancelled job %s for user=%s", job_id, user_id)
                return True
    return False


# ── Execute due jobs ──────────────────────────────────────────────────────────

async def execute_due_jobs(user_id: str) -> List[Dict[str, Any]]:
    """
    Find all jobs whose publish_at ≤ now, attempt to publish them, and return results.
    Jobs that fail are marked with status='failed' and re-stored; successful ones are removed.
    """
    redis = await _get_redis()
    key = _user_key(user_id)
    now = time.time()

    due_raw = await redis.zrangebyscore(key, "-inf", str(now))
    results = []
    for raw in due_raw:
        try:
            job = json.loads(raw)
        except Exception:
            await redis.zrem(key, raw)
            continue

        await redis.zrem(key, raw)
        try:
            await _publish_job(job)
            job["status"] = "published"
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            logger.warning("[schedule_publish] Job %s failed: %s", job.get("job_id"), exc)

        results.append(job)

    return results


async def _publish_job(job: Dict[str, Any]) -> None:
    """Call the social publisher for a single scheduled job."""
    from src.services.social_publisher import publish_clip
    await publish_clip(
        clip_id=job["clip_id"],
        platform=job["platform"],
        title=job.get("title", ""),
        description=job.get("description", ""),
        hashtags=job.get("hashtags", []),
    )


# ── Execute single ────────────────────────────────────────────────────────────

async def execute_now(user_id: str, job_id: str) -> Optional[Dict[str, Any]]:
    """
    Immediately publish a specific scheduled job regardless of its publish_at time.
    Removes the job from the queue and returns the result dict.
    """
    redis = await _get_redis()
    key = _user_key(user_id)

    all_raw = await redis.zrange(key, 0, -1)
    for raw in all_raw:
        try:
            job = json.loads(raw)
        except Exception:
            continue
        if job.get("job_id") != job_id:
            continue

        await redis.zrem(key, raw)
        try:
            await _publish_job(job)
            job["status"] = "published"
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            logger.warning("[schedule_publish] Immediate publish failed for job %s: %s",
                           job_id, exc)
        return job

    return None
