"""
Phase 24 — Clip Chapters, Caption Variants & User Activity Log Tests

Covers:
  - clip_chapter_service: add/get/remove/clear/at_time
  - caption_variant_service: generate_variants, get_or_generate, clear
  - user_activity_log_service: log_action/get_log/stats/clear
  - clip_chapters_captions API routes
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLIP CHAPTER SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_chapter_json(chapter_id="ch1", start=0.0, end=30.0):
    return json.dumps({
        "chapter_id": chapter_id, "clip_id": "c1",
        "title": "Intro", "start_time": start,
        "end_time": end, "description": "", "created_at": "t",
    }).encode()


class TestClipChapterService(unittest.TestCase):
    def _mock_redis(self, zcard=0, zrange=None, zrem=1, zcard_after=0):
        r = MagicMock()
        r.zcard = AsyncMock(side_effect=[zcard, zcard_after])
        r.zadd = AsyncMock(return_value=1)
        r.hset = AsyncMock(return_value=1)
        r.zrange = AsyncMock(return_value=zrange or [])
        r.zrem = AsyncMock(return_value=zrem)
        r.delete = AsyncMock(return_value=1)
        return r

    def test_add_chapter(self):
        from src.services.clip_chapter_service import add_chapter
        r = self._mock_redis(zcard=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(add_chapter("c1", "Intro", 0.0, 30.0))
        self.assertEqual(result["title"], "Intro")
        self.assertEqual(result["start_time"], 0.0)
        r.zadd.assert_awaited_once()

    def test_add_chapter_raises_at_max(self):
        from src.services.clip_chapter_service import add_chapter, _MAX_CHAPTERS
        r = MagicMock()
        r.zcard = AsyncMock(return_value=_MAX_CHAPTERS)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(add_chapter("c1", "Overflow", 100.0))

    def test_get_chapters_returns_list(self):
        from src.services.clip_chapter_service import get_chapters
        items = [_make_chapter_json("ch1", 0.0, 30.0),
                 _make_chapter_json("ch2", 30.0, 60.0)]
        r = MagicMock()
        r.zrange = AsyncMock(return_value=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_chapters("c1"))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["chapter_id"], "ch1")

    def test_get_chapters_empty(self):
        from src.services.clip_chapter_service import get_chapters
        r = MagicMock()
        r.zrange = AsyncMock(return_value=[])
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_chapters("c1"))
        self.assertEqual(result, [])

    def test_remove_chapter_found(self):
        from src.services.clip_chapter_service import remove_chapter
        items = [_make_chapter_json("ch1", 0.0, 30.0)]
        r = MagicMock()
        r.zrange = AsyncMock(return_value=items)
        r.zrem = AsyncMock(return_value=1)
        r.zcard = AsyncMock(return_value=0)
        r.hset = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(remove_chapter("c1", "ch1"))
        self.assertTrue(result)

    def test_remove_chapter_not_found(self):
        from src.services.clip_chapter_service import remove_chapter
        items = [_make_chapter_json("ch1", 0.0, 30.0)]
        r = MagicMock()
        r.zrange = AsyncMock(return_value=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(remove_chapter("c1", "no-such-id"))
        self.assertFalse(result)

    def test_clear_chapters(self):
        from src.services.clip_chapter_service import clear_chapters
        r = MagicMock()
        r.zcard = AsyncMock(return_value=3)
        r.delete = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            count = run(clear_chapters("c1"))
        self.assertEqual(count, 3)

    def test_get_chapter_at_time(self):
        from src.services.clip_chapter_service import get_chapter_at_time
        items = [_make_chapter_json("ch1", 0.0, 30.0),
                 _make_chapter_json("ch2", 30.0, 60.0)]
        r = MagicMock()
        r.zrange = AsyncMock(return_value=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_chapter_at_time("c1", 15.0))
        self.assertIsNotNone(result)
        self.assertEqual(result["chapter_id"], "ch1")

    def test_get_chapter_at_time_none(self):
        from src.services.clip_chapter_service import get_chapter_at_time
        r = MagicMock()
        r.zrange = AsyncMock(return_value=[])
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_chapter_at_time("c1", 15.0))
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════
# 2. CAPTION VARIANT SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestCaptionVariantService(unittest.TestCase):
    def test_generate_variants_returns_five_styles(self):
        from src.services.caption_variant_service import generate_variants
        variants = generate_variants("My Amazing Clip")
        styles = {v["style"] for v in variants}
        self.assertEqual(len(variants), 5)
        self.assertIn("hook", styles)
        self.assertIn("question", styles)
        self.assertIn("statement", styles)
        self.assertIn("listicle", styles)
        self.assertIn("challenge", styles)

    def test_generate_variants_with_keywords(self):
        from src.services.caption_variant_service import generate_variants
        variants = generate_variants("Test Title", keywords=["pizza"])
        hook = next(v for v in variants if v["style"] == "hook")
        self.assertIn("pizza", hook["caption"])

    def test_get_or_generate_uses_cache(self):
        from src.services.caption_variant_service import get_or_generate_variants
        cached = {"clip_id": "c1", "title": "T", "generated_at": "t",
                  "variants": [{"style": "hook", "caption": "cached!"}]}
        with patch("src.services.caption_variant_service._get_cached",
                   new=AsyncMock(return_value=cached)), \
             patch("src.services.caption_variant_service._set_cached",
                   new=AsyncMock()):
            result = run(get_or_generate_variants("c1", "Test"))
        self.assertEqual(result["variants"][0]["caption"], "cached!")

    def test_get_or_generate_force_bypasses_cache(self):
        from src.services.caption_variant_service import get_or_generate_variants
        with patch("src.services.caption_variant_service._get_cached",
                   new=AsyncMock(return_value=None)), \
             patch("src.services.caption_variant_service._set_cached",
                   new=AsyncMock()) as mock_set:
            result = run(get_or_generate_variants("c1", "My Video", force=True))
        self.assertEqual(len(result["variants"]), 5)

    def test_clear_variants(self):
        from src.services.caption_variant_service import clear_variants
        r = MagicMock()
        r.delete = AsyncMock(return_value=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            run(clear_variants("c1"))
        r.delete.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# 3. USER ACTIVITY LOG SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_activity_entry(action="clip.created", resource_type="clip"):
    return json.dumps({
        "log_id": "lg1", "user_id": "u1",
        "action": action, "resource_type": resource_type,
        "resource_id": "c1", "metadata": {},
        "created_at": "t",
    }).encode()


class TestUserActivityLogService(unittest.TestCase):
    def _mock_redis(self, items=None):
        r = MagicMock()
        r.lpush = AsyncMock(return_value=1)
        r.ltrim = AsyncMock(return_value=True)
        r.expire = AsyncMock(return_value=True)
        r.lrange = AsyncMock(return_value=items or [])
        r.delete = AsyncMock(return_value=1)
        return r

    def test_log_action_returns_record(self):
        from src.services.user_activity_log_service import log_action
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(log_action("u1", "clip.created", "clip", "c1"))
        self.assertEqual(result["action"], "clip.created")
        self.assertIn("log_id", result)

    def test_get_activity_log(self):
        from src.services.user_activity_log_service import get_activity_log
        items = [_make_activity_entry("clip.created"),
                 _make_activity_entry("clip.exported")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_activity_log("u1"))
        self.assertEqual(len(result), 2)

    def test_get_activity_log_action_filter(self):
        from src.services.user_activity_log_service import get_activity_log
        items = [_make_activity_entry("clip.created"),
                 _make_activity_entry("clip.exported")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_activity_log("u1", action_filter="clip.created"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "clip.created")

    def test_get_activity_stats(self):
        from src.services.user_activity_log_service import get_activity_stats
        items = [_make_activity_entry("clip.created"),
                 _make_activity_entry("clip.created"),
                 _make_activity_entry("clip.exported")]
        r = self._mock_redis(items=items)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_activity_stats("u1"))
        self.assertEqual(result["total_actions"], 3)
        self.assertEqual(result["action_counts"]["clip.created"], 2)

    def test_clear_activity_log(self):
        from src.services.user_activity_log_service import clear_activity_log
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            run(clear_activity_log("u1"))
        r.delete.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# 4. API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_p24_app():
    from fastapi import FastAPI
    from src.api.routes.clip_chapters_captions import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestClipChaptersCaptionsApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_p24_app())

    # Chapter tests
    def test_add_chapter_200(self):
        chapter = {"chapter_id": "ch1", "clip_id": "c1", "title": "Intro",
                   "start_time": 0.0, "end_time": 30.0, "description": "",
                   "created_at": "t"}
        with patch("src.services.clip_chapter_service.add_chapter",
                   new=AsyncMock(return_value=chapter)):
            resp = self.client.post("/clips/c1/chapters",
                                    json={"title": "Intro", "start_time": 0.0})
        self.assertEqual(resp.status_code, 200)

    def test_add_chapter_400_on_overflow(self):
        with patch("src.services.clip_chapter_service.add_chapter",
                   new=AsyncMock(side_effect=ValueError("max chapters"))):
            resp = self.client.post("/clips/c1/chapters",
                                    json={"title": "X", "start_time": 0.0})
        self.assertEqual(resp.status_code, 400)

    def test_get_chapters_200(self):
        with patch("src.services.clip_chapter_service.get_chapters",
                   new=AsyncMock(return_value=[])):
            resp = self.client.get("/clips/c1/chapters")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_remove_chapter_404(self):
        with patch("src.services.clip_chapter_service.remove_chapter",
                   new=AsyncMock(return_value=False)):
            resp = self.client.delete("/clips/c1/chapters/ch-nope")
        self.assertEqual(resp.status_code, 404)

    def test_chapter_at_time_404(self):
        with patch("src.services.clip_chapter_service.get_chapter_at_time",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/clips/c1/chapters/at/999.0")
        self.assertEqual(resp.status_code, 404)

    # Caption variant tests
    def test_get_caption_variants_200(self):
        result = {"clip_id": "c1", "title": "Test", "generated_at": "t",
                  "variants": [{"style": "hook", "caption": "Hook!"}]}
        with patch("src.services.caption_variant_service.get_or_generate_variants",
                   new=AsyncMock(return_value=result)):
            resp = self.client.get("/clips/c1/caption-variants?title=Test")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["variants"]), 1)

    def test_clear_caption_variants_200(self):
        with patch("src.services.caption_variant_service.clear_variants",
                   new=AsyncMock(return_value=None)):
            resp = self.client.delete("/clips/c1/caption-variants")
        self.assertEqual(resp.status_code, 200)

    # Activity log tests
    def test_log_action_200(self):
        record = {"log_id": "lg1", "user_id": "u1", "action": "clip.created",
                  "resource_type": "clip", "resource_id": "c1",
                  "metadata": {}, "created_at": "t"}
        with patch("src.services.user_activity_log_service.log_action",
                   new=AsyncMock(return_value=record)):
            resp = self.client.post("/activity/u1",
                                    json={"action": "clip.created"})
        self.assertEqual(resp.status_code, 200)

    def test_get_activity_log_200(self):
        with patch("src.services.user_activity_log_service.get_activity_log",
                   new=AsyncMock(return_value=[])):
            resp = self.client.get("/activity/u1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_activity_stats_200(self):
        stats = {"user_id": "u1", "total_actions": 5,
                 "action_counts": {"clip.created": 3, "clip.exported": 2}}
        with patch("src.services.user_activity_log_service.get_activity_stats",
                   new=AsyncMock(return_value=stats)):
            resp = self.client.get("/activity/u1/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_actions"], 5)


if __name__ == "__main__":
    unittest.main()
