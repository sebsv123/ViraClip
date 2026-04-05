"""
Tests for:
  1. Collaboration API (/collaboration/*)
  2. Content Moderation API (/moderation/*)
  3. Email Reports API (/reports/*)
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(project_id="proj_001", name="Test Project", owner="user_a"):
    from src.services.collaboration_service import (
        Collaborator, CollaborationProject, Permission, UserRole,
    )
    return CollaborationProject(
        project_id=project_id,
        name=name,
        owner_id=owner,
        created_at=datetime.now().isoformat(),
        collaborators={
            owner: Collaborator(
                user_id=owner,
                role=UserRole.OWNER,
                joined_at=datetime.now().isoformat(),
                added_by=owner,
                permissions=set(Permission),
            )
        },
        task_ids=[],
        settings={},
    )


def _make_comment(comment_id="cmt_001", project_id="proj_001", user_id="user_a"):
    from src.services.collaboration_service import Comment
    return Comment(
        comment_id=comment_id,
        project_id=project_id,
        task_id=None,
        clip_id=None,
        user_id=user_id,
        content="Looks great!",
        timestamp=datetime.now().isoformat(),
        resolved=False,
        replies=[],
        position=None,
    )


def _make_moderation_result(content_id="content_001", is_safe=True):
    from src.services.content_moderation import ContentCategory, ModerationResult
    return ModerationResult(
        content_id=content_id,
        is_safe=is_safe,
        category=ContentCategory.SAFE if is_safe else ContentCategory.SPAM,
        confidence=1.0 if is_safe else 0.6,
        flagged_keywords=[],
        reason="No violations detected" if is_safe else "Spam detected",
        suggested_action="allow" if is_safe else "flag_for_review",
        review_required=not is_safe,
    )


def _make_subscription(sub_id="sub_001", user_id="anon"):
    from src.services.email_reports import (
        ReportFrequency, ReportSubscription, ReportType,
    )
    return ReportSubscription(
        subscription_id=sub_id,
        user_id=user_id,
        email="anon@example.com",
        report_type=ReportType.DAILY_SUMMARY,
        frequency=ReportFrequency.DAILY,
        is_active=True,
        created_at=datetime.now().isoformat(),
        last_sent=None,
        preferences={},
    )


def _make_email_report(report_id="rep_001", user_id="anon"):
    from src.services.email_reports import EmailReport, ReportFrequency, ReportType
    return EmailReport(
        report_id=report_id,
        user_id=user_id,
        report_type=ReportType.DAILY_SUMMARY,
        frequency=ReportFrequency.DAILY,
        subject="Your Daily ViraClip Summary",
        content_html="<html>...</html>",
        content_text="...",
        created_at=datetime.now().isoformat(),
        sent_at=None,
        status="pending",
        metrics={},
    )


# ===========================================================================
# 1. Collaboration API
# ===========================================================================

class TestCollaborationAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.collaboration import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_project(self):
        client = self._get_client()
        proj = _make_project()
        with patch(
            "src.services.collaboration_service.CollaborationService.create_project",
            return_value=proj,
        ):
            resp = client.post("/collaboration/projects", json={"name": "Test Project"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["project"]["project_id"], "proj_001")

    def test_list_projects(self):
        client = self._get_client()
        mock_list = [{"project_id": "proj_001", "name": "Test", "role": "owner", "created_at": "2026-01-01T00:00:00", "collaborator_count": 1, "task_count": 0}]
        with patch(
            "src.services.collaboration_service.CollaborationService.get_user_projects",
            return_value=mock_list,
        ):
            resp = client.get("/collaboration/projects")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_get_project_success(self):
        client = self._get_client()
        proj = _make_project()
        svc = MagicMock()
        svc._projects = {"proj_001": proj}
        svc.can_view.return_value = True
        with patch("src.api.routes.collaboration.get_collaboration_service", return_value=svc):
            resp = client.get("/collaboration/projects/proj_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["project"]["name"], "Test Project")

    def test_get_project_not_found(self):
        client = self._get_client()
        svc = MagicMock()
        svc._projects = {}
        with patch("src.api.routes.collaboration.get_collaboration_service", return_value=svc):
            resp = client.get("/collaboration/projects/missing")
        self.assertEqual(resp.status_code, 404)

    def test_get_project_no_permission(self):
        client = self._get_client()
        proj = _make_project()
        svc = MagicMock()
        svc._projects = {"proj_001": proj}
        svc.can_view.return_value = False
        with patch("src.api.routes.collaboration.get_collaboration_service", return_value=svc):
            resp = client.get("/collaboration/projects/proj_001")
        self.assertEqual(resp.status_code, 403)

    def test_add_member_success(self):
        client = self._get_client()
        with patch(
            "src.services.collaboration_service.CollaborationService.add_collaborator",
            return_value=True,
        ):
            resp = client.post("/collaboration/projects/proj_001/members", json={
                "user_id": "user_b",
                "role": "editor",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "added")

    def test_add_member_invalid_role(self):
        client = self._get_client()
        resp = client.post("/collaboration/projects/proj_001/members", json={
            "user_id": "user_b",
            "role": "superhero",
        })
        self.assertEqual(resp.status_code, 400)

    def test_add_member_permission_denied(self):
        client = self._get_client()
        with patch(
            "src.services.collaboration_service.CollaborationService.add_collaborator",
            return_value=False,
        ):
            resp = client.post("/collaboration/projects/proj_001/members", json={
                "user_id": "user_b",
                "role": "viewer",
            })
        self.assertEqual(resp.status_code, 403)

    def test_remove_member_success(self):
        client = self._get_client()
        with patch(
            "src.services.collaboration_service.CollaborationService.remove_collaborator",
            return_value=True,
        ):
            resp = client.delete("/collaboration/projects/proj_001/members/user_b")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "removed")

    def test_remove_member_failure(self):
        client = self._get_client()
        with patch(
            "src.services.collaboration_service.CollaborationService.remove_collaborator",
            return_value=False,
        ):
            resp = client.delete("/collaboration/projects/proj_001/members/owner")
        self.assertEqual(resp.status_code, 403)

    def test_add_comment_success(self):
        client = self._get_client()
        comment = _make_comment()
        with patch(
            "src.services.collaboration_service.CollaborationService.add_comment",
            return_value=comment,
        ):
            resp = client.post("/collaboration/projects/proj_001/comments", json={
                "content": "Looks great!",
                "clip_id": "clip_42",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["comment"]["content"], "Looks great!")

    def test_add_comment_permission_denied(self):
        client = self._get_client()
        with patch(
            "src.services.collaboration_service.CollaborationService.add_comment",
            return_value=None,
        ):
            resp = client.post("/collaboration/projects/proj_001/comments", json={"content": "Hi"})
        self.assertEqual(resp.status_code, 403)

    def test_get_comments(self):
        client = self._get_client()
        comments = [_make_comment()]
        with patch(
            "src.services.collaboration_service.CollaborationService.get_comments",
            return_value=comments,
        ):
            resp = client.get("/collaboration/projects/proj_001/comments")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_resolve_comment_success(self):
        client = self._get_client()
        with patch(
            "src.services.collaboration_service.CollaborationService.resolve_comment",
            return_value=True,
        ):
            resp = client.post("/collaboration/projects/proj_001/comments/cmt_001/resolve")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "resolved")

    def test_resolve_comment_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.collaboration_service.CollaborationService.resolve_comment",
            return_value=False,
        ):
            resp = client.post("/collaboration/projects/proj_001/comments/missing/resolve")
        self.assertEqual(resp.status_code, 404)

    def test_get_activity(self):
        client = self._get_client()
        mock_activities = [
            {"type": "comment", "user_id": "user_a", "timestamp": "2026-04-06T10:00:00", "content": "Nice"},
        ]
        with patch(
            "src.services.collaboration_service.CollaborationService.get_project_activity",
            return_value=mock_activities,
        ):
            resp = client.get("/collaboration/projects/proj_001/activity")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_list_roles(self):
        client = self._get_client()
        resp = client.get("/collaboration/roles")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("owner", data["roles"])
        self.assertIn("edit", data["permissions"])
        self.assertIn("owner", data["role_permissions"])


# ===========================================================================
# 2. Content Moderation API
# ===========================================================================

class TestModerationAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.moderation import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_moderate_text_safe(self):
        client = self._get_client()
        result = _make_moderation_result(is_safe=True)
        with patch(
            "src.services.content_moderation.ContentModerationService.moderate_text",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/moderation/text", json={
                "text": "This is a great tutorial!",
                "content_id": "content_001",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_safe"])
        self.assertEqual(data["suggested_action"], "allow")

    def test_moderate_text_unsafe(self):
        client = self._get_client()
        result = _make_moderation_result(is_safe=False)
        with patch(
            "src.services.content_moderation.ContentModerationService.moderate_text",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/moderation/text", json={
                "text": "Buy now! Click here for free giveaway",
                "content_id": "spam_001",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_safe"])
        self.assertEqual(data["category"], "spam")
        self.assertTrue(data["review_required"])

    def test_moderate_metadata(self):
        client = self._get_client()
        mock_result = {
            "is_safe": True,
            "category": "safe",
            "confidence": 1.0,
            "components_checked": 3,
        }
        with patch(
            "src.services.content_moderation.ContentModerationService.moderate_video_metadata",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/moderation/metadata", json={
                "video_id": "vid_001",
                "title": "Amazing Tutorial",
                "description": "Learn something cool",
                "tags": ["tutorial", "education"],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_safe"])

    def test_moderate_transcript(self):
        client = self._get_client()
        with patch(
            "src.services.content_moderation.ContentModerationService.moderate_transcript",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.post("/moderation/transcript", json={
                "transcript": "Hello, welcome to this tutorial.",
                "task_id": "task_001",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_clean"])
        self.assertEqual(data["violation_count"], 0)

    def test_moderate_transcript_with_violations(self):
        client = self._get_client()
        violations = [{"segment_index": 0, "text": "spam content", "violation": "spam", "confidence": 0.8, "keywords": ["spam"]}]
        with patch(
            "src.services.content_moderation.ContentModerationService.moderate_transcript",
            new_callable=AsyncMock,
            return_value=violations,
        ):
            resp = client.post("/moderation/transcript", json={
                "transcript": "Buy now! Click here for free giveaway!",
                "task_id": "task_002",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_clean"])
        self.assertEqual(data["violation_count"], 1)

    def test_validate_clip_allowed(self):
        client = self._get_client()
        with patch(
            "src.services.content_moderation.SafetyFilter.filter_clip_content",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            resp = client.post("/moderation/clip/validate", json={
                "clip_id": "clip_001",
                "title": "Great Tutorial",
                "transcript": "Today we learn Python.",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["allowed"])
        self.assertIsNone(data["reason"])

    def test_validate_clip_blocked(self):
        client = self._get_client()
        with patch(
            "src.services.content_moderation.SafetyFilter.filter_clip_content",
            new_callable=AsyncMock,
            return_value=(False, "Blocked: 1 high-confidence violations detected"),
        ):
            resp = client.post("/moderation/clip/validate", json={
                "clip_id": "clip_002",
                "transcript": "Kill everyone and use violence.",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["allowed"])
        self.assertIn("Blocked", data["reason"])

    def test_get_safety_score(self):
        client = self._get_client()
        with patch(
            "src.services.content_moderation.ContentModerationService.get_safety_score",
            return_value=95.0,
        ):
            resp = client.get("/moderation/score/content_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["safety_score"], 95.0)

    def test_batch_moderate(self):
        client = self._get_client()
        results = [_make_moderation_result(f"item_{i}") for i in range(3)]
        with patch(
            "src.services.content_moderation.ContentModerationService.batch_moderate",
            new_callable=AsyncMock,
            return_value=results,
        ):
            resp = client.post("/moderation/batch", json={
                "items": [{"id": f"item_{i}", "text": "Hello world"} for i in range(3)]
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 3)

    def test_batch_moderate_empty(self):
        client = self._get_client()
        resp = client.post("/moderation/batch", json={"items": []})
        self.assertEqual(resp.status_code, 400)

    def test_list_categories(self):
        client = self._get_client()
        resp = client.get("/moderation/categories")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("safe", resp.json()["categories"])
        self.assertIn("spam", resp.json()["categories"])


# ===========================================================================
# 3. Email Reports API
# ===========================================================================

class TestReportsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.reports import router
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
            resp = client.post("/reports/subscribe", json={
                "email": "user@example.com",
                "report_type": "daily_summary",
                "frequency": "daily",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "subscribed")
        self.assertEqual(data["subscription"]["report_type"], "daily_summary")

    def test_subscribe_invalid_type(self):
        client = self._get_client()
        resp = client.post("/reports/subscribe", json={
            "email": "user@example.com",
            "report_type": "flying_saucer_report",
            "frequency": "daily",
        })
        self.assertEqual(resp.status_code, 400)

    def test_subscribe_invalid_frequency(self):
        client = self._get_client()
        resp = client.post("/reports/subscribe", json={
            "email": "user@example.com",
            "report_type": "daily_summary",
            "frequency": "hourly_infinity",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_subscriptions(self):
        client = self._get_client()
        subs = [_make_subscription()]
        with patch(
            "src.services.email_reports.EmailReportService.list_user_subscriptions",
            return_value=subs,
        ):
            resp = client.get("/reports/subscriptions")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_unsubscribe_success(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.unsubscribe",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/reports/subscriptions/sub_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "unsubscribed")

    def test_unsubscribe_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.unsubscribe",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/reports/subscriptions/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_generate_report_no_send(self):
        client = self._get_client()
        report = _make_email_report()
        with patch(
            "src.services.email_reports.EmailReportService.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            resp = client.post("/reports/generate", json={
                "report_type": "daily_summary",
                "data": {"username": "Alice", "videos_processed": 3, "clips_generated": 7,
                         "avg_virality": 82, "top_clip": "Hook intro", "dashboard_url": "http://localhost/dashboard"},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "generated")
        self.assertFalse(data["sent"])

    def test_generate_report_with_send(self):
        client = self._get_client()
        report = _make_email_report()
        with patch(
            "src.services.email_reports.EmailReportService.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ), patch(
            "src.services.email_reports.EmailReportService.send_report",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/reports/generate", json={
                "report_type": "daily_summary",
                "data": {},
                "send_to": "alice@example.com",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["sent"])

    def test_send_report_success(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.send_report",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/reports/send/rep_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "sent")

    def test_send_report_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.send_report",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/reports/send/missing")
        self.assertEqual(resp.status_code, 404)

    def test_process_scheduled(self):
        client = self._get_client()
        with patch(
            "src.services.email_reports.EmailReportService.process_scheduled_reports",
            new_callable=AsyncMock,
            return_value=["rep_001", "rep_002"],
        ):
            resp = client.post("/reports/process-scheduled")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["sent_count"], 2)

    def test_get_stats(self):
        client = self._get_client()
        mock_stats = {"total_reports": 20, "sent": 18, "failed": 1, "pending": 1, "active_subscriptions": 5}
        with patch(
            "src.services.email_reports.EmailReportService.get_report_stats",
            return_value=mock_stats,
        ):
            resp = client.get("/reports/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["sent"], 18)

    def test_list_report_types(self):
        client = self._get_client()
        resp = client.get("/reports/types")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("daily_summary", data["report_types"])
        self.assertIn("weekly", data["frequencies"])


if __name__ == "__main__":
    unittest.main()
