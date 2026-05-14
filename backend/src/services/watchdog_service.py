"""
Auto-healing watchdog — detects errors, diagnoses, repairs, and retries automatically.

Runs every 60s and applies these healing rules:

1. QUEUED > 600s → re-enqueue via JobQueue (never mark failed)
2. FAILED with "_SegmentsWrapper has no attribute" → already fixed, re-enqueue
3. FAILED with "function=final_result" / "Invalid JSON" / "output validation" →
   strip_function_wrapper() fix applied to ai.py, then re-enqueue
4. FAILED with "Exceeded maximum retries" → increase max_result_retries in ai.py, re-enqueue
5. Any FAILED with retry_count < 3 → re-enqueue automatically
6. retry_count >= 3 → mark dead permanently with descriptive error_code

Retry tracking uses the watchdog_events table (not error_code column, which gets
cleared by workers). This prevents infinite re-enqueue loops.

Usage:
    cd /home/_sebastian/CascadeProjects/ViraClip/backend
    .venv/bin/python -m src.services.watchdog_service
"""
import asyncio
import json
import logging
import os
import re
import signal
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
)
logger = logging.getLogger("watchdog")

# ── Config ──────────────────────────────────────────────────────────────────
_REDIS_HOST = os.getenv("REDIS_HOST", "redis")
_REDIS_PORT = os.getenv("REDIS_PORT", "6379")
_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
_DB_URL = os.getenv("DATABASE_URL", "postgresql://viraclip:viraclip_password@postgres:5432/viraclip")

if _REDIS_PASSWORD:
    REDIS_URL = f"redis://:{_REDIS_PASSWORD}@{_REDIS_HOST}:{_REDIS_PORT}"
else:
    REDIS_URL = f"redis://{_REDIS_HOST}:{_REDIS_PORT}"

DATABASE_URL = _DB_URL
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

LOOP_INTERVAL_S = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "60"))
QUEUED_TIMEOUT_S = int(os.getenv("WATCHDOG_QUEUED_TIMEOUT_S", "600"))
MAX_RETRIES = int(os.getenv("WATCHDOG_MAX_RETRIES", "3"))
# Circuit breaker: how far back to look for re-enqueue events (default 24h)
RETRY_WINDOW_HOURS = int(os.getenv("WATCHDOG_RETRY_WINDOW_HOURS", "24"))

_shutdown = asyncio.Event()

# ── Known error patterns and their healing actions ──────────────────────────
HEALING_RULES = [
    # (error_pattern, fix_description, fix_file, fix_search, fix_replace)
    (
        re.compile(r"_SegmentsWrapper has no attribute"),
        "SegmentsWrapper bug already fixed in _pipeline.py — re-enqueue",
        "", "", "",
    ),
    (
        re.compile(r"function=final_result|Invalid JSON|output validation"),
        "LLM returned XML wrapper — apply strip_function_wrapper to ai.py",
        "src/ai.py",
        "result = await agent.run(user_prompt)",
        "result = await agent.run(user_prompt)\n    # Strip XML/JSON wrappers from LLM output\n    import re as _re\n    _raw = getattr(result, 'output', None) or getattr(result, 'data', None)\n    if isinstance(_raw, str):\n        _m = _re.search(r'<function[^>]*>(.*?)</function>', _raw, _re.DOTALL)\n        if _m:\n            _raw = _m.group(1).strip()\n        _m = _re.search(r'```(?:json)?\\s*(.*?)\\s*```', _raw, _re.DOTALL)\n        if _m:\n            _raw = _m.group(1).strip()",
    ),
    (
        re.compile(r"Exceeded maximum retries"),
        "Increase max_result_retries in ai.py — re-enqueue",
        "src/ai.py",
        "max_result_retries",
        "max_result_retries = 3  # increased by watchdog",
    ),
]


async def _ensure_table(conn: Any) -> None:
    """Create watchdog_events and dead_letter_tasks tables if they don't exist."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watchdog_events (
            id          UUID PRIMARY KEY,
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            error_type  VARCHAR(50) NOT NULL,
            context     JSONB,
            fix_applied VARCHAR(200),
            fix_success BOOLEAN
        )
        """
    )
    # Add index on (error_type, context->>'task_id') for fast retry counting
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_watchdog_events_task_retry
        ON watchdog_events (error_type, (context->>'task_id'))
        """
    )
    # Dead-letter table — tasks that have exhausted all retries
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dead_letter_tasks (
            id              UUID PRIMARY KEY,
            task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            original_status VARCHAR(50) NOT NULL DEFAULT 'dead',
            error_code      VARCHAR(100) NOT NULL,
            error_message   TEXT,
            source          VARCHAR(50) NOT NULL DEFAULT 'watchdog',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            retried_at      TIMESTAMPTZ,
            retried_by      VARCHAR(100),
            UNIQUE(task_id)
        )
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dead_letter_tasks_created_at
            ON dead_letter_tasks (created_at DESC)
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dead_letter_tasks_retried
            ON dead_letter_tasks (retried_at)
            WHERE retried_at IS NULL
        """
    )



