from __future__ import annotations

import datetime
import logging
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin_auth import require_admin_user
from ...config import get_config
from ...database import get_db
from ...utils.cleanup import cleanup_old_clips, cleanup_old_downloads

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── JWT helpers ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    secret: str


def _verify_admin_jwt(request: Request) -> None:
    """Raise 401 if the request lacks a valid admin JWT."""
    cfg = get_config()
    if not cfg.admin_secret:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET not configured")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    try:
        jwt.decode(token, cfg.admin_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/login", summary="Issue a short-lived admin JWT")
async def admin_login(body: LoginRequest):
    cfg = get_config()
    if not cfg.admin_secret:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET not configured")
    if body.secret != cfg.admin_secret:
        raise HTTPException(status_code=401, detail="Invalid secret")
    payload = {
        "sub": "admin",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, cfg.admin_secret, algorithm="HS256")
    return {"token": token}


@router.get("/stats", summary="Live dashboard stats (requires admin JWT)")
async def admin_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """Returns active_workers, queued_jobs, 1h success rate, and clip rating breakdown."""
    _verify_admin_jwt(request)
    from sqlalchemy import text

    # 1h task metrics
    row = (await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status IN ('queued','processing')) AS active,
            COUNT(*) FILTER (WHERE status = 'queued')                 AS queued,
            COUNT(*) FILTER (WHERE status = 'completed'
                             AND updated_at > NOW() - INTERVAL '1 hour') AS ok_1h,
            COUNT(*) FILTER (WHERE status IN ('failed','error')
                             AND updated_at > NOW() - INTERVAL '1 hour') AS fail_1h
        FROM tasks
    """))).fetchone()

    active, queued, ok_1h, fail_1h = (row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0)
    total_1h = ok_1h + fail_1h
    success_rate = round(ok_1h / total_1h * 100, 1) if total_1h else 100.0

    # Rating breakdown
    rating_row = (await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE user_rating >= 4)  AS good,
            COUNT(*) FILTER (WHERE user_rating <= 2
                             AND user_rating IS NOT NULL) AS bad,
            COUNT(*) FILTER (WHERE user_rating IS NULL) AS unrated,
            COUNT(*) AS total
        FROM generated_clips
    """))).fetchone()
    good, bad, unrated, total_clips = (
        rating_row[0] or 0, rating_row[1] or 0,
        rating_row[2] or 0, rating_row[3] or 0,
    )
    good_pct = round(good / (good + bad) * 100, 1) if (good + bad) else 0.0

    return {
        "active_workers": active,
        "queued_jobs": queued,
        "success_rate_1h": success_rate,
        "failed_jobs_1h": fail_1h,
        "alert": fail_1h > 3 or success_rate < 60,
        "ratings": {
            "good": good, "bad": bad, "unrated": unrated,
            "total": total_clips, "good_pct": good_pct,
        },
    }

# Include AI metrics sub-router
from .ai_metrics import router as ai_metrics_router


@router.get("/health")
async def admin_health(
    request: Request, db: AsyncSession = Depends(get_db)
):
    await require_admin_user(request, db, get_config())
    return {"status": "ok"}


