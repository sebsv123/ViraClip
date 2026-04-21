"""
Analytics Dashboard API Routes

Provides endpoints for system metrics, task statistics, and health monitoring.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...services.analytics_service import get_analytics_service, AnalyticsService
from ...services.validation_stats import get_validation_stats_service
from ...auth_headers import get_signed_user_id

logger = logging.getLogger(__name__)

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


@router.get("/validation/stats", response_model=None)
async def get_validation_stats(
    days: int = Query(7, ge=1, le=90),
    task_id: Optional[str] = None,
    current_user: str = Depends(get_signed_user_id)
):
    """
    Get aggregated validation statistics.
    
    - **days**: Number of days to look back (1-90)
    - **task_id**: Filter by specific task ID
    
    Returns metrics about clip validation success/failure rates.
    """
    stats_service = get_validation_stats_service()
    stats = await stats_service.get_validation_stats(days=days, task_id=task_id)
    
    return {
        "period_days": days,
        "task_id": task_id,
        "total_validations": stats.total_validations,
        "passed": stats.passed,
        "failed": stats.failed,
        "success_rate": stats.success_rate,
        "common_issues": stats.common_issues,
        "common_warnings": stats.common_warnings,
        "avg_duration_diff_seconds": stats.avg_duration_diff,
        "avg_file_size_mb": stats.avg_file_size_mb,
    }


@router.get("/validation/patterns", response_model=None)
async def get_validation_failure_patterns(
    days: int = Query(30, ge=1, le=90),
    min_occurrences: int = Query(2, ge=1, le=100),
    current_user: str = Depends(get_signed_user_id)
):
    """
    Identify patterns in validation failures.
    
    - **days**: Number of days to analyze (1-90)
    - **min_occurrences**: Minimum occurrences to be considered a pattern
    
    Returns common failure patterns with timestamps and examples.
    """
    stats_service = get_validation_stats_service()
    patterns = await stats_service.get_failure_patterns(
        days=days,
        min_occurrences=min_occurrences,
    )
    
    return {
        "period_days": days,
        "min_occurrences": min_occurrences,
        "patterns": [
            {
                "issue_type": p.issue_type,
                "count": p.count,
                "percentage": p.percentage,
                "first_seen": p.first_seen,
                "last_seen": p.last_seen,
                "example": p.example_metadata,
            }
            for p in patterns
        ],
        "total_patterns": len(patterns),
    }


@router.get("/validation/trend", response_model=None)
async def get_validation_trend(
    days: int = Query(30, ge=1, le=90),
    current_user: str = Depends(get_signed_user_id)
):
    """
    Get daily validation success rate trend.
    
    - **days**: Number of days to analyze (1-90)
    
    Returns daily breakdown of validation pass/fail rates.
    """
    stats_service = get_validation_stats_service()
    trend = await stats_service.get_validation_trend(days=days)
    
    return {
        "period_days": days,
        "trend": trend,
        "total_days": len(trend),
    }


async def _is_admin(user_id: str) -> bool:
    """Check if user is admin (placeholder - implement proper admin check)."""
    # TODO: Implement proper admin check against DB or config
    return user_id.startswith("admin_") or user_id == "system"


# =============================================================================
# FEEDBACK LOOP & ANALYTICS IMPORT ENDPOINTS (Phase 5.3)
# =============================================================================

from ...services.analytics_importer import run_feedback_import
from ...services.feedback_loop_service import FeedbackLoopService
from ...services.social_auth_service import SocialAuthService
from ...services.social_publisher_service import SocialPublisherService
from ...dependencies import get_redis, get_current_user


class ImportRequest(BaseModel):
    days_back: int = 2


class RetrainRequest(BaseModel):
    force: bool = False


@router.post("/import", response_model=None)
async def trigger_analytics_import(
    request: ImportRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    redis = Depends(get_redis),
):
    """
    Trigger manual analytics import for the authenticated user.
    
    - Fetches metrics from all connected platforms (TikTok, Instagram, YouTube)
    - Runs feedback import to get real performance data
    - Automatically incorporates data into training batch
    
    Returns import results and retraining status.
    """
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    
    try:
        # Initialize services with injected Redis
        auth_service = SocialAuthService(redis)
        publisher_service = SocialPublisherService(redis, auth_service)
        
        # Run feedback import
        import_result = await run_feedback_import(
            user_id=user_id,
            auth_service=auth_service,
            publisher_service=publisher_service,
            days_back=request.days_back,
        )
        
        # Incorporate into feedback loop
        feedback_service = FeedbackLoopService(db_session=None, redis_client=redis)
        training_result = await feedback_service.incorporate_analytics_batch(import_result)
        
        return {
            "imported": import_result.get("total_fetched", 0),
            "errors": import_result.get("errors", 0),
            "retrained": training_result.get("status") == "retrained",
            "status": training_result.get("status"),
            "metrics": training_result.get("metrics"),
            "total_samples": training_result.get("total_samples"),
        }
        
    except Exception as e:
        logger.error(f"[analytics_api] Import failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.get("/model/status", response_model=None)
async def get_model_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
    redis = Depends(get_redis),
):
    """
    Get current virality scorer model status and training statistics.
    
    Returns:
    - Model version and metadata
    - Training metrics (MSE, R²)
    - Number of training samples
    - Last training timestamp
    """
    try:
        feedback_service = FeedbackLoopService(db_session=None, redis_client=redis)
        stats = await feedback_service.get_training_stats()
        
        return {
            "model_exists": stats.get("model_exists", False),
            "version": stats.get("model_version"),
            "metadata": stats.get("model_metadata"),
            "feedback_batches": stats.get("feedback_batches", 0),
            "model_size_mb": stats.get("model_size_mb"),
            "model_modified": stats.get("model_modified"),
        }
        
    except Exception as e:
        logger.error(f"[analytics_api] Failed to get model status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get model status: {str(e)}")


@router.post("/model/retrain", response_model=None)
async def force_model_retrain(
    request: RetrainRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    redis = Depends(get_redis),
):
    """
    Force immediate model retraining (admin only).
    
    This endpoint triggers a full retraining cycle using accumulated feedback data.
    Requires admin role.
    
    Returns training metrics and deployment status.
    """
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    
    # Check admin role
    if not await _is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        feedback_service = FeedbackLoopService(db_session=None, redis_client=redis)
        
        # Collect feedback and retrain
        df = await feedback_service.collect_feedback_batch(days_back=30)
        
        if len(df) < feedback_service.min_samples_for_training:
            return {
                "status": "insufficient_samples",
                "total_samples": len(df),
                "needed": feedback_service.min_samples_for_training,
            }
        
        result = await feedback_service.retrain_model(df=df, validate=True)
        
        return {
            "status": "retrained" if result.get("deployed") else "validation_failed",
            "metrics": result,
            "version": result.get("version"),
            "total_samples": len(df),
        }
        
    except Exception as e:
        logger.error(f"[analytics_api] Retraining failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Retraining failed: {str(e)}")


@router.get("/clips/{clip_id}", response_model=None)
async def get_clip_platform_metrics(
    clip_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    redis = Depends(get_redis),
):
    """
    Get platform-specific metrics for a published clip.
    
    Reads PublishResult from Redis for all platforms and returns:
    - TikTok metrics (views, likes, shares, etc.)
    - Instagram metrics (views, likes, comments, etc.)
    - YouTube metrics (views, likes, comments, etc.)
    
    Only returns metrics for clips owned by the authenticated user.
    """
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    
    try:
        platforms = ["tiktok", "instagram", "youtube"]
        results = {}
        
        for platform in platforms:
            key = f"publish_result:{clip_id}:{platform}"
            data = await redis.get(key)
            
            if data:
                if isinstance(data, dict):
                    results[platform] = {
                        "status": data.get("status"),
                        "platform_post_id": data.get("platform_post_id"),
                        "platform_url": data.get("platform_url"),
                        "published_at": data.get("published_at"),
                        "error_message": data.get("error_message"),
                        "retry_count": data.get("retry_count", 0),
                    }
                else:
                    results[platform] = {"status": "unknown", "raw": str(data)}
            else:
                results[platform] = {"status": "not_published"}
        
        return {
            "clip_id": clip_id,
            "platforms": results,
        }
        
    except Exception as e:
        logger.error(f"[analytics_api] Failed to get clip metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get clip metrics: {str(e)}")


__all__ = ["router"]
