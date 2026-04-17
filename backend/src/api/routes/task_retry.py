"""
Task Retry API Routes — Phase 20

POST /tasks/{task_id}/retry     → re-queue a failed task
GET  /tasks/{task_id}/retry-info → retry count + remaining retries
"""

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/tasks", tags=["task-retry"])
logger = logging.getLogger(__name__)


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, user_id: str = Query(default="")):
    """Re-queue a failed task for reprocessing."""
    from src.services.task_retry_service import retry_task as svc_retry
    result = await svc_retry(task_id, user_id=user_id or None)
    status = result["status"]
    if status == "not_found":
        raise HTTPException(status_code=404, detail=result["message"])
    if status == "max_retries_exceeded":
        raise HTTPException(status_code=429, detail=result["message"])
    if status == "not_failed":
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.get("/{task_id}/retry-info")
async def retry_info(task_id: str):
    """Return retry count and remaining retries for a task."""
    from src.services.task_retry_service import get_retry_info
    return await get_retry_info(task_id)
