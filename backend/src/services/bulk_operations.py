"""
Bulk Operations Service — Process Multiple Sources
=====================================================

Enables batch processing of multiple videos, channels, or sources
in a single operation with progress tracking.

Usage:
    from services.bulk_operations import BulkOperationsService
    
    bulk = BulkOperationsService()
    job = await bulk.create_bulk_job(
        user_id="xxx",
        sources=[
            {"type": "youtube", "url": "..."},
            {"type": "youtube", "url": "..."},
        ],
        processing_config={"target_platform": "tiktok"}
    )
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class BulkJobStatus(Enum):
    """Status of a bulk job."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceItemStatus(Enum):
    """Status of individual source item."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SourceItem:
    """A single source in a bulk job."""
    item_id: str
    source_type: str
    source_url: str
    title: Optional[str] = None
    status: SourceItemStatus = SourceItemStatus.PENDING
    task_id: Optional[str] = None
    clips_generated: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class BulkJob:
    """A bulk processing job."""
    job_id: str
    user_id: str
    name: str
    status: BulkJobStatus
    sources: List[SourceItem]
    processing_config: Dict[str, Any]
    publish_config: Dict[str, Any]
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    total_clips_generated: int = 0
    total_views_estimate: int = 0
    
    def get_progress(self) -> Dict[str, Any]:
        """Calculate job progress."""
        total = len(self.sources)
        completed = sum(1 for s in self.sources if s.status in [
            SourceItemStatus.COMPLETED, SourceItemStatus.FAILED, SourceItemStatus.SKIPPED
        ])
        processing = sum(1 for s in self.sources if s.status == SourceItemStatus.PROCESSING)
        pending = sum(1 for s in self.sources if s.status == SourceItemStatus.PENDING)
        
        return {
            "total": total,
            "completed": completed,
            "processing": processing,
            "pending": pending,
            "percentage": int((completed / total * 100)) if total > 0 else 0,
        }


class BulkOperationsService:
    """
    Service for managing bulk video processing operations.
    """
    
    def __init__(self):
        self._jobs: Dict[str, BulkJob] = {}
        self.max_concurrent = 3  # Process 3 sources at a time
    
    async def create_bulk_job(
        self,
        db: AsyncSession,
        user_id: str,
        name: str,
        sources: List[Dict[str, str]],
        processing_config: Dict[str, Any],
        publish_config: Optional[Dict[str, Any]] = None,
    ) -> BulkJob:
        """
        Create a new bulk processing job.
        
        Args:
            user_id: User ID
            name: Job name/description
            sources: List of {type, url, title?}
            processing_config: Processing options
            publish_config: Auto-publish settings
        """
        job_id = str(uuid.uuid4())
        
        # Create source items
        source_items = []
        for i, source in enumerate(sources):
            item = SourceItem(
                item_id=f"{job_id}_item_{i}",
                source_type=source.get("type", "youtube"),
                source_url=source["url"],
                title=source.get("title"),
            )
            source_items.append(item)
        
        job = BulkJob(
            job_id=job_id,
            user_id=user_id,
            name=name,
            status=BulkJobStatus.QUEUED,
            sources=source_items,
            processing_config=processing_config,
            publish_config=publish_config or {},
        )
        
        # Store job
        self._jobs[job_id] = job
        
        # Persist to database
        await self._save_job(db, job)
        
        logger.info(f"[Bulk] Created job {job_id} with {len(sources)} sources for user {user_id}")
        return job
    
    async def start_bulk_job(
        self,
        db: AsyncSession,
        job_id: str,
    ) -> bool:
        """
        Start processing a bulk job.
        """
        job = self._jobs.get(job_id)
        if not job:
            # Load from DB
            job = await self._load_job(db, job_id)
            if not job:
                return False
            self._jobs[job_id] = job
        
        if job.status != BulkJobStatus.QUEUED:
            logger.warning(f"[Bulk] Job {job_id} cannot be started (status: {job.status})")
            return False
        
        job.status = BulkJobStatus.PROCESSING
        job.started_at = datetime.utcnow()
        
        # Start processing in background
        asyncio.create_task(self._process_bulk_job(db, job))
        
        await self._save_job(db, job)
        return True
    
    async def _process_bulk_job(
        self,
        db: AsyncSession,
        job: BulkJob,
    ):
        """Process all sources in the job."""
        from ...services.task_service import TaskService
        from ...workers.queue_router import enqueue
        from ...workers.job_queue import JobQueue
        
        task_service = TaskService()
        redis = await JobQueue.get_pool()
        
        # Process in batches
        pending = [s for s in job.sources if s.status == SourceItemStatus.PENDING]
        
        for i in range(0, len(pending), self.max_concurrent):
            batch = pending[i:i + self.max_concurrent]
            
            # Process batch concurrently
            tasks = []
            for source in batch:
                task = self._process_source(db, job, source, task_service, redis)
                tasks.append(task)
            
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Save progress after each batch
            await self._save_job(db, job)
        
        # Mark job complete
        job.status = BulkJobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        await self._save_job(db, job)
        
        logger.info(f"[Bulk] Job {job.job_id} completed. Generated {job.total_clips_generated} clips.")
    
    async def _process_source(
        self,
        db: AsyncSession,
        job: BulkJob,
        source: SourceItem,
        task_service,
        redis,
    ):
        """Process a single source item."""
        try:
            source.status = SourceItemStatus.PROCESSING
            source.started_at = datetime.utcnow()
            
            # Create task
            task_data = {
                "user_id": job.user_id,
                "source": source.source_url,
                "type": source.source_type,
                "processing_mode": job.processing_config.get("processing_mode", "fast"),
                "target_platform": job.processing_config.get("target_platform", "tiktok"),
                "auto_center_face": job.processing_config.get("auto_center_face", True),
                "add_subtitles": job.processing_config.get("add_subtitles", True),
                "include_broll": job.processing_config.get("include_broll", True),
                "auto_publish": job.publish_config.get("auto_publish", False),
                "publish_config": job.publish_config,
            }
            
            task = await task_service.create_task(db, task_data)
            source.task_id = task.id
            
            # Enqueue for processing
            await enqueue(redis, "process_video_task", task_id=task.id, **task_data)
            
            # Wait for completion (poll or use webhook)
            # For now, just mark as complete (real implementation would poll)
            source.status = SourceItemStatus.COMPLETED
            source.completed_at = datetime.utcnow()
            source.clips_generated = 1  # Would be actual count from task result
            
            job.total_clips_generated += source.clips_generated
            
        except Exception as e:
            logger.error(f"[Bulk] Failed to process source {source.item_id}: {e}")
            source.status = SourceItemStatus.FAILED
            source.error_message = str(e)
    
    async def get_job_status(
        self,
        db: AsyncSession,
        job_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get current status of a bulk job."""
        job = self._jobs.get(job_id)
        if not job:
            job = await self._load_job(db, job_id)
        
        if not job:
            return None
        
        progress = job.get_progress()
        
        return {
            "job_id": job.job_id,
            "name": job.name,
            "status": job.status.value,
            "progress": progress,
            "total_clips_generated": job.total_clips_generated,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "sources": [
                {
                    "item_id": s.item_id,
                    "source_url": s.source_url,
                    "title": s.title,
                    "status": s.status.value,
                    "clips_generated": s.clips_generated,
                    "error": s.error_message,
                }
                for s in job.sources
            ],
        }
    
    async def cancel_job(
        self,
        db: AsyncSession,
        job_id: str,
    ) -> bool:
        """Cancel a running bulk job."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        
        if job.status not in [BulkJobStatus.QUEUED, BulkJobStatus.PROCESSING]:
            return False
        
        job.status = BulkJobStatus.CANCELLED
        job.completed_at = datetime.utcnow()
        
        # Cancel pending sources
        for source in job.sources:
            if source.status == SourceItemStatus.PENDING:
                source.status = SourceItemStatus.SKIPPED
        
        await self._save_job(db, job)
        return True
    
    async def list_user_jobs(
        self,
        db: AsyncSession,
        user_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """List all bulk jobs for a user."""
        # Query from database
        from ...models import BulkJob as BulkJobModel
        
        result = await db.execute(
            select(BulkJobModel)
            .where(BulkJobModel.user_id == user_id)
            .order_by(BulkJobModel.created_at.desc())
            .limit(limit)
        )
        jobs = result.scalars().all()
        
        return [
            {
                "job_id": j.job_id,
                "name": j.name,
                "status": j.status,
                "total_sources": j.total_sources,
                "total_clips": j.total_clips_generated,
                "created_at": j.created_at.isoformat(),
            }
            for j in jobs
        ]
    
    async def _save_job(self, db: AsyncSession, job: BulkJob):
        """Save job to database."""
        from ...models import BulkJob as BulkJobModel
        
        # Check if exists
        existing = await db.get(BulkJobModel, job.job_id)
        
        if existing:
            # Update
            existing.status = job.status.value
            existing.sources = json.dumps([self._source_to_dict(s) for s in job.sources])
            existing.total_clips_generated = job.total_clips_generated
            existing.started_at = job.started_at
            existing.completed_at = job.completed_at
        else:
            # Create new
            new_job = BulkJobModel(
                job_id=job.job_id,
                user_id=job.user_id,
                name=job.name,
                status=job.status.value,
                sources=json.dumps([self._source_to_dict(s) for s in job.sources]),
                processing_config=job.processing_config,
                publish_config=job.publish_config,
                total_sources=len(job.sources),
                total_clips_generated=job.total_clips_generated,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
            )
            db.add(new_job)
        
        await db.commit()
    
    async def _load_job(
        self,
        db: AsyncSession,
        job_id: str,
    ) -> Optional[BulkJob]:
        """Load job from database."""
        from ...models import BulkJob as BulkJobModel
        
        result = await db.execute(
            select(BulkJobModel).where(BulkJobModel.job_id == job_id)
        )
        db_job = result.scalar_one_or_none()
        
        if not db_job:
            return None
        
        # Reconstruct
        sources_data = json.loads(db_job.sources)
        sources = [self._dict_to_source(s) for s in sources_data]
        
        return BulkJob(
            job_id=db_job.job_id,
            user_id=db_job.user_id,
            name=db_job.name,
            status=BulkJobStatus(db_job.status),
            sources=sources,
            processing_config=db_job.processing_config,
            publish_config=db_job.publish_config,
            created_at=db_job.created_at,
            started_at=db_job.started_at,
            completed_at=db_job.completed_at,
            total_clips_generated=db_job.total_clips_generated,
        )
    
    def _source_to_dict(self, source: SourceItem) -> Dict[str, Any]:
        """Convert SourceItem to dict."""
        return {
            "item_id": source.item_id,
            "source_type": source.source_type,
            "source_url": source.source_url,
            "title": source.title,
            "status": source.status.value,
            "task_id": source.task_id,
            "clips_generated": source.clips_generated,
            "error_message": source.error_message,
            "started_at": source.started_at.isoformat() if source.started_at else None,
            "completed_at": source.completed_at.isoformat() if source.completed_at else None,
        }
    
    def _dict_to_source(self, data: Dict[str, Any]) -> SourceItem:
        """Convert dict to SourceItem."""
        return SourceItem(
            item_id=data["item_id"],
            source_type=data["source_type"],
            source_url=data["source_url"],
            title=data.get("title"),
            status=SourceItemStatus(data.get("status", "pending")),
            task_id=data.get("task_id"),
            clips_generated=data.get("clips_generated", 0),
            error_message=data.get("error_message"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
        )
    
    async def validate_sources(
        self,
        sources: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Validate a list of sources before creating job.
        
        Returns validation results with any errors.
        """
        valid = []
        invalid = []
        
        for source in sources:
            url = source.get("url", "")
            
            # Basic validation
            if not url:
                invalid.append({"source": source, "error": "Missing URL"})
                continue
            
            if not url.startswith(("http://", "https://")):
                invalid.append({"source": source, "error": "Invalid URL format"})
                continue
            
            # Check if YouTube URL is valid format
            if "youtube" in url or "youtu.be" in url:
                if "watch?v=" not in url and "youtu.be/" not in url:
                    invalid.append({"source": source, "error": "Invalid YouTube URL format"})
                    continue
            
            valid.append(source)
        
        return {
            "valid_count": len(valid),
            "invalid_count": len(invalid),
            "valid_sources": valid,
            "invalid_sources": invalid,
            "can_proceed": len(valid) > 0,
        }


__all__ = ["BulkOperationsService", "BulkJob", "SourceItem", "BulkJobStatus"]
