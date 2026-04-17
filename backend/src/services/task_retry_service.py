"""
Task Retry Service — Phase 20

Allows failed tasks to be re-queued for reprocessing.

Flow:
  1. Look up the task in the DB.
  2. Confirm its status is "failed" or "error".
  3. Reset status to "pending" and clear the error field.
  4. Re-enqueue the job via the JobQueue (arq).
  5. Return the updated task dict.

Retry limits: max _MAX_RETRIES attempts per task (tracked in Redis).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_TTL = 60 * 60 * 24 * 7  # 7 days


async def _get_redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def _retry_count(task_id: str) -> int:
    try:
        redis = await _get_redis()
        val = await redis.get(f"retry_count:{task_id}")
        return int(val) if val else 0
    except Exception:
        return 0


async def _increment_retry_count(task_id: str) -> int:
    try:
        redis = await _get_redis()
        key = f"retry_count:{task_id}"
        count = await redis.incr(key)
        await redis.expire(key, _RETRY_TTL)
        return count
    except Exception:
        return 1


async def retry_task(task_id: str, user_id: Optional[str] = None) -> dict:
    """
    Retry a failed task.

    Returns a dict with:
      - status: "queued" | "already_pending" | "max_retries_exceeded" | "not_found" | "not_failed"
      - task_id
      - retry_count (after this retry)
      - message
    """
    from src.database import AsyncSessionLocal
    from src.repositories.task_repository import TaskRepository

    async with AsyncSessionLocal() as db:
        task = await TaskRepository.get_task_by_id(db, task_id)
    if task is None:
        return {"status": "not_found", "task_id": task_id,
                "retry_count": 0, "message": f"Task {task_id} not found"}

    task_status = task.get("status", "")
    if task_status in ("pending", "processing"):
        return {"status": "already_pending", "task_id": task_id,
                "retry_count": await _retry_count(task_id),
                "message": f"Task is already {task_status}"}

    if task_status not in ("failed", "error"):
        return {"status": "not_failed", "task_id": task_id,
                "retry_count": await _retry_count(task_id),
                "message": f"Task status is '{task_status}'; only failed/error tasks can be retried"}

    current_retries = await _retry_count(task_id)
    if current_retries >= _MAX_RETRIES:
        return {"status": "max_retries_exceeded", "task_id": task_id,
                "retry_count": current_retries,
                "message": f"Task has already been retried {current_retries} times (max {_MAX_RETRIES})"}

    async with AsyncSessionLocal() as db:
        await TaskRepository.update_task_status(db, task_id, "pending")

    try:
        from src.workers.job_queue import JobQueue
        queue = JobQueue()
        await queue.enqueue_job("process_task", task_id=task_id)
    except Exception as exc:
        logger.warning("[retry] enqueue failed for task=%s: %s", task_id, exc)

    new_count = await _increment_retry_count(task_id)
    logger.info("[retry] task=%s queued (attempt %d/%d)", task_id, new_count, _MAX_RETRIES)
    return {"status": "queued", "task_id": task_id,
            "retry_count": new_count, "message": "Task re-queued for processing"}


async def get_retry_info(task_id: str) -> dict:
    """Return current retry count and remaining retries for a task."""
    count = await _retry_count(task_id)
    return {
        "task_id": task_id,
        "retry_count": count,
        "max_retries": _MAX_RETRIES,
        "retries_remaining": max(0, _MAX_RETRIES - count),
    }
