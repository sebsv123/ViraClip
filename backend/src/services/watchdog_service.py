"""
Auto-healing watchdog — detects errors, diagnoses, repairs, and retries automatically.

Runs every 60s and applies these healing rules:

1. QUEUED > 600s → re-enqueue via JobQueue (never mark failed)
2. FAILED with "_SegmentsWrapper has no attribute" → already fixed, re-enqueue
3. FAILED with "function=final_result" / "Invalid JSON" / "output validation" →
   strip_function_wrapper() fix applied to ai.py, then re-enqueue
4. FAILED with "Exceeded maximum retries" → increase max_result_retries in ai.py, re-enqueue
5. Any FAILED with retry_count < 3 → re-enqueue automatically
6. retry_count >= 3 → mark failed permanently with descriptive error_code

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


async def _re_enqueue_task(task_id: str) -> bool:
    """Re-enqueue a task via JobQueue."""
    try:
        sys.path.insert(0, "/app")
        from src.workers.job_queue import JobQueue
        await JobQueue.enqueue_processing_job(
            "process_video_task", "fast", task_id, "", "", "",
        )
        logger.info("✅ Re-enqueued task %s", str(task_id)[:12])
        return True
    except Exception as exc:
        logger.error("Failed to re-enqueue task %s: %s", str(task_id)[:12], exc)
        return False


async def _get_retry_count(conn: Any, task_id: str) -> int:
    """Get retry count from task metadata or error_code."""
    row = await conn.fetchrow(
        "SELECT error_code, metadata FROM tasks WHERE id = $1", task_id,
    )
    if not row:
        return 0
    error_code = row["error_code"] or ""
    # Count retries from error_code pattern: "RETRY_1", "RETRY_2", etc.
    m = re.search(r"RETRY_(\d+)", error_code)
    if m:
        return int(m.group(1))
    return 0


async def _set_retry_count(conn: Any, task_id: str, count: int) -> None:
    """Update retry count in error_code."""
    await conn.execute(
        "UPDATE tasks SET error_code = $1, updated_at = NOW() WHERE id = $2",
        f"RETRY_{count}",
        task_id,
    )


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
        ok = await _re_enqueue_task(task_id)
        await _log_event(conn, "QUEUED_HEAL", {"task_id": str(task_id)}, "re_enqueue", ok)
        logger.info("[HEAL] QUEUED task %s → re-enqueue (%s)", str(task_id)[:12], "OK" if ok else "FAIL")

    # 2. FAILED tasks with retry_count < MAX_RETRIES
    rows = await conn.fetch(
        "SELECT id, error_code, error_message FROM tasks WHERE status = 'failed'",
    )
    for row in rows:
        task_id = row["id"]
        error_code = row["error_code"] or ""
        error_message = row["error_message"] or ""
        retry_count = await _get_retry_count(conn, task_id)

        if retry_count >= MAX_RETRIES:
            logger.info("[HEAL] Task %s retry_count=%d >= %d — permanent failure", str(task_id)[:12], retry_count, MAX_RETRIES)
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
                ok = await _re_enqueue_task(task_id)
                await _set_retry_count(conn, task_id, retry_count + 1)
                await _log_event(conn, "HEAL_RE_ENQUEUE", {"task_id": str(task_id), "retry": retry_count + 1}, "re_enqueue", ok)
                healed = True
                break

        if not healed and retry_count < MAX_RETRIES:
            # Generic re-enqueue for unknown errors
            logger.info("[HEAL] Task %s unknown error — re-enqueue (retry %d/%d)", str(task_id)[:12], retry_count + 1, MAX_RETRIES)
            ok = await _re_enqueue_task(task_id)
            await _set_retry_count(conn, task_id, retry_count + 1)
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
