"""
Tests for:
  1. Cost Optimization API (/cost/*)
  2. Observability API (/observability/*)
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_usage_record():
    from src.services.cost_optimization import ResourceUsage, ResourceType
    return ResourceUsage(
        resource_id="rec_001",
        resource_type=ResourceType.COMPUTE,
        usage_amount=10.5,
        unit="minutes",
        cost_usd=0.21,
        timestamp="2026-01-01T00:00:00",
        efficiency_score=0.85,
    )


# ===========================================================================
# 1. Cost Optimization API
# ===========================================================================

class TestCostOptimizationAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.cost_optimization import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_track_usage(self):
        client = self._get_client()
        usage = _make_usage_record()
        with patch(
            "src.services.cost_optimization.CostOptimizationService.track_usage",
            new_callable=AsyncMock,
            return_value=usage,
        ):
            resp = client.post("/cost/track", json={
                "resource_type": "compute",
                "usage_amount": 10.5,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "tracked")
        self.assertEqual(data["usage"]["resource_type"], "compute")
        self.assertAlmostEqual(data["usage"]["cost_usd"], 0.21)

    def test_track_usage_invalid_resource(self):
        client = self._get_client()
        resp = client.post("/cost/track", json={
            "resource_type": "unicorn_power",
            "usage_amount": 5.0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_cost_summary(self):
        client = self._get_client()
        summary = {
            "period_days": 30,
            "total_cost_usd": 145.72,
            "by_resource": {"compute": 80.5, "storage": 45.2, "bandwidth": 20.02},
            "alerts_count": 2,
        }
        with patch(
            "src.services.cost_optimization.CostOptimizationService.get_cost_summary",
            return_value=summary,
        ):
            resp = client.get("/cost/summary?days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["summary"]["total_cost_usd"], 145.72)

    def test_cost_summary_invalid_days(self):
        client = self._get_client()
        resp = client.get("/cost/summary?days=0")
        self.assertEqual(resp.status_code, 400)
        resp2 = client.get("/cost/summary?days=999")
        self.assertEqual(resp2.status_code, 400)

    def test_list_alerts(self):
        client = self._get_client()
        alerts = [
            {"alert_id": "al_001", "severity": "warning", "resource_type": "storage",
             "message": "Storage cost approaching threshold"},
        ]
        with patch(
            "src.services.cost_optimization.CostOptimizationService.get_alerts",
            return_value=alerts,
        ):
            resp = client.get("/cost/alerts")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_list_alerts_by_severity(self):
        client = self._get_client()
        with patch(
            "src.services.cost_optimization.CostOptimizationService.get_alerts",
            return_value=[],
        ):
            resp = client.get("/cost/alerts?severity=critical")
        self.assertEqual(resp.status_code, 200)

    def test_list_alerts_invalid_severity(self):
        client = self._get_client()
        resp = client.get("/cost/alerts?severity=apocalyptic")
        self.assertEqual(resp.status_code, 400)

    def test_list_alerts_by_resource(self):
        client = self._get_client()
        with patch(
            "src.services.cost_optimization.CostOptimizationService.get_alerts",
            return_value=[],
        ):
            resp = client.get("/cost/alerts?resource_type=storage")
        self.assertEqual(resp.status_code, 200)

    def test_optimize_resources(self):
        client = self._get_client()
        result = {
            "optimizations": [
                {"resource": "storage", "action": "switch_to_cold_tier", "savings_usd": 22.0},
            ],
            "total_potential_savings_usd": 22.0,
        }
        with patch(
            "src.services.cost_optimization.CostOptimizationService.optimize_resources",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/cost/optimize")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "analyzed")

    def test_list_resource_types(self):
        client = self._get_client()
        resp = client.get("/cost/resource-types")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("compute", data["resource_types"])
        self.assertIn("storage", data["resource_types"])
        self.assertIn("compute", data["unit_costs"])


# ===========================================================================
# 2. Observability API
# ===========================================================================

class TestObservabilityAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.observability import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_start_span(self):
        client = self._get_client()
        with patch(
            "src.services.observability.ObservabilityManager.start_span",
            return_value="span_abc123",
        ):
            resp = client.post("/observability/spans/start", json={
                "span_name": "clip_processing",
                "request_id": "req_001",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "started")
        self.assertEqual(data["span_id"], "span_abc123")

    def test_end_span(self):
        client = self._get_client()
        with patch(
            "src.services.observability.ObservabilityManager.end_span",
            return_value=None,
        ):
            resp = client.post("/observability/spans/end", json={
                "span_id": "span_abc123",
                "status": "success",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ended")

    def test_span_tree(self):
        client = self._get_client()
        spans = [
            {"span_id": "s1", "name": "clip_processing", "duration_ms": 1200},
            {"span_id": "s2", "name": "ffmpeg_encode", "duration_ms": 800, "parent": "s1"},
        ]
        with patch(
            "src.services.observability.ObservabilityManager.get_span_tree",
            return_value=spans,
        ):
            resp = client.get("/observability/spans/req_001")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["spans"]), 2)

    def test_operation_stats(self):
        client = self._get_client()
        stats = {
            "mean_ms": 340.5,
            "p50_ms": 310.0,
            "p95_ms": 620.0,
            "p99_ms": 950.0,
            "count": 150,
        }
        with patch(
            "src.services.observability.PerformanceMonitor.get_stats",
            return_value=stats,
        ):
            resp = client.get("/observability/performance/clip_processing")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["operation"], "clip_processing")
        self.assertEqual(data["stats"]["count"], 150)

    def test_operation_stats_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.observability.PerformanceMonitor.get_stats",
            return_value={},
        ):
            resp = client.get("/observability/performance/unknown_op")
        self.assertEqual(resp.status_code, 404)

    def test_health(self):
        client = self._get_client()
        obs_mock = MagicMock()
        obs_mock._spans = {"s1": {}, "s2": {}}
        perf_mock = MagicMock()
        perf_mock._operation_times = {"clip_processing": [100, 200]}
        with patch("src.api.routes.observability.get_observability", return_value=obs_mock), \
             patch("src.api.routes.observability.get_performance_monitor", return_value=perf_mock):
            resp = client.get("/observability/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["active_spans"], 2)
        self.assertEqual(data["tracked_operations"], 1)


if __name__ == "__main__":
    unittest.main()
