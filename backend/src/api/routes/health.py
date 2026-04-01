"""
Health check and system status endpoints.

Provides detailed health information for monitoring and ops.
"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...database import get_db
from ...scaling.redis_manager import get_redis_manager
from ...caching import get_cache
from ...services.metrics_service import get_metrics_collector
from ...services.cache_manager import get_cache_manager
from ...services.concurrency_optimizer import get_optimizer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    """
    Basic health check endpoint.
    
    Returns 200 if service is running.
    """
    return {"status": "ok", "service": "viraclip"}


@router.get("/detailed")
async def detailed_health(db: AsyncSession = Depends(get_db)):
    """
    Detailed health check with all dependencies.
    
    Checks:
    - Database connectivity
    - Redis connectivity
    - Cache metrics
    """
    health = {
        "status": "ok",
        "checks": {}
    }
    
    # Database check
    try:
        result = await db.execute(text("SELECT 1"))
        result.fetchone()
        health["checks"]["database"] = {"status": "healthy"}
    except Exception as e:
        health["status"] = "degraded"
        health["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    # Redis check
    try:
        redis_manager = await get_redis_manager()
        redis_health = await redis_manager.health_check()
        health["checks"]["redis"] = redis_health
        
        if redis_health["status"] != "healthy":
            health["status"] = "degraded"
    except Exception as e:
        health["status"] = "degraded"
        health["checks"]["redis"] = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    # Cache metrics
    try:
        cache = get_cache()
        metrics = await cache.get_metrics()
        health["checks"]["cache"] = {
            "status": "healthy",
            "metrics": metrics
        }
    except Exception as e:
        health["checks"]["cache"] = {
            "status": "error",
            "error": str(e)
        }
    
    return health


@router.get("/redis")
async def redis_status():
    """Get Redis connection status and metrics."""
    try:
        redis_manager = await get_redis_manager()
        return await redis_manager.health_check()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/cache/metrics")
async def cache_metrics():
    """Get cache performance metrics."""
    try:
        cache = get_cache()
        metrics = await cache.get_metrics()
        return {"status": "ok", "metrics": metrics}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/metrics/pipeline")
async def pipeline_metrics():
    """
    Get pipeline processing metrics.
    
    Returns:
    - Total pipelines processed
    - Success rate
    - Stage averages
    - Daily stats
    """
    try:
        collector = get_metrics_collector()
        summary = collector.get_summary(days=7)
        return {
            "status": "ok",
            "metrics": summary
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/metrics/smart-cache")
async def smart_cache_metrics():
    """Get Smart Cache Manager metrics."""
    try:
        cache_mgr = get_cache_manager()
        stats = cache_mgr.get_stats()
        return {
            "status": "ok",
            "metrics": stats
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/metrics/concurrency")
async def concurrency_metrics():
    """Get Concurrency Optimizer metrics."""
    try:
        optimizer = await get_optimizer()
        stats = optimizer.get_stats()
        return {
            "status": "ok",
            "metrics": stats
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/system/resources")
async def system_resources():
    """
    Get system resource usage.
    
    Returns:
    - CPU usage
    - Memory usage
    - Disk usage
    """
    try:
        import psutil
        
        return {
            "status": "ok",
            "resources": {
                "cpu": {
                    "percent": psutil.cpu_percent(interval=0.1),
                    "count": psutil.cpu_count()
                },
                "memory": {
                    "total_gb": psutil.virtual_memory().total / (1024**3),
                    "available_gb": psutil.virtual_memory().available / (1024**3),
                    "percent": psutil.virtual_memory().percent
                },
                "disk": {
                    "total_gb": psutil.disk_usage('/').total / (1024**3),
                    "free_gb": psutil.disk_usage('/').free / (1024**3),
                    "percent": psutil.disk_usage('/').percent
                }
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/performance/slow-stages")
async def slow_stages(threshold_ms: float = 5000):
    """
    Get pipeline stages that are consistently slow.
    
    Args:
        threshold_ms: Minimum average duration to report (default 5000ms)
    """
    try:
        collector = get_metrics_collector()
        slow = collector.get_slow_stages(threshold_ms=threshold_ms)
        return {
            "status": "ok",
            "slow_stages": slow,
            "threshold_ms": threshold_ms
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
