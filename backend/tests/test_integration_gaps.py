"""
Tests for integration gap fixes:
  1. analyze_ab_test ARQ worker function (tasks.py)
  2. Translation API routes (routes/translation.py)
  3. Campaign API routes (routes/campaigns.py)
  4. Task model feature flags (enable_timeline, enable_vision_ai, enable_timeline_render)
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. analyze_ab_test ARQ worker
# ---------------------------------------------------------------------------

class TestAnalyzeAbTestWorker(unittest.TestCase):
    def test_function_exists_in_tasks(self):
        """analyze_ab_test must be importable from workers.tasks."""
        from src.workers.tasks import analyze_ab_test
        self.assertTrue(callable(analyze_ab_test))

    def test_registered_in_worker_settings(self):
        """analyze_ab_test must be in WorkerSettings.functions."""
        from src.workers.tasks import WorkerSettings, analyze_ab_test
        self.assertIn(analyze_ab_test, WorkerSettings.functions)

    def test_analyze_ab_test_success(self):
        """Worker returns analyzed result when service succeeds."""
        from src.workers.tasks import analyze_ab_test

        mock_winner = MagicMock()
        mock_winner.variant_id = "variant_abc"

        ctx = {"redis": AsyncMock()}

        with patch("src.workers.tasks.ABTestingService", create=True) as mock_cls:
            # patch inside the lazy import path
            pass

        with patch.dict("sys.modules", {}):
            async def run_test():
                with patch("src.services.ab_testing_service.ABTestingService") as mock_cls:
                    mock_svc = mock_cls.return_value
                    mock_svc.analyze_test = AsyncMock(return_value=mock_winner)

                    # Patch the import inside the worker function
                    import importlib
                    import src.workers.tasks as tasks_mod

                    original = getattr(tasks_mod, "_ab_svc_factory", None)
                    try:
                        with patch.object(
                            mock_svc, "analyze_test", return_value=mock_winner
                        ):
                            # Direct call with mocked service
                            with patch(
                                "src.services.ab_testing_service.ABTestingService",
                                return_value=mock_svc,
                            ):
                                result = await analyze_ab_test(
                                    ctx, user_id="user1", test_id="test123"
                                )
                        return result
                    finally:
                        pass

            result = run(run_test())
            self.assertEqual(result["test_id"], "test123")
            self.assertEqual(result["status"], "analyzed")

    def test_analyze_ab_test_inconclusive(self):
        """Worker handles None winner (inconclusive result)."""
        from src.workers.tasks import analyze_ab_test

        ctx = {"redis": AsyncMock()}

        async def run_test():
            with patch("src.services.ab_testing_service.ABTestingService") as mock_cls:
                mock_svc = mock_cls.return_value
                mock_svc.analyze_test = AsyncMock(return_value=None)
                with patch(
                    "src.services.ab_testing_service.ABTestingService",
                    return_value=mock_svc,
                ):
                    return await analyze_ab_test(ctx, user_id="u1", test_id="t_null")

        result = run(run_test())
        self.assertIsNone(result["winner"])

    def test_analyze_ab_test_reraises_on_error(self):
        """Worker re-raises exceptions so ARQ can retry."""
        from src.workers.tasks import analyze_ab_test

        ctx = {"redis": AsyncMock()}

        async def run_test():
            with patch("src.services.ab_testing_service.ABTestingService") as mock_cls:
                mock_svc = mock_cls.return_value
                mock_svc.analyze_test = AsyncMock(side_effect=RuntimeError("DB down"))
                with patch(
                    "src.services.ab_testing_service.ABTestingService",
                    return_value=mock_svc,
                ):
                    return await analyze_ab_test(ctx, user_id="u1", test_id="err_t")

        with self.assertRaises(RuntimeError):
            run(run_test())


# ---------------------------------------------------------------------------
# 2. Translation API route tests
# ---------------------------------------------------------------------------

class TestTranslationAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.translation import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_languages(self):
        client = self._get_client()
        resp = client.get("/translations/languages")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("languages", data)
        self.assertIn("es", data["languages"])
        self.assertIn("ja", data["languages"])
        self.assertGreater(data["count"], 10)

    def test_translation_stats(self):
        client = self._get_client()
        resp = client.get("/translations/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("stats", data)
        self.assertIn("provider", data["stats"])
        self.assertIn("cache_size", data["stats"])

    def test_quick_translate(self):
        client = self._get_client()
        resp = client.post("/translations/quick", json={
            "text": "Hello world",
            "target_language": "es",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["original"], "Hello world")
        self.assertEqual(data["target_language"], "es")
        self.assertIn("translated", data)
        self.assertIn("confidence", data)

    def test_quick_translate_empty_text(self):
        client = self._get_client()
        resp = client.post("/translations/quick", json={
            "text": "",
            "target_language": "fr",
        })
        self.assertEqual(resp.status_code, 200)
        # Empty text returns original unchanged
        self.assertEqual(resp.json()["original"], "")

    def test_translate_clip(self):
        client = self._get_client()
        resp = client.post("/translations/clip", json={
            "clip_id": "clip_001",
            "title": "Amazing viral moment",
            "captions": [
                {"start": 0.0, "end": 2.0, "text": "This is incredible!"},
            ],
            "description": "You won't believe this",
            "target_languages": ["es", "fr", "de"],
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clip_id"], "clip_001")
        self.assertEqual(data["languages_count"], 3)
        self.assertIn("es", data["title_translations"])
        self.assertIn("fr", data["title_translations"])
        self.assertIn("de", data["title_translations"])
        self.assertIn("es", data["hashtag_suggestions"])

    def test_translate_clip_default_languages(self):
        """When no target_languages specified, defaults to top-5."""
        client = self._get_client()
        resp = client.post("/translations/clip", json={
            "clip_id": "clip_002",
            "title": "Wow",
            "description": "desc",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["languages_count"], 1)

    def test_detect_language(self):
        client = self._get_client()
        resp = client.post("/translations/detect", params={"text": "Hello there"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("detected_language", data)
        self.assertIn("language_name", data)

    def test_quick_translate_unsupported_language_graceful(self):
        """Unsupported language falls back (mock translate handles it)."""
        client = self._get_client()
        resp = client.post("/translations/quick", json={
            "text": "Test",
            "target_language": "xx",  # unsupported
        })
        # Should still return 200 (service handles unknown lang gracefully)
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# 3. Campaign API route tests
# ---------------------------------------------------------------------------

class TestCampaignAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.campaigns import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_campaign_success(self):
        client = self._get_client()

        with patch("src.services.campaign_service.CampaignService.create_ab_test_campaign",
                   new_callable=AsyncMock,
                   return_value={"campaign_id": "camp_1", "variations_count": 2, "status": "active"}):
            resp = client.post("/campaigns", json={
                "task_id": "task_001",
                "clip_id": "clip_001",
                "test_styles": ["tiktok_viral", "reels_drama"],
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["campaign"]["campaign_id"], "camp_1")

    def test_analyze_campaign_performance(self):
        client = self._get_client()

        with patch("src.services.campaign_service.CampaignService.analyze_performance",
                   new_callable=AsyncMock,
                   return_value={"top_variant": "tiktok_viral", "improvement_score": 1.3}):
            resp = client.get("/campaigns/camp_1/performance")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["campaign_id"], "camp_1")
        self.assertIn("analysis", data)

    def test_list_campaigns_empty_repo(self):
        """If CampaignRepository.get_user_campaigns doesn't exist, returns empty list."""
        client = self._get_client()
        with patch("src.repositories.campaign_repository.CampaignRepository.get_user_campaigns",
                   side_effect=AttributeError("not found")):
            resp = client.get("/campaigns")
        # AttributeError is caught → returns empty list
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_get_campaign_not_found(self):
        client = self._get_client()
        with patch("src.repositories.campaign_repository.CampaignRepository.get_campaign",
                   return_value=None):
            resp = client.get("/campaigns/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_get_campaign_success(self):
        client = self._get_client()
        mock_camp = {"campaign_id": "c1", "name": "Test", "status": "active"}

        with patch("src.repositories.campaign_repository.CampaignRepository.get_campaign",
                   return_value=mock_camp):
            resp = client.get("/campaigns/c1")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["campaign"]["campaign_id"], "c1")

    def test_record_performance(self):
        client = self._get_client()
        mock_record = {"clip_id": "clip_1", "platform": "tiktok", "views": 500}

        with patch("src.repositories.campaign_repository.CampaignRepository.record_clip_performance",
                   return_value=mock_record):
            resp = client.post("/campaigns/performance", json={
                "clip_id": "clip_1",
                "platform": "tiktok",
                "views": 500,
                "likes": 50,
                "watch_rate": 0.75,
            })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "recorded")

    def test_record_performance_stub_fallback(self):
        """If record_clip_performance not on repository, returns stub."""
        client = self._get_client()
        with patch("src.repositories.campaign_repository.CampaignRepository.record_clip_performance",
                   side_effect=AttributeError("not found")):
            resp = client.post("/campaigns/performance", json={
                "clip_id": "clip_2",
                "platform": "instagram",
                "views": 100,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["record"]["clip_id"], "clip_2")

    def test_get_clip_performance_empty(self):
        client = self._get_client()
        with patch("src.repositories.campaign_repository.CampaignRepository.get_clip_performance",
                   side_effect=AttributeError):
            resp = client.get("/campaigns/performance/clip_999")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_top_performing_clips(self):
        client = self._get_client()
        with patch("src.repositories.campaign_repository.CampaignRepository.get_top_clips",
                   return_value=[{"clip_id": "top1", "views": 10000}]):
            resp = client.get("/campaigns/leaderboard/top?metric=views&limit=5")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["clips"]), 1)

    def test_top_performing_clips_invalid_metric(self):
        client = self._get_client()
        resp = client.get("/campaigns/leaderboard/top?metric=invalid_metric")
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# 4. Task model feature flag tests
# ---------------------------------------------------------------------------

