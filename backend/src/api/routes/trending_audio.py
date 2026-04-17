"""Trending Audio API — fetch and match trending sounds to clips."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/trending-audio", tags=["Trending Audio"])


class RecommendRequest(BaseModel):
    niche: str = "lifestyle"
    tone: str = "entertainment"
    bpm_hint: float = 0.0
    duration: float = 30.0
    genre: str = "auto"
    territory: str = "global"


@router.get("/")
async def list_trending_sounds(
    genre: str = Query("auto", description="Filter by genre"),
    territory: str = Query("global", description="Territory code (US, UK, BR, …)"),
    limit: int = Query(10, ge=1, le=50),
):
    """Return ranked list of trending sounds for a genre/territory."""
    from src.services.trending_audio_service import get_trending_sounds
    sounds = await get_trending_sounds(genre=genre, territory=territory, limit=limit)
    return {"sounds": [s.to_dict() for s in sounds], "count": len(sounds)}


@router.post("/recommend")
async def recommend_sound(req: RecommendRequest):
    """Recommend the best trending sound for a clip given its features."""
    from src.services.trending_audio_service import (
        get_trending_sounds, recommend_sound_for_clip,
    )
    sounds = await get_trending_sounds(
        genre=req.genre, territory=req.territory, limit=20
    )
    recommendation = recommend_sound_for_clip(
        clip_features={
            "niche": req.niche,
            "tone": req.tone,
            "bpm_hint": req.bpm_hint,
            "duration": req.duration,
        },
        trending=sounds,
    )
    return {
        "recommendation": recommendation.to_dict() if recommendation else None,
        "candidates": len(sounds),
    }
