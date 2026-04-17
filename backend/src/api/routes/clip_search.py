"""
Clip Search API Routes — Phase 16

GET /clips/search      → full-text + score-based search across all user clips
GET /clips/facets      → facet counts for filter UI
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.services.clip_search_service import search_clips, get_search_facets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clips", tags=["clip-search"])


@router.get("/search")
async def search_clips_endpoint(
    user_id: str = Query(..., description="Owner user ID"),
    q: Optional[str] = Query(None, description="Full-text query on transcript + title"),
    hook_type: Optional[str] = Query(None, description="Filter by hook type"),
    min_virality: Optional[int] = Query(None, ge=0, le=100),
    max_virality: Optional[int] = Query(None, ge=0, le=100),
    min_duration: Optional[float] = Query(None, ge=0),
    max_duration: Optional[float] = Query(None, ge=0),
    min_rating: Optional[int] = Query(None, ge=1, le=5),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Search clips with optional full-text query and score filters.
    Results are sorted by virality_score DESC, then created_at DESC.
    """
    return await search_clips(
        db,
        user_id=user_id,
        query=q,
        hook_type=hook_type,
        min_virality=min_virality,
        max_virality=max_virality,
        min_duration=min_duration,
        max_duration=max_duration,
        min_rating=min_rating,
        limit=limit,
        offset=offset,
    )


@router.get("/facets")
async def get_facets_endpoint(
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Return facet counts (hook_type distribution) for the filter UI."""
    return await get_search_facets(db, user_id=user_id)
