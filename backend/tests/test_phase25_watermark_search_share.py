"""
Phase 25 — Watermark, Transcript Search & Share Link Tests

Covers:
  - clip_watermark_service: set/get/delete/apply_watermark
  - transcript_search_service: index/get/delete/search/list
  - clip_share_link_service: create/resolve/list/revoke
  - watermark_search_share API routes
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLIP WATERMARK SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipWatermarkService(unittest.TestCase):
    def _mock_redis(self, hgetall=None, delete=1):
        r = MagicMock()
        r.hset = AsyncMock(return_value=1)
        r.hgetall = AsyncMock(return_value=hgetall or {})
        r.delete = AsyncMock(return_value=delete)
        return r

    def test_set_watermark_stores_text(self):
        from src.services.clip_watermark_service import set_watermark_config
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(set_watermark_config("u1", text="MyBrand"))
        self.assertEqual(result["text"], "MyBrand")
        r.hset.assert_awaited_once()

    def test_set_watermark_raises_on_invalid_position(self):
        from src.services.clip_watermark_service import set_watermark_config
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(set_watermark_config("u1", position="invalid-pos"))

    def test_set_watermark_raises_on_invalid_opacity(self):
        from src.services.clip_watermark_service import set_watermark_config
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(set_watermark_config("u1", opacity=1.5))

    def test_get_watermark_config_defaults(self):
        from src.services.clip_watermark_service import get_watermark_config
        r = self._mock_redis(hgetall={})
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_watermark_config("u1"))
        self.assertEqual(result["text"], "ViraClip")
        self.assertEqual(result["position"], "bottom-right")
        self.assertTrue(result["enabled"])

    def test_get_watermark_config_with_stored_values(self):
        from src.services.clip_watermark_service import get_watermark_config
        stored = {b"text": b"Brand", b"position": b"top-left",
                  b"opacity": b"0.8", b"font_size": b"32",
                  b"color": b"black", b"enabled": b"true"}
        r = self._mock_redis(hgetall=stored)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_watermark_config("u1"))
        self.assertEqual(result["text"], "Brand")
        self.assertEqual(result["opacity"], 0.8)
        self.assertEqual(result["font_size"], 32)

    def test_delete_watermark_config(self):
        from src.services.clip_watermark_service import delete_watermark_config
        r = self._mock_redis(delete=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_watermark_config("u1"))
        self.assertTrue(result)

    def test_apply_watermark_disabled(self):
        from src.services.clip_watermark_service import apply_watermark
        config = {"text": "ViraClip", "position": "bottom-right",
                  "opacity": 0.5, "font_size": 24, "color": "white",
                  "enabled": False}
        with patch("src.services.clip_watermark_service.get_watermark_config",
                   new=AsyncMock(return_value=config)):
            result = run(apply_watermark("u1", "/in.mp4", "/out.mp4"))
        self.assertFalse(result)

    def test_apply_watermark_calls_ffmpeg(self):
        from src.services.clip_watermark_service import apply_watermark
        config = {"text": "Brand", "position": "top-right",
                  "opacity": 0.6, "font_size": 24, "color": "white",
                  "enabled": True}
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=None)
        mock_proc.returncode = 0
        with patch("src.services.clip_watermark_service.get_watermark_config",
                   new=AsyncMock(return_value=config)), \
             patch("asyncio.create_subprocess_exec",
                   new=AsyncMock(return_value=mock_proc)):
            result = run(apply_watermark("u1", "/in.mp4", "/out.mp4"))
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# 2. TRANSCRIPT SEARCH SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestTranscriptSearchService(unittest.TestCase):
    def _mock_redis(self, get_val=None, smembers=None):
        r = MagicMock()
        r.set = AsyncMock(return_value=True)
        r.sadd = AsyncMock(return_value=1)
        r.delete = AsyncMock(return_value=1)
        r.srem = AsyncMock(return_value=1)
        r.get = AsyncMock(return_value=get_val)
        r.smembers = AsyncMock(return_value=smembers or set())
        return r

    def test_index_transcript(self):
        from src.services.transcript_search_service import index_transcript
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            run(index_transcript("u1", "c1", "Hello world"))
        r.set.assert_awaited_once()
        r.sadd.assert_awaited_once()

    def test_get_transcript_returns_text(self):
        from src.services.transcript_search_service import get_transcript
        r = self._mock_redis(get_val=b"Hello world")
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_transcript("u1", "c1"))
        self.assertEqual(result, "Hello world")

    def test_get_transcript_returns_none(self):
        from src.services.transcript_search_service import get_transcript
        r = self._mock_redis(get_val=None)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_transcript("u1", "c1"))
        self.assertIsNone(result)

    def test_search_transcripts_finds_match(self):
        from src.services.transcript_search_service import search_transcripts
        _texts = {
            "transcript:u1:c1": b"The quick brown fox jumps over the lazy dog",
            "transcript:u1:c2": b"Completely unrelated content here",
        }

        async def _get(key):
            return _texts.get(key if isinstance(key, str) else key.decode(), None)

        r = MagicMock()
        r.smembers = AsyncMock(return_value={b"c1", b"c2"})
        r.get = _get
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            results = run(search_transcripts("u1", "fox"))
        matched = [x for x in results if x["clip_id"] == "c1"]
        self.assertEqual(len(matched), 1)
        self.assertGreater(matched[0]["hit_count"], 0)

    def test_search_transcripts_empty_query(self):
        from src.services.transcript_search_service import search_transcripts
        r = MagicMock()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            results = run(search_transcripts("u1", ""))
        self.assertEqual(results, [])

    def test_delete_transcript(self):
        from src.services.transcript_search_service import delete_transcript
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(delete_transcript("u1", "c1"))
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# 3. CLIP SHARE LINK SERVICE
# ═══════════════════════════════════════════════════════════════════════════

def _make_share_entry(token="abc12345"):
    return {
        b"token": token.encode(), b"clip_id": b"c1", b"user_id": b"u1",
        b"created_at": b"t", b"expires_at": b"", b"views": b"3",
    }


class TestClipShareLinkService(unittest.TestCase):
    def _mock_redis(self, scard=0, hgetall=None, hincrby=1,
                   smembers=None, delete=1):
        r = MagicMock()
        r.scard = AsyncMock(return_value=scard)
        r.hset = AsyncMock(return_value=1)
        r.expire = AsyncMock(return_value=True)
        r.sadd = AsyncMock(return_value=1)
        r.hgetall = AsyncMock(return_value=hgetall or {})
        r.hincrby = AsyncMock(return_value=hincrby)
        r.smembers = AsyncMock(return_value=smembers or set())
        r.delete = AsyncMock(return_value=delete)
        r.srem = AsyncMock(return_value=1)
        return r

    def test_create_share_link(self):
        from src.services.clip_share_link_service import create_share_link
        r = self._mock_redis(scard=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(create_share_link("c1", "u1"))
        self.assertIn("token", result)
        self.assertEqual(len(result["token"]), 8)
        r.hset.assert_awaited_once()

    def test_create_share_link_raises_at_max(self):
        from src.services.clip_share_link_service import create_share_link, _MAX_LINKS_PER_CLIP
        r = self._mock_redis(scard=_MAX_LINKS_PER_CLIP)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(create_share_link("c1", "u1"))

    def test_resolve_share_link_increments_views(self):
        from src.services.clip_share_link_service import resolve_share_link
        r = self._mock_redis(hgetall=_make_share_entry(), hincrby=4)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(resolve_share_link("abc12345"))
        self.assertEqual(result["views"], 4)

    def test_resolve_share_link_returns_none_when_missing(self):
        from src.services.clip_share_link_service import resolve_share_link
        r = self._mock_redis(hgetall={})
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(resolve_share_link("nope1234"))
        self.assertIsNone(result)

    def test_revoke_share_link(self):
        from src.services.clip_share_link_service import revoke_share_link
        r = self._mock_redis(delete=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(revoke_share_link("c1", "abc12345"))
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# 4. WATERMARK / SEARCH / SHARE API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_p25_app():
    from fastapi import FastAPI
    from src.api.routes.watermark_search_share import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestWatermarkSearchShareApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_p25_app())

    # Watermark tests
    def test_get_watermark_config(self):
        config = {"text": "ViraClip", "position": "bottom-right",
                  "opacity": 0.5, "font_size": 24, "color": "white", "enabled": True}
        with patch("src.services.clip_watermark_service.get_watermark_config",
                   new=AsyncMock(return_value=config)):
            resp = self.client.get("/watermark/u1")
        self.assertEqual(resp.status_code, 200)

    def test_update_watermark_400_invalid(self):
        with patch("src.services.clip_watermark_service.set_watermark_config",
                   new=AsyncMock(side_effect=ValueError("invalid position"))):
            resp = self.client.put("/watermark/u1", json={"position": "bad"})
        self.assertEqual(resp.status_code, 400)

    def test_apply_watermark(self):
        with patch("src.services.clip_watermark_service.apply_watermark",
                   new=AsyncMock(return_value=True)):
            resp = self.client.post("/watermark/u1/apply",
                                    json={"input_path": "/in.mp4",
                                          "output_path": "/out.mp4"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    # Transcript search tests
    def test_index_transcript(self):
        with patch("src.services.transcript_search_service.index_transcript",
                   new=AsyncMock(return_value=None)):
            resp = self.client.post("/transcripts/u1/c1",
                                    json={"transcript": "hello world"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["indexed"])

    def test_get_transcript_404(self):
        with patch("src.services.transcript_search_service.get_transcript",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/transcripts/u1/c1")
        self.assertEqual(resp.status_code, 404)

    def test_search_transcripts(self):
        results = [{"clip_id": "c1", "hit_count": 2, "snippet": "...fox..."}]
        with patch("src.services.transcript_search_service.search_transcripts",
                   new=AsyncMock(return_value=results)):
            resp = self.client.get("/transcripts/u1/search?q=fox")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    # Share link tests
    def test_create_share_link_200(self):
        link = {"token": "abc12345", "clip_id": "c1", "user_id": "u1",
                "created_at": "t", "expires_at": None, "views": 0}
        with patch("src.services.clip_share_link_service.create_share_link",
                   new=AsyncMock(return_value=link)):
            resp = self.client.post("/share/c1",
                                    json={"user_id": "u1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["token"], "abc12345")

    def test_create_share_link_400_on_overflow(self):
        with patch("src.services.clip_share_link_service.create_share_link",
                   new=AsyncMock(side_effect=ValueError("max links"))):
            resp = self.client.post("/share/c1", json={"user_id": "u1"})
        self.assertEqual(resp.status_code, 400)

    def test_resolve_share_link_404(self):
        with patch("src.services.clip_share_link_service.resolve_share_link",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/share/resolve/nope1234")
        self.assertEqual(resp.status_code, 404)

    def test_revoke_share_link_404(self):
        with patch("src.services.clip_share_link_service.revoke_share_link",
                   new=AsyncMock(return_value=False)):
            resp = self.client.delete("/share/c1/nope1234")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
