"""A/B Feedback Loop API — import real analytics and close the training loop."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/ab-feedback", tags=["A/B Feedback"])


class ClipAnalyticsRequest(BaseModel):
    clip_id: str
    youtube_video_id: Optional[str] = None
    tiktok_video_id: Optional[str] = None
    predicted_virality: float = 0.0
    feature_vector: Optional[dict] = None


class ManualMetricsRequest(BaseModel):
    clip_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    completion_rate: float = 0.0


@router.post("/import")
async def import_analytics(clips: list[ClipAnalyticsRequest]):
    """Fetch real metrics from TikTok/YouTube APIs and compute actual virality."""
    from src.services.analytics_importer import run_feedback_import
    clips_data = [c.model_dump() for c in clips]
    result = await run_feedback_import(clips_data)
    return {
        "imported": len(result["updates"]),
        "training_samples": len(result["training_samples"]),
        "updates": result["updates"],
    }


@router.post("/manual")
def report_manual_metrics(req: ManualMetricsRequest):
    """Manually report clip performance metrics (no API token needed)."""
    from src.services.analytics_importer import (
        ClipMetrics, compute_actual_virality_score,
    )
    metrics = ClipMetrics(
        clip_id=req.clip_id,
        platform=req.platform,
        views=req.views,
        likes=req.likes,
        comments=req.comments,
        shares=req.shares,
        completion_rate=req.completion_rate,
        engagement_rate=round(
            (req.likes + req.comments + req.shares) / max(req.views, 1), 4
        ),
    )
    actual = compute_actual_virality_score(metrics)
    return {
        "clip_id": req.clip_id,
        "platform": req.platform,
        "actual_virality_score": actual,
        "engagement_rate": metrics.engagement_rate,
    }


@router.get("/score/{clip_id}")
async def get_actual_score(
    clip_id: str,
    youtube_video_id: Optional[str] = None,
    tiktok_video_id: Optional[str] = None,
):
    """Fetch and compute actual virality score for a specific clip."""
    from src.services.analytics_importer import (
        import_metrics_for_clip, compute_actual_virality_score,
    )
    metrics_list = await import_metrics_for_clip(
        clip_id, youtube_video_id, tiktok_video_id
    )
    if not metrics_list:
        raise HTTPException(status_code=404, detail="No metrics found — check platform IDs")
    scores = [
        {"platform": m.platform, "actual_virality": compute_actual_virality_score(m),
         "views": m.views, "engagement_rate": m.engagement_rate}
        for m in metrics_list
    ]
    return {"clip_id": clip_id, "scores": scores}
