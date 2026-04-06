"""
Phase 16 — Export, Clip Search & Webhook Security Tests

Covers:
  - export_service: build_task_zip (all present, some missing, metadata)
  - clip_search_service: search_clips, get_search_facets
  - webhook_security_service: TikTok, Meta, YouTube HMAC verification
  - Export API routes: /export/tasks/{id}/zip and /zip/info
  - Clip search API routes: /clips/search and /clips/facets
"""

import asyncio
import hashlib
import hmac
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. EXPORT SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildTaskZip(unittest.TestCase):
    def _make_clips(self, tmpdir: str, count: int = 3):
        clips = []
        for i in range(count):
            p = Path(tmpdir) / f"clip_{i+1}.mp4"
            p.write_bytes(b"fake video data " * (i + 1))
            clips.append({
                "filename": p.name,
                "file_path": str(p),
                "start_time": f"00:0{i}",
                "end_time": f"00:0{i+1}",
                "duration": 10.0 + i,
                "virality_score": 70 + i * 5,
                "hook_score": 60,
                "relevance_score": 0.85,
                "text": f"Transcript segment {i}",
                "hook_type": "question",
                "social_title": f"Clip {i+1}",
                "suggested_hashtags": ["#viral", "#test"],
            })
        return clips

    def test_all_files_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clips = self._make_clips(tmpdir, 3)
            buf = run(build_task_zip(clips, task_title="My Test Task"))
            self.assertIsInstance(buf, io.BytesIO)
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
                # 3 mp4 files + metadata.json
                self.assertEqual(len(names), 4)
                mp4s = [n for n in names if n.endswith(".mp4")]
                self.assertEqual(len(mp4s), 3)

    def test_metadata_json_included_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clips = self._make_clips(tmpdir, 2)
            buf = run(build_task_zip(clips, task_title="MyTask"))
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
                meta_names = [n for n in names if "metadata.json" in n]
                self.assertEqual(len(meta_names), 1)
                meta = json.loads(zf.read(meta_names[0]))
                self.assertEqual(meta["total_clips"], 2)
                self.assertEqual(meta["exported_clips"], 2)
                self.assertEqual(meta["missing_files"], [])

    def test_metadata_json_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clips = self._make_clips(tmpdir, 2)
            buf = run(build_task_zip(clips, task_title="NoMeta",
                                     include_metadata=False))
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
                meta_names = [n for n in names if "metadata.json" in n]
                self.assertEqual(len(meta_names), 0)

    def test_missing_files_tracked(self):
        clips = [
            {"filename": "missing.mp4", "file_path": "/nonexistent/missing.mp4",
             "virality_score": 0, "hook_score": 0, "relevance_score": 0, "duration": 5},
        ]
        buf = run(build_task_zip(clips, task_title="Missing"))
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            meta_entry = [n for n in names if "metadata.json" in n]
            meta = json.loads(zf.read(meta_entry[0]))
            self.assertEqual(meta["missing_files"], ["missing.mp4"])
            self.assertEqual(meta["exported_clips"], 0)

    def test_empty_clips_list(self):
        buf = run(build_task_zip([], task_title="Empty"))
        with zipfile.ZipFile(buf) as zf:
            self.assertEqual(len(zf.namelist()), 0)

    def test_safe_folder_name_strips_special_chars(self):
        from src.services.export_service import _safe_folder_name
        result = _safe_folder_name("My/Task/../Test")
        self.assertNotIn("/", result)
        self.assertNotIn(".", result)
        self.assertTrue(result.startswith("My"))
        self.assertTrue(result.endswith("Test"))

    def test_folder_name_truncated_to_64(self):
        from src.services.export_service import _safe_folder_name
        long_name = "a" * 200
        self.assertLessEqual(len(_safe_folder_name(long_name)), 64)

    def test_zip_seeked_to_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clips = self._make_clips(tmpdir, 1)
            buf = run(build_task_zip(clips))
            self.assertEqual(buf.tell(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 2. WEBHOOK SECURITY SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestWebhookSecurity(unittest.TestCase):
    def _make_tiktok_sig(self, secret: bytes, body: bytes) -> str:
        return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    def _make_meta_sig(self, secret: bytes, body: bytes) -> str:
        return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    def _make_yt_sig(self, secret: bytes, body: bytes) -> str:
        return "sha1=" + hmac.new(secret, body, hashlib.sha1).hexdigest()

    def test_tiktok_valid_signature(self):
        from src.services.webhook_security_service import verify_tiktok_webhook
        secret = b"my_tiktok_secret"
        body = b'{"event":"post.published","data":{"id":"123"}}'
        sig = self._make_tiktok_sig(secret, body)
        with patch.dict(os.environ, {"TIKTOK_WEBHOOK_SECRET": "my_tiktok_secret"}):
            self.assertTrue(verify_tiktok_webhook(body, sig))

    def test_tiktok_invalid_signature(self):
        from src.services.webhook_security_service import verify_tiktok_webhook
        body = b"payload"
        with patch.dict(os.environ, {"TIKTOK_WEBHOOK_SECRET": "real_secret"}):
            self.assertFalse(verify_tiktok_webhook(body, "sha256=badhex"))

    def test_tiktok_skipped_when_no_secret(self):
        from src.services.webhook_security_service import verify_tiktok_webhook
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TIKTOK_WEBHOOK_SECRET", None)
            self.assertTrue(verify_tiktok_webhook(b"any", "sha256=anything"))

    def test_meta_valid_signature(self):
        from src.services.webhook_security_service import verify_meta_webhook
        secret = b"meta_secret"
        body = b'{"object":"instagram","entry":[]}'
        sig = self._make_meta_sig(secret, body)
        with patch.dict(os.environ, {"META_WEBHOOK_SECRET": "meta_secret"}):
            self.assertTrue(verify_meta_webhook(body, sig))

    def test_meta_invalid_signature(self):
        from src.services.webhook_security_service import verify_meta_webhook
        with patch.dict(os.environ, {"META_WEBHOOK_SECRET": "real"}):
            self.assertFalse(verify_meta_webhook(b"body", "sha256=wronghex"))

    def test_youtube_valid_signature(self):
        from src.services.webhook_security_service import verify_youtube_webhook
        secret = b"yt_secret"
        body = b"<feed>...</feed>"
        sig = self._make_yt_sig(secret, body)
        with patch.dict(os.environ, {"YOUTUBE_WEBHOOK_SECRET": "yt_secret"}):
            self.assertTrue(verify_youtube_webhook(body, sig))

    def test_youtube_invalid_signature(self):
        from src.services.webhook_security_service import verify_youtube_webhook
        with patch.dict(os.environ, {"YOUTUBE_WEBHOOK_SECRET": "secret"}):
            self.assertFalse(verify_youtube_webhook(b"body", "sha1=badhex"))

    def test_youtube_wrong_prefix(self):
        from src.services.webhook_security_service import verify_youtube_webhook
        with patch.dict(os.environ, {"YOUTUBE_WEBHOOK_SECRET": "secret"}):
            self.assertFalse(verify_youtube_webhook(b"body", "sha256=something"))

    def test_dispatcher_tiktok(self):
        from src.services.webhook_security_service import verify_webhook
        secret = b"s"
        body = b"data"
        sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {"TIKTOK_WEBHOOK_SECRET": "s"}):
            self.assertTrue(verify_webhook("tiktok", body, tiktok_signature=sig))

    def test_dispatcher_instagram(self):
        from src.services.webhook_security_service import verify_webhook
        secret = b"s"
        body = b"data"
        sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {"META_WEBHOOK_SECRET": "s"}):
            self.assertTrue(verify_webhook("instagram", body, meta_signature=sig))

    def test_dispatcher_unknown_platform(self):
        from src.services.webhook_security_service import verify_webhook
        self.assertFalse(verify_webhook("twitch", b"body"))

    def test_timing_safe_comparison(self):
        from src.services.webhook_security_service import _verify_hmac_sha256
        secret = b"sec"
        body = b"payload"
        good = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        self.assertTrue(_verify_hmac_sha256(secret, body, good))
        self.assertFalse(_verify_hmac_sha256(secret, body, "sha256=" + "0" * 64))


