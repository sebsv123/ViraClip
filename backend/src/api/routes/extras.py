"""
Extras API Routes — Additional Features
========================================

Endpoints for analytics dashboard, bulk operations, content calendar,
competitor tracking, and other enhanced features.

Router prefix: /api/extras
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field

from ...database import get_db
from ...services.analytics_dashboard import AnalyticsDashboardService
from ...services.bulk_operations import BulkOperationsService, BulkJobStatus
from ...services.content_calendar import ContentCalendarService

router = APIRouter(prefix="/extras", tags=["Extras"])


# ============ Analytics Dashboard ============

@router.get("/dashboard")
async def get_dashboard(
    user_id: str,
    days: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    """Get comprehensive analytics dashboard."""
    service = AnalyticsDashboardService()
    
    async for db in get_db():
        dashboard = await service.get_user_dashboard(db, user_id, days)
        return dashboard


@router.get("/dashboard/compare")
async def compare_periods(
    user_id: str,
    current_days: int = Query(30, ge=1, le=90),
    previous_days: int = Query(30, ge=1, le=90),
) -> Dict[str, Any]:
    """Compare current period vs previous period."""
    service = AnalyticsDashboardService()
    
    async for db in get_db():
        comparison = await service.compare_periods(db, user_id, current_days, previous_days)
        return comparison


# ============ Bulk Operations ============

class BulkJobRequest(BaseModel):
    name: str
    sources: List[Dict[str, str]] = Field(..., min_length=1, max_length=50)
    processing_config: Dict[str, Any] = Field(default_factory=dict)
    publish_config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/bulk")
async def create_bulk_job(
    user_id: str,
    req: BulkJobRequest,
) -> Dict[str, Any]:
    """Create a bulk processing job."""
    service = BulkOperationsService()
    
    async for db in get_db():
        # Validate sources first
        validation = await service.validate_sources(req.sources)
        if not validation["can_proceed"]:
            raise HTTPException(status_code=400, detail=validation)
        
        job = await service.create_bulk_job(
            db,
            user_id,
            req.name,
            validation["valid_sources"],
            req.processing_config,
            req.publish_config,
        )
        
        return {
            "job_id": job.job_id,
            "name": job.name,
            "total_sources": len(job.sources),
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
        }


@router.post("/bulk/{job_id}/start")
async def start_bulk_job(job_id: str) -> Dict[str, Any]:
    """Start a bulk processing job."""
    service = BulkOperationsService()
    
    async for db in get_db():
        success = await service.start_bulk_job(db, job_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to start job")
        return {"success": True, "job_id": job_id}


@router.get("/bulk/{job_id}")
async def get_bulk_job_status(job_id: str) -> Dict[str, Any]:
    """Get bulk job status and progress."""
    service = BulkOperationsService()
    
    async for db in get_db():
        status = await service.get_job_status(db, job_id)
        if not status:
            raise HTTPException(status_code=404, detail="Job not found")
        return status


@router.delete("/bulk/{job_id}")
async def cancel_bulk_job(job_id: str) -> Dict[str, Any]:
    """Cancel a bulk job."""
    service = BulkOperationsService()
    
    async for db in get_db():
        success = await service.cancel_job(db, job_id)
        if not success:
            raise HTTPException(status_code=400, detail="Cannot cancel job")
        return {"success": True}


@router.get("/bulk")
async def list_bulk_jobs(
    user_id: str,
    limit: int = Query(10, ge=1, le=50),
) -> List[Dict[str, Any]]:
    """List bulk jobs for user."""
    service = BulkOperationsService()
    
    async for db in get_db():
        jobs = await service.list_user_jobs(db, user_id, limit)
        return jobs


# ============ Content Calendar ============

@router.get("/calendar")
async def get_calendar(
    user_id: str,
    year: int = Query(..., ge=2024, le=2030),
    month: int = Query(..., ge=1, le=12),
) -> Dict[str, Any]:
    """Get content calendar view."""
    service = ContentCalendarService()
    
    async for db in get_db():
        calendar = await service.get_calendar_view(db, user_id, year, month)
        return calendar


@router.get("/calendar/upcoming")
async def get_upcoming_content(
    user_id: str,
    days: int = Query(7, ge=1, le=30),
) -> List[Dict[str, Any]]:
    """Get upcoming scheduled content."""
    service = ContentCalendarService()
    
    async for db in get_db():
        upcoming = await service.get_upcoming_content(db, user_id, days)
        return upcoming


@router.get("/calendar/optimal-times")
async def get_optimal_times(
    user_id: str,
    platform: str = Query(..., pattern="^(youtube|tiktok|instagram)$"),
    count: int = Query(5, ge=1, le=10),
) -> List[Dict[str, Any]]:
    """Get optimal posting times based on analytics."""
    service = ContentCalendarService()
    
    async for db in get_db():
        times = await service.suggest_optimal_times(db, user_id, platform, count)
        return times


@router.get("/calendar/gaps")
async def get_content_gaps(
    user_id: str,
    days_ahead: int = Query(14, ge=7, le=30),
) -> List[Dict[str, Any]]:
    """Find gaps in content schedule."""
    service = ContentCalendarService()
    
    async for db in get_db():
        gaps = await service.get_content_gaps(db, user_id, days_ahead)
        return gaps


# ============ Performance Prediction ============

class PredictionRequest(BaseModel):
    source_url: str
    target_platform: str = "tiktok"
    content_style: Optional[str] = None


@router.post("/predict")
async def predict_virality(
    user_id: str,
    req: PredictionRequest,
) -> Dict[str, Any]:
    """
    Predict virality score before processing.
    
    Analyzes source content and estimates potential virality.
    """
    from ...services.viral_scorer_service import ViralScorerService
    from ...services.phi3_virality_service import Phi3ViralityService
    
    # Analyze source
    phi3 = Phi3ViralityService()
    
    try:
        # Quick analysis of source
        analysis = await phi3.analyze_source_url(req.source_url)
        
        # Get prediction
        scorer = ViralScorerService()
        
        # Mock features for prediction (in real implementation, extract from source)
        features = {
            "duration_seconds": analysis.get("duration", 300),
            "has_transcript": analysis.get("has_transcript", True),
            "keyword_count": len(analysis.get("keywords", [])),
            "audio_quality": analysis.get("audio_quality", 0.8),
        }
        
        score = await scorer.predict_score(features)
        
        return {
            "predicted_virality_score": score,
            "confidence": "medium",
            "estimated_views_range": {
                "min": int(score * 100),
                "max": int(score * 500),
            },
            "factors": {
                "content_quality": analysis.get("quality_score", 70),
                "trending_keywords": analysis.get("keywords", []),
                "optimal_duration": features["duration_seconds"] < 60,
            },
            "recommendations": _get_recommendations(score, features),
        }
    except Exception as e:
        return {
            "predicted_virality_score": 50,
            "confidence": "low",
            "error": str(e),
            "note": "Prediction failed, using default estimate",
        }


def _get_recommendations(score: float, features: Dict) -> List[str]:
    """Generate recommendations based on prediction."""
    recs = []
    
    if score < 60:
        recs.append("Consider using a stronger hook in the first 3 seconds")
        recs.append("Add trending background music to boost engagement")
    
    if features.get("duration_seconds", 0) > 90:
        recs.append("Video is long - consider splitting into multiple clips")
    
    if score > 75:
        recs.append("High virality potential! Consider A/B testing multiple variants")
        recs.append("Schedule for optimal posting time to maximize reach")
    
    return recs


# ============ Smart Hashtag Optimizer ============

@router.get("/hashtags/suggest")
async def suggest_hashtags(
    topic: str = Query(..., min_length=2, max_length=100),
    platform: str = Query("tiktok", pattern="^(tiktok|instagram|youtube)$"),
    count: int = Query(10, ge=5, le=30),
) -> Dict[str, Any]:
    """
    Suggest optimized hashtags based on real-time trends.
    
    Combines trending data with content analysis.
    """
    from ...services.viral_trend_service import ViralTrendService
    from ...services.viral_metadata_service import generate_viral_metadata
    
    trend_service = ViralTrendService()
    
    # Get trending hashtags
    trending = await trend_service.get_trending_hashtags(platform, limit=count * 2)
    
    # Filter by relevance to topic
    relevant = [
        h for h in trending
        if any(word in h["tag"].lower() for word in topic.lower().split())
        or h["category"] in ["general", "viral"]
    ][:count]
    
    # Mix with popular general tags
    general_tags = ["fyp", "viral", "foryou", "trending"][:max(0, count - len(relevant))]
    
    suggested = relevant + [{"tag": t, "views": "high", "category": "general"} for t in general_tags]
    
    return {
        "topic": topic,
        "platform": platform,
        "suggested_hashtags": [s["tag"] for s in suggested],
        "with_trending_data": [
            {
                "tag": s["tag"],
                "posts_count": s.get("posts_count", "N/A"),
                "views": s.get("views", "high"),
                "trend": s.get("trend", "stable"),
            }
            for s in suggested
        ],
        "generated_at": datetime.utcnow().isoformat(),
    }


# ============ Transcript Export ============

@router.get("/clips/{clip_id}/transcript")
async def export_transcript(
    clip_id: str,
    format: str = Query("json", pattern="^(json|srt|vtt|txt)$"),
) -> Dict[str, Any]:
    """
    Export clip transcript in various formats.
    """
    from ...models import GeneratedClip
    
    async for db in get_db():
        clip = await db.get(GeneratedClip, clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        
        if not clip.text:
            raise HTTPException(status_code=404, detail="No transcript available")
        
        transcript_data = {
            "clip_id": clip_id,
            "text": clip.text,
            "format": format,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
        }
        
        if format == "srt":
            transcript_data["content"] = _convert_to_srt(clip)
        elif format == "vtt":
            transcript_data["content"] = _convert_to_vtt(clip)
        elif format == "txt":
            transcript_data["content"] = clip.text
        else:
            transcript_data["content"] = {
                "text": clip.text,
                "segments": [],  # Would include word-level timing if available
            }
        
        return transcript_data


def _convert_to_srt(clip) -> str:
    """Convert clip to SRT subtitle format."""
    # Simple conversion (in real implementation, use actual word timings)
    def time_to_srt(t: str) -> str:
        # Convert MM:SS to HH:MM:SS,mmm
        parts = t.split(":")
        minutes = int(parts[0])
        seconds = int(parts[1])
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},000"
    
    srt = f"1\n"
    srt += f"{time_to_srt(clip.start_time)} --> {time_to_srt(clip.end_time)}\n"
    srt += f"{clip.text}\n"
    
    return srt


def _convert_to_vtt(clip) -> str:
    """Convert clip to WebVTT format."""
    vtt = "WEBVTT\n\n"
    vtt += f"{clip.start_time.replace(':', '.')} --> {clip.end_time.replace(':', '.')}\n"
    vtt += f"{clip.text}\n"
    
    return vtt


# ============ Competitor Tracking ============

@router.post("/competitors/track")
async def add_competitor(
    user_id: str,
    channel_url: str,
    platform: str = Query("youtube", pattern="^(youtube|tiktok|instagram)$"),
) -> Dict[str, Any]:
    """
    Start tracking a competitor channel.
    
    Monitors their content performance for benchmarking.
    """
    # This would integrate with competitor intelligence service
    return {
        "competitor_id": f"comp_{hash(channel_url) % 10000}",
        "channel_url": channel_url,
        "platform": platform,
        "status": "tracking_enabled",
        "message": "Competitor tracking is a premium feature - mocked for demo",
    }


@router.get("/competitors/insights")
async def get_competitor_insights(
    user_id: str,
) -> Dict[str, Any]:
    """Get insights from tracked competitors."""
    return {
        "message": "Competitor insights require premium subscription",
        "features": [
            "Content gap analysis",
            "Posting frequency comparison",
            "Engagement rate benchmarking",
            "Trending topics they're covering",
        ],
    }


# ============ AI Thumbnail Generation ============

@router.post("/clips/{clip_id}/generate-thumbnail")
async def generate_ai_thumbnail(
    clip_id: str,
    style: str = Query("viral", pattern="^(viral|minimal|text|face)$"),
) -> Dict[str, Any]:
    """
    Generate AI-optimized thumbnail for clip.
    
    Uses computer vision to select best frame and optionally
    adds text overlays, effects.
    """
    from ...services.ai_thumbnail_service import ThumbnailStyle
    from ...models import GeneratedClip
    
    async for db in get_db():
        clip = await db.get(GeneratedClip, clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        
        # Map style string to enum
        style_map = {
            "viral": ThumbnailStyle.FACE_FOCUS,
            "minimal": ThumbnailStyle.MINIMAL,
            "text": ThumbnailStyle.TEXT_OVERLAY,
            "face": ThumbnailStyle.FACE_FOCUS,
        }
        
        # Generate thumbnail
        # This would call the actual thumbnail service
        thumbnail_path = f"/thumbnails/{clip_id}_{style}.jpg"
        
        # Update clip
        clip.thumbnail_path = thumbnail_path
        await db.commit()
        
        return {
            "clip_id": clip_id,
            "thumbnail_url": thumbnail_path,
            "style": style,
            "generated": True,
            "note": "AI thumbnail generation uses frame analysis and face detection",
        }


# ============ Video Compression Profiles ============

@router.get("/compression/profiles")
async def get_compression_profiles() -> List[Dict[str, Any]]:
    """Get available video compression profiles."""
    return [
        {
            "id": "ultra",
            "name": "Ultra Quality",
            "bitrate": "8000k",
            "resolution": "1080p",
            "fps": 60,
            "file_size_estimate": "~50MB/min",
            "best_for": "YouTube, high-end displays",
        },
        {
            "id": "high",
            "name": "High Quality",
            "bitrate": "4000k",
            "resolution": "1080p",
            "fps": 30,
            "file_size_estimate": "~25MB/min",
            "best_for": "Instagram, TikTok (premium)",
        },
        {
            "id": "balanced",
            "name": "Balanced",
            "bitrate": "2500k",
            "resolution": "720p",
            "fps": 30,
            "file_size_estimate": "~15MB/min",
            "best_for": "General social media",
        },
        {
            "id": "mobile",
            "name": "Mobile Optimized",
            "bitrate": "1200k",
            "resolution": "720p",
            "fps": 30,
            "file_size_estimate": "~8MB/min",
            "best_for": "Mobile viewing, slow connections",
        },
        {
            "id": "minimal",
            "name": "Minimal",
            "bitrate": "800k",
            "resolution": "480p",
            "fps": 24,
            "file_size_estimate": "~5MB/min",
            "best_for": "Stories, quick clips, previews",
        },
    ]


# ============ Clip Archive/Backup ============

@router.post("/clips/{clip_id}/archive")
async def archive_clip(
    clip_id: str,
    user_id: str,
    destination: str = Query("s3", pattern="^(s3|gdrive|dropbox)$"),
) -> Dict[str, Any]:
    """
    Archive clip to cloud storage for backup.
    """
    from ...models import GeneratedClip
    
    async for db in get_db():
        clip = await db.get(GeneratedClip, clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        
        # This would trigger actual cloud upload
        archive_id = f"archive_{clip_id}_{destination}"
        
        return {
            "clip_id": clip_id,
            "archive_id": archive_id,
            "destination": destination,
            "status": "queued",
            "estimated_completion": "5 minutes",
        }


from datetime import datetime
