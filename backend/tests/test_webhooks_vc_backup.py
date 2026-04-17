"""
Tests for:
  1. Webhook Management API (/webhooks/*)
  2. Version Control API (/version-control/*)
  3. Backup & Recovery API (/backup/*)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_endpoint(ep_id="ep_001"):
    from src.services.webhook_service import WebhookEndpoint, WebhookEventType
    return WebhookEndpoint(
        endpoint_id=ep_id,
        url="https://example.com/webhook",
        secret="supersecret",
        events=[WebhookEventType.TASK_COMPLETED, WebhookEventType.CLIP_READY],
        is_active=True,
        created_at="2026-01-01T00:00:00",
        retry_count=3,
        timeout_seconds=30,
        headers={},
    )


def _make_delivery(d_id="del_001", status="delivered"):
    from src.services.webhook_service import WebhookDelivery, WebhookEventType
    return WebhookDelivery(
        delivery_id=d_id,
        endpoint_id="ep_001",
        event_type=WebhookEventType.TASK_COMPLETED,
        payload={"task_id": "t1"},
        status=status,
        attempts=1,
        created_at="2026-01-01T00:00:00",
        delivered_at="2026-01-01T00:00:01",
        http_status=200,
    )


def _make_clip_version(ver_id="v001", clip_id="clip_001"):
    from src.services.version_control import ChangeType, ClipVersion
    return ClipVersion(
        version_id=ver_id,
        clip_id=clip_id,
        version_number=1,
        parent_version_id=None,
        author_id="user_001",
        author_name="Alice",
        change_type=ChangeType.CREATE,
        change_summary="Initial version",
        file_path=Path("/app/data/versions/clip_001/v001.mp4"),
        file_hash="abc123",
        file_size=1024000,
        metadata={"duration": 30.0, "effects": ["zoom"]},
        created_at="2026-01-01T00:00:00",
        tags=[],
    )


def _make_branch(branch_id="br_001", clip_id="clip_001"):
    from src.services.version_control import Branch
    return Branch(
        branch_id=branch_id,
        clip_id=clip_id,
        name="main",
        description="Main branch",
        head_version_id="v001",
        is_main=True,
        created_by="user_001",
        created_at="2026-01-01T00:00:00",
        is_active=True,
    )


def _make_diff():
    from src.services.version_control import ChangeDiff
    return ChangeDiff(
        from_version_id="v001",
        to_version_id="v002",
        added_effects=["fade"],
        removed_effects=["zoom"],
        duration_change=-5.0,
        metadata_changes={"duration": {"from": 35.0, "to": 30.0}},
        thumbnail_changed=False,
    )


def _make_backup(backup_id="bk_001", status="completed"):
    from src.services.backup_recovery import BackupRecord
    return BackupRecord(
        backup_id=backup_id,
        name="system",
        started_at="2026-01-01T00:00:00",
        completed_at="2026-01-01T00:01:00",
        size_bytes=1048576,
        file_count=42,
        status=status,
        error_message=None,
        location=Path("/app/backups/system_20260101.tar.gz"),
    )


# ===========================================================================
# 1. Webhook Management API
# ===========================================================================

class TestWebhooksAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.webhooks import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_register_endpoint(self):
        client = self._get_client()
        ep = _make_endpoint()
        with patch(
            "src.services.webhook_service.WebhookManager.register_endpoint",
            return_value=ep,
        ):
            resp = client.post("/webhooks/endpoints", json={
                "user_id": "user_001",
                "url": "https://example.com/webhook",
                "secret": "supersecret",
                "events": ["task.completed", "clip.ready"],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "registered")
        self.assertIn("task.completed", data["endpoint"]["events"])

    def test_register_invalid_url(self):
        client = self._get_client()
        resp = client.post("/webhooks/endpoints", json={
            "user_id": "user_001",
            "url": "ftp://bad.url",
            "secret": "s",
            "events": ["task.completed"],
        })
        self.assertEqual(resp.status_code, 400)

    def test_register_empty_events(self):
        client = self._get_client()
        resp = client.post("/webhooks/endpoints", json={
            "user_id": "user_001",
            "url": "https://example.com/wh",
            "secret": "s",
            "events": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_register_unknown_event(self):
        client = self._get_client()
        resp = client.post("/webhooks/endpoints", json={
            "user_id": "user_001",
            "url": "https://example.com/wh",
            "secret": "s",
            "events": ["task.unknown"],
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_endpoints(self):
        client = self._get_client()
        with patch(
            "src.services.webhook_service.WebhookManager.get_user_endpoints",
            return_value=[_make_endpoint()],
        ):
            resp = client.get("/webhooks/endpoints/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_delete_endpoint(self):
        client = self._get_client()
        with patch(
            "src.services.webhook_service.WebhookManager.delete_endpoint",
            return_value=True,
        ):
            resp = client.delete("/webhooks/endpoints/user_001/ep_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_delete_endpoint_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.webhook_service.WebhookManager.delete_endpoint",
            return_value=False,
        ):
            resp = client.delete("/webhooks/endpoints/user_001/unknown")
        self.assertEqual(resp.status_code, 404)

    def test_trigger_event(self):
        client = self._get_client()
        deliveries = [_make_delivery()]
        with patch(
            "src.services.webhook_service.WebhookManager.trigger_event",
            new_callable=AsyncMock,
            return_value=deliveries,
        ):
            resp = client.post("/webhooks/trigger", json={
                "user_id": "user_001",
                "event_type": "task.completed",
                "payload": {"task_id": "t1", "clip_count": 3},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["deliveries"], 1)
        self.assertEqual(data["results"][0]["status"], "delivered")

    def test_get_delivery_history(self):
        client = self._get_client()
        with patch(
            "src.services.webhook_service.WebhookManager.get_delivery_history",
            return_value=[_make_delivery()],
        ):
            resp = client.get("/webhooks/deliveries/ep_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_retry_failed(self):
        client = self._get_client()
        with patch(
            "src.services.webhook_service.WebhookManager.retry_failed_deliveries",
            new_callable=AsyncMock,
            return_value=2,
        ):
            resp = client.post("/webhooks/deliveries/ep_001/retry")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["retried_count"], 2)

    def test_list_event_types(self):
        client = self._get_client()
        resp = client.get("/webhooks/events")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("task.completed", resp.json()["events"])
        self.assertIn("clip.ready", resp.json()["events"])


# ===========================================================================
# 2. Version Control API
# ===========================================================================

class TestVersionControlAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.version_control import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_history(self):
        client = self._get_client()
        history = [
            {"version_id": "v001", "version_number": 1, "author": "Alice",
             "change_type": "create", "change_summary": "Initial",
             "created_at": "2026-01-01T00:00:00", "file_size": 1024, "tags": []},
        ]
        with patch(
            "src.services.version_control.VersionControlService.get_version_history",
            new_callable=AsyncMock,
            return_value=history,
        ):
            resp = client.get("/version-control/clips/clip_001/history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_create_version(self):
        client = self._get_client()
        version = _make_clip_version("v002")
        with patch(
            "src.services.version_control.VersionControlService.create_version",
            new_callable=AsyncMock,
            return_value=version,
        ):
            resp = client.post("/version-control/clips/clip_001/versions", json={
                "clip_id": "clip_001",
                "file_path": "/app/data/clip_001.mp4",
                "parent_version_id": "v001",
                "author_id": "user_001",
                "author_name": "Alice",
                "change_summary": "Added fade effect",
                "change_type": "modify",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["version"]["change_type"], "create")

    def test_create_version_invalid_change_type(self):
        client = self._get_client()
        resp = client.post("/version-control/clips/clip_001/versions", json={
            "clip_id": "clip_001",
            "file_path": "/app/clip.mp4",
            "parent_version_id": "v001",
            "author_id": "user_001",
            "author_name": "Alice",
            "change_summary": "Test",
            "change_type": "explode",
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_version_parent_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.version_control.VersionControlService.create_version",
            new_callable=AsyncMock,
            side_effect=ValueError("Parent version not_found not found"),
        ):
            resp = client.post("/version-control/clips/clip_001/versions", json={
                "clip_id": "clip_001",
                "file_path": "/app/clip.mp4",
                "parent_version_id": "not_found",
                "author_id": "u1",
                "author_name": "Bob",
                "change_summary": "Test",
            })
        self.assertEqual(resp.status_code, 404)

    def test_compare_versions(self):
        client = self._get_client()
        diff = _make_diff()
        with patch(
            "src.services.version_control.VersionControlService.compare_versions",
            new_callable=AsyncMock,
            return_value=diff,
        ):
            resp = client.get("/version-control/versions/v001/compare/v002")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["diff"]
        self.assertEqual(data["added_effects"], ["fade"])
        self.assertEqual(data["duration_change"], -5.0)

    def test_compare_versions_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.version_control.VersionControlService.compare_versions",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get("/version-control/versions/v_bad/compare/v_also_bad")
        self.assertEqual(resp.status_code, 404)

    def test_revert(self):
        client = self._get_client()
        version = _make_clip_version("v003")
        with patch(
            "src.services.version_control.VersionControlService.revert_to_version",
            new_callable=AsyncMock,
            return_value=version,
        ):
            resp = client.post("/version-control/clips/clip_001/revert", json={
                "clip_id": "clip_001",
                "version_id": "v001",
                "author_id": "user_001",
                "author_name": "Alice",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "reverted")

    def test_revert_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.version_control.VersionControlService.revert_to_version",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/version-control/clips/clip_001/revert", json={
                "clip_id": "clip_001",
                "version_id": "missing",
                "author_id": "u1",
                "author_name": "Bob",
            })
        self.assertEqual(resp.status_code, 404)

    def test_tag_version(self):
        client = self._get_client()
        with patch(
            "src.services.version_control.VersionControlService.tag_version",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/version-control/versions/v001/tag", json={
                "version_id": "v001",
                "tag": "release-1.0",
                "author_id": "user_001",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["tag"], "release-1.0")

    def test_list_branches(self):
        client = self._get_client()
        branch_data = [{"branch_id": "br_001", "name": "main", "is_main": True}]
        with patch(
            "src.services.version_control.VersionControlService.get_branches",
            return_value=branch_data,
        ):
            resp = client.get("/version-control/clips/clip_001/branches")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_create_branch(self):
        client = self._get_client()
        branch = _make_branch("br_002")
        with patch(
            "src.services.version_control.VersionControlService.create_branch",
            new_callable=AsyncMock,
            return_value=branch,
        ):
            resp = client.post("/version-control/branches", json={
                "clip_id": "clip_001",
                "name": "experimental",
                "description": "Trying new effects",
                "head_version_id": "v001",
                "created_by": "user_001",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "created")

    def test_merge_branches(self):
        client = self._get_client()
        version = _make_clip_version("v_merge")
        with patch(
            "src.services.version_control.VersionControlService.merge_branches",
            new_callable=AsyncMock,
            return_value=version,
        ):
            resp = client.post("/version-control/branches/merge", json={
                "source_branch_id": "br_002",
                "target_branch_id": "br_001",
                "author_id": "user_001",
                "author_name": "Alice",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "merged")

    def test_get_stats(self):
        client = self._get_client()
        stats = {"total_versions": 10, "total_branches": 3,
                 "total_clips_with_versions": 5, "total_storage_bytes": 1024000,
                 "total_storage_gb": 0.001, "average_versions_per_clip": 2.0}
        with patch(
            "src.services.version_control.VersionControlService.get_version_stats",
            return_value=stats,
        ):
            resp = client.get("/version-control/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["total_versions"], 10)

    def test_list_change_types(self):
        client = self._get_client()
        resp = client.get("/version-control/change-types")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("modify", resp.json()["change_types"])
        self.assertIn("merge", resp.json()["change_types"])


# ===========================================================================
# 3. Backup & Recovery API
# ===========================================================================

class TestBackupAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.backup import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_backup(self):
        client = self._get_client()
        record = _make_backup()
        with patch(
            "src.services.backup_recovery.BackupManager.create_backup",
            new_callable=AsyncMock,
            return_value=record,
        ):
            resp = client.post("/backup", json={
                "name": "system",
                "source_paths": ["/app/data", "/app/config"],
                "compress": True,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["backup"]["status"], "completed")

    def test_create_backup_empty_paths(self):
        client = self._get_client()
        resp = client.post("/backup", json={"name": "test", "source_paths": []})
        self.assertEqual(resp.status_code, 400)

    def test_list_backups(self):
        client = self._get_client()
        with patch(
            "src.services.backup_recovery.BackupManager.list_backups",
            return_value=[_make_backup()],
        ):
            resp = client.get("/backup")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_list_backups_filtered(self):
        client = self._get_client()
        with patch(
            "src.services.backup_recovery.BackupManager.list_backups",
            return_value=[_make_backup()],
        ):
            resp = client.get("/backup?name=system")
        self.assertEqual(resp.status_code, 200)

    def test_restore_backup(self):
        client = self._get_client()
        with patch(
            "src.services.backup_recovery.BackupManager.restore_backup",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/backup/restore", json={"backup_id": "bk_001"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "restored")

    def test_restore_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.backup_recovery.BackupManager.restore_backup",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/backup/restore", json={"backup_id": "missing"})
        self.assertEqual(resp.status_code, 404)

    def test_cleanup(self):
        client = self._get_client()
        with patch(
            "src.services.backup_recovery.BackupManager.cleanup_old_backups",
            return_value=3,
        ):
            resp = client.delete("/backup/cleanup?retention_days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["removed_count"], 3)

    def test_cleanup_invalid_retention(self):
        client = self._get_client()
        resp = client.delete("/backup/cleanup?retention_days=0")
        self.assertEqual(resp.status_code, 400)

    def test_backup_status(self):
        client = self._get_client()
        status = {
            "total_backups": 5, "successful": 5, "failed": 0,
            "total_size_bytes": 5242880, "last_backup": {"id": "bk_001", "status": "completed"},
            "backup_directory": "/app/backups", "health": "healthy",
        }
        with patch(
            "src.services.backup_recovery.BackupManager.get_backup_status",
            return_value=status,
        ):
            resp = client.get("/backup/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["backup_status"]["health"], "healthy")

    def test_disaster_recovery(self):
        client = self._get_client()
        results = {"database": True, "uploads": True, "clips": True, "config": True}
        with patch(
            "src.services.backup_recovery.DisasterRecovery.perform_recovery",
            new_callable=AsyncMock,
            return_value=results,
        ):
            resp = client.post("/backup/disaster-recovery", json={"backup_id": "bk_001"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["results"]["database"])

    def test_disaster_recovery_partial(self):
        client = self._get_client()
        results = {"database": True, "uploads": True}
        with patch(
            "src.services.backup_recovery.DisasterRecovery.perform_recovery",
            new_callable=AsyncMock,
            return_value=results,
        ):
            resp = client.post("/backup/disaster-recovery", json={
                "backup_id": "bk_001",
                "components": ["database", "uploads"],
            })
        self.assertEqual(resp.status_code, 200)

    def test_recovery_readiness(self):
        client = self._get_client()
        status = {
            "recovery_ready": True,
            "recent_backups_count": 3,
            "last_successful_backup": "2026-01-01T00:00:00",
            "recovery_components": ["database", "uploads", "clips", "config"],
            "test_recovery_recommended": True,
        }
        with patch(
            "src.services.backup_recovery.DisasterRecovery.get_recovery_status",
            return_value=status,
        ):
            resp = client.get("/backup/disaster-recovery/status")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["recovery_status"]["recovery_ready"])


if __name__ == "__main__":
    unittest.main()
