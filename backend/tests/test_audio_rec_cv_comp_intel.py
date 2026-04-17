"""
Tests for:
  1. Audio Recommendation API (/audio-rec/*)
  2. Computer Vision API (/computer-vision/*)
  3. Competitor Intelligence API (/competitor-intel/*)
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audio_rec(rec_id="rec_001", audio_type="background_music", genre="upbeat_pop"):
    from src.services.audio_recommendation import (
        AudioRecommendation,
        AudioType,
        MusicGenre,
    )
    return AudioRecommendation(
        recommendation_id=rec_id,
        audio_type=AudioType(audio_type),
        genre=MusicGenre(genre),
        title="Viral Energy",
        artist="AudioFlow",
        duration=30.0,
        bpm=128,
        mood="energetic",
        energy_level=0.9,
        match_score=0.82,
        file_url="/api/audio/library/track_001",
        preview_url="/api/audio/preview/track_001",
        license_type="premium",
        credits_cost=10,
        tags=["viral", "upbeat"],
    )


def _make_audio_profile():
    from src.services.audio_recommendation import MusicGenre, VideoAudioProfile
    return VideoAudioProfile(
        duration=30.0,
        has_voiceover=False,
        dominant_mood="energetic",
        energy_curve=[0.5, 0.7, 0.8],
        scene_changes=[5.0, 15.0],
        recommended_bpm_range=(120, 150),
        suitable_genres=[MusicGenre.UPBEAT_POP, MusicGenre.ELECTRONIC],
    )


def _make_visual_analysis(ts=0.0):
    from src.services.computer_vision import VisualAnalysis
    return VisualAnalysis(
        timestamp=ts,
        faces=[{"x": 100, "y": 100, "width": 200, "height": 250, "confidence": 0.95}],
        text_regions=[],
        dominant_colors=[(255, 100, 100), (100, 255, 100)],
        brightness=0.7,
        contrast=0.6,
        sharpness=0.8,
        motion_score=0.5,
        engagement_prediction=0.85,
    )


def _make_competitor():
    from src.services.competitor_intelligence import Competitor
    return Competitor(
        competitor_id="comp_abc123",
        name="TrendMaker",
        platforms={"youtube": "@trendmaker", "tiktok": "@trendmaker"},
        niche="fitness",
        follower_count={"youtube": 150000, "tiktok": 200000},
        added_at="2026-01-01T00:00:00",
        last_sync="2026-01-02T00:00:00",
        is_active=True,
    )


# ===========================================================================
# 1. Audio Recommendation API
# ===========================================================================

class TestAudioRecAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.audio_rec import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_analyze_video(self):
        client = self._get_client()
        profile = _make_audio_profile()
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.analyze_video_for_audio",
            new_callable=AsyncMock,
            return_value=profile,
        ):
            resp = client.post("/audio-rec/analyze", json={"video_path": "/app/v.mp4"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "analyzed")
        self.assertEqual(data["profile"]["dominant_mood"], "energetic")
        self.assertIn("upbeat_pop", data["profile"]["suitable_genres"])

    def test_analyze_with_transcript(self):
        client = self._get_client()
        profile = _make_audio_profile()
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.analyze_video_for_audio",
            new_callable=AsyncMock,
            return_value=profile,
        ):
            resp = client.post("/audio-rec/analyze", json={
                "video_path": "/app/v.mp4",
                "transcript": "This is an epic gaming moment",
            })
        self.assertEqual(resp.status_code, 200)

    def test_recommend_music(self):
        client = self._get_client()
        profile = _make_audio_profile()
        recs = [_make_audio_rec(f"rec_00{i}") for i in range(3)]
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.analyze_video_for_audio",
            new_callable=AsyncMock,
            return_value=profile,
        ), patch(
            "src.services.audio_recommendation.AudioRecommendationService.recommend_music",
            new_callable=AsyncMock,
            return_value=recs,
        ):
            resp = client.post("/audio-rec/music", json={
                "video_path": "/app/v.mp4",
                "count": 3,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["recommendations"][0]["bpm"], 128)

    def test_recommend_sfx(self):
        client = self._get_client()
        sfx_recs = [_make_audio_rec("sfx_001", "transition_sfx")]
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.recommend_sfx",
            new_callable=AsyncMock,
            return_value=sfx_recs,
        ):
            resp = client.post("/audio-rec/sfx", json={
                "video_path": "/app/v.mp4",
                "scene_changes": [5.0, 10.0, 15.0],
                "key_moments": [12.0],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_beat_cuts(self):
        client = self._get_client()
        cuts = [0.0, 1.875, 3.75, 5.625, 7.5]
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.generate_beat_matched_cuts",
            new_callable=AsyncMock,
            return_value=cuts,
        ):
            resp = client.post("/audio-rec/beat-cuts", json={
                "video_path": "/app/v.mp4",
                "music_bpm": 128,
                "video_duration": 30.0,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["cut_count"], 5)
        self.assertAlmostEqual(data["beat_interval_seconds"], 0.469, places=2)

    def test_beat_cuts_invalid_bpm(self):
        client = self._get_client()
        resp = client.post("/audio-rec/beat-cuts", json={
            "video_path": "/app/v.mp4",
            "music_bpm": 0,
            "video_duration": 30.0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_beat_cuts_invalid_duration(self):
        client = self._get_client()
        resp = client.post("/audio-rec/beat-cuts", json={
            "video_path": "/app/v.mp4",
            "music_bpm": 120,
            "video_duration": -1.0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_trending(self):
        client = self._get_client()
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.get_trending_audio",
            return_value=[_make_audio_rec()],
        ):
            resp = client.get("/audio-rec/trending?platform=tiktok")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["platform"], "tiktok")

    def test_stats(self):
        client = self._get_client()
        stats = {"music_tracks": 5, "sfx_tracks": 5, "total_recommendations_made": 20, "genres_available": 5}
        with patch(
            "src.services.audio_recommendation.AudioRecommendationService.get_audio_stats",
            return_value=stats,
        ):
            resp = client.get("/audio-rec/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["music_tracks"], 5)

    def test_list_genres(self):
        client = self._get_client()
        resp = client.get("/audio-rec/genres")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("upbeat_pop", resp.json()["genres"])

    def test_list_audio_types(self):
        client = self._get_client()
        resp = client.get("/audio-rec/audio-types")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("background_music", resp.json()["types"])


# ===========================================================================
# 2. Computer Vision API
# ===========================================================================

class TestComputerVisionAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.computer_vision import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_analyze_video(self):
        client = self._get_client()
        analyses = [_make_visual_analysis(ts) for ts in [0.0, 1.0, 2.0]]
        with patch(
            "src.services.computer_vision.ComputerVisionService.analyze_video_visuals",
            new_callable=AsyncMock,
            return_value=analyses,
        ):
            resp = client.post("/computer-vision/analyze", json={
                "video_path": "/app/v.mp4",
                "sample_interval": 1.0,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["frames_analyzed"], 3)
        self.assertAlmostEqual(data["frames"][0]["engagement_prediction"], 0.85)

    def test_analyze_invalid_interval(self):
        client = self._get_client()
        resp = client.post("/computer-vision/analyze", json={
            "video_path": "/app/v.mp4",
            "sample_interval": 0.0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_summary_success(self):
        client = self._get_client()
        summary = {
            "total_frames_analyzed": 30,
            "avg_brightness": 0.72,
            "avg_contrast": 0.65,
            "avg_sharpness": 0.78,
            "avg_engagement_prediction": 0.84,
            "total_faces_detected": 25,
            "has_face_presence": True,
            "visual_quality_score": 0.717,
        }
        with patch(
            "src.services.computer_vision.ComputerVisionService.get_visual_summary",
            return_value=summary,
        ):
            resp = client.get("/computer-vision/summary?video_path=/app/v.mp4")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["summary"]["has_face_presence"])

    def test_get_summary_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.computer_vision.ComputerVisionService.get_visual_summary",
            return_value={"error": "Video not analyzed"},
        ):
            resp = client.get("/computer-vision/summary?video_path=/app/missing.mp4")
        self.assertEqual(resp.status_code, 404)

    def test_best_frames_success(self):
        client = self._get_client()
        with patch(
            "src.services.computer_vision.ComputerVisionService.find_best_frames",
            return_value=[5.0, 12.0, 18.0],
        ):
            resp = client.post("/computer-vision/best-frames", json={
                "video_path": "/app/v.mp4",
                "criteria": "engagement",
                "count": 3,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertIn(5.0, data["timestamps"])

    def test_best_frames_by_brightness(self):
        client = self._get_client()
        with patch(
            "src.services.computer_vision.ComputerVisionService.find_best_frames",
            return_value=[3.0, 9.0],
        ):
            resp = client.post("/computer-vision/best-frames", json={
                "video_path": "/app/v.mp4",
                "criteria": "brightness",
                "count": 2,
            })
        self.assertEqual(resp.status_code, 200)

    def test_best_frames_invalid_criteria(self):
        client = self._get_client()
        resp = client.post("/computer-vision/best-frames", json={
            "video_path": "/app/v.mp4",
            "criteria": "vibes",
        })
        self.assertEqual(resp.status_code, 400)

    def test_best_frames_not_analyzed(self):
        client = self._get_client()
        with patch(
            "src.services.computer_vision.ComputerVisionService.find_best_frames",
            return_value=[],
        ):
            resp = client.post("/computer-vision/best-frames", json={"video_path": "/app/v.mp4"})
        self.assertEqual(resp.status_code, 404)

    def test_list_elements(self):
        client = self._get_client()
        resp = client.get("/computer-vision/elements")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("face", resp.json()["elements"])
        self.assertIn("motion", resp.json()["elements"])


# ===========================================================================
# 3. Competitor Intelligence API
# ===========================================================================

class TestCompetitorIntelAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.competitor_intel import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_add_competitor(self):
        client = self._get_client()
        competitor = _make_competitor()
        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.add_competitor",
            new_callable=AsyncMock,
            return_value=competitor,
        ):
            resp = client.post("/competitor-intel/competitors", json={
                "name": "TrendMaker",
                "platform_handles": {"youtube": "@trendmaker", "tiktok": "@trendmaker"},
                "niche": "fitness",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "added")
        self.assertEqual(data["name"], "TrendMaker")
        self.assertIn("competitor_id", data)

    def test_add_competitor_empty_handles(self):
        client = self._get_client()
        resp = client.post("/competitor-intel/competitors", json={
            "name": "NoHandle",
            "platform_handles": {},
            "niche": "tech",
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_dashboard(self):
        client = self._get_client()
        dashboard = {
            "competitors": [{"competitor_id": "comp_abc123", "name": "TrendMaker"}],
            "competitor_count": 1,
            "recent_viral_videos": [],
            "trend_insights": [],
            "monitoring_active": False,
        }
        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_dashboard",
            return_value=dashboard,
        ):
            resp = client.get("/competitor-intel/dashboard")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["dashboard"]["competitor_count"], 1)

    def test_get_performance(self):
        client = self._get_client()
        performance = {
            "competitor_id": "comp_abc123",
            "name": "TrendMaker",
            "period_days": 30,
            "videos_published": 15,
            "total_views": 500000,
            "avg_engagement_rate": 9.2,
            "avg_virality_score": 78.5,
            "best_performing_video": "Epic Workout #1",
            "platform_breakdown": {},
        }
        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_performance",
            return_value=performance,
        ):
            resp = client.get("/competitor-intel/competitors/comp_abc123?days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["performance"]["avg_virality_score"], 78.5)

    def test_get_performance_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.get_competitor_performance",
            return_value=None,
        ):
            resp = client.get("/competitor-intel/competitors/unknown_comp")
        self.assertEqual(resp.status_code, 404)

    def test_compare_to_competitors(self):
        client = self._get_client()
        result = {
            "comparisons": [
                {
                    "competitor_name": "TrendMaker",
                    "their_avg_engagement": 9.2,
                    "their_avg_virality": 78.5,
                    "your_avg_engagement": 5.0,
                    "your_avg_virality": 65.0,
                    "engagement_gap": 4.2,
                    "virality_gap": 13.5,
                }
            ],
            "average_market_engagement": 9.2,
            "average_market_virality": 78.5,
            "recommendations": ["Improve hook quality"],
        }
        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.compare_to_competitors",
            return_value=result,
        ):
            resp = client.post("/competitor-intel/compare", json={
                "user_metrics": {"avg_engagement": 5.0, "avg_virality": 65.0},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["comparison"]["comparisons"][0]["engagement_gap"], 4.2)

    def test_compare_empty_metrics(self):
        client = self._get_client()
        resp = client.post("/competitor-intel/compare", json={"user_metrics": {}})
        self.assertEqual(resp.status_code, 400)

    def test_stop_monitoring(self):
        client = self._get_client()
        with patch(
            "src.services.competitor_intelligence.CompetitorIntelligenceService.stop_monitoring",
            new_callable=AsyncMock,
        ):
            resp = client.post("/competitor-intel/monitoring/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "stopped")

    def test_list_platforms(self):
        client = self._get_client()
        resp = client.get("/competitor-intel/platforms")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("youtube", data["platforms"])
        self.assertIn("tiktok", data["platforms"])


if __name__ == "__main__":
    unittest.main()
