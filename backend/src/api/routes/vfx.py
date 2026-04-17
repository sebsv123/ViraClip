"""
VFX Service API Routes
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.vfx_service import VFXService

router = APIRouter(prefix="/vfx", tags=["VFX"])


class GenerativeStyleRequest(BaseModel):
    video_path: str
    style_references: List[str] = Field(..., min_length=1)
    intensity: float = Field(0.5, ge=0.0, le=1.0)


class KlingSawpRequest(BaseModel):
    video_path: str
    swap_type: str = Field("wardrobe", pattern="^(wardrobe|background|accessory)$")
    target_description: str = Field(..., min_length=1)


class ViralLoopsRequest(BaseModel):
    video_path: str
    threshold: float = Field(0.80, ge=0.0, le=1.0)


class BrandingRequest(BaseModel):
    video_path: str
    brand_dna: Dict[str, Any]


@router.post("/style")
async def apply_generative_style(body: GenerativeStyleRequest) -> Dict[str, Any]:
    """Apply generative style transfer to a video clip."""
    try:
        result = await VFXService.apply_generative_style(
            Path(body.video_path),
            style_references=body.style_references,
            intensity=body.intensity,
        )
        return {"input": body.video_path, "output": str(result), "intensity": body.intensity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kling-swap")
async def generate_kling_swap(body: KlingSawpRequest) -> Dict[str, Any]:
    """Generate a Kling-style wardrobe/background swap on a video."""
    try:
        result = await VFXService.generate_kling_swap(
            Path(body.video_path),
            swap_type=body.swap_type,
            target_description=body.target_description,
        )
        return {
            "input": body.video_path,
            "output": str(result),
            "swap_type": body.swap_type,
            "target_description": body.target_description,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/viral-loops")
async def detect_viral_loops(body: ViralLoopsRequest) -> Dict[str, Any]:
    """Detect seamless loop candidates in a video for viral loop content."""
    try:
        loops = await VFXService.detect_viral_loops(
            Path(body.video_path), threshold=body.threshold
        )
        return {
            "video_path": body.video_path,
            "threshold": body.threshold,
            "loop_count": len(loops),
            "loops": loops,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/branding")
async def generate_elite_branding(body: BrandingRequest) -> Dict[str, Any]:
    """Apply elite AI-generated branding overlays to a video."""
    try:
        result = await VFXService.generate_elite_branding(
            Path(body.video_path), brand_dna=body.brand_dna
        )
        return {"input": body.video_path, "output": str(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
