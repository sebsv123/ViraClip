"""
Tests for:
  1. Content Calendar API (/calendar/*)
  2. Advanced Search API (/search/*)
  3. Trending Topics API (/trending/*)
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scheduled_content(schedule_id="sched_001", clip_id="clip_abc"):
    from src.services.content_calendar import (
        ContentCalendarService,
        ContentType,
        ScheduleStatus,
        ScheduledContent,
    )
    return ScheduledContent(
        schedule_id=schedule_id,
        user_id="anon",
        clip_id=clip_id,
        content_type=ContentType.SHORT_FORM,
        platforms=["tiktok", "instagram"],
        scheduled_time=(datetime.now() + timedelta(hours=3)).isoformat(),
        caption="Amazing content!",
        hashtags=["#viral", "#trending"],
        thumbnail_url="",
        status=ScheduleStatus.SCHEDULED,
        timezone="UTC",
        optimal_score=0.87,
        created_at=datetime.now().isoformat(),
        published_at=None,
    )


# ---------------------------------------------------------------------------
# 1. Content Calendar API
# ---------------------------------------------------------------------------

class TestCalendarAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.calendar import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_schedule_clip_auto_optimize(self):
        client = self._get_client()
        mock_item = _make_scheduled_content()

        with patch(
            "src.services.content_calendar.ContentCalendarService.schedule_content",
            new_callable=AsyncMock,
            return_value=mock_item,
        ):
            resp = client.post("/calendar/schedule", json={
                "clip_id": "clip_abc",
                "platforms": ["tiktok"],
                "auto_optimize": True,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "scheduled")
        self.assertEqual(data["item"]["clip_id"], "clip_abc")
        self.assertEqual(data["item"]["optimal_score"], 0.87)

    def test_schedule_clip_with_preferred_time(self):
        client = self._get_client()
        mock_item = _make_scheduled_content()
        future_time = (datetime.now() + timedelta(hours=5)).isoformat()

        with patch(
            "src.services.content_calendar.ContentCalendarService.schedule_content",
            new_callable=AsyncMock,
            return_value=mock_item,
        ):
            resp = client.post("/calendar/schedule", json={
                "clip_id": "clip_abc",
                "platforms": ["youtube"],
                "preferred_time": future_time,
                "auto_optimize": False,
            })

        self.assertEqual(resp.status_code, 200)

    def test_schedule_invalid_content_type(self):
        client = self._get_client()
        resp = client.post("/calendar/schedule", json={
            "clip_id": "clip_xyz",
            "platforms": ["tiktok"],
            "content_type": "hologram",
        })
        self.assertEqual(resp.status_code, 400)

    def test_schedule_invalid_datetime(self):
        client = self._get_client()
        resp = client.post("/calendar/schedule", json={
            "clip_id": "clip_xyz",
            "platforms": ["tiktok"],
            "preferred_time": "not-a-date",
        })
        self.assertEqual(resp.status_code, 400)

    def test_bulk_schedule(self):
        client = self._get_client()
        mocks = [_make_scheduled_content(f"sched_{i}", f"clip_{i}") for i in range(3)]

        with patch(
            "src.services.content_calendar.ContentCalendarService.bulk_schedule",
            new_callable=AsyncMock,
            return_value=mocks,
        ):
            resp = client.post("/calendar/schedule/bulk", json={
                "items": [
                    {"clip_id": f"clip_{i}", "platforms": ["tiktok"]}
                    for i in range(3)
                ],
                "spacing_hours": 6,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["items"]), 3)

    def test_reschedule_clip_success(self):
        client = self._get_client()
        future_time = (datetime.now() + timedelta(days=1)).isoformat()

        with patch(
            "src.services.content_calendar.ContentCalendarService.reschedule_content",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.put("/calendar/schedule/sched_001/reschedule", json={
                "new_time": future_time,
                "reason": "Better engagement window",
            })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "rescheduled")

    def test_reschedule_clip_not_found(self):
        client = self._get_client()

        with patch(
            "src.services.content_calendar.ContentCalendarService.reschedule_content",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.put("/calendar/schedule/nonexistent/reschedule", json={
                "new_time": (datetime.now() + timedelta(days=1)).isoformat(),
            })

        self.assertEqual(resp.status_code, 404)

    def test_cancel_scheduled_success(self):
        client = self._get_client()

        with patch(
            "src.services.content_calendar.ContentCalendarService.cancel_scheduled",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/calendar/schedule/sched_001")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "cancelled")

    def test_cancel_scheduled_not_found(self):
        client = self._get_client()

        with patch(
            "src.services.content_calendar.ContentCalendarService.cancel_scheduled",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/calendar/schedule/missing")

        self.assertEqual(resp.status_code, 404)

    def test_get_calendar_view(self):
        client = self._get_client()
        start = datetime.now().isoformat()
        end = (datetime.now() + timedelta(days=7)).isoformat()
        mock_view = {
            "user_id": "anon",
            "start_date": start,
            "end_date": end,
            "events": [{"schedule_id": "s1", "scheduled_time": start}],
            "optimal_slots": [],
            "total_scheduled": 1,
            "publishing": 1,
        }

        with patch(
            "src.services.content_calendar.ContentCalendarService.get_calendar_view",
            new_callable=AsyncMock,
            return_value=mock_view,
        ):
            resp = client.get(f"/calendar/view?start={start}&end={end}")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_scheduled"], 1)

    def test_get_publishing_queue(self):
        client = self._get_client()
        mock_queue = [{"schedule_id": "s1", "scheduled_time": "2026-04-06T19:00:00"}]

        with patch(
            "src.services.content_calendar.ContentCalendarService.get_publishing_queue",
            new_callable=AsyncMock,
            return_value=mock_queue,
        ):
            resp = client.get("/calendar/queue?limit=10")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_get_scheduling_stats(self):
        client = self._get_client()
        mock_stats = {
            "total_scheduled": 5,
            "published": 3,
            "scheduled": 2,
            "failed": 0,
            "avg_optimal_score": 0.82,
            "platforms_used": ["tiktok", "instagram"],
        }

        with patch(
            "src.services.content_calendar.ContentCalendarService.get_scheduling_stats",
            return_value=mock_stats,
        ):
            resp = client.get("/calendar/stats")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["total_scheduled"], 5)


# ---------------------------------------------------------------------------
# 2. Advanced Search API
# ---------------------------------------------------------------------------

class TestSearchAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.search import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _mock_results(self):
        return {
            "results": [
                {
                    "item_id": "clip_001",
                    "item_type": "clip",
                    "title": "Amazing AI tutorial",
                    "description": "Learn AI in 60 seconds",
                    "score": 15.3,
                    "matched_fields": ["title"],
                    "highlight": {"title": "...<mark>AI</mark> tutorial..."},
                    "metadata": {"virality_score": 88.0},
                }
            ],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "total_pages": 1,
            "facets": {"niche": {}, "platform": {}, "virality_ranges": {"high": 1, "medium": 0, "low": 0}},
        }

    def test_search_post(self):
        client = self._get_client()

        with patch(
            "src.services.search_service.AdvancedSearchService.search",
            return_value=self._mock_results(),
        ):
            resp = client.post("/search", json={"query": "AI tutorial", "sort": "relevance"})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["item_id"], "clip_001")

    def test_search_get(self):
        client = self._get_client()

        with patch(
            "src.services.search_service.AdvancedSearchService.search",
            return_value=self._mock_results(),
        ):
            resp = client.get("/search?q=AI+tutorial&platform=tiktok&min_virality=50")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)

    def test_search_invalid_sort(self):
        client = self._get_client()
        resp = client.post("/search", json={"query": "test", "sort": "random_order"})
        self.assertEqual(resp.status_code, 400)

    def test_search_get_invalid_sort(self):
        client = self._get_client()
        resp = client.get("/search?q=test&sort=bogus")
        self.assertEqual(resp.status_code, 400)

    def test_suggest(self):
        client = self._get_client()

        with patch(
            "src.services.search_service.AdvancedSearchService.get_suggestions",
            return_value=["viral", "virality", "viralclip"],
        ):
            resp = client.get("/search/suggest?q=vir")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("viral", data["suggestions"])
        self.assertEqual(data["query"], "vir")

    def test_index_clip(self):
        client = self._get_client()

        with patch("src.services.search_service.AdvancedSearchService.index_clip") as mock_idx:
            resp = client.post("/search/index", json={
                "clip_id": "clip_new",
                "title": "My Viral Clip",
                "virality_score": 82.5,
                "platform": "tiktok",
            })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "indexed")
        mock_idx.assert_called_once()

    def test_remove_from_index(self):
        client = self._get_client()

        with patch("src.services.search_service.SearchIndex.remove_document") as mock_rm:
            resp = client.delete("/search/index/clip_001")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "removed")
        mock_rm.assert_called_once_with("clip_001")

    def test_list_fields(self):
        client = self._get_client()
        resp = client.get("/search/fields")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("title", data["fields"])
        self.assertIn("relevance", data["sort_options"])
        self.assertIn("min_virality", data["filter_keys"])


# ---------------------------------------------------------------------------
# 3. Trending Topics API
# ---------------------------------------------------------------------------

class TestTrendingAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.trending import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _make_topic(self):
        from src.services.trending_topics import TrendCategory, TrendStatus, TrendingTopic
        return TrendingTopic(
            topic_id="trend_abc",
            keyword="AI tutorial",
            category=TrendCategory.TECHNOLOGY,
            status=TrendStatus.RISING,
            velocity=2.5,
            volume=50000,
            sentiment_score=0.8,
            related_hashtags=["#AI", "#Tutorial"],
            peak_time=None,
            estimated_duration_hours=48,
            score=78.5,
        )

    def test_get_trending_topics(self):
        client = self._get_client()
        topic = self._make_topic()

        with patch(
            "src.services.trending_topics.TrendingTopicsService.get_trending_topics",
            new_callable=AsyncMock,
            return_value=[topic],
        ):
            resp = client.get("/trending")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["topics"][0]["keyword"], "AI tutorial")
        self.assertEqual(data["topics"][0]["score"], 78.5)

    def test_get_trending_with_category_filter(self):
        client = self._get_client()
        topic = self._make_topic()

        with patch(
            "src.services.trending_topics.TrendingTopicsService.get_trending_topics",
            new_callable=AsyncMock,
            return_value=[topic],
        ):
            resp = client.get("/trending?category=technology&status=rising")

        self.assertEqual(resp.status_code, 200)

    def test_get_trending_invalid_category(self):
        client = self._get_client()
        resp = client.get("/trending?category=quantum_cooking")
        self.assertEqual(resp.status_code, 400)

    def test_get_trending_invalid_status(self):
        client = self._get_client()
        resp = client.get("/trending?status=hyperactive")
        self.assertEqual(resp.status_code, 400)

    def test_get_trend_analytics(self):
        client = self._get_client()
        mock_analytics = {
            "total_trends": 5,
            "by_category": {"technology": {"count": 2, "avg_score": 75.0, "total_volume": 100000}},
            "by_status": {"rising": 3, "peak": 2},
            "top_trends": [{"keyword": "AI tutorial", "score": 78.5, "status": "rising"}],
            "last_updated": datetime.now().isoformat(),
        }

        with patch(
            "src.services.trending_topics.TrendingTopicsService.get_trend_analytics",
            return_value=mock_analytics,
        ):
            resp = client.get("/trending/analytics")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_trends"], 5)

    def test_list_categories(self):
        client = self._get_client()
        resp = client.get("/trending/categories")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("technology", data["categories"])
        self.assertIn("rising", data["statuses"])

    def test_predict_lifecycle(self):
        client = self._get_client()
        mock_lifecycle = {
            "topic": "AI tutorial",
            "current_status": "rising",
            "predicted_peak": (datetime.now() + timedelta(hours=12)).isoformat(),
            "time_to_peak": "12 hours",
            "estimated_duration_remaining": 48,
            "recommendation": "Post now",
        }

        with patch(
            "src.services.trending_topics.TrendingTopicsService.predict_trend_lifecycle",
            new_callable=AsyncMock,
            return_value=mock_lifecycle,
        ):
            resp = client.get("/trending/trend_abc/lifecycle")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["recommendation"], "Post now")

    def test_predict_lifecycle_not_found(self):
        client = self._get_client()

        with patch(
            "src.services.trending_topics.TrendingTopicsService.predict_trend_lifecycle",
            new_callable=AsyncMock,
            return_value={"error": "Topic not found"},
        ):
            resp = client.get("/trending/nonexistent/lifecycle")

        self.assertEqual(resp.status_code, 404)

    def test_analyze_content_for_trends(self):
        client = self._get_client()
        mock_analysis = {
            "alignment_score": 82.0,
            "matching_trends": [{"keyword": "AI tutorial", "score": 78.5}],
            "trending_potential": "high",
            "suggestions": ["Your content aligns well with 'AI tutorial' trend"],
        }

        with patch(
            "src.services.trending_topics.TrendingTopicsService.analyze_content_for_trends",
            new_callable=AsyncMock,
            return_value=mock_analysis,
        ):
            resp = client.post("/trending/analyze", json={
                "transcript": "Today we cover AI and machine learning",
                "title": "AI tutorial for beginners",
                "hashtags": ["#AI", "#ML"],
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["trending_potential"], "high")
        self.assertEqual(data["alignment_score"], 82.0)

    def test_get_personalized_recommendations(self):
        client = self._get_client()
        topic = self._make_topic()
        from src.services.trending_topics import ContentRecommendation
        mock_rec = ContentRecommendation(
            recommendation_id="rec_001",
            topic=topic,
            content_type="short_form",
            suggested_hook="This AI tutorial will change everything...",
            suggested_duration=45,
            suggested_hashtags=["#AI", "#Tutorial"],
            confidence=0.78,
            created_at=datetime.now().isoformat(),
        )

        with patch(
            "src.services.trending_topics.TrendingTopicsService.get_personalized_recommendations",
            new_callable=AsyncMock,
            return_value=[mock_rec],
        ):
            resp = client.post("/trending/recommendations", json={
                "user_id": "user_123",
                "niche": "tech",
                "limit": 5,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["recommendations"][0]["keyword"], "AI tutorial")
        self.assertEqual(data["recommendations"][0]["suggested_duration_seconds"], 45)
        self.assertAlmostEqual(data["recommendations"][0]["confidence"], 0.78, places=2)


if __name__ == "__main__":
    unittest.main()
