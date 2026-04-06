"""
Clip Playlist Service — Phase 22

Ordered clip groups stored in Redis lists.
Key schema:
  playlist:{user_id}:{playlist_id}        → Redis LIST of clip_ids (ordered)
  playlist_meta:{user_id}:{playlist_id}   → Redis HASH of name, description, created_at, updated_at
  playlists:{user_id}                     → Redis SET of playlist_ids

Max 200 clips per playlist.  Max 50 playlists per user.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

_MAX_CLIPS = 200
_MAX_PLAYLISTS = 50


def _clips_key(user_id: str, playlist_id: str) -> str:
    return f"playlist:{user_id}:{playlist_id}"


def _meta_key(user_id: str, playlist_id: str) -> str:
    return f"playlist_meta:{user_id}:{playlist_id}"


def _index_key(user_id: str) -> str:
    return f"playlists:{user_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def create_playlist(
    user_id: str,
    name: str,
    description: str = "",
    clip_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new playlist. Returns the playlist dict."""
    r = await _redis()
    count = await r.scard(_index_key(user_id))
    if count >= _MAX_PLAYLISTS:
        raise ValueError(f"User has reached the maximum of {_MAX_PLAYLISTS} playlists")

    playlist_id = str(uuid.uuid4())
    meta = {
        "playlist_id": playlist_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await r.hset(_meta_key(user_id, playlist_id), mapping=meta)
    await r.sadd(_index_key(user_id), playlist_id)

    if clip_ids:
        clips = clip_ids[:_MAX_CLIPS]
        await r.rpush(_clips_key(user_id, playlist_id), *clips)

    meta["clip_count"] = len(clip_ids or [])
    return meta


async def get_playlist(user_id: str, playlist_id: str) -> Optional[Dict[str, Any]]:
    """Return playlist metadata + clip list, or None if not found."""
    try:
        r = await _redis()
        raw_meta = await r.hgetall(_meta_key(user_id, playlist_id))
        if not raw_meta:
            return None
        meta = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw_meta.items()
        }
        clips_raw = await r.lrange(_clips_key(user_id, playlist_id), 0, -1)
        meta["clips"] = [c.decode() if isinstance(c, bytes) else c for c in clips_raw]
        meta["clip_count"] = len(meta["clips"])
        return meta
    except Exception as exc:
        logger.warning("[playlist] get failed user=%s pid=%s: %s", user_id, playlist_id, exc)
        return None


async def list_playlists(user_id: str) -> List[Dict[str, Any]]:
    """Return all playlist metadata for a user (without clip lists)."""
    try:
        r = await _redis()
        ids = await r.smembers(_index_key(user_id))
        result = []
        for pid_raw in ids:
            pid = pid_raw.decode() if isinstance(pid_raw, bytes) else pid_raw
            raw_meta = await r.hgetall(_meta_key(user_id, pid))
            if raw_meta:
                meta = {
                    (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                    for k, v in raw_meta.items()
                }
                clip_count = await r.llen(_clips_key(user_id, pid))
                meta["clip_count"] = clip_count
                result.append(meta)
        return sorted(result, key=lambda x: x.get("created_at", ""))
    except Exception as exc:
        logger.warning("[playlist] list failed user=%s: %s", user_id, exc)
        return []


async def delete_playlist(user_id: str, playlist_id: str) -> bool:
    """Delete a playlist and all its data. Returns True if it existed."""
    try:
        r = await _redis()
        existed = await r.exists(_meta_key(user_id, playlist_id))
        if not existed:
            return False
        await r.delete(_meta_key(user_id, playlist_id))
        await r.delete(_clips_key(user_id, playlist_id))
        await r.srem(_index_key(user_id), playlist_id)
        return True
    except Exception as exc:
        logger.warning("[playlist] delete failed user=%s pid=%s: %s", user_id, playlist_id, exc)
        return False


async def add_clip_to_playlist(user_id: str, playlist_id: str, clip_id: str) -> int:
    """Append a clip to a playlist. Returns new length. Raises ValueError at max."""
    r = await _redis()
    current = await r.llen(_clips_key(user_id, playlist_id))
    if current >= _MAX_CLIPS:
        raise ValueError(f"Playlist is full ({_MAX_CLIPS} clips)")
    new_len = await r.rpush(_clips_key(user_id, playlist_id), clip_id)
    await r.hset(_meta_key(user_id, playlist_id), "updated_at", _now())
    return new_len


async def remove_clip_from_playlist(user_id: str, playlist_id: str, clip_id: str) -> int:
    """Remove all occurrences of clip_id from a playlist. Returns removed count."""
    r = await _redis()
    removed = await r.lrem(_clips_key(user_id, playlist_id), 0, clip_id)
    if removed:
        await r.hset(_meta_key(user_id, playlist_id), "updated_at", _now())
    return removed
