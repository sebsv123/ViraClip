"""
WebSocket endpoint for real-time task progress.

Replaces polling with Redis pub/sub for granular progress updates.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["progress"])


async def _get_redis_client():
    """Get Redis client for pub/sub."""
    try:
        import redis.asyncio as aioredis
        cfg = get_config()
        r = aioredis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            password=cfg.redis_password or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await r.ping()
        return r
    except Exception:
        return None


@router.websocket("/ws/tasks/{task_id}/progress")
async def task_progress_ws(websocket: WebSocket, task_id: str):
    """
    WebSocket para progreso en tiempo real del re-render de un task.

    Escucha el canal Redis ``progress:{task_id}`` y reenvía los mensajes
    al cliente WebSocket. Se cierra automáticamente cuando el stage es
    ``"done"`` o ``"error"``.

    Si Redis no está disponible, envía un mensaje de error y cierra.
    """
    await websocket.accept()
    logger.debug("[WS] Cliente conectado a progress:%s", task_id)

    redis_client = await _get_redis_client()
    if redis_client is None:
        await websocket.send_text(json.dumps({
            "stage": "error",
            "percent": 0,
            "detail": "Redis no disponible — no se puede obtener progreso en tiempo real",
            "timestamp": 0,
        }))
        await websocket.close()
        return

    pubsub = redis_client.pubsub()
    try:
        await pubsub.subscribe(f"progress:{task_id}")
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    await websocket.send_text(message["data"])
                    data = json.loads(message["data"])
                    if data.get("stage") in ("done", "error"):
                        break
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.debug("[WS] Cliente desconectado de progress:%s", task_id)
    except Exception as exc:
        logger.warning("[WS] Error en WebSocket progress:%s: %s", task_id, exc)
    finally:
        try:
            await pubsub.unsubscribe(f"progress:{task_id}")
            await pubsub.close()
            await redis_client.aclose()
        except Exception:
            pass
