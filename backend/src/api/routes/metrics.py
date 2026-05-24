"""
Metrics API endpoints for the admin dashboard.

Provides effect timing stats, system health, and transition feedback stats.
All endpoints require admin authentication.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...config import get_config
from ...database import get_db
from ...metrics import get_all_effects_stats, TIMEOUT_THRESHOLDS
from ...feedback_store import get_transition_feedback_stats, adjust_selector_weights

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/metrics", tags=["admin"])


def _verify_admin(request: Request) -> None:
    """Verify admin authentication via JWT, session, or X-Admin-Secret header."""
    from ...admin_auth import require_admin_user
    cfg = get_config()

    # 1. X-Admin-Secret header (for frontend health dashboard)
    admin_secret = request.headers.get("X-Admin-Secret", "")
    if admin_secret and cfg.admin_secret and admin_secret == cfg.admin_secret:
        return

    # 2. Bearer JWT
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        import jwt
        token = auth[7:]
        try:
            jwt.decode(token, cfg.admin_secret, algorithms=["HS256"])
            return
        except Exception:
            pass

    raise HTTPException(status_code=401, detail="Admin authentication required")


async def _get_redis_client():
    """Get Redis client for metrics storage."""
    try:
        import redis.asyncio as aioredis
        cfg = get_config()
        r = aioredis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            password=cfg.redis_password or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # Test connection
        await r.ping()
        return r
    except Exception:
        return None


@router.get("/effects")
async def effect_metrics(request: Request):
    """
    Devuelve estadísticas de rendimiento de todos los efectos.

    Returns
    -------
    dict
        ``{"effects": {...}, "generated_at": "...", "worker_uptime_seconds": float}``
    """
    _verify_admin(request)

    effects = get_all_effects_stats()

    # Añadir slow_count a cada efecto (ya incluido en get_effect_stats)
    # Añadir threshold para referencia
    for name, stats in effects.items():
        stats["threshold_s"] = TIMEOUT_THRESHOLDS.get(name, 30.0)

    return {
        "effects": effects,
        "generated_at": datetime.utcnow().isoformat(),
        "worker_uptime_seconds": _get_worker_uptime(),
    }


@router.get("/system")
async def system_metrics(request: Request):
    """
    Estado global del sistema.

    Returns
    -------
    dict
        ``{"redis", "sam", "render3d", "worker"}``
    """
    _verify_admin(request)

    redis_client = await _get_redis_client()

    # Redis status
    redis_status = {"connected": False, "queue_length": 0}
    if redis_client:
        try:
            await redis_client.ping()
            redis_status["connected"] = True
            queue_len = await redis_client.zcard("arq:queue:viraclip_cpu_tasks")
            redis_status["queue_length"] = queue_len or 0
        except Exception:
            pass
        finally:
            try:
                await redis_client.aclose()
            except Exception:
                pass

    # SAM status
    sam_status = {"available": False, "model_type": None}
    try:
        from ...sam_singleton import is_sam_available, get_sam_model_type
        sam_status["available"] = is_sam_available()
        sam_status["model_type"] = get_sam_model_type()
    except Exception:
        pass

    # render3d status
    render3d_status = {"available": False, "gpu": False}
    try:
        import httpx
        cfg = get_config()
        render3d_url = getattr(cfg, "render3d_url", "http://render3d:7890")
        resp = httpx.get(f"{render3d_url}/health", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            render3d_status["available"] = True
            render3d_status["gpu"] = data.get("gpu_available", False)
    except Exception:
        pass

    # Worker status
    worker_status = {"last_heartbeat": None, "tasks_processed_today": 0}
    try:
        import asyncpg
        cfg = get_config()
        db_url = cfg.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as cnt
                FROM tasks
                WHERE status = 'completed'
                  AND updated_at > NOW() - INTERVAL '1 day'
            """)
            worker_status["tasks_processed_today"] = row["cnt"] if row else 0
        finally:
            await conn.close()
    except Exception:
        pass

    return {
        "redis": redis_status,
        "sam": sam_status,
        "render3d": render3d_status,
        "worker": worker_status,
    }


@router.get("/effects/feedback")
async def effect_feedback(request: Request):
    """
    Devuelve estadísticas de feedback del selector de transiciones.

    Returns
    -------
    dict
        Estadísticas de feedback + recomendaciones de ajuste.
    """
    _verify_admin(request)

    redis_client = await _get_redis_client()
    try:
        feedback_stats = await get_transition_feedback_stats(redis_client)

        # Generar recomendaciones
        scores = {
            "match_cut": 0.65,
            "glitch": 0.50,
            "sweep_mask": 0.55,
            "mask_reveal": 0.50,
            "shape_morph": 0.40,
        }
        recommendations = adjust_selector_weights(scores, feedback_stats)

        return {
            **feedback_stats,
            "recommendations": recommendations.get("recommendations", []),
        }
    finally:
        if redis_client:
            try:
                await redis_client.aclose()
            except Exception:
                pass


def _get_worker_uptime() -> float:
    """Estima el uptime del worker basado en el tiempo de ejecución del proceso."""
    try:
        import os
        import psutil
        process = psutil.Process(os.getpid())
        create_time = process.create_time()
        return time.time() - create_time
    except Exception:
        return 0.0
