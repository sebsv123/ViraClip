"""
Automation API Routes
=====================

Endpoints for full automation:
- Platform OAuth (YouTube, TikTok, Instagram)
- Auto-publishing configuration
- Scheduling recurring tasks
- A/B testing management
- Trend triggers
- Analytics feedback

Router prefix: /api/auto
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field

from ...database import get_db
from ...models import User
from ...services.auto_scheduler import AutoSchedulerService, ScheduleFrequency, TriggerType
from ...services.ab_testing_service import ABTestingService, VariantStyle
from ...services.youtube_upload_service import YouTubeUploadService, YouTubeCredentials
from ...services.tiktok_upload_service import TikTokUploadService, TikTokCredentials
from ...services.instagram_upload_service import InstagramUploadService, InstagramCredentials
from ...services.analytics_feedback import AnalyticsFeedbackService

router = APIRouter(prefix="/auto", tags=["Automation"])


# ============ OAuth Routes ============

@router.get("/auth/youtube/url")
async def get_youtube_oauth_url(user_id: str) -> Dict[str, str]:
    """Get YouTube OAuth authorization URL."""
    service = YouTubeUploadService()
    state = f"user_{user_id}"  # CSRF protection
    url = service.get_oauth_url(state=state)
    return {"oauth_url": url, "state": state}


class OAuthExchangeRequest(BaseModel):
    code: str
    user_id: str


@router.post("/auth/youtube/exchange")
async def exchange_youtube_code(req: OAuthExchangeRequest) -> Dict[str, Any]:
    """Exchange OAuth code for YouTube tokens."""
    service = YouTubeUploadService()
    
    try:
        credentials = await service.exchange_code(req.code)
        
        # Store in user record
        async for db in get_db():
            user = await db.get(User, req.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            import json
            user.youtube_credentials = json.dumps({
                "access_token": credentials.access_token,
                "refresh_token": credentials.refresh_token,
                "expires_at": credentials.expires_at.isoformat(),
            })
            await db.commit()
        
        return {"success": True, "expires_at": credentials.expires_at.isoformat()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/auth/tiktok/url")
async def get_tiktok_oauth_url(user_id: str) -> Dict[str, str]:
    """Get TikTok OAuth authorization URL."""
    service = TikTokUploadService()
    url = service.get_oauth_url(state=f"user_{user_id}")
    return {"oauth_url": url}


@router.post("/auth/tiktok/exchange")
async def exchange_tiktok_code(req: OAuthExchangeRequest) -> Dict[str, Any]:
    """Exchange OAuth code for TikTok tokens."""
    service = TikTokUploadService()
    
    try:
        credentials = await service.exchange_code(req.code)
        
        async for db in get_db():
            user = await db.get(User, req.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            import json
            user.tiktok_credentials = json.dumps({
                "access_token": credentials.access_token,
                "refresh_token": credentials.refresh_token,
                "open_id": credentials.open_id,
                "expires_at": credentials.expires_at.isoformat(),
            })
            await db.commit()
        
        return {"success": True, "open_id": credentials.open_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/auth/instagram/url")
async def get_instagram_oauth_url(user_id: str) -> Dict[str, str]:
    """Get Instagram OAuth authorization URL."""
    service = InstagramUploadService()
    url = service.get_oauth_url(state=f"user_{user_id}")
    return {"oauth_url": url}


@router.post("/auth/instagram/exchange")
async def exchange_instagram_code(req: OAuthExchangeRequest) -> Dict[str, Any]:
    """Exchange OAuth code for Instagram tokens."""
    service = InstagramUploadService()
    
    try:
        credentials = await service.exchange_code(req.code)
        
        async for db in get_db():
            user = await db.get(User, req.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            import json
            user.instagram_credentials = json.dumps({
                "access_token": credentials.access_token,
                "user_id": credentials.user_id,
                "expires_at": credentials.expires_at.isoformat(),
            })
            await db.commit()
        
        return {"success": True, "user_id": credentials.user_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============ Scheduling Routes ============

class CreateScheduleRequest(BaseModel):
    user_id: str
    name: str
    source_type: str  # youtube_channel, rss_feed, etc.
    source_url: str
    frequency: str  # hourly, daily, weekly, monthly
    cron_expression: Optional[str] = None
    processing_config: Dict[str, Any] = Field(default_factory=dict)
    publish_config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/schedule")
async def create_scheduled_job(req: CreateScheduleRequest) -> Dict[str, Any]:
    """Create a recurring scheduled job."""
    scheduler = AutoSchedulerService()
    
    frequency = ScheduleFrequency(req.frequency)
    
    job = await scheduler.schedule_recurring_source(
        user_id=req.user_id,
        name=req.name,
        source_type=req.source_type,
        source_url=req.source_url,
        frequency=frequency,
        cron_expression=req.cron_expression,
        processing_config=req.processing_config,
        publish_config=req.publish_config,
    )
    
    return {
        "job_id": job.job_id,
        "name": job.name,
        "next_run": job.next_run.isoformat() if job.next_run else None,
    }


@router.get("/schedule/list")
async def list_scheduled_jobs(user_id: str) -> List[Dict[str, Any]]:
    """List all scheduled jobs for a user."""
    scheduler = AutoSchedulerService()
    jobs = await scheduler.get_user_schedules(user_id)
    
    return [
        {
            "job_id": job.job_id,
            "name": job.name,
            "source_type": job.source_config.get("type"),
            "frequency": job.frequency.value if job.frequency else None,
            "is_active": job.is_active,
            "next_run": job.next_run.isoformat() if job.next_run else None,
            "run_count": job.run_count,
        }
        for job in jobs
    ]


@router.delete("/schedule/{job_id}")
async def delete_scheduled_job(job_id: str, user_id: str) -> Dict[str, bool]:
    """Deactivate a scheduled job."""
    scheduler = AutoSchedulerService()
    success = await scheduler.deactivate_job(user_id, job_id)
    return {"success": success}


# ============ A/B Testing Routes ============

class CreateABTestRequest(BaseModel):
    user_id: str
    clip_id: str
    num_variants: int = Field(3, ge=2, le=5)
    test_duration_hours: int = Field(24, ge=1, le=168)
    test_accounts: Optional[Dict[str, str]] = None


@router.post("/abtest/create")
async def create_ab_test(req: CreateABTestRequest) -> Dict[str, Any]:
    """Create an A/B test for a clip."""
    ab_service = ABTestingService()
    
    test = await ab_service.create_ab_test(
        user_id=req.user_id,
        original_clip_id=req.clip_id,
        num_variants=req.num_variants,
        test_duration_hours=req.test_duration_hours,
        test_accounts=req.test_accounts,
    )
    
    return {
        "test_id": test.test_id,
        "name": test.name,
        "variants": [
            {
                "variant_id": v.variant_id,
                "style": v.style.value,
                "clip_id": v.clip_id,
            }
            for v in test.variants
        ],
        "status": test.status,
    }


@router.post("/abtest/start")
async def start_ab_test(test_id: str, user_id: str) -> Dict[str, Any]:
    """Start an A/B test."""
    ab_service = ABTestingService()
    success = await ab_service.start_test(user_id, test_id)
    return {"success": success}


@router.get("/abtest/results")
async def get_ab_test_results(test_id: str, user_id: str) -> Dict[str, Any]:
    """Get A/B test results."""
    ab_service = ABTestingService()
    
    test = await ab_service._load_test(user_id, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    
    winner = None
    if test.winner_variant_id:
        winner = next((v for v in test.variants if v.variant_id == test.winner_variant_id), None)
    
    return {
        "test_id": test.test_id,
        "status": test.status,
        "started_at": test.started_at.isoformat() if test.started_at else None,
        "completed_at": test.completed_at.isoformat() if test.completed_at else None,
        "winner": {
            "variant_id": winner.variant_id if winner else None,
            "style": winner.style.value if winner else None,
            "virality_score": winner.virality_score if winner else None,
        } if winner else None,
        "confidence_level": test.confidence_level,
        "variants": [
            {
                "variant_id": v.variant_id,
                "style": v.style.value,
                "status": v.status,
                "views": v.views,
                "engagement_rate": v.engagement_rate,
                "virality_score": v.virality_score,
            }
            for v in test.variants
        ],
    }


@router.get("/abtest/list")
async def list_ab_tests(user_id: str) -> List[Dict[str, Any]]:
    """List all A/B tests for a user."""
    ab_service = ABTestingService()
    tests = await ab_service.get_user_tests(user_id)
    
    return [
        {
            "test_id": t.test_id,
            "name": t.name,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "num_variants": len(t.variants),
            "winner": t.winner_variant_id,
        }
        for t in tests
    ]


# ============ Trend Trigger Routes ============

class CreateTrendTriggerRequest(BaseModel):
    user_id: str
    keywords: List[str]
    min_virality_score: float = Field(75.0, ge=0, le=100)
    processing_config: Dict[str, Any] = Field(default_factory=dict)
    publish_config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/trend-triggers")
async def create_trend_trigger(req: CreateTrendTriggerRequest) -> Dict[str, Any]:
    """Create a trend trigger for auto-processing."""
    scheduler = AutoSchedulerService()
    
    trigger = await scheduler.create_trend_trigger(
        user_id=req.user_id,
        keywords=req.keywords,
        min_virality_score=req.min_virality_score,
        processing_config=req.processing_config,
        publish_config=req.publish_config,
    )
    
    return {
        "trigger_id": trigger.trigger_id,
        "keywords": trigger.keywords,
        "is_active": trigger.is_active,
    }


@router.get("/trend-triggers")
async def list_trend_triggers(user_id: str) -> List[Dict[str, Any]]:
    """List trend triggers for a user."""
    # Implementation would fetch from Redis
    return []  # Placeholder


# ============ Analytics Routes ============

@router.post("/analytics/update")
async def update_analytics(background_tasks: BackgroundTasks) -> Dict[str, str]:
    """Trigger analytics update for all published clips."""
    async def _update():
        async for db in get_db():
            feedback = AnalyticsFeedbackService()
            await feedback.update_clip_metrics(db)
            break
    
    background_tasks.add_task(_update)
    return {"status": "update_started"}


@router.get("/clips/{clip_id}/performance")
async def get_clip_performance(clip_id: str) -> Dict[str, Any]:
    """Get performance metrics for a clip."""
    from sqlalchemy import select
    from ...models import GeneratedClip
    
    async for db in get_db():
        result = await db.execute(
            select(GeneratedClip).where(GeneratedClip.id == clip_id)
        )
        clip = result.scalar_one_or_none()
        
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        
        feedback = AnalyticsFeedbackService()
        actual_virality = await feedback.compute_actual_virality(clip)
        
        return {
            "clip_id": clip_id,
            "predicted_virality": clip.virality_score,
            "actual_virality": actual_virality,
            "platforms": {
                "youtube": {
                    "video_id": clip.youtube_video_id,
                    "views": clip.youtube_views,
                    "likes": clip.youtube_likes,
                    "engagement_rate": clip.youtube_engagement_rate,
                },
                "tiktok": {
                    "video_id": clip.tiktok_video_id,
                    "views": clip.tiktok_views,
                    "likes": clip.tiktok_likes,
                    "engagement_rate": clip.tiktok_engagement_rate,
                },
                "instagram": {
                    "media_id": clip.instagram_media_id,
                    "impressions": clip.instagram_impressions,
                    "engagement": clip.instagram_engagement,
                    "engagement_rate": clip.instagram_engagement_rate,
                },
            },
            "metrics_last_updated": clip.metrics_last_updated.isoformat() if clip.metrics_last_updated else None,
        }


# ============ Notification Routes ============

class UpdateNotificationPrefsRequest(BaseModel):
    email_notifications: bool = True
    slack_webhook_url: Optional[str] = None
    discord_webhook_url: Optional[str] = None


@router.post("/user/notifications")
async def update_notification_preferences(
    user_id: str,
    req: UpdateNotificationPrefsRequest,
) -> Dict[str, bool]:
    """Update user notification preferences."""
    async for db in get_db():
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user.email_notifications = req.email_notifications
        user.slack_webhook_url = req.slack_webhook_url
        user.discord_webhook_url = req.discord_webhook_url
        await db.commit()
    
    return {"success": True}


@router.post("/user/notifications/test")
async def test_notification(user_id: str) -> Dict[str, bool]:
    """Send a test notification."""
    from ...services.notification_service import NotificationService
    
    notifier = NotificationService()
    await notifier.notify_clip_complete(
        user_id=user_id,
        clip_id="test_clip_id",
        viral_score=85,
    )
    
    return {"success": True}
