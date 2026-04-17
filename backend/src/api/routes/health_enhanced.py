"""
Enhanced Health API Route — Phase 19

GET /health/detailed  → full component-level health report
GET /health/ready     → readiness probe (DB + Redis must be ok)
GET /health/live      → liveness probe (always 200 if process is up)
"""

import logging

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/health", tags=["health-enhanced"])
logger = logging.getLogger(__name__)


@router.get("/detailed")
async def detailed_health():
    """Full health check: Redis, database, disk, worker queue."""
    from src.services.health_service import full_health_check
    report = await full_health_check()
    status_code = 200 if report["status"] in ("ok", "warning") else 503
    if status_code == 503:
        raise HTTPException(status_code=503, detail=report)
    return report


@router.get("/ready")
async def readiness_probe():
    """
    Readiness probe: returns 200 only if DB and Redis are reachable.
    Used by Kubernetes/Docker health checks to stop routing traffic during startup.
    """
    from src.services.health_service import check_redis, check_database
    redis_status = await check_redis()
    db_status = await check_database()

    if redis_status["status"] == "error" or db_status["status"] == "error":
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "redis": redis_status,
                "database": db_status,
            },
        )
    return {"ready": True, "redis": redis_status, "database": db_status}


@router.get("/live")
def liveness_probe():
    """Liveness probe: always 200 if the process is running."""
    return {"alive": True}
