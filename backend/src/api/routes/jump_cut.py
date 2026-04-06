"""Jump-Cut Engine API routes."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/jump-cut", tags=["jump-cut"])


class JumpCutRequest(BaseModel):
    video_path: str
    remove_fillers: bool = True
    remove_silence: bool = True
    silence_threshold_db: float = -35.0
    silence_min_duration: float = 0.4
    custom_fillers: Optional[List[str]] = None
    words: Optional[List[dict]] = None  # word-level transcript


class JumpCutResponse(BaseModel):
    output_path: str
    original_duration: float
    output_duration: float
    compression_ratio: float
    time_saved: float
    segments_removed: int
    filler_words_removed: int
    silence_gaps_removed: int
    error: Optional[str] = None


@router.post("/apply", response_model=JumpCutResponse)
async def apply_jump_cuts(body: JumpCutRequest):
    """
    Apply jump cuts to a video: remove silence gaps and filler words.

    Returns the output path to the cleaned version of the clip.
    """
    if not Path(body.video_path).exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {body.video_path}")

    from ...services.jump_cut_service import apply_jump_cuts as _apply

    out_dir = Path(body.video_path).parent
    stem = Path(body.video_path).stem
    output_path = str(out_dir / f"{stem}_jumpcut.mp4")

    result = await _apply(
        video_path=body.video_path,
        output_path=output_path,
        words=body.words,
        remove_fillers=body.remove_fillers,
        remove_silence=body.remove_silence,
        silence_threshold_db=body.silence_threshold_db,
        silence_min_duration=body.silence_min_duration,
        custom_fillers=body.custom_fillers,
    )

    return JumpCutResponse(
        output_path=result.output_path,
        original_duration=result.original_duration,
        output_duration=result.output_duration,
        compression_ratio=result.compression_ratio,
        time_saved=result.time_saved,
        segments_removed=result.segments_removed,
        filler_words_removed=result.filler_words_removed,
        silence_gaps_removed=result.silence_gaps_removed,
        error=result.error,
    )


@router.get("/fillers")
def list_default_fillers():
    """List the default filler words that will be removed."""
    from ...services.jump_cut_service import DEFAULT_FILLERS
    return {"fillers": sorted(DEFAULT_FILLERS)}


@router.post("/detect-silence")
async def detect_silence_gaps(
    video_path: str,
    threshold_db: float = -35.0,
    min_duration: float = 0.4,
):
    """Detect silence intervals in a video without applying cuts."""
    if not Path(video_path).exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {video_path}")

    from ...services.jump_cut_service import detect_silence as _detect
    silences = await _detect(video_path, threshold_db, min_duration)
    return {
        "video_path": video_path,
        "silence_count": len(silences),
        "intervals": [{"start": s, "end": e, "duration": e - s} for s, e in silences],
    }