# ═══════════════════════════════════════════════════════════════════════════
# 3. EXPORT API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_export_app():
    from fastapi import FastAPI
    from src.api.routes.export import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestExportApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_export_app())

    def test_zip_info_404_unknown_task(self):
        with patch("src.repositories.task_repository.TaskRepository.get_task_by_id",
                   new=AsyncMock(return_value=None)):
            resp = self.client.get("/export/tasks/unknown/zip/info")
            self.assertEqual(resp.status_code, 404)

    def test_zip_info_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "clip.mp4"
            p.write_bytes(b"data")
            mock_task = {"id": "t1", "source_title": "Test"}
            mock_clips = [{"file_path": str(p), "filename": "clip.mp4"}]
            with patch("src.repositories.task_repository.TaskRepository.get_task_by_id",
                       new=AsyncMock(return_value=mock_task)), \
                 patch("src.repositories.clip_repository.ClipRepository.get_clips_by_task",
                       new=AsyncMock(return_value=mock_clips)):
                resp = self.client.get("/export/tasks/t1/zip/info")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["total_clips"], 1)
                self.assertEqual(data["missing_files"], 0)
                self.assertTrue(data["ready"])

    def test_zip_422_no_clips(self):
        with patch("src.repositories.task_repository.TaskRepository.get_task_by_id",
                   new=AsyncMock(return_value={"id": "t1", "source_title": "T"})), \
             patch("src.repositories.clip_repository.ClipRepository.get_clips_by_task",
                   new=AsyncMock(return_value=[])):
            resp = self.client.post("/export/tasks/t1/zip")
            self.assertEqual(resp.status_code, 422)

    def test_zip_404_unknown_task(self):
        with patch("src.repositories.task_repository.TaskRepository.get_task_by_id",
                   new=AsyncMock(return_value=None)):
            resp = self.client.post("/export/tasks/unknown/zip")
            self.assertEqual(resp.status_code, 404)

    def test_zip_returns_zip_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "clip.mp4"
            p.write_bytes(b"video data")
            mock_task = {"id": "t1", "source_title": "Test Task"}
            mock_clips = [{
                "file_path": str(p), "filename": "clip.mp4",
                "start_time": "00:00", "end_time": "00:10",
                "duration": 10.0, "virality_score": 75,
                "hook_score": 60, "relevance_score": 0.8,
                "text": "hello world", "hook_type": "question",
                "social_title": None, "suggested_hashtags": [],
            }]
            with patch("src.repositories.task_repository.TaskRepository.get_task_by_id",
                       new=AsyncMock(return_value=mock_task)), \
                 patch("src.repositories.clip_repository.ClipRepository.get_clips_by_task",
                       new=AsyncMock(return_value=mock_clips)):
                resp = self.client.post("/export/tasks/t1/zip")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.headers["content-type"], "application/zip")
                self.assertIn("attachment", resp.headers["content-disposition"])
                buf = io.BytesIO(resp.content)
                with zipfile.ZipFile(buf) as zf:
                    names = zf.namelist()
                    self.assertTrue(any("clip.mp4" in n for n in names))


