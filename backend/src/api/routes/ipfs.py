"""
IPFS Storage API — ViraClip

Endpoints for uploading content to IPFS, retrieving content,
managing pins, testing gateway latency, and viewing storage stats.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.ipfs_storage import ContentType, get_ipfs_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ipfs", tags=["ipfs"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class UploadRequest(BaseModel):
    content_id: str
    local_path: str
    content_type: str = "video"     # ContentType value
    pin: bool = True
    replicate: bool = True


class RetrieveRequest(BaseModel):
    ipfs_hash: str
    output_path: str
    preferred_gateway: Optional[str] = None


class ArchiveRequest(BaseModel):
    content_ids: List[str]
    archive_name: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_content_type(value: str) -> ContentType:
    try:
        return ContentType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown content_type '{value}'. Valid: {[c.value for c in ContentType]}",
        )


def _fmt_content(c) -> Dict[str, Any]:
    return {
        "content_id": c.content_id,
        "ipfs_hash": c.ipfs_hash,
        "content_type": c.content_type.value,
        "size_mb": round(c.size_bytes / (1024 * 1024), 3),
        "status": c.status.value,
        "pinned_at": c.pinned_at,
        "gateways": c.gateways,
        "metadata": c.metadata,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/upload")
async def upload_content(body: UploadRequest):
    """
    Upload a file to IPFS.

    Optionally pin (`pin=true`) and replicate across gateways (`replicate=true`).
    Returns the IPFS hash and gateway access URLs.
    """
    content_type = _parse_content_type(body.content_type)
    svc = get_ipfs_service()
    try:
        content = await svc.upload_content(
            body.content_id, Path(body.local_path),
            content_type, body.pin, body.replicate,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "uploaded", "content": _fmt_content(content)}


@router.post("/retrieve")
async def retrieve_content(body: RetrieveRequest):
    """
    Retrieve content from IPFS by hash.

    Pass `preferred_gateway` (e.g. `cloudflare`) to hint which gateway to try first.
    """
    svc = get_ipfs_service()
    try:
        success = await svc.retrieve_content(
            body.ipfs_hash, Path(body.output_path), body.preferred_gateway
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to retrieve {body.ipfs_hash} from all gateways",
        )
    return {"status": "retrieved", "ipfs_hash": body.ipfs_hash, "output_path": body.output_path}


@router.get("/content/{content_id}")
def get_content(content_id: str):
    """Get IPFS content record by local content ID."""
    svc = get_ipfs_service()
    content = svc.get_content_info(content_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Content '{content_id}' not found")
    return {"status": "success", "content": _fmt_content(content)}


@router.delete("/pin/{ipfs_hash}")
async def unpin_content(ipfs_hash: str):
    """Unpin content from IPFS to allow garbage collection."""
    svc = get_ipfs_service()
    success = await svc.unpin_content(ipfs_hash)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to unpin {ipfs_hash}")
    return {"status": "unpinned", "ipfs_hash": ipfs_hash}


@router.get("/gateways")
def gateway_status():
    """Get current status and reliability scores of all IPFS gateways."""
    svc = get_ipfs_service()
    return {"gateways": svc.get_gateway_status()}


@router.post("/gateways/latency")
async def test_latency(gateway_id: Optional[str] = None):
    """
    Test latency to IPFS gateways.

    Pass `gateway_id` to test a single gateway, or omit to test all.
    """
    svc = get_ipfs_service()
    results = await svc.test_gateway_latency(gateway_id)
    return {"latency_ms": results}


@router.get("/stats")
def storage_stats():
    """Get IPFS storage statistics: total content, size, pinned count, breakdown by type."""
    svc = get_ipfs_service()
    return {"status": "success", "stats": svc.get_storage_stats()}


@router.post("/archive")
async def create_archive(body: ArchiveRequest):
    """
    Create an IPFS archive of multiple content items.

    Bundles the specified `content_ids` into a JSON manifest, uploads it to IPFS,
    and returns the archive content record.
    """
    if not body.content_ids:
        raise HTTPException(status_code=400, detail="content_ids must not be empty")
    svc = get_ipfs_service()
    try:
        archive = await svc.create_content_archive(body.content_ids, body.archive_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "archived", "archive": _fmt_content(archive)}


@router.get("/content-types")
def list_content_types():
    """List all supported IPFS content types."""
    return {"content_types": [c.value for c in ContentType]}
