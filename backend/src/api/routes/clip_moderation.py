"""
Clip Annotation, Notification & Content Moderation API Routes — Phase 21

Annotations:
  GET    /clips/{id}/annotation        → get annotation
  PUT    /clips/{id}/annotation        → set/replace annotation
  DELETE /clips/{id}/annotation        → delete annotation
  PATCH  /clips/{id}/annotation/field  → update single field

Moderation:
  POST   /clips/{id}/moderate          → scan transcript + cache result
  GET    /clips/{id}/moderate          → return cached result
  DELETE /clips/{id}/moderate          → evict cache

Notifications:
  GET    /notifications/{user_id}      → list notifications
  POST   /notifications/{user_id}      → push a notification
  PATCH  /notifications/{user_id}/{notif_id}/read  → mark read
  POST   /notifications/{user_id}/read-all         → mark all read
  DELETE /notifications/{user_id}      → clear all
  GET    /notifications/{user_id}/unread-count      → count
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["clip-moderation"])
logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────

class AnnotationRequest(BaseModel):
    note: str
    author: str = ""
    extra: Optional[Dict[str, Any]] = None


class AnnotationFieldUpdate(BaseModel):
    field: str
    value: str


class ModerationRequest(BaseModel):
    transcript: str


class NotificationPushRequest(BaseModel):
    type: str
    title: str
    body: str = ""
    extra: Optional[Dict[str, Any]] = None


# ── Annotations ────────────────────────────────────────────────────────────

@router.get("/clips/{clip_id}/annotation")
async def get_annotation(clip_id: str):
    from src.services.clip_annotation_service import get_annotation as svc_get
    ann = await svc_get(clip_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="No annotation found")
    return {"clip_id": clip_id, "annotation": ann}


@router.put("/clips/{clip_id}/annotation")
async def set_annotation(clip_id: str, body: AnnotationRequest):
    from src.services.clip_annotation_service import set_annotation as svc_set
    try:
        ann = await svc_set(clip_id, body.note, author=body.author, extra=body.extra)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"clip_id": clip_id, "annotation": ann}


@router.delete("/clips/{clip_id}/annotation")
async def delete_annotation(clip_id: str):
    from src.services.clip_annotation_service import delete_annotation as svc_del
    deleted = await svc_del(clip_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No annotation found")
    return {"deleted": True, "clip_id": clip_id}


@router.patch("/clips/{clip_id}/annotation/field")
async def update_annotation_field(clip_id: str, body: AnnotationFieldUpdate):
    from src.services.clip_annotation_service import update_annotation_field as svc_upd
    updated = await svc_upd(clip_id, body.field, body.value)
    if not updated:
        raise HTTPException(status_code=404, detail="No annotation found to update")
    return {"updated": True, "clip_id": clip_id, "field": body.field}


# ── Moderation ─────────────────────────────────────────────────────────────

@router.post("/clips/{clip_id}/moderate")
async def moderate_clip(clip_id: str, body: ModerationRequest):
    from src.services.content_moderation_service import moderate_clip as svc_mod
    result = await svc_mod(clip_id, body.transcript)
    return result


@router.get("/clips/{clip_id}/moderate")
async def get_moderation(clip_id: str):
    from src.services.content_moderation_service import get_moderation_result
    result = await get_moderation_result(clip_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No moderation result cached")
    return result


@router.delete("/clips/{clip_id}/moderate")
async def clear_moderation(clip_id: str):
    from src.services.content_moderation_service import clear_moderation_cache
    await clear_moderation_cache(clip_id)
    return {"cleared": True, "clip_id": clip_id}


# ── Notifications ──────────────────────────────────────────────────────────

@router.get("/notifications/{user_id}")
async def list_notifications(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
):
    from src.services.inapp_notification_service import get_notifications
    notifs = await get_notifications(user_id, limit=limit, unread_only=unread_only)
    return {"user_id": user_id, "count": len(notifs), "notifications": notifs}


@router.post("/notifications/{user_id}")
async def push_notification(user_id: str, body: NotificationPushRequest):
    from src.services.inapp_notification_service import push_notification as svc_push
    notif = await svc_push(user_id, body.type, body.title, body.body, extra=body.extra)
    return {"user_id": user_id, "notification": notif}


@router.patch("/notifications/{user_id}/{notif_id}/read")
async def mark_notification_read(user_id: str, notif_id: str):
    from src.services.inapp_notification_service import mark_read
    found = await mark_read(user_id, notif_id)
    if not found:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"marked_read": True, "notif_id": notif_id}


@router.post("/notifications/{user_id}/read-all")
async def mark_all_read(user_id: str):
    from src.services.inapp_notification_service import mark_all_read as svc_all
    count = await svc_all(user_id)
    return {"marked_read": count, "user_id": user_id}


@router.delete("/notifications/{user_id}")
async def clear_notifications(user_id: str):
    from src.services.inapp_notification_service import clear_notifications as svc_clear
    await svc_clear(user_id)
    return {"cleared": True, "user_id": user_id}


@router.get("/notifications/{user_id}/unread-count")
async def get_unread_count(user_id: str):
    from src.services.inapp_notification_service import unread_count
    count = await unread_count(user_id)
    return {"user_id": user_id, "unread_count": count}
