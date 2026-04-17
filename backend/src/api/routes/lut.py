"""
LUT Routes — Cinematic Color Grading via lut3d
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.lut_service import get_lut_service

router = APIRouter(prefix="/lut", tags=["LUT Color Grading"])


class ApplyLUTRequest(BaseModel):
    video_path:  str = Field(..., min_length=1)
    output_path: str = Field(..., min_length=1)
    lut_id: str = Field("teal_orange", min_length=1)
    extra_vf: Optional[str] = None


@router.get("/info")
async def get_info() -> Dict[str, Any]:
    """List available LUTs and their availability (cube file present or fallback)."""
    return get_lut_service().get_info()


@router.get("/list")
async def list_luts() -> Dict[str, Any]:
    svc = get_lut_service()
    return {"luts": svc.list_luts()}


@router.post("/apply")
async def apply_lut(body: ApplyLUTRequest) -> Dict[str, Any]:
    """Apply a cinematic LUT to a video clip."""
    svc = get_lut_service()
    try:
        ok = await svc.apply(
            video_path=Path(body.video_path),
            output_path=Path(body.output_path),
            lut_id=body.lut_id,
        )
        return {"success": ok, "lut_id": body.lut_id, "output_path": body.output_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filter/{lut_id}")
async def get_vf_filter(lut_id: str) -> Dict[str, Any]:
    """Return the FFmpeg vf filter string for a given LUT id."""
    svc = get_lut_service()
    vf = svc.get_vf_filter(lut_id)
    if vf is None:
        raise HTTPException(status_code=404, detail=f"LUT '{lut_id}' not found")
    return {"lut_id": lut_id, "vf_filter": vf}


@router.post("/download")
async def download_luts() -> Dict[str, Any]:
    """Clone YahiaAngelo/Film-Luts into the LUT directory (run once to get 100+ free LUTs)."""
    svc = get_lut_service()
    try:
        result = await svc.download_luts()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
