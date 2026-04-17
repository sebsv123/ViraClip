"""
Background task manager with trackable IDs and cancellation support.

Uses asyncio.create_task() instead of FastAPI BackgroundTasks for better control.
"""

import asyncio
import logging
from typing import Dict, Optional, Callable, Any
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Global registry of running tasks
_running_tasks: Dict[str, asyncio.Task] = {}
_task_metadata: Dict[str, dict] = {}


class TaskManager:
    """Manages long-running background tasks with cancellation support."""
    
    @classmethod
    def create_task(
        cls,
        coro: Callable,
        task_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> str:
        """
        Create and track a background task.
        
        Args:
            coro: Coroutine to execute
            task_id: Optional task ID (generated if not provided)
            metadata: Optional metadata to store with task
            
        Returns:
            task_id: Unique task identifier
        """
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        # Create asyncio task
        task = asyncio.create_task(coro)
        
        # Store in global registry
        _running_tasks[task_id] = task
        _task_metadata[task_id] = {
            "task_id": task_id,
            "created_at": datetime.utcnow().isoformat(),
            "status": "running",
            "metadata": metadata or {}
        }
        
        # Cleanup callback when task completes
        def cleanup(t: asyncio.Task):
            try:
                # Check if task completed successfully or with error
                if t.cancelled():
                    _task_metadata[task_id]["status"] = "cancelled"
                elif t.exception():
                    _task_metadata[task_id]["status"] = "failed"
                    _task_metadata[task_id]["error"] = str(t.exception())
                else:
                    _task_metadata[task_id]["status"] = "completed"
                    _task_metadata[task_id]["result"] = t.result()
                
                _task_metadata[task_id]["completed_at"] = datetime.utcnow().isoformat()
                
            except Exception as e:
                logger.error(f"Error in task cleanup for {task_id}: {e}")
            finally:
                # Remove from running tasks registry
                _running_tasks.pop(task_id, None)
                logger.info(f"Task {task_id} cleaned up: {_task_metadata[task_id]['status']}")
        
        task.add_done_callback(cleanup)
        
        logger.info(f"🚀 Created background task: {task_id}")
        return task_id
    
    @classmethod
    async def cancel_task(cls, task_id: str) -> bool:
        """
        Cancel a running task.
        
        Args:
            task_id: Task to cancel
            
        Returns:
            True if task was cancelled, False if not found or already done
        """
        task = _running_tasks.get(task_id)
        
        if task is None:
            logger.warning(f"Cannot cancel task {task_id}: not found in running tasks")
            return False
        
        if task.done():
            logger.info(f"Task {task_id} already completed, cannot cancel")
            return False
        
        # Cancel the task
        task.cancel()
        logger.info(f"🛑 Cancelled task: {task_id}")
        
        # Wait for cancellation to complete
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        return True
    
    @classmethod
    def get_task_status(cls, task_id: str) -> Optional[dict]:
        """
        Get task status and metadata.
        
        Args:
            task_id: Task ID
            
        Returns:
            Task metadata dict or None if not found
        """
        return _task_metadata.get(task_id)
    
    @classmethod
    def get_all_tasks(cls) -> dict:
        """
        Get all tracked tasks (running and completed).
        
        Returns:
            Dict of task_id -> metadata
        """
        return _task_metadata.copy()
    
    @classmethod
    def get_running_tasks(cls) -> Dict[str, asyncio.Task]:
        """
        Get currently running tasks.
        
        Returns:
            Dict of task_id -> asyncio.Task
        """
        return _running_tasks.copy()
    
    @classmethod
    async def wait_for_task(cls, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        Wait for a task to complete.
        
        Args:
            task_id: Task ID
            timeout: Optional timeout in seconds
            
        Returns:
            Task result
            
        Raises:
            TimeoutError: If timeout is reached
            ValueError: If task not found
        """
        task = _running_tasks.get(task_id)
        
        if task is None:
            # Check if it already completed
            metadata = _task_metadata.get(task_id)
            if metadata and metadata.get("status") == "completed":
                return metadata.get("result")
            raise ValueError(f"Task {task_id} not found")
        
        if timeout:
            await asyncio.wait_for(task, timeout=timeout)
        else:
            await task
        
        return task.result()
    
    @classmethod
    def cleanup_old_tasks(cls, max_age_hours: int = 24) -> int:
        """
        Remove old completed task metadata.
        
        Args:
            max_age_hours: Maximum age in hours for completed tasks
            
        Returns:
            Number of tasks cleaned up
        """
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        to_remove = []
        for task_id, metadata in _task_metadata.items():
            # Only cleanup completed/failed/cancelled tasks
            if metadata["status"] not in ["running"]:
                completed_at = metadata.get("completed_at")
                if completed_at:
                    completed_time = datetime.fromisoformat(completed_at)
                    if completed_time < cutoff:
                        to_remove.append(task_id)
        
        for task_id in to_remove:
            _task_metadata.pop(task_id, None)
        
        if to_remove:
            logger.info(f"🧹 Cleaned up {len(to_remove)} old tasks")
        
        return len(to_remove)


# Convenience functions
async def create_background_task(coro: Callable, task_id: Optional[str] = None, **metadata) -> str:
    """Shorthand for TaskManager.create_task()."""
    return TaskManager.create_task(coro, task_id=task_id, metadata=metadata)


async def cancel_background_task(task_id: str) -> bool:
    """Shorthand for TaskManager.cancel_task()."""
    return await TaskManager.cancel_task(task_id)


def get_task_status(task_id: str) -> Optional[dict]:
    """Shorthand for TaskManager.get_task_status()."""
    return TaskManager.get_task_status(task_id)
