"""
Phase 17 — Rate Limiting Extensions + Scheduled Publish Tests

Covers:
  - rate_limit.py: new ingest + autopilot limits in DEFAULT_LIMITS
  - ingest_rate_limit_dependency + autopilot_rate_limit_dependency
  - scheduled_publish_service: schedule, list, cancel, execute_now, execute_due_jobs
  - scheduled_publish API routes: schedule, list, cancel, publish-now, execute-due
"""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. RATE LIMIT — DEFAULT_LIMITS entries
# ═══════════════════════════════════════════════════════════════════════════

class TestRateLimitDefaults(unittest.TestCase):
    def test_ingest_limit_exists(self):
        from src.api.middleware.rate_limit import DEFAULT_LIMITS
        self.assertIn("ingest", DEFAULT_LIMITS)
        cfg = DEFAULT_LIMITS["ingest"]
        self.assertGreater(cfg["requests"], 0)
        self.assertEqual(cfg["window"], 3600)

    def test_autopilot_limit_exists(self):
        from src.api.middleware.rate_limit import DEFAULT_LIMITS
        self.assertIn("autopilot", DEFAULT_LIMITS)
        cfg = DEFAULT_LIMITS["autopilot"]
        self.assertGreater(cfg["requests"], 0)
        self.assertEqual(cfg["window"], 3600)

    def test_ingest_dependency_exported(self):
        from src.api.middleware.rate_limit import ingest_rate_limit_dependency
        self.assertTrue(callable(ingest_rate_limit_dependency))

    def test_autopilot_dependency_exported(self):
        from src.api.middleware.rate_limit import autopilot_rate_limit_dependency
        self.assertTrue(callable(autopilot_rate_limit_dependency))

    def test_ingest_dependency_in_all(self):
        from src.api.middleware import rate_limit as rl
        self.assertIn("ingest_rate_limit_dependency", rl.__all__)

    def test_autopilot_dependency_in_all(self):
        from src.api.middleware import rate_limit as rl
        self.assertIn("autopilot_rate_limit_dependency", rl.__all__)


class TestIngestRateLimitDependency(unittest.TestCase):
    def _make_mock_request(self, user_id="u1"):
        req = MagicMock()
        req.headers = {"x-viraclip-user-id": user_id}
        req.query_params = {}
        req.client = MagicMock()
        req.client.host = "127.0.0.1"
        return req

    def test_allows_when_under_limit(self):
        from src.api.middleware.rate_limit import ingest_rate_limit_dependency
        req = self._make_mock_request()
        with patch("src.api.middleware.rate_limit.check_rate_limit",
                   new=AsyncMock(return_value=(True, 1, 0))):
            run(ingest_rate_limit_dependency(req))

    def test_raises_429_when_exceeded(self):
        from src.api.middleware.rate_limit import ingest_rate_limit_dependency, RateLimitExceeded
        req = self._make_mock_request()
        with patch("src.api.middleware.rate_limit.check_rate_limit",
                   new=AsyncMock(return_value=(False, 11, 3590))):
            with self.assertRaises(RateLimitExceeded):
                run(ingest_rate_limit_dependency(req))

    def test_uses_ingest_endpoint_type(self):
        from src.api.middleware.rate_limit import ingest_rate_limit_dependency
        req = self._make_mock_request("u42")
        with patch("src.api.middleware.rate_limit.check_rate_limit",
                   new=AsyncMock(return_value=(True, 1, 0))) as mock_rl:
            run(ingest_rate_limit_dependency(req))
            args = mock_rl.call_args
            self.assertEqual(args.args[1] if len(args.args) > 1 else args.args[0], "ingest")


