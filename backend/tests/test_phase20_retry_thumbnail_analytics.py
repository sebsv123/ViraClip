"""
Phase 20 — Task Retry, Clip Thumbnail & Usage Analytics Tests

Covers:
  - task_retry_service: retry_task, get_retry_info
  - clip_thumbnail_service: extract_thumbnail, delete_thumbnail
  - usage_analytics_service: record_usage, get_daily_usage, get_total_usage, get_usage_summary
  - task_retry API routes: POST /tasks/{id}/retry, GET /tasks/{id}/retry-info
  - usage_analytics API routes: /usage/*, /clips/{id}/thumbnail
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. TASK RETRY SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskRetryService(unittest.TestCase):
    def _mock_redis(self, count=0):
        redis = MagicMock()
        redis.get = AsyncMock(return_value=str(count).encode() if count else None)
        redis.incr = AsyncMock(return_value=count + 1)
        redis.expire = AsyncMock(return_value=True)
        return redis

    def _patch_repo(self, task=None):
        """Context manager that patches TaskRepository + AsyncSessionLocal."""
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        return (
            patch("src.database.AsyncSessionLocal", return_value=mock_db),
            patch("src.repositories.task_repository.TaskRepository.get_task_by_id",
                  new=AsyncMock(return_value=task)),
            patch("src.repositories.task_repository.TaskRepository.update_task_status",
                  new=AsyncMock(return_value=None)),
        )

    def test_retry_not_found(self):
        from src.services.task_retry_service import retry_task
        p1, p2, p3 = self._patch_repo(task=None)
        with p1, p2, p3:
            result = run(retry_task("t999"))
        self.assertEqual(result["status"], "not_found")

    def test_retry_already_pending(self):
        from src.services.task_retry_service import retry_task
        p1, p2, p3 = self._patch_repo(task={"status": "pending"})
        with p1, p2, p3, \
             patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=self._mock_redis(0))
            result = run(retry_task("t1"))
        self.assertEqual(result["status"], "already_pending")

    def test_retry_not_failed(self):
        from src.services.task_retry_service import retry_task
        p1, p2, p3 = self._patch_repo(task={"status": "completed"})
        with p1, p2, p3, \
             patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=self._mock_redis(0))
            result = run(retry_task("t1"))
        self.assertEqual(result["status"], "not_failed")

    def test_retry_max_retries_exceeded(self):
        from src.services.task_retry_service import retry_task, _MAX_RETRIES
        p1, p2, p3 = self._patch_repo(task={"status": "failed"})
        with p1, p2, p3, \
             patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=self._mock_redis(_MAX_RETRIES))
            result = run(retry_task("t1"))
        self.assertEqual(result["status"], "max_retries_exceeded")

    def test_retry_success(self):
        from src.services.task_retry_service import retry_task
        redis = self._mock_redis(0)
        mock_jq_instance = MagicMock()
        mock_jq_instance.enqueue_job = AsyncMock(return_value=None)
        p1, p2, p3 = self._patch_repo(task={"status": "failed"})
        with p1, p2, p3, \
             patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            jq.return_value = mock_jq_instance
            result = run(retry_task("t1"))
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["retry_count"], 1)

    def test_get_retry_info(self):
        from src.services.task_retry_service import get_retry_info, _MAX_RETRIES
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=self._mock_redis(1))
            result = run(get_retry_info("t1"))
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["max_retries"], _MAX_RETRIES)
        self.assertEqual(result["retries_remaining"], _MAX_RETRIES - 1)


# ═══════════════════════════════════════════════════════════════════════════
# 2. CLIP THUMBNAIL SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipThumbnailService(unittest.TestCase):
    def test_extract_thumbnail_returns_path_on_success(self):
        from src.services.clip_thumbnail_service import extract_thumbnail
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / "c1_1.00.jpg")
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            with patch("asyncio.create_subprocess_exec",
                       new=AsyncMock(return_value=mock_proc)), \
                 patch("src.services.clip_thumbnail_service._THUMB_DIR", tmpdir), \
                 patch("src.services.clip_thumbnail_service._get_cached",
                       new=AsyncMock(return_value=None)), \
                 patch("src.services.clip_thumbnail_service._set_cached",
                       new=AsyncMock(return_value=None)):
                result = run(extract_thumbnail("/fake/clip.mp4", "c1", timestamp=1.0))
        self.assertIsNotNone(result)
        self.assertIn("c1", result)

    def test_extract_thumbnail_returns_none_on_ffmpeg_failure(self):
        from src.services.clip_thumbnail_service import extract_thumbnail
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Error"))
            with patch("asyncio.create_subprocess_exec",
                       new=AsyncMock(return_value=mock_proc)), \
                 patch("src.services.clip_thumbnail_service._THUMB_DIR", tmpdir), \
                 patch("src.services.clip_thumbnail_service._get_cached",
                       new=AsyncMock(return_value=None)), \
                 patch("src.services.clip_thumbnail_service._set_cached",
                       new=AsyncMock(return_value=None)):
                result = run(extract_thumbnail("/fake/clip.mp4", "c1"))
        self.assertIsNone(result)

    def test_extract_thumbnail_uses_cache(self):
        from src.services.clip_thumbnail_service import extract_thumbnail
        cached_path = "/app/storage/thumbnails/c1_1.00.jpg"
        with patch("src.services.clip_thumbnail_service._get_cached",
                   new=AsyncMock(return_value=cached_path)), \
             patch("pathlib.Path.exists", return_value=True):
            result = run(extract_thumbnail("/fake/clip.mp4", "c1", timestamp=1.0))
        self.assertEqual(result, cached_path)

    def test_delete_thumbnail_removes_files(self):
        from src.services.clip_thumbnail_service import delete_thumbnail
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "c1_1.00.jpg"
            f.write_bytes(b"fake")
            with patch("src.services.clip_thumbnail_service._THUMB_DIR", tmpdir):
                count = run(delete_thumbnail("c1", timestamp=1.0))
        self.assertEqual(count, 1)


# ═══════════════════════════════════════════════════════════════════════════
# 3. USAGE ANALYTICS SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_pipe_mock():
    pipe = MagicMock()
    pipe.incr = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, True, 1])
    return pipe


class TestUsageAnalyticsService(unittest.TestCase):
    def test_record_usage(self):
        from src.services.usage_analytics_service import record_usage
        redis = MagicMock()
        pipe = _make_pipe_mock()
        redis.pipeline = MagicMock(return_value=pipe)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            run(record_usage("u1", "ingest", count=1))
        pipe.execute.assert_awaited_once()

    def test_record_usage_fails_open(self):
        from src.services.usage_analytics_service import record_usage
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(side_effect=Exception("Redis down"))
            run(record_usage("u1", "ingest"))

    def test_get_daily_usage_by_endpoint(self):
        from src.services.usage_analytics_service import get_daily_usage
        redis = MagicMock()
        redis.get = AsyncMock(return_value=b"5")
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(get_daily_usage("u1", endpoint="ingest", days=3))
        self.assertEqual(len(result), 3)
        for entry in result:
            self.assertEqual(entry["count"], 5)
            self.assertEqual(entry["endpoint"], "ingest")

    def test_get_daily_usage_all_endpoints(self):
        from src.services.usage_analytics_service import get_daily_usage
        redis = MagicMock()
        redis.keys = AsyncMock(return_value=[b"usage:u1:2026-01-01:ingest"])
        redis.get = AsyncMock(return_value=b"3")
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(get_daily_usage("u1", days=1))
        self.assertEqual(len(result), 1)
        self.assertIn("total", result[0])

    def test_get_total_usage(self):
        from src.services.usage_analytics_service import get_total_usage
        redis = MagicMock()
        redis.keys = AsyncMock(return_value=[
            b"usage_total:u1:ingest", b"usage_total:u1:autopilot"
        ])
        redis.get = AsyncMock(return_value=b"10")
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(get_total_usage("u1"))
        self.assertIn("ingest", result)
        self.assertIn("autopilot", result)
        self.assertEqual(result["ingest"], 10)

    def test_get_usage_summary(self):
        from src.services.usage_analytics_service import get_usage_summary
        with patch("src.services.usage_analytics_service.get_daily_usage",
                   new=AsyncMock(return_value=[])), \
             patch("src.services.usage_analytics_service.get_total_usage",
                   new=AsyncMock(return_value={"ingest": 5})):
            result = run(get_usage_summary("u1", days=7))
        self.assertEqual(result["grand_total"], 5)
        self.assertEqual(result["user_id"], "u1")


# ═══════════════════════════════════════════════════════════════════════════
# 4. TASK RETRY API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_retry_app():
    from fastapi import FastAPI
    from src.api.routes.task_retry import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestTaskRetryApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_retry_app())

    def test_retry_404_not_found(self):
        with patch("src.services.task_retry_service.retry_task",
                   new=AsyncMock(return_value={"status": "not_found",
                                               "task_id": "t999", "message": "not found",
                                               "retry_count": 0})):
            resp = self.client.post("/tasks/t999/retry")
        self.assertEqual(resp.status_code, 404)

    def test_retry_429_max_retries(self):
        with patch("src.services.task_retry_service.retry_task",
                   new=AsyncMock(return_value={"status": "max_retries_exceeded",
                                               "task_id": "t1", "message": "max",
                                               "retry_count": 3})):
            resp = self.client.post("/tasks/t1/retry")
        self.assertEqual(resp.status_code, 429)

    def test_retry_409_not_failed(self):
        with patch("src.services.task_retry_service.retry_task",
                   new=AsyncMock(return_value={"status": "not_failed",
                                               "task_id": "t1", "message": "completed",
                                               "retry_count": 0})):
            resp = self.client.post("/tasks/t1/retry")
        self.assertEqual(resp.status_code, 409)

    def test_retry_200_queued(self):
        with patch("src.services.task_retry_service.retry_task",
                   new=AsyncMock(return_value={"status": "queued",
                                               "task_id": "t1", "message": "queued",
                                               "retry_count": 1})):
            resp = self.client.post("/tasks/t1/retry")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "queued")

    def test_retry_info(self):
        with patch("src.services.task_retry_service.get_retry_info",
                   new=AsyncMock(return_value={"task_id": "t1", "retry_count": 1,
                                               "max_retries": 3, "retries_remaining": 2})):
            resp = self.client.get("/tasks/t1/retry-info")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["retries_remaining"], 2)


# ═══════════════════════════════════════════════════════════════════════════
# 5. USAGE ANALYTICS API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_usage_app():
    from fastapi import FastAPI
    from src.api.routes.usage_analytics import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestUsageAnalyticsApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_usage_app())

    def test_summary_endpoint(self):
        mock_summary = {"user_id": "u1", "period_days": 7,
                        "grand_total": 20, "totals_by_endpoint": {}, "daily": []}
        with patch("src.services.usage_analytics_service.get_usage_summary",
                   new=AsyncMock(return_value=mock_summary)):
            resp = self.client.get("/usage/u1/summary")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["grand_total"], 20)

    def test_daily_endpoint(self):
        with patch("src.services.usage_analytics_service.get_daily_usage",
                   new=AsyncMock(return_value=[])):
            resp = self.client.get("/usage/u1/daily?days=3")
        self.assertEqual(resp.status_code, 200)

    def test_totals_endpoint(self):
        with patch("src.services.usage_analytics_service.get_total_usage",
                   new=AsyncMock(return_value={"ingest": 5})):
            resp = self.client.get("/usage/u1/totals")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["grand_total"], 5)

    def test_record_usage_event(self):
        with patch("src.services.usage_analytics_service.record_usage",
                   new=AsyncMock(return_value=None)):
            resp = self.client.post("/usage/u1/record",
                                    json={"endpoint": "ingest", "count": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["recorded"])

    def test_thumbnail_endpoint_success(self):
        with patch("src.services.clip_thumbnail_service.extract_thumbnail",
                   new=AsyncMock(return_value="/app/storage/thumbnails/c1_1.00.jpg")):
            resp = self.client.get(
                "/clips/c1/thumbnail?clip_path=/fake/clip.mp4&timestamp=1.0")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("thumbnail_path", resp.json())

    def test_thumbnail_endpoint_500_on_failure(self):
        with patch("src.services.clip_thumbnail_service.extract_thumbnail",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get(
                "/clips/c1/thumbnail?clip_path=/fake/clip.mp4")
        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
