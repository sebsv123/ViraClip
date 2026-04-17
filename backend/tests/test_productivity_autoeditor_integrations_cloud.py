"""
Tests for:
  1. Productivity Integrations API (/productivity/*)
  2. Smart Auto Editor API (/auto-editor/*)
  3. Third-Party Integrations API (/integrations/*)
  4. Cloud Storage API (/cloud-storage/*)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_connection(conn_id="conn_001"):
    from src.services.productivity_integrations import ToolConnection, ToolType
    return ToolConnection(
        connection_id=conn_id,
        user_id="user_001",
        tool_type=ToolType.SLACK,
        access_token="tok_abc",
        workspace_id="ws_001",
        workspace_name="ViraClip Team",
        is_active=True,
        created_at="2026-01-01T00:00:00",
        last_used=None,
    )


def _make_automation_rule(rule_id="rule_001"):
    from src.services.productivity_integrations import AutomationRule, ToolType, EventType
    return AutomationRule(
        rule_id=rule_id,
        user_id="user_001",
        tool_type=ToolType.SLACK,
        connection_id="conn_001",
        event_type=EventType.CLIP_CREATED,
        action="post_message",
        target_location="C001",
        message_template="New clip: {title}",
        is_active=True,
    )


def _make_webhook(webhook_id="wh_001"):
    from src.services.third_party_integrations import IntegrationWebhook, IntegrationType, TriggerEvent
    return IntegrationWebhook(
        webhook_id=webhook_id,
        user_id="user_001",
        integration_type=IntegrationType.ZAPIER,
        trigger_event=TriggerEvent.CLIP_CREATED,
        webhook_url="https://hooks.zapier.com/hooks/catch/123/abc",
        is_active=True,
        headers={},
        created_at="2026-01-01T00:00:00",
        last_triggered=None,
        trigger_count=0,
    )


def _make_upload_result(success=True):
    from src.services.cloud_storage import UploadResult, StorageClass
    return UploadResult(
        success=success,
        file_key="clips/clip_001.mp4",
        public_url="https://storage.googleapis.com/viraclip/clips/clip_001.mp4" if success else None,
        size_bytes=52_428_800,
        etag="abc123",
        storage_class=StorageClass.STANDARD,
        upload_time_ms=350,
        error_message=None if success else "Bucket not found",
    )


# ===========================================================================
# 1. Productivity Integrations API
# ===========================================================================

class TestProductivityAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.productivity import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_connect_tool(self):
        client = self._get_client()
        conn = _make_tool_connection()
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.connect_tool",
            new_callable=AsyncMock,
            return_value=conn,
        ):
            resp = client.post("/productivity/tools/connect", json={
                "user_id": "user_001",
                "tool_type": "slack",
                "access_token": "tok_abc",
                "workspace_id": "ws_001",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "connected")
        self.assertEqual(data["connection"]["tool_type"], "slack")

    def test_connect_invalid_tool(self):
        client = self._get_client()
        resp = client.post("/productivity/tools/connect", json={
            "user_id": "user_001",
            "tool_type": "whatsapp",
            "access_token": "tok_abc",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_connections(self):
        client = self._get_client()
        connections = [
            {"connection_id": "conn_001", "tool_type": "slack",
             "workspace_name": "ViraClip Team", "is_active": True},
        ]
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.get_user_connections",
            return_value=connections,
        ):
            resp = client.get("/productivity/tools/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_disconnect_tool(self):
        client = self._get_client()
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.disconnect_tool",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/productivity/tools/conn_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "disconnected")

    def test_disconnect_tool_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.disconnect_tool",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/productivity/tools/missing")
        self.assertEqual(resp.status_code, 404)

    def test_create_automation_rule(self):
        client = self._get_client()
        rule = _make_automation_rule()
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.create_automation_rule",
            new_callable=AsyncMock,
            return_value=rule,
        ):
            resp = client.post("/productivity/rules", json={
                "user_id": "user_001",
                "tool_type": "slack",
                "event_type": "clip_created",
                "target_location": "C001",
                "message_template": "New clip: {title}",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["rule"]["event_type"], "clip_created")

    def test_create_rule_invalid_event(self):
        client = self._get_client()
        resp = client.post("/productivity/rules", json={
            "user_id": "user_001",
            "tool_type": "slack",
            "event_type": "asteroid_strike",
            "target_location": "C001",
            "message_template": "Test",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_rules(self):
        client = self._get_client()
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.get_user_automations",
            return_value=[{"rule_id": "rule_001", "tool_type": "slack"}],
        ):
            resp = client.get("/productivity/rules/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_handle_event(self):
        client = self._get_client()
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.handle_event",
            new_callable=AsyncMock,
            return_value=[{"rule_id": "rule_001", "success": True}],
        ):
            resp = client.post("/productivity/events/handle", json={
                "user_id": "user_001",
                "event_type": "clip_created",
                "event_data": {"clip_id": "clip_001", "title": "Test Clip"},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "handled")

    def test_activity_stats(self):
        client = self._get_client()
        with patch(
            "src.services.productivity_integrations.ProductivityIntegrationService.get_activity_stats",
            return_value={"total_actions": 50, "success_rate": 0.96},
        ):
            resp = client.get("/productivity/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("stats", resp.json())

    def test_list_tool_types(self):
        client = self._get_client()
        resp = client.get("/productivity/tool-types")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("slack", data["tool_types"])
        self.assertIn("notion", data["tool_types"])
        self.assertIn("clip_created", data["event_types"])


# ===========================================================================
# 2. Smart Auto Editor API
# ===========================================================================

class TestAutoEditorAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.auto_editor import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _word_timings(self):
        return [
            {"word": "This", "start": 0.0, "end": 0.3},
            {"word": "is", "start": 0.4, "end": 0.5},
            {"word": "amazing", "start": 0.6, "end": 1.0},
        ]

    def test_analyze_and_edit(self):
        client = self._get_client()
        edit_plan = {
            "decisions": [
                {"type": "silence_remove", "timestamp": 1.5, "duration": 0.8},
                {"type": "zoom_punch", "timestamp": 0.6, "duration": 0.3},
            ],
            "pacing_score": 0.72,
            "ffmpeg_script": "trim=0:5,",
        }
        with patch(
            "src.services.smart_auto_editor.SmartAutoEditor.analyze_and_edit",
            new_callable=AsyncMock,
            return_value=edit_plan,
        ):
            resp = client.post("/auto-editor/analyze", json={
                "transcript": "This is amazing content you need to watch.",
                "word_timings": self._word_timings(),
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("edit_plan", data)

    def test_analyze_empty_transcript(self):
        client = self._get_client()
        resp = client.post("/auto-editor/analyze", json={
            "transcript": "   ",
            "word_timings": self._word_timings(),
        })
        self.assertEqual(resp.status_code, 400)

    def test_analyze_empty_word_timings(self):
        client = self._get_client()
        resp = client.post("/auto-editor/analyze", json={
            "transcript": "This is some content.",
            "word_timings": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_apply_text_pops(self):
        client = self._get_client()
        with patch(
            "src.services.smart_auto_editor.SmartAutoEditor.apply_text_pops",
            new_callable=AsyncMock,
            return_value=Path("/app/data/clip_text.mp4"),
        ):
            resp = client.post("/auto-editor/text-pops", json={
                "clip_path": "/app/data/clip.mp4",
                "output_path": "/app/data/clip_text.mp4",
                "decisions": [
                    {"type": "TEXT_POP", "timestamp": 0.5, "duration": 1.0,
                     "parameters": {"text": "AMAZING!", "color": "#FF0050"}},
                ],
                "hook_offset": 0.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("output_path", resp.json())

    def test_apply_text_pops_empty_decisions(self):
        client = self._get_client()
        resp = client.post("/auto-editor/text-pops", json={
            "clip_path": "/app/data/clip.mp4",
            "output_path": "/app/data/out.mp4",
            "decisions": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_default_rules(self):
        client = self._get_client()
        resp = client.get("/auto-editor/default-rules")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("hook_zoom_enabled", data)
        self.assertIn("text_pop_enabled", data)
        self.assertIn("min_silence_sec", data)
        self.assertTrue(data["hook_zoom_enabled"])


# ===========================================================================
# 3. Third-Party Integrations API
# ===========================================================================

class TestIntegrationsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.integrations import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_register_webhook(self):
        client = self._get_client()
        webhook = _make_webhook()
        with patch(
            "src.services.third_party_integrations.ThirdPartyIntegrationService.register_webhook",
            new_callable=AsyncMock,
            return_value=webhook,
        ):
            resp = client.post("/integrations/webhooks", json={
                "user_id": "user_001",
                "integration_type": "zapier",
                "trigger_event": "clip_created",
                "webhook_url": "https://hooks.zapier.com/hooks/catch/123/abc",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "registered")
        self.assertEqual(data["webhook"]["integration_type"], "zapier")

    def test_register_webhook_invalid_url(self):
        client = self._get_client()
        resp = client.post("/integrations/webhooks", json={
            "user_id": "user_001",
            "integration_type": "zapier",
            "trigger_event": "clip_created",
            "webhook_url": "not-a-url",
        })
        self.assertEqual(resp.status_code, 400)

    def test_register_webhook_invalid_platform(self):
        client = self._get_client()
        resp = client.post("/integrations/webhooks", json={
            "user_id": "user_001",
            "integration_type": "myspace",
            "trigger_event": "clip_created",
            "webhook_url": "https://myspace.com/hook",
        })
        self.assertEqual(resp.status_code, 400)

    def test_register_webhook_invalid_event(self):
        client = self._get_client()
        resp = client.post("/integrations/webhooks", json={
            "user_id": "user_001",
            "integration_type": "zapier",
            "trigger_event": "alien_abduction",
            "webhook_url": "https://hooks.zapier.com/123",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_integrations(self):
        client = self._get_client()
        integrations = [
            {"webhook_id": "wh_001", "integration_type": "zapier",
             "webhook_url": "https://hooks.zapier.com/123", "is_active": True},
        ]
        with patch(
            "src.services.third_party_integrations.ThirdPartyIntegrationService.get_user_integrations",
            return_value=integrations,
        ):
            resp = client.get("/integrations/webhooks/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_toggle_integration(self):
        client = self._get_client()
        with patch(
            "src.services.third_party_integrations.ThirdPartyIntegrationService.toggle_integration",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.patch("/integrations/webhooks/wh_001/toggle", json={"active": False})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "disabled")

    def test_toggle_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.third_party_integrations.ThirdPartyIntegrationService.toggle_integration",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.patch("/integrations/webhooks/missing/toggle", json={"active": True})
        self.assertEqual(resp.status_code, 404)

    def test_delete_integration(self):
        client = self._get_client()
        with patch(
            "src.services.third_party_integrations.ThirdPartyIntegrationService.delete_integration",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/integrations/webhooks/wh_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_trigger_event(self):
        client = self._get_client()
        with patch(
            "src.services.third_party_integrations.ThirdPartyIntegrationService.trigger_integration",
            new_callable=AsyncMock,
            return_value=[{"webhook_id": "wh_001", "success": True, "status_code": 200}],
        ):
            resp = client.post("/integrations/trigger", json={
                "user_id": "user_001",
                "event": "clip_created",
                "data": {"clip_id": "clip_001"},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "triggered")

    def test_trigger_invalid_event(self):
        client = self._get_client()
        resp = client.post("/integrations/trigger", json={
            "user_id": "user_001",
            "event": "magic_happens",
            "data": {},
        })
        self.assertEqual(resp.status_code, 400)

    def test_integration_stats(self):
        client = self._get_client()
        with patch(
            "src.services.third_party_integrations.ThirdPartyIntegrationService.get_integration_stats",
            return_value={"total": 3, "active": 2, "total_triggers": 150},
        ):
            resp = client.get("/integrations/stats")
        self.assertEqual(resp.status_code, 200)

    def test_list_types(self):
        client = self._get_client()
        resp = client.get("/integrations/types")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("zapier", data["integration_types"])
        self.assertIn("clip_created", data["trigger_events"])


# ===========================================================================
# 4. Cloud Storage API
# ===========================================================================

class TestCloudStorageAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.cloud_storage import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_upload_file(self):
        client = self._get_client()
        result = _make_upload_result()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.upload_file",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/cloud-storage/upload", json={
                "local_path": "/app/data/clip.mp4",
                "file_key": "clips/clip_001.mp4",
                "storage_class": "standard",
                "public": False,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "uploaded")
        self.assertAlmostEqual(data["result"]["size_mb"], 50.0)

    def test_upload_file_failure(self):
        client = self._get_client()
        result = _make_upload_result(success=False)
        with patch(
            "src.services.cloud_storage.CloudStorageManager.upload_file",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/cloud-storage/upload", json={
                "local_path": "/app/data/clip.mp4",
                "file_key": "clips/clip_001.mp4",
            })
        self.assertEqual(resp.status_code, 500)

    def test_upload_invalid_provider(self):
        client = self._get_client()
        resp = client.post("/cloud-storage/upload", json={
            "local_path": "/app/data/clip.mp4",
            "file_key": "clips/clip_001.mp4",
            "provider": "dropbox",
        })
        self.assertEqual(resp.status_code, 400)

    def test_upload_invalid_storage_class(self):
        client = self._get_client()
        resp = client.post("/cloud-storage/upload", json={
            "local_path": "/app/data/clip.mp4",
            "file_key": "clips/clip_001.mp4",
            "storage_class": "ultra_cheap",
        })
        self.assertEqual(resp.status_code, 400)

    def test_download_file(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.download_file",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/cloud-storage/download", json={
                "file_key": "clips/clip_001.mp4",
                "local_path": "/app/data/clip_dl.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "downloaded")

    def test_download_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.download_file",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/cloud-storage/download", json={
                "file_key": "clips/missing.mp4",
                "local_path": "/app/data/out.mp4",
            })
        self.assertEqual(resp.status_code, 404)

    def test_presigned_url(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.generate_presigned_url",
            new_callable=AsyncMock,
            return_value="https://storage.googleapis.com/signed?token=xyz&expires=999",
        ):
            resp = client.post("/cloud-storage/presigned-url", json={
                "file_key": "clips/clip_001.mp4",
                "expiration": 3600,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("url", resp.json())

    def test_presigned_url_invalid_expiry(self):
        client = self._get_client()
        resp = client.post("/cloud-storage/presigned-url", json={
            "file_key": "clips/clip_001.mp4",
            "expiration": 0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_presigned_url_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.generate_presigned_url",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/cloud-storage/presigned-url", json={
                "file_key": "clips/missing.mp4",
            })
        self.assertEqual(resp.status_code, 404)

    def test_delete_file(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.delete_file",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.request("DELETE", "/cloud-storage/files",
                                  json={"file_key": "clips/clip_001.mp4"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_delete_file_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.delete_file",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.request("DELETE", "/cloud-storage/files",
                                  json={"file_key": "clips/missing.mp4"})
        self.assertEqual(resp.status_code, 404)

    def test_list_files(self):
        client = self._get_client()
        from src.services.cloud_storage import StorageObject, StorageClass
        from datetime import datetime
        objs = [
            StorageObject(
                key="clips/clip_001.mp4",
                size_bytes=52_428_800,
                last_modified=datetime(2026, 1, 1),
                etag="abc",
                storage_class=StorageClass.STANDARD,
                public_url=None,
                metadata={},
            )
        ]
        with patch(
            "src.services.cloud_storage.CloudStorageManager.list_files",
            new_callable=AsyncMock,
            return_value=objs,
        ):
            resp = client.get("/cloud-storage/files?prefix=clips/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_change_storage_class(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.move_to_storage_class",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.patch("/cloud-storage/storage-class", json={
                "file_key": "clips/clip_001.mp4",
                "new_class": "glacier",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "moved")

    def test_change_storage_class_invalid(self):
        client = self._get_client()
        resp = client.patch("/cloud-storage/storage-class", json={
            "file_key": "clips/clip_001.mp4",
            "new_class": "quantum_storage",
        })
        self.assertEqual(resp.status_code, 400)

    def test_usage_stats(self):
        client = self._get_client()
        with patch(
            "src.services.cloud_storage.CloudStorageManager.get_usage_stats",
            return_value={"total_uploads": 200, "total_size_gb": 45.2},
        ):
            resp = client.get("/cloud-storage/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("stats", resp.json())

    def test_list_providers(self):
        client = self._get_client()
        resp = client.get("/cloud-storage/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("aws_s3", data["providers"])
        self.assertIn("standard", data["storage_classes"])


if __name__ == "__main__":
    unittest.main()