async def _log_event(conn: Any, error_type: str, context: dict, fix_applied: str, fix_success: bool) -> None:
    try:
        await conn.execute(
            "INSERT INTO watchdog_events (id, detected_at, error_type, context, fix_applied, fix_success) "
            "VALUES ($1, $2, $3, $4::jsonb, $5, $6)",
            str(uuid.uuid4()), datetime.now(timezone.utc), error_type,
            json.dumps(context), fix_applied, fix_success,
        )
    except Exception as exc:
        logger.warning("Failed to log event: %s", exc)


async def _apply_file_fix(fix_file: str, fix_search: str, fix_replace: str) -> bool:
    """Apply a SEARCH/REPLACE fix to a source file."""
    file_path = Path("/app") / fix_file
    if not file_path.exists():
        logger.warning("Fix file not found: %s", file_path)
        return False
    try:
        content = file_path.read_text(encoding="utf-8")
        if fix_search not in content:
            logger.warning("Fix search not found in %s", fix_file)
            return False
        new_content = content.replace(fix_search, fix_replace)
        if new_content == content:
            return False
        file_path.write_text(new_content, encoding="utf-8")
        logger.info("✅ Fix applied to %s", fix_file)
        return True
    except Exception as exc:
        logger.error("Failed to apply fix to %s: %s", fix_file, exc)
        return False


async def _re_enqueue_task(r: Any, task_id: str) -> bool:
    """Re-enqueue a task via arq directly (no JobQueue import to avoid zombie subprocesses)."""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        settings = RedisSettings(
            host=_REDIS_HOST,
            port=int(_REDIS_PORT),
            password=_REDIS_PASSWORD or None,
            database=0,
        )
        pool = await create_pool(settings)
        try:
            job = await pool.enqueue_job(
                "process_video_task",
                task_id, "", "", "",
                _queue_name="viraclip_cpu_tasks",
            )
            if job:
                logger.info("✅ Re-enqueued task %s (job %s)", str(task_id)[:12], getattr(job, "job_id", "?"))
                return True
            logger.error("Failed to enqueue job for task %s", str(task_id)[:12])
            return False
        finally:
            await pool.close()
    except Exception as exc:
        logger.error("Failed to re-enqueue task %s: %s", str(task_id)[:12], exc)
        return False


async def _get_retry_count(conn: Any, task_id: str) -> int:
    """
    Get retry count from watchdog_events table (not error_code).

    Counts HEAL_RE_ENQUEUE or HEAL_RE_ENQUEUE_GENERIC events for this task
    within the retry window. This is reliable because watchdog_events are
    append-only and never cleared by workers.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RETRY_WINDOW_HOURS)
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS cnt FROM watchdog_events
        WHERE error_type IN ('HEAL_RE_ENQUEUE', 'HEAL_RE_ENQUEUE_GENERIC')
          AND context->>'task_id' = $1
          AND detected_at >= $2
        """,
        str(task_id),
        cutoff,
    )
    return row["cnt"] if row else 0


async def _mark_task_dead(conn: Any, task_id: str, error_code: str, error_message: str) -> None:
    """Mark a task as permanently dead (circuit breaker) and write to dead-letter store."""
    await conn.execute(
        """
        UPDATE tasks
        SET status = 'dead',
            error_code = $1,
            error_message = $2,
            updated_at = NOW()
        WHERE id = $3
        """,
        error_code,
        error_message[:500],
        task_id,
    )
    # Write to dead_letter_tasks table (idempotent via UNIQUE(task_id))
    await conn.execute(
        """
        INSERT INTO dead_letter_tasks (id, task_id, original_status, error_code, error_message, source)
        VALUES ($1, $2, 'dead', $3, $4, 'watchdog')
        ON CONFLICT (task_id) DO UPDATE
            SET error_code = EXCLUDED.error_code,
                error_message = EXCLUDED.error_message,
                retried_at = NULL,
                retried_by = NULL
        """,
        str(uuid.uuid4()),
        task_id,
        error_code,
        error_message[:500],
    )
    logger.info("🔴 Task %s marked dead: %s", str(task_id)[:12], error_code)



