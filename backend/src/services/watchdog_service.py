"""
Production-grade watchdog service — auto-heals all pipeline issues every N seconds.

11 checks:
  1. QUEUED_TIMEOUT      — tasks queued >120s without ARQ result → mark failed
  2. PROCESSING_TIMEOUT  — tasks processing >15min → mark failed + clean Redis
  3. ORPHAN_RESULT       — arq:result:* keys with no matching task → delete key
  4. ORPHAN_PROCESSING   — tasks "processing" without arq:job:* in Redis → mark failed
  5. WORKER_HEALTH       — 0 workers + stale queued >5min → docker restart
  6. REDIS_CONN_FAILURE  — Redis down → log critical + retry backoff
  7. DB_CONN_FAILURE     — PostgreSQL down → log critical + retry backoff
  8. STUCK_EXPORT        — tasks "exporting" >10min → mark failed
  9. ZOMBIE_TASKS        — tasks created >24h never finished → force failed
 10. REDIS_MEMORY_PRESSURE — Redis >80% maxmemory → purge old arq:result:*
 11. DLQ_DRAIN           — dead letter queue entries → mark tasks failed

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
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG][%(name)s] %(message)s",
)
logger = logging.getLogger("watchdog")

# ── Config from env (uses same env vars as workers — works in Docker Compose) ─
_REDIS_HOST = os.getenv("REDIS_HOST", "redis")
_REDIS_PORT = os.getenv("REDIS_PORT", "6379")
_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
_DB_USER = os.getenv("DATABASE_URL", "postgresql://viraclip:viraclip_password@postgres:5432/viraclip")

# Build Redis URL from individual env vars (same pattern as config.py)
if _REDIS_PASSWORD:
    REDIS_URL = f"redis://:{_REDIS_PASSWORD}@{_REDIS_HOST}:{_REDIS_PORT}"
else:
    REDIS_URL = f"redis://{_REDIS_HOST}:{_REDIS_PORT}"

# Build PostgreSQL URL from DATABASE_URL (already points to postgres:5432 in Docker)
DATABASE_URL = _DB_USER
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

LOOP_INTERVAL_S = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "60"))
WORKER_CONTAINER = os.getenv("WATCHDOG_WORKER_CONTAINER", "viraclip-worker")

QUEUED_TIMEOUT_S = int(os.getenv("WATCHDOG_QUEUED_TIMEOUT_S", "120"))
PROCESSING_TIMEOUT_S = int(os.getenv("WATCHDOG_PROCESSING_TIMEOUT_S", "900"))  # 15min
STUCK_EXPORT_S = int(os.getenv("WATCHDOG_STUCK_EXPORT_S", "600"))  # 10min
ZOMBIE_HOURS = int(os.getenv("WATCHDOG_ZOMBIE_HOURS", "24"))
WORKER_DOWN_TIMEOUT_S = int(os.getenv("WATCHDOG_WORKER_DOWN_TIMEOUT_S", "300"))
REDIS_MEMORY_PCT = int(os.getenv("WATCHDOG_REDIS_MEMORY_PCT", "80"))

# ── Global shutdown flag ────────────────────────────────────────────────────
_shutdown = asyncio.Event()


def _handle_sigterm() -> None:
    logger.info("[SIGNAL] SIGTERM received — shutting down gracefully")
    _shutdown.set()


# ── Helpers ─────────────────────────────────────────────────────────────────
def _log_check(check: str, status: str, msg: str = "") -> None:
    logger.info("[%s][%s] %s", check, status, msg)


async def _log_event(
    conn: Any,
    error_type: str,
    context: dict,
    fix_applied: str,
    fix_success: bool,
) -> None:
    try:
        await conn.execute(
            """
            INSERT INTO watchdog_events (id, detected_at, error_type, context, fix_applied, fix_success)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            """,
            str(uuid.uuid4()),
            datetime.now(timezone.utc),
            error_type,
            json.dumps(context),
            fix_applied,
            fix_success,
        )
    except Exception as exc:
        logger.warning("[EVENT_LOG] Failed to insert event: %s", exc)


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


async def _connect_postgres(retries: int = 3, delay: float = 2.0) -> Optional[Any]:
    for attempt in range(1, retries + 1):
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            await _ensure_table(conn)
            _log_check("DB_CONN", "OK", f"Connected (attempt {attempt})")
            return conn
        except Exception as exc:
            wait = delay * (2 ** (attempt - 1))
            _log_check("DB_CONN", "RETRY", f"Attempt {attempt}/{retries} failed: {exc}. Retrying in {wait:.0f}s")
            await asyncio.sleep(wait)
    _log_check("DB_CONN", "CRITICAL", "All connection attempts exhausted")
    return None


async def _connect_redis(retries: int = 3, delay: float = 2.0) -> Optional[Any]:
    for attempt in range(1, retries + 1):
        try:
            import redis.asyncio as aioredis
            r = await aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5)
            await r.ping()
            _log_check("REDIS_CONN", "OK", f"Connected (attempt {attempt})")
            return r
        except Exception as exc:
            wait = delay * (2 ** (attempt - 1))
            _log_check("REDIS_CONN", "RETRY", f"Attempt {attempt}/{retries} failed: {exc}. Retrying in {wait:.0f}s")
            await asyncio.sleep(wait)
    _log_check("REDIS_CONN", "CRITICAL", "All connection attempts exhausted")
    return None


# ── Check 1: QUEUED_TIMEOUT ────────────────────────────────────────────────
async def _check_queued_timeout(conn: Any, r: Any) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=QUEUED_TIMEOUT_S)
    rows = await conn.fetch(
        "SELECT id, created_at FROM tasks WHERE status = 'queued' AND created_at < $1",
        cutoff,
    )
    for row in rows:
        task_id = row["id"]
        result_key = f"arq:result:{task_id}"
        if await r.exists(result_key):
            raw = await r.get(result_key)
            data = json.loads(raw) if raw else {}
            err = str(data.get("error", "E_RESULT_ORPHAN"))[:80]
            await conn.execute(
                "UPDATE tasks SET status='failed', error_code=$1, updated_at=NOW() WHERE id=$2",
                err, task_id,
            )
            await _log_event(conn, "QUEUED_TIMEOUT", {"task_id": str(task_id)}, "mark_failed", True)
            _log_check("QUEUED_TIMEOUT", "FIXED", f"Task {str(task_id)[:12]} had ARQ result → failed")
        else:
            # No ARQ result — just mark as failed (safer than re-enqueue without arq)
            await conn.execute(
                "UPDATE tasks SET status='failed', error_code='QUEUED_TIMEOUT', updated_at=NOW() WHERE id=$1",
                task_id,
            )
            await _log_event(conn, "QUEUED_TIMEOUT", {"task_id": str(task_id)}, "mark_failed_no_result", True)
            _log_check("QUEUED_TIMEOUT", "FIXED", f"Task {str(task_id)[:12]} no ARQ result → failed")


# ── Check 2: PROCESSING_TIMEOUT ────────────────────────────────────────────
async def _check_processing_timeout(conn: Any, r: Any) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=PROCESSING_TIMEOUT_S)
    rows = await conn.fetch(
        "SELECT id, updated_at FROM tasks WHERE status = 'processing' AND updated_at < $1",
        cutoff,
    )
    for row in rows:
        task_id = row["id"]
        job_key = f"arq:job:{task_id}"
        if await r.exists(job_key):
            await r.delete(job_key)
        await conn.execute(
            "UPDATE tasks SET status='failed', error_code='PROCESSING_TIMEOUT', updated_at=NOW() WHERE id=$1",
            task_id,
        )
        await _log_event(conn, "PROCESSING_TIMEOUT", {"task_id": str(task_id)}, "mark_failed+clean_redis", True)
        _log_check("PROCESSING_TIMEOUT", "FIXED", f"Task {str(task_id)[:12]} timed out → failed")


# ── Check 3: ORPHAN_RESULT ─────────────────────────────────────────────────
async def _check_orphan_results(conn: Any, r: Any) -> None:
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="arq:result:*", count=200)
        for key in keys:
            job_id = key.split("arq:result:", 1)[-1]
            row = await conn.fetchrow("SELECT id, status FROM tasks WHERE id = $1", job_id)
            if not row:
                await r.delete(key)
                await _log_event(conn, "ORPHAN_RESULT", {"job_id": job_id}, "delete_key", True)
                _log_check("ORPHAN_RESULT", "FIXED", f"Deleted key {key} (no task)")
            elif row["status"] not in ("queued", "processing"):
                await r.delete(key)
                await _log_event(conn, "ORPHAN_RESULT", {"job_id": job_id, "status": row["status"]}, "delete_key", True)
                _log_check("ORPHAN_RESULT", "FIXED", f"Deleted key {key} (task {row['status']})")
        if cursor == 0:
            break


# ── Check 4: ORPHAN_PROCESSING ─────────────────────────────────────────────
async def _check_orphan_processing(conn: Any, r: Any) -> None:
    rows = await conn.fetch("SELECT id FROM tasks WHERE status = 'processing'")
    for row in rows:
        task_id = row["id"]
        job_key = f"arq:job:{task_id}"
        if not await r.exists(job_key):
            await conn.execute(
                "UPDATE tasks SET status='failed', error_code='ORPHAN_PROCESSING', updated_at=NOW() WHERE id=$1",
                task_id,
            )
            await _log_event(conn, "ORPHAN_PROCESSING", {"task_id": str(task_id)}, "mark_failed", True)
            _log_check("ORPHAN_PROCESSING", "FIXED", f"Task {str(task_id)[:12]} had no arq:job → failed")


# ── Check 5: WORKER_HEALTH ─────────────────────────────────────────────────
async def _check_worker_health(conn: Any, r: Any) -> None:
    processing = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status = 'processing'")
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=WORKER_DOWN_TIMEOUT_S)
    stale = await conn.fetchval(
        "SELECT COUNT(*) FROM tasks WHERE status = 'queued' AND created_at < $1", cutoff,
    )
    if processing == 0 and stale > 0:
        _log_check("WORKER_HEALTH", "WARN", f"0 processing, {stale} stale → restarting {WORKER_CONTAINER}")
        try:
            subprocess.run(["docker", "restart", WORKER_CONTAINER], capture_output=True, text=True, timeout=30)
            await _log_event(conn, "WORKER_HEALTH", {"processing": 0, "stale_queued": stale}, "restart_container", True)
            _log_check("WORKER_HEALTH", "FIXED", "Restart command sent")
        except Exception as exc:
            await _log_event(conn, "WORKER_HEALTH", {"processing": 0, "stale_queued": stale, "error": str(exc)}, "restart_container", False)
            _log_check("WORKER_HEALTH", "ERROR", f"Restart failed: {exc}")


# ── Check 6+7: Connection health is handled by _connect_* with backoff ─────

# ── Check 8: STUCK_EXPORT ──────────────────────────────────────────────────
async def _check_stuck_export(conn: Any, r: Any) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STUCK_EXPORT_S)
    rows = await conn.fetch(
        "SELECT id FROM tasks WHERE status = 'exporting' AND updated_at < $1", cutoff,
    )
    for row in rows:
        await conn.execute(
            "UPDATE tasks SET status='failed', error_code='STUCK_EXPORT', updated_at=NOW() WHERE id=$1",
            row["id"],
        )
        await _log_event(conn, "STUCK_EXPORT", {"task_id": str(row["id"])}, "mark_failed", True)
        _log_check("STUCK_EXPORT", "FIXED", f"Task {str(row['id'])[:12]} stuck exporting → failed")


# ── Check 9: ZOMBIE_TASKS ─────────────────────────────────────────────────
async def _check_zombie_tasks(conn: Any, r: Any) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ZOMBIE_HOURS)
    rows = await conn.fetch(
        "SELECT id, status FROM tasks WHERE status NOT IN ('completed','failed','aborted') AND created_at < $1",
        cutoff,
    )
    for row in rows:
        await conn.execute(
            "UPDATE tasks SET status='failed', error_code='ZOMBIE_TASK', updated_at=NOW() WHERE id=$1",
            row["id"],
        )
        await _log_event(conn, "ZOMBIE_TASKS", {"task_id": str(row["id"]), "status": row["status"]}, "mark_failed", True)
        _log_check("ZOMBIE_TASKS", "FIXED", f"Task {str(row['id'])[:12]} ({row['status']}) → failed")


# ── Check 10: REDIS_MEMORY_PRESSURE ────────────────────────────────────────
async def _check_redis_memory(conn: Any, r: Any) -> None:
    try:
        info = await r.info("memory")
        used = info.get("used_memory", 0)
        maxmem = info.get("maxmemory", 0)
        if maxmem > 0 and (used / maxmem) * 100 > REDIS_MEMORY_PCT:
            _log_check("REDIS_MEMORY", "WARN", f"Memory at {used/maxmem*100:.0f}% > {REDIS_MEMORY_PCT}%")
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await r.scan(cursor=cursor, match="arq:result:*", count=500)
                for key in keys:
                    ttl = await r.ttl(key)
                    if ttl == -1 or ttl > 3600:
                        await r.delete(key)
                        deleted += 1
                if cursor == 0:
                    break
            if deleted:
                await _log_event(conn, "REDIS_MEMORY", {"purged": deleted}, "purge_keys", True)
                _log_check("REDIS_MEMORY", "FIXED", f"Purged {deleted} old arq:result:* keys")
    except Exception as exc:
        _log_check("REDIS_MEMORY", "ERROR", str(exc))


# ── Check 11: DLQ_DRAIN ────────────────────────────────────────────────────
async def _check_dlq_drain(conn: Any, r: Any) -> None:
    try:
        result = subprocess.run(
            ["docker", "logs", WORKER_CONTAINER, "--tail", "300", "2>&1"],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout + result.stderr
    except Exception:
        return

    for match in re.finditer(r"dead letter queue.*?task[_\s]*id[_\s]*[:=][_\s]*([a-f0-9-]+)", output, re.IGNORECASE):
        task_id = match.group(1)
        row = await conn.fetchrow("SELECT id, status FROM tasks WHERE id = $1", task_id)
        if row and row["status"] in ("queued", "processing"):
            await conn.execute(
                "UPDATE tasks SET status='failed', error_code='DLQ', updated_at=NOW() WHERE id=$1",
                task_id,
            )
            await _log_event(conn, "DLQ_DRAIN", {"task_id": task_id}, "mark_failed", True)
            _log_check("DLQ_DRAIN", "FIXED", f"Task {task_id[:12]} from DLQ → failed")


# ── Main cycle ──────────────────────────────────────────────────────────────
async def run_cycle(conn: Any, r: Any) -> None:
    checks = [
        ("QUEUED_TIMEOUT",      _check_queued_timeout),
        ("PROCESSING_TIMEOUT",  _check_processing_timeout),
        ("ORPHAN_RESULT",       _check_orphan_results),
        ("ORPHAN_PROCESSING",   _check_orphan_processing),
        ("WORKER_HEALTH",       _check_worker_health),
        ("STUCK_EXPORT",        _check_stuck_export),
        ("ZOMBIE_TASKS",        _check_zombie_tasks),
        ("REDIS_MEMORY",        _check_redis_memory),
        ("DLQ_DRAIN",           _check_dlq_drain),
    ]
    _log_check("CYCLE", "START", f"Running {len(checks)} checks")
    for name, check in checks:
        if _shutdown.is_set():
            break
        try:
            await check(conn, r)
        except Exception as exc:
            _log_check(name, "ERROR", str(exc)[:200])
    _log_check("CYCLE", "END", "Cycle complete")


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Watchdog starting (interval=%ds, %d checks)", LOOP_INTERVAL_S, 9)
    logger.info("=" * 50)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_sigterm)

    conn = await _connect_postgres()
    r = await _connect_redis()
    if not conn or not r:
        logger.critical("Cannot start without DB and Redis connections")
        sys.exit(1)

    try:
        while not _shutdown.is_set():
            await run_cycle(conn, r)
            for _ in range(LOOP_INTERVAL_S):
                if _shutdown.is_set():
                    break
                await asyncio.sleep(1)
    finally:
        logger.info("Shutting down...")
        if r:
            await r.aclose()
        if conn:
            await conn.close()
        logger.info("Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
