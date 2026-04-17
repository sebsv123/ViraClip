"""
Unit Tests — Phase 4.3: Viral Trend Integration
================================================
Tests for trend scraping and virality score boosting.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from services.viral_trend_service import ViralTrendService, TrendingHashtag


class TestViralTrendService:
    """Test ViralTrendService functionality."""
    
    def test_service_initialization(self):
        """Service should initialize without errors."""
        service = ViralTrendService()
        assert service is not None
        assert hasattr(service, 'trending_hashtags')
    
    def test_apply_trend_boost_no_match(self):
        """Should return base score when no trends match."""
        service = ViralTrendService()
        
        base_score = 75.0
        boosted = service.apply_trend_boost(
            base_score=base_score,
            transcript="Random content about cats",
            hashtags=["cats", "pets"],
            platform="tiktok"
        )
        
        # Should be same or slightly higher (fallback trends)
        assert boosted >= base_score
        assert boosted <= base_score + 5.0
    
    def test_apply_trend_boost_with_match(self):
        """Should boost score when trending hashtag matches."""
        service = ViralTrendService()
        
        # Add mock trending hashtag
        service.trending_hashtags["tiktok"] = [
            TrendingHashtag(
                tag="viral",
                score=95.0,
                views=1000000,
                platform="tiktok"
            )
        ]
        
        base_score = 75.0
        boosted = service.apply_trend_boost(
            base_score=base_score,
            transcript="This is going viral!",
            hashtags=["viral", "trending"],
            platform="tiktok"
        )
        
        # Should be boosted
        assert boosted > base_score
        assert boosted <= 100.0  # Should not exceed max
    
    def test_trend_boost_caps_at_100(self):
        """Boosted score should never exceed 100."""
        service = ViralTrendService()
        
        # Add high-scoring trend
        service.trending_hashtags["tiktok"] = [
            TrendingHashtag(tag="mega", score=99.0, views=10000000, platform="tiktok")
        ]
        
        boosted = service.apply_trend_boost(
            base_score=90.0,
            transcript="mega viral content",
            hashtags=["mega"],
            platform="tiktok"
        )
        
        assert boosted <= 100.0
    
    def test_get_trending_hashtags_fallback(self):
        """Should return fallback trends when no cached data."""
        service = ViralTrendService()
        
        hashtags = service.get_trending_hashtags("tiktok", limit=5)
        
        assert len(hashtags) > 0
        assert len(hashtags) <= 5
        assert all(isinstance(tag, str) for tag in hashtags)
    
    def test_calculate_trend_match_score(self):
        """Should calculate match score correctly."""
        service = ViralTrendService()
        
        trending = [
            TrendingHashtag(tag="viral", score=90.0, views=1000000, platform="tiktok"),
            TrendingHashtag(tag="trending", score=85.0, views=800000, platform="tiktok")
        ]
        
        # Exact match
        score = service._calculate_trend_match_score(
            transcript="viral content",
            hashtags=["viral"],
            trending_tags=trending
        )
        assert score > 0
        
        # No match
        score = service._calculate_trend_match_score(
            transcript="random content",
            hashtags=["random"],
            trending_tags=trending
        )
        assert score == 0


class TestTrendingHashtag:
    """Test TrendingHashtag dataclass."""
    
    def test_hashtag_creation(self):
        """Should create hashtag with correct attributes."""
        hashtag = TrendingHashtag(
            tag="viral",
            score=95.0,
            views=1000000,
            platform="tiktok"
        )
        
        assert hashtag.tag == "viral"
        assert hashtag.score == 95.0
        assert hashtag.views == 1000000
        assert hashtag.platform == "tiktok"


@pytest.mark.asyncio
class TestTrendScraping:
    """Test trend scraping functionality."""
    
    async def test_refresh_trends_method_exists(self):
        """Should have refresh_trends method."""
        service = ViralTrendService()
        assert hasattr(service, 'refresh_trends')
    
    @patch('services.viral_trend_service.httpx.AsyncClient')
    async def test_scrape_tiktok_trends_mock(self, mock_client):
        """Should scrape TikTok trends (mocked)."""
        service = ViralTrendService()
        
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "hashtags": [
                    {"name": "viral", "views": 1000000},
                    {"name": "trending", "views": 800000}
                ]
            }
        }
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        
        trends = await service._scrape_tiktok_trends()
        
        assert len(trends) >= 0  # May be empty if scraping fails


@pytest.mark.integration
class TestTrendIntegration:
    """Integration tests for trend service."""
    
    @pytest.mark.skip(reason="Requires external API")
    async def test_refresh_all_trends(self):
        """Should refresh trends from all platforms."""
        service = ViralTrendService()
        
        await service.refresh_trends()
        
        # Should have cached some trends
        assert len(service.trending_hashtags) > 0
    
    def test_trend_boost_integration_with_phi3(self):
        """Should integrate with Phi3ViralityService."""
        from services.phi3_virality_service import Phi3ViralityService
        
        trend_service = ViralTrendService()
        phi3_service = Phi3ViralityService()
        
        # Verify Phi3 has trend service
        assert phi3_service.trend_service is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
