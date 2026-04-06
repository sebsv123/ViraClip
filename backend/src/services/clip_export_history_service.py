"""
Clip Export History Service — Phase 23

Tracks all clip export operations per user in a Redis list.
Key schema: export_history:{user_id}  → Redis LIST of JSON export records

Each record: export_id, clip_ids, format, status, created_at, completed_at, file_path, file_size_bytes
Max 200 records per user; TTL 60 days.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_RECORDS = 200
_TTL = 60 * 60 * 24 * 60  # 60 days


def _key(user_id: str) -> str:
    return f"export_history:{user_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def record_export(
    user_id: str,
    clip_ids: List[str],
    fmt: str = "zip",
    status: str = "pending",
    file_path: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> Dict:
    """Create a new export history record. Returns the record dict."""
    record = {
        "export_id": str(uuid.uuid4()),
        "user_id": user_id,
        "clip_ids": clip_ids,
        "clip_count": len(clip_ids),
        "format": fmt,
        "status": status,
        "file_path": file_path,
        "file_size_bytes": file_size_bytes,
        "created_at": _now(),
        "completed_at": None,
    }
    try:
        r = await _redis()
        await r.lpush(_key(user_id), json.dumps(record))
        await r.ltrim(_key(user_id), 0, _MAX_RECORDS - 1)
        await r.expire(_key(user_id), _TTL)
    except Exception as exc:
        logger.warning("[export_history] record_export failed user=%s: %s", user_id, exc)
    return record


async def update_export_status(
    user_id: str,
    export_id: str,
    status: str,
    file_path: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> bool:
    """Update status of an existing export record. Returns True if found."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_RECORDS - 1)
        for i, item in enumerate(raw):
            rec = json.loads(item.decode() if isinstance(item, bytes) else item)
            if rec.get("export_id") == export_id:
                rec["status"] = status
                if file_path is not None:
                    rec["file_path"] = file_path
                if file_size_bytes is not None:
                    rec["file_size_bytes"] = file_size_bytes
                if status in ("completed", "failed"):
                    rec["completed_at"] = _now()
                await r.lset(_key(user_id), i, json.dumps(rec))
                return True
        return False
    except Exception as exc:
        logger.warning("[export_history] update failed: %s", exc)
        return False


async def get_export_history(
    user_id: str,
    limit: int = 20,
    status_filter: Optional[str] = None,
) -> List[Dict]:
    """Return recent export records for a user."""
    try:
        r = await _redis()
        raw = await r.lrange(_key(user_id), 0, _MAX_RECORDS - 1)
        results = []
        for item in raw:
            rec = json.loads(item.decode() if isinstance(item, bytes) else item)
            if status_filter and rec.get("status") != status_filter:
                continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results
    except Exception as exc:
        logger.warning("[export_history] get failed: %s", exc)
        return []


async def get_export_stats(user_id: str) -> Dict:
    """Return export statistics: total, completed, failed, pending."""
    records = await get_export_history(user_id, limit=_MAX_RECORDS)
    stats: Dict[str, int] = {"total": len(records), "completed": 0, "failed": 0, "pending": 0}
    total_clips = 0
    for r in records:
        s = r.get("status", "pending")
        if s in stats:
            stats[s] += 1
        total_clips += r.get("clip_count", 0)
    stats["total_clips_exported"] = total_clips
    return stats
