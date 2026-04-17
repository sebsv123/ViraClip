"""
Batch Processing Service
Handles processing of multiple videos in batch with parallel execution.
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


class BatchStatus(Enum):
    """Status of batch processing job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Some videos failed
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchJob:
    """A batch processing job."""
    batch_id: str
    user_id: str
    name: str
    video_urls: List[str]
    settings: Dict[str, Any]
    status: BatchStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    progress: int = 0  # 0-100
    total_clips_generated: int = 0


class BatchProcessor:
    """
    Processor for batch video operations.
    """
    
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._jobs: Dict[str, BatchJob] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
    
    async def create_batch_job(
        self,
        user_id: str,
        video_urls: List[str],
        settings: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None
    ) -> BatchJob:
        """Create a new batch processing job."""
        batch_id = str(uuid.uuid4())
        
        job = BatchJob(
            batch_id=batch_id,
            user_id=user_id,
            name=name or f"Batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            video_urls=video_urls,
            settings=settings or {},
            status=BatchStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        self._jobs[batch_id] = job
        
        logger.info(f"Created batch job {batch_id} with {len(video_urls)} videos")
        return job
    
    async def start_batch_processing(self, batch_id: str) -> bool:
        """Start processing a batch job."""
        if batch_id not in self._jobs:
            return False
        
        job = self._jobs[batch_id]
        
        if job.status != BatchStatus.PENDING:
            logger.warning(f"Batch {batch_id} is not in pending state")
            return False
        
        job.status = BatchStatus.PROCESSING
        job.started_at = datetime.now().isoformat()
        
        # Start processing in background
        task = asyncio.create_task(self._process_batch(batch_id))
        self._active_tasks[batch_id] = task
        
        return True
    
    async def _process_batch(self, batch_id: str) -> None:
        """Process all videos in batch."""
        job = self._jobs[batch_id]
        
        try:
            # Process videos with limited concurrency
            semaphore = asyncio.Semaphore(self.max_concurrent)
            
            tasks = []
            for i, url in enumerate(job.video_urls):
                task = self._process_single_video(semaphore, job, url, i)
                tasks.append(task)
            
            # Wait for all to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            success_count = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    job.errors.append({
                        "video_index": i,
                        "url": job.video_urls[i],
                        "error": str(result)
                    })
                else:
                    success_count += 1
                    job.results.append(result)
                    job.total_clips_generated += result.get("clip_count", 0)
            
            # Determine final status
            if success_count == len(job.video_urls):
                job.status = BatchStatus.COMPLETED
            elif success_count > 0:
                job.status = BatchStatus.PARTIAL
            else:
                job.status = BatchStatus.FAILED
            
            job.completed_at = datetime.now().isoformat()
            job.progress = 100
            
            logger.info(
                f"Batch {batch_id} completed: {success_count}/{len(job.video_urls)} videos successful"
            )
            
        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            job.status = BatchStatus.FAILED
            job.errors.append({"error": str(e)})
            job.completed_at = datetime.now().isoformat()
    
    async def _process_single_video(
        self,
        semaphore: asyncio.Semaphore,
        job: BatchJob,
        url: str,
        index: int
    ) -> Dict[str, Any]:
        """Process a single video with semaphore control."""
        async with semaphore:
            try:
                # Import here to avoid circular dependencies
                from ..services.video_service import VideoService
                
                logger.info(f"Processing video {index + 1}/{len(job.video_urls)}: {url}")
                
                # Process video
                result = await VideoService.process_video_complete(
                    url=url,
                    source_type="youtube",
                    **job.settings
                )
                
                # Update progress
                job.progress = int(((index + 1) / len(job.video_urls)) * 100)
                
                return {
                    "video_index": index,
                    "url": url,
                    "status": "success",
                    "clip_count": len(result.get("clips", [])),
                    "clips": result.get("clips", []),
                    "task_id": result.get("task_id")
                }
                
            except Exception as e:
                logger.error(f"Failed to process video {url}: {e}")
                raise
    
    async def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch job."""
        if batch_id not in self._jobs:
            return False
        
        job = self._jobs[batch_id]
        
        if job.status != BatchStatus.PROCESSING:
            return False
        
        # Cancel task
        if batch_id in self._active_tasks:
            self._active_tasks[batch_id].cancel()
            del self._active_tasks[batch_id]
        
        job.status = BatchStatus.CANCELLED
        job.completed_at = datetime.now().isoformat()
        
        return True
    
    def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a batch job."""
        if batch_id not in self._jobs:
            return None
        
        job = self._jobs[batch_id]
        
        return {
            "batch_id": job.batch_id,
            "name": job.name,
            "status": job.status.value,
            "progress": job.progress,
            "total_videos": len(job.video_urls),
            "processed": len(job.results) + len(job.errors),
            "successful": len(job.results),
            "failed": len(job.errors),
            "total_clips": job.total_clips_generated,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "errors": job.errors if job.status in [BatchStatus.FAILED, BatchStatus.PARTIAL] else []
        }
    
    def get_batch_results(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed results of a completed batch."""
        if batch_id not in self._jobs:
            return None
        
        job = self._jobs[batch_id]
        
        return {
            "batch_id": job.batch_id,
            "name": job.name,
            "status": job.status.value,
            "settings": job.settings,
            "results": job.results,
            "errors": job.errors,
            "summary": {
                "total_videos": len(job.video_urls),
                "successful": len(job.results),
                "failed": len(job.errors),
                "total_clips": job.total_clips_generated,
                "avg_clips_per_video": (
                    job.total_clips_generated / len(job.results)
                    if job.results else 0
                )
            }
        }
    
    def list_user_batches(
        self,
        user_id: str,
        status: Optional[BatchStatus] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List batch jobs for a user."""
        batches = [
            job for job in self._jobs.values()
            if job.user_id == user_id
        ]
        
        if status:
            batches = [b for b in batches if b.status == status]
        
        # Sort by created date
        batches.sort(key=lambda x: x.created_at, reverse=True)
        
        return [
            {
                "batch_id": b.batch_id,
                "name": b.name,
                "status": b.status.value,
                "progress": b.progress,
                "total_videos": len(b.video_urls),
                "created_at": b.created_at
            }
            for b in batches[:limit]
        ]


class BatchScheduler:
    """
    Scheduler for recurring batch jobs.
    """
    
    def __init__(self):
        self._scheduled: Dict[str, Dict[str, Any]] = {}
    
    def schedule_recurring_batch(
        self,
        user_id: str,
        name: str,
        source_playlist: str,
        schedule: str,  # cron format or simple like "daily", "weekly"
        settings: Dict[str, Any]
    ) -> str:
        """Schedule a recurring batch job."""
        schedule_id = str(uuid.uuid4())
        
        self._scheduled[schedule_id] = {
            "schedule_id": schedule_id,
            "user_id": user_id,
            "name": name,
            "source_playlist": source_playlist,
            "schedule": schedule,
            "settings": settings,
            "created_at": datetime.now().isoformat(),
            "last_run": None,
            "next_run": None,
            "active": True
        }
        
        return schedule_id


# Global instance
_batch_processor: Optional[BatchProcessor] = None


def get_batch_processor() -> BatchProcessor:
    """Get global batch processor."""
    global _batch_processor
    if _batch_processor is None:
        _batch_processor = BatchProcessor()
    return _batch_processor


# Convenience functions
async def submit_batch_job(
    user_id: str,
    video_urls: List[str],
    settings: Optional[Dict[str, Any]] = None
) -> str:
    """Submit a new batch job."""
    processor = get_batch_processor()
    job = await processor.create_batch_job(user_id, video_urls, settings)
    await processor.start_batch_processing(job.batch_id)
    return job.batch_id


def get_batch_status(batch_id: str) -> Optional[Dict[str, Any]]:
    """Get status of a batch job."""
    return get_batch_processor().get_batch_status(batch_id)
