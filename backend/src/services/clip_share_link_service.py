"""
Clip Share Link Service — Phase 25

Generates short share links for clips with optional expiry.
Key schema:
  share:{token}          → HASH: clip_id, user_id, created_at, expires_at, views
  share_index:{clip_id}  → SET of active tokens for that clip

Token: 8-char alphanumeric (URL-safe)
Default TTL: 7 days; pass ttl_seconds=0 for no expiry.
Max 10 active share links per clip.
"""

import logging
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "share"
_INDEX_PREFIX = "share_index"
_DEFAULT_TTL = 60 * 60 * 24 * 7  # 7 days
_TOKEN_LEN = 8
_MAX_LINKS_PER_CLIP = 10


def _skey(token: str) -> str:
    return f"{_KEY_PREFIX}:{token}"


def _ikey(clip_id: str) -> str:
    return f"{_INDEX_PREFIX}:{clip_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_token() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=_TOKEN_LEN))


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def create_share_link(
    clip_id: str,
    user_id: str,
    ttl_seconds: int = _DEFAULT_TTL,
) -> Dict:
    """Create a new share link token for a clip. Returns the link record."""
    r = await _redis()
    active = await r.scard(_ikey(clip_id))
    if active >= _MAX_LINKS_PER_CLIP:
        raise ValueError(f"Clip {clip_id} already has {_MAX_LINKS_PER_CLIP} share links (max)")

    token = _generate_token()
    expires_at = None
    if ttl_seconds > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

    record = {
        "token": token,
        "clip_id": clip_id,
        "user_id": user_id,
        "created_at": _now(),
        "expires_at": expires_at or "",
        "views": "0",
    }
    await r.hset(_skey(token), mapping=record)
    if ttl_seconds > 0:
        await r.expire(_skey(token), ttl_seconds)
    await r.sadd(_ikey(clip_id), token)

    return {**record, "views": 0, "expires_at": expires_at}


async def resolve_share_link(token: str) -> Optional[Dict]:
    """Resolve a share token and increment view count. Returns None if expired/missing."""
    try:
        r = await _redis()
        raw = await r.hgetall(_skey(token))
        if not raw:
            return None
        data = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        views = await r.hincrby(_skey(token), "views", 1)
        data["views"] = views
        data["expires_at"] = data.get("expires_at") or None
        return data
    except Exception as exc:
        logger.warning("[share_link] resolve failed token=%s: %s", token, exc)
        return None


async def list_share_links(clip_id: str) -> List[Dict]:
    """Return all active share links for a clip."""
    try:
        r = await _redis()
        tokens_raw = await r.smembers(_ikey(clip_id))
        results = []
        dead_tokens = []
        for t_raw in tokens_raw:
            token = t_raw.decode() if isinstance(t_raw, bytes) else t_raw
            raw = await r.hgetall(_skey(token))
            if not raw:
                dead_tokens.append(token)
                continue
            data = {
                (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                for k, v in raw.items()
            }
            data["views"] = int(data.get("views", 0))
            data["expires_at"] = data.get("expires_at") or None
            results.append(data)
        if dead_tokens:
            await r.srem(_ikey(clip_id), *dead_tokens)
        return results
    except Exception as exc:
        logger.warning("[share_link] list failed clip=%s: %s", clip_id, exc)
        return []


async def revoke_share_link(clip_id: str, token: str) -> bool:
    """Revoke (delete) a share link token. Returns True if it existed."""
    try:
        r = await _redis()
        deleted = await r.delete(_skey(token))
        await r.srem(_ikey(clip_id), token)
        return bool(deleted)
    except Exception as exc:
        logger.warning("[share_link] revoke failed token=%s: %s", token, exc)
        return False
