"""
Tests for:
  1. Workflow Automation API (/workflows/*)
  2. Real-time Dashboard API (/dashboard/*)
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow(wf_id="wf_001", user_id="user_001"):
    from src.services.workflow_automation import (
        Workflow, WorkflowNodeType, WorkflowStatus, WorkflowNode,
    )
    return Workflow(
        workflow_id=wf_id,
        user_id=user_id,
        name="My Pipeline",
        description="Custom video workflow",
        status=WorkflowStatus.DRAFT,
        nodes=[
            WorkflowNode(
                node_id="node_1",
                type=WorkflowNodeType.TRIGGER,
                name="On Upload",
                config={"event": "video.uploaded"},
                position={"x": 100.0, "y": 100.0},
                outputs=["node_2"],
            )
        ],
        connections=[{"source": "node_1", "target": "node_2"}],
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


def _make_node():
    from src.services.workflow_automation import WorkflowNode, WorkflowNodeType
    return WorkflowNode(
        node_id="node_new",
        type=WorkflowNodeType.AI_ANALYZE,
        name="AI Analysis",
        config={"model": "virality_v2"},
        position={"x": 300.0, "y": 100.0},
    )


def _make_run(run_id="run_001", status="completed"):
    return {
        "run_id": run_id,
        "workflow_id": "wf_001",
        "status": status,
        "started_at": "2026-01-01T00:00:00",
        "completed_at": "2026-01-01T00:01:00",
        "logs": ["Executing On Upload (trigger)", "Executing AI Analysis (ai_analyze)"],
        "node_results": {"node_1": {"triggered": True}, "node_2": {"analysis_complete": True}},
    }


def _make_metric(metric_id="clips_generated"):
    from src.services.realtime_dashboard import MetricType, MetricDataPoint, RealtimeMetric
    return RealtimeMetric(
        metric_id=metric_id,
        name="Clips Generated",
        metric_type=MetricType.COUNTER,
        description="Total clips generated",
        unit="clips",
        current_value=42.0,
        data_points=[],
        aggregation="sum",
    )


# ===========================================================================
# 1. Workflow Automation API
# ===========================================================================

class TestWorkflowsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.workflows import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_templates(self):
        client = self._get_client()
        templates = [
            {"template_id": "viral_shorts", "name": "Viral Shorts Pipeline",
             "description": "Auto-create viral shorts", "nodes_count": 7, "category": "viral"},
            {"template_id": "tutorial", "name": "Tutorial Content Pipeline",
             "description": "Educational content", "nodes_count": 4, "category": "education"},
        ]
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.get_templates",
            return_value=templates,
        ):
            resp = client.get("/workflows/templates")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertIn("viral_shorts", [t["template_id"] for t in data["templates"]])

    def test_create_workflow_blank(self):
        client = self._get_client()
        wf = _make_workflow()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.create_workflow",
            new_callable=AsyncMock,
            return_value=wf,
        ):
            resp = client.post("/workflows", json={
                "user_id": "user_001",
                "name": "My Pipeline",
                "description": "Custom workflow",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["workflow"]["status"], "draft")

    def test_create_workflow_from_template(self):
        client = self._get_client()
        wf = _make_workflow()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.create_workflow",
            new_callable=AsyncMock,
            return_value=wf,
        ):
            resp = client.post("/workflows", json={
                "user_id": "user_001",
                "name": "Viral Shorts Copy",
                "description": "Based on template",
                "template_id": "viral_shorts",
            })
        self.assertEqual(resp.status_code, 200)

    def test_list_user_workflows(self):
        client = self._get_client()
        workflows = [{"workflow_id": "wf_001", "name": "My Pipeline", "status": "draft",
                      "nodes_count": 1, "run_count": 0}]
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.get_user_workflows",
            return_value=workflows,
        ):
            resp = client.get("/workflows/user/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_get_workflow(self):
        client = self._get_client()
        wf = _make_workflow()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.get_workflow",
            return_value=wf,
        ):
            resp = client.get("/workflows/wf_001")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["workflow"]
        self.assertEqual(data["workflow_id"], "wf_001")
        self.assertEqual(len(data["nodes"]), 1)

    def test_get_workflow_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.get_workflow",
            return_value=None,
        ):
            resp = client.get("/workflows/missing")
        self.assertEqual(resp.status_code, 404)

    def test_add_node(self):
        client = self._get_client()
        node = _make_node()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.add_node",
            new_callable=AsyncMock,
            return_value=node,
        ):
            resp = client.post("/workflows/wf_001/nodes", json={
                "node_type": "ai_analyze",
                "name": "AI Analysis",
                "config": {"model": "virality_v2"},
                "position": {"x": 300.0, "y": 100.0},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["node"]["type"], "ai_analyze")

    def test_add_node_invalid_type(self):
        client = self._get_client()
        resp = client.post("/workflows/wf_001/nodes", json={
            "node_type": "explode",
            "name": "Bad Node",
            "config": {},
            "position": {"x": 0.0, "y": 0.0},
        })
        self.assertEqual(resp.status_code, 400)

    def test_add_node_workflow_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.add_node",
            new_callable=AsyncMock,
            side_effect=ValueError("Workflow missing not found"),
        ):
            resp = client.post("/workflows/missing/nodes", json={
                "node_type": "ai_analyze",
                "name": "Test",
                "config": {},
                "position": {"x": 0.0, "y": 0.0},
            })
        self.assertEqual(resp.status_code, 404)

    def test_activate_workflow(self):
        client = self._get_client()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.activate_workflow",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/workflows/wf_001/activate")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "activated")

    def test_activate_workflow_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.activate_workflow",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/workflows/missing/activate")
        self.assertEqual(resp.status_code, 404)

    def test_execute_workflow(self):
        client = self._get_client()
        run_data = _make_run()
        mock_run = MagicMock()
        mock_run.run_id = "run_001"

        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.execute_workflow",
            new_callable=AsyncMock,
            return_value=mock_run,
        ) as mock_exec, patch(
            "src.services.workflow_automation.WorkflowAutomationService.get_run_status",
            return_value=run_data,
        ):
            resp = client.post("/workflows/wf_001/execute", json={
                "input_data": {"video_url": "https://youtu.be/abc123"},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["run"]["status"], "completed")

    def test_execute_workflow_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.execute_workflow",
            new_callable=AsyncMock,
            side_effect=ValueError("Workflow missing not found"),
        ):
            resp = client.post("/workflows/missing/execute", json={"input_data": {}})
        self.assertEqual(resp.status_code, 404)

    def test_get_run_status(self):
        client = self._get_client()
        run_data = _make_run()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.get_run_status",
            return_value=run_data,
        ):
            resp = client.get("/workflows/runs/run_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["run"]["status"], "completed")

    def test_get_run_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.workflow_automation.WorkflowAutomationService.get_run_status",
            return_value=None,
        ):
            resp = client.get("/workflows/runs/missing")
        self.assertEqual(resp.status_code, 404)

    def test_list_node_types(self):
        client = self._get_client()
        resp = client.get("/workflows/node-types/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["node_types"]
        self.assertIn("trigger", data)
        self.assertIn("ai_analyze", data)
        self.assertIn("export", data)


# ===========================================================================
# 2. Real-time Dashboard API
# ===========================================================================

class TestDashboardAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.dashboard import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_register_metric(self):
        client = self._get_client()
        metric = _make_metric()
        with patch(
            "src.services.realtime_dashboard.RealtimeDashboardService.register_metric",
            return_value=metric,
        ):
            resp = client.post("/dashboard/metrics", json={
                "metric_id": "clips_generated",
                "name": "Clips Generated",
                "metric_type": "counter",
                "description": "Total clips generated",
                "unit": "clips",
                "aggregation": "sum",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "registered")
        self.assertEqual(data["metric"]["metric_type"], "counter")

    def test_register_metric_invalid_type(self):
        client = self._get_client()
        resp = client.post("/dashboard/metrics", json={
            "metric_id": "m1",
            "name": "Bad",
            "metric_type": "thermometer",
            "description": "invalid",
        })
        self.assertEqual(resp.status_code, 400)

    def test_record_metric(self):
        client = self._get_client()
        with patch(
            "src.services.realtime_dashboard.RealtimeDashboardService.record_metric",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/dashboard/metrics/record", json={
                "metric_id": "clips_generated",
                "value": 1.0,
                "labels": {"platform": "tiktok"},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "recorded")
        self.assertEqual(data["value"], 1.0)

    def test_record_metric_no_labels(self):
        client = self._get_client()
        with patch(
            "src.services.realtime_dashboard.RealtimeDashboardService.record_metric",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/dashboard/metrics/record", json={
                "metric_id": "virality_score",
                "value": 85.5,
            })
        self.assertEqual(resp.status_code, 200)

    def test_get_metric_history(self):
        client = self._get_client()
        history = [
            {"timestamp": "2026-01-01T00:10:00", "value": 1.0, "labels": {}},
            {"timestamp": "2026-01-01T00:20:00", "value": 3.0, "labels": {}},
        ]
        with patch(
            "src.services.realtime_dashboard.RealtimeDashboardService.get_metric_history",
            return_value=history,
        ):
            resp = client.get("/dashboard/metrics/clips_generated/history?time_range=1h")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["time_range"], "1h")

    def test_get_metric_history_all_ranges(self):
        client = self._get_client()
        for tr in ["1h", "24h", "7d", "30d"]:
            with patch(
                "src.services.realtime_dashboard.RealtimeDashboardService.get_metric_history",
                return_value=[],
            ):
                resp = client.get(f"/dashboard/metrics/m1/history?time_range={tr}")
            self.assertEqual(resp.status_code, 200, f"Failed for time_range={tr}")

    def test_get_metric_history_invalid_range(self):
        client = self._get_client()
        resp = client.get("/dashboard/metrics/m1/history?time_range=6months")
        self.assertEqual(resp.status_code, 400)

    def test_dashboard_summary(self):
        client = self._get_client()
        summary = {
            "active_metrics": 3,
            "active_connections": 2,
            "total_data_points": 150,
            "metrics": [
                {"metric_id": "clips_generated", "name": "Clips Generated",
                 "current_value": 42.0, "type": "counter"},
            ],
        }
        with patch(
            "src.services.realtime_dashboard.RealtimeDashboardService.get_dashboard_summary",
            return_value=summary,
        ):
            resp = client.get("/dashboard/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["summary"]
        self.assertEqual(data["active_metrics"], 3)

    def test_create_custom_dashboard(self):
        client = self._get_client()
        dashboard = {
            "dashboard_id": "dash_user_001_main",
            "user_id": "user_001",
            "name": "Main Board",
            "metrics": ["clips_generated", "virality_score"],
            "created_at": "2026-01-01T00:00:00",
        }
        with patch(
            "src.services.realtime_dashboard.RealtimeDashboardService.create_custom_dashboard",
            return_value=dashboard,
        ):
            resp = client.post("/dashboard/custom", json={
                "user_id": "user_001",
                "name": "Main Board",
                "metric_ids": ["clips_generated", "virality_score"],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["dashboard"]["dashboard_id"], "dash_user_001_main")

    def test_create_custom_dashboard_empty_metrics(self):
        client = self._get_client()
        resp = client.post("/dashboard/custom", json={
            "user_id": "user_001",
            "name": "Empty",
            "metric_ids": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_time_ranges(self):
        client = self._get_client()
        resp = client.get("/dashboard/time-ranges")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["time_ranges"]
        self.assertIn("1h", data)
        self.assertIn("30d", data)

    def test_list_metric_types(self):
        client = self._get_client()
        resp = client.get("/dashboard/metric-types")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["metric_types"]
        self.assertIn("counter", data)
        self.assertIn("gauge", data)
        self.assertIn("histogram", data)
        self.assertIn("rate", data)


if __name__ == "__main__":
    unittest.main()
