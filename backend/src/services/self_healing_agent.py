"""
Self-Healing Agent — orchestrator that uses ErrorDiagnostician + CodePatcher.

Runs every 30s as arq cron job. Finds failed tasks, diagnoses errors,
applies code fixes, re-enqueues, and tracks attempts.

Architecture:
  run_healing_cycle()
    → get_healable_tasks()  # failed + queued-timeout
    → heal_task(task)
      → ErrorDiagnostician.diagnose(error, traceback)
      → CodePatcher.apply_fix(diagnosis)  # if fix_code exists
      → JobQueue.enqueue_processing_job()
      → update_task_metadata()
"""
import asyncio
import json
import logging
import os
import sys
import traceback as tb_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SELF-HEALING] %(message)s",
)
logger = logging.getLogger("self_healing")

REPO_ROOT = Path(os.getenv("REPO_ROOT", "/app"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://viraclip:viraclip_password@postgres:5432/viraclip")
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

MAX_ATTEMPTS = 3


async def _get_db():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


async def _get_redis():
    import redis.asyncio as aioredis
    return await aioredis.from_url(
        f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}",
        decode_responses=True,
    )


async def get_healable_tasks() -> list[dict]:
    """Get tasks that need healing: failed + queued > 600s."""
    conn = await _get_db()
    try:
        rows = await conn.fetch(
            "SELECT id, status, error_message, retry_count, progress_message, metadata, source_url, source_type, user_id "
            "FROM tasks WHERE status = 'failed'",
        )
        tasks = []
        for row in rows:
            task = dict(row)
            meta = task.get("metadata")
            if isinstance(meta, str):
                task["metadata"] = json.loads(meta)
            elif meta is None:
                task["metadata"] = {}
            tasks.append(task)

        # Queued > 600s
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=600)
        qrows = await conn.fetch(
            "SELECT id, status, source_url, source_type, user_id FROM tasks WHERE status = 'queued' AND created_at < $1",
            cutoff,
        )
        for row in qrows:
            tasks.append(dict(row) | {"metadata": {}, "error_message": "QUEUED_TIMEOUT", "retry_count": 0})

        return tasks
    finally:
        await conn.close()


async def get_task_source(task_id: str) -> dict:
    """Get task source URL and type from Redis cache or DB."""
    try:
        r = await _get_redis()
        raw = await r.get(f"task_source:{task_id}")
        await r.aclose()
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"url": "", "source_type": ""}


async def update_task_metadata(task_id: str, metadata: dict) -> None:
    """Update task metadata in DB."""
    conn = await _get_db()
    try:
        # Get existing metadata
        row = await conn.fetchrow("SELECT metadata FROM tasks WHERE id = $1", task_id)
        existing = {}
        if row and row["metadata"]:
            if isinstance(row["metadata"], str):
                existing = json.loads(row["metadata"])
            elif isinstance(row["metadata"], dict):
                existing = row["metadata"]
        existing.update(metadata)
        await conn.execute(
            "UPDATE tasks SET metadata = $1::jsonb, updated_at = NOW() WHERE id = $2",
            json.dumps(existing),
            task_id,
        )
    finally:
        await conn.close()


async def mark_permanently_failed(task_id: str, error_message: str) -> None:
    """Mark task as permanently failed after exhausting healing attempts."""
    conn = await _get_db()
    try:
        await conn.execute(
            "UPDATE tasks SET status='failed', error_code='SELF_HEALING_EXHAUSTED', error_message=$1, updated_at=NOW() WHERE id=$2",
            error_message[:500],
            task_id,
        )
        logger.warning("⚠️ Task %s permanently failed (SELF_HEALING_EXHAUSTED)", task_id[:12])
    finally:
        await conn.close()


async def heal_task(task: dict) -> str:
    """Heal a single failed task using ErrorDiagnostician + CodePatcher."""
    from .error_diagnostician import ErrorDiagnostician
    from .code_patcher import CodePatcher

    task_id = task["id"]
    error = task.get("error_message") or task.get("progress_message") or ""
    tb = (task.get("metadata") or {}).get("traceback", "")
    attempts = (task.get("metadata") or {}).get("self_healing_attempts", 0)

    if attempts >= MAX_ATTEMPTS:
        await mark_permanently_failed(task_id, error)
        return "EXHAUSTED"

    # Diagnose
    diagnosis = await ErrorDiagnostician.diagnose(error, tb)
    logger.info("[SELF-HEALING] task %s → %s (attempt %d/%d)", task_id[:12], diagnosis.error_type, attempts + 1, MAX_ATTEMPTS)

    # Apply code fix if available and not already known
    fix_applied = False
    if diagnosis.fix_code and not diagnosis.is_known:
        fix_applied = await CodePatcher.apply_fix(diagnosis)
        if fix_applied:
            logger.info("[SELF-HEALING] Patch applied: %s", diagnosis.fix_description)
        await ErrorDiagnostician.save_to_knowledge_base(diagnosis, fix_applied)

    # Re-enqueue
    source = await get_task_source(task_id)
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.workers.job_queue import JobQueue
        await JobQueue.enqueue_processing_job(
            "process_video_task", "fast",
            task_id,
            source.get("url") or task.get("source_url", ""),
            source.get("source_type") or task.get("source_type", ""),
            task.get("user_id", ""),
        )
        logger.info("[SELF-HEALING] task %s re-enqueued", task_id[:12])
    except Exception as exc:
        logger.error("Re-enqueue failed for %s: %s", task_id[:12], exc)

    # Update metadata
    await update_task_metadata(task_id, {
        "self_healing_attempts": attempts + 1,
        "last_healing_action": diagnosis.error_type,
        "last_healing_timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return diagnosis.error_type


async def run_healing_cycle(ctx: dict = None) -> None:
    """Main cycle — find healable tasks and heal them."""
    logger.info("Starting healing cycle...")
    tasks = await get_healable_tasks()
    logger.info("Found %d healable tasks", len(tasks))

    for task in tasks:
        try:
            await heal_task(task)
        except Exception as exc:
            logger.error("Failed to heal task %s: %s", task.get("id", "?")[:12], exc)


# ── Cron entry point ────────────────────────────────────────────────────────
async def self_healing_cron(ctx: dict) -> None:
    """Called by arq cron every 30s."""
    await run_healing_cycle()


# ── CLI ─────────────────────────────────────────────────────────────────────
async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one healing cycle")
    parser.add_argument("--watch", action="store_true", help="Run every 30s")
    args = parser.parse_args()

    if args.once:
        await run_healing_cycle()
        return
    if args.watch:
        logger.info("Watching every 30s")
        while True:
            await run_healing_cycle()
            await asyncio.sleep(30)
        return
    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