class TestAutopilotRateLimitDependency(unittest.TestCase):
    def _make_mock_request(self, user_id="u1"):
        req = MagicMock()
        req.headers = {"x-viraclip-user-id": user_id}
        req.query_params = {}
        req.client = MagicMock()
        req.client.host = "127.0.0.1"
        return req

    def test_allows_when_under_limit(self):
        from src.api.middleware.rate_limit import autopilot_rate_limit_dependency
        req = self._make_mock_request()
        with patch("src.api.middleware.rate_limit.check_rate_limit",
                   new=AsyncMock(return_value=(True, 1, 0))):
            run(autopilot_rate_limit_dependency(req))

    def test_raises_429_when_exceeded(self):
        from src.api.middleware.rate_limit import autopilot_rate_limit_dependency, RateLimitExceeded
        req = self._make_mock_request()
        with patch("src.api.middleware.rate_limit.check_rate_limit",
                   new=AsyncMock(return_value=(False, 6, 3590))):
            with self.assertRaises(RateLimitExceeded):
                run(autopilot_rate_limit_dependency(req))

    def test_uses_autopilot_endpoint_type(self):
        from src.api.middleware.rate_limit import autopilot_rate_limit_dependency
        req = self._make_mock_request()
        with patch("src.api.middleware.rate_limit.check_rate_limit",
                   new=AsyncMock(return_value=(True, 1, 0))) as mock_rl:
            run(autopilot_rate_limit_dependency(req))
            args = mock_rl.call_args
            endpoint_type = args.args[1] if len(args.args) > 1 else args.args[0]
            self.assertEqual(endpoint_type, "autopilot")


# ═══════════════════════════════════════════════════════════════════════════
# 2. SCHEDULED PUBLISH SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_mock_redis(jobs=None):
    """Build a MagicMock that looks like an aioredis connection."""
    redis = MagicMock()
    redis.zadd = AsyncMock(return_value=1)
    redis.zcard = AsyncMock(return_value=len(jobs or []))
    redis.zrem = AsyncMock(return_value=1)

    raw_jobs = [json.dumps(j).encode() for j in (jobs or [])]
    redis.zrangebyscore = AsyncMock(return_value=raw_jobs)
    redis.zrange = AsyncMock(return_value=raw_jobs)
    return redis


