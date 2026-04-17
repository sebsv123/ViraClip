"""
Enhanced Health Service — Phase 19

Provides detailed health checks for all infrastructure components:
  - Database (async SQLAlchemy ping)
  - Redis (PING command)
  - Disk space (storage directory free space)
  - Worker queue (Redis-backed job queue reachability)
"""

import logging
import os
import shutil
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

_STORAGE_PATH = os.environ.get("STORAGE_PATH", "/app/storage")
_DISK_WARN_GB = float(os.environ.get("DISK_WARN_GB", "5"))


async def check_redis() -> Dict[str, Any]:
    start = time.monotonic()
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        pong = await redis.ping()
        latency_ms = (time.monotonic() - start) * 1000
        return {
            "status": "ok" if pong else "degraded",
            "latency_ms": round(latency_ms, 2),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def check_database() -> Dict[str, Any]:
    start = time.monotonic()
    try:
        from src.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def check_disk() -> Dict[str, Any]:
    try:
        path = _STORAGE_PATH if os.path.exists(_STORAGE_PATH) else "/"
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = round((usage.used / usage.total) * 100, 1)
        status = "ok" if free_gb >= _DISK_WARN_GB else "warning"
        return {
            "status": status,
            "path": path,
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_pct": used_pct,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def check_worker_queue() -> Dict[str, Any]:
    """Check that the job queue is reachable by doing a lightweight LLEN."""
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        queue_len = await redis.llen("arq:queue")
        return {"status": "ok", "queue_length": queue_len}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def full_health_check() -> Dict[str, Any]:
    """Run all health checks and return a combined report."""
    redis_status = await check_redis()
    db_status = await check_database()
    disk_status = check_disk()
    queue_status = await check_worker_queue()

    components = {
        "redis": redis_status,
        "database": db_status,
        "disk": disk_status,
        "worker_queue": queue_status,
    }

    all_ok = all(
        c.get("status") == "ok" for c in components.values()
    )
    has_warning = any(
        c.get("status") == "warning" for c in components.values()
    )
    overall = "ok" if all_ok else ("warning" if has_warning else "degraded")

    return {
        "status": overall,
        "timestamp": time.time(),
        "components": components,
    }
