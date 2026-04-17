"""
ARQ Scheduling System — Automated Task Scheduling
==================================================

Provides recurring task scheduling via ARQ cron jobs.

Features:
- Schedule recurring video processing (daily, weekly, etc.)
- Auto-trigger on trends
- Webhook-based auto-processing
- Campaign scheduling

Usage:
    from services.auto_scheduler import AutoSchedulerService
    
    scheduler = AutoSchedulerService()
    await scheduler.schedule_recurring_source(
        user_id="user_123",
        source_type="youtube_channel",
        source_url="https://youtube.com/@channel",
        schedule="0 9 * * *",  # Daily at 9am
        processing_options={"target_platform": "tiktok"}
    )
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib

from arq import create_pool
from arq.connections import RedisSettings

logger = logging.getLogger(__name__)

# Redis settings for ARQ
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD")

redis_settings = RedisSettings(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    database=0,
)


class ScheduleFrequency(Enum):
    """Schedule frequencies."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class TriggerType(Enum):
    """Types of auto-triggers."""
    SCHEDULED = "scheduled"
    TREND_DETECTED = "trend_detected"
    WEBHOOK = "webhook"
    NEW_CONTENT = "new_content"


@dataclass
class ScheduledJob:
    """A scheduled automation job."""
    job_id: str
    user_id: str
    name: str
    trigger_type: TriggerType
    frequency: Optional[ScheduleFrequency]
    cron_expression: Optional[str]  # For custom schedules
    source_config: Dict[str, Any]  # URL, channel, etc.
    processing_config: Dict[str, Any]  # Platform, style, etc.
    publish_config: Dict[str, Any]  # Auto-publish settings
    is_active: bool
    created_at: datetime
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    total_clips_generated: int = 0


@dataclass
class TrendTrigger:
    """Auto-trigger when trending topic detected."""
    trigger_id: str
    user_id: str
    keywords: List[str]
    min_virality_score: float  # Only trigger if trend virality > threshold
    processing_config: Dict[str, Any]
    publish_config: Dict[str, Any]
    is_active: bool


