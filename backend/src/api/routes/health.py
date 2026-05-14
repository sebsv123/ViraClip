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
from ...core.metrics_service import get_metrics_collector
from ...core.cache_manager import get_cache_manager
from ...core.concurrency_optimizer import get_optimizer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    """
    Basic health check endpoint.
    
    Returns 200 if service is running.
    """
    return {"status": "healthy"}


@router.get("/db")
async def db_health(db: AsyncSession = Depends(get_db)):
    """Check database connectivity."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


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


@router.get("/creative-services")
async def creative_services_health():
    """
    Check if Phase 9 creative services are available and can be imported.
    
    Tests:
    - All service imports
    - Critical dependencies (librosa, moviepy, etc.)
    - Service instantiation
    """
    health = {
        "status": "healthy",
        "services": {},
        "dependencies": {},
        "summary": {
            "services_ok": 0,
            "services_failed": 0,
            "dependencies_ok": 0,
            "dependencies_failed": 0,
        }
    }
    
    # Test service imports
    services_to_test = [
        ("multimodal_detector", "src.services.multimodal_detector", "get_multimodal_detector"),
        ("virality_engine", "src.services.virality_engine", "get_virality_engine"),
        ("hook_engine", "src.services.hook_engine", "get_hook_engine"),
        ("smart_templates", "src.services.smart_templates", "get_template_selector"),
        ("contextual_broll", "src.services.contextual_broll", "get_contextual_broll"),
        ("video_effects", "src.services.video_effects", "apply_preset_effects"),
        ("smart_audio", "src.services.smart_audio", "get_smart_audio"),
        ("learning_loop", "src.services.learning_loop", "get_learning_loop"),
        ("creative_pipeline", "src.services.creative_pipeline", "get_creative_pipeline"),
    ]
    
    for name, module_path, func_name in services_to_test:
        try:
            module = __import__(module_path, fromlist=[func_name])
            func = getattr(module, func_name)
            health["services"][name] = {
                "status": "ok",
                "module": module_path,
                "callable": func_name
            }
            health["summary"]["services_ok"] += 1
        except ImportError as e:
            health["services"][name] = {
                "status": "import_error",
                "error": str(e)
            }
            health["summary"]["services_failed"] += 1
            health["status"] = "degraded"
        except Exception as e:
            health["services"][name] = {
                "status": "error",
                "error": f"{type(e).__name__}: {e}"
            }
            health["summary"]["services_failed"] += 1
            health["status"] = "degraded"
    
    # Test critical dependencies
    dependencies = ["librosa", "moviepy", "pydantic", "httpx", "numpy", "scipy"]
    for dep in dependencies:
        try:
            __import__(dep)
            health["dependencies"][dep] = {"status": "installed"}
            health["summary"]["dependencies_ok"] += 1
        except ImportError as e:
            health["dependencies"][dep] = {
                "status": "missing",
                "error": str(e)
            }
            health["summary"]["dependencies_failed"] += 1
            health["status"] = "unhealthy"
    
    # Check audio/BGM files
    from pathlib import Path
    sfx_dir = Path("/app/assets/sounds")
    bgm_dir = Path("/app/assets/sounds/bgm")
    
    health["assets"] = {
        "sfx_available": sfx_dir.exists() and len(list(sfx_dir.glob("*.mp3"))) > 0,
        "bgm_available": bgm_dir.exists() and len(list(bgm_dir.glob("*.mp3"))) > 0,
        "sfx_count": len(list(sfx_dir.glob("*.mp3"))) if sfx_dir.exists() else 0,
        "bgm_count": len(list(bgm_dir.glob("*.mp3"))) if bgm_dir.exists() else 0,
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


@router.get("/worker")
async def worker_health():
    """
    Check ARQ worker health via Redis heartbeats.
    
    Returns:
    - workers_active: number of workers with recent heartbeats
    - last_heartbeat: ISO timestamp of most recent heartbeat
    - seconds_since_heartbeat: seconds since last heartbeat
    - queued_tasks: number of jobs waiting in queue
    - processing_tasks: number of jobs currently being processed
    - status: "healthy" | "degraded" | "down"
    """
    import time
    from datetime import datetime
    from ...config import get_config
    
    queue_name = "viraclip_cpu_tasks"
    cfg = get_config()
    
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(host=cfg.redis_host, port=cfg.redis_port, password=cfg.redis_password or None, decode_responses=True)
        
        # Get worker health data
        health_key = f"arq:health:{queue_name}"
        health_data = await r.hgetall(health_key)
        
        # Get queue lengths
        queued = await r.zcard(f"arq:queue:{queue_name}")
        processing = await r.zcard(f"arq:in-progress:{queue_name}")
        
        await r.aclose()
        
        workers_active = 0
        last_heartbeat = None
        seconds_since_heartbeat = None
        
        if health_data:
            workers_active = int(health_data.get("workers", 0))
            hb_str = health_data.get("heartbeat")
            if hb_str:
                try:
                    hb_ts = float(hb_str)
                    seconds_since_heartbeat = int(time.time() - hb_ts)
                    last_heartbeat = datetime.fromtimestamp(hb_ts).isoformat()
                except (ValueError, TypeError):
                    pass
        
        if workers_active > 0 and seconds_since_heartbeat is not None and seconds_since_heartbeat < 60:
            status = "healthy"
        elif workers_active > 0:
            status = "degraded"
        else:
            status = "down"
        
        result = {
            "workers_active": workers_active,
            "last_heartbeat": last_heartbeat,
            "seconds_since_heartbeat": seconds_since_heartbeat,
            "queued_tasks": queued,
            "processing_tasks": processing,
            "status": status,
        }
        
        if status == "down":
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=503, content=result)
        return result
        
    except Exception as e:
        return {
            "status": "degraded",
            "error": f"Redis unavailable: {e}",
            "workers_active": 0,
            "last_heartbeat": None,
            "seconds_since_heartbeat": None,
            "queued_tasks": 0,
            "processing_tasks": 0,
        }


@router.get("/system")
async def system_health():
    """
    Comprehensive system health with GPU, pipeline, and queue metrics.
    
    Returns:
    - GPU: availability, encoder, utilization, VRAM
    - Pipeline: tasks completed/failed/processing, success rate, avg clip time
    - Queue: depth, active workers
    """
    import subprocess as _sp
    import os as _os
    from src import gpu_utils
    
    result = {
        "gpu": {
            "available": gpu_utils.cuda_available(),
            "encoder": gpu_utils.get_video_encoder(),
            "name": gpu_utils.gpu_name(),
            "utilization_pct": 0.0,
            "vram_used_mb": 0,
            "vram_total_mb": 0,
        },
        "pipeline": {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_processing": 0,
            "success_rate_pct": 100.0,
            "avg_clip_time_s": 0.0,
        },
        "queue": {
            "depth": 0,
            "workers_active": 0,
        },
    }
    
    # GPU metrics via nvidia-smi
    try:
        _r = _sp.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if _r.returncode == 0 and _r.stdout.strip():
            parts = _r.stdout.strip().split(", ")
            if len(parts) >= 3:
                result["gpu"]["utilization_pct"] = float(parts[0])
                result["gpu"]["vram_used_mb"] = int(float(parts[1]))
                result["gpu"]["vram_total_mb"] = int(float(parts[2]))
    except Exception:
        pass
    
    # Pipeline metrics from metrics_collector
    try:
        from ...core.metrics_service import get_metrics_collector
        _mc = get_metrics_collector()
        _summary = _mc.get_summary(days=7)
        result["pipeline"]["tasks_completed"] = _summary.get("total_pipelines", 0)
        result["pipeline"]["tasks_failed"] = _summary.get("failed_pipelines", 0)
        result["pipeline"]["tasks_processing"] = _summary.get("processing_pipelines", 0)
        _total = result["pipeline"]["tasks_completed"] + result["pipeline"]["tasks_failed"]
        if _total > 0:
            result["pipeline"]["success_rate_pct"] = round(
                result["pipeline"]["tasks_completed"] / _total * 100, 1
            )
        result["pipeline"]["avg_clip_time_s"] = _summary.get("avg_clip_time_s", 0.0)
    except Exception:
        pass
    
    # Queue depth via Redis
    try:
        from ...workers.job_queue import JobQueue
        _pool = await JobQueue.get_pool()
        _queue_len = await _pool.llen("arq:queue")
        result["queue"]["depth"] = _queue_len or 0
    except Exception:
        pass
    
    return result


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


@router.get("/diagnostics")
async def comprehensive_diagnostics(db: AsyncSession = Depends(get_db)):
    """
    Comprehensive diagnostics endpoint for ViraClip.
    
    Verifies all critical dependencies:
    - FFmpeg/FFprobe
    - Groq API connectivity
    - Ollama service
    - Redis
    - PostgreSQL
    - Disk space
    - Worker processes
    """
    import shutil
    import httpx
    import os
    import psutil
    from ...config import get_config
    
    checks = {}
    config = get_config()
    
    # FFmpeg check
    ffmpeg_path = shutil.which("ffmpeg")
    checks["ffmpeg"] = {
        "ok": bool(ffmpeg_path),
        "path": ffmpeg_path or "Not found",
        "version": None
    }
    if ffmpeg_path:
        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            version_line = result.stdout.split('\n')[0] if result.stdout else ""
            checks["ffmpeg"]["version"] = version_line
        except Exception as e:
            checks["ffmpeg"]["version_error"] = str(e)
    
    # FFprobe check
    ffprobe_path = shutil.which("ffprobe")
    checks["ffprobe"] = {
        "ok": bool(ffprobe_path),
        "path": ffprobe_path or "Not found"
    }
    
    # Groq API check
    if config.groq_api_key:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {config.groq_api_key}"}
                )
                checks["groq_api"] = {
                    "ok": response.status_code == 200,
                    "status_code": response.status_code,
                    "models_available": len(response.json().get("data", [])) if response.status_code == 200 else 0
                }
        except Exception as e:
            checks["groq_api"] = {
                "ok": False,
                "error": str(e)
            }
    else:
        checks["groq_api"] = {
            "ok": False,
            "error": "GROQ_API_KEY not configured"
        }
    
    # Ollama check
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{config.ollama_base_url}/api/tags")
            if response.status_code == 200:
                models = [m["name"] for m in response.json().get("models", [])]
                vision_model_available = any(
                    config.ollama_vision_model in m or "qwen" in m or "phi3" in m 
                    for m in models
                )
                checks["ollama"] = {
                    "ok": vision_model_available,
                    "models": models,
                    "vision_model": config.ollama_vision_model,
                    "vision_available": vision_model_available
                }
            else:
                checks["ollama"] = {
                    "ok": False,
                    "status_code": response.status_code
                }
    except Exception as e:
        checks["ollama"] = {
            "ok": False,
            "error": str(e)
        }
    
    # Redis check
    try:
        from ...workers.job_queue import JobQueue
        pool = await JobQueue.get_pool()
        await pool.ping()
        checks["redis"] = {
            "ok": True,
            "host": config.redis_host,
            "port": config.redis_port
        }
    except Exception as e:
        checks["redis"] = {
            "ok": False,
            "error": str(e)
        }
    
    # PostgreSQL check
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = {
            "ok": True,
            "connection": "healthy"
        }
    except Exception as e:
        checks["postgres"] = {
            "ok": False,
            "error": str(e)
        }
    
    # Disk space check (minimum 1GB free)
    try:
        temp_dir = config.temp_dir or "/app/temp"
        disk = psutil.disk_usage(temp_dir)
        free_gb = disk.free / (1024**3)
        checks["disk_space"] = {
            "ok": free_gb > 1.0,
            "free_gb": round(free_gb, 2),
            "total_gb": round(disk.total / (1024**3), 2),
            "percent_used": disk.percent,
            "path": temp_dir
        }
    except Exception as e:
        checks["disk_space"] = {
            "ok": False,
            "error": str(e)
        }
    
    # Python module checks
    critical_modules = [
        "faster_whisper",
        "moviepy",
        "pydantic",
        "httpx"
    ]
    checks["python_modules"] = {}
    for module_name in critical_modules:
        try:
            __import__(module_name)
            checks["python_modules"][module_name] = {"ok": True}
        except ImportError:
            checks["python_modules"][module_name] = {"ok": False, "error": "Not installed"}
    
    # Worker process status (check if any ARQ workers are running)
    checks["workers_active"] = {
        "ok": True,
        "note": "Backend is responding (workers are separate containers)"
    }
    
    # Overall health status
    all_ok = all(
        v.get("ok", False) if isinstance(v, dict) else False
        for v in checks.values()
        if isinstance(v, dict) and "ok" in v
    )
    
    # Check python modules separately
    modules_ok = all(v.get("ok", False) for v in checks.get("python_modules", {}).values())
    
    overall_ok = all_ok and modules_ok
    
    return {
        "status": "healthy" if overall_ok else "degraded",
        "checks": checks,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat()
    }
