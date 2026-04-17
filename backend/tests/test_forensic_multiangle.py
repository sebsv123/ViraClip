"""
Tests for:
  1. Forensic Analysis API (/forensic/*)
  2. Multi-Angle API (/multi-angle/*)
"""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_forensic_result(check_type_val="deepfake", passed=True, score=0.15):
    from src.services.forensic_analysis import ForensicCheckType, ForensicResult
    ct = ForensicCheckType(check_type_val)
    return ForensicResult(
        check_type=ct,
        score=score,
        confidence=0.85,
        details="No issues detected" if passed else "Issues found",
        passed=passed,
        evidence=[],
    )


def _make_video_authenticity(video_id="vid_001", status="authentic"):
    from src.services.forensic_analysis import (
        AuthenticityStatus,
        VideoAuthenticity,
    )
    checks = [
        _make_forensic_result("deepfake"),
        _make_forensic_result("frame_consistency"),
        _make_forensic_result("audio_sync"),
        _make_forensic_result("metadata_integrity"),
    ]
    return VideoAuthenticity(
        video_id=video_id,
        overall_status=AuthenticityStatus(status),
        trust_score=92.0,
        file_hash="0xdeadbeef1234567890abcdef",
        metadata={"format": {}, "streams": [], "encoder": "libx264"},
        forensic_checks=checks,
        created_at=datetime.now().isoformat(),
        analyzed_at=datetime.now().isoformat(),
    )


# ===========================================================================
# 1. Forensic Analysis API
# ===========================================================================

class TestForensicAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.forensic import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_analyze_video_success(self):
        client = self._get_client()
        report = _make_video_authenticity()
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.analyze_video",
            new_callable=AsyncMock,
            return_value=report,
        ):
            resp = client.post("/forensic/analyze", json={
                "video_id": "vid_001",
                "video_path": "/app/storage/videos/vid_001.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "analyzed")
        self.assertEqual(data["report"]["overall_status"], "authentic")
        self.assertEqual(data["report"]["trust_score"], 92.0)
        self.assertIn("forensic_checks", data["report"])

    def test_analyze_video_subset_checks(self):
        client = self._get_client()
        report = _make_video_authenticity()
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.analyze_video",
            new_callable=AsyncMock,
            return_value=report,
        ):
            resp = client.post("/forensic/analyze", json={
                "video_id": "vid_001",
                "video_path": "/app/videos/v.mp4",
                "checks": ["deepfake", "audio_sync"],
            })
        self.assertEqual(resp.status_code, 200)

    def test_analyze_video_invalid_check(self):
        client = self._get_client()
        resp = client.post("/forensic/analyze", json={
            "video_id": "v1",
            "video_path": "/app/v.mp4",
            "checks": ["mind_reading"],
        })
        self.assertEqual(resp.status_code, 400)

    def test_analyze_video_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.analyze_video",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("Video not found: /app/missing.mp4"),
        ):
            resp = client.post("/forensic/analyze", json={
                "video_id": "v_missing",
                "video_path": "/app/missing.mp4",
            })
        self.assertEqual(resp.status_code, 404)

    def test_get_report_success(self):
        client = self._get_client()
        report = _make_video_authenticity()
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.get_analysis_report",
            return_value=report,
        ):
            resp = client.get("/forensic/vid_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["report"]["video_id"], "vid_001")

    def test_get_report_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.get_analysis_report",
            return_value=None,
        ):
            resp = client.get("/forensic/missing_video")
        self.assertEqual(resp.status_code, 404)

    def test_verify_authenticity_success(self):
        client = self._get_client()
        verify_result = {
            "video_id": "vid_001",
            "status": "authentic",
            "trust_score": 92.0,
            "analyzed_at": datetime.now().isoformat(),
            "file_hash": "0xdeadbeef",
            "hash_matches": True,
            "verification_passed": True,
        }
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.verify_authenticity",
            new_callable=AsyncMock,
            return_value=verify_result,
        ):
            resp = client.post("/forensic/verify", json={
                "video_id": "vid_001",
                "claimed_hash": "0xdeadbeef",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["verification"]["hash_matches"])
        self.assertTrue(data["verification"]["verification_passed"])

    def test_verify_no_report(self):
        client = self._get_client()
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.verify_authenticity",
            new_callable=AsyncMock,
            return_value={"error": "No forensic analysis found for this video"},
        ):
            resp = client.post("/forensic/verify", json={"video_id": "unknown"})
        self.assertEqual(resp.status_code, 404)

    def test_batch_analyze(self):
        client = self._get_client()
        reports = [
            _make_video_authenticity("v1", "authentic"),
            _make_video_authenticity("v2", "suspicious"),
        ]
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.batch_analyze",
            new_callable=AsyncMock,
            return_value=reports,
        ):
            resp = client.post("/forensic/batch", json={
                "videos": [
                    {"video_id": "v1", "path": "/app/v1.mp4"},
                    {"video_id": "v2", "path": "/app/v2.mp4"},
                ],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_batch_analyze_empty(self):
        client = self._get_client()
        resp = client.post("/forensic/batch", json={"videos": []})
        self.assertEqual(resp.status_code, 400)

    def test_get_stats(self):
        client = self._get_client()
        stats = {
            "total_analyzed": 50,
            "status_breakdown": {"authentic": 42, "suspicious": 5, "manipulated": 2, "unknown": 1},
            "average_trust_score": 87.3,
            "authentic_percentage": 84.0,
        }
        with patch(
            "src.services.forensic_analysis.ForensicAnalysisService.get_forensic_stats",
            return_value=stats,
        ):
            resp = client.get("/forensic/stats/overview")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["total_analyzed"], 50)

    def test_list_checks(self):
        client = self._get_client()
        resp = client.get("/forensic/checks/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("deepfake", data["checks"])
        self.assertIn("audio_sync", data["checks"])
        self.assertIn("authentic", data["statuses"])
        self.assertIn("manipulated", data["statuses"])


# ===========================================================================
# 2. Multi-Angle API
# ===========================================================================

class TestMultiAngleAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.multi_angle import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_sync_success(self):
        client = self._get_client()
        sync_result = {
            "offset_seconds": 1.35,
            "sync_ready": True,
            "primary": "/app/primary.mp4",
            "secondary": "/app/secondary.mp4",
        }
        with patch(
            "src.services.multi_angle_service.MultiAngleService.synchronize_sources",
            new_callable=AsyncMock,
            return_value=sync_result,
        ):
            resp = client.post("/multi-angle/sync", json={
                "primary_path": "/app/primary.mp4",
                "secondary_path": "/app/secondary.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "synced")
        self.assertAlmostEqual(data["offset_seconds"], 1.35)

    def test_sync_failure(self):
        client = self._get_client()
        with patch(
            "src.services.multi_angle_service.MultiAngleService.synchronize_sources",
            new_callable=AsyncMock,
            return_value={"sync_ready": False, "error": "No audio track found"},
        ):
            resp = client.post("/multi-angle/sync", json={
                "primary_path": "/app/silent.mp4",
                "secondary_path": "/app/secondary.mp4",
            })
        self.assertEqual(resp.status_code, 422)

    def test_align_timestamps(self):
        client = self._get_client()
        with patch(
            "src.services.multi_angle_service.MultiAngleService.get_aligned_timestamps",
            return_value=(8.65, 38.65),
        ):
            resp = client.post("/multi-angle/align-timestamps", json={
                "primary_start": 10.0,
                "primary_end": 40.0,
                "offset": 1.35,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["secondary_start"], 8.65)
        self.assertEqual(data["secondary_end"], 38.65)

    def test_align_timestamps_negative_offset(self):
        client = self._get_client()
        with patch(
            "src.services.multi_angle_service.MultiAngleService.get_aligned_timestamps",
            return_value=(11.5, 41.5),
        ):
            resp = client.post("/multi-angle/align-timestamps", json={
                "primary_start": 10.0,
                "primary_end": 40.0,
                "offset": -1.5,
            })
        self.assertEqual(resp.status_code, 200)

    def test_generate_switching_plan(self):
        client = self._get_client()
        plan = [
            {"start": 0.0, "end": 3.3, "angle": 0},
            {"start": 3.3, "end": 6.6, "angle": 1},
            {"start": 6.6, "end": 10.0, "angle": 0},
        ]
        with patch(
            "src.services.multi_angle_service.MultiAngleService.generate_camera_switching_plan",
            return_value=plan,
        ):
            resp = client.post("/multi-angle/switching-plan", json={
                "duration": 10.0,
                "interval": 3.3,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_segments"], 3)
        self.assertEqual(data["plan"][0]["angle"], 0)
        self.assertEqual(data["plan"][1]["angle"], 1)

    def test_switching_plan_default_interval(self):
        client = self._get_client()
        plan = [{"start": 0.0, "end": 3.3, "angle": 0}]
        with patch(
            "src.services.multi_angle_service.MultiAngleService.generate_camera_switching_plan",
            return_value=plan,
        ):
            resp = client.post("/multi-angle/switching-plan", json={"duration": 30.0})
        self.assertEqual(resp.status_code, 200)

    def test_switching_plan_invalid_duration(self):
        client = self._get_client()
        resp = client.post("/multi-angle/switching-plan", json={"duration": -5.0})
        self.assertEqual(resp.status_code, 400)

    def test_switching_plan_invalid_interval(self):
        client = self._get_client()
        resp = client.post("/multi-angle/switching-plan", json={
            "duration": 60.0,
            "interval": 0,
        })
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
