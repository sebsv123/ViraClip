"""
Video Polish API Routes
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.video_polish_service import VideoPolishService

router = APIRouter(prefix="/polish", tags=["Video Polish"])

_svc: Optional[VideoPolishService] = None


def _get_svc() -> VideoPolishService:
    global _svc
    if _svc is None:
        _svc = VideoPolishService()
    return _svc


class PolishRequest(BaseModel):
    input_path: str
    output_path: str


class PatternInterruptRequest(BaseModel):
    input_path: str
    output_path: str
    viral_cues: List[Dict[str, Any]] = Field(default_factory=list)


@router.post("/auto-center-face")
async def auto_center_face(body: PolishRequest) -> Dict[str, Any]:
    """Zoom in and center the face for a better portrait/shorts look."""
    svc = _get_svc()
    try:
        success = await svc.auto_center_face(Path(body.input_path), Path(body.output_path))
        return {
            "input": body.input_path,
            "output": body.output_path,
            "success": success,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/eye-contact")
async def apply_eye_contact_correction(body: PolishRequest) -> Dict[str, Any]:
    """Apply subtle gaze correction so the speaker appears to look at camera."""
    svc = _get_svc()
    try:
        await svc.apply_eye_contact_correction(Path(body.input_path), Path(body.output_path))
        return {
            "input": body.input_path,
            "output": body.output_path,
            "applied": True,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pattern-interrupts")
async def apply_pattern_interrupts(body: PatternInterruptRequest) -> Dict[str, Any]:
    """Apply dynamic micro-zoom pattern interrupts to maximize viewer retention."""
    svc = _get_svc()
    try:
        success = await svc.apply_pattern_interrupts(
            Path(body.input_path), Path(body.output_path), viral_cues=body.viral_cues
        )
        return {
            "input": body.input_path,
            "output": body.output_path,
            "cues_applied": len(body.viral_cues),
            "success": success,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
