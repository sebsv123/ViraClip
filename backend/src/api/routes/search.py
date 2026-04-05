"""
Advanced Search API — ViraClip

Full-text search across clips with filters, sorting, facets, and autocomplete.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...services.search_service import (
    SortOrder,
    get_search_service,
    index_clip_for_search,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    filters: Dict[str, Any] = {}
    sort: str = "relevance"
    page: int = 1
    per_page: int = 20


class IndexClipRequest(BaseModel):
    clip_id: str
    title: str = ""
    description: str = ""
    transcript: str = ""
    tags: List[str] = []
    niche: str = ""
    platform: str = ""
    virality_score: float = 0.0
    duration: int = 0
    created_at: str = ""


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("")
def search_clips(body: SearchRequest):
    """
    Full-text search across indexed clips.

    **Filters** (all optional):
    - `niche` — exact match
    - `platform` — exact match
    - `min_virality` — float
    - `min_duration` / `max_duration` — int seconds
    - `created_after` / `created_before` — ISO-8601 string

    **Sort**: `relevance | virality_desc | virality_asc | date_desc | date_asc | duration_desc | duration_asc`
    """
    try:
        sort_order = SortOrder(body.sort)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort '{body.sort}'. Choose: {[s.value for s in SortOrder]}",
        )

    svc = get_search_service()
    try:
        results = svc.search(
            query=body.query,
            filters=body.filters,
            sort=sort_order,
            page=body.page,
            per_page=body.per_page,
        )
        return {"status": "success", **results}
    except Exception as e:
        logger.error(f"[Search] search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def search_clips_get(
    q: str = Query(..., description="Search query"),
    niche: Optional[str] = None,
    platform: Optional[str] = None,
    min_virality: Optional[float] = None,
    min_duration: Optional[int] = None,
    max_duration: Optional[int] = None,
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    """GET variant of search — convenient for browser/URL-based queries."""
    filters: Dict[str, Any] = {}
    if niche:
        filters["niche"] = niche
    if platform:
        filters["platform"] = platform
    if min_virality is not None:
        filters["min_virality"] = min_virality
    if min_duration is not None:
        filters["min_duration"] = min_duration
    if max_duration is not None:
        filters["max_duration"] = max_duration

    try:
        sort_order = SortOrder(sort)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid sort '{sort}'")

    svc = get_search_service()
    results = svc.search(query=q, filters=filters, sort=sort_order, page=page, per_page=per_page)
    return {"status": "success", **results}


@router.get("/suggest")
def suggest(q: str = Query(..., min_length=2), limit: int = 10):
    """Autocomplete suggestions for partial search input."""
    svc = get_search_service()
    suggestions = svc.get_suggestions(partial=q, limit=limit)
    return {"status": "success", "query": q, "suggestions": suggestions}


@router.post("/index")
def index_clip(body: IndexClipRequest):
    """Index a clip so it becomes searchable. Called automatically by the pipeline."""
    clip_data = body.model_dump(exclude={"clip_id"})
    try:
        index_clip_for_search(clip_id=body.clip_id, clip_data=clip_data)
        return {"status": "indexed", "clip_id": body.clip_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/index/{clip_id}")
def remove_from_index(clip_id: str):
    """Remove a clip from the search index."""
    svc = get_search_service()
    svc.index.remove_document(clip_id)
    return {"status": "removed", "clip_id": clip_id}


@router.get("/fields")
def list_search_fields():
    """List all searchable fields and available sort options."""
    return {
        "fields": ["title", "description", "transcript", "tags", "niche", "platform"],
        "sort_options": [s.value for s in SortOrder],
        "filter_keys": [
            "niche", "platform", "min_virality",
            "min_duration", "max_duration",
            "created_after", "created_before",
        ],
    }
