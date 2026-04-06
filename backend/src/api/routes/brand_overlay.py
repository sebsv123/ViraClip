"""Brand/Watermark Overlay API — apply text or image watermark to clips."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/brand-overlay", tags=["Brand Overlay"])


class BrandOverlayRequest(BaseModel):
    video_path: str
    output_path: Optional[str] = None
    text: str = ""
    text_color: str = "white"
    font_size: int = 28
    font_alpha: float = 0.75
    image_path: str = ""
    image_width: int = 120
    image_alpha: float = 0.70
    position: str = "bottom_right"
    margin_x: int = 20
    margin_y: int = 20


class ThumbnailBrandRequest(BaseModel):
    image_path: str
    output_path: Optional[str] = None
    text: str = ""
    font_size: int = 28
    font_alpha: float = 0.75
    position: str = "bottom_right"
    margin_x: int = 20
    margin_y: int = 20


@router.post("/apply")
async def apply_brand_overlay(req: BrandOverlayRequest):
    """Apply text or image watermark to a video clip."""
    if not os.path.exists(req.video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    if not req.text and not req.image_path:
        raise HTTPException(status_code=400, detail="Provide text or image_path")

    from src.services.brand_overlay_service import BrandConfig, apply_brand_overlay
    stem = os.path.splitext(req.video_path)[0]
    out = req.output_path or f"{stem}_branded.mp4"

    cfg = BrandConfig(
        text=req.text,
        text_color=req.text_color,
        font_size=req.font_size,
        font_alpha=req.font_alpha,
        image_path=req.image_path,
        image_width=req.image_width,
        image_alpha=req.image_alpha,
        position=req.position,
        margin_x=req.margin_x,
        margin_y=req.margin_y,
    )
    result = await apply_brand_overlay(req.video_path, out, cfg)
    return {
        "output_path": result,
        "applied": result != req.video_path,
        "type": "image" if (req.image_path and os.path.exists(req.image_path)) else "text",
    }


@router.post("/thumbnail")
def apply_brand_to_thumbnail(req: ThumbnailBrandRequest):
    """Apply text watermark to a thumbnail image."""
    if not os.path.exists(req.image_path):
        raise HTTPException(status_code=404, detail="Image not found")
    if not req.text:
        raise HTTPException(status_code=400, detail="text is required")

    from src.services.brand_overlay_service import BrandConfig, apply_brand_to_thumbnail
    cfg = BrandConfig(
        text=req.text,
        font_size=req.font_size,
        font_alpha=req.font_alpha,
        position=req.position,
        margin_x=req.margin_x,
        margin_y=req.margin_y,
        apply_to_thumbnail=True,
    )
    out = req.output_path or req.image_path
    result = apply_brand_to_thumbnail(req.image_path, cfg, out)
    return {"output_path": result, "applied": result == out}