# ═══════════════════════════════════════════════════════════════════════════
# 4. CLIP SEARCH API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_search_app():
    from fastapi import FastAPI
    from src.api.routes.clip_search import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestClipSearchApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_search_app())

    def test_search_requires_user_id(self):
        resp = self.client.get("/clips/search")
        self.assertEqual(resp.status_code, 422)

    def test_search_returns_results(self):
        mock_result = {
            "clips": [{"id": "c1", "virality_score": 80, "text": "hello"}],
            "total": 1,
            "limit": 50,
            "offset": 0,
        }
        with patch("src.api.routes.clip_search.search_clips",
                   new=AsyncMock(return_value=mock_result)):
            resp = self.client.get("/clips/search?user_id=u1")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["total"], 1)
            self.assertEqual(len(data["clips"]), 1)

    def test_search_passes_filters(self):
        mock_result = {"clips": [], "total": 0, "limit": 10, "offset": 0}
        with patch("src.api.routes.clip_search.search_clips",
                   new=AsyncMock(return_value=mock_result)) as mock_fn:
            self.client.get(
                "/clips/search?user_id=u1&q=hello&hook_type=question"
                "&min_virality=60&max_virality=100&limit=10"
            )
            call_kwargs = mock_fn.call_args
            self.assertEqual(call_kwargs.kwargs.get("query") or call_kwargs.args[2] if len(call_kwargs.args) > 2 else call_kwargs.kwargs.get("query"), "hello")
            self.assertEqual(call_kwargs.kwargs.get("hook_type"), "question")
            self.assertEqual(call_kwargs.kwargs.get("min_virality"), 60)

    def test_search_pagination(self):
        mock_result = {"clips": [], "total": 100, "limit": 20, "offset": 40}
        with patch("src.api.routes.clip_search.search_clips",
                   new=AsyncMock(return_value=mock_result)):
            resp = self.client.get("/clips/search?user_id=u1&limit=20&offset=40")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["limit"], 20)
            self.assertEqual(data["offset"], 40)

    def test_facets_requires_user_id(self):
        resp = self.client.get("/clips/facets")
        self.assertEqual(resp.status_code, 422)

    def test_facets_returns_hook_types(self):
        mock_facets = {"hook_types": [{"type": "question", "count": 5}]}
        with patch("src.api.routes.clip_search.get_search_facets",
                   new=AsyncMock(return_value=mock_facets)):
            resp = self.client.get("/clips/facets?user_id=u1")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(len(data["hook_types"]), 1)
            self.assertEqual(data["hook_types"][0]["type"], "question")