@router.get("/metrics")
async def get_system_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get system metrics for observability.
    
    Returns:
        - Task statistics (total, by status, error rates)
        - Performance metrics (avg render time, clip generation rate)
        - Error breakdown (top error codes)
        - Resource usage (disk space)
    """
    await require_admin_user(request, db, get_config())
    from sqlalchemy import text
    
    # Task statistics
    task_stats = await db.execute(text("""
        SELECT 
            COUNT(*) as total_tasks,
            COUNT(*) FILTER (WHERE status = 'completed') as completed,
            COUNT(*) FILTER (WHERE status = 'failed') as failed,
            COUNT(*) FILTER (WHERE status = 'processing') as processing,
            COUNT(*) FILTER (WHERE status = 'queued') as queued,
            ROUND(AVG(EXTRACT(EPOCH FROM (updated_at - created_at))), 2) as avg_duration_seconds
        FROM tasks
        WHERE created_at > NOW() - INTERVAL '7 days'
    """))
    task_row = task_stats.fetchone()
    
    # Error breakdown
    error_stats = await db.execute(text("""
        SELECT 
            error_code,
            COUNT(*) as count,
            ARRAY_AGG(DISTINCT error_message) as messages
        FROM tasks
        WHERE status = 'failed' 
        AND error_code IS NOT NULL
        AND created_at > NOW() - INTERVAL '7 days'
        GROUP BY error_code
        ORDER BY count DESC
        LIMIT 10
    """))
    error_rows = error_stats.fetchall()
    
    # Performance metrics
    perf_stats = await db.execute(text("""
        SELECT 
            COUNT(gc.id) as total_clips,
            ROUND(AVG(gc.duration), 2) as avg_clip_duration,
            COUNT(DISTINCT gc.task_id) as tasks_with_clips
        FROM generated_clips gc
        JOIN tasks t ON gc.task_id = t.id
        WHERE t.created_at > NOW() - INTERVAL '7 days'
    """))
    perf_row = perf_stats.fetchone()
    
    # Disk usage
    cfg = get_config()
    clips_dir = Path(cfg.temp_dir) / "clips"
    total_size = sum(f.stat().st_size for f in clips_dir.rglob("*") if f.is_file()) if clips_dir.exists() else 0
    
    return {
        "tasks": {
            "total": task_row[0] or 0,
            "completed": task_row[1] or 0,
            "failed": task_row[2] or 0,
            "processing": task_row[3] or 0,
            "queued": task_row[4] or 0,
            "avg_duration_seconds": task_row[5] or 0,
            "success_rate": round((task_row[1] / task_row[0] * 100) if task_row[0] > 0 else 0, 2),
        },
        "errors": [
            {
                "code": row[0],
                "count": row[1],
                "sample_messages": row[2][:3] if row[2] else []
            }
            for row in error_rows
        ],
        "performance": {
            "total_clips_generated": perf_row[0] or 0,
            "avg_clip_duration": perf_row[1] or 0,
            "tasks_with_clips": perf_row[2] or 0,
        },
        "disk": {
            "clips_dir_size_mb": round(total_size / (1024 * 1024), 2),
        },
        "period": "last_7_days"
    }


@router.get("/usage")
async def admin_usage(request: Request):
    """Get LLM and TTS usage stats with cost estimation."""
    _verify_admin_jwt(request)
    import os
    from datetime import datetime, timedelta

    env = os.getenv("APP_ENV", "production")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        import redis.asyncio as aioredis
        from ...config import get_config
        cfg = get_config()
        r = aioredis.Redis(host=cfg.redis_host, port=cfg.redis_port, password=cfg.redis_password or None, decode_responses=True)

        # Today's usage
        deepseek_today = int(await r.get(f"{env}:usage:deepseek:tokens:{today}") or 0)
        groq_today = int(await r.get(f"{env}:usage:groq:tokens:{today}") or 0)
        elevenlabs_today = int(await r.get(f"{env}:usage:elevenlabs:chars:{today}") or 0)

        # 30-day accumulated usage (parallel reads)
        import asyncio
        today_date = datetime.utcnow().date()
        deepseek_30d = 0
        groq_30d = 0
        elevenlabs_30d = 0

        async def _read_day(day_offset):
            day = (today_date - timedelta(days=day_offset)).strftime("%Y-%m-%d")
            ds = int(await r.get(f"{env}:usage:deepseek:tokens:{day}") or 0)
            gq = int(await r.get(f"{env}:usage:groq:tokens:{day}") or 0)
            el = int(await r.get(f"{env}:usage:elevenlabs:chars:{day}") or 0)
            return ds, gq, el

        results = await asyncio.gather(*[_read_day(i) for i in range(30)])
        for ds, gq, el in results:
            deepseek_30d += ds
            groq_30d += gq
            elevenlabs_30d += el

        await r.aclose()
    except Exception:
        deepseek_today = groq_today = elevenlabs_today = 0
        deepseek_30d = groq_30d = elevenlabs_30d = 0

    # Cost calculations
    deepseek_cost_today = round(deepseek_today * 0.00000027, 4)
    groq_cost_today = round(groq_today * 0.0000001, 4)
    elevenlabs_cost_today = round(elevenlabs_today * 0.00003, 4)
    deepseek_cost_30d = round(deepseek_30d * 0.00000027, 4)
    groq_cost_30d = round(groq_30d * 0.0000001, 4)
    elevenlabs_cost_30d = round(elevenlabs_30d * 0.00003, 4)

    total_today = round(deepseek_cost_today + groq_cost_today + elevenlabs_cost_today, 4)
    total_30d = round(deepseek_cost_30d + groq_cost_30d + elevenlabs_cost_30d, 4)

    if total_today > 5:
        alert = "high"
    elif total_today > 2:
        alert = "moderate"
    else:
        alert = "ok"

    return {
        "date": today,
        "deepseek": {"tokens_today": deepseek_today, "cost_today": deepseek_cost_today, "cost_30d": deepseek_cost_30d},
        "groq": {"tokens_today": groq_today, "cost_today": groq_cost_today, "cost_30d": groq_cost_30d},
        "elevenlabs": {"chars_today": elevenlabs_today, "cost_today": elevenlabs_cost_today, "cost_30d": elevenlabs_cost_30d},
        "total_cost_today": total_today,
        "total_cost_30d": total_30d,
        "alert_level": alert,
    }


@router.post("/cleanup")
async def run_cleanup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    retention_hours: float = 48.0,
):
    """
    Manually trigger disk cleanup of old clips and downloaded videos.
    Removes files older than `retention_hours` (default 48h).
    Requires admin authentication.
    """
    await require_admin_user(request, db, get_config())
    cfg = get_config()

    clips_dir = Path(cfg.temp_dir) / "clips"
    downloads_dir = Path(cfg.temp_dir) / "uploads"

    clips_deleted, clips_freed = cleanup_old_clips(clips_dir, retention_hours)
    dl_deleted, dl_freed = cleanup_old_downloads(downloads_dir, retention_hours)

    total_freed_mb = (clips_freed + dl_freed) / (1024 * 1024)
    logger.info(
        f"Admin cleanup complete: {clips_deleted + dl_deleted} files, "
        f"{total_freed_mb:.1f}MB freed"
    )
    return {
        "status": "ok",
        "clips_deleted": clips_deleted,
        "clips_freed_mb": round(clips_freed / (1024 * 1024), 2),
        "downloads_deleted": dl_deleted,
        "downloads_freed_mb": round(dl_freed / (1024 * 1024), 2),
        "total_freed_mb": round(total_freed_mb, 2),
        "retention_hours": retention_hours,
    }