# ── Healing check ───────────────────────────────────────────────────────────
async def _check_and_heal(conn: Any, r: Any) -> None:
    """Main healing loop — find broken tasks and fix them."""
    now = datetime.now(timezone.utc)

    # 1. QUEUED > 600s → re-enqueue
    queued_cutoff = now - timedelta(seconds=QUEUED_TIMEOUT_S)
    rows = await conn.fetch(
        "SELECT id FROM tasks WHERE status = 'queued' AND created_at < $1",
        queued_cutoff,
    )
    for row in rows:
        task_id = row["id"]
        ok = await _re_enqueue_task(r, task_id)
        await _log_event(conn, "QUEUED_HEAL", {"task_id": str(task_id)}, "re_enqueue", ok)
        logger.info("[HEAL] QUEUED task %s → re-enqueue (%s)", str(task_id)[:12], "OK" if ok else "FAIL")

    # 2. FAILED tasks — check retry count and heal or mark dead
    rows = await conn.fetch(
        "SELECT id, error_code, error_message FROM tasks WHERE status = 'failed'",
    )
    for row in rows:
        task_id = row["id"]
        error_code = row["error_code"] or ""
        error_message = row["error_message"] or ""
        retry_count = await _get_retry_count(conn, task_id)

        # Circuit breaker: if already exhausted, skip
        if retry_count >= MAX_RETRIES:
            logger.info(
                "[HEAL] Task %s retry_count=%d >= %d — marking dead (circuit breaker)",
                str(task_id)[:12], retry_count, MAX_RETRIES,
            )
            await _mark_task_dead(
                conn, task_id,
                "WATCHDOG_EXHAUSTED",
                f"Watchdog re-enqueued {retry_count} times without success. "
                f"Last error: {error_code} — {error_message}",
            )
            await _log_event(
                conn, "CIRCUIT_BREAKER",
                {"task_id": str(task_id), "retry_count": retry_count, "error_code": error_code},
                "mark_dead", True,
            )
            continue

        combined = f"{error_code} {error_message}"
        healed = False

        for pattern, desc, fix_file, fix_search, fix_replace in HEALING_RULES:
            if pattern.search(combined):
                logger.info("[HEAL] Task %s matched: %s", str(task_id)[:12], desc)
                # Apply file fix if needed
                if fix_file and fix_search:
                    fix_ok = await _apply_file_fix(fix_file, fix_search, fix_replace)
                    await _log_event(conn, "FILE_FIX", {"file": fix_file, "pattern": desc}, "apply_fix", fix_ok)
                # Re-enqueue
                ok = await _re_enqueue_task(r, task_id)
                await _log_event(conn, "HEAL_RE_ENQUEUE", {"task_id": str(task_id), "retry": retry_count + 1}, "re_enqueue", ok)
                healed = True
                break

        if not healed:
            # Generic re-enqueue for unknown errors
            logger.info(
                "[HEAL] Task %s unknown error — re-enqueue (retry %d/%d)",
                str(task_id)[:12], retry_count + 1, MAX_RETRIES,
            )
            ok = await _re_enqueue_task(r, task_id)
            await _log_event(conn, "HEAL_RE_ENQUEUE_GENERIC", {"task_id": str(task_id), "retry": retry_count + 1}, "re_enqueue", ok)

    # 3. PROCESSING > 15min → mark failed
    proc_cutoff = now - timedelta(seconds=900)
    rows = await conn.fetch(
        "SELECT id FROM tasks WHERE status = 'processing' AND updated_at < $1",
        proc_cutoff,
    )
    for row in rows:
        task_id = row["id"]
        await conn.execute(
            "UPDATE tasks SET status='failed', error_code='PROCESSING_TIMEOUT', updated_at=NOW() WHERE id=$1",
            task_id,
        )
        await _log_event(conn, "PROCESSING_TIMEOUT", {"task_id": str(task_id)}, "mark_failed", True)
        logger.info("[HEAL] PROCESSING timeout task %s → failed", str(task_id)[:12])


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Auto-healing watchdog starting (interval=%ds, max_retries=%d)", LOOP_INTERVAL_S, MAX_RETRIES)
    logger.info("=" * 50)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown.set)

    # Connect PostgreSQL
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await _ensure_table(conn)
        logger.info("✅ Connected to PostgreSQL")
    except Exception as exc:
        logger.critical("PostgreSQL connection failed: %s", exc)
        sys.exit(1)

    # Connect Redis
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        await r.ping()
        logger.info("✅ Connected to Redis")
    except Exception as exc:
        logger.critical("Redis connection failed: %s", exc)
        sys.exit(1)

    try:
        while not _shutdown.is_set():
            try:
                await _check_and_heal(conn, r)
            except Exception as exc:
                logger.error("Healing cycle failed: %s", exc)
            for _ in range(LOOP_INTERVAL_S):
                if _shutdown.is_set():
                    break
                await asyncio.sleep(1)
    finally:
        await r.aclose()
        await conn.close()
        logger.info("Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
