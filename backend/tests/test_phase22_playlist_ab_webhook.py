"""
Phase 22 — Playlist, A/B Test & Webhook Event Log Tests

Covers:
  - playlist_service: create/get/list/delete/add_clip/remove_clip
  - ab_test_service: create_variant/record_impression/record_click/get_stats/delete
  - webhook_event_log_service: log_event/update_status/get_log/clear/stats
  - playlist_ab_webhook API routes
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. PLAYLIST SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_playlist_redis(scard=0, exists=1, hgetall=None, lrange=None):
    r = MagicMock()
    r.scard = AsyncMock(return_value=scard)
    r.hset = AsyncMock(return_value=1)
    r.sadd = AsyncMock(return_value=1)
    r.rpush = AsyncMock(return_value=1)
    r.llen = AsyncMock(return_value=0)
    r.smembers = AsyncMock(return_value=set())
    r.hgetall = AsyncMock(return_value=hgetall or {})
    r.lrange = AsyncMock(return_value=lrange or [])
    r.delete = AsyncMock(return_value=1)
    r.srem = AsyncMock(return_value=1)
    r.lrem = AsyncMock(return_value=1)
    r.exists = AsyncMock(return_value=exists)
    return r


class TestPlaylistService(unittest.TestCase):
    def test_create_playlist(self):
        from src.services.playlist_service import create_playlist
        r = _make_playlist_redis(scard=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(create_playlist("u1", "My List", clip_ids=["c1", "c2"]))
        self.assertEqual(result["name"], "My List")
        self.assertIn("playlist_id", result)
        r.hset.assert_awaited()

    def test_create_playlist_raises_at_max(self):
        from src.services.playlist_service import create_playlist, _MAX_PLAYLISTS
        r = _make_playlist_redis(scard=_MAX_PLAYLISTS)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(create_playlist("u1", "Overflow"))

    def test_get_playlist_returns_none_when_not_found(self):
        from src.services.playlist_service import get_playlist
        r = _make_playlist_redis(hgetall={})
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_playlist("u1", "no-such-id"))
        self.assertIsNone(result)

    def test_get_playlist_returns_clips(self):
        from src.services.playlist_service import get_playlist
        meta = {b"name": b"Test", b"playlist_id": b"pid1",
                b"user_id": b"u1", b"description": b"",
                b"created_at": b"t", b"updated_at": b"t"}
        clips = [b"c1", b"c2"]
        r = _make_playlist_redis(hgetall=meta, lrange=clips)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_playlist("u1", "pid1"))
        self.assertEqual(result["name"], "Test")
        self.assertEqual(result["clips"], ["c1", "c2"])

    def test_delete_playlist(self):
        from src.services.playlist_service import delete_playlist
        r = _make_playlist_redis(exists=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_playlist("u1", "pid1"))
        self.assertTrue(result)

    def test_delete_playlist_not_found(self):
        from src.services.playlist_service import delete_playlist
        r = _make_playlist_redis(exists=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_playlist("u1", "pid1"))
        self.assertFalse(result)

    def test_add_clip_to_playlist(self):
        from src.services.playlist_service import add_clip_to_playlist
        r = _make_playlist_redis()
        r.llen = AsyncMock(return_value=5)
        r.rpush = AsyncMock(return_value=6)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(add_clip_to_playlist("u1", "pid1", "c99"))
        self.assertEqual(result, 6)

    def test_add_clip_raises_at_max(self):
        from src.services.playlist_service import add_clip_to_playlist, _MAX_CLIPS
        r = _make_playlist_redis()
        r.llen = AsyncMock(return_value=_MAX_CLIPS)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(add_clip_to_playlist("u1", "pid1", "c99"))

    def test_remove_clip_from_playlist(self):
        from src.services.playlist_service import remove_clip_from_playlist
        r = _make_playlist_redis()
        r.lrem = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            removed = run(remove_clip_from_playlist("u1", "pid1", "c1"))
        self.assertEqual(removed, 1)


# ═══════════════════════════════════════════════════════════════════════════
# 2. A/B TEST SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_ab_redis(scard=0, hgetall_meta=None, hgetall_stats=None, exists=1):
    r = MagicMock()
    r.scard = AsyncMock(return_value=scard)
    r.hset = AsyncMock(return_value=1)
    r.sadd = AsyncMock(return_value=1)
    r.hincrby = AsyncMock(return_value=1)
    r.smembers = AsyncMock(return_value=set())
    r.hgetall = AsyncMock(side_effect=[
        hgetall_meta or {},
        hgetall_stats or {b"impressions": b"10", b"clicks": b"2"},
    ])
    r.exists = AsyncMock(return_value=exists)
    r.delete = AsyncMock(return_value=1)
    r.srem = AsyncMock(return_value=1)
    return r


class TestAbTestService(unittest.TestCase):
    def test_create_variant(self):
        from src.services.ab_test_service import create_variant
        r = _make_ab_redis(scard=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(create_variant("c1", "Version A", "Hello world"))
        self.assertEqual(result["label"], "Version A")
        self.assertIn("variant_id", result)

    def test_create_variant_raises_at_max(self):
        from src.services.ab_test_service import create_variant, _MAX_VARIANTS
        r = _make_ab_redis(scard=_MAX_VARIANTS)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(create_variant("c1", "Overflow"))

    def test_record_impression(self):
        from src.services.ab_test_service import record_impression
        r = MagicMock()
        r.hincrby = AsyncMock(return_value=5)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(record_impression("c1", "v1"))
        self.assertEqual(result, 5)

    def test_record_click(self):
        from src.services.ab_test_service import record_click
        r = MagicMock()
        r.hincrby = AsyncMock(return_value=3)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(record_click("c1", "v1"))
        self.assertEqual(result, 3)

    def test_get_variant_stats_ctr(self):
        from src.services.ab_test_service import get_variant_stats
        meta = {b"variant_id": b"v1", b"clip_id": b"c1",
                b"label": b"A", b"content": b"x", b"created_at": b"t"}
        stats = {b"impressions": b"10", b"clicks": b"2"}
        r = MagicMock()
        r.hgetall = AsyncMock(side_effect=[meta, stats])
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_variant_stats("c1", "v1"))
        self.assertEqual(result["ctr"], 0.2)
        self.assertEqual(result["impressions"], 10)

    def test_get_variant_stats_returns_none_when_missing(self):
        from src.services.ab_test_service import get_variant_stats
        r = MagicMock()
        r.hgetall = AsyncMock(return_value={})
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_variant_stats("c1", "nope"))
        self.assertIsNone(result)

    def test_delete_variant(self):
        from src.services.ab_test_service import delete_variant
        r = MagicMock()
        r.exists = AsyncMock(return_value=1)
        r.delete = AsyncMock(return_value=1)
        r.srem = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_variant("c1", "v1"))
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# 3. WEBHOOK EVENT LOG SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_log_entry(event_id="e1", status="pending"):
    return json.dumps({
        "event_id": event_id, "event_type": "task.completed",
        "url": "https://example.com/hook", "payload_summary": "",
        "status": status, "http_status": None, "attempts": 0,
        "created_at": "t", "delivered_at": None,
    }).encode()


class TestWebhookEventLogService(unittest.TestCase):
    def _mock_redis(self, items=None):
        r = MagicMock()
        r.lpush = AsyncMock(return_value=1)
        r.ltrim = AsyncMock(return_value=True)
        r.expire = AsyncMock(return_value=True)
        r.lrange = AsyncMock(return_value=items or [])
        r.lset = AsyncMock(return_value=True)
        r.delete = AsyncMock(return_value=1)
        return r

    def test_log_event_returns_entry(self):
        from src.services.webhook_event_log_service import log_event
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(log_event("u1", "task.done", "https://hook.test"))
        self.assertEqual(result["event_type"], "task.done")
        self.assertIn("event_id", result)

    def test_get_event_log(self):
        from src.services.webhook_event_log_service import get_event_log
        items = [_make_log_entry("e1", "delivered"), _make_log_entry("e2", "failed")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_event_log("u1", limit=10))
        self.assertEqual(len(result), 2)

    def test_get_event_log_status_filter(self):
        from src.services.webhook_event_log_service import get_event_log
        items = [_make_log_entry("e1", "delivered"), _make_log_entry("e2", "failed")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_event_log("u1", status_filter="delivered"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "delivered")

    def test_update_event_status(self):
        from src.services.webhook_event_log_service import update_event_status
        items = [_make_log_entry("e1", "pending")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(update_event_status("u1", "e1", "delivered", http_status=200))
        self.assertTrue(result)

    def test_update_event_status_not_found(self):
        from src.services.webhook_event_log_service import update_event_status
        items = [_make_log_entry("e1", "pending")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(update_event_status("u1", "no-such-id", "delivered"))
        self.assertFalse(result)

    def test_get_event_stats(self):
        from src.services.webhook_event_log_service import get_event_stats
        items = [_make_log_entry("e1", "delivered"),
                 _make_log_entry("e2", "failed"),
                 _make_log_entry("e3", "pending")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_event_stats("u1"))
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["delivered"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["pending"], 1)


# ═══════════════════════════════════════════════════════════════════════════
# 4. PLAYLIST/AB/WEBHOOK API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_p22_app():
    from fastapi import FastAPI
    from src.api.routes.playlist_ab_webhook import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestPlaylistAbWebhookApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_p22_app())

    # Playlist tests
    def test_create_playlist_200(self):
        mock_pl = {"playlist_id": "pid1", "name": "My List",
                   "user_id": "u1", "description": "", "clip_count": 0,
                   "created_at": "t", "updated_at": "t"}
        with patch("src.services.playlist_service.create_playlist",
                   new=AsyncMock(return_value=mock_pl)):
            resp = self.client.post("/playlists",
                                    json={"user_id": "u1", "name": "My List"})
        self.assertEqual(resp.status_code, 200)

    def test_create_playlist_400_on_overflow(self):
        with patch("src.services.playlist_service.create_playlist",
                   new=AsyncMock(side_effect=ValueError("max playlists"))):
            resp = self.client.post("/playlists",
                                    json={"user_id": "u1", "name": "Overflow"})
        self.assertEqual(resp.status_code, 400)

    def test_get_playlist_404(self):
        with patch("src.services.playlist_service.get_playlist",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/playlists/u1/pid1")
        self.assertEqual(resp.status_code, 404)

    def test_delete_playlist_200(self):
        with patch("src.services.playlist_service.delete_playlist",
                   new=AsyncMock(return_value=True)):
            resp = self.client.delete("/playlists/u1/pid1")
        self.assertEqual(resp.status_code, 200)

    # A/B test tests
    def test_create_variant_200(self):
        mock_v = {"variant_id": "v1", "label": "A", "content": "x",
                  "clip_id": "c1", "created_at": "t",
                  "impressions": 0, "clicks": 0, "ctr": 0.0}
        with patch("src.services.ab_test_service.create_variant",
                   new=AsyncMock(return_value=mock_v)):
            resp = self.client.post("/ab-tests/c1/variants",
                                    json={"label": "A", "content": "x"})
        self.assertEqual(resp.status_code, 200)

    def test_get_variant_404(self):
        with patch("src.services.ab_test_service.get_variant_stats",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/ab-tests/c1/variants/v1")
        self.assertEqual(resp.status_code, 404)

    def test_record_impression_200(self):
        with patch("src.services.ab_test_service.record_impression",
                   new=AsyncMock(return_value=1)):
            resp = self.client.post("/ab-tests/c1/variants/v1/impression")
        self.assertEqual(resp.status_code, 200)

    def test_record_click_200(self):
        with patch("src.services.ab_test_service.record_click",
                   new=AsyncMock(return_value=1)):
            resp = self.client.post("/ab-tests/c1/variants/v1/click")
        self.assertEqual(resp.status_code, 200)

    # Webhook log tests
    def test_log_webhook_event(self):
        entry = {"event_id": "e1", "event_type": "task.done",
                 "url": "https://hook.test", "payload_summary": "",
                 "status": "pending", "http_status": None,
                 "attempts": 0, "created_at": "t", "delivered_at": None}
        with patch("src.services.webhook_event_log_service.log_event",
                   new=AsyncMock(return_value=entry)):
            resp = self.client.post("/webhook-log/u1",
                                    json={"event_type": "task.done",
                                          "url": "https://hook.test"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["event_type"], "task.done")

    def test_get_webhook_log(self):
        with patch("src.services.webhook_event_log_service.get_event_log",
                   new=AsyncMock(return_value=[])):
            resp = self.client.get("/webhook-log/u1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_update_webhook_status_404(self):
        with patch("src.services.webhook_event_log_service.update_event_status",
                   new=AsyncMock(return_value=False)):
            resp = self.client.patch("/webhook-log/u1/e-nope",
                                     json={"status": "delivered"})
        self.assertEqual(resp.status_code, 404)

    def test_webhook_stats(self):
        stats = {"total": 5, "delivered": 3, "failed": 1, "pending": 1}
        with patch("src.services.webhook_event_log_service.get_event_stats",
                   new=AsyncMock(return_value=stats)):
            resp = self.client.get("/webhook-log/u1/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 5)


if __name__ == "__main__":
    unittest.main()
