"""
Clip Tag Service — Phase 19

Lightweight tag storage using Redis sets.
Key schema:  clip_tags:{clip_id}  →  Redis SET of tag strings

Tags are lowercased and stripped of whitespace before storage.
Max 20 tags per clip; max tag length 50 chars.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

_MAX_TAGS = 20
_MAX_TAG_LEN = 50
_KEY_PREFIX = "clip_tags"


def _key(clip_id: str) -> str:
    return f"{_KEY_PREFIX}:{clip_id}"


def _normalise(tag: str) -> str:
    return tag.strip().lower()[:_MAX_TAG_LEN]


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


# ── Public API ────────────────────────────────────────────────────────────────

async def add_tags(clip_id: str, tags: List[str]) -> List[str]:
    """
    Add one or more tags to a clip.  Returns the updated full tag list.

    Raises ValueError if adding would exceed _MAX_TAGS.
    """
    normalised = [_normalise(t) for t in tags if t.strip()]
    if not normalised:
        return await get_tags(clip_id)

    r = await _redis()
    existing = await r.smembers(_key(clip_id))
    current_count = len(existing)
    new_tags = [t for t in normalised if t.encode() not in existing]
    if current_count + len(new_tags) > _MAX_TAGS:
        raise ValueError(f"Clip {clip_id} already has {current_count} tags; "
                         f"cannot add {len(new_tags)} more (max {_MAX_TAGS})")

    if new_tags:
        await r.sadd(_key(clip_id), *new_tags)
    return await get_tags(clip_id)


async def remove_tags(clip_id: str, tags: List[str]) -> List[str]:
    """Remove one or more tags from a clip.  Returns updated tag list."""
    normalised = [_normalise(t) for t in tags if t.strip()]
    if not normalised:
        return await get_tags(clip_id)
    r = await _redis()
    await r.srem(_key(clip_id), *normalised)
    return await get_tags(clip_id)


async def get_tags(clip_id: str) -> List[str]:
    """Return all tags for a clip, sorted alphabetically."""
    try:
        r = await _redis()
        members = await r.smembers(_key(clip_id))
        return sorted(m.decode() if isinstance(m, bytes) else m for m in members)
    except Exception as exc:
        logger.warning("[clip_tags] get_tags failed for clip=%s: %s", clip_id, exc)
        return []


async def clear_tags(clip_id: str) -> None:
    """Remove all tags for a clip (e.g. when clip is deleted)."""
    try:
        r = await _redis()
        await r.delete(_key(clip_id))
    except Exception as exc:
        logger.warning("[clip_tags] clear_tags failed for clip=%s: %s", clip_id, exc)


async def get_clips_by_tag(tag: str, clip_ids: List[str]) -> List[str]:
    """
    Given a list of clip_ids, return only those that have the given tag.
    Useful for tag-based filtering when combined with search results.
    """
    normalised = _normalise(tag)
    try:
        r = await _redis()
        matching = []
        for clip_id in clip_ids:
            is_member = await r.sismember(_key(clip_id), normalised)
            if is_member:
                matching.append(clip_id)
        return matching
    except Exception as exc:
        logger.warning("[clip_tags] get_clips_by_tag failed tag=%s: %s", tag, exc)
        return []
