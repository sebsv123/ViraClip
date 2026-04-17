"""
Task control endpoints for managing background jobs.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from ...services.task_manager import TaskManager
from ...services.coordinator import VideoCoordinator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["task-control"])


class ProcessVideoRequest(BaseModel):
    """Request to process a video."""
    video_path: str
    language: str = "es"
    num_clips: int = 3
    processing_mode: str = "fast"


class TaskResponse(BaseModel):
    """Response with task information."""
    task_id: str
    status: str
    stream_url: str
    created_at: Optional[str] = None


@router.post("/process", response_model=TaskResponse)
async def process_video_async(request: ProcessVideoRequest):
    """
    Start video processing as a background task.
    
    Returns task_id immediately without blocking.
    Client can monitor progress via SSE at /tasks/{task_id}/stream
    """
    import uuid
    from ...services.coordinator import VideoCoordinator
    
    task_id = str(uuid.uuid4())
    
    # Create coordinator
    coordinator = VideoCoordinator(
        task_id=task_id,
        video_path=request.video_path,
        config={
            "language": request.language,
            "num_clips": request.num_clips,
            "processing_mode": request.processing_mode
        }
    )
    
    # Launch as background task
    TaskManager.create_task(
        coro=coordinator.run(),
        task_id=task_id,
        metadata={
            "video_path": request.video_path,
            "language": request.language,
            "num_clips": request.num_clips
        }
    )
    
    logger.info(f"🎬 Started video processing task: {task_id}")
    
    return TaskResponse(
        task_id=task_id,
        status="running",
        stream_url=f"/api/tasks/{task_id}/stream",
        created_at=TaskManager.get_task_status(task_id)["created_at"]
    )


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    """
    Cancel a running task.
    
    Args:
        task_id: Task to cancel
        
    Returns:
        Cancellation status
    """
    status = TaskManager.get_task_status(task_id)
    
    if not status:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    
    if status["status"] != "running":
        return {
            "task_id": task_id,
            "cancelled": False,
            "reason": f"Task is not running (status: {status['status']})"
        }
    
    cancelled = await TaskManager.cancel_task(task_id)
    
    return {
        "task_id": task_id,
        "cancelled": cancelled,
        "message": "Task cancelled successfully" if cancelled else "Failed to cancel task"
    }


@router.get("/{task_id}/status")
async def get_task_status(task_id: str):
    """
    Get detailed task status.
    
    Args:
        task_id: Task ID
        
    Returns:
        Task metadata and current status
    """
    status = TaskManager.get_task_status(task_id)
    
    if not status:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    
    return status


@router.get("/all")
async def list_all_tasks(include_completed: bool = False):
    """
    List all tracked tasks.
    
    Args:
        include_completed: Include completed/failed tasks (default: False)
        
    Returns:
        List of tasks with status
    """
    all_tasks = TaskManager.get_all_tasks()
    
    if not include_completed:
        # Filter to only running tasks
        all_tasks = {
            task_id: metadata
            for task_id, metadata in all_tasks.items()
            if metadata["status"] == "running"
        }
    
    return {
        "total_tasks": len(all_tasks),
        "tasks": all_tasks
    }


@router.post("/cleanup")
async def cleanup_old_tasks(max_age_hours: int = 24):
    """
    Clean up old completed task metadata.
    
    Args:
        max_age_hours: Maximum age in hours (default: 24)
        
    Returns:
        Number of tasks cleaned up
    """
    cleaned = TaskManager.cleanup_old_tasks(max_age_hours=max_age_hours)
    
    return {
        "cleaned_count": cleaned,
        "max_age_hours": max_age_hours
    }
