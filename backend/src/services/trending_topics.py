"""
Trending Topics Recommendation Service
AI-powered trending topic analysis and content recommendations.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class TrendCategory(Enum):
    """Categories of trends."""
    ENTERTAINMENT = "entertainment"
    EDUCATION = "education"
    TECHNOLOGY = "technology"
    LIFESTYLE = "lifestyle"
    NEWS = "news"
    SPORTS = "sports"
    GAMING = "gaming"
    MUSIC = "music"


class TrendStatus(Enum):
    """Trend lifecycle status."""
    EMERGING = "emerging"
    RISING = "rising"
    PEAK = "peak"
    DECLINING = "declining"


@dataclass
class TrendingTopic:
    """Trending topic data."""
    topic_id: str
    keyword: str
    category: TrendCategory
    status: TrendStatus
    velocity: float  # Growth rate
    volume: int  # Mentions/posts
    sentiment_score: float  # -1 to 1
    related_hashtags: List[str]
    peak_time: Optional[str]
    estimated_duration_hours: int
    score: float  # Overall trend score


@dataclass
class ContentRecommendation:
    """Content recommendation based on trends."""
    recommendation_id: str
    topic: TrendingTopic
    content_type: str
    suggested_hook: str
    suggested_duration: int
    suggested_hashtags: List[str]
    confidence: float
    created_at: str


class TrendingTopicsService:
    """
    AI-powered trending topic analysis and recommendations.
    """
    
    def __init__(self):
        self._trends: Dict[str, TrendingTopic] = {}
        self._historical_data: List[Dict[str, Any]] = []
        self._user_niches: Dict[str, List[str]] = {}
        
        # Initialize with sample trending topics
        self._initialize_sample_trends()
    
    def _initialize_sample_trends(self):
        """Initialize sample trending data."""
        sample_trends = [
            {
                "keyword": "AI tutorial",
                "category": TrendCategory.TECHNOLOGY,
                "status": TrendStatus.RISING,
                "velocity": 2.5,
                "volume": 50000,
                "sentiment": 0.8,
                "hashtags": ["#AI", "#MachineLearning", "#Tutorial"]
            },
            {
                "keyword": "morning routine",
                "category": TrendCategory.LIFESTYLE,
                "status": TrendStatus.PEAK,
                "velocity": 1.8,
                "volume": 120000,
                "sentiment": 0.9,
                "hashtags": ["#MorningRoutine", "#Productivity", "#SelfCare"]
            },
            {
                "keyword": "quick recipes",
                "category": TrendCategory.LIFESTYLE,
                "status": TrendStatus.EMERGING,
                "velocity": 3.2,
                "volume": 35000,
                "sentiment": 0.7,
                "hashtags": ["#QuickRecipes", "#FoodTok", "#Cooking"]
            },
            {
                "keyword": "gaming highlights",
                "category": TrendCategory.GAMING,
                "status": TrendStatus.RISING,
                "velocity": 2.1,
                "volume": 80000,
                "sentiment": 0.6,
                "hashtags": ["#Gaming", "#Highlights", "#Gameplay"]
            },
            {
                "keyword": "study tips",
                "category": TrendCategory.EDUCATION,
                "status": TrendStatus.PEAK,
                "velocity": 1.5,
                "volume": 95000,
                "sentiment": 0.85,
                "hashtags": ["#StudyTips", "#Education", "#Learning"]
            }
        ]
        
        import uuid
        for trend_data in sample_trends:
            topic_id = f"trend_{uuid.uuid4().hex[:8]}"
            
            # Calculate trend score
            score = self._calculate_trend_score(
                velocity=trend_data["velocity"],
                volume=trend_data["volume"],
                sentiment=trend_data["sentiment"],
                status=trend_data["status"]
            )
            
            trend = TrendingTopic(
                topic_id=topic_id,
                keyword=trend_data["keyword"],
                category=trend_data["category"],
                status=trend_data["status"],
                velocity=trend_data["velocity"],
                volume=trend_data["volume"],
                sentiment_score=trend_data["sentiment"],
                related_hashtags=trend_data["hashtags"],
                peak_time=None,
                estimated_duration_hours=48,
                score=score
            )
            
            self._trends[topic_id] = trend
    
    def _calculate_trend_score(
        self,
        velocity: float,
        volume: int,
        sentiment: float,
        status: TrendStatus
    ) -> float:
        """Calculate overall trend score."""
        # Normalize components
        velocity_norm = min(velocity / 5.0, 1.0)  # Cap at 5x growth
        volume_norm = min(volume / 200000, 1.0)  # Cap at 200k mentions
        sentiment_norm = (sentiment + 1) / 2  # Convert -1..1 to 0..1
        
        # Status multiplier
        status_mult = {
            TrendStatus.EMERGING: 1.3,
            TrendStatus.RISING: 1.2,
            TrendStatus.PEAK: 1.0,
            TrendStatus.DECLINING: 0.7
        }.get(status, 1.0)
        
        # Weighted calculation
        score = (
            velocity_norm * 0.35 +
            volume_norm * 0.30 +
            sentiment_norm * 0.20
        ) * status_mult * 100
        
        return min(score, 100.0)
    
    async def get_trending_topics(
        self,
        category: Optional[TrendCategory] = None,
        status: Optional[TrendStatus] = None,
        min_score: float = 0.0,
        limit: int = 20
    ) -> List[TrendingTopic]:
        """Get trending topics with optional filtering."""
        trends = list(self._trends.values())
        
        # Apply filters
        if category:
            trends = [t for t in trends if t.category == category]
        
        if status:
            trends = [t for t in trends if t.status == status]
        
        trends = [t for t in trends if t.score >= min_score]
        
        # Sort by score descending
        trends.sort(key=lambda x: x.score, reverse=True)
        
        return trends[:limit]
    
    async def get_personalized_recommendations(
        self,
        user_id: str,
        user_niche: str,
        content_history: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[ContentRecommendation]:
        """Get personalized trend-based content recommendations."""
        import uuid
        
        # Get relevant trends for user's niche
        niche_categories = self._get_categories_for_niche(user_niche)
        
        relevant_trends = [
            t for t in self._trends.values()
            if t.category in niche_categories
            and t.status in [TrendStatus.EMERGING, TrendStatus.RISING, TrendStatus.PEAK]
        ]
        
        # Sort by relevance and score
        relevant_trends.sort(key=lambda x: x.score, reverse=True)
        
        # Generate recommendations
        recommendations = []
        
        for trend in relevant_trends[:limit]:
            rec = self._generate_recommendation_from_trend(trend)
            recommendations.append(rec)
        
        return recommendations
    
    def _get_categories_for_niche(self, niche: str) -> List[TrendCategory]:
        """Map niche to trend categories."""
        niche_map = {
            "tech": [TrendCategory.TECHNOLOGY, TrendCategory.EDUCATION],
            "education": [TrendCategory.EDUCATION, TrendCategory.LIFESTYLE],
            "entertainment": [TrendCategory.ENTERTAINMENT, TrendCategory.MUSIC],
            "gaming": [TrendCategory.GAMING, TrendCategory.ENTERTAINMENT],
            "lifestyle": [TrendCategory.LIFESTYLE, TrendCategory.ENTERTAINMENT],
            "news": [TrendCategory.NEWS, TrendCategory.TECHNOLOGY],
            "sports": [TrendCategory.SPORTS, TrendCategory.ENTERTAINMENT]
        }
        
        return niche_map.get(niche.lower(), list(TrendCategory))
    
    def _generate_recommendation_from_trend(
        self,
        trend: TrendingTopic
    ) -> ContentRecommendation:
        """Generate content recommendation from trend."""
        import uuid
        
        # Generate hook based on trend
        hooks = {
            TrendCategory.TECHNOLOGY: f"This {trend.keyword} will change everything...",
            TrendCategory.EDUCATION: f"Learn {trend.keyword} in 60 seconds!",
            TrendCategory.LIFESTYLE: f"The ultimate {trend.keyword} you need to try",
            TrendCategory.ENTERTAINMENT: f"You won't believe this {trend.keyword}",
            TrendCategory.GAMING: f"Insane {trend.keyword} that broke the internet"
        }
        
        suggested_hook = hooks.get(
            trend.category,
            f"Trending now: {trend.keyword}"
        )
        
        # Suggest duration based on category
        duration_map = {
            TrendCategory.EDUCATION: 60,
            TrendCategory.TECHNOLOGY: 45,
            TrendCategory.LIFESTYLE: 30,
            TrendCategory.ENTERTAINMENT: 15,
            TrendCategory.GAMING: 30
        }
        
        return ContentRecommendation(
            recommendation_id=str(uuid.uuid4()),
            topic=trend,
            content_type="short_form",
            suggested_hook=suggested_hook,
            suggested_duration=duration_map.get(trend.category, 30),
            suggested_hashtags=trend.related_hashtags[:5],
            confidence=min(trend.score / 100, 0.95),
            created_at=datetime.now().isoformat()
        )
    
    async def analyze_content_for_trends(
        self,
        transcript: str,
        title: str,
        hashtags: List[str]
    ) -> Dict[str, Any]:
        """Analyze content for trending topic alignment."""
        text = f"{title} {transcript} {' '.join(hashtags)}"
        text_lower = text.lower()
        
        matching_trends = []
        
        for trend in self._trends.values():
            # Check if trend keyword appears in content
            if trend.keyword.lower() in text_lower:
                matching_trends.append({
                    "topic_id": trend.topic_id,
                    "keyword": trend.keyword,
                    "category": trend.category.value,
                    "score": trend.score,
                    "status": trend.status.value,
                    "relevance": "high" if trend.keyword.lower() in title.lower() else "medium"
                })
        
        # Calculate trend alignment score
        if matching_trends:
            avg_trend_score = sum(t["score"] for t in matching_trends) / len(matching_trends)
            alignment_score = min(avg_trend_score * 1.2, 100)  # Bonus for trend alignment
        else:
            alignment_score = 50  # Neutral score
        
        return {
            "alignment_score": alignment_score,
            "matching_trends": matching_trends,
            "trending_potential": "high" if alignment_score > 75 else "medium" if alignment_score > 50 else "low",
            "suggestions": self._generate_trend_suggestions(matching_trends)
        }
    
    def _generate_trend_suggestions(
        self,
        matching_trends: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate suggestions for better trend alignment."""
        suggestions = []
        
        if not matching_trends:
            suggestions.append("Consider adding trending hashtags to increase visibility")
            suggestions.append("Check current trends in your niche for content ideas")
        else:
            top_trend = matching_trends[0]
            suggestions.append(f"Your content aligns well with '{top_trend['keyword']}' trend")
            
            if top_trend["status"] == "emerging":
                suggestions.append("Great timing! This trend is still emerging - post soon!")
            elif top_trend["status"] == "peak":
                suggestions.append("This trend is at peak - high competition but high reward")
        
        return suggestions
    
    async def predict_trend_lifecycle(
        self,
        topic_id: str
    ) -> Dict[str, Any]:
        """Predict trend lifecycle and best posting times."""
        if topic_id not in self._trends:
            return {"error": "Topic not found"}
        
        trend = self._trends[topic_id]
        
        # Predict peak time
        if trend.status == TrendStatus.EMERGING:
            predicted_peak = datetime.now() + timedelta(hours=24)
            time_to_peak = "24 hours"
        elif trend.status == TrendStatus.RISING:
            predicted_peak = datetime.now() + timedelta(hours=12)
            time_to_peak = "12 hours"
        else:
            predicted_peak = datetime.now()
            time_to_peak = "Now"
        
        return {
            "topic": trend.keyword,
            "current_status": trend.status.value,
            "predicted_peak": predicted_peak.isoformat(),
            "time_to_peak": time_to_peak,
            "estimated_duration_remaining": trend.estimated_duration_hours,
            "recommendation": "Post now" if trend.status in [TrendStatus.EMERGING, TrendStatus.RISING] else "Consider next trend"
        }
    
    def get_trend_analytics(self) -> Dict[str, Any]:
        """Get comprehensive trend analytics."""
        total_trends = len(self._trends)
        
        by_category = {}
        for trend in self._trends.values():
            cat = trend.category.value
            if cat not in by_category:
                by_category[cat] = {"count": 0, "avg_score": 0, "total_volume": 0}
            by_category[cat]["count"] += 1
            by_category[cat]["avg_score"] += trend.score
            by_category[cat]["total_volume"] += trend.volume
        
        # Calculate averages
        for cat in by_category:
            by_category[cat]["avg_score"] /= by_category[cat]["count"]
        
        by_status = {}
        for trend in self._trends.values():
            status = trend.status.value
            by_status[status] = by_status.get(status, 0) + 1
        
        return {
            "total_trends": total_trends,
            "by_category": by_category,
            "by_status": by_status,
            "top_trends": [
                {
                    "keyword": t.keyword,
                    "score": t.score,
                    "status": t.status.value
                }
                for t in sorted(self._trends.values(), key=lambda x: x.score, reverse=True)[:10]
            ],
            "last_updated": datetime.now().isoformat()
        }


# Global instance
_trends_service: Optional[TrendingTopicsService] = None


def get_trending_topics_service() -> TrendingTopicsService:
    """Get global trending topics service."""
    global _trends_service
    if _trends_service is None:
        _trends_service = TrendingTopicsService()
    return _trends_service
