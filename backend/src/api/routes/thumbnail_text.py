"""Thumbnail Text API — overlay hook text on clip thumbnails."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/thumbnail-text", tags=["Thumbnail Text"])


class ThumbnailTextRequest(BaseModel):
    thumbnail_path: str
    hook_text: str
    sub_text: str = ""
    platform: str = "tiktok"
    emoji: str = ""
    position: str = "top"
    font_size: int = 64
    arrow_enabled: bool = True
    arrow_direction: str = "right"
    background_opacity: float = 0.45


@router.post("/generate")
async def generate_thumbnail_text(req: ThumbnailTextRequest):
    """Overlay hook text on an existing thumbnail image."""
    if not os.path.exists(req.thumbnail_path):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    from src.services.thumbnail_text_service import generate_hook_thumbnail
    output = await generate_hook_thumbnail(
        source_thumbnail=req.thumbnail_path,
        hook_text=req.hook_text,
        sub_text=req.sub_text,
        platform=req.platform,
        emoji=req.emoji,
        position=req.position,
    )
    return {
        "output_path": output,
        "hook_text": req.hook_text,
        "platform": req.platform,
    }


@router.post("/generate-for-task/{task_id}/clip/{clip_index}")
async def generate_for_clip(
    task_id: str,
    clip_index: int,
    hook_text: str,
    sub_text: str = "",
    platform: str = "tiktok",
    emoji: str = "🔥",
):
    """Generate hook-text thumbnail for a specific clip by task + index."""
    import os
    clips_dir = os.getenv("CLIPS_DIR", "/app/clips")
    thumb_dir = os.path.join(clips_dir, task_id)

    # Find thumbnail file
    candidates = []
    if os.path.isdir(thumb_dir):
        for f in os.listdir(thumb_dir):
            if f.endswith((".jpg", ".jpeg", ".png")) and "thumb" in f.lower():
                candidates.append(os.path.join(thumb_dir, f))
    candidates.sort()

    if clip_index >= len(candidates):
        raise HTTPException(status_code=404, detail="Thumbnail not found for this clip")

    from src.services.thumbnail_text_service import generate_hook_thumbnail
    output = await generate_hook_thumbnail(
        source_thumbnail=candidates[clip_index],
        hook_text=hook_text,
        sub_text=sub_text,
        platform=platform,
        emoji=emoji,
    )
    return {"output_path": output, "hook_text": hook_text}
