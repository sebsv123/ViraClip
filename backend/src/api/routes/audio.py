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
router = APIRouter(prefix="/audio", tags=["audio"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class MusicRecommendationRequest(BaseModel):
    clip_path: str                           # Path on server to the clip file
    transcript: Optional[str] = None
    count: int = 5
    exclude_vocals: bool = True


class SfxRecommendationRequest(BaseModel):
    clip_path: str
    scene_change_timestamps: List[float] = []
    key_moment_timestamps: Optional[List[float]] = None


class BeatMatchRequest(BaseModel):
    clip_path: str
    music_bpm: int


class AudioProfileRequest(BaseModel):
    clip_path: str
    transcript: Optional[str] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_rec(r) -> Dict[str, Any]:
    return {
        "recommendation_id": r.recommendation_id,
        "audio_type": r.audio_type.value,
        "genre": r.genre.value,
        "title": r.title,
        "artist": r.artist,
        "duration": r.duration,
        "bpm": r.bpm,
        "mood": r.mood,
        "energy_level": r.energy_level,
        "match_score": round(r.match_score, 3),
        "file_url": r.file_url,
        "preview_url": r.preview_url,
        "license_type": r.license_type,
        "credits_cost": r.credits_cost,
        "tags": r.tags,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/recommend/music")
async def recommend_music(body: MusicRecommendationRequest):
    """
    Analyse a video clip and return ranked background music recommendations.

    The service extracts duration, dominant mood, energy curve, and scene changes,
    then scores every track in the library for genre, BPM, mood, and energy fit.
    """
    svc = get_audio_recommendation_service()
    clip = Path(body.clip_path)

    try:
        profile = await svc.analyze_video_for_audio(clip, body.transcript)
        recommendations = await svc.recommend_music(
            clip, profile, count=body.count, exclude_vocals=body.exclude_vocals
        )
        return {
            "status": "success",
            "clip_profile": {
                "duration": profile.duration,
                "dominant_mood": profile.dominant_mood,
                "has_voiceover": profile.has_voiceover,
                "recommended_bpm_range": list(profile.recommended_bpm_range),
                "suitable_genres": [g.value for g in profile.suitable_genres],
            },
            "count": len(recommendations),
            "recommendations": [_fmt_rec(r) for r in recommendations],
        }
    except Exception as e:
        logger.error(f"[Audio] recommend_music failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recommend/sfx")
async def recommend_sfx(body: SfxRecommendationRequest):
    """
    Recommend sound effects for scene transitions and key moments in a clip.
    Returns transition SFX and beat-drop suggestions.
    """
    svc = get_audio_recommendation_service()
    clip = Path(body.clip_path)

    try:
        recommendations = await svc.recommend_sfx(
            video_path=clip,
            scene_changes=body.scene_change_timestamps,
            key_moments=body.key_moment_timestamps,
        )
        return {
            "status": "success",
            "count": len(recommendations),
            "recommendations": [_fmt_rec(r) for r in recommendations],
        }
    except Exception as e:
        logger.error(f"[Audio] recommend_sfx failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/beat-match")
async def generate_beat_matched_cuts(body: BeatMatchRequest):
    """
    Generate optimal cut-point timestamps aligned to the given music BPM.
    Useful for creating rhythmic edits that feel natural to the beat.
    """
    svc = get_audio_recommendation_service()
    clip = Path(body.clip_path)

    try:
        duration = await svc._get_video_duration(clip)
        cut_points = await svc.generate_beat_matched_cuts(
            video_path=clip,
            music_bpm=body.music_bpm,
            video_duration=duration,
        )
        beat_interval = 60.0 / body.music_bpm
        return {
            "status": "success",
            "music_bpm": body.music_bpm,
            "beat_interval_seconds": round(beat_interval, 3),
            "video_duration": duration,
            "cut_count": len(cut_points),
            "cut_points": [round(t, 3) for t in cut_points],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profile")
async def analyze_audio_profile(body: AudioProfileRequest):
    """
    Analyse a clip's audio characteristics without recommending tracks.
    Returns dominant mood, energy curve, scene-change timestamps, BPM range,
    and suitable genres for downstream use.
    """
    svc = get_audio_recommendation_service()
    clip = Path(body.clip_path)

    try:
        profile = await svc.analyze_video_for_audio(clip, body.transcript)
        return {
            "status": "success",
            "duration": profile.duration,
            "has_voiceover": profile.has_voiceover,
            "dominant_mood": profile.dominant_mood,
            "energy_curve": profile.energy_curve,
            "scene_changes": profile.scene_changes,
            "recommended_bpm_range": list(profile.recommended_bpm_range),
            "suitable_genres": [g.value for g in profile.suitable_genres],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trending")
def get_trending_audio(platform: str = "tiktok"):
    """Get currently trending audio tracks for the given platform."""
    svc = get_audio_recommendation_service()
    trending = svc.get_trending_audio(platform=platform)
    return {
        "status": "success",
        "platform": platform,
        "count": len(trending),
        "tracks": [_fmt_rec(r) for r in trending],
    }


@router.get("/stats")
def get_audio_stats():
    """Audio library statistics: track counts, genres available, recommendations served."""
    svc = get_audio_recommendation_service()
    stats = svc.get_audio_stats()
    return {"status": "success", "stats": stats}


@router.get("/genres")
def list_genres():
    """List all available music genres and audio types."""
    return {
        "genres": [g.value for g in MusicGenre],
        "audio_types": [t.value for t in AudioType],
    }
