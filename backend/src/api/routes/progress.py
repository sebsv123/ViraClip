"""
Server-Sent Events (SSE) streaming for real-time progress updates.

Uses the EventBus + SSE bridge so that every pipeline event is emitted
as a *named* SSE event.  Named events are required for the frontend's
EventSource.addEventListener("progress", ...) etc. to fire — a generic
data-only message would only trigger the unused "message" handler.

Frontend named event listeners wired in page.tsx:
    addEventListener("status",     handler)  ← initial connection ACK
    addEventListener("progress",   handler)  ← transcription / scoring / render
    addEventListener("clip_ready", handler)  ← individual clip is ready
    addEventListener("close",      handler)  ← pipeline finished (done / cache_hit)
    addEventListener("error",      handler)  ← pipeline error
"""

import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["progress"])

# Heartbeat interval in seconds — keeps proxies from closing idle SSE connections
_HEARTBEAT_INTERVAL = 15


async def pipeline_event_generator(task_id: str) -> AsyncGenerator[str, None]:
    """
    Subscribe to EventBus and stream named SSE events for *task_id*.

    1. Immediately yields a "status" event so the client knows it's connected.
    2. Yields a heartbeat comment every _HEARTBEAT_INTERVAL seconds to keep
       the connection alive through load-balancers and Nginx proxies.
    3. Maps each PipelineEvent to the correct named SSE event via sse_bridge.
    4. Closes automatically when a terminal event (done / error / cache_hit)
       is received.
    """
    from ...events.bus import EventBus
    from ...events.sse_bridge import event_to_sse, make_connected_sse, make_error_sse, make_heartbeat_sse

    try:
        logger.info("📡 SSE connected for task %s", task_id)
        yield make_connected_sse(task_id)

        # Wrap the EventBus async generator in a task so we can race it with
        # a periodic heartbeat without blocking on the next message.
        queue: asyncio.Queue = asyncio.Queue()

        async def _feed():
            _errored = False
            try:
                async for event in EventBus.subscribe(task_id):
                    await queue.put(event)
                    if event.is_terminal:
                        break
            except Exception as exc:
                logger.error("EventBus feed error for %s: %s", task_id, exc)
                _errored = True
                await queue.put(exc)   # signal error to main loop
            finally:
                if not _errored:
                    await queue.put(None)  # normal completion sentinel

        feed_task = asyncio.create_task(_feed())

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    yield make_heartbeat_sse()
                    continue

                if event is None:  # normal completion sentinel
                    break

                if isinstance(event, Exception):  # feed raised — emit error SSE
                    logger.error("SSE feed exception for task %s: %s", task_id, event)
                    yield make_error_sse(task_id, str(event))
                    break

                yield event_to_sse(event)
                logger.debug(
                    "📡 SSE → task=%s event=%s progress=%d%%",
                    task_id, event.event_type, event.progress,
                )

                if event.is_terminal:
                    logger.info(
                        "📡 SSE terminal '%s' for task %s — closing stream",
                        event.event_type, task_id,
                    )
                    break
        finally:
            feed_task.cancel()
            try:
                await feed_task
            except asyncio.CancelledError:
                pass

    except Exception as exc:
        logger.error("SSE generator error for task %s: %s", task_id, exc)
        yield make_error_sse(task_id, str(exc))


_SSE_HEADERS = {
    "Cache-Control":     "no-cache",
    "Connection":        "keep-alive",
    "X-Accel-Buffering": "no",        # Disable Nginx response buffering
    "Access-Control-Allow-Origin": "*",
}


@router.get("/{task_id}/stream")
async def stream_progress(task_id: str):
    """
    SSE endpoint — real-time task progress via named events.

    JavaScript usage:
        const es = new EventSource(`/api/tasks/${taskId}/progress`);
        es.addEventListener("status",     e => { const d = JSON.parse(e.data); ... });
        es.addEventListener("progress",   e => { const d = JSON.parse(e.data); setProgress(d.progress); });
        es.addEventListener("clip_ready", e => { const d = JSON.parse(e.data); addClip(d.clip_data); });
        es.addEventListener("close",      e => { es.close(); refreshClips(); });
        es.addEventListener("error",      e => { es.close(); showError(); });
    """
    if not task_id or len(task_id) < 10:
        raise HTTPException(status_code=400, detail="Invalid task_id")

    return StreamingResponse(
        pipeline_event_generator(task_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/{task_id}/progress")
async def stream_progress_alias(task_id: str):
    """
    Alias matching the frontend proxy path /api/tasks/{id}/progress.
    Delegates to the same generator as /stream.
    """
    return await stream_progress(task_id)


@router.get("/{task_id}/stream/health")
async def stream_health(task_id: str):
    """Return whether anyone is subscribed to this task's event channel."""
    from ...events.bus import EventBus

    is_active = await EventBus.is_active(task_id)
    return {
        "task_id":       task_id,
        "stream_active": is_active,
        "channel":       f"progress:{task_id}",
    }
