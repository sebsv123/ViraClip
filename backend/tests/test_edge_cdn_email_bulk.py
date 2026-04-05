"""
Tests for:
  1. Edge CDN API (/edge-cdn/*)
  2. Email Reports API (/email-reports/*)
  3. Bulk Operations API (/bulk/*)
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subscription(sub_id="sub_001"):
    from src.services.email_reports import ReportSubscription, ReportType, ReportFrequency
    return ReportSubscription(
        subscription_id=sub_id,
        user_id="user_001",
        email="user@example.com",
        report_type=ReportType.WEEKLY_ANALYTICS,
        frequency=ReportFrequency.WEEKLY,
        is_active=True,
        created_at="2026-01-01T00:00:00",
        last_sent=None,
        preferences={},
    )


def _make_report(report_id="rep_001"):
    from src.services.email_reports import EmailReport, ReportType, ReportFrequency
    return EmailReport(
        report_id=report_id,
        user_id="user_001",
        report_type=ReportType.WEEKLY_ANALYTICS,
        frequency=ReportFrequency.WEEKLY,
        subject="Your Weekly ViraClip Report",
        content_html="<h1>Report</h1>",
        content_text="Report",
        created_at="2026-01-01T00:00:00",
        sent_at=None,
        status="pending",
        metrics={"total_clips": 10, "total_views": 50000},
    )


def _make_bulk_job(job_id="job_001"):
    from src.services.bulk_operations import BulkJob, BulkJobStatus, SourceItem, SourceItemStatus
    return BulkJob(
        job_id=job_id,
        user_id="user_001",
        name="Test Bulk Job",
        sources=[
            SourceItem(
                item_id="item_001",
                source_type="youtube",
                source_url="https://youtube.com/watch?v=abc123",
                title="Test Video",
                status=SourceItemStatus.PENDING,
            )
        ],
        status=BulkJobStatus.QUEUED,
        processing_config={},
        publish_config={},
    )


# ===========================================================================
# 1. Edge CDN API
# ===========================================================================

class TestEdgeCDNAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.edge_cdn import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_process_at_edge(self):
        client = self._get_client()
        result = {
            "success": True,
            "clip_id": "clip_001",
            "node_id": "node_us_east_1",
            "region": "us-east",
            "processing_time_ms": 245,
            "latency_ms": 12,
        }
        with patch(
            "src.services.edge_cdn.EdgeCDNService.process_at_edge",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/edge-cdn/process", json={
                "clip_id": "clip_001",
                "user_location": "us-east",
                "task": "transcode",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "processed")
        self.assertEqual(data["result"]["region"], "us-east")

    def test_process_at_edge_failure(self):
        client = self._get_client()
        with patch(
            "src.services.edge_cdn.EdgeCDNService.process_at_edge",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "No nodes available"},
        ):
            resp = client.post("/edge-cdn/process", json={
                "clip_id": "clip_001",
                "user_location": "antarctica",
                "task": "transcode",
            })
        self.assertEqual(resp.status_code, 503)

    def test_distribute_to_cdn(self):
        client = self._get_client()
        result = {
            "clip_id": "clip_001",
            "distributed_to": ["us-east", "eu-west", "ap-southeast"],
            "global_coverage": 75.0,
        }
        with patch(
            "src.services.edge_cdn.EdgeCDNService.distribute_to_cdn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/edge-cdn/distribute", json={
                "clip_id": "clip_001",
                "clip_url": "https://origin.viraclip.com/clips/clip_001.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "distributed")

    def test_get_optimal_endpoint(self):
        client = self._get_client()
        endpoint = {
            "endpoint_id": "ep_us_east",
            "url": "https://cdn-us-east.viraclip.com/clips/clip_001.mp4",
            "latency_ms": 8,
            "cache_hit_ratio": 0.95,
        }
        with patch(
            "src.services.edge_cdn.EdgeCDNService.get_optimal_endpoint",
            new_callable=AsyncMock,
            return_value=endpoint,
        ):
            resp = client.get("/edge-cdn/endpoint/clip_001?user_location=us-east")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("endpoint", resp.json())

    def test_get_optimal_endpoint_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.edge_cdn.EdgeCDNService.get_optimal_endpoint",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get("/edge-cdn/endpoint/missing")
        self.assertEqual(resp.status_code, 404)

    def test_network_status(self):
        client = self._get_client()
        status = {
            "total_nodes": 12,
            "active_nodes": 11,
            "avg_latency_ms": 45,
            "regions_covered": 8,
        }
        with patch(
            "src.services.edge_cdn.EdgeCDNService.get_edge_network_status",
            return_value=status,
        ):
            resp = client.get("/edge-cdn/network/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["network"]["active_nodes"], 11)

    def test_cdn_stats(self):
        client = self._get_client()
        with patch(
            "src.services.edge_cdn.EdgeCDNService.get_cdn_stats",
            return_value={"total_requests_per_s": 1000, "bandwidth_gb": 5.2},
        ):
            resp = client.get("/edge-cdn/stats")
        self.assertEqual(resp.status_code, 200)

    def test_region_details(self):
        client = self._get_client()
        details = {
            "region": "us-east",
            "node_count": 3,
            "avg_latency_ms": 8,
            "nodes": [],
        }
        with patch(
            "src.services.edge_cdn.EdgeCDNService.get_region_details",
            return_value=details,
        ):
            resp = client.get("/edge-cdn/regions/us-east")
        self.assertEqual(resp.status_code, 200)

    def test_region_invalid(self):
        client = self._get_client()
        resp = client.get("/edge-cdn/regions/mars")
        self.assertEqual(resp.status_code, 400)

    def test_list_regions(self):
        client = self._get_client()
        resp = client.get("/edge-cdn/regions")
        self.assertEqual(resp.status_code, 200)
        regions = resp.json()["regions"]
        self.assertIn("us-east", regions)
        self.assertIn("eu-west", regions)


# ===========================================================================
# 2. Email Reports API
# ===========================================================================

class TestEmailReportsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.email_reports import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_subscribe(self):
        client = self._get_client()
        sub = _make_subscription()
        with patch(
            "src.services.email_reports.EmailReportService.subscribe",
            new_callable=AsyncMock,
            return_value=sub,
        ):
            resp = client.post("/email-reports/subscribe", json={
                "user_id": "user_001",
                "email": "user@example.com",
                "report_type": "weekly_analytics",
                "frequency": "weekly",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "subscribed")
        self.assertEqual(data["subscription"]["report_type"], "weekly_analytics")

    def test_subscribe_invalid_email(self):
        client = self._get_client()
        resp = client.post("/email-reports/subscribe", json={
            "user_id": "user_001",
            "email": "not-an-email",
            "report_type": "weekly_analytics",
        })
        self.assertEqual(resp.status_code, 400)

    def test_subscribe_invalid_report_type(self):
        client = self._get_client()
        resp = client.post("/email-reports/subscribe", json={
            "user_id": "user_001",
            "email": "user@example.com",
            "report_type": "horoscope",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_subscriptions(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.list_user_subscriptions",
            return_value=[{"subscription_id": "sub_001", "report_type": "weekly_analytics"}],
        ):
            resp = client.get("/email-reports/subscriptions/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_unsubscribe(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.unsubscribe",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/email-reports/subscriptions/sub_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "unsubscribed")

    def test_unsubscribe_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.unsubscribe",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/email-reports/subscriptions/missing")
        self.assertEqual(resp.status_code, 404)

    def test_generate_report(self):
        client = self._get_client()
        report = _make_report()
        with patch(
            "src.services.email_reports.EmailReportService.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            resp = client.post("/email-reports/generate", json={
                "user_id": "user_001",
                "report_type": "weekly_analytics",
                "send_immediately": False,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "generated")
        self.assertEqual(data["report"]["report_type"], "weekly_analytics")

    def test_generate_and_send(self):
        client = self._get_client()
        report = _make_report()
        with patch(
            "src.services.email_reports.EmailReportService.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ), patch(
            "src.services.email_reports.EmailReportService.send_report",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/email-reports/generate", json={
                "user_id": "user_001",
                "report_type": "weekly_analytics",
                "send_immediately": True,
                "email": "user@example.com",
            })
        self.assertEqual(resp.status_code, 200)

    def test_send_report(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.send_report",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/email-reports/send/rep_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "sent")

    def test_send_report_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.send_report",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/email-reports/send/missing")
        self.assertEqual(resp.status_code, 404)

    def test_process_scheduled(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.process_scheduled_reports",
            new_callable=AsyncMock,
            return_value=["rep_001", "rep_002"],
        ):
            resp = client.post("/email-reports/process-scheduled")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["reports_sent"], 2)

    def test_report_stats(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.get_report_stats",
            return_value={"total": 100, "sent": 98, "failed": 2},
        ):
            resp = client.get("/email-reports/stats")
        self.assertEqual(resp.status_code, 200)

    def test_list_report_types(self):
        client = self._get_client()
        resp = client.get("/email-reports/report-types")
        self.assertEqual(resp.status_code, 200)
        types = resp.json()["report_types"]
        self.assertIn("weekly_analytics", types)


# ===========================================================================
# 3. Bulk Operations API
# ===========================================================================

class TestBulkOpsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.bulk_ops import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_validate_sources_valid(self):
        client = self._get_client()
        with patch(
            "src.services.bulk_operations.BulkOperationsService.validate_sources",
            new_callable=AsyncMock,
            return_value={
                "valid_count": 2, "invalid_count": 0,
                "valid_sources": [], "invalid_sources": [],
                "can_proceed": True,
            },
        ):
            resp = client.post("/bulk/validate", json={
                "sources": [
                    {"url": "https://youtube.com/watch?v=abc123"},
                    {"url": "https://youtube.com/watch?v=def456"},
                ],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["result"]["can_proceed"])

    def test_validate_sources_empty(self):
        client = self._get_client()
        resp = client.post("/bulk/validate", json={"sources": []})
        self.assertEqual(resp.status_code, 400)

    def test_create_job(self):
        client = self._get_client()
        job = _make_bulk_job()
        with patch(
            "src.services.bulk_operations.BulkOperationsService.create_bulk_job",
            new_callable=AsyncMock,
            return_value=job,
        ):
            resp = client.post("/bulk/jobs", json={
                "user_id": "user_001",
                "sources": [{"url": "https://youtube.com/watch?v=abc123", "title": "Test"}],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["job"]["status"], "queued")

    def test_create_job_empty_sources(self):
        client = self._get_client()
        resp = client.post("/bulk/jobs", json={
            "user_id": "user_001",
            "sources": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_start_job(self):
        client = self._get_client()
        with patch(
            "src.services.bulk_operations.BulkOperationsService.start_bulk_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/bulk/jobs/job_001/start")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "started")

    def test_start_job_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.bulk_operations.BulkOperationsService.start_bulk_job",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/bulk/jobs/missing/start")
        self.assertEqual(resp.status_code, 404)

    def test_cancel_job(self):
        client = self._get_client()
        with patch(
            "src.services.bulk_operations.BulkOperationsService.cancel_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/bulk/jobs/job_001/cancel")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "cancelled")

    def test_job_status(self):
        client = self._get_client()
        status = {
            "job_id": "job_001",
            "status": "processing",
            "progress": {"completed": 1, "total": 3, "percentage": 33},
            "sources": [],
        }
        with patch(
            "src.services.bulk_operations.BulkOperationsService.get_job_status",
            new_callable=AsyncMock,
            return_value=status,
        ):
            resp = client.get("/bulk/jobs/job_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["job"]["status"], "processing")

    def test_job_status_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.bulk_operations.BulkOperationsService.get_job_status",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get("/bulk/jobs/missing")
        self.assertEqual(resp.status_code, 404)

    def test_list_user_jobs(self):
        client = self._get_client()
        with patch(
            "src.services.bulk_operations.BulkOperationsService.list_user_jobs",
            new_callable=AsyncMock,
            return_value=[{"job_id": "job_001", "status": "completed"}],
        ):
            resp = client.get("/bulk/jobs/user/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
