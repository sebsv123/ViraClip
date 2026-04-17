"""
Timeline API endpoints - monitoring, metrics, and timeline access.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pathlib import Path

from ...project_store import ProjectStore
from ...schemas_v2 import ClipTimeline
from ...services.timeline_metrics import get_metrics_collector

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("/metrics/aggregate")
async def get_aggregate_metrics():
    """
    Get aggregate timeline building metrics.
    
    Returns:
        - total_timelines: Total number of timelines built
        - successful_timelines: Successfully completed
        - failed_timelines: Failed builds
        - success_rate: Percentage of successful builds
        - avg_total_duration: Average total build time
        - avg_vision_ai_duration: Average Vision AI time
        - total_frames_extracted: Total frames processed
        - total_vision_api_calls: Total Vision AI API calls
        - vision_error_rate: Vision AI error percentage
    """
    collector = get_metrics_collector()
    stats = collector.get_aggregate_stats()
    return {
        "status": "success",
        "metrics": stats
    }


@router.get("/metrics/recent")
async def get_recent_metrics(limit: int = Query(default=10, ge=1, le=100)):
    """
    Get recent timeline building metrics.
    
    Args:
        limit: Number of recent metrics to return (1-100)
    
    Returns:
        List of recent timeline metrics with timing breakdown
    """
    collector = get_metrics_collector()
    recent = collector.get_recent_metrics(limit=limit)
    return {
        "status": "success",
        "count": len(recent),
        "metrics": recent
    }


@router.get("/metrics/{task_id}")
async def get_task_metrics(task_id: str):
    """
    Get timeline metrics for a specific task.
    
    Args:
        task_id: Task identifier
    
    Returns:
        Detailed metrics for the task's timeline building
    """
    collector = get_metrics_collector()
    metrics = collector.get_metrics(task_id)
    
    if not metrics:
        raise HTTPException(
            status_code=404,
            detail=f"No timeline metrics found for task {task_id}"
        )
    
    return {
        "status": "success",
        "metrics": metrics.to_dict()
    }


@router.get("/{task_id}")
async def get_timeline(task_id: str):
    """
    Get the ClipTimeline for a specific task.
    
    Args:
        task_id: Task identifier
    
    Returns:
        Full ClipTimeline structure with segments, texts, assets
    """
    store = ProjectStore()
    
    timeline_data = store.load_json(task_id, "timeline.json")
    
    if not timeline_data:
        raise HTTPException(
            status_code=404,
            detail=f"Timeline not found for task {task_id}. Enable timeline building with config.enable_timeline=true"
        )
    
    return {
        "status": "success",
        "timeline": timeline_data
    }


@router.get("/{task_id}/segments")
async def get_timeline_segments(task_id: str):
    """
    Get segments from a task's timeline.
    
    Args:
        task_id: Task identifier
    
    Returns:
        List of segments with virality scores, camera movements, etc.
    """
    store = ProjectStore()
    timeline_data = store.load_json(task_id, "timeline.json")
    
    if not timeline_data:
        raise HTTPException(
            status_code=404,
            detail=f"Timeline not found for task {task_id}"
        )
    
    segments = timeline_data.get("segments", [])
    
    return {
        "status": "success",
        "task_id": task_id,
        "segment_count": len(segments),
        "segments": segments
    }


@router.get("/{task_id}/analysis")
async def get_timeline_analysis(task_id: str):
    """
    Get Vision AI analysis data for a task's timeline.
    
    Args:
        task_id: Task identifier
    
    Returns:
        Frame descriptions and placements if Vision AI was enabled
    """
    store = ProjectStore()
    
    descriptions = store.load_json(task_id, "descriptions.json", folder="analysis")
    placements = store.load_json(task_id, "placements.json", folder="analysis")
    
    if not descriptions and not placements:
        raise HTTPException(
            status_code=404,
            detail=f"No Vision AI analysis found for task {task_id}. Enable with config.enable_vision_ai=true"
        )
    
    return {
        "status": "success",
        "task_id": task_id,
        "descriptions": descriptions,
        "placements": placements,
        "frames_analyzed": len(descriptions.get("frames", [])) if descriptions else 0
    }


@router.delete("/metrics/clear")
async def clear_old_metrics(max_age_hours: int = Query(default=24, ge=1, le=168)):
    """
    Clear timeline metrics older than specified hours.
    
    Args:
        max_age_hours: Maximum age in hours (1-168, default 24)
    
    Returns:
        Confirmation of cleared metrics
    """
    collector = get_metrics_collector()
    
    before_count = len(collector._metrics)
    collector.clear_old_metrics(max_age_hours=max_age_hours)
    after_count = len(collector._metrics)
    cleared = before_count - after_count
    
    return {
        "status": "success",
        "cleared_count": cleared,
        "remaining_count": after_count,
        "max_age_hours": max_age_hours
    }


@router.get("/health")
async def timeline_health():
    """
    Check timeline system health.
    
    Returns:
        System health status and statistics
    """
    collector = get_metrics_collector()
    stats = collector.get_aggregate_stats()
    
    # Check if timeline system is operational
    is_healthy = True
    issues = []
    
    # Check Vision AI error rate
    if stats.get("vision_error_rate", 0) > 0.1:  # >10% error rate
        issues.append(f"High Vision AI error rate: {stats['vision_error_rate']:.1%}")
        is_healthy = False
    
    # Check success rate
    if stats.get("success_rate", 1.0) < 0.9:  # <90% success
        issues.append(f"Low success rate: {stats['success_rate']:.1%}")
        is_healthy = False
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "timeline_enabled": True,
        "issues": issues,
        "statistics": {
            "total_timelines": stats.get("total_timelines", 0),
            "success_rate": stats.get("success_rate", 0),
            "avg_duration_seconds": round(stats.get("avg_total_duration", 0), 2),
        }
    }
