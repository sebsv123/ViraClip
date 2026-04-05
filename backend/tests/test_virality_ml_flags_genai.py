"""
Tests for:
  1. ML Virality Predictor API (/virality/ml/*)
  2. Feature Flags API (/feature-flags/*)
  3. Generative AI API (/genai/*)
"""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prediction():
    from src.services.ml_virality_predictor import ViralityPrediction
    return ViralityPrediction(
        predicted_score=72.5,
        confidence=0.85,
        feature_importance={"hook_strength": 0.22, "has_hook": 0.18},
        model_version="v1.0.0",
        prediction_time=datetime.now().isoformat(),
        recommendation="Add a stronger hook in the first 3 seconds",
    )


def _make_features_vector():
    return {
        "duration_seconds": 30.0,
        "has_hook": 1.0,
        "hook_strength": 0.7,
        "emotional_valence": 0.6,
        "pattern_match_score": 0.5,
        "audio_energy": 0.5,
        "speech_clarity": 0.7,
        "silence_ratio": 0.1,
        "motion_intensity": 0.5,
        "face_presence": 0.5,
        "scene_changes": 3.0,
        "word_count": 50.0,
        "sentiment_score": 0.6,
        "readability_score": 0.7,
        "keyword_density": 0.1,
        "similar_content_avg_views": 1000.0,
        "niche_performance_score": 0.5,
        "time_of_day_factor": 1.0,
    }


def _make_gen_result(success=True, request_id="req_001"):
    from src.services.generative_ai import GenerationResult
    return GenerationResult(
        request_id=request_id,
        success=success,
        image_url="https://openai.com/images/gen_001.png" if success else None,
        local_path=Path("/app/temp/generated_images/gen_001.png") if success else None,
        generation_time_ms=1500,
        prompt_used="YouTube thumbnail: test viral style",
        cost_usd=0.04 if success else 0.0,
        error_message=None if success else "API key not configured",
    )


# ===========================================================================
# 1. ML Virality Predictor API
# ===========================================================================

class TestViralityMLAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.virality_ml import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_predict_success(self):
        client = self._get_client()
        prediction = _make_prediction()
        mock_features = MagicMock()
        with patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.extract_features",
            return_value=mock_features,
        ), patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.predict_virality",
            return_value=prediction,
        ):
            resp = client.post("/virality/ml/predict", json={
                "clip_data": {"duration": 30, "has_hook": True, "hook_strength": 0.7},
                "transcript": "This is amazing content you won't believe",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["predicted_score"], 72.5)
        self.assertEqual(data["confidence"], 0.85)
        self.assertIn("recommendation", data)

    def test_predict_minimal_input(self):
        client = self._get_client()
        prediction = _make_prediction()
        mock_features = MagicMock()
        with patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.extract_features",
            return_value=mock_features,
        ), patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.predict_virality",
            return_value=prediction,
        ):
            resp = client.post("/virality/ml/predict", json={})
        self.assertEqual(resp.status_code, 200)

    def test_extract_features(self):
        client = self._get_client()
        mock_features = MagicMock()
        feat_vec = _make_features_vector()
        with patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.extract_features",
            return_value=mock_features,
        ), patch(
            "src.services.ml_virality_predictor.MLViralityPredictor._features_to_vector",
            return_value=feat_vec,
        ):
            resp = client.post("/virality/ml/features", json={
                "clip_data": {"duration": 30},
                "transcript": "test content",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("features", data)
        self.assertIn("duration_seconds", data["features"])

    def test_train_success(self):
        client = self._get_client()
        mock_features = MagicMock()
        stats = {
            "version": "v1.0.0",
            "training_samples": 51,
            "feature_weights": {},
            "last_updated": datetime.now().isoformat(),
            "accuracy_estimate": 88.5,
        }
        with patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.extract_features",
            return_value=mock_features,
        ), patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.train",
        ), patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.get_model_stats",
            return_value=stats,
        ):
            resp = client.post("/virality/ml/train", json={
                "clip_data": {"duration": 30},
                "transcript": "test",
                "actual_virality_score": 85.0,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "trained")
        self.assertEqual(data["training_samples"], 51)

    def test_train_invalid_score(self):
        client = self._get_client()
        resp = client.post("/virality/ml/train", json={
            "actual_virality_score": 150.0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_model_stats(self):
        client = self._get_client()
        stats = {
            "version": "v1.0.0",
            "training_samples": 200,
            "feature_weights": {"hook_strength": 0.20},
            "last_updated": datetime.now().isoformat(),
            "accuracy_estimate": 91.2,
        }
        with patch(
            "src.services.ml_virality_predictor.MLViralityPredictor.get_model_stats",
            return_value=stats,
        ):
            resp = client.get("/virality/ml/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["model"]["training_samples"], 200)


# ===========================================================================
# 2. Feature Flags API
# ===========================================================================

class TestFeatureFlagsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.feature_flags import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _mock_flag_status(self, name="test_flag", enabled=True):
        return {
            "name": name,
            "enabled": enabled,
            "strategy": "all_users",
            "rollout_percentage": 0,
            "allowed_users_count": 0,
            "blocked_users_count": 0,
            "metadata": {},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

    def test_create_flag(self):
        client = self._get_client()
        mock_flag = MagicMock()
        mock_flag.name = "new_feature"
        flag_status = self._mock_flag_status("new_feature")

        mock_mgr = MagicMock()
        mock_mgr.flags = {}                       # empty so name not in flags
        mock_mgr.create_flag.return_value = mock_flag
        mock_mgr.get_flag_status.return_value = flag_status

        with patch(
            "src.api.routes.feature_flags.get_feature_flag_manager",
            return_value=mock_mgr,
        ):
            resp = client.post("/feature-flags", json={
                "name": "new_feature",
                "enabled": True,
                "strategy": "all_users",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "created")

    def test_create_flag_invalid_strategy(self):
        client = self._get_client()
        resp = client.post("/feature-flags", json={
            "name": "bad_flag",
            "strategy": "moon_phase",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_flags(self):
        client = self._get_client()
        mock_flags = {
            "flag_a": self._mock_flag_status("flag_a"),
            "flag_b": self._mock_flag_status("flag_b", enabled=False),
        }
        with patch(
            "src.services.feature_flags.FeatureFlagManager.get_all_flags",
            return_value=mock_flags,
        ):
            resp = client.get("/feature-flags")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("flags", resp.json())

    def test_get_flag_success(self):
        client = self._get_client()
        flag_status = self._mock_flag_status("test_flag")
        with patch(
            "src.services.feature_flags.FeatureFlagManager.get_flag_status",
            return_value=flag_status,
        ):
            resp = client.get("/feature-flags/test_flag")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["flag"]["name"], "test_flag")

    def test_get_flag_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.get_flag_status",
            return_value=None,
        ):
            resp = client.get("/feature-flags/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_delete_flag(self):
        client = self._get_client()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.delete_flag",
            return_value=True,
        ):
            resp = client.delete("/feature-flags/test_flag")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_delete_flag_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.delete_flag",
            return_value=False,
        ):
            resp = client.delete("/feature-flags/missing")
        self.assertEqual(resp.status_code, 404)

    def test_toggle_flag(self):
        client = self._get_client()
        flag_status = self._mock_flag_status("test_flag", enabled=False)
        with patch(
            "src.services.feature_flags.FeatureFlagManager.toggle_flag",
            return_value=True,
        ), patch(
            "src.services.feature_flags.FeatureFlagManager.get_flag_status",
            return_value=flag_status,
        ):
            resp = client.post("/feature-flags/test_flag/toggle")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "toggled")

    def test_update_rollout(self):
        client = self._get_client()
        flag_status = self._mock_flag_status()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.update_rollout",
            return_value=True,
        ), patch(
            "src.services.feature_flags.FeatureFlagManager.get_flag_status",
            return_value=flag_status,
        ):
            resp = client.patch("/feature-flags/test_flag/rollout", json={"percentage": 50})
        self.assertEqual(resp.status_code, 200)

    def test_update_rollout_invalid(self):
        client = self._get_client()
        resp = client.patch("/feature-flags/test_flag/rollout", json={"percentage": 150})
        self.assertEqual(resp.status_code, 400)

    def test_enable_for_user(self):
        client = self._get_client()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.enable_for_user",
            return_value=True,
        ):
            resp = client.post("/feature-flags/test_flag/enable-user", json={"user_id": "user_a"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "enabled")

    def test_disable_for_user(self):
        client = self._get_client()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.disable_for_user",
            return_value=True,
        ):
            resp = client.post("/feature-flags/test_flag/disable-user", json={"user_id": "user_b"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "disabled")

    def test_check_flag_enabled(self):
        client = self._get_client()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.is_enabled",
            return_value=True,
        ):
            resp = client.get("/feature-flags/test_flag/check?user_id=user_a")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["enabled"])

    def test_check_flag_disabled(self):
        client = self._get_client()
        with patch(
            "src.services.feature_flags.FeatureFlagManager.is_enabled",
            return_value=False,
        ):
            resp = client.get("/feature-flags/test_flag/check?user_id=user_b")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["enabled"])

    def test_list_strategies(self):
        client = self._get_client()
        resp = client.get("/feature-flags/strategies/list")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("all_users", resp.json()["strategies"])
        self.assertIn("canary", resp.json()["strategies"])


