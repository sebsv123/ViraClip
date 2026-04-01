"""
Competitor Intelligence Service
Real-time competitor video and trend monitoring.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class CompetitorPlatform(Enum):
    """Platforms to monitor."""
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    ALL = "all"


@dataclass
class Competitor:
    """Competitor profile."""
    competitor_id: str
    name: str
    platforms: Dict[str, str]  # platform -> handle
    niche: str
    follower_count: Dict[str, int]
    added_at: str
    last_sync: str
    is_active: bool


@dataclass
class CompetitorVideo:
    """Competitor video metrics."""
    video_id: str
    competitor_id: str
    platform: str
    title: str
    url: str
    thumbnail: str
    published_at: str
    views: int
    likes: int
    comments: int
    shares: int
    engagement_rate: float
    virality_score: float
    duration: int
    tags: List[str]


@dataclass
class TrendInsight:
    """Trend analysis insight."""
    insight_id: str
    trend_type: str
    description: str
    confidence: float
    detected_at: str
    affected_competitors: List[str]
    example_videos: List[str]
    recommended_action: str


class CompetitorIntelligenceService:
    """
    Monitors competitors and analyzes viral trends in real-time.
    """
    
    def __init__(self):
        self._competitors: Dict[str, Competitor] = {}
        self._video_cache: Dict[str, CompetitorVideo] = {}
        self._insights: List[TrendInsight] = []
        self._monitoring_task: Optional[asyncio.Task] = None
        self._is_monitoring = False
    
    async def add_competitor(
        self,
        name: str,
        platform_handles: Dict[str, str],
        niche: str
    ) -> Competitor:
        """Add a competitor to monitor."""
        import uuid
        
        competitor_id = f"comp_{uuid.uuid4().hex[:8]}"
        
        # Fetch initial stats
        follower_counts = await self._fetch_follower_counts(platform_handles)
        
        competitor = Competitor(
            competitor_id=competitor_id,
            name=name,
            platforms=platform_handles,
            niche=niche,
            follower_count=follower_counts,
            added_at=datetime.now().isoformat(),
            last_sync=datetime.now().isoformat(),
            is_active=True
        )
        
        self._competitors[competitor_id] = competitor
        
        # Initial sync of recent videos
        await self._sync_competitor_videos(competitor_id)
        
        logger.info(f"Added competitor {name} for monitoring")
        return competitor
    
    async def _fetch_follower_counts(
        self,
        handles: Dict[str, str]
    ) -> Dict[str, int]:
        """Fetch follower counts for each platform."""
        # In production, would call platform APIs
        # Simulated data
        return {
            platform: 100000 + i * 50000
            for i, platform in enumerate(handles.keys())
        }
    
    async def _sync_competitor_videos(self, competitor_id: str) -> List[CompetitorVideo]:
        """Sync recent videos from competitor."""
        competitor = self._competitors.get(competitor_id)
        if not competitor:
            return []
        
        videos = []
        
        for platform, handle in competitor.platforms.items():
            platform_videos = await self._fetch_platform_videos(
                platform, handle, competitor_id
            )
            videos.extend(platform_videos)
        
        # Update cache
        for video in videos:
            self._video_cache[video.video_id] = video
        
        competitor.last_sync = datetime.now().isoformat()
        
        return videos
    
    async def _fetch_platform_videos(
        self,
        platform: str,
        handle: str,
        competitor_id: str
    ) -> List[CompetitorVideo]:
        """Fetch videos from a specific platform."""
        # In production, would call YouTube API, TikTok API, etc.
        # Simulated data
        import uuid
        
        videos = []
        for i in range(5):
            video_id = f"vid_{uuid.uuid4().hex[:8]}"
            views = 10000 + i * 50000
            
            video = CompetitorVideo(
                video_id=video_id,
                competitor_id=competitor_id,
                platform=platform,
                title=f"Viral Video {i+1} - {handle}",
                url=f"https://{platform}.com/video/{video_id}",
                thumbnail="",
                published_at=(datetime.now() - timedelta(days=i)).isoformat(),
                views=views,
                likes=int(views * 0.08),
                comments=int(views * 0.02),
                shares=int(views * 0.03),
                engagement_rate=8.5 + i,
                virality_score=75.0 + i * 5,
                duration=30 + i * 15,
                tags=["viral", "trending", platform]
            )
            videos.append(video)
        
        return videos
    
    async def start_monitoring(self, interval_minutes: int = 30):
        """Start continuous competitor monitoring."""
        if self._is_monitoring:
            return
        
        self._is_monitoring = True
        
        while self._is_monitoring:
            try:
                await self._monitoring_cycle()
                await asyncio.sleep(interval_minutes * 60)
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _monitoring_cycle(self):
        """Single monitoring cycle."""
        logger.info("Running competitor monitoring cycle")
        
        for competitor_id in self._competitors:
            # Sync new videos
            new_videos = await self._sync_competitor_videos(competitor_id)
            
            # Analyze for trends
            for video in new_videos:
                if video.virality_score > 80:
                    await self._analyze_viral_content(video)
        
        # Generate insights
        await self._generate_trend_insights()
    
    async def _analyze_viral_content(self, video: CompetitorVideo):
        """Analyze what makes content viral."""
        logger.info(
            f"Analyzing viral content: {video.title} "
            f"(Score: {video.virality_score:.1f})"
        )
    
    async def _generate_trend_insights(self):
        """Generate trend insights from competitor data."""
        # Analyze common patterns
        all_videos = list(self._video_cache.values())
        
        if len(all_videos) < 10:
            return
        
        # Find trending topics
        tag_counts = {}
        for video in all_videos:
            for tag in video.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        if top_tags:
            import uuid
            insight = TrendInsight(
                insight_id=str(uuid.uuid4()),
                trend_type="emerging_topic",
                description=f"Trending: {', '.join([t[0] for t in top_tags])}",
                confidence=0.75,
                detected_at=datetime.now().isoformat(),
                affected_competitors=list(self._competitors.keys()),
                example_videos=[v.video_id for v in all_videos[:3]],
                recommended_action="Create content around these trending topics"
            )
            self._insights.append(insight)
    
    def get_competitor_dashboard(self, user_id: str) -> Dict[str, Any]:
        """Get competitor intelligence dashboard."""
        competitors = [
            {
                "competitor_id": c.competitor_id,
                "name": c.name,
                "niche": c.niche,
                "platforms": c.platforms,
                "follower_count": c.follower_count,
                "last_sync": c.last_sync,
                "is_active": c.is_active
            }
            for c in self._competitors.values()
        ]
        
        # Get recent high-performing videos
        recent_viral = [
            {
                "video_id": v.video_id,
                "competitor_id": v.competitor_id,
                "platform": v.platform,
                "title": v.title,
                "url": v.url,
                "views": v.views,
                "engagement_rate": v.engagement_rate,
                "virality_score": v.virality_score,
                "published_at": v.published_at
            }
            for v in sorted(
                self._video_cache.values(),
                key=lambda x: x.virality_score,
                reverse=True
            )[:10]
        ]
        
        # Get insights
        insights = [
            {
                "insight_id": i.insight_id,
                "type": i.trend_type,
                "description": i.description,
                "confidence": i.confidence,
                "detected_at": i.detected_at,
                "action": i.recommended_action
            }
            for i in sorted(self._insights, key=lambda x: x.detected_at, reverse=True)[:5]
        ]
        
        return {
            "competitors": competitors,
            "competitor_count": len(competitors),
            "recent_viral_videos": recent_viral,
            "trend_insights": insights,
            "monitoring_active": self._is_monitoring
        }
    
    def get_competitor_performance(
        self,
        competitor_id: str,
        days: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Get performance metrics for a competitor."""
        if competitor_id not in self._competitors:
            return None
        
        competitor = self._competitors[competitor_id]
        
        # Filter videos by date
        cutoff = datetime.now() - timedelta(days=days)
        videos = [
            v for v in self._video_cache.values()
            if v.competitor_id == competitor_id
            and datetime.fromisoformat(v.published_at) > cutoff
        ]
        
        if not videos:
            return None
        
        total_views = sum(v.views for v in videos)
        avg_engagement = sum(v.engagement_rate for v in videos) / len(videos)
        avg_virality = sum(v.virality_score for v in videos) / len(videos)
        
        return {
            "competitor_id": competitor_id,
            "name": competitor.name,
            "period_days": days,
            "videos_published": len(videos),
            "total_views": total_views,
            "avg_engagement_rate": round(avg_engagement, 2),
            "avg_virality_score": round(avg_virality, 1),
            "best_performing_video": max(videos, key=lambda x: x.views).title,
            "platform_breakdown": self._get_platform_breakdown(videos)
        }
    
    def _get_platform_breakdown(
        self,
        videos: List[CompetitorVideo]
    ) -> Dict[str, Any]:
        """Get performance breakdown by platform."""
        by_platform = {}
        
        for video in videos:
            if video.platform not in by_platform:
                by_platform[video.platform] = {
                    "video_count": 0,
                    "total_views": 0,
                    "avg_engagement": []
                }
            
            by_platform[video.platform]["video_count"] += 1
            by_platform[video.platform]["total_views"] += video.views
            by_platform[video.platform]["avg_engagement"].append(video.engagement_rate)
        
        # Calculate averages
        for platform in by_platform:
            engagements = by_platform[platform]["avg_engagement"]
            by_platform[platform]["avg_engagement"] = round(
                sum(engagements) / len(engagements), 2
            ) if engagements else 0
        
        return by_platform
    
    async def stop_monitoring(self):
        """Stop competitor monitoring."""
        self._is_monitoring = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
    
    def compare_to_competitors(
        self,
        user_metrics: Dict[str, Any],
        competitor_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Compare user metrics to competitors."""
        if not competitor_ids:
            competitor_ids = list(self._competitors.keys())
        
        comparisons = []
        
        for comp_id in competitor_ids:
            comp_data = self.get_competitor_performance(comp_id, days=30)
            if comp_data:
                comparisons.append({
                    "competitor_name": comp_data["name"],
                    "their_avg_engagement": comp_data["avg_engagement_rate"],
                    "their_avg_virality": comp_data["avg_virality_score"],
                    "your_avg_engagement": user_metrics.get("avg_engagement", 0),
                    "your_avg_virality": user_metrics.get("avg_virality", 0),
                    "engagement_gap": comp_data["avg_engagement_rate"] - user_metrics.get("avg_engagement", 0),
                    "virality_gap": comp_data["avg_virality_score"] - user_metrics.get("avg_virality", 0)
                })
        
        return {
            "comparisons": comparisons,
            "average_market_engagement": sum(c["their_avg_engagement"] for c in comparisons) / len(comparisons) if comparisons else 0,
            "average_market_virality": sum(c["their_avg_virality"] for c in comparisons) / len(comparisons) if comparisons else 0,
            "recommendations": self._generate_comparison_recommendations(comparisons)
        }
    
    def _generate_comparison_recommendations(
        self,
        comparisons: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate recommendations based on competitor comparison."""
        recommendations = []
        
        if not comparisons:
            return recommendations
        
        avg_gap = sum(c["engagement_gap"] for c in comparisons) / len(comparisons)
        
        if avg_gap > 2:
            recommendations.append(
                "Competitors have significantly higher engagement. "
                "Consider analyzing their hook patterns and video structure."
            )
        
        if any(c["their_avg_virality"] > 80 for c in comparisons):
            recommendations.append(
                "Some competitors are consistently creating viral content (>80 score). "
                "Study their trending topics and timing strategies."
            )
        
        return recommendations


# Global instance
_competitor_service: Optional[CompetitorIntelligenceService] = None


def get_competitor_intelligence_service() -> CompetitorIntelligenceService:
    """Get global competitor intelligence service."""
    global _competitor_service
    if _competitor_service is None:
        _competitor_service = CompetitorIntelligenceService()
    return _competitor_service
