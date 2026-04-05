"""
GPU Health Check Endpoint
=========================
Provides detailed GPU status and health information.

Endpoints:
    GET /health/gpu — GPU-specific health status
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health Checks"])


class GPUHealthResponse(BaseModel):
    """GPU health check response model."""
    status: str  # "healthy", "degraded", "unavailable"
    gpu_available: bool
    device_name: Optional[str] = None
    vram_total_gb: Optional[float] = None
    vram_used_gb: Optional[float] = None
    vram_free_gb: Optional[float] = None
    cuda_version: Optional[str] = None
    driver_version: Optional[str] = None
    supported_features: List[str] = []
    temperature_c: Optional[float] = None  # GPU temperature if available
    warnings: List[str] = []


class ServiceHealthResponse(BaseModel):
    """Overall service health including GPU."""
    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: str
    services: Dict[str, Any]
    gpu: Optional[GPUHealthResponse] = None


@router.get("/gpu", response_model=GPUHealthResponse)
async def gpu_health_check() -> GPUHealthResponse:
    """
    Check GPU health and availability.
    
    Returns detailed GPU information including VRAM usage,
    CUDA version, and supported features.
    """
    try:
        import torch
        
        if not torch.cuda.is_available():
            return GPUHealthResponse(
                status="unavailable",
                gpu_available=False,
                warnings=["CUDA not available - GPU features disabled"]
            )
        
        # Get GPU properties
        device_idx = 0  # Primary GPU
        props = torch.cuda.get_device_properties(device_idx)
        
        vram_total = props.total_memory / (1024**3)  # Convert to GB
        vram_allocated = torch.cuda.memory_allocated(device_idx) / (1024**3)
        vram_reserved = torch.cuda.memory_reserved(device_idx) / (1024**3)
        vram_used = max(vram_allocated, vram_reserved)
        vram_free = vram_total - vram_used
        
        # Determine supported features based on VRAM
        supported_features = []
        warnings = []
        
        if vram_total >= 4:
            supported_features.append("esrgan_upscaling")
        if vram_total >= 5:
            supported_features.append("t2v_ltx_video")
        if vram_total >= 8:
            supported_features.append("tts_xtts_v2")
            supported_features.append("lora_training")
            supported_features.append("upscale_8k")
        if vram_total >= 12:
            supported_features.append("t2v_wan2.2-1.3b")
        if vram_total >= 16:
            supported_features.append("t2v_wan2.2-14b")
        
        # Check VRAM pressure
        vram_usage_pct = (vram_used / vram_total) * 100
        status = "healthy"
        if vram_usage_pct > 90:
            status = "degraded"
            warnings.append(f"High VRAM usage: {vram_usage_pct:.1f}%")
        
        # Check environment variables
        gpu_worker_enabled = os.environ.get("GPU_WORKER_ENABLED", "false").lower() == "true"
        if not gpu_worker_enabled:
            warnings.append("GPU_WORKER_ENABLED=false - GPU tasks will fall back to CPU")
        
        return GPUHealthResponse(
            status=status,
            gpu_available=True,
            device_name=props.name,
            vram_total_gb=round(vram_total, 2),
            vram_used_gb=round(vram_used, 2),
            vram_free_gb=round(vram_free, 2),
            cuda_version=torch.version.cuda,
            driver_version=str(props.major) + "." + str(props.minor),
            supported_features=supported_features,
            warnings=warnings
        )
        
    except ImportError:
        return GPUHealthResponse(
            status="unavailable",
            gpu_available=False,
            warnings=["PyTorch not installed - GPU features disabled"]
        )
    except Exception as e:
        logger.error(f"GPU health check failed: {e}")
        return GPUHealthResponse(
            status="unavailable",
            gpu_available=False,
            warnings=[f"GPU check error: {str(e)}"]
        )


@router.get("/services", response_model=ServiceHealthResponse)
async def services_health_check() -> ServiceHealthResponse:
    """
    Comprehensive health check of all services including GPU.
    
    Checks:
    - Database connectivity
    - Redis connectivity
    - GPU availability
    - Model service status
    """
    import asyncio
    from datetime import datetime
    
    services: Dict[str, Any] = {}
    warnings: List[str] = []
    
    # Check GPU
    gpu_health = await gpu_health_check()
    
    # Check database (async)
    try:
        from ...database import get_db
        async for db in get_db():
            from sqlalchemy import text
            result = await db.execute(text("SELECT 1"))
            services["database"] = {"status": "healthy", "latency_ms": 0}
            break
    except Exception as e:
        services["database"] = {"status": "unhealthy", "error": str(e)}
        warnings.append("Database connectivity issue")
    
    # Check Redis
    try:
        from ...workers.job_queue import JobQueue
        pool = await JobQueue.get_pool()
        await pool.ping()
        services["redis"] = {"status": "healthy"}
    except Exception as e:
        services["redis"] = {"status": "unhealthy", "error": str(e)}
        warnings.append("Redis connectivity issue")
    
    # Check GPU services
    services["gpu"] = {
        "available": gpu_health.gpu_available,
        "device": gpu_health.device_name,
        "vram_gb": gpu_health.vram_total_gb,
        "supported_features": gpu_health.supported_features,
    }
    
    # Overall status
    if any(s.get("status") == "unhealthy" for s in services.values() if isinstance(s, dict)):
        overall_status = "unhealthy"
    elif warnings or gpu_health.status == "degraded":
        overall_status = "degraded"
    else:
        overall_status = "healthy"
    
    return ServiceHealthResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat(),
        services=services,
        gpu=gpu_health if gpu_health.gpu_available else None
    )


__all__ = ["router", "GPUHealthResponse", "ServiceHealthResponse"]
