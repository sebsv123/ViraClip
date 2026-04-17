"""
User Activity Log Service — Phase 24

Append-only log of user actions stored in a Redis list.
Key schema: activity_log:{user_id}  → Redis LIST of JSON records (newest first)

Each record: log_id, action, resource_type, resource_id, metadata, created_at
Max 1000 entries per user; TTL 90 days.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 1000
_TTL = 60 * 60 * 24 * 90  # 90 days


def _key(user_id: str) -> str:
    return f"activity_log:{user_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def log_action(
    user_id: str,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    metadata: Optional[Dict] = None,
) -> Dict:
    """Append a new action record. Returns the record dict."""
    record = {
        "log_id": str(uuid.uuid4()),
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "metadata": metadata or {},
        "created_at": _now(),
    }
    try:
        r = await _redis()
        await r.lpush(_key(user_id), json.dumps(record))
        await r.ltrim(_key(user_id), 0, _MAX_ENTRIES - 1)
        await r.expire(_key(user_id), _TTL)
    except Exception as exc:
        logger.warning("[activity_log] log_action failed user=%s: %s", user_id, exc)
    return record


async def get_activity_log(
    user_id: str,
    limit: int = 50,
    action_filter: Optional[str] = None,
    resource_type_filter: Optional[str] = None,
) -> List[Dict]:
    """Return recent activity records (newest first)."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_ENTRIES - 1)
        results = []
        for item in raw:
            rec = json.loads(item.decode() if isinstance(item, bytes) else item)
            if action_filter and rec.get("action") != action_filter:
                continue
            if resource_type_filter and rec.get("resource_type") != resource_type_filter:
                continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results
    except Exception as exc:
        logger.warning("[activity_log] get failed user=%s: %s", user_id, exc)
        return []


async def get_activity_stats(user_id: str) -> Dict:
    """Return action frequency counts for a user."""
    records = await get_activity_log(user_id, limit=_MAX_ENTRIES)
    action_counts: Dict[str, int] = {}
    for rec in records:
        action = rec.get("action", "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1
    return {
        "user_id": user_id,
        "total_actions": len(records),
        "action_counts": action_counts,
    }


async def clear_activity_log(user_id: str) -> None:
    """Delete all activity log entries for a user."""
    try:
        r = await _redis()
        await r.delete(_key(user_id))
    except Exception as exc:
        logger.warning("[activity_log] clear failed user=%s: %s", user_id, exc)
