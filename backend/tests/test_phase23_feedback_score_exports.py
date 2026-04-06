"""
Phase 23 — Clip Score Override, Feedback Aggregation & Export History Tests

Covers:
  - clip_score_override_service: set/get/delete/resolve
  - feedback_aggregation_service: submit_thumbs/submit_rating/get_stats/get_user
  - clip_export_history_service: record/update/get/stats
  - clip_feedback_score API routes
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLIP SCORE OVERRIDE SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipScoreOverrideService(unittest.TestCase):
    def _mock_redis(self, hgetall=None, delete=1):
        r = MagicMock()
        r.hset = AsyncMock(return_value=1)
        r.hgetall = AsyncMock(return_value=hgetall or {})
        r.delete = AsyncMock(return_value=delete)
        return r

    def test_set_score_override_stores_fields(self):
        from src.services.clip_score_override_service import set_score_override
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(set_score_override("c1", 85.0, author="admin", reason="manual fix"))
        self.assertEqual(result["score"], 85.0)
        self.assertEqual(result["author"], "admin")
        r.hset.assert_awaited_once()

    def test_set_score_override_raises_on_out_of_range(self):
        from src.services.clip_score_override_service import set_score_override
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(set_score_override("c1", 150.0))

    def test_get_score_override_returns_dict(self):
        from src.services.clip_score_override_service import get_score_override
        hgetall = {b"clip_id": b"c1", b"score": b"85.0", b"author": b"admin",
                   b"reason": b"test", b"original_score": b"70.0", b"created_at": b"t"}
        r = self._mock_redis(hgetall=hgetall)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_score_override("c1"))
        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 85.0)
        self.assertEqual(result["original_score"], 70.0)

    def test_get_score_override_returns_none_when_empty(self):
        from src.services.clip_score_override_service import get_score_override
        r = self._mock_redis(hgetall={})
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_score_override("c1"))
        self.assertIsNone(result)

    def test_delete_score_override(self):
        from src.services.clip_score_override_service import delete_score_override
        r = self._mock_redis(delete=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_score_override("c1"))
        self.assertTrue(result)

    def test_resolve_score_uses_override(self):
        from src.services.clip_score_override_service import resolve_score
        override = {"clip_id": "c1", "score": 90.0, "author": "u", "reason": "",
                    "original_score": None, "created_at": "t"}
        with patch("src.services.clip_score_override_service.get_score_override",
                   new=AsyncMock(return_value=override)):
            result = run(resolve_score("c1", 50.0))
        self.assertTrue(result["overridden"])
        self.assertEqual(result["effective_score"], 90.0)

    def test_resolve_score_falls_back_to_computed(self):
        from src.services.clip_score_override_service import resolve_score
        with patch("src.services.clip_score_override_service.get_score_override",
                   new=AsyncMock(return_value=None)):
            result = run(resolve_score("c1", 60.0))
        self.assertFalse(result["overridden"])
        self.assertEqual(result["effective_score"], 60.0)


# ═══════════════════════════════════════════════════════════════════════════
# 2. FEEDBACK AGGREGATION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_feedback_redis(prev_thumbs=None, prev_rating=None, hgetall=None):
    r = MagicMock()
    pipe = MagicMock()
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.hset = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, 1, 1])
    r.pipeline = MagicMock(return_value=pipe)
    r.hget = AsyncMock(side_effect=[
        prev_thumbs.encode() if prev_thumbs else None,
        prev_rating.encode() if prev_rating else None,
    ])
    r.hgetall = AsyncMock(return_value=hgetall or {
        b"thumbs_up": b"2", b"thumbs_down": b"1",
        b"rating_sum": b"12", b"rating_count": b"3"
    })
    return r


class TestFeedbackAggregationService(unittest.TestCase):
    def test_submit_thumbs_up(self):
        from src.services.feedback_aggregation_service import submit_thumbs
        r = _make_feedback_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(submit_thumbs("c1", "u1", "thumbs_up"))
        self.assertIn("thumbs_up", result)

    def test_submit_thumbs_invalid_vote(self):
        from src.services.feedback_aggregation_service import submit_thumbs
        r = _make_feedback_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(submit_thumbs("c1", "u1", "invalid"))

    def test_submit_rating_valid(self):
        from src.services.feedback_aggregation_service import submit_rating
        r = _make_feedback_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(submit_rating("c1", "u1", 4))
        self.assertIn("avg_rating", result)

    def test_submit_rating_invalid(self):
        from src.services.feedback_aggregation_service import submit_rating
        r = _make_feedback_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(submit_rating("c1", "u1", 10))

    def test_get_feedback_stats_calculates_avg(self):
        from src.services.feedback_aggregation_service import get_feedback_stats
        r = MagicMock()
        r.hgetall = AsyncMock(return_value={
            b"thumbs_up": b"5", b"thumbs_down": b"2",
            b"rating_sum": b"20", b"rating_count": b"5"
        })
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_feedback_stats("c1"))
        self.assertEqual(result["thumbs_up"], 5)
        self.assertEqual(result["avg_rating"], 4.0)

    def test_get_user_feedback(self):
        from src.services.feedback_aggregation_service import get_user_feedback
        r = MagicMock()
        r.hget = AsyncMock(side_effect=[b"thumbs_up", b"4"])
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_user_feedback("c1", "u1"))
        self.assertEqual(result["thumbs"], "thumbs_up")
        self.assertEqual(result["rating"], 4)


# ═══════════════════════════════════════════════════════════════════════════
# 3. CLIP EXPORT HISTORY SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_export_entry(export_id="ex1", status="pending"):
    return json.dumps({
        "export_id": export_id, "user_id": "u1",
        "clip_ids": ["c1", "c2"], "clip_count": 2,
        "format": "zip", "status": status,
        "file_path": None, "file_size_bytes": None,
        "created_at": "t", "completed_at": None,
    }).encode()


class TestClipExportHistoryService(unittest.TestCase):
    def _mock_redis(self, items=None):
        r = MagicMock()
        r.lpush = AsyncMock(return_value=1)
        r.ltrim = AsyncMock(return_value=True)
        r.expire = AsyncMock(return_value=True)
        r.lrange = AsyncMock(return_value=items or [])
        r.lset = AsyncMock(return_value=True)
        return r

    def test_record_export_returns_entry(self):
        from src.services.clip_export_history_service import record_export
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(record_export("u1", ["c1", "c2"], fmt="zip"))
        self.assertEqual(result["format"], "zip")
        self.assertEqual(result["clip_count"], 2)
        self.assertIn("export_id", result)

    def test_get_export_history(self):
        from src.services.clip_export_history_service import get_export_history
        items = [_make_export_entry("ex1", "completed"),
                 _make_export_entry("ex2", "failed")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_export_history("u1"))
        self.assertEqual(len(result), 2)

    def test_get_export_history_status_filter(self):
        from src.services.clip_export_history_service import get_export_history
        items = [_make_export_entry("ex1", "completed"),
                 _make_export_entry("ex2", "failed")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_export_history("u1", status_filter="completed"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "completed")

    def test_update_export_status(self):
        from src.services.clip_export_history_service import update_export_status
        items = [_make_export_entry("ex1", "pending")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(update_export_status("u1", "ex1", "completed",
                                              file_path="/tmp/out.zip"))
        self.assertTrue(result)

    def test_get_export_stats(self):
        from src.services.clip_export_history_service import get_export_stats
        items = [_make_export_entry("ex1", "completed"),
                 _make_export_entry("ex2", "failed"),
                 _make_export_entry("ex3", "pending")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_export_stats("u1"))
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["total_clips_exported"], 6)


# ═══════════════════════════════════════════════════════════════════════════
# 4. CLIP FEEDBACK SCORE API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_p23_app():
    from fastapi import FastAPI
    from src.api.routes.clip_feedback_score import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestClipFeedbackScoreApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_p23_app())

    # Score override tests
    def test_set_score_override_200(self):
        override = {"clip_id": "c1", "score": 90.0, "author": "admin",
                    "reason": "test", "original_score": None, "created_at": "t"}
        with patch("src.services.clip_score_override_service.set_score_override",
                   new=AsyncMock(return_value=override)):
            resp = self.client.put("/clips/c1/score-override",
                                   json={"score": 90.0, "author": "admin"})
        self.assertEqual(resp.status_code, 200)

    def test_set_score_override_400_on_invalid(self):
        with patch("src.services.clip_score_override_service.set_score_override",
                   new=AsyncMock(side_effect=ValueError("out of range"))):
            resp = self.client.put("/clips/c1/score-override", json={"score": 999.0})
        self.assertEqual(resp.status_code, 400)

    def test_get_score_override_404(self):
        with patch("src.services.clip_score_override_service.get_score_override",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/clips/c1/score-override")
        self.assertEqual(resp.status_code, 404)

    def test_delete_score_override_404(self):
        with patch("src.services.clip_score_override_service.delete_score_override",
                   new=AsyncMock(return_value=False)):
            resp = self.client.delete("/clips/c1/score-override")
        self.assertEqual(resp.status_code, 404)

    def test_effective_score(self):
        result = {"clip_id": "c1", "effective_score": 85.0,
                  "overridden": True, "override": {}}
        with patch("src.services.clip_score_override_service.resolve_score",
                   new=AsyncMock(return_value=result)):
            resp = self.client.get("/clips/c1/effective-score?computed_score=50.0")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["effective_score"], 85.0)

    # Feedback tests
    def test_submit_thumbs_200(self):
        stats = {"clip_id": "c1", "thumbs_up": 1, "thumbs_down": 0,
                 "rating_count": 0, "avg_rating": None}
        with patch("src.services.feedback_aggregation_service.submit_thumbs",
                   new=AsyncMock(return_value=stats)):
            resp = self.client.post("/clips/c1/feedback/thumbs",
                                    json={"user_id": "u1", "vote": "thumbs_up"})
        self.assertEqual(resp.status_code, 200)

    def test_submit_thumbs_400_invalid(self):
        with patch("src.services.feedback_aggregation_service.submit_thumbs",
                   new=AsyncMock(side_effect=ValueError("invalid vote"))):
            resp = self.client.post("/clips/c1/feedback/thumbs",
                                    json={"user_id": "u1", "vote": "bad"})
        self.assertEqual(resp.status_code, 400)

    def test_submit_rating_200(self):
        stats = {"clip_id": "c1", "thumbs_up": 0, "thumbs_down": 0,
                 "rating_count": 1, "avg_rating": 4.0}
        with patch("src.services.feedback_aggregation_service.submit_rating",
                   new=AsyncMock(return_value=stats)):
            resp = self.client.post("/clips/c1/feedback/rating",
                                    json={"user_id": "u1", "rating": 4})
        self.assertEqual(resp.status_code, 200)

    def test_get_feedback_stats(self):
        stats = {"clip_id": "c1", "thumbs_up": 5, "thumbs_down": 2,
                 "rating_count": 3, "avg_rating": 4.0}
        with patch("src.services.feedback_aggregation_service.get_feedback_stats",
                   new=AsyncMock(return_value=stats)):
            resp = self.client.get("/clips/c1/feedback")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["thumbs_up"], 5)

    # Export history tests
    def test_record_export_200(self):
        record = {"export_id": "ex1", "user_id": "u1",
                  "clip_ids": ["c1"], "clip_count": 1, "format": "zip",
                  "status": "pending", "file_path": None,
                  "file_size_bytes": None, "created_at": "t", "completed_at": None}
        with patch("src.services.clip_export_history_service.record_export",
                   new=AsyncMock(return_value=record)):
            resp = self.client.post("/exports/u1",
                                    json={"clip_ids": ["c1"], "format": "zip"})
        self.assertEqual(resp.status_code, 200)

    def test_get_export_history(self):
        with patch("src.services.clip_export_history_service.get_export_history",
                   new=AsyncMock(return_value=[])):
            resp = self.client.get("/exports/u1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_update_export_status_404(self):
        with patch("src.services.clip_export_history_service.update_export_status",
                   new=AsyncMock(return_value=False)):
            resp = self.client.patch("/exports/u1/ex-nope",
                                     json={"status": "completed"})
        self.assertEqual(resp.status_code, 404)

    def test_export_stats(self):
        stats = {"total": 3, "completed": 2, "failed": 0,
                 "pending": 1, "total_clips_exported": 6}
        with patch("src.services.clip_export_history_service.get_export_stats",
                   new=AsyncMock(return_value=stats)):
            resp = self.client.get("/exports/u1/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)


if __name__ == "__main__":
    unittest.main()
