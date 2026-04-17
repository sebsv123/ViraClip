"""
A/B Test Service — Phase 22

Tracks caption/title/thumbnail variants for a clip and records
impression + click counts per variant.  Uses Redis hashes.

Key schema:
  ab_test:{clip_id}:{variant_id}:meta   → HASH: variant label, created_at
  ab_test:{clip_id}:{variant_id}:stats  → HASH: impressions, clicks
  ab_tests:{clip_id}                    → SET of variant_ids

Calculates CTR (clicks / impressions) for each variant.
Max 5 variants per clip.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_VARIANTS = 5


def _meta_key(clip_id: str, variant_id: str) -> str:
    return f"ab_test:{clip_id}:{variant_id}:meta"


def _stats_key(clip_id: str, variant_id: str) -> str:
    return f"ab_test:{clip_id}:{variant_id}:stats"


def _index_key(clip_id: str) -> str:
    return f"ab_tests:{clip_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def create_variant(clip_id: str, label: str, content: str = "") -> Dict:
    """Create a new A/B test variant for a clip."""
    r = await _redis()
    count = await r.scard(_index_key(clip_id))
    if count >= _MAX_VARIANTS:
        raise ValueError(f"Clip {clip_id} already has {_MAX_VARIANTS} variants (max)")

    variant_id = str(uuid.uuid4())[:8]
    meta = {
        "variant_id": variant_id,
        "clip_id": clip_id,
        "label": label,
        "content": content,
        "created_at": _now(),
    }
    await r.hset(_meta_key(clip_id, variant_id), mapping=meta)
    await r.hset(_stats_key(clip_id, variant_id), mapping={"impressions": 0, "clicks": 0})
    await r.sadd(_index_key(clip_id), variant_id)
    return {**meta, "impressions": 0, "clicks": 0, "ctr": 0.0}


async def record_impression(clip_id: str, variant_id: str) -> int:
    """Increment impression count. Returns new count."""
    r = await _redis()
    return await r.hincrby(_stats_key(clip_id, variant_id), "impressions", 1)


async def record_click(clip_id: str, variant_id: str) -> int:
    """Increment click count. Returns new count."""
    r = await _redis()
    return await r.hincrby(_stats_key(clip_id, variant_id), "clicks", 1)


async def get_variant_stats(clip_id: str, variant_id: str) -> Optional[Dict]:
    """Return stats for a single variant."""
    try:
        r = await _redis()
        meta_raw = await r.hgetall(_meta_key(clip_id, variant_id))
        if not meta_raw:
            return None
        stats_raw = await r.hgetall(_stats_key(clip_id, variant_id))
        meta = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                for k, v in meta_raw.items()}
        stats = {(k.decode() if isinstance(k, bytes) else k): int(v)
                 for k, v in stats_raw.items()}
        impressions = stats.get("impressions", 0)
        clicks = stats.get("clicks", 0)
        ctr = round(clicks / impressions, 4) if impressions else 0.0
        return {**meta, **stats, "ctr": ctr}
    except Exception as exc:
        logger.warning("[ab_test] get_stats failed clip=%s vid=%s: %s", clip_id, variant_id, exc)
        return None


async def get_all_variants(clip_id: str) -> List[Dict]:
    """Return stats for all variants of a clip, sorted by CTR desc."""
    try:
        r = await _redis()
        variant_ids = await r.smembers(_index_key(clip_id))
        results = []
        for vid_raw in variant_ids:
            vid = vid_raw.decode() if isinstance(vid_raw, bytes) else vid_raw
            stats = await get_variant_stats(clip_id, vid)
            if stats:
                results.append(stats)
        return sorted(results, key=lambda x: x.get("ctr", 0), reverse=True)
    except Exception as exc:
        logger.warning("[ab_test] get_all_variants failed clip=%s: %s", clip_id, exc)
        return []


async def delete_variant(clip_id: str, variant_id: str) -> bool:
    """Delete a variant and its stats."""
    try:
        r = await _redis()
        existed = await r.exists(_meta_key(clip_id, variant_id))
        if not existed:
            return False
        await r.delete(_meta_key(clip_id, variant_id))
        await r.delete(_stats_key(clip_id, variant_id))
        await r.srem(_index_key(clip_id), variant_id)
        return True
    except Exception as exc:
        logger.warning("[ab_test] delete_variant failed: %s", exc)
        return False
