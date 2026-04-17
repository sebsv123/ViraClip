"""
Analytics Dashboard API — Aggregated Performance Metrics
===========================================================

Provides comprehensive analytics dashboard data:
- Overall account performance across platforms
- Trending clips and virality trends
- Best performing content types
- Growth metrics over time
- Platform comparison

Usage:
    from services.analytics_dashboard import AnalyticsDashboardService
    
    dashboard = AnalyticsDashboardService()
    stats = await dashboard.get_user_dashboard(user_id="xxx", days=30)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class PlatformStats:
    """Stats for a single platform."""
    platform: str
    total_clips: int
    total_views: int
    total_likes: int
    total_comments: int
    avg_engagement_rate: float
    avg_virality_score: float
    best_performing_clip_id: Optional[str] = None
    growth_rate: float = 0.0  # Views growth vs previous period


@dataclass
class ContentTypePerformance:
    """Performance by content type/hook style."""
    hook_type: str
    clip_count: int
    avg_views: float
    avg_engagement_rate: float
    success_rate: float  # % of clips above viral threshold


@dataclass
class TimeSeriesPoint:
    """A single point in a time series."""
    date: str
    clips_published: int
    total_views: int
    avg_virality_score: float


class AnalyticsDashboardService:
    """
    Comprehensive analytics dashboard service.
    """
    
    def __init__(self):
        self.viral_threshold_views = 10000
        self.viral_threshold_engagement = 5.0
    
    async def get_user_dashboard(
        self,
        db: AsyncSession,
        user_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get complete dashboard data for a user.
        
        Args:
            user_id: User ID
            days: Time period for analytics
            
        Returns:
            Complete dashboard data dictionary
        """
        from ...models import GeneratedClip, Task
        
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get all clips for user in date range
        result = await db.execute(
            select(GeneratedClip)
            .join(Task)
            .where(Task.user_id == user_id)
            .where(GeneratedClip.created_at >= start_date)
        )
        clips = result.scalars().all()
        
        if not clips:
            return self._empty_dashboard()
        
        # Calculate all metrics
        platform_stats = await self._get_platform_stats(clips)
        content_performance = self._get_content_type_performance(clips)
        time_series = self._get_time_series(clips, days)
        top_clips = self._get_top_clips(clips, limit=10)
        insights = self._generate_insights(clips, platform_stats, content_performance)
        
        return {
            "summary": {
                "total_clips_generated": len(clips),
                "total_views_across_platforms": sum(p.total_views for p in platform_stats.values()),
                "total_engagements": sum(
                    (p.total_likes + p.total_comments) for p in platform_stats.values()
                ),
                "avg_virality_score": sum(c.virality_score or 0 for c in clips) / len(clips) if clips else 0,
                "viral_clips_count": sum(1 for c in clips if self._is_viral(c)),
                "period_days": days,
            },
            "platforms": {
                name: {
                    "total_clips": stats.total_clips,
                    "total_views": stats.total_views,
                    "total_likes": stats.total_likes,
                    "total_comments": stats.total_comments,
                    "avg_engagement_rate": round(stats.avg_engagement_rate, 2),
                    "avg_virality_score": round(stats.avg_virality_score, 1),
                    "growth_rate": round(stats.growth_rate, 1),
                    "best_clip_id": stats.best_performing_clip_id,
                }
                for name, stats in platform_stats.items()
            },
            "content_performance": [
                {
                    "hook_type": cp.hook_type,
                    "clip_count": cp.clip_count,
                    "avg_views": int(cp.avg_views),
                    "avg_engagement_rate": round(cp.avg_engagement_rate, 2),
                    "success_rate": round(cp.success_rate, 1),
                }
                for cp in content_performance
            ],
            "time_series": [
                {
                    "date": point.date,
                    "clips_published": point.clips_published,
                    "total_views": point.total_views,
                    "avg_virality_score": round(point.avg_virality_score, 1),
                }
                for point in time_series
            ],
            "top_performing_clips": top_clips,
            "ai_insights": insights,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    def _is_viral(self, clip) -> bool:
        """Check if a clip meets viral criteria."""
        total_views = (
            (clip.youtube_views or 0) +
            (clip.tiktok_views or 0) +
            (clip.instagram_impressions or 0)
        )
        
        # Check views threshold
        if total_views >= self.viral_threshold_views:
            return True
        
        # Check engagement rate
        engagement_rates = []
        if clip.youtube_engagement_rate:
            engagement_rates.append(clip.youtube_engagement_rate)
        if clip.tiktok_engagement_rate:
            engagement_rates.append(clip.tiktok_engagement_rate)
        if clip.instagram_engagement_rate:
            engagement_rates.append(clip.instagram_engagement_rate)
        
        if engagement_rates:
            avg_engagement = sum(engagement_rates) / len(engagement_rates)
            if avg_engagement >= self.viral_threshold_engagement:
                return True
        
        # Check predicted virality score
        if clip.virality_score and clip.virality_score >= 80:
            return True
        
        return False
    
    async def _get_platform_stats(
        self,
        clips: List[Any],
    ) -> Dict[str, PlatformStats]:
        """Calculate stats per platform."""
        platforms = ["youtube", "tiktok", "instagram"]
        stats = {}
        
        for platform in platforms:
            platform_clips = [c for c in clips if getattr(c, f"{platform}_video_id") or getattr(c, f"{platform}_media_id")]
            
            if not platform_clips:
                continue
            
            total_views = sum(
                getattr(c, f"{platform}_views", 0) or 
                getattr(c, f"{platform}_impressions", 0) or 0
                for c in platform_clips
            )
            
            total_likes = sum(
                getattr(c, f"{platform}_likes", 0) or 0
                for c in platform_clips
            )
            
            total_comments = sum(
                getattr(c, f"{platform}_comments", 0) or 0
                for c in platform_clips
            )
            
            # Calculate engagement rate
            engagement_rates = [
                getattr(c, f"{platform}_engagement_rate", 0) or 0
                for c in platform_clips
                if getattr(c, f"{platform}_engagement_rate", 0)
            ]
            avg_engagement = sum(engagement_rates) / len(engagement_rates) if engagement_rates else 0
            
            # Calculate virality score
            virality_scores = [c.virality_score or 0 for c in platform_clips]
            avg_virality = sum(virality_scores) / len(virality_scores) if virality_scores else 0
            
            # Find best clip
            best_clip = max(platform_clips, key=lambda c: (
                getattr(c, f"{platform}_views", 0) or 0
            ), default=None)
            
            stats[platform] = PlatformStats(
                platform=platform,
                total_clips=len(platform_clips),
                total_views=total_views,
                total_likes=total_likes,
                total_comments=total_comments,
                avg_engagement_rate=avg_engagement,
                avg_virality_score=avg_virality,
                best_performing_clip_id=best_clip.id if best_clip else None,
            )
        
        return stats
    
    def _get_content_type_performance(
        self,
        clips: List[Any],
    ) -> List[ContentTypePerformance]:
        """Analyze performance by content type/hook."""
        # Group by hook type
        by_hook = defaultdict(list)
        for clip in clips:
            hook = clip.hook_type or "unknown"
            by_hook[hook].append(clip)
        
        performance = []
        for hook_type, hook_clips in by_hook.items():
            total_views = sum(
                (c.youtube_views or 0) + (c.tiktok_views or 0) + (c.instagram_impressions or 0)
                for c in hook_clips
            )
            
            avg_views = total_views / len(hook_clips) if hook_clips else 0
            
            # Calculate engagement rates
            all_rates = []
            for c in hook_clips:
                rates = [
                    c.youtube_engagement_rate or 0,
                    c.tiktok_engagement_rate or 0,
                    c.instagram_engagement_rate or 0,
                ]
                all_rates.extend([r for r in rates if r > 0])
            
            avg_engagement = sum(all_rates) / len(all_rates) if all_rates else 0
            
            # Success rate
            viral_count = sum(1 for c in hook_clips if self._is_viral(c))
            success_rate = (viral_count / len(hook_clips) * 100) if hook_clips else 0
            
            performance.append(ContentTypePerformance(
                hook_type=hook_type,
                clip_count=len(hook_clips),
                avg_views=avg_views,
                avg_engagement_rate=avg_engagement,
                success_rate=success_rate,
            ))
        
        # Sort by success rate
        performance.sort(key=lambda x: x.success_rate, reverse=True)
        return performance
    
    def _get_time_series(
        self,
        clips: List[Any],
        days: int,
    ) -> List[TimeSeriesPoint]:
        """Generate time series data."""
        # Group by date
        by_date = defaultdict(list)
        for clip in clips:
            date_key = clip.created_at.strftime("%Y-%m-%d")
            by_date[date_key].append(clip)
        
        # Generate series for last N days
        series = []
        for i in range(days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            day_clips = by_date.get(date, [])
            
            total_views = sum(
                (c.youtube_views or 0) + (c.tiktok_views or 0) + (c.instagram_impressions or 0)
                for c in day_clips
            )
            
            virality_scores = [c.virality_score or 0 for c in day_clips]
            avg_virality = sum(virality_scores) / len(virality_scores) if virality_scores else 0
            
            series.append(TimeSeriesPoint(
                date=date,
                clips_published=len(day_clips),
                total_views=total_views,
                avg_virality_score=avg_virality,
            ))
        
        # Reverse to chronological order
        series.reverse()
        return series
    
    def _get_top_clips(
        self,
        clips: List[Any],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get top performing clips."""
        # Calculate total views for each clip
        clips_with_views = []
        for clip in clips:
            total_views = (
                (clip.youtube_views or 0) +
                (clip.tiktok_views or 0) +
                (clip.instagram_impressions or 0)
            )
            clips_with_views.append((clip, total_views))
        
        # Sort by views
        clips_with_views.sort(key=lambda x: x[1], reverse=True)
        
        top_clips = []
        for clip, views in clips_with_views[:limit]:
            top_clips.append({
                "clip_id": clip.id,
                "task_id": clip.task_id,
                "text": clip.text[:100] if clip.text else "",
                "total_views": views,
                "virality_score": clip.virality_score,
                "hook_type": clip.hook_type,
                "created_at": clip.created_at.isoformat(),
                "platforms": {
                    "youtube": bool(clip.youtube_video_id),
                    "tiktok": bool(clip.tiktok_video_id),
                    "instagram": bool(clip.instagram_media_id),
                },
            })
        
        return top_clips
    
    def _generate_insights(
        self,
        clips: List[Any],
        platform_stats: Dict[str, PlatformStats],
        content_performance: List[ContentTypePerformance],
    ) -> List[str]:
        """Generate AI insights from the data."""
        insights = []
        
        if not clips:
            return ["Start creating clips to see personalized insights!"]
        
        # Best platform insight
        if platform_stats:
            best_platform = max(platform_stats.items(), key=lambda x: x[1].total_views)
            insights.append(
                f"🚀 Your content performs best on {best_platform[0].title()}. "
                f"Consider prioritizing this platform."
            )
        
        # Hook type insight
        if content_performance:
            best_hook = content_performance[0]
            insights.append(
                f"💡 '{best_hook.hook_type}' hooks have {best_hook.success_rate:.0f}% viral success rate. "
                f"Use this style more often!"
            )
        
        # Posting frequency insight
        days_with_clips = len(set(c.created_at.date() for c in clips))
        if days_with_clips < 7:
            insights.append(
                "📅 You've been inactive recently. Consistent posting (daily) improves virality."
            )
        
        # Engagement insight
        avg_engagements = [p.avg_engagement_rate for p in platform_stats.values()]
        if avg_engagements and sum(avg_engagements) / len(avg_engagements) < 3:
            insights.append(
                "🎯 Your engagement rate is below average. Try adding more B-roll and faster cuts."
            )
        
        # Viral clip insight
        viral_clips = [c for c in clips if self._is_viral(c)]
        if viral_clips:
            insights.append(
                f"🔥 You have {len(viral_clips)} viral clips! Analyze what made them successful."
            )
        else:
            insights.append(
                "📈 No viral hits yet. Focus on trending topics and stronger hooks."
            )
        
        return insights
    
    def _empty_dashboard(self) -> Dict[str, Any]:
        """Return empty dashboard structure."""
        return {
            "summary": {
                "total_clips_generated": 0,
                "total_views_across_platforms": 0,
                "total_engagements": 0,
                "avg_virality_score": 0,
                "viral_clips_count": 0,
                "period_days": 0,
            },
            "platforms": {},
            "content_performance": [],
            "time_series": [],
            "top_performing_clips": [],
            "ai_insights": ["Start creating clips to see your analytics dashboard!"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    async def compare_periods(
        self,
        db: AsyncSession,
        user_id: str,
        current_days: int = 30,
        previous_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Compare current period vs previous period.
        
        Returns growth metrics and trends.
        """
        current = await self.get_user_dashboard(db, user_id, current_days)
        
        # Calculate previous period
        from ...models import GeneratedClip, Task
        
        end_prev = datetime.now(timezone.utc) - timedelta(days=current_days)
        start_prev = end_prev - timedelta(days=previous_days)
        
        result = await db.execute(
            select(GeneratedClip)
            .join(Task)
            .where(Task.user_id == user_id)
            .where(GeneratedClip.created_at >= start_prev)
            .where(GeneratedClip.created_at < end_prev)
        )
        prev_clips = result.scalars().all()
        
        prev_views = sum(
            (c.youtube_views or 0) + (c.tiktok_views or 0) + (c.instagram_impressions or 0)
            for c in prev_clips
        )
        
        current_views = current["summary"]["total_views_across_platforms"]
        
        growth_pct = ((current_views - prev_views) / prev_views * 100) if prev_views > 0 else 0
        
        return {
            "current_period": {
                "days": current_days,
                "clips": current["summary"]["total_clips_generated"],
                "views": current_views,
            },
            "previous_period": {
                "days": previous_days,
                "clips": len(prev_clips),
                "views": prev_views,
            },
            "growth_percentage": round(growth_pct, 1),
            "trend": "up" if growth_pct > 0 else "down" if growth_pct < 0 else "stable",
        }


__all__ = ["AnalyticsDashboardService", "PlatformStats", "ContentTypePerformance"]
