"""
Caption Routes — ASS Karaoke + Box Highlight Burn-in
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.caption_service import get_caption_service

router = APIRouter(prefix="/captions", tags=["Captions"])


class WordItem(BaseModel):
    text: str
    start: float = Field(..., ge=0)
    end: float   = Field(..., ge=0)


class BurnRequest(BaseModel):
    video_path:  str = Field(..., min_length=1)
    output_path: str = Field(..., min_length=1)
    words: List[WordItem]
    style: str = Field("tiktok", pattern="^(karaoke|highlight|tiktok|minimal|neon)$")
    font_dir: Optional[str] = None


class GenerateASSRequest(BaseModel):
    words: List[WordItem]
    style: str = Field("tiktok", pattern="^(karaoke|highlight|tiktok|minimal|neon)$")
    play_res_x: int = Field(1080, gt=0)
    play_res_y: int = Field(1920, gt=0)


class SegmentRequest(BaseModel):
    words: List[WordItem]
    max_words_per_line: int = Field(5, ge=1, le=15)


@router.get("/styles")
async def list_styles() -> Dict[str, Any]:
    svc = get_caption_service()
    return {"styles": svc.get_styles()}


@router.post("/burn")
async def burn_captions(body: BurnRequest) -> Dict[str, Any]:
    """Burn ASS karaoke captions into a video file."""
    svc = get_caption_service()
    words = [w.model_dump() for w in body.words]
    try:
        ok = await svc.burn(
            video_path=Path(body.video_path),
            output_path=Path(body.output_path),
            words=words,
            style=body.style,
            font_dir=body.font_dir,
        )
        return {"success": ok, "output_path": body.output_path, "style": body.style}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def generate_ass(body: GenerateASSRequest) -> Dict[str, Any]:
    """Generate raw ASS script from word timestamps (no video needed)."""
    svc = get_caption_service()
    words = [w.model_dump() for w in body.words]
    try:
        ass = svc.generate_ass(
            words=words,
            style=body.style,
            play_res_x=body.play_res_x,
            play_res_y=body.play_res_y,
        )
        return {"ass_script": ass, "style": body.style, "word_count": len(words)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/segment")
async def segment_words(body: SegmentRequest) -> Dict[str, Any]:
    """Segment word-level timestamps into display-ready caption lines."""
    svc = get_caption_service()
    words = [w.model_dump() for w in body.words]
    try:
        lines = svc.segment_words(words, max_words_per_line=body.max_words_per_line)
        return {"lines": lines, "line_count": len(lines)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
