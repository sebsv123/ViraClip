"""
Phase 18 — Cache, Dedup & User Quota Tests

Covers:
  - cache_service: get/set/invalidate/prefix/stats
  - dedup_service: hash computation, is_duplicate, register_hash, clear_hash
  - user_quota API routes: quota, dedup-check, dedup-clear
"""

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CACHE SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_redis(stored=None):
    redis = MagicMock()
    stored = stored or {}
    redis.get = AsyncMock(side_effect=lambda k: stored.get(k))
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.keys = AsyncMock(return_value=[b"cache:trend:tech", b"cache:niche:gaming"])
    return redis


class TestCacheService(unittest.TestCase):
    def test_cache_miss_returns_none(self):
        from src.services.cache_service import cached_response
        redis = _make_redis(stored={})
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            result = run(cached_response("trend:tech"))
        self.assertIsNone(result)

    def test_cache_hit_returns_value(self):
        from src.services.cache_service import cached_response
        data = {"hooks": ["Use this trick...", "Did you know..."], "niche": "tech"}
        redis = _make_redis(stored={"cache:trend:tech": json.dumps(data).encode()})
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            result = run(cached_response("trend:tech"))
        self.assertEqual(result, data)

    def test_set_cached_response_calls_setex(self):
        from src.services.cache_service import set_cached_response
        redis = _make_redis()
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            run(set_cached_response("trend:tech", {"data": 1}, ttl=1800))
        redis.setex.assert_awaited_once()
        args = redis.setex.call_args.args
        self.assertEqual(args[0], "cache:trend:tech")
        self.assertEqual(args[1], 1800)

    def test_set_cached_stores_json(self):
        from src.services.cache_service import set_cached_response
        captured = {}
        async def fake_setex(key, ttl, val):
            captured["val"] = val
        redis = MagicMock()
        redis.setex = fake_setex
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            run(set_cached_response("k", {"x": 42}))
        self.assertEqual(json.loads(captured["val"]), {"x": 42})

    def test_invalidate_cache(self):
        from src.services.cache_service import invalidate_cache
        redis = _make_redis()
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            result = run(invalidate_cache("trend:tech"))
        self.assertTrue(result)
        redis.delete.assert_awaited_once_with("cache:trend:tech")

    def test_invalidate_prefix(self):
        from src.services.cache_service import invalidate_prefix
        redis = MagicMock()
        redis.keys = AsyncMock(return_value=[b"cache:trend:tech", b"cache:trend:fitness"])
        redis.delete = AsyncMock(return_value=2)
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            count = run(invalidate_prefix("trend:"))
        self.assertEqual(count, 2)

    def test_invalidate_prefix_empty_returns_zero(self):
        from src.services.cache_service import invalidate_prefix
        redis = MagicMock()
        redis.keys = AsyncMock(return_value=[])
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            count = run(invalidate_prefix("nonexistent:"))
        self.assertEqual(count, 0)

    def test_get_cache_stats(self):
        from src.services.cache_service import get_cache_stats
        redis = _make_redis()
        with patch("src.services.cache_service._get_redis", new=AsyncMock(return_value=redis)):
            stats = run(get_cache_stats(prefixes=["trend", "niche"]))
        self.assertIn("total_keys", stats)
        self.assertIn("by_prefix", stats)

    def test_cache_fails_open_on_redis_error(self):
        from src.services.cache_service import cached_response
        with patch("src.services.cache_service._get_redis",
                   new=AsyncMock(side_effect=Exception("Redis down"))):
            result = run(cached_response("any:key"))
        self.assertIsNone(result)

    def test_set_cache_fails_open_on_redis_error(self):
        from src.services.cache_service import set_cached_response
        with patch("src.services.cache_service._get_redis",
                   new=AsyncMock(side_effect=Exception("Redis down"))):
            run(set_cached_response("any:key", {"data": 1}))


