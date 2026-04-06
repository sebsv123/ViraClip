"""
Phase 26 — Clip Collections, AI Summary & Clip Comparison Tests

Covers:
  - clip_collection_service: create/get/list/delete/add_clip/remove_clip
  - ai_summary_service: extract_keywords, generate_summary, get_or_generate, clear
  - clip_comparison_service: compare_metrics, compare_clips_from_redis
  - collections_summary_compare API routes
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLIP COLLECTION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipCollectionService(unittest.TestCase):
    def _mock_redis(self, scard=0, hgetall=None, smembers=None,
                   sadd=1, srem=1, delete=1):
        r = MagicMock()
        r.scard = AsyncMock(return_value=scard)
        r.hset = AsyncMock(return_value=1)
        r.sadd = AsyncMock(return_value=sadd)
        r.hgetall = AsyncMock(return_value=hgetall or {})
        r.smembers = AsyncMock(return_value=smembers or set())
        r.srem = AsyncMock(return_value=srem)
        r.delete = AsyncMock(return_value=delete)
        return r

    def test_create_collection(self):
        from src.services.clip_collection_service import create_collection
        r = self._mock_redis(scard=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(create_collection("u1", "Favorites"))
        self.assertEqual(result["name"], "Favorites")
        self.assertIn("collection_id", result)

    def test_create_collection_raises_at_max(self):
        from src.services.clip_collection_service import create_collection, _MAX_COLLECTIONS
        r = self._mock_redis(scard=_MAX_COLLECTIONS)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(create_collection("u1", "Overflow"))

    def test_get_collection_returns_none_when_missing(self):
        from src.services.clip_collection_service import get_collection
        r = self._mock_redis(hgetall={})
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_collection("u1", "no-such-id"))
        self.assertIsNone(result)

    def test_get_collection_returns_clips(self):
        from src.services.clip_collection_service import get_collection
        meta = {b"collection_id": b"col1", b"user_id": b"u1",
                b"name": b"Faves", b"description": b"",
                b"created_at": b"t", b"updated_at": b"t"}
        r = self._mock_redis(hgetall=meta, smembers={b"c1", b"c2"}, scard=2)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_collection("u1", "col1"))
        self.assertEqual(result["name"], "Faves")
        self.assertEqual(result["clip_count"], 2)

    def test_add_clip_raises_at_max(self):
        from src.services.clip_collection_service import add_clip_to_collection, _MAX_CLIPS
        r = self._mock_redis(scard=_MAX_CLIPS)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(add_clip_to_collection("u1", "col1", "c99"))

    def test_remove_clip_from_collection(self):
        from src.services.clip_collection_service import remove_clip_from_collection
        r = self._mock_redis(srem=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(remove_clip_from_collection("u1", "col1", "c1"))
        self.assertTrue(result)

    def test_delete_collection(self):
        from src.services.clip_collection_service import delete_collection
        r = self._mock_redis(delete=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_collection("u1", "col1"))
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# 2. AI SUMMARY SERVICE
# ═══════════════════════════════════════════════════════════════════════════

_SAMPLE_TEXT = (
    "The fox jumps quickly over the lazy brown dog. "
    "The dog barks loudly at the fox. "
    "The fox runs away into the forest."
)


class TestAiSummaryService(unittest.TestCase):
    def test_extract_keywords_returns_list(self):
        from src.services.ai_summary_service import extract_keywords
        kws = extract_keywords(_SAMPLE_TEXT)
        self.assertIsInstance(kws, list)
        self.assertGreater(len(kws), 0)
        # "fox" appears most so should be near top
        self.assertIn("fox", kws)

    def test_extract_keywords_filters_stop_words(self):
        from src.services.ai_summary_service import extract_keywords
        kws = extract_keywords("The quick brown fox")
        self.assertNotIn("the", kws)

    def test_generate_summary_returns_string(self):
        from src.services.ai_summary_service import generate_summary
        summary = generate_summary(_SAMPLE_TEXT)
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)

    def test_generate_summary_short_text(self):
        from src.services.ai_summary_service import generate_summary
        text = "Short text."
        result = generate_summary(text)
        self.assertEqual(result, "Short text.")

    def test_get_or_generate_uses_cache(self):
        from src.services.ai_summary_service import get_or_generate_summary
        cached = {"clip_id": "c1", "summary": "cached!",
                  "keywords": ["fox"], "word_count": 5, "generated_at": "t"}
        with patch("src.services.ai_summary_service._get_cached",
                   new=AsyncMock(return_value=cached)), \
             patch("src.services.ai_summary_service._set_cached",
                   new=AsyncMock()):
            result = run(get_or_generate_summary("c1", _SAMPLE_TEXT))
        self.assertEqual(result["summary"], "cached!")

    def test_get_or_generate_computes_fresh(self):
        from src.services.ai_summary_service import get_or_generate_summary
        with patch("src.services.ai_summary_service._get_cached",
                   new=AsyncMock(return_value=None)), \
             patch("src.services.ai_summary_service._set_cached",
                   new=AsyncMock()):
            result = run(get_or_generate_summary("c1", _SAMPLE_TEXT))
        self.assertIn("keywords", result)
        self.assertIn("summary", result)
        self.assertGreater(result["word_count"], 0)

    def test_clear_summary_cache(self):
        from src.services.ai_summary_service import clear_summary_cache
        r = MagicMock()
        r.delete = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            run(clear_summary_cache("c1"))
        r.delete.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# 3. CLIP COMPARISON SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipComparisonService(unittest.TestCase):
    def test_compare_metrics_winner_a(self):
        from src.services.clip_comparison_service import compare_metrics
        result = compare_metrics(
            "c1", "c2",
            {"viral_score": 80.0, "hook_score": 75.0},
            {"viral_score": 60.0, "hook_score": 65.0},
        )
        self.assertEqual(result["overall_winner"], "a")
        self.assertEqual(result["wins_a"], 2)
        self.assertEqual(result["wins_b"], 0)

    def test_compare_metrics_winner_b(self):
        from src.services.clip_comparison_service import compare_metrics
        result = compare_metrics(
            "c1", "c2",
            {"viral_score": 40.0},
            {"viral_score": 90.0},
        )
        self.assertEqual(result["overall_winner"], "b")
        self.assertEqual(result["metrics"]["viral_score"]["winner"], "b")

    def test_compare_metrics_tie(self):
        from src.services.clip_comparison_service import compare_metrics
        result = compare_metrics(
            "c1", "c2",
            {"viral_score": 70.0},
            {"viral_score": 70.0},
        )
        self.assertEqual(result["overall_winner"], "tie")
        self.assertEqual(result["metrics"]["viral_score"]["diff"], 0.0)

    def test_compare_metrics_asymmetric_keys(self):
        from src.services.clip_comparison_service import compare_metrics
        result = compare_metrics(
            "c1", "c2",
            {"viral_score": 80.0, "views": 1000},
            {"viral_score": 60.0},
        )
        self.assertIn("viral_score", result["metrics"])
        self.assertIn("views", result["metrics"])
        self.assertIsNone(result["metrics"]["views"]["b"])

    def test_compare_clips_from_redis(self):
        from src.services.clip_comparison_service import compare_clips_from_redis
        r = MagicMock()
        r.hgetall = AsyncMock(side_effect=[
            {b"viral_score": b"85.0"},
            {b"viral_score": b"55.0"},
        ])
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(compare_clips_from_redis("c1", "c2"))
        self.assertEqual(result["overall_winner"], "a")


# ═══════════════════════════════════════════════════════════════════════════
# 4. API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_p26_app():
    from fastapi import FastAPI
    from src.api.routes.collections_summary_compare import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestCollectionsSummaryCompareApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_p26_app())

    # Collection tests
    def test_create_collection_200(self):
        col = {"collection_id": "col1", "user_id": "u1",
               "name": "Faves", "description": "",
               "created_at": "t", "updated_at": "t", "clip_count": 0}
        with patch("src.services.clip_collection_service.create_collection",
                   new=AsyncMock(return_value=col)):
            resp = self.client.post("/collections/u1",
                                    json={"name": "Faves"})
        self.assertEqual(resp.status_code, 200)

    def test_create_collection_400_on_overflow(self):
        with patch("src.services.clip_collection_service.create_collection",
                   new=AsyncMock(side_effect=ValueError("max collections"))):
            resp = self.client.post("/collections/u1", json={"name": "X"})
        self.assertEqual(resp.status_code, 400)

    def test_get_collection_404(self):
        with patch("src.services.clip_collection_service.get_collection",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/collections/u1/col-nope")
        self.assertEqual(resp.status_code, 404)

    def test_delete_collection_404(self):
        with patch("src.services.clip_collection_service.delete_collection",
                   new=AsyncMock(return_value=False)):
            resp = self.client.delete("/collections/u1/col-nope")
        self.assertEqual(resp.status_code, 404)

    # AI summary tests
    def test_generate_summary_200(self):
        result = {"clip_id": "c1", "summary": "Fox runs.",
                  "keywords": ["fox"], "word_count": 10, "generated_at": "t"}
        with patch("src.services.ai_summary_service.get_or_generate_summary",
                   new=AsyncMock(return_value=result)):
            resp = self.client.post("/clips/c1/summary",
                                    json={"transcript": "The fox runs."})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["summary"], "Fox runs.")

    def test_clear_summary_200(self):
        with patch("src.services.ai_summary_service.clear_summary_cache",
                   new=AsyncMock(return_value=None)):
            resp = self.client.delete("/clips/c1/summary")
        self.assertEqual(resp.status_code, 200)

    # Comparison tests
    def test_compare_clips_inline(self):
        result = {"clip_a": "c1", "clip_b": "c2",
                  "metrics": {"viral_score": {"a": 80.0, "b": 60.0,
                                              "diff": 20.0, "winner": "a"}},
                  "overall_winner": "a", "wins_a": 1, "wins_b": 0}
        with patch("src.services.clip_comparison_service.compare_metrics",
                   return_value=result):
            resp = self.client.post("/clips/compare", json={
                "clip_a_id": "c1", "clip_b_id": "c2",
                "metrics_a": {"viral_score": 80.0},
                "metrics_b": {"viral_score": 60.0},
                "use_redis": False,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["overall_winner"], "a")


if __name__ == "__main__":
    unittest.main()
