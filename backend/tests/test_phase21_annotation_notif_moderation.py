"""
Phase 21 — Clip Annotation, In-App Notifications & Content Moderation Tests

Covers:
  - clip_annotation_service: set/get/delete/update_field
  - inapp_notification_service: push/get/mark_read/mark_all/clear/unread_count
  - content_moderation_service: scan_transcript, moderate_clip, get/clear cache
  - clip_moderation API routes: annotations, moderation, notifications
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLIP ANNOTATION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipAnnotationService(unittest.TestCase):
    def _mock_redis(self, existing_created_at=None, hgetall_data=None, exists=1):
        r = MagicMock()
        r.hget = AsyncMock(return_value=existing_created_at.encode() if existing_created_at else None)
        r.hset = AsyncMock(return_value=1)
        r.hgetall = AsyncMock(return_value=hgetall_data or {})
        r.delete = AsyncMock(return_value=1)
        r.exists = AsyncMock(return_value=exists)
        return r

    def test_set_annotation_stores_fields(self):
        from src.services.clip_annotation_service import set_annotation
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(set_annotation("c1", "Great clip!", author="u1"))
        self.assertEqual(result["note"], "Great clip!")
        self.assertEqual(result["author"], "u1")
        self.assertIn("created_at", result)
        r.hset.assert_awaited_once()

    def test_set_annotation_raises_on_too_long(self):
        from src.services.clip_annotation_service import set_annotation, _NOTE_MAX_LEN
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(set_annotation("c1", "x" * (_NOTE_MAX_LEN + 1)))

    def test_get_annotation_returns_dict(self):
        from src.services.clip_annotation_service import get_annotation
        data = {b"note": b"test", b"author": b"u1",
                b"created_at": b"2026-01-01", b"updated_at": b"2026-01-01"}
        r = self._mock_redis(hgetall_data=data)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_annotation("c1"))
        self.assertIsNotNone(result)
        self.assertEqual(result["note"], "test")

    def test_get_annotation_returns_none_when_empty(self):
        from src.services.clip_annotation_service import get_annotation
        r = self._mock_redis(hgetall_data={})
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_annotation("c1"))
        self.assertIsNone(result)

    def test_delete_annotation(self):
        from src.services.clip_annotation_service import delete_annotation
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_annotation("c1"))
        self.assertTrue(result)
        r.delete.assert_awaited_once()

    def test_update_annotation_field(self):
        from src.services.clip_annotation_service import update_annotation_field
        r = self._mock_redis(exists=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(update_annotation_field("c1", "note", "Updated!"))
        self.assertTrue(result)

    def test_update_annotation_field_returns_false_when_not_exists(self):
        from src.services.clip_annotation_service import update_annotation_field
        r = self._mock_redis(exists=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(update_annotation_field("c1", "note", "Updated!"))
        self.assertFalse(result)


# ═══════════════════════════════════════════════════════════════════════════
# 2. IN-APP NOTIFICATION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_notif_json(notif_id="n1", read=False, notif_type="info"):
    return json.dumps({"id": notif_id, "type": notif_type,
                       "title": "T", "body": "B", "read": read,
                       "created_at": "2026-01-01"}).encode()


class TestInAppNotificationService(unittest.TestCase):
    def _mock_redis(self, items=None):
        r = MagicMock()
        r.lpush = AsyncMock(return_value=1)
        r.ltrim = AsyncMock(return_value=True)
        r.lrange = AsyncMock(return_value=items or [])
        r.lset = AsyncMock(return_value=True)
        r.delete = AsyncMock(return_value=1)
        return r

    def test_push_notification(self):
        from src.services.inapp_notification_service import push_notification
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(push_notification("u1", "info", "Hello", "World"))
        self.assertEqual(result["title"], "Hello")
        self.assertFalse(result["read"])
        r.lpush.assert_awaited_once()

    def test_get_notifications_returns_list(self):
        from src.services.inapp_notification_service import get_notifications
        items = [_make_notif_json("n1", read=False), _make_notif_json("n2", read=True)]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_notifications("u1", limit=10))
        self.assertEqual(len(result), 2)

    def test_get_notifications_unread_only(self):
        from src.services.inapp_notification_service import get_notifications
        items = [_make_notif_json("n1", read=False), _make_notif_json("n2", read=True)]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_notifications("u1", unread_only=True))
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["read"])

    def test_mark_read(self):
        from src.services.inapp_notification_service import mark_read
        items = [_make_notif_json("n1", read=False)]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(mark_read("u1", "n1"))
        self.assertTrue(result)
        r.lset.assert_awaited_once()

    def test_mark_read_not_found(self):
        from src.services.inapp_notification_service import mark_read
        items = [_make_notif_json("n1", read=False)]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(mark_read("u1", "no-such-id"))
        self.assertFalse(result)

    def test_mark_all_read(self):
        from src.services.inapp_notification_service import mark_all_read
        items = [_make_notif_json("n1", read=False), _make_notif_json("n2", read=False)]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            count = run(mark_all_read("u1"))
        self.assertEqual(count, 2)

    def test_clear_notifications(self):
        from src.services.inapp_notification_service import clear_notifications
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            run(clear_notifications("u1"))
        r.delete.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# 3. CONTENT MODERATION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestContentModerationService(unittest.TestCase):
    def test_scan_clean_transcript(self):
        from src.services.content_moderation_service import scan_transcript
        result = scan_transcript("This is a great video about cooking.")
        self.assertFalse(result["flagged"])
        self.assertEqual(result["severity"], "none")
        self.assertEqual(result["total_hits"], 0)

    def test_scan_detects_profanity(self):
        from src.services.content_moderation_service import scan_transcript
        result = scan_transcript("What the fuck is this shit!")
        self.assertTrue(result["flagged"])
        self.assertGreater(result["categories"]["profanity"], 0)

    def test_scan_detects_violence(self):
        from src.services.content_moderation_service import scan_transcript
        result = scan_transcript("They shoot and kill people in this movie.")
        self.assertTrue(result["flagged"])
        self.assertGreater(result["categories"]["violence"], 0)

    def test_severity_levels(self):
        from src.services.content_moderation_service import scan_transcript
        low = scan_transcript("fuck")
        self.assertEqual(low["severity"], "low")
        high = scan_transcript("fuck shit fuck kill murder shoot blood stab fuck shit fuck")
        self.assertEqual(high["severity"], "high")

    def test_moderate_clip_uses_cache(self):
        from src.services.content_moderation_service import moderate_clip
        cached = {"clip_id": "c1", "flagged": False, "severity": "none",
                  "categories": {}, "total_hits": 0}
        with patch("src.services.content_moderation_service._get_cached",
                   new=AsyncMock(return_value=cached)), \
             patch("src.services.content_moderation_service._set_cached",
                   new=AsyncMock(return_value=None)):
            result = run(moderate_clip("c1", "clean text"))
        self.assertEqual(result["severity"], "none")

    def test_moderate_clip_stores_result(self):
        from src.services.content_moderation_service import moderate_clip
        with patch("src.services.content_moderation_service._get_cached",
                   new=AsyncMock(return_value=None)), \
             patch("src.services.content_moderation_service._set_cached",
                   new=AsyncMock(return_value=None)) as mock_set:
            result = run(moderate_clip("c1", "fuck this shit"))
        self.assertTrue(result["flagged"])


# ═══════════════════════════════════════════════════════════════════════════
# 4. CLIP MODERATION API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_moderation_app():
    from fastapi import FastAPI
    from src.api.routes.clip_moderation import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestClipModerationApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_moderation_app())

    # Annotation tests
    def test_get_annotation_404(self):
        with patch("src.services.clip_annotation_service.get_annotation",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/clips/c1/annotation")
        self.assertEqual(resp.status_code, 404)

    def test_get_annotation_200(self):
        ann = {"note": "test", "author": "u1", "created_at": "t", "updated_at": "t"}
        with patch("src.services.clip_annotation_service.get_annotation",
                   new=AsyncMock(return_value=ann)):
            resp = self.client.get("/clips/c1/annotation")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["annotation"]["note"], "test")

    def test_set_annotation_200(self):
        ann = {"note": "Hello", "author": "u1", "created_at": "t", "updated_at": "t"}
        with patch("src.services.clip_annotation_service.set_annotation",
                   new=AsyncMock(return_value=ann)):
            resp = self.client.put("/clips/c1/annotation",
                                   json={"note": "Hello", "author": "u1"})
        self.assertEqual(resp.status_code, 200)

    def test_set_annotation_400_on_value_error(self):
        with patch("src.services.clip_annotation_service.set_annotation",
                   new=AsyncMock(side_effect=ValueError("too long"))):
            resp = self.client.put("/clips/c1/annotation",
                                   json={"note": "x" * 3000})
        self.assertEqual(resp.status_code, 400)

    def test_delete_annotation_200(self):
        with patch("src.services.clip_annotation_service.delete_annotation",
                   new=AsyncMock(return_value=True)):
            resp = self.client.delete("/clips/c1/annotation")
        self.assertEqual(resp.status_code, 200)

    def test_delete_annotation_404(self):
        with patch("src.services.clip_annotation_service.delete_annotation",
                   new=AsyncMock(return_value=False)):
            resp = self.client.delete("/clips/c1/annotation")
        self.assertEqual(resp.status_code, 404)

    # Moderation tests
    def test_moderate_clip_post(self):
        mock_result = {"clip_id": "c1", "flagged": True, "severity": "low",
                       "categories": {"profanity": 1}, "total_hits": 1}
        with patch("src.services.content_moderation_service.moderate_clip",
                   new=AsyncMock(return_value=mock_result)):
            resp = self.client.post("/clips/c1/moderate",
                                    json={"transcript": "fuck"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["flagged"])

    def test_get_moderation_404_when_not_cached(self):
        with patch("src.services.content_moderation_service.get_moderation_result",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/clips/c1/moderate")
        self.assertEqual(resp.status_code, 404)

    # Notification tests
    def test_push_notification(self):
        notif = {"id": "n1", "type": "info", "title": "Hi",
                 "body": "", "read": False, "created_at": "t"}
        with patch("src.services.inapp_notification_service.push_notification",
                   new=AsyncMock(return_value=notif)):
            resp = self.client.post("/notifications/u1",
                                    json={"type": "info", "title": "Hi"})
        self.assertEqual(resp.status_code, 200)

    def test_list_notifications(self):
        notifs = [{"id": "n1", "type": "info", "title": "T",
                   "body": "", "read": False, "created_at": "t"}]
        with patch("src.services.inapp_notification_service.get_notifications",
                   new=AsyncMock(return_value=notifs)):
            resp = self.client.get("/notifications/u1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_mark_notification_read_404(self):
        with patch("src.services.inapp_notification_service.mark_read",
                   new=AsyncMock(return_value=False)):
            resp = self.client.patch("/notifications/u1/n-nope/read")
        self.assertEqual(resp.status_code, 404)

    def test_unread_count(self):
        with patch("src.services.inapp_notification_service.unread_count",
                   new=AsyncMock(return_value=5)):
            resp = self.client.get("/notifications/u1/unread-count")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unread_count"], 5)


if __name__ == "__main__":
    unittest.main()
