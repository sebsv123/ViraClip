"""
Analytics Feedback Loop — Real Performance Metrics
==================================================

Polls YouTube/TikTok/Instagram APIs for real performance data
and feeds it back into the virality prediction model.

Usage:
    from services.analytics_feedback import AnalyticsFeedbackService
    
    feedback = AnalyticsFeedbackService()
    await feedback.update_clip_metrics()
    await feedback.retrain_if_needed()
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ClipPerformance:
    """Performance metrics for a clip."""
    clip_id: str
    platform: str  # youtube, tiktok, instagram
    video_id: str  # Platform's video ID
    
    # Engagement metrics
    views: int
    likes: int
    comments: int
    shares: int
    
    # Quality metrics
    watch_time_seconds: float
    avg_view_duration: float
    completion_rate: float
    ctr: float  # Click-through rate
    
    # Computed virality
    engagement_rate: float  # (likes + comments + shares) / views
    viral_score: float  # 0-100 computed score
    
    # Timestamps
    published_at: datetime
    metrics_updated_at: datetime


class AnalyticsFeedbackService:
    """
    Service for fetching analytics and feeding back into ML models.
    """
    
    def __init__(self):
        self._retrain_threshold = 100  # Retrain after 100 new data points
        self._min_views_for_feedback = 100  # Min views to consider valid
    
    async def update_clip_metrics(self, db: AsyncSession):
        """
        Fetch latest metrics for all published clips.
        
        Called periodically (daily) to update performance data.
        """
        from ...models import GeneratedClip
        
        # Get clips with platform IDs but not recently updated
        yesterday = datetime.utcnow() - timedelta(hours=24)
        
        result = await db.execute(
            select(GeneratedClip).where(
                (GeneratedClip.youtube_video_id != None) |
                (GeneratedClip.tiktok_video_id != None) |
                (GeneratedClip.instagram_media_id != None)
            ).where(
                (GeneratedClip.metrics_last_updated == None) |
                (GeneratedClip.metrics_last_updated < yesterday)
            ).limit(100)  # Batch size
        )
        
        clips = result.scalars().all()
        
        for clip in clips:
            try:
                await self._update_clip_metrics(db, clip)
            except Exception as e:
                logger.error(f"[Analytics] Failed to update metrics for clip {clip.id}: {e}")
        
        await db.commit()
    
    async def _update_clip_metrics(self, db: AsyncSession, clip):
        """Update metrics for a single clip."""
        from ...models import GeneratedClip
        
        # YouTube
        if clip.youtube_video_id and clip.user.youtube_credentials:
            await self._fetch_youtube_metrics(db, clip)
        
        # TikTok
        if clip.tiktok_video_id and clip.user.tiktok_credentials:
            await self._fetch_tiktok_metrics(db, clip)
        
        # Instagram
        if clip.instagram_media_id and clip.user.instagram_credentials:
            await self._fetch_instagram_metrics(db, clip)
        
        # Update timestamp
        clip.metrics_last_updated = datetime.utcnow()
    
    async def _fetch_youtube_metrics(self, db: AsyncSession, clip):
        """Fetch YouTube analytics."""
        from ...services.youtube_upload_service import YouTubeUploadService
        
        try:
            service = YouTubeUploadService()
            
            # Parse credentials
            creds_data = json.loads(clip.user.youtube_credentials)
            from ...services.youtube_upload_service import YouTubeCredentials
            credentials = YouTubeCredentials(**creds_data)
            
            analytics = await service.get_video_analytics(
                video_id=clip.youtube_video_id,
                credentials=credentials,
                days_back=30,
            )
            
            if analytics:
                # Store metrics
                clip.youtube_views = analytics.views
                clip.youtube_likes = analytics.likes
                clip.youtube_comments = analytics.comments
                clip.youtube_watch_time = analytics.estimated_minutes_watched
                clip.youtube_ctr = analytics.ctr
                
                # Calculate engagement rate
                if analytics.views > 0:
                    clip.youtube_engagement_rate = (
                        (analytics.likes + analytics.comments) / analytics.views * 100
                    )
                
                logger.debug(f"[Analytics] YouTube metrics updated for {clip.id}")
                
        except Exception as e:
            logger.warning(f"[Analytics] YouTube fetch failed for {clip.id}: {e}")
    
    async def _fetch_tiktok_metrics(self, db: AsyncSession, clip):
        """Fetch TikTok analytics."""
        from ...services.tiktok_upload_service import TikTokUploadService
        
        try:
            service = TikTokUploadService()
            
            creds_data = json.loads(clip.user.tiktok_credentials)
            from ...services.tiktok_upload_service import TikTokCredentials
            credentials = TikTokCredentials(**creds_data)
            
            metrics = await service.get_video_metrics(
                video_id=clip.tiktok_video_id,
                credentials=credentials,
            )
            
            if metrics:
                clip.tiktok_views = metrics.views
                clip.tiktok_likes = metrics.likes
                clip.tiktok_comments = metrics.comments
                clip.tiktok_shares = metrics.shares
                clip.tiktok_completion_rate = metrics.completion_rate
                
                if metrics.views > 0:
                    clip.tiktok_engagement_rate = (
                        (metrics.likes + metrics.comments + metrics.shares) / metrics.views * 100
                    )
                
                logger.debug(f"[Analytics] TikTok metrics updated for {clip.id}")
                
        except Exception as e:
            logger.warning(f"[Analytics] TikTok fetch failed for {clip.id}: {e}")
    
    async def _fetch_instagram_metrics(self, db: AsyncSession, clip):
        """Fetch Instagram analytics."""
        from ...services.instagram_upload_service import InstagramUploadService
        
        try:
            service = InstagramUploadService()
            
            creds_data = json.loads(clip.user.instagram_credentials)
            from ...services.instagram_upload_service import InstagramCredentials
            credentials = InstagramCredentials(**creds_data)
            
            insights = await service.get_insights(
                media_id=clip.instagram_media_id,
                credentials=credentials,
            )
            
            if insights:
                clip.instagram_impressions = insights.impressions
                clip.instagram_reach = insights.reach
                clip.instagram_engagement = insights.engagement
                clip.instagram_likes = insights.likes
                clip.instagram_comments = insights.comments
                clip.instagram_shares = insights.shares
                clip.instagram_saves = insights.saves
                
                if insights.impressions > 0:
                    clip.instagram_engagement_rate = (
                        insights.engagement / insights.impressions * 100
                    )
                
                logger.debug(f"[Analytics] Instagram metrics updated for {clip.id}")
                
        except Exception as e:
            logger.warning(f"[Analytics] Instagram fetch failed for {clip.id}: {e}")
    
    async def compute_actual_virality(self, clip) -> float:
        """
        Compute actual virality score from real metrics.
        
        Returns:
            0-100 score based on performance
        """
        scores = []
        
        # YouTube scoring
        if clip.youtube_views:
            yt_score = self._compute_platform_score(
                views=clip.youtube_views,
                engagement_rate=clip.youtube_engagement_rate or 0,
                watch_time_ratio=0.5,  # Placeholder
                platform="youtube"
            )
            scores.append(yt_score)
        
        # TikTok scoring
        if clip.tiktok_views:
            tt_score = self._compute_platform_score(
                views=clip.tiktok_views,
                engagement_rate=clip.tiktok_engagement_rate or 0,
                watch_time_ratio=clip.tiktok_completion_rate or 0,
                platform="tiktok"
            )
            scores.append(tt_score)
        
        # Instagram scoring
        if clip.instagram_impressions:
            ig_score = self._compute_platform_score(
                views=clip.instagram_impressions,
                engagement_rate=clip.instagram_engagement_rate or 0,
                watch_time_ratio=0.3,  # Estimated
                platform="instagram"
            )
            scores.append(ig_score)
        
        return sum(scores) / len(scores) if scores else 0.0
    
    def _compute_platform_score(
        self,
        views: int,
        engagement_rate: float,
        watch_time_ratio: float,
        platform: str,
    ) -> float:
        """Compute virality score for a platform."""
        # View count score (log scale)
        if views < 100:
            view_score = 10
        elif views < 1000:
            view_score = 30
        elif views < 10000:
            view_score = 50
        elif views < 100000:
            view_score = 70
        elif views < 1000000:
            view_score = 85
        else:
            view_score = 95
        
        # Engagement score
        if platform == "tiktok":
            # TikTok has higher engagement
            if engagement_rate < 5:
                eng_score = 20
            elif engagement_rate < 10:
                eng_score = 40
            elif engagement_rate < 15:
                eng_score = 60
            else:
                eng_score = 80
        else:
            if engagement_rate < 3:
                eng_score = 20
            elif engagement_rate < 6:
                eng_score = 40
            elif engagement_rate < 10:
                eng_score = 60
            else:
                eng_score = 80
        
        # Watch time score
        wt_score = min(100, watch_time_ratio * 100)
        
        # Weighted combination
        final_score = view_score * 0.5 + eng_score * 0.3 + wt_score * 0.2
        
        return min(100, final_score)
    
    async def prepare_training_data(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Prepare training data from clips with actual performance.
        
        Returns:
            List of training examples with features and actual virality
        """
        from ...models import GeneratedClip
        
        result = await db.execute(
            select(GeneratedClip).where(
                (GeneratedClip.youtube_views > 100) |
                (GeneratedClip.tiktok_views > 100) |
                (GeneratedClip.instagram_impressions > 100)
            ).where(
                GeneratedClip.virality_score != None  # Has predicted score
            )
        )
        
        clips = result.scalars().all()
        training_data = []
        
        for clip in clips:
            actual_virality = await self.compute_actual_virality(clip)
            
            # Skip if too different (outlier detection)
            predicted = clip.virality_score or 50
            if abs(actual_virality - predicted) > 50:
                logger.warning(f"[Analytics] Outlier detected: predicted={predicted}, actual={actual_virality}")
                continue
            
            training_data.append({
                "clip_id": clip.id,
                "predicted_score": predicted,
                "actual_score": actual_virality,
                "features": {
                    "duration": clip.duration,
                    "hook_strength": clip.hook_score,
                    "engagement_prediction": clip.engagement_score,
                    "value_score": clip.value_score,
                    "shareability": clip.shareability_score,
                },
                "platform_performance": {
                    "youtube_views": clip.youtube_views,
                    "tiktok_views": clip.tiktok_views,
                    "instagram_impressions": clip.instagram_impressions,
                }
            })
        
        return training_data
    
    async def retrain_if_needed(self, db: AsyncSession) -> bool:
        """
        Check if we have enough new data to retrain the model.
        
        Returns:
            True if retraining was triggered
        """
        training_data = await self.prepare_training_data(db)
        
        if len(training_data) < self._retrain_threshold:
            logger.info(f"[Analytics] Not enough data for retrain: {len(training_data)}/{self._retrain_threshold}")
            return False
        
        # Trigger retraining via FeedbackLoopService
        from ...services.feedback_loop_service import FeedbackLoopService
        
        feedback_service = FeedbackLoopService(db)
        
        try:
            result = await feedback_service.retrain_model(
                training_data=training_data,
                validate=True,
            )
            
            logger.info(f"[Analytics] Model retrained with {len(training_data)} samples")
            return result.get("deployed", False)
            
        except Exception as e:
            logger.error(f"[Analytics] Retraining failed: {e}")
            return False


__all__ = [
    "AnalyticsFeedbackService",
    "ClipPerformance",
]
