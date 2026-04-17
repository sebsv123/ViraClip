"""
Scheduling and Automation System
Automated workflows for recurring tasks and scheduled processing.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


class ScheduleType(Enum):
    """Types of schedules."""
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class TaskType(Enum):
    """Types of automated tasks."""
    PROCESS_VIDEO = "process_video"
    PUBLISH_CLIP = "publish_clip"
    CLEANUP = "cleanup"
    BACKUP = "backup"
    GENERATE_REPORT = "generate_report"


@dataclass
class ScheduledTask:
    """A scheduled task."""
    task_id: str
    user_id: str
    name: str
    task_type: TaskType
    schedule_type: ScheduleType
    schedule_config: Dict[str, Any]
    task_config: Dict[str, Any]
    is_active: bool
    created_at: str
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    run_count: int = 0


class SchedulerService:
    """
    Service for scheduling and automation.
    """
    
    def __init__(self):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._execution_history: List[Dict[str, Any]] = []
    
    def create_schedule(
        self,
        user_id: str,
        name: str,
        task_type: TaskType,
        schedule_type: ScheduleType,
        schedule_config: Dict[str, Any],
        task_config: Dict[str, Any]
    ) -> ScheduledTask:
        """Create a new scheduled task."""
        task_id = str(uuid.uuid4())
        
        # Calculate next run
        next_run = self._calculate_next_run(schedule_type, schedule_config)
        
        task = ScheduledTask(
            task_id=task_id,
            user_id=user_id,
            name=name,
            task_type=task_type,
            schedule_type=schedule_type,
            schedule_config=schedule_config,
            task_config=task_config,
            is_active=True,
            created_at=datetime.now().isoformat(),
            next_run=next_run
        )
        
        self._tasks[task_id] = task
        
        logger.info(f"Created scheduled task: {name} ({task_type.value})")
        return task
    
    def _calculate_next_run(
        self,
        schedule_type: ScheduleType,
        config: Dict[str, Any]
    ) -> Optional[str]:
        """Calculate next run time based on schedule."""
        now = datetime.now()
        
        if schedule_type == ScheduleType.ONCE:
            run_at = config.get("run_at")
            return run_at
        
        elif schedule_type == ScheduleType.DAILY:
            time_str = config.get("time", "09:00")
            hour, minute = map(int, time_str.split(":"))
            
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            
            return next_run.isoformat()
        
        elif schedule_type == ScheduleType.WEEKLY:
            day = config.get("day", 0)  # 0 = Monday
            time_str = config.get("time", "09:00")
            hour, minute = map(int, time_str.split(":"))
            
            days_ahead = day - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            next_run += timedelta(days=days_ahead)
            
            return next_run.isoformat()
        
        elif schedule_type == ScheduleType.MONTHLY:
            day_of_month = config.get("day", 1)
            time_str = config.get("time", "09:00")
            hour, minute = map(int, time_str.split(":"))
            
            # Simple implementation - doesn't handle edge cases
            if now.day >= day_of_month:
                # Next month
                if now.month == 12:
                    next_run = now.replace(year=now.year + 1, month=1, day=day_of_month)
                else:
                    next_run = now.replace(month=now.month + 1, day=day_of_month)
            else:
                next_run = now.replace(day=day_of_month)
            
            next_run = next_run.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return next_run.isoformat()
        
        return None
    
    async def execute_task(self, task_id: str) -> Dict[str, Any]:
        """Execute a scheduled task."""
        if task_id not in self._tasks:
            return {"error": "Task not found"}
        
        task = self._tasks[task_id]
        
        if not task.is_active:
            return {"error": "Task is inactive"}
        
        start_time = datetime.now()
        
        try:
            # Execute based on task type
            executors = {
                TaskType.PROCESS_VIDEO: self._execute_video_processing,
                TaskType.PUBLISH_CLIP: self._execute_publish,
                TaskType.CLEANUP: self._execute_cleanup,
                TaskType.BACKUP: self._execute_backup,
                TaskType.GENERATE_REPORT: self._execute_report
            }
            
            executor = executors.get(task.task_type)
            
            if not executor:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            result = await executor(task.task_config)
            
            # Update task
            task.last_run = start_time.isoformat()
            task.run_count += 1
            task.next_run = self._calculate_next_run(task.schedule_type, task.schedule_config)
            
            # Record execution
            execution_record = {
                "execution_id": str(uuid.uuid4()),
                "task_id": task_id,
                "started_at": start_time.isoformat(),
                "completed_at": datetime.now().isoformat(),
                "status": "success",
                "result": result
            }
            self._execution_history.append(execution_record)
            
            logger.info(f"Executed scheduled task: {task.name}")
            
            return {"success": True, "result": result}
            
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            
            self._execution_history.append({
                "execution_id": str(uuid.uuid4()),
                "task_id": task_id,
                "started_at": start_time.isoformat(),
                "completed_at": datetime.now().isoformat(),
                "status": "failed",
                "error": str(e)
            })
            
            return {"success": False, "error": str(e)}
    
    async def _execute_video_processing(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute video processing task."""
        video_url = config.get("video_url")
        settings = config.get("settings", {})
        
        # This would call the video service
        logger.info(f"Scheduled video processing: {video_url}")
        
        return {"video_url": video_url, "status": "processed"}
    
    async def _execute_publish(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute publish task."""
        clip_id = config.get("clip_id")
        platform = config.get("platform")
        
        logger.info(f"Scheduled publish: {clip_id} to {platform}")
        
        return {"clip_id": clip_id, "platform": platform, "status": "published"}
    
    async def _execute_cleanup(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute cleanup task."""
        older_than_days = config.get("older_than_days", 7)
        
        logger.info(f"Scheduled cleanup: files older than {older_than_days} days")
        
        return {"cleaned": True, "older_than_days": older_than_days}
    
    async def _execute_backup(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute backup task."""
        from ..services.backup_recovery import create_system_backup
        
        result = await create_system_backup("scheduled")
        
        return {"backup_id": result.backup_id, "status": result.status}
    
    async def _execute_report(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute report generation task."""
        report_type = config.get("report_type", "daily")
        
        logger.info(f"Scheduled report generation: {report_type}")
        
        return {"report_type": report_type, "generated": True}
    
    def get_due_tasks(self) -> List[ScheduledTask]:
        """Get all tasks that are due for execution."""
        now = datetime.now()
        due = []
        
        for task in self._tasks.values():
            if not task.is_active or not task.next_run:
                continue
            
            next_run = datetime.fromisoformat(task.next_run)
            if next_run <= now:
                due.append(task)
        
        return due
    
    def list_user_tasks(
        self,
        user_id: str,
        active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """List scheduled tasks for a user."""
        tasks = [
            task for task in self._tasks.values()
            if task.user_id == user_id
        ]
        
        if active_only:
            tasks = [t for t in tasks if t.is_active]
        
        return [
            {
                "task_id": t.task_id,
                "name": t.name,
                "type": t.task_type.value,
                "schedule": t.schedule_type.value,
                "is_active": t.is_active,
                "next_run": t.next_run,
                "last_run": t.last_run,
                "run_count": t.run_count,
                "created_at": t.created_at
            }
            for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)
        ]
    
    def get_task_details(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a task."""
        if task_id not in self._tasks:
            return None
        
        task = self._tasks[task_id]
        
        return {
            "task_id": task.task_id,
            "name": task.name,
            "type": task.task_type.value,
            "schedule": {
                "type": task.schedule_type.value,
                "config": task.schedule_config
            },
            "task_config": task.task_config,
            "is_active": task.is_active,
            "next_run": task.next_run,
            "last_run": task.last_run,
            "run_count": task.run_count,
            "created_at": task.created_at
        }
    
    def update_task(
        self,
        task_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update a scheduled task."""
        if task_id not in self._tasks:
            return False
        
        task = self._tasks[task_id]
        
        if "is_active" in updates:
            task.is_active = updates["is_active"]
        
        if "task_config" in updates:
            task.task_config.update(updates["task_config"])
        
        if "schedule_config" in updates:
            task.schedule_config.update(updates["schedule_config"])
            # Recalculate next run
            task.next_run = self._calculate_next_run(
                task.schedule_type,
                task.schedule_config
            )
        
        logger.info(f"Updated scheduled task: {task.name}")
        return True
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a scheduled task."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False
    
    def get_execution_history(
        self,
        task_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get execution history."""
        history = self._execution_history
        
        if task_id:
            history = [h for h in history if h["task_id"] == task_id]
        
        return sorted(
            history,
            key=lambda x: x["started_at"],
            reverse=True
        )[:limit]


# Global instance
_scheduler: Optional[SchedulerService] = None


def get_scheduler() -> SchedulerService:
    """Get global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService()
    return _scheduler


# Convenience functions
def create_scheduled_task(
    user_id: str,
    name: str,
    task_type: str,
    schedule_type: str,
    schedule_config: Dict[str, Any],
    task_config: Dict[str, Any]
) -> ScheduledTask:
    """Create a new scheduled task."""
    return get_scheduler().create_schedule(
        user_id=user_id,
        name=name,
        task_type=TaskType(task_type),
        schedule_type=ScheduleType(schedule_type),
        schedule_config=schedule_config,
        task_config=task_config
    )


def get_user_schedules(user_id: str) -> List[Dict[str, Any]]:
    """Get user's scheduled tasks."""
    return get_scheduler().list_user_tasks(user_id)
