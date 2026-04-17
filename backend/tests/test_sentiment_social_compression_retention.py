"""
Tests for:
  1. Sentiment Analysis API (/sentiment/*)
  2. Social Media Integration API (/social-media/*)
  3. Video Compression API (/compression/*)
  4. Data Retention API (/retention/*)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sentiment_result():
    from src.services.sentiment_analyzer import (
        EmotionType, SentimentAnalysisResult, SentimentCategory, SentimentSegment,
    )
    return SentimentAnalysisResult(
        overall_sentiment=0.65,
        overall_category=SentimentCategory.POSITIVE,
        confidence=0.8,
        segments=[
            SentimentSegment(
                start_time=0.0, end_time=5.0,
                text="This is amazing content!",
                sentiment_score=0.7, confidence=0.85,
                dominant_emotion=EmotionType.JOY,
                keywords=["amazing"],
            )
        ],
        dominant_emotions=[(EmotionType.EXCITEMENT, 0.6), (EmotionType.JOY, 0.4)],
        sentiment_trend="improving",
        viral_correlation=0.78,
    )


def _make_account(acct_id="acc_001", platform="tiktok"):
    from src.services.social_integration import SocialMediaService, SocialPlatform, PlatformAccount
    return PlatformAccount(
        account_id=acct_id,
        user_id="user_001",
        platform=SocialPlatform(platform),
        account_name="@alice",
        access_token="tok_123",
        refresh_token=None,
        token_expires_at=None,
        is_active=True,
        metadata={},
    )


def _make_publish_result(success=True):
    from src.services.social_integration import PublishResult, SocialPlatform
    return PublishResult(
        success=success,
        platform=SocialPlatform.TIKTOK,
        post_id="post_abc" if success else None,
        post_url="https://tiktok.com/@alice/video/post_abc" if success else None,
        error_message=None if success else "Token expired",
        published_at="2026-01-01T00:00:00" if success else None,
        engagement_prediction=0.75 if success else None,
    )


def _make_compression_result(success=True):
    from src.services.video_compression import CompressionResult
    return CompressionResult(
        success=success,
        input_path=Path("/app/data/clip.mp4"),
        output_path=Path("/app/data/clip_compressed.mp4"),
        input_size_mb=50.0,
        output_size_mb=15.0 if success else 50.0,
        compression_ratio=0.3 if success else 1.0,
        space_saved_mb=35.0 if success else 0.0,
        quality_score=88.0 if success else 0.0,
        duration_seconds=2.5 if success else 0.0,
        error_message=None if success else "ffmpeg error",
    )


def _make_cleanup_result():
    from src.services.data_retention import CleanupResult, DataType
    return CleanupResult(
        data_type=DataType.TEMP_FILES,
        items_scanned=20,
        items_deleted=15,
        items_archived=0,
        space_freed_mb=128.5,
        errors=[],
    )


def _make_policy(policy_id="pol_001"):
    from src.services.data_retention import DataType, RetentionAction, RetentionPolicy
    return RetentionPolicy(
        policy_id=policy_id,
        data_type=DataType.TEMP_FILES,
        retention_days=7,
        action=RetentionAction.DELETE,
        enabled=True,
        created_at="2026-01-01T00:00:00",
        exempt_user_ids=[],
        min_size_threshold_mb=None,
    )


# ===========================================================================
# 1. Sentiment Analysis API
# ===========================================================================

class TestSentimentAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.sentiment import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_analyze_transcript(self):
        client = self._get_client()
        result = _make_sentiment_result()
        with patch(
            "src.services.sentiment_analyzer.SentimentAnalyzer.analyze_transcript",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/sentiment/analyze", json={
                "transcript": "This is amazing content! You will absolutely love it.",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["analysis"]
        self.assertAlmostEqual(data["overall_sentiment"], 0.65)
        self.assertEqual(data["overall_category"], "positive")
        self.assertEqual(data["sentiment_trend"], "improving")
        self.assertAlmostEqual(data["viral_correlation"], 0.78)

    def test_analyze_with_segments(self):
        client = self._get_client()
        result = _make_sentiment_result()
        with patch(
            "src.services.sentiment_analyzer.SentimentAnalyzer.analyze_transcript",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/sentiment/analyze", json={
                "transcript": "Amazing content.",
                "segments": [[0.0, 5.0, "Amazing content."]],
            })
        self.assertEqual(resp.status_code, 200)

    def test_analyze_empty_transcript(self):
        client = self._get_client()
        resp = client.post("/sentiment/analyze", json={"transcript": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_analyze_invalid_segments(self):
        client = self._get_client()
        resp = client.post("/sentiment/analyze", json={
            "transcript": "Test",
            "segments": [[0.0]],   # missing end and text
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_trends(self):
        client = self._get_client()
        trends = {
            "period_days": 7, "analyses_count": 5,
            "average_sentiment": 0.4, "average_viral_correlation": 0.65,
            "category_distribution": {"positive": 3, "neutral": 2},
            "trend_direction": "positive",
        }
        with patch(
            "src.services.sentiment_analyzer.SentimentAnalyzer.get_historical_trends",
            return_value=trends,
        ):
            resp = client.get("/sentiment/trends?days=7")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["trends"]["analyses_count"], 5)

    def test_get_trends_invalid_days(self):
        client = self._get_client()
        resp = client.get("/sentiment/trends?days=0")
        self.assertEqual(resp.status_code, 400)
        resp = client.get("/sentiment/trends?days=400")
        self.assertEqual(resp.status_code, 400)

    def test_list_categories(self):
        client = self._get_client()
        resp = client.get("/sentiment/categories")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("positive", data["sentiment_categories"])
        self.assertIn("joy", data["emotion_types"])
        self.assertIn("excitement", data["emotion_types"])


# ===========================================================================
# 2. Social Media Integration API
# ===========================================================================

class TestSocialMediaAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.social_media import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_connect_account(self):
        client = self._get_client()
        account = _make_account()
        with patch(
            "src.services.social_integration.SocialMediaService.connect_account",
            new_callable=AsyncMock,
            return_value=account,
        ):
            resp = client.post("/social-media/accounts/connect", json={
                "user_id": "user_001",
                "platform": "tiktok",
                "auth_code": "oauth_code_xyz",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "connected")
        self.assertEqual(data["account"]["platform"], "tiktok")

    def test_connect_account_oauth_fail(self):
        client = self._get_client()
        with patch(
            "src.services.social_integration.SocialMediaService.connect_account",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/social-media/accounts/connect", json={
                "user_id": "user_001",
                "platform": "youtube",
                "auth_code": "bad_code",
            })
        self.assertEqual(resp.status_code, 400)

    def test_connect_account_invalid_platform(self):
        client = self._get_client()
        resp = client.post("/social-media/accounts/connect", json={
            "user_id": "user_001",
            "platform": "myspace",
            "auth_code": "code_123",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_accounts(self):
        client = self._get_client()
        accounts = [
            {"account_id": "acc_001", "platform": "tiktok", "account_name": "@alice",
             "is_active": True, "connected_at": None},
        ]
        with patch(
            "src.services.social_integration.SocialMediaService.get_user_accounts",
            return_value=accounts,
        ):
            resp = client.get("/social-media/accounts/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_disconnect_account(self):
        client = self._get_client()
        with patch(
            "src.services.social_integration.SocialMediaService.disconnect_account",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/social-media/accounts/acc_001/disconnect")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "disconnected")

    def test_disconnect_account_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.social_integration.SocialMediaService.disconnect_account",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/social-media/accounts/missing/disconnect")
        self.assertEqual(resp.status_code, 404)

    def test_publish_clip(self):
        client = self._get_client()
        result = _make_publish_result()
        with patch(
            "src.services.social_integration.SocialMediaService.publish_clip",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/social-media/publish", json={
                "account_id": "acc_001",
                "clip_path": "/app/data/clip.mp4",
                "caption": "Check out this amazing content!",
                "hashtags": ["viral", "trending"],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "published")
        self.assertEqual(data["result"]["post_id"], "post_abc")

    def test_publish_clip_empty_caption(self):
        client = self._get_client()
        resp = client.post("/social-media/publish", json={
            "account_id": "acc_001",
            "clip_path": "/app/data/clip.mp4",
            "caption": "",
            "hashtags": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_publish_clip_failure(self):
        client = self._get_client()
        result = _make_publish_result(success=False)
        with patch(
            "src.services.social_integration.SocialMediaService.publish_clip",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/social-media/publish", json={
                "account_id": "acc_001",
                "clip_path": "/app/data/clip.mp4",
                "caption": "Test",
                "hashtags": [],
            })
        self.assertEqual(resp.status_code, 400)

    def test_schedule_post(self):
        client = self._get_client()
        scheduled = {"schedule_id": "sched_001", "status": "scheduled",
                     "scheduled_time": "2026-02-01T12:00:00"}
        with patch(
            "src.services.social_integration.SocialMediaService.schedule_post",
            new_callable=AsyncMock,
            return_value=scheduled,
        ):
            resp = client.post("/social-media/schedule", json={
                "account_id": "acc_001",
                "clip_path": "/app/data/clip.mp4",
                "caption": "Scheduled post",
                "hashtags": ["content"],
                "schedule_time": "2026-02-01T12:00:00",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "scheduled")

    def test_get_history(self):
        client = self._get_client()
        history = [
            {"account_id": "acc_001", "platform": "tiktok",
             "result": True, "timestamp": "2026-01-01T00:00:00"},
        ]
        with patch(
            "src.services.social_integration.SocialMediaService.get_publishing_history",
            return_value=history,
        ):
            resp = client.get("/social-media/history/user_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_get_history_with_platform_filter(self):
        client = self._get_client()
        with patch(
            "src.services.social_integration.SocialMediaService.get_publishing_history",
            return_value=[],
        ):
            resp = client.get("/social-media/history/user_001?platform=youtube")
        self.assertEqual(resp.status_code, 200)

    def test_get_history_invalid_platform(self):
        client = self._get_client()
        resp = client.get("/social-media/history/user_001?platform=snapchat")
        self.assertEqual(resp.status_code, 400)

    def test_list_platforms(self):
        client = self._get_client()
        resp = client.get("/social-media/platforms")
        self.assertEqual(resp.status_code, 200)
        platforms = resp.json()["platforms"]
        self.assertIn("tiktok", platforms)
        self.assertIn("youtube", platforms)
        self.assertIn("instagram", platforms)


# ===========================================================================
# 3. Video Compression API
# ===========================================================================

class TestCompressionAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.compression import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_compress_clip(self):
        client = self._get_client()
        result = _make_compression_result()
        with patch(
            "src.services.video_compression.VideoCompressionService.compress_clip",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/compression/compress", json={
                "input_path": "/app/data/clip.mp4",
                "output_path": "/app/data/clip_out.mp4",
                "preset": "balanced",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["result"]
        self.assertTrue(data["success"])
        self.assertAlmostEqual(data["space_saved_mb"], 35.0)
        self.assertEqual(data["quality_score"], 88.0)

    def test_compress_invalid_preset(self):
        client = self._get_client()
        resp = client.post("/compression/compress", json={
            "input_path": "/app/data/clip.mp4",
            "output_path": "/app/data/out.mp4",
            "preset": "superduper",
        })
        self.assertEqual(resp.status_code, 400)

    def test_compress_all_presets(self):
        client = self._get_client()
        result = _make_compression_result()
        for preset in ["ultra", "high", "balanced", "compact", "aggressive"]:
            with patch(
                "src.services.video_compression.VideoCompressionService.compress_clip",
                new_callable=AsyncMock,
                return_value=result,
            ):
                resp = client.post("/compression/compress", json={
                    "input_path": "/app/data/clip.mp4",
                    "output_path": f"/app/data/out_{preset}.mp4",
                    "preset": preset,
                })
            self.assertEqual(resp.status_code, 200, f"Failed for preset={preset}")

    def test_recommend_preset(self):
        client = self._get_client()
        from src.services.video_compression import CompressionPreset
        with patch(
            "src.services.video_compression.VideoCompressionService.recommend_preset",
            return_value=CompressionPreset.COMPACT,
        ):
            resp = client.post("/compression/recommend", json={
                "video_path": "/app/data/clip.mp4",
                "target_size_mb": 20.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["recommended_preset"], "compact")
        self.assertIn("profile", resp.json())

    def test_compression_stats(self):
        client = self._get_client()
        stats = {"total_compressed": 10, "total_space_saved_mb": 500.0,
                 "average_compression_ratio": 0.35}
        with patch(
            "src.services.video_compression.VideoCompressionService.get_compression_stats",
            return_value=stats,
        ):
            resp = client.get("/compression/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["total_compressed"], 10)

    def test_list_presets(self):
        client = self._get_client()
        resp = client.get("/compression/presets")
        self.assertEqual(resp.status_code, 200)
        presets = [p["preset"] for p in resp.json()["presets"]]
        self.assertIn("ultra", presets)
        self.assertIn("aggressive", presets)

    def test_list_codecs(self):
        client = self._get_client()
        resp = client.get("/compression/codecs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("libx264", resp.json()["codecs"])


# ===========================================================================
# 4. Data Retention API
# ===========================================================================

class TestRetentionAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.retention import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_policies(self):
        client = self._get_client()
        policies = [
            {"policy_id": "default_temp", "data_type": "temp_files",
             "retention_days": 7, "action": "delete", "enabled": True,
             "created_at": "2026-01-01T00:00:00", "exempt_count": 0},
        ]
        with patch(
            "src.services.data_retention.DataRetentionService.list_policies",
            return_value=policies,
        ):
            resp = client.get("/retention/policies")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_get_policy(self):
        client = self._get_client()
        policy = _make_policy()
        with patch(
            "src.services.data_retention.DataRetentionService.get_policy",
            return_value=policy,
        ):
            resp = client.get("/retention/policies/pol_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data_type"], "temp_files")

    def test_get_policy_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.data_retention.DataRetentionService.get_policy",
            return_value=None,
        ):
            resp = client.get("/retention/policies/missing")
        self.assertEqual(resp.status_code, 404)

    def test_create_policy(self):
        client = self._get_client()
        policy = _make_policy("pol_new")
        with patch(
            "src.services.data_retention.DataRetentionService.create_policy",
            return_value=policy,
        ):
            resp = client.post("/retention/policies", json={
                "data_type": "temp_files",
                "retention_days": 7,
                "action": "delete",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "created")

    def test_create_policy_invalid_type(self):
        client = self._get_client()
        resp = client.post("/retention/policies", json={
            "data_type": "cookies",
            "retention_days": 7,
            "action": "delete",
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_policy_invalid_action(self):
        client = self._get_client()
        resp = client.post("/retention/policies", json={
            "data_type": "clips",
            "retention_days": 30,
            "action": "shred",
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_policy_bad_days(self):
        client = self._get_client()
        resp = client.post("/retention/policies", json={
            "data_type": "clips",
            "retention_days": 0,
            "action": "delete",
        })
        self.assertEqual(resp.status_code, 400)

    def test_update_policy(self):
        client = self._get_client()
        with patch(
            "src.services.data_retention.DataRetentionService.update_policy",
            return_value=True,
        ):
            resp = client.patch("/retention/policies/pol_001", json={
                "retention_days": 14,
                "enabled": False,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "updated")

    def test_update_policy_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.data_retention.DataRetentionService.update_policy",
            return_value=False,
        ):
            resp = client.patch("/retention/policies/missing", json={"enabled": True})
        self.assertEqual(resp.status_code, 404)

    def test_delete_policy(self):
        client = self._get_client()
        with patch(
            "src.services.data_retention.DataRetentionService.delete_policy",
            return_value=True,
        ):
            resp = client.delete("/retention/policies/pol_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_apply_policy(self):
        client = self._get_client()
        result = _make_cleanup_result()
        with patch(
            "src.services.data_retention.DataRetentionService.apply_policy",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/retention/policies/pol_001/apply", json={"dry_run": False})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "applied")
        self.assertEqual(data["result"]["items_deleted"], 15)

    def test_apply_policy_dry_run(self):
        client = self._get_client()
        result = _make_cleanup_result()
        with patch(
            "src.services.data_retention.DataRetentionService.apply_policy",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/retention/policies/pol_001/apply", json={"dry_run": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "dry_run")

    def test_run_all_policies(self):
        client = self._get_client()
        result = _make_cleanup_result()
        with patch(
            "src.services.data_retention.DataRetentionService.run_all_policies",
            new_callable=AsyncMock,
            return_value={"pol_001": result},
        ):
            resp = client.post("/retention/run-all", json={"dry_run": False})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["policies_applied"], 1)
        self.assertEqual(data["total_items_deleted"], 15)

    def test_storage_summary(self):
        client = self._get_client()
        storage = {
            "temp_files": {"file_count": 50, "size_mb": 200.0, "size_gb": 0.2},
            "clips": {"file_count": 120, "size_mb": 5000.0, "size_gb": 4.88},
        }
        with patch(
            "src.services.data_retention.DataRetentionService.get_storage_summary",
            return_value=storage,
        ):
            resp = client.get("/retention/storage")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("temp_files", resp.json()["storage"])

    def test_cleanup_history(self):
        client = self._get_client()
        history = [
            {"timestamp": "2026-01-01T00:00:00", "policy_id": "pol_001",
             "dry_run": False, "result": {"items_deleted": 10}},
        ]
        with patch(
            "src.services.data_retention.DataRetentionService.get_cleanup_history",
            return_value=history,
        ):
            resp = client.get("/retention/history?days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_cleanup_history_invalid_days(self):
        client = self._get_client()
        resp = client.get("/retention/history?days=0")
        self.assertEqual(resp.status_code, 400)

    def test_list_data_types(self):
        client = self._get_client()
        resp = client.get("/retention/data-types")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("temp_files", data["data_types"])
        self.assertIn("delete", data["retention_actions"])
        self.assertIn("archive", data["retention_actions"])


if __name__ == "__main__":
    unittest.main()
