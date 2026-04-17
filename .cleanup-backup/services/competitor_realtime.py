"""
Real-time Competitor Analysis System
Monitors competitor content and trends for strategic insights.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class CompetitorPlatform(Enum):
    """Platforms to monitor."""
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


@dataclass
class CompetitorVideo:
    """Competitor video data."""
    video_id: str
    platform: CompetitorPlatform
    creator: str
    title: str
    views: int
    likes: int
    comments: int
    virality_signals: Dict[str, float]
    uploaded_at: str
    duration: int
    niche: str


@dataclass
class TrendInsight:
    """Trending content insight."""
    trend_id: str
    topic: str
    growth_rate: float  # Percentage growth
    peak_time: str
    related_hashtags: List[str]
    top_creators: List[str]
    content_examples: List[str]


class CompetitorRealtimeService:
    """
    Real-time competitor monitoring and trend analysis.
    """
    
    def __init__(self):
        self._monitored_creators: Dict[str, Dict[str, Any]] = {}
        self._tracked_trends: Dict[str, TrendInsight] = {}
        self._competitor_videos: List[CompetitorVideo] = []
        self._alerts: List[Dict[str, Any]] = []
    
    async def add_competitor(
        self,
        creator_handle: str,
        platform: CompetitorPlatform,
        niches: List[str]
    ) -> bool:
        """Add a competitor to monitor."""
        key = f"{platform.value}:{creator_handle}"
        
        self._monitored_creators[key] = {
            "handle": creator_handle,
            "platform": platform.value,
            "niches": niches,
            "added_at": datetime.now().isoformat(),
            "last_check": None,
            "video_count": 0
        }
        
        logger.info(f"Added competitor: {creator_handle} on {platform.value}")
        return True
    
    async def analyze_trending_content(
        self,
        niche: str,
        hours: int = 24
    ) -> List[TrendInsight]:
        """Analyze trending content in a niche."""
        # This would integrate with platform APIs
        # For now, return simulated insights
        
        insights = []
        
        # Find videos in niche from last N hours
        recent_videos = [
            v for v in self._competitor_videos
            if v.niche == niche
            and datetime.fromisoformat(v.uploaded_at) > datetime.now() - timedelta(hours=hours)
        ]
        
        if not recent_videos:
            return insights
        
        # Group by topic/hashtag patterns
        topic_groups = {}
        for video in recent_videos:
            # Extract key topics from title
            topics = self._extract_topics(video.title)
            
            for topic in topics:
                if topic not in topic_groups:
                    topic_groups[topic] = []
                topic_groups[topic].append(video)
        
        # Calculate trends
        for topic, videos in topic_groups.items():
            if len(videos) < 3:  # Need minimum data
                continue
            
            # Calculate growth metrics
            avg_views = sum(v.views for v in videos) / len(videos)
            avg_engagement = sum(v.likes + v.comments for v in videos) / len(videos)
            
            # Estimate growth rate
            growth_rate = self._calculate_growth_rate(videos)
            
            insight = TrendInsight(
                trend_id=f"trend_{topic}_{datetime.now().strftime('%Y%m%d')}",
                topic=topic,
                growth_rate=growth_rate,
                peak_time=self._estimate_peak_time(videos),
                related_hashtags=self._extract_hashtags([v.title for v in videos]),
                top_creators=list(set(v.creator for v in videos))[:5],
                content_examples=[v.title for v in videos[:3]]
            )
            
            insights.append(insight)
            self._tracked_trends[insight.trend_id] = insight
        
        # Sort by growth rate
        insights.sort(key=lambda x: x.growth_rate, reverse=True)
        
        return insights[:10]  # Top 10 trends
    
    def _extract_topics(self, title: str) -> List[str]:
        """Extract key topics from video title."""
        # Simple extraction - in production would use NLP
        words = title.lower().split()
        
        # Filter out common words
        stop_words = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "is", "are"}
        keywords = [w for w in words if w not in stop_words and len(w) > 3]
        
        return list(set(keywords))[:5]  # Top 5 unique keywords
    
    def _calculate_growth_rate(self, videos: List[CompetitorVideo]) -> float:
        """Calculate view growth rate for a set of videos."""
        if len(videos) < 2:
            return 0.0
        
        # Sort by upload time
        sorted_videos = sorted(videos, key=lambda x: x.uploaded_at)
        
        # Calculate rate of change
        first_batch = sorted_videos[:len(sorted_videos)//2]
        second_batch = sorted_videos[len(sorted_videos)//2:]
        
        avg_first = sum(v.views for v in first_batch) / len(first_batch)
        avg_second = sum(v.views for v in second_batch) / len(second_batch)
        
        if avg_first == 0:
            return 100.0  # New trend
        
        return ((avg_second - avg_first) / avg_first) * 100
    
    def _estimate_peak_time(self, videos: List[CompetitorVideo]) -> str:
        """Estimate peak engagement time for a trend."""
        # Extract upload times and find most common hour
        hours = [datetime.fromisoformat(v.uploaded_at).hour for v in videos]
        
        if not hours:
            return "18:00"  # Default evening
        
        # Find most common hour
        from collections import Counter
        peak_hour = Counter(hours).most_common(1)[0][0]
        
        return f"{peak_hour:02d}:00"
    
    def _extract_hashtags(self, texts: List[str]) -> List[str]:
        """Extract hashtags from texts."""
        hashtags = []
        for text in texts:
            words = text.split()
            for word in words:
                if word.startswith('#'):
                    hashtags.append(word.lower())
        
        # Return top hashtags
        from collections import Counter
        return [tag for tag, _ in Counter(hashtags).most_common(5)]
    
    async def get_competitive_position(
        self,
        user_niche: str,
        user_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get competitive positioning analysis."""
        # Get competitor data for same niche
        niche_competitors = [
            v for v in self._competitor_videos
            if v.niche == user_niche
        ]
        
        if not niche_competitors:
            return {"error": "No competitor data for niche"}
        
        # Calculate averages
        avg_views = sum(v.views for v in niche_competitors) / len(niche_competitors)
        avg_engagement = sum(v.likes + v.comments for v in niche_competitors) / len(niche_competitors)
        avg_duration = sum(v.duration for v in niche_competitors) / len(niche_competitors)
        
        # Compare user metrics
        user_views = user_metrics.get("avg_views", 0)
        user_engagement = user_metrics.get("avg_engagement", 0)
        
        position = {
            "niche": user_niche,
            "market_average": {
                "views": int(avg_views),
                "engagement": int(avg_engagement),
                "duration": int(avg_duration)
            },
            "user_performance": {
                "views": user_views,
                "engagement": user_engagement
            },
            "comparison": {
                "views_percentile": (user_views / avg_views) * 100 if avg_views > 0 else 0,
                "engagement_percentile": (user_engagement / avg_engagement) * 100 if avg_engagement > 0 else 0
            },
            "top_performers": self._get_top_performers(niche_competitors, 5),
            "gaps": self._identify_gaps(user_metrics, avg_views, avg_engagement)
        }
        
        return position
    
    def _get_top_performers(
        self,
        videos: List[CompetitorVideo],
        limit: int
    ) -> List[Dict[str, Any]]:
        """Get top performing creators."""
        # Group by creator and calculate average performance
        creator_stats = {}
        
        for video in videos:
            if video.creator not in creator_stats:
                creator_stats[video.creator] = {"views": [], "engagement": []}
            
            creator_stats[video.creator]["views"].append(video.views)
            creator_stats[video.creator]["engagement"].append(video.likes + video.comments)
        
        # Calculate averages
        performers = []
        for creator, stats in creator_stats.items():
            avg_views = sum(stats["views"]) / len(stats["views"])
            avg_engagement = sum(stats["engagement"]) / len(stats["engagement"])
            
            performers.append({
                "creator": creator,
                "avg_views": int(avg_views),
                "avg_engagement": int(avg_engagement),
                "score": avg_views * 0.7 + avg_engagement * 0.3
            })
        
        # Sort by score
        performers.sort(key=lambda x: x["score"], reverse=True)
        
        return performers[:limit]
    
    def _identify_gaps(
        self,
        user_metrics: Dict[str, Any],
        market_avg_views: float,
        market_avg_engagement: float
    ) -> List[str]:
        """Identify competitive gaps for improvement."""
        gaps = []
        
        user_views = user_metrics.get("avg_views", 0)
        user_engagement = user_metrics.get("avg_engagement", 0)
        
        if user_views < market_avg_views * 0.8:
            gaps.append("views_below_market")
        
        if user_engagement < market_avg_engagement * 0.8:
            gaps.append("engagement_below_market")
        
        if not gaps:
            gaps.append("maintain_lead")
        
        return gaps
    
    async def generate_opportunity_alert(self) -> Optional[Dict[str, Any]]:
        """Generate alert for emerging opportunities."""
        # Check for new trends with low competition
        opportunities = []
        
        for trend in self._tracked_trends.values():
            # High growth + few creators = opportunity
            if trend.growth_rate > 50 and len(trend.top_creators) < 5:
                opportunities.append({
                    "type": "emerging_trend",
                    "topic": trend.topic,
                    "growth_rate": trend.growth_rate,
                    "competition_level": "low",
                    "recommended_action": "create_content",
                    "best_posting_time": trend.peak_time
                })
        
        return opportunities[0] if opportunities else None
    
    def get_monitoring_summary(self) -> Dict[str, Any]:
        """Get summary of competitor monitoring."""
        return {
            "monitored_creators": len(self._monitored_creators),
            "tracked_trends": len(self._tracked_trends),
            "videos_analyzed": len(self._competitor_videos),
            "active_alerts": len(self._alerts),
            "last_update": datetime.now().isoformat()
        }


# Global instance
_competitor_service: Optional[CompetitorRealtimeService] = None


def get_competitor_service() -> CompetitorRealtimeService:
    """Get global competitor service."""
    global _competitor_service
    if _competitor_service is None:
        _competitor_service = CompetitorRealtimeService()
    return _competitor_service


# Convenience functions
async def analyze_niche_trends(niche: str) -> List[TrendInsight]:
    """Analyze trends in a niche."""
    return await get_competitor_service().analyze_trending_content(niche)


async def get_market_position(niche: str, user_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Get competitive position analysis."""
    return await get_competitor_service().get_competitive_position(niche, user_metrics)
