"""
Phase 19 — Clip Tags, Bulk Actions & Enhanced Health Tests

Covers:
  - clip_tag_service: add/remove/get/clear + get_clips_by_tag
  - clip_bulk API: /clips/bulk, /clips/{id}/tags CRUD
  - health_service: check_redis, check_disk, check_worker_queue, full_health_check
  - health_enhanced API: /health/detailed, /health/ready, /health/live
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLIP TAG SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_tag_redis(members=None):
    members = {m.encode() for m in (members or [])}
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value=members)
    redis.sadd = AsyncMock(return_value=1)
    redis.srem = AsyncMock(return_value=1)
    redis.delete = AsyncMock(return_value=1)
    redis.sismember = AsyncMock(side_effect=lambda key, tag: AsyncMock(return_value=tag.encode() in members)())
    return redis


class TestClipTagService(unittest.TestCase):
    def test_add_tags_returns_updated_list(self):
        from src.services.clip_tag_service import add_tags
        redis = _make_tag_redis(members=[])
        # After sadd, smembers should return the new tags
        redis.smembers = AsyncMock(side_effect=[set(), {b"viral", b"funny"}])
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(add_tags("c1", ["viral", "Funny"]))
        self.assertIn("viral", result)
        self.assertIn("funny", result)

    def test_add_tags_normalises_case(self):
        from src.services.clip_tag_service import _normalise
        self.assertEqual(_normalise("  TECH  "), "tech")
        self.assertEqual(_normalise("Finance"), "finance")

    def test_add_tags_raises_on_quota_exceeded(self):
        from src.services.clip_tag_service import add_tags, _MAX_TAGS
        existing = {f"tag{i}".encode() for i in range(_MAX_TAGS)}
        redis = _make_tag_redis()
        redis.smembers = AsyncMock(return_value=existing)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            with self.assertRaises(ValueError):
                run(add_tags("c1", ["new_tag"]))

    def test_remove_tags(self):
        from src.services.clip_tag_service import remove_tags
        redis = _make_tag_redis(members=[])
        redis.smembers = AsyncMock(return_value=set())
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(remove_tags("c1", ["viral"]))
        redis.srem.assert_awaited_once()
        self.assertEqual(result, [])

    def test_get_tags_returns_sorted_list(self):
        from src.services.clip_tag_service import get_tags
        redis = _make_tag_redis(members=["zzz", "aaa", "mmm"])
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(get_tags("c1"))
        self.assertEqual(result, ["aaa", "mmm", "zzz"])

    def test_get_tags_fails_open(self):
        from src.services.clip_tag_service import get_tags
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(side_effect=Exception("Redis down"))
            result = run(get_tags("c1"))
        self.assertEqual(result, [])

    def test_clear_tags(self):
        from src.services.clip_tag_service import clear_tags
        redis = _make_tag_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            run(clear_tags("c1"))
        redis.delete.assert_awaited_once()

    def test_get_clips_by_tag_filters_correctly(self):
        from src.services.clip_tag_service import get_clips_by_tag
        redis = MagicMock()
        # c1 has "viral", c2/c3 do not
        redis.sismember = AsyncMock(side_effect=lambda key, tag: True if "c1" in key else False)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(get_clips_by_tag("viral", ["c1", "c2", "c3"]))
        self.assertEqual(result, ["c1"])


# ═══════════════════════════════════════════════════════════════════════════
# 2. CLIP BULK + TAG API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_bulk_app():
    from fastapi import FastAPI
    from src.api.routes.clip_bulk import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestClipBulkApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_bulk_app())

    def test_bulk_tag_action(self):
        with patch("src.services.clip_tag_service.add_tags",
                   new=AsyncMock(return_value=["viral"])):
            resp = self.client.post("/clips/bulk?user_id=u1", json={
                "clip_ids": ["c1", "c2"],
                "action": "tag",
                "tags": ["viral"],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["processed"], 2)
        self.assertEqual(len(data["failed"]), 0)

    def test_bulk_untag_action(self):
        with patch("src.services.clip_tag_service.remove_tags",
                   new=AsyncMock(return_value=[])):
            resp = self.client.post("/clips/bulk?user_id=u1", json={
                "clip_ids": ["c1"],
                "action": "untag",
                "tags": ["viral"],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["processed"], 1)

    def test_bulk_delete_action(self):
        with patch("src.services.clip_tag_service.add_tags",
                   new=AsyncMock(return_value=["__status:delete"])):
            resp = self.client.post("/clips/bulk?user_id=u1", json={
                "clip_ids": ["c1", "c2"],
                "action": "delete",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["processed"], 2)

    def test_bulk_empty_clip_ids_400(self):
        resp = self.client.post("/clips/bulk?user_id=u1", json={
            "clip_ids": [],
            "action": "tag",
            "tags": ["x"],
        })
        self.assertEqual(resp.status_code, 400)

    def test_bulk_invalid_action_422(self):
        resp = self.client.post("/clips/bulk?user_id=u1", json={
            "clip_ids": ["c1"],
            "action": "fly_to_moon",
        })
        self.assertEqual(resp.status_code, 422)

    def test_bulk_records_failures(self):
        with patch("src.services.clip_tag_service.add_tags",
                   new=AsyncMock(side_effect=ValueError("quota exceeded"))):
            resp = self.client.post("/clips/bulk?user_id=u1", json={
                "clip_ids": ["c1"],
                "action": "tag",
                "tags": ["x"],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["processed"], 0)
        self.assertEqual(len(data["failed"]), 1)

    def test_get_tags_endpoint(self):
        with patch("src.services.clip_tag_service.get_tags",
                   new=AsyncMock(return_value=["funny", "viral"])):
            resp = self.client.get("/clips/c1/tags")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["clip_id"], "c1")
        self.assertIn("viral", data["tags"])

    def test_add_tags_endpoint(self):
        with patch("src.services.clip_tag_service.add_tags",
                   new=AsyncMock(return_value=["funny", "viral"])):
            resp = self.client.post("/clips/c1/tags", json={"tags": ["viral"]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("viral", resp.json()["tags"])

    def test_add_tags_400_on_quota_error(self):
        with patch("src.services.clip_tag_service.add_tags",
                   new=AsyncMock(side_effect=ValueError("max tags"))):
            resp = self.client.post("/clips/c1/tags", json={"tags": ["x"]})
        self.assertEqual(resp.status_code, 400)

    def test_remove_tags_endpoint(self):
        with patch("src.services.clip_tag_service.remove_tags",
                   new=AsyncMock(return_value=["funny"])):
            resp = self.client.request("DELETE", "/clips/c1/tags",
                                       json={"tags": ["viral"]})
        self.assertEqual(resp.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 3. HEALTH SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthService(unittest.TestCase):
    def test_check_redis_ok(self):
        from src.services.health_service import check_redis
        redis = MagicMock()
        redis.ping = AsyncMock(return_value=True)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(check_redis())
        self.assertEqual(result["status"], "ok")
        self.assertIn("latency_ms", result)

    def test_check_redis_error(self):
        from src.services.health_service import check_redis
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(side_effect=Exception("refused"))
            result = run(check_redis())
        self.assertEqual(result["status"], "error")

    def test_check_disk_ok(self):
        from src.services.health_service import check_disk
        result = check_disk()
        self.assertIn(result["status"], ("ok", "warning"))
        self.assertIn("free_gb", result)
        self.assertIn("used_pct", result)

    def test_check_worker_queue(self):
        from src.services.health_service import check_worker_queue
        redis = MagicMock()
        redis.llen = AsyncMock(return_value=3)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=redis)
            result = run(check_worker_queue())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["queue_length"], 3)

    def test_full_health_check_ok(self):
        from src.services.health_service import full_health_check
        ok = {"status": "ok", "latency_ms": 1.0}
        disk = {"status": "ok", "free_gb": 100, "total_gb": 200, "used_pct": 50}
        queue = {"status": "ok", "queue_length": 0}
        with patch("src.services.health_service.check_redis",
                   new=AsyncMock(return_value=ok)), \
             patch("src.services.health_service.check_database",
                   new=AsyncMock(return_value=ok)), \
             patch("src.services.health_service.check_disk", return_value=disk), \
             patch("src.services.health_service.check_worker_queue",
                   new=AsyncMock(return_value=queue)):
            result = run(full_health_check())
        self.assertEqual(result["status"], "ok")
        self.assertIn("components", result)

    def test_full_health_check_degraded_when_redis_down(self):
        from src.services.health_service import full_health_check
        ok = {"status": "ok", "latency_ms": 1.0}
        disk = {"status": "ok", "free_gb": 100, "total_gb": 200, "used_pct": 50}
        with patch("src.services.health_service.check_redis",
                   new=AsyncMock(return_value={"status": "error", "error": "refused"})), \
             patch("src.services.health_service.check_database",
                   new=AsyncMock(return_value=ok)), \
             patch("src.services.health_service.check_disk", return_value=disk), \
             patch("src.services.health_service.check_worker_queue",
                   new=AsyncMock(return_value={"status": "error", "error": "refused"})):
            result = run(full_health_check())
        self.assertEqual(result["status"], "degraded")


# ═══════════════════════════════════════════════════════════════════════════
# 4. HEALTH ENHANCED API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_health_app():
    from fastapi import FastAPI
    from src.api.routes.health_enhanced import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestHealthEnhancedApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_health_app())

    def test_liveness_always_200(self):
        resp = self.client.get("/health/live")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["alive"])

    def test_detailed_returns_components(self):
        report = {
            "status": "ok",
            "timestamp": 1000.0,
            "components": {
                "redis": {"status": "ok"},
                "database": {"status": "ok"},
                "disk": {"status": "ok"},
                "worker_queue": {"status": "ok"},
            },
        }
        with patch("src.services.health_service.full_health_check",
                   new=AsyncMock(return_value=report)):
            resp = self.client.get("/health/detailed")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("components", resp.json())

    def test_detailed_503_when_degraded(self):
        report = {
            "status": "degraded",
            "timestamp": 1000.0,
            "components": {"redis": {"status": "error"}},
        }
        with patch("src.services.health_service.full_health_check",
                   new=AsyncMock(return_value=report)):
            resp = self.client.get("/health/detailed")
        self.assertEqual(resp.status_code, 503)

    def test_ready_200_when_all_ok(self):
        ok = {"status": "ok", "latency_ms": 1.0}
        with patch("src.services.health_service.check_redis",
                   new=AsyncMock(return_value=ok)), \
             patch("src.services.health_service.check_database",
                   new=AsyncMock(return_value=ok)):
            resp = self.client.get("/health/ready")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ready"])

    def test_ready_503_when_redis_down(self):
        ok = {"status": "ok", "latency_ms": 1.0}
        with patch("src.services.health_service.check_redis",
                   new=AsyncMock(return_value={"status": "error", "error": "refused"})), \
             patch("src.services.health_service.check_database",
                   new=AsyncMock(return_value=ok)):
            resp = self.client.get("/health/ready")
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
