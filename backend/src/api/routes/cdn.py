"""
CDN Management API — ViraClip

Endpoints for uploading clips to CDN, generating signed URLs,
invalidating cache, deleting assets, and health monitoring.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.cdn_service import CDNProvider, get_cdn_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cdn", tags=["cdn"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class UploadRequest(BaseModel):
    clip_path: str
    clip_id: str
    ttl_days: int = 30


class InvalidateRequest(BaseModel):
    clip_id: Optional[str] = None
    pattern: Optional[str] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_asset(a) -> Dict[str, Any]:
    return {
        "asset_id": a.asset_id,
        "cdn_url": a.cdn_url,
        "provider": a.provider.value,
        "size_mb": round(a.size_bytes / (1024 * 1024), 3),
        "created_at": a.created_at,
        "expires_at": a.expires_at,
        "etag": a.etag,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/upload")
async def upload_clip(body: UploadRequest):
    """
    Upload a clip to CDN and return its CDN URL and asset record.

    `ttl_days=0` disables expiration.
    """
    if body.ttl_days < 0:
        raise HTTPException(status_code=400, detail="ttl_days must be >= 0")
    cdn = get_cdn_manager()
    try:
        asset = await cdn.upload_clip(Path(body.clip_path), body.clip_id, body.ttl_days)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "uploaded", "asset": _fmt_asset(asset)}


@router.get("/url/{clip_id}")
def get_clip_url(clip_id: str, signed: bool = True, expiry_hours: int = 24):
    """
    Get the CDN delivery URL for a clip.

    `signed=true` (default) generates a time-limited signed URL.
    `expiry_hours` controls signed URL validity (default 24 h).
    """
    cdn = get_cdn_manager()
    url = cdn.get_clip_url(clip_id, signed, expiry_hours)
    if url is None:
        raise HTTPException(status_code=404, detail=f"No CDN asset found for clip '{clip_id}'")
    return {"clip_id": clip_id, "url": url, "signed": signed, "expiry_hours": expiry_hours}


@router.get("/stats/{clip_id}")
def asset_stats(clip_id: str):
    """Get CDN statistics for a specific clip asset."""
    cdn = get_cdn_manager()
    stats = cdn.get_asset_stats(clip_id)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"No CDN asset found for clip '{clip_id}'")
    return {"status": "success", "stats": stats}


@router.post("/invalidate")
async def invalidate_cache(body: InvalidateRequest):
    """
    Invalidate CDN cache entries.

    Provide `clip_id` to purge a single clip or `pattern` (e.g. `/clips/*`)
    to purge by glob. At least one field is required.
    """
    if not body.clip_id and not body.pattern:
        raise HTTPException(status_code=400, detail="Provide clip_id or pattern")
    cdn = get_cdn_manager()
    success = await cdn.invalidate_cache(body.clip_id, body.pattern)
    if not success:
        raise HTTPException(status_code=400, detail="Invalidation failed — no paths matched")
    return {"status": "invalidated", "clip_id": body.clip_id, "pattern": body.pattern}


@router.delete("/assets/{clip_id}")
async def delete_asset(clip_id: str):
    """Delete a clip from CDN and remove its tracking record."""
    cdn = get_cdn_manager()
    success = await cdn.delete_asset(clip_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"No CDN asset found for clip '{clip_id}'")
    return {"status": "deleted", "clip_id": clip_id}


@router.get("/health")
def cdn_health():
    """CDN health status: provider, total assets, cache hit ratio, edge locations."""
    cdn = get_cdn_manager()
    return {"status": "success", "health": cdn.get_cdn_health()}


@router.get("/providers")
def list_providers():
    """List all supported CDN providers."""
    return {"providers": [p.value for p in CDNProvider]}
