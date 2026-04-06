"""
In-App Notification Service — Phase 21

Stores per-user notifications in a Redis list (newest first).
Key schema: notifications:{user_id}  →  Redis LIST of JSON strings

Max _MAX_NOTIFS notifications per user (oldest trimmed automatically).
Each notification has: id, type, title, body, read, created_at
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_NOTIFS = 100
_KEY_PREFIX = "notifications"


def _key(user_id: str) -> str:
    return f"{_KEY_PREFIX}:{user_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


# ── Public API ────────────────────────────────────────────────────────────────

async def push_notification(
    user_id: str,
    notif_type: str,
    title: str,
    body: str = "",
    extra: Optional[Dict] = None,
) -> Dict:
    """Push a new notification to the front of the user's notification list."""
    notif = {
        "id": str(uuid.uuid4()),
        "type": notif_type,
        "title": title,
        "body": body,
        "read": False,
        "created_at": _now(),
        **(extra or {}),
    }
    try:
        r = await _redis()
        await r.lpush(_key(user_id), json.dumps(notif))
        await r.ltrim(_key(user_id), 0, _MAX_NOTIFS - 1)
        logger.debug("[notif] pushed user=%s type=%s", user_id, notif_type)
    except Exception as exc:
        logger.warning("[notif] push failed user=%s: %s", user_id, exc)
    return notif


async def get_notifications(
    user_id: str,
    limit: int = 20,
    unread_only: bool = False,
) -> List[Dict]:
    """Return up to `limit` notifications for a user (newest first)."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_NOTIFS - 1)
        notifs = []
        for item in raw:
            try:
                n = json.loads(item.decode() if isinstance(item, bytes) else item)
                if unread_only and n.get("read"):
                    continue
                notifs.append(n)
                if len(notifs) >= limit:
                    break
            except Exception:
                pass
        return notifs
    except Exception as exc:
        logger.warning("[notif] get failed user=%s: %s", user_id, exc)
        return []


async def mark_read(user_id: str, notif_id: str) -> bool:
    """Mark a specific notification as read. Returns True if found and updated."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_NOTIFS - 1)
        for i, item in enumerate(raw):
            n = json.loads(item.decode() if isinstance(item, bytes) else item)
            if n.get("id") == notif_id:
                n["read"] = True
                await r.lset(_key(user_id), i, json.dumps(n))
                return True
        return False
    except Exception as exc:
        logger.warning("[notif] mark_read failed user=%s: %s", user_id, exc)
        return False


async def mark_all_read(user_id: str) -> int:
    """Mark all notifications as read. Returns the count updated."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_NOTIFS - 1)
        count = 0
        for i, item in enumerate(raw):
            n = json.loads(item.decode() if isinstance(item, bytes) else item)
            if not n.get("read"):
                n["read"] = True
                await r.lset(_key(user_id), i, json.dumps(n))
                count += 1
        return count
    except Exception as exc:
        logger.warning("[notif] mark_all_read failed user=%s: %s", user_id, exc)
        return 0


async def clear_notifications(user_id: str) -> None:
    """Delete all notifications for a user."""
    try:
        r = await _redis()
        await r.delete(_key(user_id))
    except Exception as exc:
        logger.warning("[notif] clear failed user=%s: %s", user_id, exc)


async def unread_count(user_id: str) -> int:
    """Return the number of unread notifications."""
    notifs = await get_notifications(user_id, limit=_MAX_NOTIFS, unread_only=True)
    return len(notifs)
