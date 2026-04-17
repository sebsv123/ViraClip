"""Narrative Arc API — multi-clip series, best-of compilation, and teaser."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/narrative-arc", tags=["Narrative Arc"])


class ClipMetaRequest(BaseModel):
    clip_id: str
    file_path: str
    duration: float
    virality_score: float
    start_time: float = 0.0
    transcript: str = ""
    order: int = 0


class NarrativeRequest(BaseModel):
    clips: list[ClipMetaRequest]
    strategy: str = "series"         # series | best_of | teaser
    output_dir: Optional[str] = None
    title_prefix: str = "Part"
    max_part_duration: float = 60.0
    best_of_n: int = 5
    best_of_max_duration: float = 90.0
    teaser_duration: float = 15.0


@router.post("/build")
async def build_narrative(req: NarrativeRequest):
    """Build a series, best-of, or teaser from a list of clips."""
    from src.services.narrative_arc_service import (
        ClipMeta, build_series, build_best_of, build_teaser,
    )
    if not req.clips:
        raise HTTPException(status_code=400, detail="No clips provided")

    clips = [
        ClipMeta(
            clip_id=c.clip_id,
            file_path=c.file_path,
            duration=c.duration,
            virality_score=c.virality_score,
            start_time=c.start_time,
            transcript=c.transcript,
            order=c.order,
        )
        for c in req.clips
    ]

    out_dir = req.output_dir or os.getenv("CLIPS_DIR", "/app/clips")
    os.makedirs(out_dir, exist_ok=True)

    if req.strategy == "series":
        result = await build_series(
            clips, out_dir,
            title_prefix=req.title_prefix,
            max_part_duration=req.max_part_duration,
        )
    elif req.strategy == "best_of":
        result = await build_best_of(
            clips, out_dir,
            n=req.best_of_n,
            max_total_duration=req.best_of_max_duration,
        )
    elif req.strategy == "teaser":
        result = await build_teaser(clips, out_dir, teaser_duration=req.teaser_duration)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")

    return {
        "strategy": result.strategy,
        "description": result.description,
        "output_paths": result.output_paths,
        "parts": [
            {
                "part_number": p.part_number,
                "title": p.title,
                "hook_text": p.hook_text,
                "clip_count": len(p.clips),
                "total_duration": round(p.total_duration, 2),
            }
            for p in result.parts
        ],
    }