# ===========================================================================
# 3. Generative AI API
# ===========================================================================

class TestGenAIAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.genai import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_generate_thumbnail_success(self):
        client = self._get_client()
        result = _make_gen_result()
        with patch(
            "src.services.generative_ai.GenerativeAIService.generate_thumbnail",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/genai/thumbnail", json={
                "video_title": "Top 10 AI Hacks",
                "video_description": "Amazing AI productivity hacks",
                "style": "viral",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["result"]["success"])
        self.assertEqual(data["result"]["cost_usd"], 0.04)

    def test_generate_thumbnail_failure(self):
        client = self._get_client()
        result = _make_gen_result(success=False)
        with patch(
            "src.services.generative_ai.GenerativeAIService.generate_thumbnail",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/genai/thumbnail", json={
                "video_title": "Test Video",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["result"]["success"])
        self.assertIn("error_message", resp.json()["result"])

    def test_batch_generate_thumbnails(self):
        client = self._get_client()
        results = [_make_gen_result(request_id=f"req_{i}") for i in range(3)]
        with patch(
            "src.services.generative_ai.GenerativeAIService.batch_generate_thumbnails",
            new_callable=AsyncMock,
            return_value=results,
        ):
            resp = client.post("/genai/thumbnail/batch", json={
                "videos": [
                    {"title": "Video 1", "description": "desc 1"},
                    {"title": "Video 2", "description": "desc 2"},
                    {"title": "Video 3", "description": "desc 3"},
                ],
                "style": "viral",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 3)

    def test_batch_empty_videos(self):
        client = self._get_client()
        resp = client.post("/genai/thumbnail/batch", json={"videos": []})
        self.assertEqual(resp.status_code, 400)

    def test_generate_background(self):
        client = self._get_client()
        result = _make_gen_result()
        with patch(
            "src.services.generative_ai.GenerativeAIService.generate_background",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/genai/background", json={
                "theme": "technology",
                "mood": "energetic",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["result"]["success"])

    def test_generate_text_effect(self):
        client = self._get_client()
        result = _make_gen_result()
        with patch(
            "src.services.generative_ai.GenerativeAIService.generate_text_effect",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/genai/text-effect", json={
                "text": "Watch This!",
                "effect_style": "neon",
            })
        self.assertEqual(resp.status_code, 200)

    def test_generate_text_effect_empty(self):
        client = self._get_client()
        resp = client.post("/genai/text-effect", json={"text": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_configure_provider(self):
        client = self._get_client()
        with patch(
            "src.services.generative_ai.GenerativeAIService.configure_provider",
        ):
            resp = client.post("/genai/configure", json={
                "provider": "dalle",
                "api_key": "sk-test123",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "configured")

    def test_configure_invalid_provider(self):
        client = self._get_client()
        resp = client.post("/genai/configure", json={
            "provider": "imaginary_ai",
            "api_key": "key123",
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_stats(self):
        client = self._get_client()
        stats = {
            "total_generations": 150,
            "successful": 140,
            "failed": 10,
            "total_cost_usd": 5.60,
            "avg_generation_time_ms": 1450.0,
        }
        with patch(
            "src.services.generative_ai.GenerativeAIService.get_generation_stats",
            return_value=stats,
        ), patch(
            "src.services.generative_ai.GenerativeAIService.get_user_costs",
            return_value=0.12,
        ):
            resp = client.get("/genai/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["total_generations"], 150)


if __name__ == "__main__":
    unittest.main()
