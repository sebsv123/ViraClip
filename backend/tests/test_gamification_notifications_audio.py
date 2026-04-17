"""
Tests for:
  1. Gamification API (/gamification/*)
  2. Smart Notifications API (/notifications/*)
  3. Audio Recommendation API (/audio/*)
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

def _make_achievement(achievement_id="first_clip", name="Clip Pioneer", rarity="common"):
    from src.services.gamification_service import Achievement, AchievementType
    return Achievement(
        achievement_id=achievement_id,
        type=AchievementType.FIRST_CLIP,
        name=name,
        description="Create your first viral clip",
        icon="🎬",
        points=100,
        criteria={"clips_created": 1},
        rarity=rarity,
    )


def _make_notification(notif_id="notif_001", user_id="anon"):
    from src.services.smart_notifications import (
        Notification, NotificationChannel, NotificationPriority, NotificationType,
    )
    return Notification(
        notification_id=notif_id,
        user_id=user_id,
        type=NotificationType.CLIP_READY,
        priority=NotificationPriority.NORMAL,
        title="Your clip is ready!",
        message="Clip #42 has finished processing.",
        channels=[NotificationChannel.IN_APP],
        data={"clip_id": "clip_42"},
        created_at=datetime.now().isoformat(),
        scheduled_for=None,
        delivered_at=datetime.now().isoformat(),
        read_at=None,
        engagement_score=0.82,
    )


def _make_audio_rec(rec_id="rec_001"):
    from src.services.audio_recommendation import AudioRecommendation, AudioType, MusicGenre
    return AudioRecommendation(
        recommendation_id=rec_id,
        audio_type=AudioType.BACKGROUND_MUSIC,
        genre=MusicGenre.UPBEAT_POP,
        title="Viral Energy",
        artist="AudioFlow",
        duration=30.0,
        bpm=128,
        mood="energetic",
        energy_level=0.9,
        match_score=0.87,
        file_url="/api/audio/library/track_001",
        preview_url="/api/audio/preview/track_001",
        license_type="premium",
        credits_cost=10,
        tags=["viral", "upbeat"],
    )


def _make_video_profile():
    from src.services.audio_recommendation import MusicGenre, VideoAudioProfile
    return VideoAudioProfile(
        duration=30.0,
        has_voiceover=False,
        dominant_mood="energetic",
        energy_curve=[0.5, 0.7, 0.6, 0.8],
        scene_changes=[5.0, 10.0, 15.0],
        recommended_bpm_range=(120, 150),
        suitable_genres=[MusicGenre.UPBEAT_POP, MusicGenre.ELECTRONIC],
    )


# ===========================================================================
# 1. Gamification API
# ===========================================================================

class TestGamificationAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.gamification import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_profile(self):
        client = self._get_client()
        mock_profile = {
            "user_id": "anon",
            "total_points": 250,
            "current_level": 2,
            "rank": "bronze",
            "achievements_earned": 1,
            "achievements_total": 10,
            "badges": ["🔥"],
            "streak_days": 3,
            "unlocked_features": [],
            "level_progress": 0.5,
            "next_level_points": 1500,
        }
        with patch(
            "src.services.gamification_service.GamificationService.get_profile",
            return_value=mock_profile,
        ):
            resp = client.get("/gamification/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["profile"]["total_points"], 250)
        self.assertEqual(data["profile"]["rank"], "bronze")

    def test_get_profile_by_id(self):
        client = self._get_client()
        mock_profile = {"user_id": "user_xyz", "total_points": 1200, "current_level": 3, "rank": "silver"}
        with patch(
            "src.services.gamification_service.GamificationService.get_profile",
            return_value=mock_profile,
        ):
            resp = client.get("/gamification/profile/user_xyz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["profile"]["rank"], "silver")

    def test_record_activity_no_new_achievements(self):
        client = self._get_client()
        with patch(
            "src.services.gamification_service.GamificationService.record_activity",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.post("/gamification/activity", json={
                "activity_type": "video_processed",
                "metadata": {},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "recorded")
        self.assertEqual(data["achievements_unlocked"], 0)

    def test_record_activity_earns_achievement(self):
        client = self._get_client()
        ach = _make_achievement()
        with patch(
            "src.services.gamification_service.GamificationService.record_activity",
            new_callable=AsyncMock,
            return_value=[ach],
        ):
            resp = client.post("/gamification/activity", json={
                "activity_type": "clip_created",
                "metadata": {"virality_score": 90.0, "niche": "tech"},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["achievements_unlocked"], 1)
        self.assertEqual(data["new_achievements"][0]["id"], "first_clip")

    def test_get_achievements(self):
        client = self._get_client()
        mock_achievements = [
            {"id": "first_clip", "name": "Clip Pioneer", "earned": True, "points": 100, "rarity": "common"},
            {"id": "viral_creator", "name": "Viral Creator", "earned": False, "points": 500, "rarity": "rare"},
        ]
        with patch(
            "src.services.gamification_service.GamificationService.get_achievements",
            return_value=mock_achievements,
        ):
            resp = client.get("/gamification/achievements")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["earned_count"], 1)

    def test_get_leaderboard(self):
        client = self._get_client()
        mock_board = [
            {"rank": 1, "user_id": "user_a", "total_points": 5000, "level": 5, "rank_tier": "gold"},
            {"rank": 2, "user_id": "user_b", "total_points": 3200, "level": 4, "rank_tier": "silver"},
        ]
        with patch(
            "src.services.gamification_service.GamificationService.get_leaderboard",
            return_value=mock_board,
        ):
            resp = client.get("/gamification/leaderboard?limit=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["leaderboard"][0]["user_id"], "user_a")


# ===========================================================================
# 2. Smart Notifications API
# ===========================================================================

class TestNotificationsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.notifications import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_send_notification(self):
        client = self._get_client()
        mock_notif = _make_notification()
        with patch(
            "src.services.smart_notifications.SmartNotificationService.send_notification",
            new_callable=AsyncMock,
            return_value=mock_notif,
        ):
            resp = client.post("/notifications/send", json={
                "user_id": "anon",
                "notification_type": "clip_ready",
                "priority": "normal",
                "title": "Your clip is ready!",
                "message": "Clip #42 has finished.",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "sent")
        self.assertEqual(data["notification_id"], "notif_001")

    def test_send_notification_invalid_type(self):
        client = self._get_client()
        resp = client.post("/notifications/send", json={
            "user_id": "anon",
            "notification_type": "alien_attack",
            "priority": "normal",
            "title": "Oops",
            "message": "Invalid type",
        })
        self.assertEqual(resp.status_code, 400)

    def test_send_notification_invalid_priority(self):
        client = self._get_client()
        resp = client.post("/notifications/send", json={
            "user_id": "anon",
            "notification_type": "clip_ready",
            "priority": "ultra",
            "title": "Test",
            "message": "Test",
        })
        self.assertEqual(resp.status_code, 400)

    def test_batch_send(self):
        client = self._get_client()
        notifs = [_make_notification(f"n_{i}", f"u_{i}") for i in range(3)]
        with patch(
            "src.services.smart_notifications.SmartNotificationService.batch_send",
            new_callable=AsyncMock,
            return_value=notifs,
        ):
            resp = client.post("/notifications/send/batch", json={
                "user_ids": ["u_0", "u_1", "u_2"],
                "notification_type": "viral_milestone",
                "priority": "high",
                "title": "🔥 Milestone reached!",
                "message": "Your clip hit 1M views",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 3)

    def test_batch_send_empty_users(self):
        client = self._get_client()
        resp = client.post("/notifications/send/batch", json={
            "user_ids": [],
            "notification_type": "marketing",
            "priority": "low",
            "title": "Hi",
            "message": "Empty",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_notifications(self):
        client = self._get_client()
        mock_items = [
            {
                "notification_id": "n1",
                "type": "clip_ready",
                "priority": "normal",
                "title": "Clip ready",
                "message": "Done",
                "channels": ["in_app"],
                "created_at": datetime.now().isoformat(),
                "delivered_at": None,
                "read_at": None,
                "engagement_score": 0.8,
                "data": {},
            }
        ]
        with patch(
            "src.services.smart_notifications.SmartNotificationService.get_user_notifications",
            return_value=mock_items,
        ):
            resp = client.get("/notifications")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["unread_count"], 1)

    def test_mark_as_read_success(self):
        client = self._get_client()
        with patch(
            "src.services.smart_notifications.SmartNotificationService.mark_as_read",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/notifications/notif_001/read")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "read")

    def test_mark_as_read_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.smart_notifications.SmartNotificationService.mark_as_read",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/notifications/missing/read")
        self.assertEqual(resp.status_code, 404)

    def test_notification_stats(self):
        client = self._get_client()
        mock_stats = {
            "total_sent": 10,
            "total_delivered": 9,
            "total_read": 7,
            "delivery_rate": 0.9,
            "read_rate": 0.78,
            "avg_engagement_score": 0.74,
            "by_type": {"clip_ready": {"sent": 5, "read": 4}},
        }
        with patch(
            "src.services.smart_notifications.SmartNotificationService.get_notification_stats",
            return_value=mock_stats,
        ):
            resp = client.get("/notifications/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["delivery_rate"], 0.9)

    def test_set_preferences(self):
        client = self._get_client()
        from src.services.smart_notifications import (
            NotificationChannel, NotificationPriority, UserPreferences,
        )
        mock_prefs = UserPreferences(
            user_id="anon",
            channels=[NotificationChannel.EMAIL, NotificationChannel.IN_APP],
            quiet_hours_start=23,
            quiet_hours_end=7,
            timezone="America/New_York",
            max_per_hour=5,
            priority_threshold=NotificationPriority.NORMAL,
            ml_optimized=True,
        )
        with patch(
            "src.services.smart_notifications.SmartNotificationService.set_user_preferences",
            new_callable=AsyncMock,
            return_value=mock_prefs,
        ):
            resp = client.put("/notifications/preferences", json={
                "channels": ["email", "in_app"],
                "quiet_hours_start": 23,
                "quiet_hours_end": 7,
                "timezone": "America/New_York",
                "max_per_hour": 5,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "updated")
        self.assertIn("email", data["channels"])

    def test_set_preferences_invalid_channel(self):
        client = self._get_client()
        resp = client.put("/notifications/preferences", json={
            "channels": ["carrier_pigeon"],
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_channels(self):
        client = self._get_client()
        resp = client.get("/notifications/channels")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("email", data["channels"])
        self.assertIn("in_app", data["channels"])
        self.assertIn("clip_ready", data["types"])
        self.assertIn("normal", data["priorities"])


# ===========================================================================
# 3. Audio Recommendation API
# ===========================================================================

class TestAudioAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.audio import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_recommend_music(self):
        client = self._get_client()
        profile = _make_video_profile()
        rec = _make_audio_rec()
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.analyze_video_for_audio",
            new_callable=AsyncMock,
            return_value=profile,
        ), patch(
            "src.services.audio_recommendation.AudioRecommendationService.recommend_music",
            new_callable=AsyncMock,
            return_value=[rec],
        ):
            resp = client.post("/audio/recommend/music", json={
                "clip_path": "/app/storage/clips/clip_001.mp4",
                "count": 3,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["recommendations"][0]["title"], "Viral Energy")
        self.assertEqual(data["clip_profile"]["dominant_mood"], "energetic")

    def test_recommend_sfx(self):
        client = self._get_client()
        from src.services.audio_recommendation import AudioRecommendation, AudioType, MusicGenre
        sfx_rec = AudioRecommendation(
            recommendation_id="sfx_001",
            audio_type=AudioType.TRANSITION_SFX,
            genre=MusicGenre.TRENDING,
            title="Whoosh",
            artist="SFX Library",
            duration=1.0,
            bpm=0,
            mood="transition",
            energy_level=0.7,
            match_score=0.9,
            file_url="/api/sfx/library/sfx_001",
            preview_url="/api/sfx/preview/sfx_001",
            license_type="free",
            credits_cost=0,
            tags=["transition"],
        )
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.recommend_sfx",
            new_callable=AsyncMock,
            return_value=[sfx_rec],
        ):
            resp = client.post("/audio/recommend/sfx", json={
                "clip_path": "/app/storage/clips/clip_001.mp4",
                "scene_change_timestamps": [5.0, 10.0, 15.0],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["recommendations"][0]["title"], "Whoosh")

    def test_beat_match(self):
        client = self._get_client()
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService._get_video_duration",
            new_callable=AsyncMock,
            return_value=30.0,
        ), patch(
            "src.services.audio_recommendation.AudioRecommendationService.generate_beat_matched_cuts",
            new_callable=AsyncMock,
            return_value=[0.0, 1.875, 3.75, 5.625, 7.5],
        ):
            resp = client.post("/audio/beat-match", json={
                "clip_path": "/app/storage/clips/clip_001.mp4",
                "music_bpm": 128,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["music_bpm"], 128)
        self.assertGreater(data["cut_count"], 0)
        self.assertAlmostEqual(data["beat_interval_seconds"], 60 / 128, places=2)

    def test_audio_profile(self):
        client = self._get_client()
        profile = _make_video_profile()
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.analyze_video_for_audio",
            new_callable=AsyncMock,
            return_value=profile,
        ):
            resp = client.post("/audio/profile", json={
                "clip_path": "/app/storage/clips/clip_001.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["dominant_mood"], "energetic")
        self.assertEqual(data["recommended_bpm_range"], [120, 150])
        self.assertIn("upbeat_pop", data["suitable_genres"])

    def test_trending_audio(self):
        client = self._get_client()
        recs = [_make_audio_rec(f"rec_{i}") for i in range(2)]
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.get_trending_audio",
            return_value=recs,
        ):
            resp = client.get("/audio/trending?platform=tiktok")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["platform"], "tiktok")
        self.assertEqual(data["count"], 2)

    def test_audio_stats(self):
        client = self._get_client()
        mock_stats = {
            "music_tracks": 5,
            "sfx_tracks": 5,
            "total_recommendations_made": 23,
            "genres_available": 6,
        }
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.get_audio_stats",
            return_value=mock_stats,
        ):
            resp = client.get("/audio/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["music_tracks"], 5)

    def test_list_genres(self):
        client = self._get_client()
        resp = client.get("/audio/genres")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("upbeat_pop", data["genres"])
        self.assertIn("background_music", data["audio_types"])


if __name__ == "__main__":
    unittest.main()
