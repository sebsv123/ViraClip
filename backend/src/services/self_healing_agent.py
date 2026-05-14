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

Fixes applied (self-healing audit):
  Fix 2: get_healable_tasks() excludes status IN ('failed','permanently_failed','cancelled')
         and only picks tasks with error_code IS NOT NULL AND error_code != 'SELF_HEALING_EXHAUSTED'
  Fix 3: heal_task() does atomic Postgres→Redis (Postgres first, rollback if Redis fails)
  Fix 4: mark_permanently_failed() uses SCAN to find ALL arq:* keys for task_id
  Fix 5: Circuit breaker by task_id (tracks skips in Redis, auto-fail after 3)
"""
import asyncio
import json
import logging
import os
import sys
import traceback as tb_module
import uuid
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
CIRCUIT_BREAKER_MAX_SKIPS = 3
CIRCUIT_BREAKER_TTL = 3600  # 1 hour


async def _get_db():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


async def _get_redis():
    import redis.asyncio as aioredis
    return await aioredis.from_url(
        f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}",
        decode_responses=True,
    )


async def _remove_arq_jobs_for_task(r, task_id: str) -> int:
    """Scan the ARQ queue sorted set and remove any jobs referencing this task_id.

    ARQ stores jobs with UUID keys (arq:job:{uuid}), NOT arq:job:{task_id}.
    The sorted set members are UUIDs, not task_ids. This function:
    1. Gets all members from the queue sorted set
    2. For each member (UUID), reads arq:job:{uuid} data
    3. If the job data contains our task_id, deletes the job key and removes from queue

    Returns the number of jobs removed.
    """
    removed = 0
    queue_name = "arq:queue:viraclip_cpu_tasks"
    members = await r.zrange(queue_name, 0, -1)
    for member in members:
        job_key = f"arq:job:{member}"
        raw = await r.get(job_key)
        if raw:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            # Check if this job references our task_id
            # ARQ stores args as a list; task_id is the first positional arg
            args = data.get("args", [])
            if task_id in args or str(task_id) in [str(a) for a in args]:
                await r.delete(job_key)
                await r.zrem(queue_name, member)
                removed += 1
                logger.info(
                    "🗑️ Removed stale ARQ job %s for task %s from queue",
                    member[:12], task_id[:12],
                )
    return removed


async def _clean_redis_keys_for_task(task_id: str) -> int:
    """Find and delete ALL Redis keys related to a task_id using SCAN.

    Fix 4 (v2): Also scans the ARQ queue sorted set for UUID-based job keys
    that reference this task_id — the old code only deleted arq:job:{task_id}
    but ARQ uses arq:job:{uuid}.

    Returns the number of keys deleted.
    """
    r = await _get_redis()
    try:
        deleted = 0
        cursor = 0
        patterns = [
            f"arq:job:{task_id}",
            f"arq:job:*{task_id}*",
            f"arq:result:*{task_id}*",
            f"arq:queue:*",
            f"dead_letter:{task_id}",
            f"task_source:{task_id}",
            f"task_cancel:{task_id}",
            f"circuit_breaker:task_id:{task_id}",
            f"progress:{task_id}",
            f"clip_preview:{task_id}:*",
            f"clip_finalize:{task_id}:*",
        ]
        # Also scan for arq:result:{uuid} keys — ARQ stores results with UUID keys
        # that may not contain the task_id in the key name. We scan all arq:result:*
        # and check their content.
        cursor = 0
        while True:
            cursor, result_keys = await r.scan(cursor, match="arq:result:*", count=200)
            for rk in result_keys:
                raw = await r.get(rk)
                if raw:
                    try:
                        data = json.loads(raw)
                        # ARQ result keys contain the job_id; check if any field references our task_id
                        if task_id in str(data) or task_id[:12] in str(data):
                            deleted += await r.delete(rk)
                    except (json.JSONDecodeError, TypeError):
                        continue
            if cursor == 0:
                break
        # Delete exact-match keys
        for key in patterns:
            if "*" not in key:
                deleted += await r.delete(key)

        # SCAN for wildcard patterns
        for pattern in patterns:
            if "*" in pattern:
                cursor = 0
                while True:
                    cursor, keys = await r.scan(cursor, match=pattern, count=100)
                    if keys:
                        deleted += await r.delete(*keys)
                    if cursor == 0:
                        break

        # Also remove from arq queue sorted sets (old approach — member = task_id)
        queue_keys = await r.keys("arq:queue:*")
        for qk in queue_keys:
            removed = await r.zrem(qk, task_id)
            if removed:
                deleted += 1

        # NEW: Scan ARQ queue for UUID-based job keys referencing this task_id
        deleted += await _remove_arq_jobs_for_task(r, task_id)

        # Remove from dead letter set
        await r.srem("tasks:dead_letter", task_id)

        return deleted
    finally:
        await r.aclose()


async def _circuit_breaker_skip(task_id: str) -> bool:
    """Check circuit breaker. Returns True if task should be skipped (too many skips).

    Increments skip counter in Redis. If counter > CIRCUIT_BREAKER_MAX_SKIPS,
    auto-fails the task and cleans up.
    """
    r = await _get_redis()
    try:
        key = f"circuit_breaker:task_id:{task_id}"
        skips = await r.incr(key)
        if skips == 1:
            await r.expire(key, CIRCUIT_BREAKER_TTL)

        if skips > CIRCUIT_BREAKER_MAX_SKIPS:
            logger.warning(
                "⚠️ Circuit breaker TRIPPED for task %s (%d skips) — auto-failing to 'dead'",
                task_id[:12], skips,
            )
            await r.delete(key)

            # Auto-fail in DB — use 'dead' so get_healable_tasks() excludes it
            conn = await _get_db()
            try:
                await conn.execute(
                    "UPDATE tasks SET status='dead', error_code='SELF_HEALING_EXHAUSTED', "
                    "error_message='Circuit breaker: skipped >3 times', updated_at=NOW() WHERE id=$1",
                    task_id,
                )
            finally:
                await conn.close()

            # Clean Redis
            await _clean_redis_keys_for_task(task_id)
            return True  # skip

        logger.info(
            "Circuit breaker for task %s: skip %d/%d",
            task_id[:12], skips, CIRCUIT_BREAKER_MAX_SKIPS,
        )
        return False  # don't skip
    finally:
        await r.aclose()


async def _reset_circuit_breaker(task_id: str) -> None:
    """Reset circuit breaker counter on successful processing."""
    r = await _get_redis()
    try:
        await r.delete(f"circuit_breaker:task_id:{task_id}")
    finally:
        await r.aclose()


async def get_healable_tasks() -> list[dict]:
    """Get tasks that need healing.

    Fix 2: Excludes status IN ('failed','permanently_failed','cancelled')
    and only picks tasks with error_code IS NOT NULL AND error_code != 'SELF_HEALING_EXHAUSTED'.
    Also picks queued tasks > 600s.
    """
    conn = await _get_db()
    try:
        # Fix 2: Only pick failed tasks that have a real error_code (not NULL, not EXHAUSTED)
        # Explicitly exclude permanently_failed and cancelled to prevent infinite healing loops
        rows = await conn.fetch(
            "SELECT id, status, error_message, retry_count, progress_message, metadata, "
            "source_url, source_type, user_id, error_code "
            "FROM tasks "
            "WHERE status = 'failed' "
            "AND error_code IS NOT NULL "
            "AND error_code != 'SELF_HEALING_EXHAUSTED' "
            "AND error_code != 'permanently_failed'",
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
            "SELECT id, status, source_url, source_type, user_id, error_code "
            "FROM tasks WHERE status = 'queued' AND created_at < $1",
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
    """Mark task as permanently failed after exhausting healing attempts.

    Fix 4: Uses SCAN to find and delete ALL arq:* Redis keys for this task_id.
    Uses status='dead' (not 'failed') so get_healable_tasks() excludes it
    automatically — preventing infinite re-enqueue loops.

    Also writes to the dead_letter_tasks table so the admin can view and
    manually retry dead tasks.
    """
    conn = await _get_db()
    try:
        await conn.execute(
            "UPDATE tasks SET status='dead', error_code='SELF_HEALING_EXHAUSTED', "
            "error_message=$1, updated_at=NOW() WHERE id=$2",
            error_message[:500],
            task_id,
        )
        # Write to dead_letter_tasks table (idempotent via UNIQUE(task_id))
        await conn.execute(
            """
            INSERT INTO dead_letter_tasks (id, task_id, original_status, error_code, error_message, source)
            VALUES ($1, $2, 'dead', 'SELF_HEALING_EXHAUSTED', $3, 'self_healing')
            ON CONFLICT (task_id) DO UPDATE
                SET error_code = EXCLUDED.error_code,
                    error_message = EXCLUDED.error_message,
                    retried_at = NULL,
                    retried_by = NULL
            """,
            str(uuid.uuid4()),
            task_id,
            error_message[:500],
        )
        logger.warning("⚠️ Task %s permanently failed (SELF_HEALING_EXHAUSTED) → status='dead'", task_id[:12])
    finally:
        await conn.close()

    # Fix 4: Comprehensive Redis cleanup using SCAN
    try:
        deleted = await _clean_redis_keys_for_task(task_id)
        logger.info("🗑️ Cleaned %d Redis keys for task %s", deleted, task_id[:12])
    except Exception as exc:
        logger.warning("Failed to clean Redis keys for task %s: %s", task_id[:12], exc)



async def heal_task(task: dict) -> str:
    """Heal a single failed task using ErrorDiagnostician + CodePatcher.

    Fix 3: Atomic Postgres→Redis update (Postgres first, rollback if Redis fails).
    Fix 5: Circuit breaker check before healing.
    """
    from .error_diagnostician import ErrorDiagnostician
    from .code_patcher import CodePatcher

    task_id = task["id"]
    error = task.get("error_message") or task.get("progress_message") or ""
    tb = (task.get("metadata") or {}).get("traceback", "")
    attempts = (task.get("metadata") or {}).get("self_healing_attempts", 0)

    # Fix 5: Circuit breaker — skip if task has been skipped too many times
    should_skip = await _circuit_breaker_skip(task_id)
    if should_skip:
        return "CIRCUIT_BREAKER_SKIP"

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

    # Fix 3: Atomic Postgres→Redis — update Postgres FIRST, then enqueue
    source = await get_task_source(task_id)
    conn = await _get_db()
    try:
        # Step 1: Update Postgres status to 'queued' first
        result = await conn.execute(
            "UPDATE tasks SET status='queued', updated_at=NOW() WHERE id=$1 AND status='failed'",
            task_id,
        )
        if result == "UPDATE 0":
            logger.warning("Task %s not in 'failed' status anymore — skipping re-enqueue", task_id[:12])
            return "STATUS_CHANGED"
    except Exception as db_err:
        logger.error("Failed to update task %s status to queued: %s", task_id[:12], db_err)
        return "DB_UPDATE_FAILED"
    finally:
        await conn.close()

    # Step 2: Remove any stale ARQ jobs for this task_id before enqueuing a new one
    # (BUG 1 fix: prevents duplicate jobs piling up in the Redis queue)
    try:
        r = await _get_redis()
        try:
            stale = await _remove_arq_jobs_for_task(r, task_id)
            if stale:
                logger.info("🧹 Removed %d stale ARQ jobs for task %s before re-enqueue", stale, task_id[:12])
        finally:
            await r.aclose()
    except Exception as clean_exc:
        logger.warning("Failed to clean stale ARQ jobs for %s: %s", task_id[:12], clean_exc)

    # Step 3: Enqueue in Redis
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

        # Reset circuit breaker on successful re-enqueue
        await _reset_circuit_breaker(task_id)
    except Exception as exc:
        logger.error("Re-enqueue failed for %s: %s", task_id[:12], exc)
        # Step 3: Rollback Postgres status if Redis enqueue failed
        conn_rollback = await _get_db()
        try:
            await conn_rollback.execute(
                "UPDATE tasks SET status='failed', updated_at=NOW() WHERE id=$1 AND status='queued'",
                task_id,
            )
            logger.info("↩️ Rolled back task %s to 'failed' after enqueue failure", task_id[:12])
        finally:
            await conn_rollback.close()
        return "ENQUEUE_FAILED"

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
