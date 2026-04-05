"""
Analytics Dashboard API Routes

Provides endpoints for system metrics, task statistics, and health monitoring.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...services.analytics_service import get_analytics_service, AnalyticsService
from ...auth_headers import get_signed_user_id

router = APIRouter(prefix="/analytics", tags=["Analytics Dashboard"])


@router.get("/metrics", response_model=None)
async def get_metrics(
    days: int = Query(30, ge=1, le=365),
    user_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_signed_user_id)
):
    """Get task processing metrics.
    
    - **days**: Number of days to look back (1-365)
    - **user_id**: Filter by specific user (admin only, otherwise uses current user)
    """
    # Non-admin users can only see their own metrics
    effective_user_id = user_id if user_id and await _is_admin(current_user) else current_user
    
    service = await get_analytics_service(db)
    metrics = await service.get_task_metrics(user_id=effective_user_id, days=days)
    
    return {
        "period_days": days,
        "user_id": effective_user_id,
        "total_tasks": metrics.total_tasks,
        "completed": metrics.completed,
        "failed": metrics.failed,
        "pending": metrics.pending,
        "processing": metrics.processing,
        "success_rate": round(metrics.completed / metrics.total_tasks * 100, 2) if metrics.total_tasks > 0 else 0,
        "avg_processing_time_seconds": round(metrics.avg_processing_time, 2),
        "total_clips_generated": metrics.total_clips
    }


@router.get("/daily", response_model=None)
async def get_daily_stats(
    days: int = Query(7, ge=1, le=30),
    user_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_signed_user_id)
):
    """Get daily statistics for the last N days."""
    effective_user_id = user_id if user_id and await _is_admin(current_user) else current_user
    
    service = await get_analytics_service(db)
    stats = await service.get_daily_stats(user_id=effective_user_id, days=days)
    
    return {
        "period_days": days,
        "user_id": effective_user_id,
        "daily_stats": [
            {
                "date": s.date,
                "tasks_created": s.tasks_created,
                "tasks_completed": s.tasks_completed,
                "tasks_failed": s.tasks_failed,
                "clips_generated": s.clips_generated,
                "avg_processing_time_seconds": round(s.avg_processing_time, 2)
            }
            for s in stats
        ]
    }


@router.get("/health", response_model=None)
async def get_system_health(
    db: AsyncSession = Depends(get_db)
):
    """Get current system health status (public endpoint)."""
    service = await get_analytics_service(db)
    health = await service.get_system_health()
    
    return {
        "status": health.status,
        "queue_depth": health.queue_depth,
        "active_workers": health.worker_count,
        "active_tasks": health.active_tasks,
        "error_rate_1h": round(health.error_rate_1h * 100, 2),
        "avg_latency_ms": round(health.avg_latency_ms, 2),
        "timestamp": health.timestamp if hasattr(health, 'timestamp') else None
    }


@router.get("/sources", response_model=None)
async def get_popular_sources(
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_signed_user_id)
):
    """Get most popular video sources (admin only)."""
    if not await _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = await get_analytics_service(db)
    sources = await service.get_popular_sources(limit=limit, days=days)
    
    return {
        "period_days": days,
        "sources": sources
    }


@router.get("/virality", response_model=None)
async def get_virality_distribution(
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db)
):
    """Get distribution of virality scores."""
    service = await get_analytics_service(db)
    distribution = await service.get_virality_distribution(days=days)
    
    total = sum(distribution.values())
    
    return {
        "period_days": days,
        "total_clips": total,
        "distribution": distribution,
        "percentages": {
            k: round(v / total * 100, 2) if total > 0 else 0
            for k, v in distribution.items()
        }
    }


@router.get("/summary", response_model=None)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_signed_user_id)
):
    """Get complete dashboard summary for the current user."""
    service = await get_analytics_service(db)
    
    # Get all metrics
    metrics = await service.get_task_metrics(user_id=current_user, days=30)
    daily = await service.get_daily_stats(user_id=current_user, days=7)
    
    # Calculate trends
    if len(daily) >= 2:
        recent = daily[-1].tasks_completed
        previous = daily[-2].tasks_completed if len(daily) > 1 else 0
        trend = "up" if recent > previous else "down" if recent < previous else "stable"
    else:
        trend = "stable"
    
    return {
        "user_id": current_user,
        "generated_at": "2024-01-01T00:00:00Z",  # Will be set by caller
        "summary": {
            "total_tasks_30d": metrics.total_tasks,
            "completed_tasks_30d": metrics.completed,
            "failed_tasks_30d": metrics.failed,
            "success_rate": round(metrics.completed / metrics.total_tasks * 100, 2) if metrics.total_tasks > 0 else 0,
            "total_clips": metrics.total_clips,
            "avg_processing_time": round(metrics.avg_processing_time, 2),
            "trend": trend
        },
        "recent_daily": [
            {
                "date": d.date,
                "tasks": d.tasks_completed,
                "clips": d.clips_generated
            }
            for d in daily[-7:]
        ]
    }


async def _is_admin(user_id: str) -> bool:
    """Check if user is admin (placeholder - implement proper admin check)."""
    # TODO: Implement proper admin check against DB or config
    return user_id.startswith("admin_") or user_id == "system"
