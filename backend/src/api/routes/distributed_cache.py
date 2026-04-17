"""
Distributed Cache API — ViraClip

Multi-layer distributed cache management: get/set/delete keys,
tag-based invalidation, pattern invalidation, cache warm-up, and stats.
"""

import logging
from typing import Any, Dict, List, Optional, Set
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.distributed_cache import CachePriority, get_cache_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cache", tags=["cache"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SetRequest(BaseModel):
    key: str
    value: Any
    ttl: int = 3600
    priority: str = "normal"
    tags: Optional[List[str]] = None


class WarmRequest(BaseModel):
    entries: List[Dict[str, Any]]  # [{key, value, ttl?, priority?}]


class InvalidateTagRequest(BaseModel):
    tag: str


class InvalidatePatternRequest(BaseModel):
    pattern: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_priority(value: str) -> CachePriority:
    try:
        return CachePriority(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown priority '{value}'. Valid: {[p.value for p in CachePriority]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/get/{key}")
async def cache_get(key: str):
    """Retrieve a value from the cache by key."""
    mgr = get_cache_manager()
    value = await mgr.get(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Cache key '{key}' not found")
    return {"key": key, "value": value}


@router.post("/set")
async def cache_set(body: SetRequest):
    """Set a value in the cache with optional TTL, priority, and tags."""
    priority = _parse_priority(body.priority)
    mgr = get_cache_manager()
    tags: Optional[Set[str]] = set(body.tags) if body.tags else None
    try:
        success = await mgr.set(body.key, body.value, priority=priority, ttl=body.ttl, tags=tags)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(status_code=500, detail="Cache set failed")
    return {"status": "stored", "key": body.key}


@router.delete("/keys/{key}")
async def cache_delete(key: str):
    """Delete a key from all cache levels."""
    mgr = get_cache_manager()
    success = await mgr.delete(key)
    if not success:
        raise HTTPException(status_code=404, detail=f"Cache key '{key}' not found")
    return {"status": "deleted", "key": key}


@router.post("/invalidate/tag")
async def invalidate_by_tag(body: InvalidateTagRequest):
    """Invalidate all cache entries associated with a tag."""
    mgr = get_cache_manager()
    count = await mgr.invalidate_by_tag(body.tag)
    return {"status": "invalidated", "tag": body.tag, "entries_removed": count}


@router.post("/invalidate/pattern")
async def invalidate_by_pattern(body: InvalidatePatternRequest):
    """Invalidate cache entries matching a glob-style pattern."""
    mgr = get_cache_manager()
    count = await mgr.invalidate_pattern(body.pattern)
    return {"status": "invalidated", "pattern": body.pattern, "entries_removed": count}


@router.post("/warm")
async def warm_cache(body: WarmRequest):
    """
    Pre-populate (warm) the cache with a batch of key-value pairs.

    Each entry must have `key` and `value`; `ttl` and `priority` are optional.
    """
    if not body.entries:
        raise HTTPException(status_code=400, detail="entries must not be empty")
    mgr = get_cache_manager()
    pairs = [(e["key"], e["value"]) for e in body.entries if "key" in e and "value" in e]
    if not pairs:
        raise HTTPException(status_code=400, detail="All entries must have 'key' and 'value'")
    try:
        await mgr.warm_cache(pairs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "warmed", "entries_loaded": len(pairs)}


@router.get("/stats")
def cache_stats():
    """Get cache performance statistics: hit rate, size, evictions, avg latency."""
    mgr = get_cache_manager()
    stats = mgr.get_stats()
    return {
        "status": "success",
        "stats": {
            "hit_rate": stats.hit_rate,
            "entry_count": stats.entry_count,
            "total_size_bytes": stats.total_size_bytes,
            "evictions": stats.evictions,
            "avg_access_time_ms": stats.avg_access_time_ms,
        },
    }


@router.get("/priorities")
def list_priorities():
    """List all supported cache priority levels."""
    return {"priorities": [p.value for p in CachePriority]}
