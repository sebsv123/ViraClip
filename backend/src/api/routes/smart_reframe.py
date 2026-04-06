"""Smart Reframe API — generate 1:1 and 16:9 variants from 9:16 clips."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/smart-reframe", tags=["Smart Reframe"])


class ReframeRequest(BaseModel):
    video_path: str
    ratios: list[str] = ["1:1", "16:9"]
    output_dir: Optional[str] = None


@router.post("/generate")
async def generate_reframes(req: ReframeRequest):
    """Generate 1:1 and/or 16:9 variants from a 9:16 video."""
    if not os.path.exists(req.video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    from src.video_processing.smart_reframe import generate_all_reframes
    results = await generate_all_reframes(
        video_path=req.video_path,
        output_dir=req.output_dir,
        ratios=req.ratios,
    )
    return {
        "source": req.video_path,
        "variants": [
            {
                "ratio": r.ratio,
                "output_path": r.output_path,
                "width": r.width,
                "height": r.height,
                "method": r.method,
                "face_x_ratio": r.face_x_ratio,
            }
            for r in results
        ],
    }


@router.post("/tasks/{task_id}/clip/{clip_index}")
async def reframe_task_clip(
    task_id: str,
    clip_index: int,
    ratios: list[str] = ["1:1", "16:9"],
):
    """Auto-reframe a specific clip from a task."""
    clips_dir = os.getenv("CLIPS_DIR", "/app/clips")
    task_dir = os.path.join(clips_dir, task_id)
    if not os.path.isdir(task_dir):
        raise HTTPException(status_code=404, detail="Task not found")

    videos = sorted([
        f for f in os.listdir(task_dir)
        if f.endswith(".mp4") and "1x1" not in f and "16x9" not in f
    ])
    if clip_index >= len(videos):
        raise HTTPException(status_code=404, detail="Clip index out of range")

    video_path = os.path.join(task_dir, videos[clip_index])
    from src.video_processing.smart_reframe import generate_all_reframes
    results = await generate_all_reframes(video_path, output_dir=task_dir, ratios=ratios)
    return {
        "task_id": task_id,
        "clip_index": clip_index,
        "source": video_path,
        "variants": [
            {"ratio": r.ratio, "output_path": r.output_path,
             "width": r.width, "height": r.height, "success": r.method != "failed"}
            for r in results
        ],
    }
