"""
Tests for:
  1. Recommendation Engine API (/recommendations/*)
  2. Voice Synthesis API (/voice/*)
  3. Platform Presets API (/platform-presets/*)
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rec(rec_id="r1", rec_type="niche"):
    from src.services.recommendation_engine import ContentRecommendation
    return ContentRecommendation(
        recommendation_id=rec_id,
        type=rec_type,
        title="Try Gaming Content",
        description="Trending hooks: Epic clutch moment",
        confidence=0.75,
        action="explore_niche",
        metadata={"niche": "gaming", "hooks": ["Epic clutch moment"]},
    )


def _make_profile(user_id="user_001"):
    from src.services.recommendation_engine import UserProfile
    return UserProfile(
        user_id=user_id,
        preferred_niches=["entertaining"],
        preferred_duration=60,
        favorite_effects=[],
        top_platforms=["tiktok"],
        avg_virality_threshold=70.0,
        content_style="entertaining",
        language_preference="en",
    )


def _make_synthesis_job(job_id="job_001", status="completed"):
    from src.services.voice_synthesis import SynthesisJob, VoiceStyle
    from pathlib import Path
    return SynthesisJob(
        job_id=job_id,
        voice_id="default_alex",
        text="Hello world",
        style=VoiceStyle.NATURAL,
        speed=1.0,
        pitch=1.0,
        emotion="neutral",
        status=status,
        output_path=Path("/app/temp/voice/job_001.wav"),
        duration=2.5,
        created_at="2026-01-01T00:00:00",
        completed_at="2026-01-01T00:00:02",
    )


def _make_voice_profile(voice_id="default_alex", cloned=False):
    from src.services.voice_synthesis import VoiceProfile
    return VoiceProfile(
        voice_id=voice_id,
        name="Alex",
        description="Versatile neutral voice",
        sample_audio_path=None,
        age=30,
        gender="neutral",
        accent="american",
        language="en",
        cloned=cloned,
        created_at="2026-01-01T00:00:00",
        usage_count=5,
    )


# ===========================================================================
# 1. Recommendation Engine API
# ===========================================================================

class TestRecommendationsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.recommendations import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_profile(self):
        client = self._get_client()
        profile = _make_profile()
        with patch(
            "src.services.recommendation_engine.RecommendationEngine.create_user_profile",
            return_value=profile,
        ):
            resp = client.post("/recommendations/profile", json={
                "user_id": "user_001",
                "initial_data": {"niches": ["gaming"], "style": "entertaining"},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["profile"]["user_id"], "user_001")

    def test_create_profile_no_initial_data(self):
        client = self._get_client()
        profile = _make_profile()
        with patch(
            "src.services.recommendation_engine.RecommendationEngine.create_user_profile",
            return_value=profile,
        ):
            resp = client.post("/recommendations/profile", json={"user_id": "user_002"})
        self.assertEqual(resp.status_code, 200)

    def test_update_behavior(self):
        client = self._get_client()
        with patch(
            "src.services.recommendation_engine.RecommendationEngine.update_profile_from_behavior",
            return_value=None,
        ):
            resp = client.post("/recommendations/behavior", json={
                "user_id": "user_001",
                "action": "clip_exported",
                "metadata": {"niche": "gaming", "duration": 45},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "clip_exported")

    def test_get_recommendations(self):
        client = self._get_client()
        recs = [_make_rec(f"r{i}") for i in range(3)]
        with patch(
            "src.services.recommendation_engine.RecommendationEngine.get_recommendations",
            return_value=recs,
        ):
            resp = client.get("/recommendations/user/user_001?current_niche=gaming")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["recommendations"][0]["type"], "niche")

    def test_get_recommendations_no_context(self):
        client = self._get_client()
        with patch(
            "src.services.recommendation_engine.RecommendationEngine.get_recommendations",
            return_value=[_make_rec()],
        ):
            resp = client.get("/recommendations/user/user_001")
        self.assertEqual(resp.status_code, 200)

    def test_virality_tips(self):
        client = self._get_client()
        tips = [
            {"priority": "high", "category": "hook", "tip": "Add stronger hook", "action": "Add overlay"},
            {"priority": "medium", "category": "pacing", "tip": "Remove pauses", "action": "Auto-edit"},
        ]
        with patch(
            "src.services.recommendation_engine.RecommendationEngine.get_virality_optimization_tips",
            return_value=tips,
        ):
            resp = client.post("/recommendations/virality-tips", json={
                "clip_data": {"virality_score": 55, "niche": "gaming", "duration": 45, "has_hook": False},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["tips"][0]["category"], "hook")

    def test_virality_tips_empty_clip_data(self):
        client = self._get_client()
        resp = client.post("/recommendations/virality-tips", json={"clip_data": {}})
        self.assertEqual(resp.status_code, 400)

    def test_predict_performance(self):
        client = self._get_client()
        prediction = {
            "predicted_views_range": (5600, 10400),
            "confidence": 0.8,
            "virality_tier": "high",
            "optimization_potential": 20,
            "estimated_engagement_rate": 16.0,
        }
        with patch(
            "src.services.recommendation_engine.RecommendationEngine.predict_performance",
            return_value=prediction,
        ):
            resp = client.post("/recommendations/predict-performance", json={
                "clip_features": {"virality_score": 80, "niche": "gaming", "has_hook": True, "duration": 45},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["prediction"]["virality_tier"], "high")

    def test_predict_empty_features(self):
        client = self._get_client()
        resp = client.post("/recommendations/predict-performance", json={"clip_features": {}})
        self.assertEqual(resp.status_code, 400)


# ===========================================================================
# 2. Voice Synthesis API
# ===========================================================================

class TestVoiceAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.voice_synthesis import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_voices(self):
        client = self._get_client()
        profiles = [_make_voice_profile(f"v{i}") for i in range(4)]
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.get_voice_profiles",
            return_value=profiles,
        ):
            resp = client.get("/voice/voices")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 4)

    def test_list_voices_cloned_only(self):
        client = self._get_client()
        cloned = [_make_voice_profile("cloned_001", cloned=True)]
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.get_voice_profiles",
            return_value=cloned,
        ):
            resp = client.get("/voice/voices?cloned_only=true")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["voices"][0]["cloned"])

    def test_synthesize_success(self):
        client = self._get_client()
        job = _make_synthesis_job()
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.synthesize_speech",
            new_callable=AsyncMock,
            return_value=job,
        ):
            resp = client.post("/voice/synthesize", json={
                "voice_id": "default_alex",
                "text": "Hello world, this is a test.",
                "style": "natural",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["job"]["status"], "completed")

    def test_synthesize_empty_text(self):
        client = self._get_client()
        resp = client.post("/voice/synthesize", json={
            "voice_id": "default_alex",
            "text": "",
        })
        self.assertEqual(resp.status_code, 400)

    def test_synthesize_invalid_speed(self):
        client = self._get_client()
        resp = client.post("/voice/synthesize", json={
            "voice_id": "default_alex",
            "text": "Hello",
            "speed": 3.0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_synthesize_invalid_pitch(self):
        client = self._get_client()
        resp = client.post("/voice/synthesize", json={
            "voice_id": "default_alex",
            "text": "Hello",
            "pitch": 0.5,
        })
        self.assertEqual(resp.status_code, 400)

    def test_synthesize_unknown_voice(self):
        client = self._get_client()
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.synthesize_speech",
            new_callable=AsyncMock,
            side_effect=ValueError("Voice not_found not found"),
        ):
            resp = client.post("/voice/synthesize", json={
                "voice_id": "not_found",
                "text": "Hello",
            })
        self.assertEqual(resp.status_code, 404)

    def test_synthesize_invalid_style(self):
        client = self._get_client()
        resp = client.post("/voice/synthesize", json={
            "voice_id": "default_alex",
            "text": "Hello",
            "style": "alien_voice",
        })
        self.assertEqual(resp.status_code, 400)

    def test_generate_narration(self):
        client = self._get_client()
        jobs = [_make_synthesis_job(f"job_00{i}") for i in range(2)]
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.generate_narration",
            new_callable=AsyncMock,
            return_value=jobs,
        ):
            resp = client.post("/voice/narration", json={
                "video_script": "Welcome to our tutorial. Today we will learn about FastAPI.",
                "voice_id": "default_alex",
                "style": "professional",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["job_count"], 2)

    def test_generate_narration_empty_script(self):
        client = self._get_client()
        resp = client.post("/voice/narration", json={
            "video_script": "   ",
            "voice_id": "default_alex",
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_job_status(self):
        client = self._get_client()
        job = _make_synthesis_job()
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.get_job_status",
            return_value=job,
        ):
            resp = client.get("/voice/jobs/job_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["job"]["job_id"], "job_001")

    def test_get_job_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.get_job_status",
            return_value=None,
        ):
            resp = client.get("/voice/jobs/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_delete_voice_cloned(self):
        client = self._get_client()
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.delete_voice",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/voice/voices/cloned_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_delete_voice_default_forbidden(self):
        client = self._get_client()
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.delete_voice",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot delete default voices"),
        ):
            resp = client.delete("/voice/voices/default_alex")
        self.assertEqual(resp.status_code, 403)

    def test_get_stats(self):
        client = self._get_client()
        stats = {
            "total_voices": 4, "cloned_voices": 0, "default_voices": 4,
            "total_synthesis_jobs": 10, "completed_jobs": 9, "failed_jobs": 1,
            "success_rate": 0.9, "total_generated_audio_seconds": 120.5,
        }
        with patch(
            "src.services.voice_synthesis.VoiceSynthesisService.get_stats",
            return_value=stats,
        ):
            resp = client.get("/voice/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(resp.json()["stats"]["success_rate"], 0.9)

    def test_list_styles(self):
        client = self._get_client()
        resp = client.get("/voice/styles")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("natural", resp.json()["styles"])
        self.assertIn("professional", resp.json()["styles"])

    def test_list_providers(self):
        client = self._get_client()
        resp = client.get("/voice/providers")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("elevenlabs", resp.json()["providers"])


# ===========================================================================
# 3. Platform Presets API
# ===========================================================================

class TestPlatformPresetsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.platform_presets import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_presets(self):
        client = self._get_client()
        resp = client.get("/platform-presets")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 7)
        platforms = [p["platform"] for p in data["presets"]]
        self.assertIn("tiktok", platforms)
        self.assertIn("linkedin", platforms)

    def test_get_preset_tiktok(self):
        client = self._get_client()
        resp = client.get("/platform-presets/tiktok")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["preset"]
        self.assertEqual(data["platform"], "tiktok")
        self.assertEqual(data["specs"]["aspect_ratio"], "9:16")
        self.assertIn("engagement_tips", data)

    def test_get_preset_youtube_shorts(self):
        client = self._get_client()
        resp = client.get("/platform-presets/youtube_shorts")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["preset"]["platform"], "youtube_shorts")

    def test_get_preset_linkedin(self):
        client = self._get_client()
        resp = client.get("/platform-presets/linkedin")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["preset"]
        self.assertEqual(data["specs"]["aspect_ratio"], "16:9")

    def test_get_preset_invalid(self):
        client = self._get_client()
        resp = client.get("/platform-presets/myspace")
        self.assertEqual(resp.status_code, 400)

    def test_get_ffmpeg_settings(self):
        client = self._get_client()
        resp = client.get("/platform-presets/tiktok/ffmpeg")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["platform"], "tiktok")
        ffmpeg = data["ffmpeg"]
        self.assertEqual(ffmpeg["video_codec"], "libx264")
        self.assertIn("extra_args", ffmpeg)

    def test_get_ffmpeg_settings_invalid(self):
        client = self._get_client()
        resp = client.get("/platform-presets/fax/ffmpeg")
        self.assertEqual(resp.status_code, 400)

    def test_validate_video(self):
        client = self._get_client()
        validation = {
            "valid": True,
            "platform": "tiktok",
            "issues": [],
            "recommendations": [],
            "current_specs": {"duration": 30.0, "size_mb": 15.0, "resolution": "1080x1920"},
        }
        with patch(
            "src.services.platform_presets.PlatformExportPresets.validate_video_for_platform",
            return_value=validation,
        ):
            resp = client.post("/platform-presets/validate", json={
                "video_path": "/app/clip.mp4",
                "platform": "tiktok",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["validation"]["valid"])

    def test_validate_video_with_issues(self):
        client = self._get_client()
        validation = {
            "valid": False,
            "platform": "youtube_shorts",
            "issues": ["Duration 120.0s exceeds limit of 60s"],
            "recommendations": ["Trim to 60 seconds"],
            "current_specs": {"duration": 120.0, "size_mb": 50.0, "resolution": "1080x1920"},
        }
        with patch(
            "src.services.platform_presets.PlatformExportPresets.validate_video_for_platform",
            return_value=validation,
        ):
            resp = client.post("/platform-presets/validate", json={
                "video_path": "/app/long_clip.mp4",
                "platform": "youtube_shorts",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["validation"]["valid"])
        self.assertEqual(len(resp.json()["validation"]["issues"]), 1)

    def test_validate_invalid_platform(self):
        client = self._get_client()
        resp = client.post("/platform-presets/validate", json={
            "video_path": "/app/clip.mp4",
            "platform": "telegraph",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_platforms(self):
        client = self._get_client()
        resp = client.get("/platform-presets/platforms/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tiktok", data["platforms"])
        self.assertIn("linkedin", data["platforms"])
        self.assertEqual(len(data["platforms"]), 7)


if __name__ == "__main__":
    unittest.main()
