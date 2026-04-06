"""
Vector Search API Routes (Milvus multimodal search)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.milvus_vector_service import MilvusVectorService

router = APIRouter(prefix="/vector", tags=["Vector Search"])

_svc: Optional[MilvusVectorService] = None


def _get_svc() -> MilvusVectorService:
    global _svc
    if _svc is None:
        _svc = MilvusVectorService()
    return _svc


class IndexClipRequest(BaseModel):
    clip_id: str
    frames: Optional[List[Dict[str, Any]]] = None
    transcript_segments: Optional[List[Dict[str, Any]]] = None
    audio_features: Optional[Dict[str, Any]] = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    modality: str = Field("text", pattern="^(text|visual|hybrid)$")
    top_k: int = Field(10, ge=1, le=100)
    filters: Optional[Dict[str, Any]] = None


class VisualSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(10, ge=1, le=100)
    filters: Optional[Dict[str, Any]] = None


@router.post("/index")
async def index_clip(body: IndexClipRequest) -> Dict[str, Any]:
    """Index a clip's frames, transcript, and audio features into the vector database."""
    svc = _get_svc()
    try:
        await svc.initialize()
        counts = await svc.index_clip(
            clip_id=body.clip_id,
            frames=body.frames,
            transcript_segments=body.transcript_segments,
            audio_features=body.audio_features,
        )
        return {"clip_id": body.clip_id, "indexed": counts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_multimodal(body: SearchRequest) -> Dict[str, Any]:
    """Search clips using text, visual, or hybrid multimodal query."""
    svc = _get_svc()
    try:
        await svc.initialize()
        results = await svc.search_multimodal(
            query=body.query,
            modality=body.modality,
            top_k=body.top_k,
            filters=body.filters or {},
        )
        return {
            "query": body.query,
            "modality": body.modality,
            "result_count": len(results),
            "results": [
                {
                    "clip_id": r.clip_id,
                    "timestamp": r.timestamp,
                    "score": r.score,
                    "modality": r.modality,
                    "metadata": r.metadata,
                }
                for r in results
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/visual")
async def search_visual(body: VisualSearchRequest) -> Dict[str, Any]:
    """Search clips by visual content using CLIP embeddings."""
    svc = _get_svc()
    try:
        await svc.initialize()
        results = await svc.search_by_visual(
            query=body.query, limit=body.limit, filters=body.filters
        )
        return {"query": body.query, "result_count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/text")
async def search_text(body: VisualSearchRequest) -> Dict[str, Any]:
    """Search clips by transcript text using sentence embeddings."""
    svc = _get_svc()
    try:
        await svc.initialize()
        results = await svc.search_by_text(
            query=body.query, limit=body.limit, filters=body.filters
        )
        return {"query": body.query, "result_count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clip/{clip_id}")
async def delete_clip(clip_id: str) -> Dict[str, Any]:
    """Remove all indexed vectors for a clip."""
    svc = _get_svc()
    try:
        await svc.initialize()
        await svc.delete_clip(clip_id)
        return {"clip_id": clip_id, "deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats() -> Dict[str, Any]:
    """Get vector database collection statistics."""
    svc = _get_svc()
    try:
        await svc.initialize()
        return await svc.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
