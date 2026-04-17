"""Clip Health Report API — actionable health checks beyond a single score."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/clip-health", tags=["Clip Health"])


class HealthReportRequest(BaseModel):
    clip_id: str
    virality_score: float = 0.0
    hook_score: Optional[float] = None
    hook_start: Optional[float] = None
    hook_type: Optional[str] = None
    duration: float = 30.0
    platform: str = "tiktok"
    loudnorm_applied: bool = False
    sfx_injected: bool = False
    audio_energy: Optional[float] = None
    broll_count: int = 0
    has_subtitles: bool = False
    hashtag_count: int = 0
    thumbnail_path: Optional[str] = None
    zoom_punch_applied: bool = False


@router.post("/report")
def get_health_report(req: HealthReportRequest):
    """Generate a full actionable health report for a clip."""
    from src.services.clip_health_service import generate_health_report
    report = generate_health_report(
        clip_id=req.clip_id,
        virality_score=req.virality_score,
        hook_score=req.hook_score,
        hook_start=req.hook_start,
        hook_type=req.hook_type,
        duration=req.duration,
        platform=req.platform,
        loudnorm_applied=req.loudnorm_applied,
        sfx_injected=req.sfx_injected,
        audio_energy=req.audio_energy,
        broll_count=req.broll_count,
        has_subtitles=req.has_subtitles,
        hashtag_count=req.hashtag_count,
        thumbnail_path=req.thumbnail_path,
        zoom_punch_applied=req.zoom_punch_applied,
    )
    return report.to_dict()


@router.post("/batch")
def get_batch_health_reports(clips: list[HealthReportRequest]):
    """Generate health reports for multiple clips at once."""
    if not clips:
        raise HTTPException(status_code=400, detail="No clips provided")
    from src.services.clip_health_service import generate_health_report
    reports = []
    for req in clips:
        r = generate_health_report(
            clip_id=req.clip_id,
            virality_score=req.virality_score,
            hook_score=req.hook_score,
            hook_start=req.hook_start,
            hook_type=req.hook_type,
            duration=req.duration,
            platform=req.platform,
            loudnorm_applied=req.loudnorm_applied,
            sfx_injected=req.sfx_injected,
            audio_energy=req.audio_energy,
            broll_count=req.broll_count,
            has_subtitles=req.has_subtitles,
            hashtag_count=req.hashtag_count,
            thumbnail_path=req.thumbnail_path,
            zoom_punch_applied=req.zoom_punch_applied,
        )
        reports.append(r.to_dict())
    avg_score = sum(r["overall_score"] for r in reports) / len(reports)
    return {
        "reports": reports,
        "count": len(reports),
        "average_score": round(avg_score, 1),
    }
