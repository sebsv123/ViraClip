"""TikTok Templates API — Duet, Stitch, and Green-Screen overlays."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/tiktok-templates", tags=["TikTok Templates"])


class DuetRequest(BaseModel):
    original_path: str
    reaction_path: str
    output_path: Optional[str] = None
    layout: str = "side_by_side"     # side_by_side | stack
    target_w: int = 1080
    target_h: int = 1920


class StitchRequest(BaseModel):
    original_path: str
    reaction_path: str
    output_path: Optional[str] = None
    stitch_seconds: float = 5.0
    target_w: int = 1080
    target_h: int = 1920


class GreenScreenRequest(BaseModel):
    subject_path: str
    background_path: str
    output_path: Optional[str] = None
    chroma_color: str = "0x00FF00"
    similarity: float = 0.30
    blend: float = 0.05
    target_w: int = 1080
    target_h: int = 1920


class SubjectOverBrollRequest(BaseModel):
    subject_path: str
    background_path: str
    output_path: Optional[str] = None
    subject_scale: float = 0.5
    position: str = "bottom_right"
    target_w: int = 1080
    target_h: int = 1920


def _check_file(path: str, label: str) -> None:
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"{label} not found: {path}")


def _default_output(base: str, suffix: str) -> str:
    stem, ext = os.path.splitext(base)
    return f"{stem}_{suffix}{ext}"


@router.post("/duet")
async def render_duet(req: DuetRequest):
    """Create a split-screen duet from two clips."""
    _check_file(req.original_path, "Original clip")
    _check_file(req.reaction_path, "Reaction clip")
    out = req.output_path or _default_output(req.original_path, "duet")

    from src.services.tiktok_templates_service import render_duet as _duet
    result = await _duet(
        req.original_path, req.reaction_path, out,
        layout=req.layout,
        target_w=req.target_w, target_h=req.target_h,
    )
    return {
        "template": result.template, "output_path": result.output_path,
        "width": result.width, "height": result.height,
        "duration": result.duration, "success": result.success,
        "error": result.error or None,
    }


@router.post("/stitch")
async def render_stitch(req: StitchRequest):
    """Stitch N seconds of original + reaction clip."""
    _check_file(req.original_path, "Original clip")
    _check_file(req.reaction_path, "Reaction clip")
    out = req.output_path or _default_output(req.original_path, "stitch")

    from src.services.tiktok_templates_service import render_stitch as _stitch
    result = await _stitch(
        req.original_path, req.reaction_path, out,
        stitch_seconds=req.stitch_seconds,
        target_w=req.target_w, target_h=req.target_h,
    )
    return {
        "template": result.template, "output_path": result.output_path,
        "width": result.width, "height": result.height,
        "duration": result.duration, "success": result.success,
        "error": result.error or None,
    }


@router.post("/green-screen")
async def render_green_screen(req: GreenScreenRequest):
    """Chroma-key subject over background clip."""
    _check_file(req.subject_path, "Subject clip")
    _check_file(req.background_path, "Background clip")
    out = req.output_path or _default_output(req.subject_path, "greenscreen")

    from src.services.tiktok_templates_service import render_green_screen as _gs
    result = await _gs(
        req.subject_path, req.background_path, out,
        chroma_color=req.chroma_color,
        similarity=req.similarity,
        blend=req.blend,
        target_w=req.target_w, target_h=req.target_h,
    )
    return {
        "template": result.template, "output_path": result.output_path,
        "width": result.width, "height": result.height,
        "duration": result.duration, "success": result.success,
        "error": result.error or None,
    }


@router.post("/subject-over-broll")
async def render_subject_over_broll(req: SubjectOverBrollRequest):
    """Overlay subject (no chroma key) over background B-roll."""
    _check_file(req.subject_path, "Subject clip")
    _check_file(req.background_path, "Background clip")
    out = req.output_path or _default_output(req.subject_path, "subject_broll")

    from src.services.tiktok_templates_service import render_subject_over_broll as _sob
    result = await _sob(
        req.subject_path, req.background_path, out,
        subject_scale=req.subject_scale,
        position=req.position,
        target_w=req.target_w, target_h=req.target_h,
    )
    return {
        "template": result.template, "output_path": result.output_path,
        "width": result.width, "height": result.height,
        "duration": result.duration, "success": result.success,
        "error": result.error or None,
    }
