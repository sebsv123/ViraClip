"""
Tests for:
  1. Competitor Intelligence API (/competitors/*)
  2. Auto-Scheduler API (/scheduler/*)
  3. process_scheduled_job ARQ worker registration
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_competitor(competitor_id="comp_abc123"):
    from src.services.competitor_intelligence import Competitor
    return Competitor(
        competitor_id=competitor_id,
        name="Test Channel",
        platforms={"youtube": "@testchan"},
        niche="education",
        follower_count={"youtube": 150000},
        added_at="2026-04-05T10:00:00",
        last_sync="2026-04-05T10:00:00",
        is_active=True,
    )


def _make_video(video_id="vid_001", competitor_id="comp_abc123"):
    from src.services.competitor_intelligence import CompetitorVideo
    return CompetitorVideo(
        video_id=video_id,
        competitor_id=competitor_id,
        platform="youtube",
        title="Amazing Video",
        url="https://youtube.com/watch?v=abc",
        thumbnail="",
        published_at="2026-04-05T09:00:00",
        views=500000,
        likes=40000,
        comments=1000,
        shares=5000,
        engagement_rate=9.0,
        virality_score=85.0,
        duration=60,
        tags=["viral", "trending"],
    )


# ---------------------------------------------------------------------------
# 1. Competitor Intelligence API
# ---------------------------------------------------------------------------

class TestCompetitorIntelligenceAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.competitors import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_add_competitor(self):
        client = self._get_client()
        mock_comp = _make_competitor()

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.add_competitor",
            new_callable=AsyncMock,
            return_value=mock_comp,
        ):
            resp = client.post("/competitors", json={
                "name": "Test Channel",
                "platform_handles": {"youtube": "@testchan"},
                "niche": "education",
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "added")
        self.assertEqual(data["competitor_id"], "comp_abc123")
        self.assertEqual(data["name"], "Test Channel")

    def test_list_competitors_dashboard(self):
        client = self._get_client()
        mock_dashboard = {
            "competitors": [{"competitor_id": "c1", "name": "Chan A", "niche": "tech"}],
            "competitor_count": 1,
            "recent_viral_videos": [],
            "trend_insights": [],
            "monitoring_active": False,
        }

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_dashboard",
            return_value=mock_dashboard,
        ):
            resp = client.get("/competitors")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["competitor_count"], 1)

    def test_get_insights(self):
        client = self._get_client()
        mock_dashboard = {
            "competitors": [],
            "competitor_count": 0,
            "recent_viral_videos": [],
            "trend_insights": [{"insight_id": "i1", "description": "Trending shorts"}],
            "monitoring_active": True,
        }

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_dashboard",
            return_value=mock_dashboard,
        ):
            resp = client.get("/competitors/insights")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["insights"]), 1)

    def test_viral_leaderboard(self):
        client = self._get_client()
        video = _make_video()
        mock_dashboard = {
            "competitors": [],
            "competitor_count": 0,
            "recent_viral_videos": [
                {
                    "video_id": video.video_id,
                    "virality_score": video.virality_score,
                    "views": video.views,
                    "title": video.title,
                }
            ],
            "trend_insights": [],
            "monitoring_active": False,
        }

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_dashboard",
            return_value=mock_dashboard,
        ):
            resp = client.get("/competitors/leaderboard?limit=5")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["videos"][0]["video_id"], "vid_001")

    def test_get_competitor_performance(self):
        client = self._get_client()
        mock_perf = {
            "competitor_id": "comp_abc123",
            "name": "Test Channel",
            "period_days": 30,
            "videos_published": 12,
            "total_views": 1200000,
            "avg_engagement_rate": 8.5,
            "avg_virality_score": 82.3,
            "best_performing_video": "Amazing Video",
            "platform_breakdown": {"youtube": {"video_count": 12, "total_views": 1200000}},
        }

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_performance",
            return_value=mock_perf,
        ):
            resp = client.get("/competitors/comp_abc123?days=30")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["performance"]["avg_virality_score"], 82.3)

    def test_get_competitor_performance_not_found(self):
        client = self._get_client()

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_performance",
            return_value=None,
        ):
            resp = client.get("/competitors/nonexistent")

        self.assertEqual(resp.status_code, 404)

    def test_compare_to_competitors(self):
        client = self._get_client()
        mock_result = {
            "comparisons": [{"competitor_name": "Chan A", "engagement_gap": 1.5}],
            "average_market_engagement": 8.5,
            "average_market_virality": 79.0,
            "recommendations": ["Increase posting frequency"],
        }

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.compare_to_competitors",
            return_value=mock_result,
        ):
            resp = client.post("/competitors/compare", json={
                "user_avg_engagement": 7.0,
                "user_avg_virality": 65.0,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("comparisons", data)
        self.assertEqual(data["average_market_virality"], 79.0)

    def test_start_monitoring(self):
        client = self._get_client()

        with patch("asyncio.create_task"):
            resp = client.post("/competitors/monitoring/start?interval_minutes=15")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["interval_minutes"], 15)

    def test_stop_monitoring(self):
        client = self._get_client()

        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.stop_monitoring",
            new_callable=AsyncMock,
        ):
            resp = client.post("/competitors/monitoring/stop")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "stopped")

    def test_sync_competitor(self):
        client = self._get_client()
        video = _make_video()

        # Seed the singleton's _competitors dict so the route finds it
        from src.services.competitor_intelligence import get_competitor_intelligence_service
        svc = get_competitor_intelligence_service()
        svc._competitors["comp_abc123"] = _make_competitor()

        with patch.object(svc, "_sync_competitor_videos", new_callable=AsyncMock, return_value=[video]):
            resp = client.post("/competitors/comp_abc123/sync")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["competitor_id"], "comp_abc123")
        self.assertEqual(data["new_videos"], 1)


# ---------------------------------------------------------------------------
# 2. Auto-Scheduler API
# ---------------------------------------------------------------------------

class TestSchedulerAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.scheduler import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_frequencies(self):
        client = self._get_client()
        resp = client.get("/scheduler/frequencies")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("daily", data["frequencies"])
        self.assertIn("weekly", data["frequencies"])
        self.assertIn("custom", data["frequencies"])

    def test_create_schedule_success(self):
        client = self._get_client()
        from datetime import datetime
        from src.services.auto_scheduler import ScheduledJob, ScheduleFrequency, TriggerType

        mock_job = ScheduledJob(
            job_id="job_abc123",
            user_id="anon",
            name="Daily YouTube",
            trigger_type=TriggerType.SCHEDULED,
            frequency=ScheduleFrequency.DAILY,
            cron_expression=None,
            source_config={"type": "youtube_channel", "url": "https://youtube.com/@chan"},
            processing_config={"target_platform": "tiktok"},
            publish_config={},
            is_active=True,
            created_at=datetime.utcnow(),
            next_run=datetime.utcnow(),
        )

        with patch(
            "src.services.auto_scheduler.AutoSchedulerService.schedule_recurring_source",
            new_callable=AsyncMock,
            return_value=mock_job,
        ):
            resp = client.post("/scheduler/schedules", json={
                "name": "Daily YouTube",
                "source_type": "youtube_channel",
                "source_url": "https://youtube.com/@chan",
                "frequency": "daily",
                "processing_config": {"target_platform": "tiktok"},
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "scheduled")
        self.assertEqual(data["job_id"], "job_abc123")

    def test_create_schedule_invalid_frequency(self):
        client = self._get_client()
        resp = client.post("/scheduler/schedules", json={
            "name": "Bad Freq",
            "source_type": "youtube_channel",
            "source_url": "https://youtube.com/@chan",
            "frequency": "minutely",   # invalid
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_schedules_empty(self):
        client = self._get_client()

        with patch(
            "src.services.auto_scheduler.AutoSchedulerService.get_user_schedules",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/scheduler/schedules")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["schedules"], [])

    def test_deactivate_schedule_success(self):
        client = self._get_client()

        with patch(
            "src.services.auto_scheduler.AutoSchedulerService.deactivate_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/scheduler/schedules/job_abc123")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deactivated")

    def test_deactivate_schedule_not_found(self):
        client = self._get_client()

        with patch(
            "src.services.auto_scheduler.AutoSchedulerService.deactivate_job",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/scheduler/schedules/missing_job")

        self.assertEqual(resp.status_code, 404)

    def test_create_trend_trigger(self):
        client = self._get_client()
        from src.services.auto_scheduler import TrendTrigger

        mock_trigger = TrendTrigger(
            trigger_id="trig_xyz",
            user_id="anon",
            keywords=["AI", "viral"],
            min_virality_score=75.0,
            processing_config={},
            publish_config={},
            is_active=True,
        )

        with patch(
            "src.services.auto_scheduler.AutoSchedulerService.create_trend_trigger",
            new_callable=AsyncMock,
            return_value=mock_trigger,
        ):
            resp = client.post("/scheduler/triggers", json={
                "keywords": ["AI", "viral"],
                "min_virality_score": 75.0,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["trigger_id"], "trig_xyz")
        self.assertIn("AI", data["keywords"])

    def test_create_trend_trigger_empty_keywords(self):
        client = self._get_client()
        resp = client.post("/scheduler/triggers", json={"keywords": []})
        self.assertEqual(resp.status_code, 400)

    def test_run_schedule_now(self):
        client = self._get_client()

        with patch(
            "src.services.auto_scheduler.AutoSchedulerService.process_scheduled_job",
            new_callable=AsyncMock,
        ):
            resp = client.post("/scheduler/schedules/job_abc/run-now")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "triggered")
        self.assertEqual(resp.json()["job_id"], "job_abc")


# ---------------------------------------------------------------------------
# 3. process_scheduled_job ARQ worker
# ---------------------------------------------------------------------------

class TestProcessScheduledJobWorker(unittest.TestCase):
    def test_function_exists(self):
        from src.workers.tasks import process_scheduled_job
        self.assertTrue(callable(process_scheduled_job))

    def test_registered_in_worker_settings(self):
        from src.workers.tasks import WorkerSettings, process_scheduled_job
        self.assertIn(process_scheduled_job, WorkerSettings.functions)

    def test_worker_success(self):
        from src.workers.tasks import process_scheduled_job

        ctx = {"redis": AsyncMock()}

        async def run_test():
            with patch("src.services.auto_scheduler.AutoSchedulerService") as mock_cls:
                mock_svc = mock_cls.return_value
                mock_svc.process_scheduled_job = AsyncMock()
                with patch(
                    "src.services.auto_scheduler.AutoSchedulerService",
                    return_value=mock_svc,
                ):
                    return await process_scheduled_job(ctx, job_id="j1", user_id="u1")

        result = run(run_test())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["job_id"], "j1")

    def test_worker_reraises_on_failure(self):
        from src.workers.tasks import process_scheduled_job

        ctx = {}

        async def run_test():
            with patch("src.services.auto_scheduler.AutoSchedulerService") as mock_cls:
                mock_svc = mock_cls.return_value
                mock_svc.process_scheduled_job = AsyncMock(
                    side_effect=RuntimeError("Redis gone")
                )
                with patch(
                    "src.services.auto_scheduler.AutoSchedulerService",
                    return_value=mock_svc,
                ):
                    return await process_scheduled_job(ctx, job_id="j_err", user_id="u1")

        with self.assertRaises(RuntimeError):
            run(run_test())


if __name__ == "__main__":
    unittest.main()
