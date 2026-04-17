"""
Clip Collection Service — Phase 26

User-curated named collections stored in Redis sets.
Key schema:
  collection:{user_id}:{collection_id}  → SET of clip_ids
  collection_meta:{user_id}:{collection_id} → HASH: name, description, created_at, updated_at
  collection_index:{user_id}            → SET of collection_ids

Max 100 collections per user; max 500 clips per collection.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_COLLECTIONS = 100
_MAX_CLIPS = 500


def _ckey(user_id: str, coll_id: str) -> str:
    return f"collection:{user_id}:{coll_id}"


def _mkey(user_id: str, coll_id: str) -> str:
    return f"collection_meta:{user_id}:{coll_id}"


def _ikey(user_id: str) -> str:
    return f"collection_index:{user_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def create_collection(
    user_id: str,
    name: str,
    description: str = "",
    clip_ids: Optional[List[str]] = None,
) -> Dict:
    r = await _redis()
    count = await r.scard(_ikey(user_id))
    if count >= _MAX_COLLECTIONS:
        raise ValueError(f"Max {_MAX_COLLECTIONS} collections reached")

    coll_id = str(uuid.uuid4())[:12]
    meta = {
        "collection_id": coll_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await r.hset(_mkey(user_id, coll_id), mapping=meta)
    await r.sadd(_ikey(user_id), coll_id)
    if clip_ids:
        if len(clip_ids) > _MAX_CLIPS:
            clip_ids = clip_ids[:_MAX_CLIPS]
        await r.sadd(_ckey(user_id, coll_id), *clip_ids)
    clip_count = await r.scard(_ckey(user_id, coll_id))
    return {**meta, "clip_count": clip_count}


async def get_collection(user_id: str, coll_id: str) -> Optional[Dict]:
    try:
        r = await _redis()
        raw = await r.hgetall(_mkey(user_id, coll_id))
        if not raw:
            return None
        meta = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        clips_raw = await r.smembers(_ckey(user_id, coll_id))
        meta["clip_ids"] = [c.decode() if isinstance(c, bytes) else c for c in clips_raw]
        meta["clip_count"] = len(meta["clip_ids"])
        return meta
    except Exception as exc:
        logger.warning("[collection] get failed: %s", exc)
        return None


async def list_collections(user_id: str) -> List[Dict]:
    try:
        r = await _redis()
        ids_raw = await r.smembers(_ikey(user_id))
        results = []
        for id_raw in ids_raw:
            coll_id = id_raw.decode() if isinstance(id_raw, bytes) else id_raw
            raw = await r.hgetall(_mkey(user_id, coll_id))
            if not raw:
                continue
            meta = {
                (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                for k, v in raw.items()
            }
            meta["clip_count"] = await r.scard(_ckey(user_id, coll_id))
            results.append(meta)
        return results
    except Exception as exc:
        logger.warning("[collection] list failed: %s", exc)
        return []


async def add_clip_to_collection(user_id: str, coll_id: str, clip_id: str) -> int:
    r = await _redis()
    count = await r.scard(_ckey(user_id, coll_id))
    if count >= _MAX_CLIPS:
        raise ValueError(f"Collection at max capacity ({_MAX_CLIPS} clips)")
    await r.sadd(_ckey(user_id, coll_id), clip_id)
    await r.hset(_mkey(user_id, coll_id), "updated_at", _now())
    return await r.scard(_ckey(user_id, coll_id))


async def remove_clip_from_collection(user_id: str, coll_id: str, clip_id: str) -> bool:
    try:
        r = await _redis()
        removed = await r.srem(_ckey(user_id, coll_id), clip_id)
        if removed:
            await r.hset(_mkey(user_id, coll_id), "updated_at", _now())
        return bool(removed)
    except Exception as exc:
        logger.warning("[collection] remove_clip failed: %s", exc)
        return False


async def delete_collection(user_id: str, coll_id: str) -> bool:
    try:
        r = await _redis()
        deleted = await r.delete(_mkey(user_id, coll_id))
        await r.delete(_ckey(user_id, coll_id))
        await r.srem(_ikey(user_id), coll_id)
        return bool(deleted)
    except Exception as exc:
        logger.warning("[collection] delete failed: %s", exc)
        return False
