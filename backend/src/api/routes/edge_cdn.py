"""
Edge CDN API — ViraClip

Edge computing and global CDN distribution: process clips at nearest edge
node, push to all CDN regions, get optimal per-user delivery URL.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.edge_cdn import Region, get_edge_cdn_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/edge-cdn", tags=["edge-cdn"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ProcessAtEdgeRequest(BaseModel):
    clip_id: str
    user_location: str          # city / country code, e.g. "us-east", "eu-west"
    task: str                   # processing task, e.g. "transcode", "thumbnail"
    metadata: Optional[Dict[str, Any]] = None


class DistributeRequest(BaseModel):
    clip_id: str
    clip_url: str               # source URL to push out to edge PoPs


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/process")
async def process_at_edge(body: ProcessAtEdgeRequest):
    """
    Route a clip-processing task to the optimal edge node for a given user location.

    Returns processing time, node ID, region, and latency.
    """
    svc = get_edge_cdn_service()
    try:
        result = await svc.process_at_edge(
            body.clip_id, body.user_location, body.task, body.metadata or {}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "Edge processing failed"))
    return {"status": "processed", "result": result}


@router.post("/distribute")
async def distribute_to_cdn(body: DistributeRequest):
    """
    Push a clip URL to all configured CDN edge PoPs globally.

    Returns per-region distribution status and global coverage %.
    """
    svc = get_edge_cdn_service()
    try:
        result = await svc.distribute_to_cdn(body.clip_id, body.clip_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "distributed", "result": result}


@router.get("/endpoint/{clip_id}")
async def get_optimal_endpoint(clip_id: str, user_location: str = "us-east"):
    """
    Get the optimal CDN delivery URL for a clip given the user's location.

    Pass `user_location` as a query param (e.g. `eu-west`, `ap-southeast`).
    """
    svc = get_edge_cdn_service()
    try:
        endpoint = await svc.get_optimal_endpoint(clip_id, user_location)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if endpoint is None:
        raise HTTPException(status_code=404, detail=f"No CDN endpoint found for clip '{clip_id}'")
    return {"clip_id": clip_id, "user_location": user_location, "endpoint": endpoint}


@router.get("/network/status")
def network_status():
    """Get overall edge network status: node count, active nodes, avg latency, coverage."""
    svc = get_edge_cdn_service()
    return {"status": "success", "network": svc.get_edge_network_status()}


@router.get("/stats")
def cdn_stats():
    """Get CDN performance statistics: requests/s, bandwidth, cache hit ratio."""
    svc = get_edge_cdn_service()
    return {"status": "success", "stats": svc.get_cdn_stats()}


@router.get("/regions/{region}")
def region_details(region: str):
    """Get edge node details for a specific region."""
    try:
        region_enum = Region(region.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown region '{region}'. Valid: {[r.value for r in Region]}",
        )
    svc = get_edge_cdn_service()
    details = svc.get_region_details(region_enum)
    if details is None:
        raise HTTPException(status_code=404, detail=f"No edge nodes found in region '{region}'")
    return {"region": region, "details": details}


@router.get("/regions")
def list_regions():
    """List all supported edge regions."""
    return {"regions": [r.value for r in Region]}