# ═══════════════════════════════════════════════════════════════════════════
# 5. CLIP SEARCH SERVICE (unit)
# ═══════════════════════════════════════════════════════════════════════════

class TestClipSearchService(unittest.TestCase):
    def _make_mock_db(self, rows=None, total=0):
        from datetime import datetime
        db = MagicMock()
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock(return_value=False)

        count_result = MagicMock()
        count_result.scalar.return_value = total

        data_result = MagicMock()
        mock_rows = []
        for r in (rows or []):
            row = MagicMock()
            row._asdict.return_value = {
                "id": r.get("id", "c1"),
                "task_id": r.get("task_id", "t1"),
                "filename": r.get("filename", "clip.mp4"),
                "file_path": r.get("file_path", "/tmp/clip.mp4"),
                "start_time": "00:00",
                "end_time": "00:10",
                "duration": 10.0,
                "text": r.get("text", ""),
                "relevance_score": r.get("relevance_score", 0.5),
                "reasoning": "",
                "clip_order": 1,
                "virality_score": r.get("virality_score", 0),
                "hook_score": 0,
                "engagement_score": 0,
                "value_score": 0,
                "shareability_score": 0,
                "hook_type": r.get("hook_type"),
                "social_title": None,
                "social_description": None,
                "suggested_hashtags": [],
                "thumbnail_filename": None,
                "face_detected": None,
                "hook_preview_score": 0,
                "user_rating": None,
                "created_at": datetime.now(),
                "task_title": "Test Task",
            }
            mock_rows.append(row)
        data_result.fetchall.return_value = mock_rows

        db.execute = AsyncMock(side_effect=[count_result, data_result])
        return db

    def test_returns_empty_on_no_results(self):
        from src.services.clip_search_service import search_clips
        db = self._make_mock_db(rows=[], total=0)
        result = run(search_clips(db, user_id="u1"))
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["clips"], [])

    def test_returns_clips(self):
        from src.services.clip_search_service import search_clips
        db = self._make_mock_db(
            rows=[{"id": "c1", "text": "viral content", "virality_score": 85}],
            total=1
        )
        result = run(search_clips(db, user_id="u1", query="viral"))
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["clips"]), 1)

    def test_graceful_on_db_error(self):
        from src.services.clip_search_service import search_clips
        db = MagicMock()
        db.execute = AsyncMock(side_effect=Exception("DB error"))
        result = run(search_clips(db, user_id="u1"))
        self.assertEqual(result["clips"], [])
        self.assertEqual(result["total"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# Imports collected at bottom to avoid circular issues in setUp methods
# ═══════════════════════════════════════════════════════════════════════════

from src.services.export_service import build_task_zip  # noqa: E402


if __name__ == "__main__":
    unittest.main()