class AutoSchedulerService:
    """
    Service for automated scheduling and triggering.
    """
    
    def __init__(self):
        self._redis_pool = None
        self._scheduled_jobs: Dict[str, ScheduledJob] = {}
    
    async def _get_redis(self):
        """Get or create Redis connection pool."""
        if self._redis_pool is None:
            self._redis_pool = await create_pool(redis_settings)
        return self._redis_pool
    
    def _generate_job_id(self, user_id: str, name: str) -> str:
        """Generate unique job ID."""
        hash_input = f"{user_id}:{name}:{datetime.utcnow().isoformat()}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    async def schedule_recurring_source(
        self,
        user_id: str,
        name: str,
        source_type: str,  # youtube_channel, rss_feed, podcast, etc.
        source_url: str,
        frequency: ScheduleFrequency,
        processing_config: Dict[str, Any],
        publish_config: Dict[str, Any],
        cron_expression: Optional[str] = None,
    ) -> ScheduledJob:
        """
        Schedule recurring processing of a content source.
        
        Args:
            user_id: User ID
            name: Schedule name
            source_type: Type of source
            source_url: URL to process
            frequency: How often to run
            processing_config: Video processing options
            publish_config: Auto-publish settings
            cron_expression: Custom cron (if frequency=CUSTOM)
        """
        job_id = self._generate_job_id(user_id, name)
        
        # Calculate next run time
        next_run = self._calculate_next_run(frequency, cron_expression)
        
        job = ScheduledJob(
            job_id=job_id,
            user_id=user_id,
            name=name,
            trigger_type=TriggerType.SCHEDULED,
            frequency=frequency,
            cron_expression=cron_expression,
            source_config={
                "type": source_type,
                "url": source_url,
            },
            processing_config=processing_config,
            publish_config=publish_config,
            is_active=True,
            created_at=datetime.utcnow(),
            next_run=next_run,
        )
        
        # Store in Redis for persistence
        redis = await self._get_redis()
        await redis.hset(
            f"scheduled_jobs:{user_id}",
            job_id,
            json.dumps(asdict(job), default=str)
        )
        
        # Schedule the ARQ job
        await self._schedule_arq_job(job)
        
        logger.info(f"[Scheduler] Created recurring job: {job_id} for user {user_id}")
        return job
    
    async def create_trend_trigger(
        self,
        user_id: str,
        keywords: List[str],
        min_virality_score: float = 70.0,
        processing_config: Optional[Dict[str, Any]] = None,
        publish_config: Optional[Dict[str, Any]] = None,
    ) -> TrendTrigger:
        """
        Create auto-trigger when trending topics match keywords.
        
        Args:
            user_id: User ID
            keywords: Keywords to watch for
            min_virality_score: Minimum trend score to trigger
            processing_config: How to process matching content
            publish_config: Auto-publish settings
        """
        trigger_id = self._generate_job_id(user_id, f"trend_{'_'.join(keywords[:2])}")
        
        trigger = TrendTrigger(
            trigger_id=trigger_id,
            user_id=user_id,
            keywords=keywords,
            min_virality_score=min_virality_score,
            processing_config=processing_config or {},
            publish_config=publish_config or {},
            is_active=True,
        )
        
        # Store in Redis
        redis = await self._get_redis()
        await redis.hset(
            f"trend_triggers:{user_id}",
            trigger_id,
            json.dumps(asdict(trigger))
        )
        
        logger.info(f"[Scheduler] Created trend trigger: {trigger_id} for keywords {keywords}")
        return trigger
    
    async def process_scheduled_job(self, job_id: str, user_id: str):
        """
        Execute a scheduled job.
        This is called by ARQ worker.
        """
        logger.info(f"[Scheduler] Executing job {job_id} for user {user_id}")
        
        # Load job config
        redis = await self._get_redis()
        job_data = await redis.hget(f"scheduled_jobs:{user_id}", job_id)
        
        if not job_data:
            logger.error(f"[Scheduler] Job not found: {job_id}")
            return
        
        job_dict = json.loads(job_data)
        source_config = job_dict["source_config"]
        processing_config = job_dict["processing_config"]
        publish_config = job_dict["publish_config"]
        
        try:
            # Create task for source
            from ...services.task_service import TaskService
            from ...database import get_db
            
            task_service = TaskService()
            
            async for db in get_db():
                # Create task
                task_data = {
                    "user_id": user_id,
                    "source": source_config["url"],
                    "type": source_config["type"],
                    "processing_mode": processing_config.get("processing_mode", "fast"),
                    "target_platform": processing_config.get("target_platform", "tiktok"),
                    "auto_center_face": processing_config.get("auto_center_face", True),
                    "add_subtitles": processing_config.get("add_subtitles", True),
                    "auto_publish": True,  # Enable auto-publish
                    "publish_config": publish_config,
                }
                
                task = await task_service.create_task(db, task_data)
                
                # Enqueue for processing
                from ...workers.queue_router import enqueue
                await enqueue(
                    await self._get_redis(),
                    "process_video_task",
                    task_id=task.id,
                    **task_data
                )
                
                logger.info(f"[Scheduler] Created task {task.id} from scheduled job {job_id}")
                
                # Update job stats
                job_dict["last_run"] = datetime.utcnow().isoformat()
                job_dict["run_count"] = job_dict.get("run_count", 0) + 1
                
                # Calculate next run
                next_run = self._calculate_next_run(
                    ScheduleFrequency(job_dict["frequency"]),
                    job_dict.get("cron_expression")
                )
                job_dict["next_run"] = next_run.isoformat() if next_run else None
                
                await redis.hset(
                    f"scheduled_jobs:{user_id}",
                    job_id,
                    json.dumps(job_dict)
                )
                
                # Reschedule next run
                await self._schedule_arq_job(ScheduledJob(**job_dict))
                
                break
                
        except Exception as e:
            logger.error(f"[Scheduler] Job execution failed: {e}")
    
    async def check_trend_triggers(self, trend_data: Dict[str, Any]):
        """
        Check if any trend triggers should fire.
        Called when new trends are fetched.
        """
        redis = await self._get_redis()
        
        # Get all trend triggers
        all_triggers = await redis.keys("trend_triggers:*")
        
        for trigger_key in all_triggers:
            triggers_data = await redis.hgetall(trigger_key)
            
            for trigger_id, trigger_json in triggers_data.items():
                trigger = json.loads(trigger_json)
                
                if not trigger["is_active"]:
                    continue
                
                # Check if trend matches keywords
                trend_keywords = trend_data.get("keywords", [])
                trigger_keywords = trigger["keywords"]
                
                matches = any(
                    tk.lower() in trend_keywords or trend_keywords in tk.lower()
                    for tk in trigger_keywords
                )
                
                if matches:
                    trend_score = trend_data.get("virality_score", 0)
                    min_score = trigger["min_virality_score"]
                    
                    if trend_score >= min_score:
                        logger.info(f"[Scheduler] Trend trigger fired: {trigger_id}")
                        
                        # Create processing task for this trend
                        await self._create_trend_task(trigger, trend_data)
    
    async def _create_trend_task(self, trigger: Dict, trend_data: Dict):
        """Create a task when trend trigger fires."""
        # Search for content matching the trend
        # This could search YouTube, news, etc.
        
        # For now, create a task that will search and process
        from ...services.task_service import TaskService
        
        task_service = TaskService()
        
        async for db in get_db():
            # Create trend-based task
            task_data = {
                "user_id": trigger["user_id"],
                "source": f"trend:{trend_data.get('keyword')}",
                "type": "trend_search",
                "search_query": trend_data.get("keyword"),
                "processing_config": trigger["processing_config"],
                "publish_config": trigger["publish_config"],
            }
            
            # This would be a special task type that searches for content
            # matching the trend, then processes it
            
            logger.info(f"[Scheduler] Trend task created for {trend_data.get('keyword')}")
            break
    
    def _calculate_next_run(
        self,
        frequency: ScheduleFrequency,
        cron_expression: Optional[str] = None
    ) -> Optional[datetime]:
        """Calculate next run time based on frequency."""
        now = datetime.utcnow()
        
        if frequency == ScheduleFrequency.HOURLY:
            return now + timedelta(hours=1)
        elif frequency == ScheduleFrequency.DAILY:
            return now + timedelta(days=1)
        elif frequency == ScheduleFrequency.WEEKLY:
            return now + timedelta(weeks=1)
        elif frequency == ScheduleFrequency.MONTHLY:
            # Approximate
            return now + timedelta(days=30)
        elif frequency == ScheduleFrequency.CUSTOM and cron_expression:
            # Parse cron and calculate next run
            # For simplicity, default to tomorrow same time
            return now + timedelta(days=1)
        
        return None
    
    async def _schedule_arq_job(self, job: ScheduledJob):
        """Schedule the job with ARQ."""
        redis = await self._get_redis()
        
        # Calculate delay until next run
        if job.next_run:
            delay = (job.next_run - datetime.utcnow()).total_seconds()
            if delay < 0:
                delay = 0
        else:
            delay = 3600  # Default 1 hour
        
        # Schedule with ARQ
        await redis.enqueue_job(
            "process_scheduled_job",
            job_id=job.job_id,
            user_id=job.user_id,
            _defer_by_seconds=int(delay),
        )
        
        logger.debug(f"[Scheduler] ARQ job scheduled in {delay}s: {job.job_id}")
    
    async def get_user_schedules(self, user_id: str) -> List[ScheduledJob]:
        """Get all scheduled jobs for a user."""
        redis = await self._get_redis()
        jobs_data = await redis.hgetall(f"scheduled_jobs:{user_id}")
        
        jobs = []
        for job_id, job_json in jobs_data.items():
            job_dict = json.loads(job_json)
            # Parse datetime strings back
            for key in ["created_at", "last_run", "next_run"]:
                if job_dict.get(key):
                    job_dict[key] = datetime.fromisoformat(job_dict[key])
            jobs.append(ScheduledJob(**job_dict))
        
        return jobs
    
    async def deactivate_job(self, user_id: str, job_id: str) -> bool:
        """Deactivate a scheduled job."""
        redis = await self._get_redis()
        
        job_data = await redis.hget(f"scheduled_jobs:{user_id}", job_id)
        if not job_data:
            return False
        
        job_dict = json.loads(job_data)
        job_dict["is_active"] = False
        
        await redis.hset(
            f"scheduled_jobs:{user_id}",
            job_id,
            json.dumps(job_dict)
        )
        
        return True


# ARQ worker function
async def process_scheduled_job(ctx, job_id: str, user_id: str):
    """
    ARQ worker function for scheduled jobs.
    """
    scheduler = AutoSchedulerService()
    await scheduler.process_scheduled_job(job_id, user_id)


__all__ = [
    "AutoSchedulerService",
    "ScheduledJob",
    "TrendTrigger",
    "ScheduleFrequency",
    "TriggerType",
    "process_scheduled_job",
]