# ═══════════════════════════════════════════════════════════════════════════
# 2. DEDUP SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestDedupService(unittest.TestCase):
    def test_compute_file_hash_sha256(self):
        from src.services.dedup_service import compute_file_hash
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            f.write(b"fake video data" * 100)
            path = f.name
        expected = hashlib.sha256(b"fake video data" * 100).hexdigest()
        self.assertEqual(compute_file_hash(path), expected)

    def test_compute_file_hash_missing_file(self):
        from src.services.dedup_service import compute_file_hash
        with self.assertRaises(FileNotFoundError):
            compute_file_hash("/nonexistent/video.mp4")

    def test_compute_bytes_hash(self):
        from src.services.dedup_service import compute_bytes_hash
        data = b"hello world"
        expected = hashlib.sha256(data).hexdigest()
        self.assertEqual(compute_bytes_hash(data), expected)

    def test_is_duplicate_false_when_not_seen(self):
        from src.services.dedup_service import is_duplicate
        redis = MagicMock()
        redis.exists = AsyncMock(return_value=0)
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(return_value=redis)
            result = run(is_duplicate("u1", "abc123"))
        self.assertFalse(result)

    def test_is_duplicate_true_when_seen(self):
        from src.services.dedup_service import is_duplicate
        redis = MagicMock()
        redis.exists = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(return_value=redis)
            result = run(is_duplicate("u1", "abc123"))
        self.assertTrue(result)

    def test_is_duplicate_fails_open_on_error(self):
        from src.services.dedup_service import is_duplicate
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(side_effect=Exception("Redis down"))
            result = run(is_duplicate("u1", "abc123"))
        self.assertFalse(result)

    def test_register_hash_calls_setex(self):
        from src.services.dedup_service import register_hash
        redis = MagicMock()
        redis.setex = AsyncMock(return_value=True)
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(return_value=redis)
            run(register_hash("u1", "abc123", task_id="t99"))
        redis.setex.assert_awaited_once()
        args = redis.setex.call_args.args
        self.assertIn("abc123", args[0])
        self.assertEqual(args[2], "t99")

    def test_get_original_task_returns_task_id(self):
        from src.services.dedup_service import get_original_task
        redis = MagicMock()
        redis.get = AsyncMock(return_value=b"t99")
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(return_value=redis)
            result = run(get_original_task("u1", "abc123"))
        self.assertEqual(result, "t99")

    def test_get_original_task_returns_none_for_unknown(self):
        from src.services.dedup_service import get_original_task
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(return_value=redis)
            result = run(get_original_task("u1", "abc123"))
        self.assertIsNone(result)

    def test_clear_hash_returns_true(self):
        from src.services.dedup_service import clear_hash
        redis = MagicMock()
        redis.delete = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(return_value=redis)
            result = run(clear_hash("u1", "abc123"))
        self.assertTrue(result)

    def test_clear_hash_returns_false_when_not_found(self):
        from src.services.dedup_service import clear_hash
        redis = MagicMock()
        redis.delete = AsyncMock(return_value=0)
        with patch("src.workers.job_queue.JobQueue") as mock_jq:
            mock_jq.get_pool = AsyncMock(return_value=redis)
            result = run(clear_hash("u1", "nonexistent"))
        self.assertFalse(result)


# ═══════════════════════════════════════════════════════════════════════════
# 3. USER QUOTA API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_quota_app():
    from fastapi import FastAPI
    from src.api.routes.user_quota import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestUserQuotaApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_quota_app())

    def test_quota_returns_all_fields(self):
        mock_rate = {"ingest": {"limit": 10, "remaining": 8, "reset_in_seconds": 3500}}
        mock_jobs = []
        mock_stats = {"total_keys": 5, "by_prefix": {"trend": 3, "niche": 2}}
        with patch("src.api.middleware.rate_limit.get_rate_limit_status",
                   new=AsyncMock(return_value=mock_rate)), \
             patch("src.services.scheduled_publish_service.list_scheduled",
                   new=AsyncMock(return_value=mock_jobs)), \
             patch("src.services.cache_service.get_cache_stats",
                   new=AsyncMock(return_value=mock_stats)):
            resp = self.client.get("/users/u1/quota")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["user_id"], "u1")
        self.assertIn("rate_limits", data)
        self.assertIn("scheduled_jobs", data)
        self.assertIn("cache", data)
        self.assertEqual(data["scheduled_jobs"]["count"], 0)

    def test_dedup_check_not_duplicate(self):
        with patch("src.services.dedup_service.is_duplicate",
                   new=AsyncMock(return_value=False)):
            resp = self.client.get("/users/u1/dedup/check?file_hash=abc123")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_duplicate"])
        self.assertIsNone(data["original_task_id"])

    def test_dedup_check_is_duplicate(self):
        with patch("src.services.dedup_service.is_duplicate",
                   new=AsyncMock(return_value=True)), \
             patch("src.services.dedup_service.get_original_task",
                   new=AsyncMock(return_value="t42")):
            resp = self.client.get("/users/u1/dedup/check?file_hash=abc123")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_duplicate"])
        self.assertEqual(data["original_task_id"], "t42")

    def test_dedup_check_requires_file_hash(self):
        resp = self.client.get("/users/u1/dedup/check")
        self.assertEqual(resp.status_code, 422)

    def test_dedup_clear_success(self):
        with patch("src.services.dedup_service.clear_hash",
                   new=AsyncMock(return_value=True)):
            resp = self.client.delete("/users/u1/dedup/abc123")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["file_hash"], "abc123")

    def test_dedup_clear_404_not_found(self):
        with patch("src.services.dedup_service.clear_hash",
                   new=AsyncMock(return_value=False)):
            resp = self.client.delete("/users/u1/dedup/nonexistent")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
