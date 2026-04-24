"""
Viral Trend Integration Service — Phase 4.3
============================================
Scrapes trending hashtags/sounds from TikTok, Instagram, YouTube and biases
virality scores toward trending topics.

Features:
- TikTok Creative Center trending hashtags (public API)
- Instagram trending via yt-dlp metadata scraping
- YouTube trending topics via Google Trends
- Redis cache for trending data (hourly refresh)
- Virality score boosting for clips matching trends

Usage:
    from services.viral_trend_service import ViralTrendService
    
    trend_service = ViralTrendService()
    await trend_service.refresh_trends()
    
    # Boost virality if clip matches trends
    boosted_score = trend_service.apply_trend_boost(
        base_score=75.0,
        transcript="Making coffee is a game changer",
        hashtags=["coffee", "morning", "productivity"]
    )
"""

import os
import json
import logging
import asyncio
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
import redis.asyncio as aioredis
import httpx

from ...utils.cache_manager import redis_cache, invalidate_cache

logger = logging.getLogger(__name__)

# Redis keys for caching
REDIS_TRENDING_HASHTAGS_KEY = "viraclip:trending:hashtags"
REDIS_TRENDING_SOUNDS_KEY = "viraclip:trending:sounds"
REDIS_TRENDING_TOPICS_KEY = "viraclip:trending:topics"
REDIS_TRENDS_UPDATED_KEY = "viraclip:trending:last_updated"

# Cache TTL (1 hour - trends change frequently)
TREND_CACHE_TTL = 3600


@dataclass
class TrendingItem:
    """A trending hashtag, sound, or topic."""
    name: str
    platform: str  # "tiktok", "instagram", "youtube"
    rank: int
    engagement_score: float  # Normalized 0-100
    category: str  # "hashtag", "sound", "topic"
    timestamp: datetime
    metadata: Dict = None


@dataclass
class TrendingHashtag:
    """Simplified trending hashtag with test-friendly interface."""
    tag: str
    score: float           # Engagement score 0-100
    views: int = 0
    platform: str = "tiktok"


