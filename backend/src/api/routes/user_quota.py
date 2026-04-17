"""
User Quota API Routes — Phase 18

GET /users/{user_id}/quota  → all rate limit statuses + scheduled job count + cache stats
GET /users/{user_id}/dedup/check  → check if a content hash is a duplicate
DELETE /users/{user_id}/dedup/{file_hash}  → clear a dedup registration
"""

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/users", tags=["user-quota"])
logger = logging.getLogger(__name__)


@router.get("/{user_id}/quota")
async def get_user_quota(user_id: str):
    """
    Return all rate limit statuses and scheduled job count for a user.
    Useful for the frontend dashboard to show remaining quota.
    """
    from src.api.middleware.rate_limit import get_rate_limit_status
    from src.services.scheduled_publish_service import list_scheduled
    from src.services.cache_service import get_cache_stats

    rate_limits = await get_rate_limit_status(user_id)
    scheduled_jobs = await list_scheduled(user_id, limit=100, include_past=False)
    cache_stats = await get_cache_stats(prefixes=["trend", "niche"])

    return {
        "user_id": user_id,
        "rate_limits": rate_limits,
        "scheduled_jobs": {
            "count": len(scheduled_jobs),
            "max": 50,
            "jobs": scheduled_jobs[:5],
        },
        "cache": cache_stats,
    }


@router.get("/{user_id}/dedup/check")
async def check_duplicate(
    user_id: str,
    file_hash: str = Query(..., description="SHA-256 hex digest of the source file"),
):
    """Check whether a file hash has already been processed by this user."""
    from src.services.dedup_service import is_duplicate, get_original_task
    duplicate = await is_duplicate(user_id, file_hash)
    original_task = None
    if duplicate:
        original_task = await get_original_task(user_id, file_hash)
    return {
        "user_id": user_id,
        "file_hash": file_hash,
        "is_duplicate": duplicate,
        "original_task_id": original_task,
    }


@router.delete("/{user_id}/dedup/{file_hash}")
async def clear_dedup(user_id: str, file_hash: str):
    """
    Clear a dedup registration (e.g. after a task is deleted).
    Returns 404 if the hash was not registered.
    """
    from src.services.dedup_service import clear_hash
    cleared = await clear_hash(user_id, file_hash)
    if not cleared:
        raise HTTPException(status_code=404, detail="Hash not found in dedup registry")
    return {"message": "Cleared", "file_hash": file_hash}
