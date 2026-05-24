"""
EventBus — Redis pub/sub backbone for pipeline progress events.

All pipeline stages call EventBus.publish(); the SSE endpoint calls
EventBus.subscribe() and streams the results to the browser.

Channel name: progress:{task_id}
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis

from ..config import get_config
from .types import PipelineEvent

logger = logging.getLogger(__name__)

# Module-level singleton — patchable in tests via:
#   monkeypatch.setattr("src.events.bus._redis_client", fake_redis)
# or by patching _get_redis.
_redis_client: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    """Return (or create) the shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        config = get_config()
        _redis_client = await aioredis.from_url(
            f"redis://{config.redis_host}:{config.redis_port}",
            password=config.redis_password or None,
            decode_responses=True,
        )
        logger.info(
            "📮 [EventBus] Redis client created: %s:%s",
            config.redis_host,
            config.redis_port,
        )
    return _redis_client


def _channel(task_id: str) -> str:
    return f"progress:{task_id}"


class EventBus:
    """
    Central event bus for the ViraClip pipeline.

    Usage — emit from pipeline stage:
        await EventBus.publish(PipelineEvent(
            task_id=task_id,
            event_type=EventType.SCORING,
            stage="scoring",
            progress=50,
            message="Scoring viral segments…",
        ))

    Usage — subscribe in SSE endpoint:
        async for event in EventBus.subscribe(task_id):
            yield event_to_sse(event)
            if event.is_terminal:
                break
    """

    @staticmethod
    async def publish(event: PipelineEvent) -> None:
        """
        Publish a PipelineEvent to the task's Redis pub/sub channel.

        Failures are logged but never re-raised — progress loss is
        preferable to crashing the pipeline.
        """
        try:
            redis = await _get_redis()
            payload = json.dumps(event.to_dict())
            await redis.publish(_channel(event.task_id), payload)
            # Persist last known state so late subscribers can catch up
            await redis.setex(
                f"progress:last:{event.task_id}",
                3600,
                payload,
            )
            logger.debug(
                "📡 [EventBus] publish task=%s type=%s progress=%d%%",
                event.task_id,
                event.event_type,
                event.progress,
            )
        except Exception as exc:
            logger.error(
                "[EventBus] publish failed for task %s: %s",
                event.task_id,
                exc,
            )

    @staticmethod
    async def subscribe(task_id: str) -> AsyncGenerator[PipelineEvent, None]:
        """
        Subscribe to all events for *task_id*.

        Yields PipelineEvent objects until the generator is closed or a
        terminal event is received. The caller is responsible for breaking
        on event.is_terminal.

        NOTE: Uses a *separate* Redis client for pub/sub to avoid blocking
        the shared client used by publish() and is_active(). A subscribed
        pubsub connection enters "listener mode" and cannot perform other
        operations — a separate client prevents interference.
        """
        redis = await _get_redis()
        channel = _channel(task_id)

        # Create a dedicated Redis client for the pubsub subscription so the
        # shared _redis_client singleton remains usable for publish() etc.
        config = get_config()
        sub_redis = await aioredis.from_url(
            f"redis://{config.redis_host}:{config.redis_port}",
            password=config.redis_password or None,
            decode_responses=True,
        )
        pubsub = sub_redis.pubsub()

        try:
            await pubsub.subscribe(channel)
            logger.info("📡 [EventBus] subscribed to %s", channel)

            # Send last known state to new subscribers (avoids race condition)
            try:
                last = await redis.get(f"progress:last:{task_id}")
                if last:
                    data = json.loads(last)
                    event = PipelineEvent.from_dict(data)
                    yield event
            except Exception as exc:
                logger.warning(
                    "[EventBus] could not replay last event for %s: %s",
                    task_id, exc,
                )

            # Loop with heartbeat to avoid SSE timeout
            import asyncio as _asyncio

            while True:
                try:
                    message = await _asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=15.0,
                    )
                except _asyncio.TimeoutError:
                    # Emit keepalive (progress=-1 signals heartbeat to frontend)
                    yield PipelineEvent(
                        task_id=task_id,
                        event_type="heartbeat",
                        stage="heartbeat",
                        progress=-1,
                        message="keepalive",
                    )
                    continue

                if message is None:
                    await _asyncio.sleep(0.05)
                    continue

                if message.get("type") != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                    event = PipelineEvent.from_dict(data)
                    yield event
                except Exception as exc:
                    logger.error(
                        "[EventBus] failed to deserialise message on %s: %s — %s",
                        channel,
                        message.get("data"),
                        exc,
                    )
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
            logger.info("📡 [EventBus] unsubscribed from %s", channel)

    @staticmethod
    async def is_active(task_id: str) -> bool:
        """Return True if at least one client is subscribed to this task."""
        try:
            redis = await _get_redis()
            result = await redis.execute_command("PUBSUB", "NUMSUB", _channel(task_id))
            if len(result) >= 2:
                return int(result[1]) > 0
        except Exception as exc:
            logger.error("[EventBus] is_active check failed: %s", exc)
        return False

    @staticmethod
    async def reset() -> None:
        """Close and discard the shared Redis client (useful in tests)."""
        global _redis_client
        if _redis_client is not None:
            try:
                await _redis_client.aclose()
            except Exception:
                pass
            _redis_client = None