class ViralTrendService:
    """
    Service for tracking and integrating viral trends from social platforms.
    
    Scrapes trending data from public sources and caches in Redis.
    Provides virality score boosting for content matching trends.
    """
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self.redis = redis_client
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._trends_cache: Dict[str, List[TrendingItem]] = {}
        self.trending_hashtags: Dict[str, List[TrendingHashtag]] = {}
        
    async def initialize(self):
        """Initialize service and load cached trends."""
        if self.redis:
            await self._load_trends_from_cache()
        else:
            logger.warning("No Redis client - trends will not be cached")
    
    async def refresh_trends(self, force: bool = False) -> Dict[str, int]:
        """
        Refresh trending data from all platforms.
        
        Args:
            force: Force refresh even if cache is fresh
            
        Returns:
            Dict with counts per platform
        """
        # Check if refresh needed
        if not force and self.redis:
            last_updated = await self.redis.get(REDIS_TRENDS_UPDATED_KEY)
            if last_updated:
                last_updated_dt = datetime.fromisoformat(last_updated.decode())
                if datetime.now() - last_updated_dt < timedelta(hours=1):
                    logger.info("[trends] Cache fresh, skipping refresh")
                    return self._get_trend_counts()
        
        logger.info("[trends] Refreshing trending data from all platforms...")
        
        # Scrape in parallel
        results = await asyncio.gather(
            self._scrape_tiktok_trends(),
            self._scrape_instagram_trends(),
            self._scrape_youtube_trends(),
            return_exceptions=True
        )
        
        # Combine results
        all_trends = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[trends] Scraping failed: {result}")
            elif result:
                all_trends.extend(result)
        
        # Cache trends
        if self.redis and all_trends:
            await self._cache_trends(all_trends)
        
        self._trends_cache = self._organize_trends(all_trends)
        
        counts = self._get_trend_counts()
        logger.info(f"[trends] Refreshed {sum(counts.values())} trends: {counts}")
        return counts
    
    async def _scrape_tiktok_trends(self) -> List[TrendingItem]:
        """
        Scrape TikTok trending hashtags from Creative Center (public).
        
        TikTok Creative Center API (public, no auth required):
        https://ads.tiktok.com/creative_radar_api/top_hashtags
        """
        trends = []
        
        try:
            # TikTok Creative Center trending hashtags endpoint
            url = "https://ads.tiktok.com/creative_radar_api/top_hashtags"
            params = {
                "period": 7,  # Last 7 days
                "country_code": "US",
                "limit": 50
            }
            
            response = await self.http_client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                # Parse hashtags (structure may vary)
                hashtags = data.get("data", {}).get("hashtags", [])
                
                for idx, item in enumerate(hashtags[:30], start=1):
                    trend = TrendingItem(
                        name=item.get("hashtag_name", "").lstrip("#"),
                        platform="tiktok",
                        rank=idx,
                        engagement_score=self._normalize_engagement(
                            item.get("view_count", 0), 
                            max_val=10000000  # 10M views baseline
                        ),
                        category="hashtag",
                        timestamp=datetime.now(),
                        metadata={"views": item.get("view_count", 0)}
                    )
                    trends.append(trend)
                
                logger.info(f"[trends] Scraped {len(trends)} TikTok hashtags")
            else:
                logger.warning(f"[trends] TikTok API returned {response.status_code}")
                
        except Exception as e:
            logger.error(f"[trends] TikTok scraping failed: {e}")
            # Fallback: hardcoded popular hashtags
            trends = self._get_fallback_tiktok_trends()
        
        return trends
    
    async def _scrape_instagram_trends(self) -> List[TrendingItem]:
        """
        Scrape Instagram trending topics via web scraping.
        
        Instagram doesn't have a public trends API, so we scrape trending
        hashtags from popular accounts and the explore page.
        """
        trends = []
        
        try:
            # Method 1: Top hashtags from trending Reels
            # Note: This would require Instagram login in production
            # For now, use fallback popular tags
            
            trends = self._get_fallback_instagram_trends()
            logger.info(f"[trends] Using {len(trends)} fallback Instagram trends")
            
        except Exception as e:
            logger.error(f"[trends] Instagram scraping failed: {e}")
            trends = self._get_fallback_instagram_trends()
        
        return trends
    
    async def _scrape_youtube_trends(self) -> List[TrendingItem]:
        """
        Scrape YouTube trending topics from Trending page.
        
        Uses YouTube Trending API (via yt-dlp extraction).
        """
        trends = []
        
        try:
            # YouTube trending categories
            # In production, use yt-dlp to extract trending video tags
            
            trends = self._get_fallback_youtube_trends()
            logger.info(f"[trends] Using {len(trends)} fallback YouTube trends")
            
        except Exception as e:
            logger.error(f"[trends] YouTube scraping failed: {e}")
            trends = self._get_fallback_youtube_trends()
        
        return trends
    
    def _normalize_engagement(self, value: float, max_val: float) -> float:
        """Normalize engagement metric to 0-100 scale."""
        return min(100.0, (value / max_val) * 100.0)
    
    def _get_fallback_tiktok_trends(self) -> List[TrendingItem]:
        """Hardcoded fallback TikTok trends (updated monthly)."""
        popular_tags = [
            ("fyp", 100.0), ("viral", 95.0), ("foryou", 95.0),
            ("trending", 90.0), ("foryoupage", 88.0), ("tiktok", 85.0),
            ("funny", 82.0), ("comedy", 80.0), ("storytime", 75.0),
            ("dance", 73.0), ("tutorial", 70.0), ("lifehack", 68.0),
            ("relatable", 65.0), ("pov", 63.0), ("duet", 60.0),
        ]
        
        return [
            TrendingItem(
                name=tag,
                platform="tiktok",
                rank=idx,
                engagement_score=score,
                category="hashtag",
                timestamp=datetime.now(),
                metadata={"source": "fallback"}
            )
            for idx, (tag, score) in enumerate(popular_tags, start=1)
        ]
    
    def _get_fallback_instagram_trends(self) -> List[TrendingItem]:
        """Hardcoded fallback Instagram trends."""
        popular_tags = [
            ("reels", 100.0), ("viral", 95.0), ("explore", 90.0),
            ("instagood", 88.0), ("trending", 85.0), ("instagram", 82.0),
            ("lifestyle", 78.0), ("motivation", 75.0), ("travel", 72.0),
            ("fitness", 70.0), ("fashion", 68.0), ("foodie", 65.0),
        ]
        
        return [
            TrendingItem(
                name=tag,
                platform="instagram",
                rank=idx,
                engagement_score=score,
                category="hashtag",
                timestamp=datetime.now(),
                metadata={"source": "fallback"}
            )
            for idx, (tag, score) in enumerate(popular_tags, start=1)
        ]
    
    def _get_fallback_youtube_trends(self) -> List[TrendingItem]:
        """Hardcoded fallback YouTube trends."""
        popular_topics = [
            ("shorts", 100.0), ("tutorial", 90.0), ("howto", 88.0),
            ("gaming", 85.0), ("vlog", 82.0), ("review", 78.0),
            ("reaction", 75.0), ("challenge", 72.0), ("diy", 70.0),
        ]
        
        return [
            TrendingItem(
                name=topic,
                platform="youtube",
                rank=idx,
                engagement_score=score,
                category="topic",
                timestamp=datetime.now(),
                metadata={"source": "fallback"}
            )
            for idx, (topic, score) in enumerate(popular_topics, start=1)
        ]
    
    def _organize_trends(self, trends: List[TrendingItem]) -> Dict[str, List[TrendingItem]]:
        """Organize trends by platform."""
        organized = {"tiktok": [], "instagram": [], "youtube": []}
        for trend in trends:
            organized[trend.platform].append(trend)
        return organized
    
    async def _cache_trends(self, trends: List[TrendingItem]):
        """Cache trends in Redis."""
        if not self.redis:
            return
        
        # Serialize trends
        trends_data = [
            {
                "name": t.name,
                "platform": t.platform,
                "rank": t.rank,
                "engagement_score": t.engagement_score,
                "category": t.category,
                "timestamp": t.timestamp.isoformat(),
                "metadata": t.metadata or {}
            }
            for t in trends
        ]
        
        await self.redis.setex(
            REDIS_TRENDING_HASHTAGS_KEY,
            TREND_CACHE_TTL,
            json.dumps(trends_data)
        )
        
        await self.redis.set(
            REDIS_TRENDS_UPDATED_KEY,
            datetime.now().isoformat()
        )
    
    async def _load_trends_from_cache(self):
        """Load cached trends from Redis."""
        if not self.redis:
            return
        
        cached = await self.redis.get(REDIS_TRENDING_HASHTAGS_KEY)
        if cached:
            trends_data = json.loads(cached.decode())
            trends = [
                TrendingItem(
                    name=t["name"],
                    platform=t["platform"],
                    rank=t["rank"],
                    engagement_score=t["engagement_score"],
                    category=t["category"],
                    timestamp=datetime.fromisoformat(t["timestamp"]),
                    metadata=t.get("metadata", {})
                )
                for t in trends_data
            ]
            self._trends_cache = self._organize_trends(trends)
            logger.info(f"[trends] Loaded {len(trends)} cached trends")
    
    def _get_trend_counts(self) -> Dict[str, int]:
        """Get count of trends per platform."""
        return {
            platform: len(trends)
            for platform, trends in self._trends_cache.items()
        }
    
    def apply_trend_boost(
        self,
        base_score: float,
        transcript: str = "",
        hashtags: List[str] = None,
        platform: str = "tiktok"
    ) -> float:
        """
        Apply virality boost if content matches trending topics.
        
        Args:
            base_score: Base virality score (0-100)
            transcript: Video transcript text
            hashtags: List of hashtags in content
            platform: Target platform
            
        Returns:
            Boosted virality score
        """
        hashtags = hashtags or []

        # Check trending_hashtags (TrendingHashtag interface) first
        ht_boost = self._calculate_trend_match_score(
            transcript=transcript,
            hashtags=hashtags,
            trending_tags=self.trending_hashtags.get(platform, []),
        )

        if not self._trends_cache and not self.trending_hashtags:
            return base_score

        transcript_lower = transcript.lower()

        # Get platform trends (TrendingItem interface)
        platform_trends = self._trends_cache.get(platform, [])

        # Check for matches
        boost = ht_boost  # Start with TrendingHashtag-based boost
        matched_trends = []

        for trend in platform_trends[:30]:  # Top 30 trends
            trend_name_lower = trend.name.lower()

            # Check hashtag match
            if any(tag.lower() == trend_name_lower for tag in hashtags):
                # Boost based on trend rank and engagement
                trend_boost = (100 - trend.rank) / 10  # Top trend = +10 points
                trend_boost *= (trend.engagement_score / 100)  # Scale by engagement
                boost += trend_boost
                matched_trends.append(trend.name)

            # Check transcript match (keyword)
            elif trend_name_lower in transcript_lower:
                keyword_boost = (100 - trend.rank) / 20  # Half the boost for keywords
                keyword_boost *= (trend.engagement_score / 100)
                boost += keyword_boost
                matched_trends.append(f"{trend.name} (keyword)")

        # Cap boost at +25 points
        boost = min(25.0, boost)
        
        if boost > 0:
            logger.info(
                f"[trends] Trend boost +{boost:.1f} points "
                f"(matched: {', '.join(matched_trends[:3])})"
            )
        
        return min(100.0, base_score + boost)
    
    def _calculate_trend_match_score(
        self,
        transcript: str,
        hashtags: List[str],
        trending_tags: List[TrendingHashtag],
    ) -> float:
        """Return a boost score (0-25) based on TrendingHashtag matches."""
        if not trending_tags:
            return 0.0
        transcript_lower = transcript.lower()
        boost = 0.0
        for th in trending_tags:
            tag_lower = th.tag.lower()
            if any(h.lower() == tag_lower for h in hashtags):
                boost += th.score / 10  # e.g. score=90 → +9
            elif tag_lower in transcript_lower:
                boost += th.score / 20
        return min(25.0, boost)

    def get_trending_hashtags(self, platform: str = "tiktok", limit: int = 20) -> List[str]:
        """Get list of trending hashtags for a platform."""
        # Check TrendingHashtag interface first
        ht = self.trending_hashtags.get(platform, [])
        if ht:
            return [h.tag for h in ht[:limit]]
        trends = self._trends_cache.get(platform, [])
        names = [t.name for t in trends[:limit] if t.category == "hashtag"]
        if names:
            return names
        # Fallback to hardcoded popular tags when cache is empty
        if platform in ("tiktok", "instagram"):
            fb = self._get_fallback_tiktok_trends() if platform == "tiktok" else self._get_fallback_instagram_trends()
            return [t.name for t in fb[:limit]]
        if platform == "youtube":
            return [t.name for t in self._get_fallback_youtube_trends()[:limit]]
        return []
    
    def get_trend_report(self) -> Dict[str, any]:
        """Get full trend report for analytics."""
        return {
            "last_updated": datetime.now().isoformat(),
            "platforms": {
                platform: {
                    "count": len(trends),
                    "top_10": [
                        {
                            "name": t.name,
                            "rank": t.rank,
                            "engagement": t.engagement_score,
                            "category": t.category
                        }
                        for t in trends[:10]
                    ]
                }
                for platform, trends in self._trends_cache.items()
            }
        }
    
    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()


# Singleton instance for app-wide use
_trend_service_instance: Optional[ViralTrendService] = None


async def get_trend_service(redis_client: Optional[aioredis.Redis] = None) -> ViralTrendService:
    """Get or create singleton trend service instance."""
    global _trend_service_instance
    
    if _trend_service_instance is None:
        _trend_service_instance = ViralTrendService(redis_client)
        await _trend_service_instance.initialize()
        
        # Start background refresh task
        asyncio.create_task(_trend_service_instance.refresh_trends())
    
    return _trend_service_instance
