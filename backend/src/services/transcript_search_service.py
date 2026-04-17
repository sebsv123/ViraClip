"""
Transcript Search Service — Phase 25

Stores clip transcripts in Redis and provides full-text search
across a user's clip transcripts using simple substring matching
with result ranking (hit count).

Key schema:
  transcript:{user_id}:{clip_id}  → STRING: transcript text
  transcript_index:{user_id}      → SET of clip_ids that have transcripts
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_TEXT_KEY = "transcript"
_INDEX_KEY = "transcript_index"
_MAX_RESULTS = 50


def _tkey(user_id: str, clip_id: str) -> str:
    return f"{_TEXT_KEY}:{user_id}:{clip_id}"


def _ikey(user_id: str) -> str:
    return f"{_INDEX_KEY}:{user_id}"


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def index_transcript(user_id: str, clip_id: str, transcript: str) -> None:
    """Store a transcript for a clip."""
    try:
        r = await _redis()
        await r.set(_tkey(user_id, clip_id), transcript)
        await r.sadd(_ikey(user_id), clip_id)
    except Exception as exc:
        logger.warning("[transcript_search] index failed clip=%s: %s", clip_id, exc)


async def delete_transcript(user_id: str, clip_id: str) -> bool:
    """Remove a transcript from the index."""
    try:
        r = await _redis()
        deleted = await r.delete(_tkey(user_id, clip_id))
        await r.srem(_ikey(user_id), clip_id)
        return bool(deleted)
    except Exception as exc:
        logger.warning("[transcript_search] delete failed clip=%s: %s", clip_id, exc)
        return False


async def search_transcripts(
    user_id: str,
    query: str,
    limit: int = 10,
    case_sensitive: bool = False,
) -> List[Dict]:
    """
    Search transcripts for a query string.
    Returns list of {clip_id, hit_count, snippet} sorted by hit_count desc.
    """
    if not query:
        return []

    try:
        r = await _redis()
        clip_ids_raw = await r.smembers(_ikey(user_id))
        clip_ids = [c.decode() if isinstance(c, bytes) else c for c in clip_ids_raw]

        search_q = query if case_sensitive else query.lower()
        results = []

        for clip_id in clip_ids:
            raw = await r.get(_tkey(user_id, clip_id))
            if not raw:
                continue
            text = raw.decode() if isinstance(raw, bytes) else raw
            compare = text if case_sensitive else text.lower()
            hit_count = compare.count(search_q)
            if hit_count == 0:
                continue

            idx = compare.find(search_q)
            snippet_start = max(0, idx - 40)
            snippet_end = min(len(text), idx + len(query) + 40)
            snippet = ("..." if snippet_start > 0 else "") + \
                      text[snippet_start:snippet_end] + \
                      ("..." if snippet_end < len(text) else "")

            results.append({
                "clip_id": clip_id,
                "hit_count": hit_count,
                "snippet": snippet,
            })

        results.sort(key=lambda x: x["hit_count"], reverse=True)
        return results[:limit]
    except Exception as exc:
        logger.warning("[transcript_search] search failed user=%s: %s", user_id, exc)
        return []


async def get_transcript(user_id: str, clip_id: str) -> Optional[str]:
    """Return the stored transcript for a clip."""
    try:
        r = await _redis()
        raw = await r.get(_tkey(user_id, clip_id))
        return (raw.decode() if isinstance(raw, bytes) else raw) if raw else None
    except Exception as exc:
        logger.warning("[transcript_search] get failed clip=%s: %s", clip_id, exc)
        return None


async def list_indexed_clips(user_id: str) -> List[str]:
    """Return all clip_ids that have indexed transcripts."""
    try:
        r = await _redis()
        raw = await r.smembers(_ikey(user_id))
        return [c.decode() if isinstance(c, bytes) else c for c in raw]
    except Exception as exc:
        logger.warning("[transcript_search] list failed user=%s: %s", user_id, exc)
        return []
