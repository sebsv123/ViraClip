"""
Clip Annotation Service — Phase 21

Stores free-text notes and key-value metadata on individual clips.
Uses a Redis hash per clip: clip_notes:{clip_id}

Fields stored per clip:
  note         → the main free-text annotation
  created_at   → ISO timestamp of first annotation
  updated_at   → ISO timestamp of last update
  author       → user_id who wrote the note
  + any extra key-value pairs passed in `extra`
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "clip_notes"
_NOTE_MAX_LEN = 2000


def _key(clip_id: str) -> str:
    return f"{_KEY_PREFIX}:{clip_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def set_annotation(
    clip_id: str,
    note: str,
    author: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create or replace the annotation for a clip.
    Returns the stored annotation dict.
    """
    if len(note) > _NOTE_MAX_LEN:
        raise ValueError(f"Note exceeds max length of {_NOTE_MAX_LEN} characters")

    r = await _redis()
    existing = await r.hget(_key(clip_id), "created_at")
    created_at = (existing.decode() if isinstance(existing, bytes) else existing) if existing else _now()

    payload: Dict[str, str] = {
        "note": note,
        "author": author,
        "created_at": created_at,
        "updated_at": _now(),
    }
    if extra:
        for k, v in extra.items():
            payload[str(k)] = str(v)

    await r.hset(_key(clip_id), mapping=payload)
    logger.debug("[annotation] set clip=%s author=%s", clip_id, author)
    return payload


async def get_annotation(clip_id: str) -> Optional[Dict[str, Any]]:
    """Return the annotation dict for a clip, or None if not set."""
    try:
        r = await _redis()
        data = await r.hgetall(_key(clip_id))
        if not data:
            return None
        return {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in data.items()
        }
    except Exception as exc:
        logger.warning("[annotation] get failed clip=%s: %s", clip_id, exc)
        return None


async def delete_annotation(clip_id: str) -> bool:
    """Delete the annotation for a clip. Returns True if it existed."""
    try:
        r = await _redis()
        deleted = await r.delete(_key(clip_id))
        return bool(deleted)
    except Exception as exc:
        logger.warning("[annotation] delete failed clip=%s: %s", clip_id, exc)
        return False


async def update_annotation_field(clip_id: str, field: str, value: str) -> bool:
    """Update a single field in an existing annotation. Returns False if no annotation exists."""
    try:
        r = await _redis()
        exists = await r.exists(_key(clip_id))
        if not exists:
            return False
        await r.hset(_key(clip_id), field, value)
        await r.hset(_key(clip_id), "updated_at", _now())
        return True
    except Exception as exc:
        logger.warning("[annotation] update_field failed clip=%s field=%s: %s", clip_id, field, exc)
        return False
