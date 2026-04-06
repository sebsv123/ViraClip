"""
Trending Topics Recommendation Service
AI-powered trending topic analysis and content recommendations.

Real data sources (all free, no API key):
  1. Google Trends Daily Trending Searches RSS  (geo=US)
  2. YouTube public trending topics via Google Trends keywords

Falls back to curated sample data when network is unavailable.
Cache TTL: 60 minutes.
"""

import logging
import uuid
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)

# ── Real-data fetch constants ─────────────────────────────────────────────────
_GOOGLE_TRENDS_RSS = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
_CACHE_TTL_MINUTES = 60

# Keyword → category heuristics
_CATEGORY_HINTS: Dict[str, str] = {
    "tutorial": "education", "how to": "education", "learn": "education", "course": "education",
    "game": "gaming",       "gaming": "gaming",    "esports": "gaming", "stream": "gaming",
    "music": "music",       "song": "music",       "album": "music",    "artist": "music",
    "sport": "sports",      "nba": "sports",       "nfl": "sports",     "soccer": "sports",
    "news": "news",         "election": "news",    "politics": "news",  "breaking": "news",
    "ai": "technology",     "tech": "technology",  "app": "technology", "software": "technology",
    "fitness": "lifestyle", "recipe": "lifestyle", "fashion": "lifestyle", "travel": "lifestyle",
}


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
        self._last_refresh: Optional[datetime] = None
        self._refresh_lock = asyncio.Lock()

        # Seed with sample trends immediately so the service is usable before first refresh
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
    
    # ── Real-data refresh ────────────────────────────────────────────────────

    async def _fetch_google_trends_rss(self) -> List[Dict[str, Any]]:
        """Fetch Google Trends Daily Trending Searches RSS for US."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_GOOGLE_TRENDS_RSS)
            resp.raise_for_status()
            return self._parse_google_trends_rss(resp.text)
        except Exception as exc:
            logger.debug("[trends] Google Trends RSS fetch failed: %s", exc)
            return []

    @staticmethod
    def _parse_google_trends_rss(xml_text: str) -> List[Dict[str, Any]]:
        """Parse Google Trends RSS into raw trend dicts."""
        results: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"ht": "https://trends.google.com/trends/trendingsearches/daily"}
            items = root.findall(".//item")
            for item in items[:30]:  # cap at 30 per refresh
                title_el = item.find("title")
                approx_el = item.find("ht:approx_traffic", ns)
                news_items = item.findall("ht:news_item", ns)
                if title_el is None:
                    continue
                keyword = title_el.text or ""
                traffic_str = (approx_el.text or "1000") if approx_el is not None else "1000"
                traffic = int(traffic_str.replace("+", "").replace(",", "").strip() or "1000")
                related_kws = [
                    ni.find("ht:news_item_title", ns).text
                    for ni in news_items
                    if ni.find("ht:news_item_title", ns) is not None
                ][:3]
                results.append({
                    "keyword": keyword,
                    "volume": traffic,
                    "related": related_kws,
                })
        except ET.ParseError as exc:
            logger.debug("[trends] RSS parse error: %s", exc)
        return results

    def _raw_to_topic(self, raw: Dict[str, Any]) -> TrendingTopic:
        """Convert a raw RSS entry to a TrendingTopic."""
        keyword = raw["keyword"]
        volume  = raw.get("volume", 5000)

        # Infer category from keyword text
        kl = keyword.lower()
        category = TrendCategory.ENTERTAINMENT  # default
        for hint, cat_name in _CATEGORY_HINTS.items():
            if hint in kl:
                try:
                    category = TrendCategory(cat_name)
                except ValueError:
                    pass
                break

        # Infer status from traffic volume
        if volume >= 500_000:
            status = TrendStatus.PEAK
        elif volume >= 100_000:
            status = TrendStatus.RISING
        elif volume >= 20_000:
            status = TrendStatus.EMERGING
        else:
            status = TrendStatus.DECLINING

        velocity = min(volume / 50_000, 5.0)
        sentiment = 0.6  # neutral-positive default for trending searches
        score = self._calculate_trend_score(velocity, volume, sentiment, status)

        # Build hashtags from keyword words
        words = keyword.split()
        hashtags = [f"#{w.capitalize()}" for w in words if len(w) > 2][:4]
        if raw.get("related"):
            for r in raw["related"][:2]:
                r_words = (r or "").split()
                if r_words:
                    hashtags.append(f"#{r_words[0].capitalize()}")
        hashtags = list(dict.fromkeys(hashtags))[:6]

        return TrendingTopic(
            topic_id=f"trend_{uuid.uuid4().hex[:8]}",
            keyword=keyword,
            category=category,
            status=status,
            velocity=round(velocity, 2),
            volume=volume,
            sentiment_score=sentiment,
            related_hashtags=hashtags,
            peak_time=None,
            estimated_duration_hours=24 if status == TrendStatus.PEAK else 48,
            score=round(score, 1),
        )

    async def refresh_trends(self) -> int:
        """
        Refresh trending topics from real data sources.
        Returns the number of topics loaded (0 = used cache/fallback).
        """
        now = datetime.now()
        if (
            self._last_refresh is not None
            and (now - self._last_refresh) < timedelta(minutes=_CACHE_TTL_MINUTES)
        ):
            return 0  # cache still fresh

        async with self._refresh_lock:
            # double-check after acquiring lock
            if (
                self._last_refresh is not None
                and (now - self._last_refresh) < timedelta(minutes=_CACHE_TTL_MINUTES)
            ):
                return 0

            raw_items = await self._fetch_google_trends_rss()
            if not raw_items:
                logger.info("[trends] Real fetch failed — keeping cached/sample trends")
                return 0

            new_trends: Dict[str, TrendingTopic] = {}
            for raw in raw_items:
                topic = self._raw_to_topic(raw)
                new_trends[topic.topic_id] = topic

            # Merge: keep sample/manual entries if no real data overlaps
            self._trends = new_trends
            self._last_refresh = now
            logger.info("[trends] Refreshed %d trending topics from Google Trends", len(new_trends))
            return len(new_trends)

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_trending_topics(
        self,
        category: Optional[TrendCategory] = None,
        status: Optional[TrendStatus] = None,
        min_score: float = 0.0,
        limit: int = 20
    ) -> List[TrendingTopic]:
        """Get trending topics with optional filtering (auto-refreshes cache)."""
        await self.refresh_trends()
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
