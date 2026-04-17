"""
Computer Vision API — ViraClip

Endpoints for frame-level visual analysis, face/text/color detection,
engagement prediction, and best-thumbnail-frame selection.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.computer_vision import (
    VisualElement,
    get_computer_vision_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/computer-vision", tags=["computer-vision"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    video_path: str
    sample_interval: float = 1.0     # seconds between sampled frames


class BestFramesRequest(BaseModel):
    video_path: str
    criteria: str = "engagement"     # engagement | brightness
    count: int = 5


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/analyze")
async def analyze_video(body: AnalyzeRequest):
    """
    Perform frame-by-frame visual analysis on a video.

    Samples frames at `sample_interval` seconds and returns per-frame:
    - Faces (position, confidence, emotion, camera-gaze)
    - Text regions (OCR)
    - Dominant colours (RGB)
    - Brightness, contrast, sharpness
    - Motion score
    - Engagement prediction (0-1)

    Results are cached server-side for `/computer-vision/summary` and
    `/computer-vision/best-frames`.
    """
    if body.sample_interval <= 0:
        raise HTTPException(status_code=400, detail="sample_interval must be > 0")

    svc = get_computer_vision_service()
    try:
        analyses = await svc.analyze_video_visuals(
            Path(body.video_path), body.sample_interval
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "analyzed",
        "frames_analyzed": len(analyses),
        "frames": [
            {
                "timestamp": a.timestamp,
                "faces": a.faces,
                "text_regions": a.text_regions,
                "dominant_colors": [list(c) for c in a.dominant_colors],
                "brightness": round(a.brightness, 3),
                "contrast": round(a.contrast, 3),
                "sharpness": round(a.sharpness, 3),
                "motion_score": round(a.motion_score, 3),
                "engagement_prediction": round(a.engagement_prediction, 3),
            }
            for a in analyses
        ],
    }


@router.get("/summary")
def get_summary(video_path: str):
    """
    Get aggregated visual analysis summary for a previously analysed video.
    Returns averages for brightness, contrast, sharpness, engagement
    and total face presence count.
    """
    svc = get_computer_vision_service()
    summary = svc.get_visual_summary(Path(video_path))

    if "error" in summary:
        raise HTTPException(
            status_code=404,
            detail=f"{summary['error']}. Run POST /computer-vision/analyze first.",
        )
    return {"status": "success", "summary": summary}


@router.post("/best-frames")
def find_best_frames(body: BestFramesRequest):
    """
    Return the timestamps of the best frames from a previously analysed video.

    `criteria` options:
    - **engagement** — frames with highest predicted viewer engagement
    - **brightness** — frames with best lighting
    """
    if body.criteria not in ("engagement", "brightness"):
        raise HTTPException(
            status_code=400,
            detail="criteria must be 'engagement' or 'brightness'",
        )
    if body.count < 1:
        raise HTTPException(status_code=400, detail="count must be >= 1")

    svc = get_computer_vision_service()
    timestamps = svc.find_best_frames(
        Path(body.video_path), body.criteria, body.count
    )

    if not timestamps:
        raise HTTPException(
            status_code=404,
            detail="No cached analysis found. Run POST /computer-vision/analyze first.",
        )
    return {
        "status": "success",
        "criteria": body.criteria,
        "count": len(timestamps),
        "timestamps": timestamps,
    }


@router.get("/elements")
def list_elements():
    """List all detectable visual element types."""
    return {"elements": [e.value for e in VisualElement]}
