"""
Audio Recommendation API — ViraClip

Endpoints for AI-powered music and SFX recommendations,
beat-matched cut-point generation, and trending audio discovery.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.audio_recommendation import (
    AudioType,
    MusicGenre,
    get_audio_recommendation_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audio-rec", tags=["audio-rec"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    video_path: str
    transcript: Optional[str] = None


class MusicRequest(BaseModel):
    video_path: str
    count: int = 5
    exclude_vocals: bool = True


class SFXRequest(BaseModel):
    video_path: str
    scene_changes: List[float] = []
    key_moments: Optional[List[float]] = None


class BeatCutsRequest(BaseModel):
    video_path: str
    music_bpm: int
    video_duration: float


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_rec(rec) -> Dict[str, Any]:
    return {
        "recommendation_id": rec.recommendation_id,
        "audio_type": rec.audio_type.value,
        "genre": rec.genre.value,
        "title": rec.title,
        "artist": rec.artist,
        "duration": rec.duration,
        "bpm": rec.bpm,
        "mood": rec.mood,
        "energy_level": rec.energy_level,
        "match_score": round(rec.match_score, 3),
        "file_url": rec.file_url,
        "preview_url": rec.preview_url,
        "license_type": rec.license_type,
        "credits_cost": rec.credits_cost,
        "tags": rec.tags,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/analyze")
async def analyze_video(body: AnalyzeRequest):
    """
    Analyse a video to build its audio profile (mood, BPM range,
    energy curve, scene-change timestamps).

    Use the result as input to `/audio-rec/music` for targeted recommendations.
    """
    svc = get_audio_recommendation_service()
    try:
        profile = await svc.analyze_video_for_audio(
            Path(body.video_path), body.transcript
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "analyzed",
        "profile": {
            "duration": profile.duration,
            "has_voiceover": profile.has_voiceover,
            "dominant_mood": profile.dominant_mood,
            "energy_curve": profile.energy_curve,
            "scene_changes": profile.scene_changes,
            "recommended_bpm_range": list(profile.recommended_bpm_range),
            "suitable_genres": [g.value for g in profile.suitable_genres],
        },
    }


@router.post("/music")
async def recommend_music(body: MusicRequest):
    """
    Get background-music recommendations for a video.

    Internally runs audio analysis then matches against the library.
    Returns up to `count` ranked tracks.
    """
    svc = get_audio_recommendation_service()
    try:
        profile = await svc.analyze_video_for_audio(Path(body.video_path))
        recs = await svc.recommend_music(
            Path(body.video_path), profile, body.count, body.exclude_vocals
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "count": len(recs), "recommendations": [_fmt_rec(r) for r in recs]}


@router.post("/sfx")
async def recommend_sfx(body: SFXRequest):
    """
    Get SFX recommendations for scene transitions and key viral moments.
    `scene_changes` is a list of timestamps (seconds) where a cut occurs.
    """
    svc = get_audio_recommendation_service()
    try:
        recs = await svc.recommend_sfx(
            Path(body.video_path), body.scene_changes, body.key_moments
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "count": len(recs), "recommendations": [_fmt_rec(r) for r in recs]}


@router.post("/beat-cuts")
async def beat_matched_cuts(body: BeatCutsRequest):
    """
    Generate optimal cut-point timestamps aligned to music beats.
    `music_bpm` is the BPM of the selected track.
    """
    if body.music_bpm <= 0:
        raise HTTPException(status_code=400, detail="music_bpm must be > 0")
    if body.video_duration <= 0:
        raise HTTPException(status_code=400, detail="video_duration must be > 0")

    svc = get_audio_recommendation_service()
    try:
        cuts = await svc.generate_beat_matched_cuts(
            Path(body.video_path), body.music_bpm, body.video_duration
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "bpm": body.music_bpm,
        "beat_interval_seconds": round(60.0 / body.music_bpm, 3),
        "cut_count": len(cuts),
        "cut_points": [round(t, 3) for t in cuts],
    }


@router.get("/trending")
def get_trending(platform: str = "tiktok"):
    """Get the current trending audio tracks for a platform."""
    svc = get_audio_recommendation_service()
    recs = svc.get_trending_audio(platform)
    return {"status": "success", "platform": platform, "count": len(recs), "tracks": [_fmt_rec(r) for r in recs]}


@router.get("/stats")
def get_stats():
    """Library stats: total tracks, genres, recommendations made."""
    svc = get_audio_recommendation_service()
    return {"status": "success", "stats": svc.get_audio_stats()}


@router.get("/genres")
def list_genres():
    """List all available music genres."""
    return {"genres": [g.value for g in MusicGenre]}


@router.get("/audio-types")
def list_audio_types():
    """List all audio recommendation types."""
    return {"types": [t.value for t in AudioType]}
