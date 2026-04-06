"""
Scene Detection API Routes
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.scene_detection import get_scene_detection_service

router = APIRouter(prefix="/scene", tags=["Scene Detection"])


class DetectScenesRequest(BaseModel):
    video_path: str
    method: str = Field("content", pattern="^(content|uniform)$")


class CutPointsRequest(BaseModel):
    video_path: str
    transcript_segments: Optional[List[Dict[str, Any]]] = None


class ExtractKeyframesRequest(BaseModel):
    video_path: str
    timestamps: List[float] = Field(..., min_length=1)


class ClipBoundariesRequest(BaseModel):
    cut_points: List[Dict[str, Any]] = Field(..., min_length=1)
    target_duration: float = Field(30.0, gt=0, le=300)


@router.post("/detect")
async def detect_scenes(body: DetectScenesRequest) -> Dict[str, Any]:
    """Detect scene changes in a video using FFmpeg content-aware analysis."""
    svc = get_scene_detection_service()
    try:
        scenes = await svc.detect_scenes(Path(body.video_path), method=body.method)
        stats = svc.get_scene_statistics(scenes)
        return {
            "video_path": body.video_path,
            "method": body.method,
            "scene_count": len(scenes),
            "scenes": [
                {
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "duration": s.end_time - s.start_time,
                    "change_type": s.change_type.value if hasattr(s, "change_type") else "cut",
                    "confidence": getattr(s, "confidence", 1.0),
                }
                for s in scenes
            ],
            "statistics": stats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cut-points")
async def find_cut_points(body: CutPointsRequest) -> Dict[str, Any]:
    """Find optimal cut points for clip extraction based on scene content and transcript."""
    svc = get_scene_detection_service()
    try:
        points = await svc.find_optimal_cut_points(
            Path(body.video_path),
            transcript_segments=body.transcript_segments,
        )
        return {
            "video_path": body.video_path,
            "cut_point_count": len(points),
            "cut_points": [
                {
                    "timestamp": p.timestamp,
                    "confidence": p.confidence,
                    "reason": p.reason,
                    "suggested_transition": p.suggested_transition,
                }
                for p in points
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keyframes")
async def extract_keyframes(body: ExtractKeyframesRequest) -> Dict[str, Any]:
    """Extract keyframe images at specified timestamps."""
    svc = get_scene_detection_service()
    try:
        keyframes = await svc.extract_keyframes(Path(body.video_path), body.timestamps)
        return {
            "video_path": body.video_path,
            "requested": len(body.timestamps),
            "extracted": len(keyframes),
            "keyframes": keyframes,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clip-boundaries")
async def suggest_clip_boundaries(body: ClipBoundariesRequest) -> Dict[str, Any]:
    """Suggest clip start/end boundaries from a set of cut points."""
    svc = get_scene_detection_service()
    try:
        suggestions = svc.suggest_clip_boundaries(
            body.cut_points, target_duration=body.target_duration
        )
        return {
            "target_duration": body.target_duration,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
