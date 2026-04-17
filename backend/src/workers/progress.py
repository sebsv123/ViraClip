"""
Progress tracking — routes all updates through the EventBus so the SSE
endpoint receives properly named events.

Redis setex (key-value) is still written for the polling fallback used by
the task status endpoint; EventBus handles pub/sub for real-time streaming.
"""
import json
import logging
from typing import AsyncGenerator, Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ProgressTracker:
    """
    Track job progress for a single task.

    Every update is:
      1. Stored as a Redis key (setex, TTL 1 h) for polling.
      2. Published via EventBus so connected SSE streams receive it as a
         named event that the frontend addEventListener() can handle.
    """

    def __init__(self, redis: Redis, task_id: str):
        self.redis = redis
        self.task_id = task_id
        self.key = f"progress:{task_id}"

    async def update(self, progress: int, message: str, status: str = "processing"):
        """
        Emit a generic progress update.

        Args:
            progress: 0–100 percentage
            message:  human-readable status message
            status:   "processing" | "completed" | "error" | "queued"
        """
        from ..events.bus import EventBus
        from ..events.types import EventType, PipelineEvent

        # --- polling key (unchanged contract) ---
        snapshot = {
            "task_id": self.task_id,
            "progress": progress,
            "message":  message,
            "status":   status,
        }
        await self.redis.setex(self.key, 3600, json.dumps(snapshot))

        # --- map status → EventType ---
        _type_map = {
            "completed": EventType.DONE,
            "error":     EventType.ERROR,
            "failed":    EventType.ERROR,
            "queued":    EventType.CONNECTED,
        }
        event_type = _type_map.get(status, EventType.ANALYSIS)

        await EventBus.publish(PipelineEvent(
            task_id=self.task_id,
            event_type=event_type,
            stage=status,
            progress=min(100, max(0, progress)),
            message=message,
            status=status,
        ))

        logger.debug("ProgressTracker %s: %d%% [%s] — %s", self.task_id, progress, status, message)

    async def get(self) -> Optional[dict]:
        """Return the last snapshot stored in Redis (for polling endpoints)."""
        raw = await self.redis.get(self.key)
        return json.loads(raw) if raw else None

    async def clip_ready(self, clip_index: int, total_clips: int, clip_data: dict):
        """Emit a clip_ready event — triggers the frontend clip_ready listener."""
        from ..events.bus import EventBus
        from ..events.types import EventType, PipelineEvent

        pct = int((clip_index + 1) / max(total_clips, 1) * 100)
        await EventBus.publish(PipelineEvent(
            task_id=self.task_id,
            event_type=EventType.CLIP_READY,
            stage="render",
            progress=pct,
            message=f"Clip {clip_index + 1} of {total_clips} ready",
            clip_index=clip_index,
            total_clips=total_clips,
            clip_data=clip_data,
        ))

    async def complete(self, message: str = "Complete!"):
        """Mark task as completed — triggers the frontend 'close' listener."""
        await self.update(100, message, "completed")

    async def error(self, message: str):
        """Mark task as failed — triggers the frontend 'error' listener."""
        await self.update(0, message, "error")

    @staticmethod
    async def subscribe_to_progress(redis: Redis, task_id: str) -> AsyncGenerator[dict, None]:
        """
        Legacy compatibility shim — delegates to EventBus and yields dicts.
        Prefer using EventBus.subscribe() directly in new code.
        """
        from ..events.bus import EventBus

        async for event in EventBus.subscribe(task_id):
            yield event.to_dict()
