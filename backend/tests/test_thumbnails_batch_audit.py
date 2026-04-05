"""
Tests for:
  1. AI Thumbnail API (/thumbnails/*)
  2. Batch Processing API (/batch/*)
  3. Audit Logging API (/audit/*)
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_thumbnail(tid="thumb_001"):
    from src.services.ai_thumbnail_service import GeneratedThumbnail, ThumbnailStyle
    return GeneratedThumbnail(
        thumbnail_id=tid,
        video_path=Path("/app/storage/clips/clip_001.mp4"),
        timestamp=3.5,
        style=ThumbnailStyle.FACE_FOCUS,
        output_path=Path(f"/app/temp/thumbnails/thumb_{tid}.jpg"),
        dimensions=(1080, 1920),
        file_size_kb=210.0,
        quality_score=0.88,
        viral_potential=0.82,
        variants=[Path(f"/app/temp/thumbnails/thumb_{tid}_v0.jpg")],
    )


def _make_frame_analysis(ts=1.0):
    from src.services.ai_thumbnail_service import ThumbnailAnalysis
    return ThumbnailAnalysis(
        timestamp=ts,
        face_detected=False,
        face_position=None,
        brightness_score=0.7,
        contrast_score=0.7,
        emotion_score=0.5,
        clarity_score=0.8,
        overall_score=0.7,
    )


def _make_batch_status(batch_id="batch_001", status="pending"):
    return {
        "batch_id": batch_id,
        "name": "Test Batch",
        "status": status,
        "progress": 0,
        "total_videos": 2,
        "processed": 0,
        "successful": 0,
        "failed": 0,
        "total_clips": 0,
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "errors": [],
    }


def _make_audit_entry(entry_id="entry_001"):
    from src.services.audit_logging import AuditEventType, AuditLogEntry, SeverityLevel
    return AuditLogEntry(
        entry_id=entry_id,
        timestamp=datetime.utcnow().isoformat(),
        event_type=AuditEventType.CLIP_CREATED,
        severity=SeverityLevel.INFO,
        user_id="user_a",
        ip_address="127.0.0.1",
        user_agent="TestAgent/1.0",
        resource_type="clip",
        resource_id="clip_001",
        action="create",
        status="success",
        details={},
        before_state=None,
        after_state=None,
        session_id=None,
        request_id=None,
    )


# ===========================================================================
# 1. Thumbnail API
# ===========================================================================

class TestThumbnailAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.thumbnails import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_generate_thumbnail_success(self):
        client = self._get_client()
        thumb = _make_thumbnail()
        with patch(
            "src.services.ai_thumbnail_service.AIThumbnailService.generate_thumbnail",
            new_callable=AsyncMock,
            return_value=thumb,
        ):
            resp = client.post("/thumbnails/generate", json={
                "clip_path": "/app/storage/clips/clip_001.mp4",
                "style": "face_focus",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["thumbnail"]["thumbnail_id"], "thumb_001")
        self.assertEqual(data["thumbnail"]["style"], "face_focus")

    def test_generate_thumbnail_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.ai_thumbnail_service.AIThumbnailService.generate_thumbnail",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/thumbnails/generate", json={
                "clip_path": "/nonexistent/clip.mp4",
            })
        self.assertEqual(resp.status_code, 404)

    def test_generate_thumbnail_invalid_style(self):
        client = self._get_client()
        resp = client.post("/thumbnails/generate", json={
            "clip_path": "/app/storage/clips/clip_001.mp4",
            "style": "ultra_mega_style",
        })
        self.assertEqual(resp.status_code, 400)

    def test_generate_thumbnail_with_text(self):
        client = self._get_client()
        thumb = _make_thumbnail()
        with patch(
            "src.services.ai_thumbnail_service.AIThumbnailService.generate_thumbnail",
            new_callable=AsyncMock,
            return_value=thumb,
        ):
            resp = client.post("/thumbnails/generate", json={
                "clip_path": "/app/storage/clips/clip_001.mp4",
                "style": "text_overlay",
                "custom_text": "Watch This!",
                "timestamp": 5.0,
            })
        self.assertEqual(resp.status_code, 200)

    def test_batch_generate(self):
        client = self._get_client()
        thumbs = [_make_thumbnail(f"thumb_{i}") for i in range(2)]
        with patch(
            "src.services.ai_thumbnail_service.AIThumbnailService.batch_generate_thumbnails",
            new_callable=AsyncMock,
            return_value=thumbs,
        ):
            resp = client.post("/thumbnails/generate/batch", json={
                "clip_paths": [
                    "/app/storage/clips/clip_001.mp4",
                    "/app/storage/clips/clip_002.mp4",
                ],
                "style": "minimal",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)

    def test_batch_generate_empty(self):
        client = self._get_client()
        resp = client.post("/thumbnails/generate/batch", json={"clip_paths": []})
        self.assertEqual(resp.status_code, 400)

    def test_analyze_frames(self):
        client = self._get_client()
        analyses = [_make_frame_analysis(float(i)) for i in range(5)]
        with patch(
            "src.services.ai_thumbnail_service.AIThumbnailService.analyze_optimal_frames",
            new_callable=AsyncMock,
            return_value=analyses,
        ):
            resp = client.post("/thumbnails/analyze", json={
                "clip_path": "/app/storage/clips/clip_001.mp4",
                "num_frames": 5,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 5)
        self.assertIn("overall_score", data["frames"][0])

    def test_recommend_styles(self):
        client = self._get_client()
        from src.services.ai_thumbnail_service import ThumbnailStyle
        with patch(
            "src.services.ai_thumbnail_service.AIThumbnailService.get_thumbnail_recommendations",
            return_value=[ThumbnailStyle.FACE_FOCUS, ThumbnailStyle.TEXT_OVERLAY],
        ):
            resp = client.get("/thumbnails/recommend?niche=education")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["niche"], "education")
        self.assertIn("face_focus", data["recommended_styles"])

    def test_list_styles(self):
        client = self._get_client()
        resp = client.get("/thumbnails/styles")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        style_values = [s["value"] for s in data["styles"]]
        self.assertIn("face_focus", style_values)
        self.assertIn("high_contrast", style_values)


# ===========================================================================
# 2. Batch Processing API
# ===========================================================================

class TestBatchAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.batch import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_batch_auto_start(self):
        client = self._get_client()
        mock_job = MagicMock()
        mock_job.batch_id = "batch_001"
        status_data = _make_batch_status()

        with patch(
            "src.services.batch_processor.BatchProcessor.create_batch_job",
            new_callable=AsyncMock,
            return_value=mock_job,
        ), patch(
            "src.services.batch_processor.BatchProcessor.start_batch_processing",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "src.services.batch_processor.BatchProcessor.get_batch_status",
            return_value=status_data,
        ):
            resp = client.post("/batch", json={
                "video_urls": [
                    "https://www.youtube.com/watch?v=abc123",
                    "https://www.youtube.com/watch?v=def456",
                ],
                "auto_start": True,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertTrue(data["auto_started"])

    def test_create_batch_empty_urls(self):
        client = self._get_client()
        resp = client.post("/batch", json={"video_urls": []})
        self.assertEqual(resp.status_code, 400)

    def test_list_batches(self):
        client = self._get_client()
        mock_list = [{"batch_id": "b1", "name": "Batch 1", "status": "completed", "progress": 100, "total_videos": 2, "created_at": "2026-01-01T00:00:00"}]
        with patch(
            "src.services.batch_processor.BatchProcessor.list_user_batches",
            return_value=mock_list,
        ):
            resp = client.get("/batch")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_get_batch_status_success(self):
        client = self._get_client()
        status_data = _make_batch_status(status="processing")
        with patch(
            "src.services.batch_processor.BatchProcessor.get_batch_status",
            return_value=status_data,
        ):
            resp = client.get("/batch/batch_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["batch"]["status"], "processing")

    def test_get_batch_status_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.batch_processor.BatchProcessor.get_batch_status",
            return_value=None,
        ):
            resp = client.get("/batch/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_get_batch_results(self):
        client = self._get_client()
        results_data = {
            "batch_id": "batch_001",
            "name": "Test",
            "status": "completed",
            "results": [{"video_index": 0, "status": "success", "clip_count": 3}],
            "errors": [],
            "summary": {"total_videos": 1, "successful": 1, "failed": 0, "total_clips": 3, "avg_clips_per_video": 3.0},
        }
        with patch(
            "src.services.batch_processor.BatchProcessor.get_batch_results",
            return_value=results_data,
        ):
            resp = client.get("/batch/batch_001/results")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"]["summary"]["total_clips"], 3)

    def test_start_batch(self):
        client = self._get_client()
        with patch(
            "src.services.batch_processor.BatchProcessor.start_batch_processing",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/batch/batch_001/start")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "started")

    def test_start_batch_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.batch_processor.BatchProcessor.start_batch_processing",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/batch/missing/start")
        self.assertEqual(resp.status_code, 400)

    def test_cancel_batch_success(self):
        client = self._get_client()
        with patch(
            "src.services.batch_processor.BatchProcessor.cancel_batch",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/batch/batch_001/cancel")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "cancelled")

    def test_cancel_batch_failure(self):
        client = self._get_client()
        with patch(
            "src.services.batch_processor.BatchProcessor.cancel_batch",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/batch/missing/cancel")
        self.assertEqual(resp.status_code, 400)

    def test_list_statuses(self):
        client = self._get_client()
        resp = client.get("/batch/statuses/list")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("pending", resp.json()["statuses"])
        self.assertIn("completed", resp.json()["statuses"])


# ===========================================================================
# 3. Audit Logging API
# ===========================================================================

class TestAuditAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.audit import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_log_event_success(self):
        client = self._get_client()
        entry = _make_audit_entry()
        with patch(
            "src.services.audit_logging.AuditLogger.log_event",
            new_callable=AsyncMock,
            return_value=entry,
        ):
            resp = client.post("/audit/log", json={
                "event_type": "clip_created",
                "severity": "info",
                "resource_type": "clip",
                "resource_id": "clip_001",
                "action": "create",
                "status": "success",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "logged")
        self.assertEqual(data["entry_id"], "entry_001")

    def test_log_event_invalid_type(self):
        client = self._get_client()
        resp = client.post("/audit/log", json={
            "event_type": "alien_invasion",
            "severity": "info",
            "resource_type": "clip",
            "resource_id": "x",
            "action": "create",
        })
        self.assertEqual(resp.status_code, 400)

    def test_log_event_invalid_severity(self):
        client = self._get_client()
        resp = client.post("/audit/log", json={
            "event_type": "clip_created",
            "severity": "ultra_critical",
            "resource_type": "clip",
            "resource_id": "x",
            "action": "create",
        })
        self.assertEqual(resp.status_code, 400)

    def test_query_logs(self):
        client = self._get_client()
        mock_entries = [
            {"entry_id": "e1", "event_type": "clip_created", "timestamp": "2026-01-01T00:00:00", "user_id": "u1"},
        ]
        with patch(
            "src.services.audit_logging.AuditLogger.query_logs",
            new_callable=AsyncMock,
            return_value=mock_entries,
        ):
            resp = client.post("/audit/query", json={"limit": 100})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_query_logs_with_filters(self):
        client = self._get_client()
        with patch(
            "src.services.audit_logging.AuditLogger.query_logs",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.post("/audit/query", json={
                "event_types": ["clip_created", "clip_exported"],
                "user_id": "user_a",
                "severity": "info",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_query_logs_invalid_event_type(self):
        client = self._get_client()
        resp = client.post("/audit/query", json={"event_types": ["gobbledygook"]})
        self.assertEqual(resp.status_code, 400)

    def test_user_activity_summary(self):
        client = self._get_client()
        mock_summary = {
            "user_id": "user_a",
            "period_days": 30,
            "total_events": 42,
            "event_breakdown": {"clip_created": 10, "clip_exported": 8},
            "unique_resources_accessed": 15,
            "failed_attempts": 1,
            "first_activity": "2026-01-01T00:00:00",
            "last_activity": "2026-01-30T23:59:59",
        }
        with patch(
            "src.services.audit_logging.AuditLogger.get_user_activity_summary",
            new_callable=AsyncMock,
            return_value=mock_summary,
        ):
            resp = client.get("/audit/user/user_a/summary?days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["summary"]["total_events"], 42)

    def test_export_logs(self):
        client = self._get_client()
        export_path = Path("/app/data/audit/audit_export_2026-01-01_2026-01-31.json")
        with patch(
            "src.services.audit_logging.AuditLogger.export_logs",
            new_callable=AsyncMock,
            return_value=export_path,
        ):
            resp = client.post("/audit/export", json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "format": "json",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "exported")
        self.assertIn("export_path", data)

    def test_export_logs_invalid_format(self):
        client = self._get_client()
        resp = client.post("/audit/export", json={
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "format": "xml",
        })
        self.assertEqual(resp.status_code, 400)

    def test_detect_anomalies(self):
        client = self._get_client()
        mock_anomalies = [
            {"type": "multiple_failed_logins", "severity": "high", "count": 7, "user_id": "user_x", "timeframe_hours": 24}
        ]
        with patch(
            "src.services.audit_logging.AuditLogger.detect_anomalies",
            new_callable=AsyncMock,
            return_value=mock_anomalies,
        ):
            resp = client.get("/audit/anomalies?hours=24")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["anomaly_count"], 1)
        self.assertEqual(data["anomalies"][0]["type"], "multiple_failed_logins")

    def test_detect_no_anomalies(self):
        client = self._get_client()
        with patch(
            "src.services.audit_logging.AuditLogger.detect_anomalies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/audit/anomalies")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["anomaly_count"], 0)

    def test_list_event_types(self):
        client = self._get_client()
        resp = client.get("/audit/event-types")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("clip_created", data["event_types"])
        self.assertIn("security_alert", data["event_types"])
        self.assertIn("info", data["severity_levels"])
        self.assertIn("critical", data["severity_levels"])


if __name__ == "__main__":
    unittest.main()
