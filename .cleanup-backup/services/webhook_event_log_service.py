"""
Webhook Event Log Service — Phase 22

Stores outgoing webhook event records in Redis lists.
Key schema: webhook_log:{user_id}  → Redis LIST of JSON objects (newest first)

Each log entry contains: event_id, event_type, url, payload_summary,
status (pending/delivered/failed), http_status, attempts, created_at, delivered_at

Max 500 log entries per user; entries expire after 30 days.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_LOG_ENTRIES = 500
_LOG_TTL = 60 * 60 * 24 * 30  # 30 days


def _key(user_id: str) -> str:
    return f"webhook_log:{user_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def log_event(
    user_id: str,
    event_type: str,
    url: str,
    payload_summary: str = "",
    status: str = "pending",
    http_status: Optional[int] = None,
    attempts: int = 0,
) -> Dict:
    """Create a new webhook event log entry. Returns the log entry dict."""
    entry = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "url": url,
        "payload_summary": payload_summary[:500],
        "status": status,
        "http_status": http_status,
        "attempts": attempts,
        "created_at": _now(),
        "delivered_at": None,
    }
    try:
        r = await _redis()
        await r.lpush(_key(user_id), json.dumps(entry))
        await r.ltrim(_key(user_id), 0, _MAX_LOG_ENTRIES - 1)
        await r.expire(_key(user_id), _LOG_TTL)
    except Exception as exc:
        logger.warning("[webhook_log] log_event failed user=%s: %s", user_id, exc)
    return entry


async def update_event_status(
    user_id: str,
    event_id: str,
    status: str,
    http_status: Optional[int] = None,
    attempts: Optional[int] = None,
) -> bool:
    """Update delivery status of an existing log entry. Returns True if found."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_LOG_ENTRIES - 1)
        for i, item in enumerate(raw):
            entry = json.loads(item.decode() if isinstance(item, bytes) else item)
            if entry.get("event_id") == event_id:
                entry["status"] = status
                if http_status is not None:
                    entry["http_status"] = http_status
                if attempts is not None:
                    entry["attempts"] = attempts
                if status == "delivered":
                    entry["delivered_at"] = _now()
                await r.lset(_key(user_id), i, json.dumps(entry))
                return True
        return False
    except Exception as exc:
        logger.warning("[webhook_log] update_event_status failed: %s", exc)
        return False


async def get_event_log(
    user_id: str,
    limit: int = 50,
    status_filter: Optional[str] = None,
) -> List[Dict]:
    """Return recent webhook log entries for a user."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_LOG_ENTRIES - 1)
        results = []
        for item in raw:
            entry = json.loads(item.decode() if isinstance(item, bytes) else item)
            if status_filter and entry.get("status") != status_filter:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results
    except Exception as exc:
        logger.warning("[webhook_log] get_event_log failed: %s", exc)
        return []


async def clear_event_log(user_id: str) -> None:
    """Delete all log entries for a user."""
    try:
        r = await _redis()
        await r.delete(_key(user_id))
    except Exception as exc:
        logger.warning("[webhook_log] clear_event_log failed: %s", exc)


async def get_event_stats(user_id: str) -> Dict:
    """Return delivery statistics: total, delivered, failed, pending."""
    entries = await get_event_log(user_id, limit=_MAX_LOG_ENTRIES)
    stats: Dict[str, int] = {"total": len(entries), "delivered": 0, "failed": 0, "pending": 0}
    for e in entries:
        s = e.get("status", "pending")
        if s in stats:
            stats[s] += 1
    return stats