class TestTaskModelFeatureFlags(unittest.TestCase):
    def test_enable_timeline_attribute_exists(self):
        """Task ORM model must have enable_timeline mapped column."""
        from src.models import Task
        self.assertTrue(hasattr(Task, "enable_timeline"))

    def test_enable_vision_ai_attribute_exists(self):
        from src.models import Task
        self.assertTrue(hasattr(Task, "enable_vision_ai"))

    def test_enable_timeline_render_attribute_exists(self):
        from src.models import Task
        self.assertTrue(hasattr(Task, "enable_timeline_render"))

    def test_migration_file_exists(self):
        """SQL migration file for task feature flags must exist."""
        from pathlib import Path
        for candidate in [
            Path("src/migrations/sql/20260405_0002_task_feature_flags.sql"),
            Path("/app/src/migrations/sql/20260405_0002_task_feature_flags.sql"),
            Path("backend/src/migrations/sql/20260405_0002_task_feature_flags.sql"),
        ]:
            if candidate.exists():
                return
        self.fail("Migration 20260405_0002_task_feature_flags.sql not found")

    def test_migration_contains_columns(self):
        """Migration SQL must ADD the three columns."""
        from pathlib import Path
        sql = ""
        for candidate in [
            Path("src/migrations/sql/20260405_0002_task_feature_flags.sql"),
            Path("/app/src/migrations/sql/20260405_0002_task_feature_flags.sql"),
            Path("backend/src/migrations/sql/20260405_0002_task_feature_flags.sql"),
        ]:
            if candidate.exists():
                sql = candidate.read_text()
                break
        self.assertNotEqual(sql, "", "Migration file not found")
        self.assertIn("enable_timeline", sql)
        self.assertIn("enable_vision_ai", sql)
        self.assertIn("enable_timeline_render", sql)


if __name__ == "__main__":
    unittest.main()
