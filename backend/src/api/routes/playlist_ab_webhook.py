"""
Playlist, A/B Test & Webhook Event Log API Routes — Phase 22

Playlists:
  POST   /playlists                              → create playlist
  GET    /playlists/{user_id}                    → list all playlists
  GET    /playlists/{user_id}/{playlist_id}      → get playlist + clips
  DELETE /playlists/{user_id}/{playlist_id}      → delete playlist
  POST   /playlists/{user_id}/{playlist_id}/clips → add clip
  DELETE /playlists/{user_id}/{playlist_id}/clips/{clip_id} → remove clip

A/B Tests:
  POST   /ab-tests/{clip_id}/variants            → create variant
  GET    /ab-tests/{clip_id}/variants            → list all variants + stats
  GET    /ab-tests/{clip_id}/variants/{vid}      → single variant stats
  POST   /ab-tests/{clip_id}/variants/{vid}/impression → record impression
  POST   /ab-tests/{clip_id}/variants/{vid}/click     → record click
  DELETE /ab-tests/{clip_id}/variants/{vid}      → delete variant

Webhook Event Log:
  POST   /webhook-log/{user_id}                  → log an event
  GET    /webhook-log/{user_id}                  → get event log
  GET    /webhook-log/{user_id}/stats            → delivery stats
  PATCH  /webhook-log/{user_id}/{event_id}       → update status
  DELETE /webhook-log/{user_id}                  → clear log
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["playlist-ab-webhook"])
logger = logging.getLogger(__name__)


# ── Schemas ─────────────────────────────────────────────────────────────────

class PlaylistCreate(BaseModel):
    user_id: str
    name: str
    description: str = ""
    clip_ids: Optional[List[str]] = None


class ClipAdd(BaseModel):
    clip_id: str


class VariantCreate(BaseModel):
    label: str
    content: str = ""


class WebhookLogCreate(BaseModel):
    event_type: str
    url: str
    payload_summary: str = ""
    status: str = "pending"
    http_status: Optional[int] = None
    attempts: int = 0


class WebhookStatusUpdate(BaseModel):
    status: str
    http_status: Optional[int] = None
    attempts: Optional[int] = None


# ── Playlists ────────────────────────────────────────────────────────────────

@router.post("/playlists")
async def create_playlist(body: PlaylistCreate):
    from src.services.playlist_service import create_playlist as svc
    try:
        result = await svc(body.user_id, body.name, body.description,
                           clip_ids=body.clip_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/playlists/{user_id}")
async def list_playlists(user_id: str):
    from src.services.playlist_service import list_playlists as svc
    return {"user_id": user_id, "playlists": await svc(user_id)}


@router.get("/playlists/{user_id}/{playlist_id}")
async def get_playlist(user_id: str, playlist_id: str):
    from src.services.playlist_service import get_playlist as svc
    pl = await svc(user_id, playlist_id)
    if pl is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return pl


@router.delete("/playlists/{user_id}/{playlist_id}")
async def delete_playlist(user_id: str, playlist_id: str):
    from src.services.playlist_service import delete_playlist as svc
    deleted = await svc(user_id, playlist_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"deleted": True, "playlist_id": playlist_id}


@router.post("/playlists/{user_id}/{playlist_id}/clips")
async def add_clip(user_id: str, playlist_id: str, body: ClipAdd):
    from src.services.playlist_service import add_clip_to_playlist
    try:
        new_len = await add_clip_to_playlist(user_id, playlist_id, body.clip_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"playlist_id": playlist_id, "clip_id": body.clip_id, "total_clips": new_len}


@router.delete("/playlists/{user_id}/{playlist_id}/clips/{clip_id}")
async def remove_clip(user_id: str, playlist_id: str, clip_id: str):
    from src.services.playlist_service import remove_clip_from_playlist
    removed = await remove_clip_from_playlist(user_id, playlist_id, clip_id)
    return {"removed": removed, "playlist_id": playlist_id, "clip_id": clip_id}


# ── A/B Tests ────────────────────────────────────────────────────────────────

@router.post("/ab-tests/{clip_id}/variants")
async def create_variant(clip_id: str, body: VariantCreate):
    from src.services.ab_test_service import create_variant as svc
    try:
        return await svc(clip_id, body.label, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/ab-tests/{clip_id}/variants")
async def list_variants(clip_id: str):
    from src.services.ab_test_service import get_all_variants
    variants = await get_all_variants(clip_id)
    return {"clip_id": clip_id, "variants": variants}


@router.get("/ab-tests/{clip_id}/variants/{variant_id}")
async def get_variant(clip_id: str, variant_id: str):
    from src.services.ab_test_service import get_variant_stats
    stats = await get_variant_stats(clip_id, variant_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return stats


@router.post("/ab-tests/{clip_id}/variants/{variant_id}/impression")
async def record_impression(clip_id: str, variant_id: str):
    from src.services.ab_test_service import record_impression as svc
    count = await svc(clip_id, variant_id)
    return {"clip_id": clip_id, "variant_id": variant_id, "impressions": count}


@router.post("/ab-tests/{clip_id}/variants/{variant_id}/click")
async def record_click(clip_id: str, variant_id: str):
    from src.services.ab_test_service import record_click as svc
    count = await svc(clip_id, variant_id)
    return {"clip_id": clip_id, "variant_id": variant_id, "clicks": count}


@router.delete("/ab-tests/{clip_id}/variants/{variant_id}")
async def delete_variant(clip_id: str, variant_id: str):
    from src.services.ab_test_service import delete_variant as svc
    deleted = await svc(clip_id, variant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Variant not found")
    return {"deleted": True, "variant_id": variant_id}


# ── Webhook Event Log ────────────────────────────────────────────────────────

@router.post("/webhook-log/{user_id}")
async def log_webhook_event(user_id: str, body: WebhookLogCreate):
    from src.services.webhook_event_log_service import log_event
    entry = await log_event(user_id, body.event_type, body.url,
                             body.payload_summary, body.status,
                             body.http_status, body.attempts)
    return entry


@router.get("/webhook-log/{user_id}")
async def get_webhook_log(
    user_id: str,
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None),
):
    from src.services.webhook_event_log_service import get_event_log
    entries = await get_event_log(user_id, limit=limit, status_filter=status)
    return {"user_id": user_id, "count": len(entries), "events": entries}


@router.get("/webhook-log/{user_id}/stats")
async def webhook_stats(user_id: str):
    from src.services.webhook_event_log_service import get_event_stats
    return await get_event_stats(user_id)


@router.patch("/webhook-log/{user_id}/{event_id}")
async def update_webhook_status(user_id: str, event_id: str, body: WebhookStatusUpdate):
    from src.services.webhook_event_log_service import update_event_status
    updated = await update_event_status(user_id, event_id, body.status,
                                        body.http_status, body.attempts)
    if not updated:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"updated": True, "event_id": event_id, "status": body.status}


@router.delete("/webhook-log/{user_id}")
async def clear_webhook_log(user_id: str):
    from src.services.webhook_event_log_service import clear_event_log
    await clear_event_log(user_id)
    return {"cleared": True, "user_id": user_id}
