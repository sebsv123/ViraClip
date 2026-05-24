"""
POST /api/v1/tasks/{task_id}/retry

Resets a failed/dead/queued task and re-enqueues it via ARQ from inside
the backend process.  This avoids the 30-s timeout that happens when
enqueuing from outside the Docker network.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from ...database import AsyncSessionLocal
from ...config import get_config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/v1/tasks/{task_id}/retry", tags=["tasks"])
async def retry_task(task_id: str) -> dict:
    """
    Reset *task_id* to 'queued' and enqueue the job in ARQ.

    Works for tasks in any terminal state (failed, dead, completed, queued).
    Cleans up stale Redis keys (circuit-breaker, dead-letter, cancel flag)
    before enqueuing so the worker starts with a clean slate.
    """
    cfg = get_config()

    # ── 1. Fetch task from DB ──────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text(
                """
                SELECT id, url, source_type, user_id, status,
                       font_family, font_size, font_color,
                       caption_template, processing_mode, output_format,
                       add_subtitles, target_language, num_clips
                FROM tasks WHERE id = :task_id
                """
            ),
            {"task_id": task_id},
        )
        task = row.fetchone()

    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # ── 2. Reset status to 'queued' ────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                UPDATE tasks
                SET status          = 'queued',
                    error_code      = NULL,
                    error_message   = NULL,
                    progress        = 0,
                    progress_message = 'Retry enqueued',
                    updated_at      = NOW()
                WHERE id = :task_id
                """
            ),
            {"task_id": task_id},
        )
        await db.commit()

    logger.info("[retry] Task %s reset to 'queued'", task_id)

    # ── 3. Clean stale Redis keys ──────────────────────────────────────────
    try:
        import redis.asyncio as aioredis

        r = aioredis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            password=cfg.redis_password,
            decode_responses=True,
        )
        keys_to_delete = [
            f"circuit_breaker:task_id:{task_id}",
            f"dead_letter:{task_id}",
            f"task_cancel:{task_id}",
            f"arq:job:{task_id}",
        ]
        deleted = await r.delete(*keys_to_delete)

        # Also remove from dead-letter set
        await r.srem("tasks:dead_letter", task_id)

        # Remove any stale ARQ zset entry that encodes this task_id in args
        queue_name = "arq:queue:viraclip_cpu_tasks"
        members = await r.zrange(queue_name, 0, -1)
        import json
        for member in members:
            job_key = f"arq:job:{member}"
            raw = await r.get(job_key)
            if raw:
                try:
                    data = json.loads(raw)
                    if task_id in [str(a) for a in data.get("args", [])]:
                        await r.delete(job_key)
                        await r.zrem(queue_name, member)
                        logger.info("[retry] Removed stale ARQ job %s", member[:12])
                except (json.JSONDecodeError, TypeError):
                    pass

        await r.aclose()
        logger.info("[retry] Cleaned %d Redis key(s) for task %s", deleted, task_id)
    except Exception as redis_err:
        # Non-fatal — log and continue
        logger.warning("[retry] Redis cleanup warning for %s: %s", task_id, redis_err)

    # ── 4. Enqueue via ARQ ────────────────────────────────────────────────
    try:
        import arq
        from arq.connections import RedisSettings

        pool = await arq.create_pool(
            RedisSettings(
                host=cfg.redis_host,
                port=cfg.redis_port,
                password=cfg.redis_password,
                database=0,
            )
        )
        job = await pool.enqueue_job(
            "process_video_task",
            task_id,
            task.url,
            task.source_type,
            task.user_id,
            # Optional overrides from stored task settings
            font_family=task.font_family or "TikTokSans-Regular",
            font_size=task.font_size or 24,
            font_color=task.font_color or "#FFFFFF",
            caption_template=task.caption_template or "default",
            processing_mode=task.processing_mode or "fast",
            output_format=task.output_format or "vertical",
            add_subtitles=bool(task.add_subtitles),
            target_language=task.target_language or "eng",
            num_clips=task.num_clips or 6,
            _queue_name="viraclip_cpu_tasks",
        )
        await pool.aclose()

        job_id = job.job_id if job else None
        logger.info("[retry] Enqueued ARQ job %s for task %s", job_id, task_id)
    except Exception as enqueue_err:
        # Revert status to failed so operator knows it didn't enqueue
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error_code = 'RETRY_ENQUEUE_FAILED',
                        error_message = :msg,
                        updated_at = NOW()
                    WHERE id = :task_id
                    """
                ),
                {"task_id": task_id, "msg": str(enqueue_err)},
            )
            await db.commit()
        logger.error("[retry] Enqueue failed for task %s: %s", task_id, enqueue_err)
        raise HTTPException(
            status_code=500,
            detail=f"Task reset to 'queued' but ARQ enqueue failed: {enqueue_err}",
        )

    return {
        "status": "ok",
        "task_id": task_id,
        "arq_job_id": job_id,
        "message": "Task reset to 'queued' and enqueued in ARQ worker.",
    }
