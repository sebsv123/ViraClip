"""
Prometheus Metrics for GPU Services
=====================================

Provides monitoring metrics for GPU utilization, queue depth, and job statistics.
Compatible with Prometheus + Grafana stack.

Metrics exposed:
- viraclip_gpu_jobs_total (Counter) — Total GPU jobs by type and status
- viraclip_gpu_jobs_duration_seconds (Histogram) — Job execution time
- viraclip_gpu_vram_bytes (Gauge) — VRAM usage per GPU
- viraclip_gpu_queue_depth (Gauge) — Current queue depth by type
- viraclip_gpu_active_jobs (Gauge) — Currently running jobs

Usage:
    from api.middleware.monitoring import record_job_completion, update_gpu_metrics
    
    # Record job metrics
    record_job_completion("t2v", "success", duration_seconds=45.2)

    # Update periodic metrics
    await update_gpu_metrics()

Endpoint:
    GET /metrics — Prometheus scrape endpoint
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Monitoring"])

# ── Prometheus Metrics ────────────────────────────────────────────────────────

# Job counters (by type and status)
gpu_jobs_total = Counter(
    "viraclip_gpu_jobs_total",
    "Total GPU jobs processed",
    ["job_type", "status"]  # job_type: t2v, tts, upscale, lora; status: success, error
)

# Job duration histogram
gpu_job_duration = Histogram(
    "viraclip_gpu_jobs_duration_seconds",
    "GPU job execution time",
    ["job_type"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600]  # Up to 1 hour
)

# VRAM usage gauge
gpu_vram_bytes = Gauge(
    "viraclip_gpu_vram_bytes",
    "GPU VRAM usage",
    ["device", "type"]  # type: total, used, free
)

# Queue depth gauge
gpu_queue_depth = Gauge(
    "viraclip_gpu_queue_depth",
    "Current GPU queue depth",
    ["queue_name"]  # viraclip_gpu_tasks, viraclip_cpu_tasks
)

# Active jobs gauge
gpu_active_jobs = Gauge(
    "viraclip_gpu_active_jobs",
    "Currently running GPU jobs",
    ["job_type"]
)

# Rate limit hits counter
rate_limit_hits = Counter(
    "viraclip_rate_limit_hits_total",
    "Rate limit violations",
    ["endpoint_type", "user_id_hash"]  # hashed user ID for privacy
)

# Health check gauge
service_health = Gauge(
    "viraclip_service_health",
    "Service health status (1=healthy, 0=unhealthy)",
    ["service"]  # database, redis, gpu
)


# ── Metric Recording Functions ───────────────────────────────────────────────

def record_job_start(job_type: str) -> None:
    """Record that a job has started."""
    gpu_active_jobs.labels(job_type=job_type).inc()


def record_job_completion(job_type: str, status: str, duration_seconds: float) -> None:
    """
    Record job completion metrics.
    
    Args:
        job_type: t2v, tts, upscale, upscale_8k, lora
        status: success, error, cancelled
        duration_seconds: Time from start to completion
    """
    gpu_jobs_total.labels(job_type=job_type, status=status).inc()
    gpu_job_duration.labels(job_type=job_type).observe(duration_seconds)
    gpu_active_jobs.labels(job_type=job_type).dec()


def record_rate_limit_hit(endpoint_type: str, user_id: str) -> None:
    """Record a rate limit violation."""
    import hashlib
    # Hash user ID for privacy in metrics
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
    rate_limit_hits.labels(endpoint_type=endpoint_type, user_id_hash=user_hash).inc()


async def update_gpu_metrics() -> None:
    """Update periodic GPU metrics (VRAM, queue depth)."""
    try:
        # Update VRAM metrics
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                total = props.total_memory
                used = torch.cuda.memory_allocated(i)
                free = total - used
                
                device_name = f"gpu_{i}"
                gpu_vram_bytes.labels(device=device_name, type="total").set(total)
                gpu_vram_bytes.labels(device=device_name, type="used").set(used)
                gpu_vram_bytes.labels(device=device_name, type="free").set(free)
    except ImportError:
        pass  # PyTorch not installed
    except Exception as e:
        logger.debug(f"Failed to update GPU metrics: {e}")
    
    # Update queue depth
    try:
        from ...workers.job_queue import JobQueue
        redis_client = await JobQueue.get_pool()
        
        # Try to get queue lengths from Redis
        # ARQ stores queue info in specific keys
        gpu_queue_len = await redis_client.llen("arq:queue:viraclip_gpu_tasks")
        cpu_queue_len = await redis_client.llen("arq:queue:viraclip_cpu_tasks")
        
        gpu_queue_depth.labels(queue_name="viraclip_gpu_tasks").set(gpu_queue_len)
        gpu_queue_depth.labels(queue_name="viraclip_cpu_tasks").set(cpu_queue_len)
    except Exception as e:
        logger.debug(f"Failed to update queue metrics: {e}")


async def update_service_health() -> None:
    """Update service health metrics."""
    # Database health
    try:
        from ...database import get_db
        async for db in get_db():
            from sqlalchemy import text
            await db.execute(text("SELECT 1"))
            service_health.labels(service="database").set(1)
            break
    except Exception:
        service_health.labels(service="database").set(0)
    
    # Redis health
    try:
        from ...workers.job_queue import JobQueue
        pool = await JobQueue.get_pool()
        await pool.ping()
        service_health.labels(service="redis").set(1)
    except Exception:
        service_health.labels(service="redis").set(0)
    
    # GPU health
    try:
        import torch
        if torch.cuda.is_available():
            service_health.labels(service="gpu").set(1)
        else:
            service_health.labels(service="gpu").set(0)
    except ImportError:
        service_health.labels(service="gpu").set(0)


# ── API Endpoints ───────────────────────────────────────────────────────────

@router.get("/metrics")
async def metrics_endpoint() -> Response:
    """
    Prometheus metrics scrape endpoint.
    
    Returns all metrics in Prometheus exposition format.
    Configure Prometheus to scrape: http://backend:8000/metrics
    """
    # Update dynamic metrics before serving
    await update_gpu_metrics()
    await update_service_health()
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@router.get("/health/detailed")
async def detailed_health() -> Dict[str, Any]:
    """
    Detailed health status with current metrics.
    
    Returns human-readable health info for debugging.
    """
    await update_gpu_metrics()
    await update_service_health()
    
    health_info = {
        "services": {},
        "gpu": None,
        "queue_depth": {},
        "active_jobs": {},
    }
    
    # Service health
    for service in ["database", "redis", "gpu"]:
        value = service_health.labels(service=service)._value.get()
        health_info["services"][service] = "healthy" if value == 1 else "unhealthy"
    
    # GPU info
    try:
        import torch
        if torch.cuda.is_available():
            device = torch.cuda.get_device_properties(0)
            health_info["gpu"] = {
                "name": device.name,
                "total_vram_gb": round(device.total_memory / (1024**3), 2),
                "cuda_version": torch.version.cuda,
            }
    except:
        pass
    
    return health_info


# ── Middleware for Automatic Metrics ──────────────────────────────────────────

# Module-level metrics (singleton pattern to avoid duplicate registration)
_request_time = Histogram(
    "viraclip_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=[.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0]
)
_request_count = Counter(
    "viraclip_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"]
)


class MetricsMiddleware:
    """
    Middleware to automatically track request metrics.
    
    Tracks:
    - Request count by endpoint
    - Request duration
    - Response status codes
    """
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        
        start_time = time.time()
        
        # Create a modified send to capture response info
        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                # Get status code from response
                status = message.get("status", 200)
                duration = time.time() - start_time
                
                # Record metrics
                method = scope.get("method", "GET")
                endpoint = scope.get("path", "/")
                
                _request_time.labels(method=method, endpoint=endpoint).observe(duration)
                _request_count.labels(method=method, endpoint=endpoint, status_code=str(status)).inc()
            
            await send(message)
        
        return await self.app(scope, receive, wrapped_send)


__all__ = [
    "router",
    "record_job_start",
    "record_job_completion",
    "record_rate_limit_hit",
    "update_gpu_metrics",
    "update_service_health",
    "MetricsMiddleware",
]
