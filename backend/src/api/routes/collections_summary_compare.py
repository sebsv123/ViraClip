"""
Collections, AI Summary & Clip Comparison API Routes — Phase 26

Collections:
  POST   /collections/{user_id}                    → create collection
  GET    /collections/{user_id}                    → list all collections
  GET    /collections/{user_id}/{coll_id}           → get single collection
  DELETE /collections/{user_id}/{coll_id}           → delete collection
  POST   /collections/{user_id}/{coll_id}/clips/{clip_id}  → add clip
  DELETE /collections/{user_id}/{coll_id}/clips/{clip_id}  → remove clip

AI Summary:
  GET    /clips/{clip_id}/summary         → get or generate summary
  DELETE /clips/{clip_id}/summary         → evict summary cache

Comparison:
  POST   /clips/compare                   → compare two clips with inline metrics
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["collections-summary-compare"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

class CollectionCreate(BaseModel):
    name: str
    description: str = ""
    clip_ids: Optional[List[str]] = None


class SummaryRequest(BaseModel):
    transcript: str
    force: bool = False


class CompareRequest(BaseModel):
    clip_a_id: str
    clip_b_id: str
    metrics_a: Optional[Dict[str, Any]] = None
    metrics_b: Optional[Dict[str, Any]] = None
    use_redis: bool = True


# ── Collections ───────────────────────────────────────────────────────────────

@router.post("/collections/{user_id}")
async def create_collection(user_id: str, body: CollectionCreate):
    from src.services.clip_collection_service import create_collection as svc
    try:
        return await svc(user_id, body.name, body.description, body.clip_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/collections/{user_id}")
async def list_collections(user_id: str):
    from src.services.clip_collection_service import list_collections as svc
    colls = await svc(user_id)
    return {"user_id": user_id, "count": len(colls), "collections": colls}


@router.get("/collections/{user_id}/{coll_id}")
async def get_collection(user_id: str, coll_id: str):
    from src.services.clip_collection_service import get_collection as svc
    coll = await svc(user_id, coll_id)
    if coll is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return coll


@router.delete("/collections/{user_id}/{coll_id}")
async def delete_collection(user_id: str, coll_id: str):
    from src.services.clip_collection_service import delete_collection as svc
    deleted = await svc(user_id, coll_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"deleted": True, "collection_id": coll_id}


@router.post("/collections/{user_id}/{coll_id}/clips/{clip_id}")
async def add_clip_to_collection(user_id: str, coll_id: str, clip_id: str):
    from src.services.clip_collection_service import add_clip_to_collection as svc
    try:
        clip_count = await svc(user_id, coll_id, clip_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"clip_count": clip_count, "collection_id": coll_id}


@router.delete("/collections/{user_id}/{coll_id}/clips/{clip_id}")
async def remove_clip_from_collection(user_id: str, coll_id: str, clip_id: str):
    from src.services.clip_collection_service import remove_clip_from_collection as svc
    removed = await svc(user_id, coll_id, clip_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Clip not found in collection")
    return {"removed": True, "clip_id": clip_id}


# ── AI Summary ────────────────────────────────────────────────────────────────

@router.post("/clips/{clip_id}/summary")
async def generate_summary(clip_id: str, body: SummaryRequest):
    from src.services.ai_summary_service import get_or_generate_summary
    return await get_or_generate_summary(clip_id, body.transcript, force=body.force)


@router.delete("/clips/{clip_id}/summary")
async def clear_summary(clip_id: str):
    from src.services.ai_summary_service import clear_summary_cache
    await clear_summary_cache(clip_id)
    return {"cleared": True, "clip_id": clip_id}


# ── Clip Comparison ───────────────────────────────────────────────────────────

@router.post("/clips/compare")
async def compare_clips(body: CompareRequest):
    if body.use_redis:
        from src.services.clip_comparison_service import compare_clips_from_redis
        return await compare_clips_from_redis(
            body.clip_a_id, body.clip_b_id,
            extra_a=body.metrics_a,
            extra_b=body.metrics_b,
        )
    from src.services.clip_comparison_service import compare_metrics
    return compare_metrics(
        body.clip_a_id, body.clip_b_id,
        body.metrics_a or {},
        body.metrics_b or {},
    )
