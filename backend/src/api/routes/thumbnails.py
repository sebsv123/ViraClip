"""
AI Thumbnail API — ViraClip

Endpoints for generating, batch-generating, and recommending
viral-optimised thumbnails from video clips.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.ai_thumbnail_service import (
    ThumbnailStyle,
    get_thumbnail_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/thumbnails", tags=["thumbnails"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class GenerateThumbnailRequest(BaseModel):
    clip_path: str
    style: str = "face_focus"           # face_focus | action_shot | text_overlay | split_screen | minimal | high_contrast
    custom_text: Optional[str] = None
    timestamp: Optional[float] = None   # auto-select optimal frame if omitted


class BatchGenerateRequest(BaseModel):
    clip_paths: List[str]
    style: str = "face_focus"


class AnalyzeFramesRequest(BaseModel):
    clip_path: str
    num_frames: int = 10


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_style(value: str) -> ThumbnailStyle:
    try:
        return ThumbnailStyle(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid style '{value}'. Choose: {[s.value for s in ThumbnailStyle]}",
        )


def _fmt_thumbnail(t) -> Dict[str, Any]:
    return {
        "thumbnail_id": t.thumbnail_id,
        "video_path": str(t.video_path),
        "timestamp": t.timestamp,
        "style": t.style.value,
        "output_path": str(t.output_path),
        "dimensions": list(t.dimensions),
        "file_size_kb": round(t.file_size_kb, 1),
        "quality_score": round(t.quality_score, 3),
        "viral_potential": round(t.viral_potential, 3),
        "variants": [str(v) for v in t.variants],
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/generate")
async def generate_thumbnail(body: GenerateThumbnailRequest):
    """
    Generate a viral-optimised thumbnail from a video clip.

    The service automatically selects the highest-scoring frame unless
    `timestamp` is provided. Returns the main thumbnail plus style variants.

    **style** options: `face_focus | action_shot | text_overlay |
    split_screen | minimal | high_contrast`
    """
    svc = get_thumbnail_service()
    clip = Path(body.clip_path)

    try:
        result = await svc.generate_thumbnail(
            video_path=clip,
            style=_parse_style(body.style),
            custom_text=body.custom_text,
            timestamp=body.timestamp,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not generate thumbnail — check that the clip exists at '{body.clip_path}'",
        )
    return {"status": "success", "thumbnail": _fmt_thumbnail(result)}


@router.post("/generate/batch")
async def batch_generate(body: BatchGenerateRequest):
    """Generate thumbnails for multiple clips in one call."""
    if not body.clip_paths:
        raise HTTPException(status_code=400, detail="clip_paths must not be empty")

    svc = get_thumbnail_service()
    style = _parse_style(body.style)
    clips = [Path(p) for p in body.clip_paths]

    try:
        results = await svc.batch_generate_thumbnails(clips, style)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "count": len(results),
        "thumbnails": [_fmt_thumbnail(t) for t in results],
    }


@router.post("/analyze")
async def analyze_frames(body: AnalyzeFramesRequest):
    """
    Analyse candidate frames in a clip and rank them by thumbnail suitability.
    Useful for letting users pick their preferred frame before generating.
    """
    svc = get_thumbnail_service()
    clip = Path(body.clip_path)

    try:
        analyses = await svc.analyze_optimal_frames(clip, num_frames=body.num_frames)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "count": len(analyses),
        "frames": [
            {
                "timestamp": a.timestamp,
                "face_detected": a.face_detected,
                "brightness_score": round(a.brightness_score, 3),
                "contrast_score": round(a.contrast_score, 3),
                "clarity_score": round(a.clarity_score, 3),
                "emotion_score": round(a.emotion_score, 3),
                "overall_score": round(a.overall_score, 3),
            }
            for a in analyses
        ],
    }


@router.get("/recommend")
def recommend_styles(niche: str = "education"):
    """Get the recommended thumbnail styles for a content niche."""
    svc = get_thumbnail_service()
    styles = svc.get_thumbnail_recommendations(niche)
    return {
        "niche": niche,
        "recommended_styles": [s.value for s in styles],
    }


@router.get("/styles")
def list_styles():
    """List all available thumbnail styles with descriptions."""
    descriptions = {
        ThumbnailStyle.FACE_FOCUS: "Close-up of speaker face — highest CTR for personal branding",
        ThumbnailStyle.ACTION_SHOT: "Dynamic moment — great for sports/fitness/gaming",
        ThumbnailStyle.TEXT_OVERLAY: "Headline text over frame — strong for educational content",
        ThumbnailStyle.SPLIT_SCREEN: "Before/after or comparison layout",
        ThumbnailStyle.MINIMAL: "Clean and simple — works for tutorials and tech",
        ThumbnailStyle.HIGH_CONTRAST: "Bold colours — eye-catching in a crowded feed",
    }
    return {
        "styles": [
            {"value": s.value, "description": descriptions[s]}
            for s in ThumbnailStyle
        ]
    }
