"""
Beat-Sync Routes — BPM Detection + BGM Auto-Selection
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.beat_sync_service import get_beat_sync_service

router = APIRouter(prefix="/beat-sync", tags=["Beat-Sync BGM"])


class AnalyseBPMRequest(BaseModel):
    audio_path: str = Field(..., min_length=1)
    duration:   float = Field(60.0, gt=0, le=600)


class SelectBGMRequest(BaseModel):
    target_bpm: float = Field(..., gt=30, lt=300)
    prefer_category: Optional[str] = Field(
        None,
        pattern="^(slow|midtempo|upbeat|hype|fast)$",
    )


class SpeechSegment(BaseModel):
    start: float = Field(..., ge=0)
    end:   float = Field(..., ge=0)


class MixRequest(BaseModel):
    video_path:  str = Field(..., min_length=1)
    output_path: str = Field(..., min_length=1)
    bgm_path:    Optional[str] = None
    target_bpm:  Optional[float] = Field(None, gt=30, lt=300)
    speech_segments: List[SpeechSegment] = []
    bgm_volume:  float = Field(0.15, gt=0, le=1.0)


@router.get("/info")
async def get_info() -> Dict[str, Any]:
    """Service info: librosa availability, BGM library size, BPM categories."""
    return get_beat_sync_service().get_info()


@router.get("/library")
async def list_library() -> Dict[str, Any]:
    """List all BGM tracks in the local library with estimated BPM."""
    svc = get_beat_sync_service()
    tracks = svc.list_library()
    return {"tracks": tracks, "count": len(tracks)}


@router.post("/analyse")
async def analyse_bpm(body: AnalyseBPMRequest) -> Dict[str, Any]:
    """Detect BPM and beat timestamps from an audio/video file."""
    svc = get_beat_sync_service()
    try:
        result = await __import__("asyncio").get_event_loop().run_in_executor(
            None, svc.analyse_bpm, Path(body.audio_path), body.duration
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/select")
async def select_bgm(body: SelectBGMRequest) -> Dict[str, Any]:
    """Select the best-matching BGM track for a target BPM."""
    svc = get_beat_sync_service()
    track = svc.select_bgm(body.target_bpm, body.prefer_category)
    if track is None:
        raise HTTPException(status_code=404, detail="No BGM tracks found in library")
    return track


@router.post("/mix")
async def mix_bgm(body: MixRequest) -> Dict[str, Any]:
    """Mix beat-synced BGM into a video with speech-aware volume ducking."""
    svc = get_beat_sync_service()
    segs = [s.model_dump() for s in body.speech_segments]
    try:
        result = await svc.mix(
            video_path=Path(body.video_path),
            output_path=Path(body.output_path),
            bgm_path=Path(body.bgm_path) if body.bgm_path else None,
            target_bpm=body.target_bpm,
            speech_segments=segs,
            bgm_volume=body.bgm_volume,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
