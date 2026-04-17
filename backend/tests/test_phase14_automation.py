"""
Phase 14 — Automation & Reach Layer Tests

Covers:
  - Video ingestion service (platform detection, result dataclass, error paths)
  - Autopilot service (workflow creation, store, status polling)
  - A/B auto-winner (auto_update_creator_template)
  - Ingest API routes (check, detect-platform, url, batch)
  - Autopilot API routes (run, status, list, ab-winner)
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. VIDEO INGESTION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestDetectPlatform(unittest.TestCase):
    def setUp(self):
        from src.services.video_ingestion_service import detect_platform
        self.detect = detect_platform

    def test_youtube(self):
        self.assertEqual(self.detect("https://www.youtube.com/watch?v=abc123"), "youtube")

    def test_youtu_be_short(self):
        self.assertEqual(self.detect("https://youtu.be/abc123"), "youtube")

    def test_tiktok(self):
        self.assertEqual(self.detect("https://www.tiktok.com/@user/video/123"), "tiktok")

    def test_instagram(self):
        self.assertEqual(self.detect("https://www.instagram.com/reel/abc123"), "instagram")

    def test_twitch(self):
        self.assertEqual(self.detect("https://www.twitch.tv/videos/12345"), "twitch")

    def test_twitter(self):
        self.assertEqual(self.detect("https://twitter.com/user/status/123"), "twitter")

    def test_x_com(self):
        self.assertEqual(self.detect("https://x.com/user/status/123"), "twitter")

    def test_vimeo(self):
        self.assertEqual(self.detect("https://vimeo.com/12345"), "vimeo")

    def test_unknown(self):
        self.assertEqual(self.detect("https://example.com/video.mp4"), "unknown")


class TestIngestResult(unittest.TestCase):
    def test_success_property(self):
        from src.services.video_ingestion_service import IngestResult
        r = IngestResult(url="http://x", local_path="/tmp/v.mp4", platform="youtube")
        self.assertTrue(r.success)

    def test_failed_when_no_path(self):
        from src.services.video_ingestion_service import IngestResult
        r = IngestResult(url="http://x", local_path=None, platform="tiktok", error="oops")
        self.assertFalse(r.success)

    def test_failed_when_error_set(self):
        from src.services.video_ingestion_service import IngestResult
        r = IngestResult(url="http://x", local_path="/tmp/v.mp4", platform="tiktok", error="oops")
        self.assertFalse(r.success)


class TestIngestUrl(unittest.TestCase):
    def test_ytdlp_not_found_returns_error(self):
        with patch("asyncio.create_subprocess_exec",
                   new=AsyncMock(side_effect=FileNotFoundError)):
            from src.services.video_ingestion_service import ingest_url
            result = run(ingest_url("https://youtube.com/watch?v=test"))
            self.assertFalse(result.success)
            self.assertIn("yt-dlp", result.error)

    def test_timeout_returns_error(self):
        with patch("asyncio.create_subprocess_exec",
                   new=AsyncMock(side_effect=asyncio.TimeoutError)):
            from src.services.video_ingestion_service import ingest_url
            result = run(ingest_url("https://youtube.com/watch?v=test"))
            self.assertFalse(result.success)
            self.assertIn("timed out", result.error)

    def test_nonzero_returncode_returns_error(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"ERROR: video unavailable"))
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            from src.services.video_ingestion_service import ingest_url
            result = run(ingest_url("https://youtube.com/watch?v=test"))
            self.assertFalse(result.success)

    def test_success_finds_downloaded_file(self):
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        fake_file = Path(tmpdir) / "abc123.mp4"
        fake_file.write_bytes(b"fake video data")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        meta = json.dumps({"id": "abc123", "title": "Test Video", "duration": 60})
        mock_proc.communicate = AsyncMock(return_value=(meta.encode(), b""))

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            from src.services.video_ingestion_service import ingest_url
            result = run(ingest_url("https://youtube.com/watch?v=abc123",
                                    output_dir=tmpdir))
            self.assertTrue(result.success)
            self.assertIsNotNone(result.local_path)
            self.assertEqual(result.title, "Test Video")
            self.assertAlmostEqual(result.duration_seconds, 60.0)

    def test_platform_detected_correctly(self):
        with patch("asyncio.create_subprocess_exec",
                   new=AsyncMock(side_effect=FileNotFoundError)):
            from src.services.video_ingestion_service import ingest_url
            result = run(ingest_url("https://www.tiktok.com/@user/video/123"))
            self.assertEqual(result.platform, "tiktok")


class TestIngestMultiple(unittest.TestCase):
    def test_returns_list_of_results(self):
        with patch("src.services.video_ingestion_service.ingest_url",
                   new=AsyncMock(side_effect=lambda url, **kw: __import__(
                       "src.services.video_ingestion_service",
                       fromlist=["IngestResult"]
                   ).IngestResult(url=url, local_path=None, platform="youtube",
                                  error="not installed"))):
            from src.services.video_ingestion_service import ingest_multiple
            results = run(ingest_multiple(
                ["https://yt.com/1", "https://yt.com/2"], max_concurrent=2
            ))
            self.assertEqual(len(results), 2)


class TestIsYtdlpAvailable(unittest.TestCase):
    def test_returns_true_when_installed(self):
        with patch("shutil.which", return_value="/usr/bin/yt-dlp"):
            from src.services.video_ingestion_service import is_ytdlp_available
            self.assertTrue(is_ytdlp_available())

    def test_returns_false_when_not_installed(self):
        with patch("shutil.which", return_value=None):
            from src.services.video_ingestion_service import is_ytdlp_available
            self.assertFalse(is_ytdlp_available())


# ═══════════════════════════════════════════════════════════════════════════
# 2. AUTOPILOT SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestAutopilotWorkflow(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self._store_patch = patch(
            "src.services.autopilot_service._WORKFLOW_STORE",
            Path(self.tmpdir) / "workflows.json"
        )
        self._store_patch.start()
        # Reset in-memory store
        import src.services.autopilot_service as mod
        mod._active_workflows.clear()

    def tearDown(self):
        self._store_patch.stop()

    def test_start_autopilot_creates_workflow(self):
        from src.services.autopilot_service import AutopilotConfig, start_autopilot, WorkflowStatus
        config = AutopilotConfig(source_local_path="/fake/video.mp4")
        with patch("src.services.autopilot_service._run_workflow", new=AsyncMock()):
            wf = run(start_autopilot(config))
        self.assertIsNotNone(wf.workflow_id)
        self.assertIn(wf.status, [WorkflowStatus.QUEUED, WorkflowStatus.INGESTING,
                                   WorkflowStatus.PROCESSING, WorkflowStatus.DONE])

    def test_workflow_saved_to_store(self):
        from src.services.autopilot_service import AutopilotConfig, start_autopilot
        config = AutopilotConfig(source_local_path="/fake/video.mp4")
        with patch("src.services.autopilot_service._run_workflow", new=AsyncMock()):
            wf = run(start_autopilot(config))
        store_path = Path(self.tmpdir) / "workflows.json"
        self.assertTrue(store_path.exists())
        data = json.loads(store_path.read_text())
        self.assertIn(wf.workflow_id, data)

    def test_get_workflow_returns_dict(self):
        from src.services.autopilot_service import AutopilotConfig, start_autopilot, get_workflow
        config = AutopilotConfig(source_local_path="/fake/video.mp4")
        with patch("src.services.autopilot_service._run_workflow", new=AsyncMock()):
            wf = run(start_autopilot(config))
        result = get_workflow(wf.workflow_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["workflow_id"], wf.workflow_id)

    def test_get_workflow_nonexistent_returns_none(self):
        from src.services.autopilot_service import get_workflow
        self.assertIsNone(get_workflow("nonexistent-id"))

    def test_list_workflows_returns_list(self):
        from src.services.autopilot_service import AutopilotConfig, start_autopilot, list_workflows
        config = AutopilotConfig(source_local_path="/fake/video.mp4")
        with patch("src.services.autopilot_service._run_workflow", new=AsyncMock()):
            run(start_autopilot(config))
        workflows = list_workflows()
        self.assertIsInstance(workflows, list)
        self.assertGreater(len(workflows), 0)

    def test_workflow_fails_without_source(self):
        from src.services.autopilot_service import AutopilotConfig, _run_workflow, AutopilotWorkflow, WorkflowStatus
        config = AutopilotConfig()  # No source
        wf = AutopilotWorkflow(workflow_id="test-wf", config=config)
        with patch("src.services.autopilot_service._save_workflow"):
            run(_run_workflow(wf))
        self.assertEqual(wf.status, WorkflowStatus.FAILED)
        self.assertIsNotNone(wf.error)

    def test_to_dict_includes_required_keys(self):
        from src.services.autopilot_service import AutopilotConfig, AutopilotWorkflow
        wf = AutopilotWorkflow(workflow_id="w1", config=AutopilotConfig())
        d = wf.to_dict()
        for key in ("workflow_id", "status", "steps", "created_at", "clips_produced"):
            self.assertIn(key, d)

    def test_ingest_stage_called_for_url_source(self):
        from src.services.autopilot_service import (
            AutopilotConfig, AutopilotWorkflow, _run_workflow, WorkflowStatus
        )
        from src.services.video_ingestion_service import IngestResult

        config = AutopilotConfig(source_url="https://youtube.com/watch?v=test")
        wf = AutopilotWorkflow(workflow_id="w2", config=config)

        mock_ingest = AsyncMock(return_value=IngestResult(
            url="https://youtube.com/watch?v=test",
            local_path="/tmp/video.mp4",
            platform="youtube",
        ))
        # Patch path.exists to return True for the local path
        with patch("src.services.video_ingestion_service.ingest_url", mock_ingest), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("src.services.autopilot_service._save_workflow"), \
             patch("src.services.autopilot_service.asyncio.create_task"):
            # Simulate: after ingest succeeds but job_queue fails gracefully
            with patch("src.workers.job_queue.JobQueue.enqueue_job",
                       new=AsyncMock(side_effect=Exception("No queue in test"))):
                run(_run_workflow(wf))

        mock_ingest.assert_called_once()

    def test_autopilot_config_defaults(self):
        from src.services.autopilot_service import AutopilotConfig
        c = AutopilotConfig()
        self.assertEqual(c.target_platform, "tiktok")
        self.assertEqual(c.max_clips, 5)
        self.assertTrue(c.denoise_audio)
        self.assertTrue(c.jump_cut)
        self.assertFalse(c.auto_publish)


# ═══════════════════════════════════════════════════════════════════════════
# 3. A/B AUTO-WINNER
# ═══════════════════════════════════════════════════════════════════════════

class TestAbAutoWinner(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self._store_patch = patch(
            "src.services.performance_webhook_service._PERF_STORE",
            Path(self.tmpdir) / "events.json"
        )
        self._store_patch.start()

    def tearDown(self):
        self._store_patch.stop()

    def test_no_winner_when_below_threshold(self):
        from src.services.performance_webhook_service import (
            PerformanceEvent, record_performance_event, auto_update_creator_template
        )
        # Only 2 viral clips for "bold" template — below default threshold of 5
        for i in range(2):
            event = PerformanceEvent(clip_id=f"c{i}", platform="tiktok", views=200000)
            record_performance_event(event, caption_template="bold")
        result = auto_update_creator_template("user_123", min_viral_posts=5)
        self.assertIsNone(result)

    def test_winner_selected_at_threshold(self):
        from src.services.performance_webhook_service import (
            PerformanceEvent, record_performance_event, auto_update_creator_template
        )
        # 5 viral clips for "minimal" template
        for i in range(5):
            event = PerformanceEvent(clip_id=f"m{i}", platform="tiktok", views=200000)
            record_performance_event(event, caption_template="minimal")

        mock_profile = MagicMock()
        mock_profile.caption_style = "default"

        with patch("src.services.creator_profile_service.get_profile",
                   return_value=mock_profile), \
             patch("src.services.creator_profile_service.update_profile",
                   return_value=mock_profile) as mock_update:
            result = auto_update_creator_template("user_abc", min_viral_posts=5)
            self.assertEqual(result, "minimal")
            mock_update.assert_called_once()

    def test_no_update_when_already_winning_template(self):
        from src.services.performance_webhook_service import (
            PerformanceEvent, record_performance_event, auto_update_creator_template
        )
        for i in range(5):
            event = PerformanceEvent(clip_id=f"k{i}", platform="tiktok", views=200000)
            record_performance_event(event, caption_template="karaoke")

        mock_profile = MagicMock()
        mock_profile.caption_style = "karaoke"  # Already set

        with patch("src.services.creator_profile_service.get_profile",
                   return_value=mock_profile), \
             patch("src.services.creator_profile_service.update_profile") as mock_update:
            result = auto_update_creator_template("user_xyz", min_viral_posts=5)
            # Should not update since already set to karaoke
            mock_update.assert_not_called()

    def test_graceful_failure_when_profile_not_found(self):
        from src.services.performance_webhook_service import (
            PerformanceEvent, record_performance_event, auto_update_creator_template
        )
        for i in range(5):
            event = PerformanceEvent(clip_id=f"z{i}", platform="tiktok", views=200000)
            record_performance_event(event, caption_template="bold")

        with patch("src.services.creator_profile_service.get_profile",
                   return_value=None):
            # Should not raise, just return None
            result = auto_update_creator_template("user_none", min_viral_posts=5)
            self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════
# 4. INGEST API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_app():
    from fastapi import FastAPI
    from src.api.routes.ingest import router
    from src.api.middleware.rate_limit import ingest_rate_limit_dependency
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[ingest_rate_limit_dependency] = lambda: None
    return app


class TestIngestApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_app())

    def test_check_ytdlp_available(self):
        with patch("src.services.video_ingestion_service.is_ytdlp_available", return_value=True):
            resp = self.client.get("/ingest/check")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["yt_dlp_available"])

    def test_check_ytdlp_not_available(self):
        with patch("src.services.video_ingestion_service.is_ytdlp_available", return_value=False):
            resp = self.client.get("/ingest/check")
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["yt_dlp_available"])

    def test_detect_platform_youtube(self):
        resp = self.client.get("/ingest/detect-platform?url=https://youtube.com/watch?v=abc")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["platform"], "youtube")

    def test_detect_platform_tiktok(self):
        resp = self.client.get("/ingest/detect-platform?url=https://tiktok.com/@user/video/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["platform"], "tiktok")

    def test_ingest_url_503_when_ytdlp_missing(self):
        with patch("src.services.video_ingestion_service.is_ytdlp_available", return_value=False):
            resp = self.client.post("/ingest/url", json={"url": "https://youtube.com/watch?v=x"})
            self.assertEqual(resp.status_code, 503)

    def test_ingest_url_returns_result(self):
        from src.services.video_ingestion_service import IngestResult
        mock_result = IngestResult(
            url="https://youtube.com/watch?v=x",
            local_path="/tmp/test.mp4",
            platform="youtube",
            title="Test",
            duration_seconds=30.0,
            file_size_bytes=1024,
        )
        with patch("src.services.video_ingestion_service.is_ytdlp_available", return_value=True), \
             patch("src.services.video_ingestion_service.ingest_url",
                   new=AsyncMock(return_value=mock_result)):
            resp = self.client.post("/ingest/url", json={"url": "https://youtube.com/watch?v=x"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["local_path"], "/tmp/test.mp4")
            self.assertEqual(data["platform"], "youtube")

    def test_batch_rejects_more_than_20_urls(self):
        with patch("src.services.video_ingestion_service.is_ytdlp_available", return_value=True):
            urls = [f"https://yt.com/{i}" for i in range(21)]
            resp = self.client.post("/ingest/batch", json={"urls": urls})
            self.assertEqual(resp.status_code, 400)

    def test_batch_success(self):
        from src.services.video_ingestion_service import IngestResult
        mock_results = [
            IngestResult(url="https://yt.com/1", local_path="/tmp/v1.mp4", platform="youtube"),
            IngestResult(url="https://yt.com/2", local_path=None, platform="youtube", error="err"),
        ]
        with patch("src.services.video_ingestion_service.is_ytdlp_available", return_value=True), \
             patch("src.services.video_ingestion_service.ingest_multiple",
                   new=AsyncMock(return_value=mock_results)):
            resp = self.client.post("/ingest/batch",
                                    json={"urls": ["https://yt.com/1", "https://yt.com/2"]})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["total"], 2)
            self.assertEqual(data["succeeded"], 1)
            self.assertEqual(data["failed"], 1)

    def test_get_video_info_404_on_failure(self):
        with patch("src.services.video_ingestion_service.get_video_info",
                   new=AsyncMock(return_value={})):
            resp = self.client.get("/ingest/info?url=https://youtube.com/watch?v=x")
            self.assertEqual(resp.status_code, 400)


# ═══════════════════════════════════════════════════════════════════════════
# 5. AUTOPILOT API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_autopilot_app():
    from fastapi import FastAPI
    from src.api.routes.autopilot import router
    from src.api.middleware.rate_limit import autopilot_rate_limit_dependency
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[autopilot_rate_limit_dependency] = lambda: None
    return app


class TestAutopilotApiRoutes(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self._store_patch = patch(
            "src.services.autopilot_service._WORKFLOW_STORE",
            Path(self.tmpdir) / "workflows.json"
        )
        self._store_patch.start()
        import src.services.autopilot_service as mod
        mod._active_workflows.clear()
        self.client = TestClient(_make_autopilot_app())

    def tearDown(self):
        self._store_patch.stop()

    def test_run_requires_source(self):
        resp = self.client.post("/autopilot/run", json={})
        self.assertEqual(resp.status_code, 400)

    def test_run_with_local_path(self):
        from src.services.autopilot_service import AutopilotWorkflow, AutopilotConfig, WorkflowStatus
        mock_wf = AutopilotWorkflow(
            workflow_id="test-wf-1",
            config=AutopilotConfig(source_local_path="/fake/video.mp4"),
            status=WorkflowStatus.QUEUED,
        )
        with patch("src.services.autopilot_service.start_autopilot",
                   new=AsyncMock(return_value=mock_wf)):
            resp = self.client.post("/autopilot/run",
                                    json={"source_local_path": "/fake/video.mp4"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["workflow_id"], "test-wf-1")
            self.assertIn("/autopilot/status/", data["message"])

    def test_run_with_url(self):
        from src.services.autopilot_service import AutopilotWorkflow, AutopilotConfig, WorkflowStatus
        mock_wf = AutopilotWorkflow(
            workflow_id="test-wf-2",
            config=AutopilotConfig(source_url="https://youtube.com/watch?v=x"),
            status=WorkflowStatus.QUEUED,
        )
        with patch("src.services.autopilot_service.start_autopilot",
                   new=AsyncMock(return_value=mock_wf)):
            resp = self.client.post("/autopilot/run",
                                    json={"source_url": "https://youtube.com/watch?v=x"})
            self.assertEqual(resp.status_code, 200)

    def test_status_404_for_unknown(self):
        resp = self.client.get("/autopilot/status/nonexistent-id")
        self.assertEqual(resp.status_code, 404)

    def test_status_returns_workflow_dict(self):
        from src.services.autopilot_service import AutopilotWorkflow, AutopilotConfig, _save_workflow
        wf = AutopilotWorkflow(workflow_id="known-id", config=AutopilotConfig())
        _save_workflow(wf)
        resp = self.client.get("/autopilot/status/known-id")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["workflow_id"], "known-id")

    def test_list_workflows_empty(self):
        resp = self.client.get("/autopilot/workflows")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["workflows"], [])

    def test_ab_winner_no_data(self):
        import tempfile
        tmpdir = tempfile.mkdtemp()
        with patch("src.services.performance_webhook_service._PERF_STORE",
                   Path(tmpdir) / "events.json"):
            resp = self.client.post("/autopilot/ab-winner?user_id=u1")
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["updated"])

    def test_ab_winner_triggers_update(self):
        with patch("src.services.performance_webhook_service.auto_update_creator_template",
                   return_value="minimal"):
            resp = self.client.post("/autopilot/ab-winner?user_id=u1&min_viral_posts=1")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["updated"])
            self.assertEqual(data["new_template"], "minimal")


if __name__ == "__main__":
    unittest.main()
