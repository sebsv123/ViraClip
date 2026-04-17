"""
Clip Chapter Service — Phase 24

Divides a clip into named, timestamped chapters stored in a Redis sorted set
(score = timestamp in seconds).

Key schema:
  clip_chapters:{clip_id}           → ZSET: member=JSON(chapter), score=timestamp
  clip_chapters_meta:{clip_id}      → HASH: chapter_count, total_duration, updated_at

Max 50 chapters per clip.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_CHAPTERS = 50
_CHAPTERS_KEY = "clip_chapters"
_META_KEY = "clip_chapters_meta"


def _zset_key(clip_id: str) -> str:
    return f"{_CHAPTERS_KEY}:{clip_id}"


def _meta_key(clip_id: str) -> str:
    return f"{_META_KEY}:{clip_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def add_chapter(
    clip_id: str,
    title: str,
    start_time: float,
    end_time: Optional[float] = None,
    description: str = "",
) -> Dict:
    """Add a chapter to a clip. Returns the new chapter dict."""
    r = await _redis()
    count = await r.zcard(_zset_key(clip_id))
    if count >= _MAX_CHAPTERS:
        raise ValueError(f"Clip {clip_id} already has {_MAX_CHAPTERS} chapters (max)")

    chapter = {
        "chapter_id": str(uuid.uuid4())[:8],
        "clip_id": clip_id,
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "description": description,
        "created_at": _now(),
    }
    await r.zadd(_zset_key(clip_id), {json.dumps(chapter): start_time})
    await r.hset(_meta_key(clip_id), mapping={
        "chapter_count": count + 1,
        "updated_at": _now(),
    })
    return chapter


async def get_chapters(clip_id: str) -> List[Dict]:
    """Return all chapters for a clip sorted by start_time (ascending)."""
    try:
        r = await _redis()
        raw = await r.zrange(_zset_key(clip_id), 0, -1)
        chapters = []
        for item in raw:
            chapters.append(json.loads(item.decode() if isinstance(item, bytes) else item))
        return chapters
    except Exception as exc:
        logger.warning("[chapters] get failed clip=%s: %s", clip_id, exc)
        return []


async def remove_chapter(clip_id: str, chapter_id: str) -> bool:
    """Remove a chapter by chapter_id. Returns True if found and removed."""
    try:
        r = await _redis()
        raw = await r.zrange(_zset_key(clip_id), 0, -1)
        for item in raw:
            ch = json.loads(item.decode() if isinstance(item, bytes) else item)
            if ch.get("chapter_id") == chapter_id:
                removed = await r.zrem(_zset_key(clip_id), item)
                if removed:
                    count = await r.zcard(_zset_key(clip_id))
                    await r.hset(_meta_key(clip_id), "chapter_count", count)
                    await r.hset(_meta_key(clip_id), "updated_at", _now())
                return bool(removed)
        return False
    except Exception as exc:
        logger.warning("[chapters] remove failed clip=%s cid=%s: %s", clip_id, chapter_id, exc)
        return False


async def clear_chapters(clip_id: str) -> int:
    """Delete all chapters for a clip. Returns count removed."""
    try:
        r = await _redis()
        count = await r.zcard(_zset_key(clip_id))
        await r.delete(_zset_key(clip_id))
        await r.delete(_meta_key(clip_id))
        return count
    except Exception as exc:
        logger.warning("[chapters] clear failed clip=%s: %s", clip_id, exc)
        return 0


async def get_chapter_at_time(clip_id: str, timestamp: float) -> Optional[Dict]:
    """Return the chapter that contains the given timestamp, or None."""
    chapters = await get_chapters(clip_id)
    active = None
    for ch in chapters:
        if ch["start_time"] <= timestamp:
            if ch.get("end_time") is None or timestamp <= ch["end_time"]:
                active = ch
        elif active:
            break
    return active