class TestScheduledPublishService(unittest.TestCase):
    def _future(self, offset=3600):
        return time.time() + offset

    def test_schedule_creates_job(self):
        from src.services.scheduled_publish_service import schedule_publish
        redis = _make_mock_redis()
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)):
            job = run(schedule_publish(
                user_id="u1", clip_id="c1", task_id="t1",
                platform="tiktok", publish_at=self._future(),
            ))
        self.assertIn("job_id", job)
        self.assertEqual(job["platform"], "tiktok")
        self.assertEqual(job["status"], "pending")
        redis.zadd.assert_awaited_once()

    def test_schedule_rejects_past_timestamp(self):
        from src.services.scheduled_publish_service import schedule_publish
        redis = _make_mock_redis()
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)):
            with self.assertRaises(ValueError):
                run(schedule_publish(
                    user_id="u1", clip_id="c1", task_id="t1",
                    platform="tiktok", publish_at=time.time() - 10,
                ))

    def test_schedule_rejects_when_quota_full(self):
        from src.services.scheduled_publish_service import schedule_publish, _MAX_JOBS_PER_USER
        redis = _make_mock_redis()
        redis.zcard = AsyncMock(return_value=_MAX_JOBS_PER_USER)
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)):
            with self.assertRaises(ValueError):
                run(schedule_publish(
                    user_id="u1", clip_id="c1", task_id="t1",
                    platform="tiktok", publish_at=self._future(),
                ))

    def test_list_scheduled_returns_jobs(self):
        from src.services.scheduled_publish_service import list_scheduled
        jobs = [
            {"job_id": "j1", "clip_id": "c1", "platform": "tiktok",
             "publish_at": self._future(), "status": "pending"},
        ]
        redis = _make_mock_redis(jobs)
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)):
            result = run(list_scheduled("u1"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job_id"], "j1")

    def test_cancel_removes_job(self):
        from src.services.scheduled_publish_service import cancel_scheduled
        job = {"job_id": "j1", "clip_id": "c1", "platform": "tiktok",
               "publish_at": self._future(), "status": "pending"}
        redis = _make_mock_redis([job])
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)):
            result = run(cancel_scheduled("u1", "j1"))
        self.assertTrue(result)
        redis.zrem.assert_awaited_once()

    def test_cancel_returns_false_for_unknown_job(self):
        from src.services.scheduled_publish_service import cancel_scheduled
        redis = _make_mock_redis([])
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)):
            result = run(cancel_scheduled("u1", "nonexistent"))
        self.assertFalse(result)

    def test_execute_now_publishes_and_removes(self):
        from src.services.scheduled_publish_service import execute_now
        job = {"job_id": "j1", "clip_id": "c1", "task_id": "t1",
               "platform": "tiktok", "publish_at": self._future(),
               "title": "", "description": "", "hashtags": [], "status": "pending"}
        redis = _make_mock_redis([job])
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)), \
             patch("src.services.scheduled_publish_service._publish_job",
                   new=AsyncMock(return_value=None)):
            result = run(execute_now("u1", "j1"))
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "published")
        redis.zrem.assert_awaited_once()

    def test_execute_now_returns_none_for_unknown(self):
        from src.services.scheduled_publish_service import execute_now
        redis = _make_mock_redis([])
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)):
            result = run(execute_now("u1", "nonexistent"))
        self.assertIsNone(result)

    def test_execute_now_marks_failed_on_error(self):
        from src.services.scheduled_publish_service import execute_now
        job = {"job_id": "j1", "clip_id": "c1", "task_id": "t1",
               "platform": "tiktok", "publish_at": self._future(),
               "title": "", "description": "", "hashtags": [], "status": "pending"}
        redis = _make_mock_redis([job])
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)), \
             patch("src.services.scheduled_publish_service._publish_job",
                   new=AsyncMock(side_effect=RuntimeError("API error"))):
            result = run(execute_now("u1", "j1"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("API error", result["error"])

    def test_execute_due_runs_past_jobs(self):
        from src.services.scheduled_publish_service import execute_due_jobs
        job = {"job_id": "j1", "clip_id": "c1", "task_id": "t1",
               "platform": "tiktok", "publish_at": time.time() - 10,
               "title": "", "description": "", "hashtags": [], "status": "pending"}
        redis = MagicMock()
        redis.zrangebyscore = AsyncMock(return_value=[json.dumps(job).encode()])
        redis.zrem = AsyncMock(return_value=1)
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)), \
             patch("src.services.scheduled_publish_service._publish_job",
                   new=AsyncMock(return_value=None)):
            results = run(execute_due_jobs("u1"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "published")

    def test_execute_due_handles_publish_failure(self):
        from src.services.scheduled_publish_service import execute_due_jobs
        job = {"job_id": "j2", "clip_id": "c2", "task_id": "t1",
               "platform": "instagram", "publish_at": time.time() - 5,
               "title": "", "description": "", "hashtags": [], "status": "pending"}
        redis = MagicMock()
        redis.zrangebyscore = AsyncMock(return_value=[json.dumps(job).encode()])
        redis.zrem = AsyncMock(return_value=1)
        with patch("src.services.scheduled_publish_service._get_redis",
                   new=AsyncMock(return_value=redis)), \
             patch("src.services.scheduled_publish_service._publish_job",
                   new=AsyncMock(side_effect=RuntimeError("rate limit"))):
            results = run(execute_due_jobs("u1"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "failed")


# ═══════════════════════════════════════════════════════════════════════════
# 3. SCHEDULED PUBLISH API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_schedule_app():
    from fastapi import FastAPI
    from src.api.routes.scheduled_publish import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestScheduledPublishApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_schedule_app())
        self.future_ts = time.time() + 7200

    def test_schedule_requires_platform_validation(self):
        payload = {
            "user_id": "u1", "clip_id": "c1", "task_id": "t1",
            "platform": "twitter",
            "publish_at": self.future_ts,
        }
        resp = self.client.post("/scheduled-publish/schedule", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_schedule_success(self):
        mock_job = {
            "job_id": "j1", "user_id": "u1", "clip_id": "c1", "task_id": "t1",
            "platform": "tiktok", "publish_at": self.future_ts, "status": "pending",
        }
        with patch("src.services.scheduled_publish_service.schedule_publish",
                   new=AsyncMock(return_value=mock_job)):
            resp = self.client.post("/scheduled-publish/schedule", json={
                "user_id": "u1", "clip_id": "c1", "task_id": "t1",
                "platform": "tiktok", "publish_at": self.future_ts,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["job"]["job_id"], "j1")

    def test_schedule_400_on_past_timestamp(self):
        with patch("src.services.scheduled_publish_service.schedule_publish",
                   new=AsyncMock(side_effect=ValueError("past timestamp"))):
            resp = self.client.post("/scheduled-publish/schedule", json={
                "user_id": "u1", "clip_id": "c1", "task_id": "t1",
                "platform": "tiktok", "publish_at": self.future_ts,
            })
        self.assertEqual(resp.status_code, 400)

    def test_list_requires_user_id(self):
        resp = self.client.get("/scheduled-publish/list")
        self.assertEqual(resp.status_code, 422)

    def test_list_returns_jobs(self):
        mock_jobs = [{"job_id": "j1"}, {"job_id": "j2"}]
        with patch("src.services.scheduled_publish_service.list_scheduled",
                   new=AsyncMock(return_value=mock_jobs)):
            resp = self.client.get("/scheduled-publish/list?user_id=u1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)

    def test_cancel_404_not_found(self):
        with patch("src.services.scheduled_publish_service.cancel_scheduled",
                   new=AsyncMock(return_value=False)):
            resp = self.client.delete("/scheduled-publish/j999?user_id=u1")
        self.assertEqual(resp.status_code, 404)

    def test_cancel_success(self):
        with patch("src.services.scheduled_publish_service.cancel_scheduled",
                   new=AsyncMock(return_value=True)):
            resp = self.client.delete("/scheduled-publish/j1?user_id=u1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["job_id"], "j1")

    def test_publish_now_404_not_found(self):
        with patch("src.services.scheduled_publish_service.execute_now",
                   new=AsyncMock(return_value=None)):
            resp = self.client.post("/scheduled-publish/j999/publish-now?user_id=u1")
        self.assertEqual(resp.status_code, 404)

    def test_publish_now_success(self):
        mock_result = {"job_id": "j1", "status": "published", "error": None}
        with patch("src.services.scheduled_publish_service.execute_now",
                   new=AsyncMock(return_value=mock_result)):
            resp = self.client.post("/scheduled-publish/j1/publish-now?user_id=u1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["job"]["status"], "published")

    def test_publish_now_502_on_failure(self):
        mock_result = {"job_id": "j1", "status": "failed", "error": "API rate limit"}
        with patch("src.services.scheduled_publish_service.execute_now",
                   new=AsyncMock(return_value=mock_result)):
            resp = self.client.post("/scheduled-publish/j1/publish-now?user_id=u1")
        self.assertEqual(resp.status_code, 502)

    def test_execute_due_requires_user_id(self):
        resp = self.client.post("/scheduled-publish/execute-due")
        self.assertEqual(resp.status_code, 422)

    def test_execute_due_returns_summary(self):
        mock_results = [
            {"job_id": "j1", "status": "published", "error": None},
            {"job_id": "j2", "status": "failed", "error": "timeout"},
        ]
        with patch("src.services.scheduled_publish_service.execute_due_jobs",
                   new=AsyncMock(return_value=mock_results)):
            resp = self.client.post("/scheduled-publish/execute-due?user_id=u1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["executed"], 2)
        self.assertEqual(data["published"], 1)
        self.assertEqual(data["failed"], 1)


if __name__ == "__main__":
    unittest.main()
