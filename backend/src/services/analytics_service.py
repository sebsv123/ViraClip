"""
Analytics Dashboard Service

Provides metrics and analytics for monitoring system performance,
task processing, and user activity.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..models import Task, GeneratedClip

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Lazy config initialization
_config = None

def _get_config():
    global _config
    if _config is None:
        _config = Config()
    return _config


class MetricType(Enum):
    TASKS_CREATED = "tasks_created"
    TASKS_COMPLETED = "tasks_completed"
    TASKS_FAILED = "tasks_failed"
    CLIPS_GENERATED = "clips_generated"
    PROCESSING_TIME = "processing_time"
    ERROR_RATE = "error_rate"


@dataclass
class TaskMetrics:
    """Task processing metrics."""
    total_tasks: int
    completed: int
    failed: int
    pending: int
    processing: int
    avg_processing_time: float
    total_clips: int


@dataclass
class DailyStats:
    """Daily statistics."""
    date: str
    tasks_created: int
    tasks_completed: int
    tasks_failed: int
    clips_generated: int
    avg_processing_time: float


@dataclass
class SystemHealth:
    """System health status."""
    status: str  # healthy, degraded, critical
    queue_depth: int
    worker_count: int
    active_tasks: int
    error_rate_1h: float
    avg_latency_ms: float


class AnalyticsService:
    """Service for collecting and querying analytics data."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._redis_client = None
    
    async def _get_redis(self):
        """Get or create Redis client."""
        if not REDIS_AVAILABLE:
            return None
        if self._redis_client is None:
            try:
                self._redis_client = aioredis.Redis(
                    host=_get_config().redis_host,
                    port=_get_config().redis_port,
                    password=_get_config().redis_password,
                    decode_responses=True,
                )
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
                return None
        return self._redis_client
    
    async def get_task_metrics(
        self,
        user_id: Optional[str] = None,
        days: int = 30
    ) -> TaskMetrics:
        """Get task processing metrics.
        
        Args:
            user_id: Optional filter by user
            days: Number of days to look back
            
        Returns:
            TaskMetrics with aggregated data
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Build query
        query = select(Task).where(Task.created_at >= since)
        if user_id:
            query = query.where(Task.user_id == user_id)
        
        result = await self.db.execute(query)
        tasks = result.scalars().all()
        
        total = len(tasks)
        completed = sum(1 for t in tasks if t.status == "completed")
        failed = sum(1 for t in tasks if t.status == "error")
        pending = sum(1 for t in tasks if t.status == "queued")
        processing = sum(1 for t in tasks if t.status == "processing")
        
        # Calculate average processing time
        completed_tasks = [t for t in tasks if t.status == "completed"]
        avg_time = 0.0
        if completed_tasks:
            times = []
            for t in completed_tasks:
                if t.updated_at and t.created_at:
                    duration = (t.updated_at - t.created_at).total_seconds()
                    times.append(duration)
            if times:
                avg_time = sum(times) / len(times)
        
        # Count clips
        clip_count = sum(len(t.clips) for t in completed_tasks)
        
        return TaskMetrics(
            total_tasks=total,
            completed=completed,
            failed=failed,
            pending=pending,
            processing=processing,
            avg_processing_time=avg_time,
            total_clips=clip_count
        )
    
    async def get_daily_stats(
        self,
        user_id: Optional[str] = None,
        days: int = 7
    ) -> List[DailyStats]:
        """Get daily statistics for the last N days."""
        stats = []
        
        for i in range(days):
            day = datetime.now(timezone.utc) - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            
            query = select(Task).where(
                and_(
                    Task.created_at >= day_start,
                    Task.created_at < day_end
                )
            )
            if user_id:
                query = query.where(Task.user_id == user_id)
            
            result = await self.db.execute(query)
            tasks = result.scalars().all()
            
            created = len(tasks)
            completed = sum(1 for t in tasks if t.status == "completed")
            failed = sum(1 for t in tasks if t.status == "error")
            
            clips = sum(len(t.clips) for t in tasks if t.status == "completed")
            
            avg_time = 0.0
            completed_tasks = [t for t in tasks if t.status == "completed"]
            if completed_tasks:
                times = []
                for t in completed_tasks:
                    if t.updated_at and t.created_at:
                        times.append((t.updated_at - t.created_at).total_seconds())
                if times:
                    avg_time = sum(times) / len(times)
            
            stats.append(DailyStats(
                date=day_start.strftime("%Y-%m-%d"),
                tasks_created=created,
                tasks_completed=completed,
                tasks_failed=failed,
                clips_generated=clips,
                avg_processing_time=avg_time
            ))
        
        return list(reversed(stats))
    
    async def get_system_health(self) -> SystemHealth:
        """Get current system health status."""
        redis = await self._get_redis()
        
        queue_depth = 0
        worker_count = 0
        error_rate = 0.0
        
        if redis:
            try:
                # Get queue depth from Redis
                queue_depth = await redis.llen("arq:queue")
                
                # Count active workers
                workers = await redis.keys("arq:worker:*")
                worker_count = len(workers)
                
                # Calculate error rate from last hour
                error_key = f"errors:{datetime.now(timezone.utc):%Y%m%d%H}"
                error_count = await redis.get(error_key) or 0
                total_key = f"tasks:{datetime.now(timezone.utc):%Y%m%d%H}"
                total_count = await redis.get(total_key) or 1
                error_rate = float(error_count) / float(total_count)
                
            except Exception as e:
                logger.warning(f"Redis health check failed: {e}")
        
        # Determine status
        if error_rate > 0.1 or queue_depth > 100:
            status = "critical"
        elif error_rate > 0.05 or queue_depth > 50:
            status = "degraded"
        else:
            status = "healthy"
        
        # Count active tasks from DB
        result = await self.db.execute(
            select(func.count()).select_from(Task).where(Task.status == "processing")
        )
        active_tasks = result.scalar() or 0
        
        return SystemHealth(
            status=status,
            queue_depth=queue_depth,
            worker_count=worker_count,
            active_tasks=active_tasks,
            error_rate_1h=error_rate,
            avg_latency_ms=0.0  # TODO: Implement latency tracking
        )
    
    async def get_popular_sources(
        self,
        limit: int = 10,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Get most popular video sources."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        result = await self.db.execute(
            select(
                Task.source_url,
                func.count().label("count"),
                func.avg(Task.progress).label("avg_progress")
            )
            .where(
                and_(
                    Task.created_at >= since,
                    Task.source_url.isnot(None)
                )
            )
            .group_by(Task.source_url)
            .order_by(func.count().desc())
            .limit(limit)
        )
        
        return [
            {
                "source_url": row.source_url,
                "task_count": row.count,
                "avg_progress": float(row.avg_progress or 0)
            }
            for row in result.all()
        ]
    
    async def get_virality_distribution(
        self,
        days: int = 30
    ) -> Dict[str, int]:
        """Get distribution of virality scores."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        result = await self.db.execute(
            select(GeneratedClip.virality_score)
            .join(Task)
            .where(Task.created_at >= since)
        )
        
        scores = [row.virality_score or 0 for row in result.all() if row.virality_score]
        
        # Bin into ranges
        distribution = {
            "0-20": 0,
            "21-40": 0,
            "41-60": 0,
            "61-80": 0,
            "81-100": 0
        }
        
        for score in scores:
            if score <= 20:
                distribution["0-20"] += 1
            elif score <= 40:
                distribution["21-40"] += 1
            elif score <= 60:
                distribution["41-60"] += 1
            elif score <= 80:
                distribution["61-80"] += 1
            else:
                distribution["81-100"] += 1
        
        return distribution
    
    async def record_metric(
        self,
        metric_type: MetricType,
        value: float,
        user_id: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a metric for analytics."""
        redis = await self._get_redis()
        if not redis:
            return
        
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            key = f"metric:{metric_type.value}:{datetime.now(timezone.utc):%Y%m%d}"
            
            metric_data = {
                "timestamp": timestamp,
                "value": value,
                "user_id": user_id or "system",
                "tags": tags or {}
            }
            
            await redis.lpush(key, json.dumps(metric_data))
            await redis.ltrim(key, 0, 9999)  # Keep last 10k entries
            await redis.expire(key, 86400 * 30)  # 30 days retention
            
        except Exception as e:
            logger.warning(f"Failed to record metric: {e}")


# Singleton factory
async def get_analytics_service(db: AsyncSession) -> AnalyticsService:
    """Factory function for AnalyticsService."""
    return AnalyticsService(db)
