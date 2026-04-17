"""
Smart Notifications API — ViraClip

Endpoints for sending, reading, and managing ML-optimised notifications
across email, push, SMS, Slack, Discord, and in-app channels.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.smart_notifications import (
    NotificationChannel,
    NotificationPriority,
    NotificationType,
    get_notification_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SendNotificationRequest(BaseModel):
    user_id: str
    notification_type: str          # clip_ready | viral_milestone | task_completed | system_alert | collaboration | marketing | security
    priority: str = "normal"        # critical | high | normal | low
    title: str
    message: str
    data: Dict[str, Any] = {}
    channels: Optional[List[str]] = None   # override channel selection


class BatchSendRequest(BaseModel):
    user_ids: List[str]
    notification_type: str
    priority: str = "normal"
    title: str
    message: str
    data: Dict[str, Any] = {}


class SetPreferencesRequest(BaseModel):
    channels: List[str] = ["email", "in_app"]
    quiet_hours_start: int = 22
    quiet_hours_end: int = 8
    timezone: str = "UTC"
    max_per_hour: int = 10
    ml_optimized: bool = True


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_type(value: str) -> NotificationType:
    try:
        return NotificationType(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid notification_type '{value}'. "
                   f"Choose: {[t.value for t in NotificationType]}",
        )


def _parse_priority(value: str) -> NotificationPriority:
    try:
        return NotificationPriority(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{value}'. "
                   f"Choose: {[p.value for p in NotificationPriority]}",
        )


def _parse_channels(values: List[str]) -> List[NotificationChannel]:
    result = []
    for v in values:
        try:
            result.append(NotificationChannel(v))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid channel '{v}'. Choose: {[c.value for c in NotificationChannel]}",
            )
    return result


# ------------------------------------------------------------------
# Send
# ------------------------------------------------------------------

@router.post("/send")
async def send_notification(body: SendNotificationRequest):
    """
    Send a smart notification to a user.
    The service uses ML to select optimal delivery channels and timing
    unless explicit `channels` are supplied.
    """
    svc = get_notification_service()
    channels = _parse_channels(body.channels) if body.channels else None

    try:
        notif = await svc.send_notification(
            user_id=body.user_id,
            notification_type=_parse_type(body.notification_type),
            priority=_parse_priority(body.priority),
            title=body.title,
            message=body.message,
            data=body.data,
            channels=channels,
        )
        return {
            "status": "sent",
            "notification_id": notif.notification_id,
            "scheduled_for": notif.scheduled_for,
            "channels": [c.value for c in notif.channels],
            "engagement_score": round(notif.engagement_score, 3),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Notifications] send failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send/batch")
async def batch_send(body: BatchSendRequest):
    """Send the same notification to multiple users at once."""
    if not body.user_ids:
        raise HTTPException(status_code=400, detail="user_ids must not be empty")

    svc = get_notification_service()
    try:
        notifs = await svc.batch_send(
            user_ids=body.user_ids,
            notification_type=_parse_type(body.notification_type),
            priority=_parse_priority(body.priority),
            title=body.title,
            message=body.message,
            data=body.data,
        )
        return {
            "status": "sent",
            "count": len(notifs),
            "notification_ids": [n.notification_id for n in notifs],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Inbox
# ------------------------------------------------------------------

@router.get("")
async def list_notifications(
    request: Request,
    unread_only: bool = False,
    limit: int = 50,
):
    """List notifications for the current user, newest first."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_notification_service()
    items = svc.get_user_notifications(
        user_id=user_id, unread_only=unread_only, limit=limit
    )
    unread = [n for n in items if not n.get("read_at")]
    return {
        "status": "success",
        "count": len(items),
        "unread_count": len(unread),
        "notifications": items,
    }


@router.post("/{notification_id}/read")
async def mark_as_read(notification_id: str):
    """Mark a notification as read and record the engagement event."""
    svc = get_notification_service()
    success = await svc.mark_as_read(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Notification '{notification_id}' not found")
    return {"status": "read", "notification_id": notification_id}


# ------------------------------------------------------------------
# Stats & preferences
# ------------------------------------------------------------------

@router.get("/stats")
async def notification_stats(request: Request):
    """Delivery rate, read rate, average engagement score, and per-type breakdown."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_notification_service()
    stats = svc.get_notification_stats(user_id)
    return {"status": "success", "stats": stats}


@router.put("/preferences")
async def set_preferences(request: Request, body: SetPreferencesRequest):
    """Update notification delivery preferences for the current user."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_notification_service()
    channels = _parse_channels(body.channels)

    try:
        prefs = await svc.set_user_preferences(
            user_id=user_id,
            channels=channels,
            quiet_hours=(body.quiet_hours_start, body.quiet_hours_end),
            timezone=body.timezone,
            max_per_hour=body.max_per_hour,
            ml_optimized=body.ml_optimized,
        )
        return {
            "status": "updated",
            "user_id": user_id,
            "channels": [c.value for c in prefs.channels],
            "quiet_hours": [prefs.quiet_hours_start, prefs.quiet_hours_end],
            "timezone": prefs.timezone,
            "ml_optimized": prefs.ml_optimized,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/channels")
def list_channels():
    """List all valid notification channels, types, and priorities."""
    return {
        "channels": [c.value for c in NotificationChannel],
        "types": [t.value for t in NotificationType],
        "priorities": [p.value for p in NotificationPriority],
    }
