"""
Tests for:
  1. Engagement Prediction API (/engagement/*)
  2. Dynamic Templates API (/templates/*)
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_curve_result(method="heuristic"):
    return {
        "curve": [95.0, 88.0, 80.0, 72.0, 65.0],
        "drop_off_points": [2.0, 4.0],
        "hook_points": [0.5, 2.5],
        "retention_score": 80,
        "predicted_by": method,
    }


def _make_template_dict(niche="gaming"):
    return {
        "niche": niche,
        "name": "Gaming Pro",
        "description": "High-energy gaming template",
        "style": {
            "primary_color": "#9146FF",
            "secondary_color": "#00FFFF",
            "accent_color": "#FF4655",
            "font_family": "Rajdhani-Bold",
            "title_style": "glitch",
            "animation_speed": "fast",
            "effect_intensity": 8,
        },
        "timing": {
            "intro_seconds": 2.0,
            "outro_seconds": 3.0,
            "optimal_duration_min": 15,
            "optimal_duration_max": 60,
        },
        "content": {
            "caption_style": "gaming_overlay",
            "recommended_music": ["electronic", "dubstep"],
            "suggested_effects": ["glitch", "flash"],
            "hashtags": ["gaming", "gamer"],
            "best_posting_times": ["18:00-22:00"],
        },
    }


# ===========================================================================
# 1. Engagement Prediction API
# ===========================================================================

class TestEngagementAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.engagement import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_predict_success(self):
        client = self._get_client()
        result = _make_curve_result()
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.predict_engagement_curve",
            return_value=result,
        ):
            resp = client.post("/engagement/predict", json={
                "words": [
                    {"text": "hey", "start": 0, "end": 500, "confidence": 0.95},
                    {"text": "you", "start": 500, "end": 1000, "confidence": 0.92},
                ],
                "duration": 30.0,
                "resolution": 1.0,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("curve", data)
        self.assertEqual(data["retention_score"], 80)
        self.assertEqual(data["predicted_by"], "heuristic")

    def test_predict_lstm_model(self):
        client = self._get_client()
        result = _make_curve_result("lstm_cnn")
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.predict_engagement_curve",
            return_value=result,
        ):
            resp = client.post("/engagement/predict", json={
                "words": [],
                "audio_features": {"rms_energy": 0.1, "spectral_centroid": 3000.0},
                "duration": 60.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["predicted_by"], "lstm_cnn")

    def test_predict_empty_words(self):
        client = self._get_client()
        result = _make_curve_result()
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.predict_engagement_curve",
            return_value=result,
        ):
            resp = client.post("/engagement/predict", json={})
        self.assertEqual(resp.status_code, 200)

    def test_predict_invalid_duration(self):
        client = self._get_client()
        resp = client.post("/engagement/predict", json={"duration": -5.0})
        self.assertEqual(resp.status_code, 400)

    def test_predict_invalid_resolution(self):
        client = self._get_client()
        resp = client.post("/engagement/predict", json={"resolution": 0.0})
        self.assertEqual(resp.status_code, 400)

    def test_train_success(self):
        client = self._get_client()
        summary = {
            "status": "trained",
            "n_samples": 12,
            "best_val_loss": 0.0043,
            "epochs": 30,
        }
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.train",
            return_value=summary,
        ):
            samples = [
                {
                    "words": [{"text": "hi", "start": 0, "end": 500, "confidence": 0.9}],
                    "duration": 30.0,
                    "retention_curve": [100.0, 90.0, 80.0],
                }
                for _ in range(12)
            ]
            resp = client.post("/engagement/train", json={
                "samples": samples,
                "epochs": 30,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "trained")
        self.assertEqual(data["summary"]["n_samples"], 12)

    def test_train_too_few_samples_returns_skipped(self):
        client = self._get_client()
        summary = {"status": "skipped", "reason": "need ≥10 samples, got 2"}
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.train",
            return_value=summary,
        ):
            resp = client.post("/engagement/train", json={
                "samples": [{"duration": 30}] * 2,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "skipped")

    def test_train_failed_raises_422(self):
        client = self._get_client()
        summary = {"status": "failed", "reason": "Missing dependency: torch"}
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.train",
            return_value=summary,
        ):
            resp = client.post("/engagement/train", json={
                "samples": [{"duration": 30}] * 12,
            })
        self.assertEqual(resp.status_code, 422)

    def test_train_empty_samples(self):
        client = self._get_client()
        resp = client.post("/engagement/train", json={"samples": []})
        self.assertEqual(resp.status_code, 400)

    def test_record_actual_no_drift(self):
        client = self._get_client()
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.record_actual",
            return_value=False,
        ):
            resp = client.post("/engagement/record-actual", json={
                "predicted_retention": 75.0,
                "actual_retention": 73.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["retrain_recommended"])

    def test_record_actual_drift(self):
        client = self._get_client()
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.record_actual",
            return_value=True,
        ):
            resp = client.post("/engagement/record-actual", json={
                "predicted_retention": 80.0,
                "actual_retention": 40.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["retrain_recommended"])

    def test_get_status_no_model(self):
        client = self._get_client()
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.is_available",
            return_value=False,
        ):
            resp = client.get("/engagement/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["model_available"])
        self.assertEqual(data["prediction_mode"], "heuristic")

    def test_get_status_model_loaded(self):
        client = self._get_client()
        with patch(
            "src.services.engagement_prediction_service.EngagementPredictionService.is_available",
            return_value=True,
        ):
            resp = client.get("/engagement/status")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["model_available"])
        self.assertEqual(resp.json()["prediction_mode"], "lstm_cnn")


# ===========================================================================
# 2. Dynamic Templates API
# ===========================================================================

class TestTemplatesAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.templates import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _mock_template(self):
        from src.services.dynamic_templates import (
            NicheTemplate,
            NicheTemplateType,
            TemplateStyle,
        )
        return NicheTemplate(
            niche=NicheTemplateType.GAMING,
            name="Gaming Pro",
            description="High-energy gaming template",
            style=TemplateStyle(
                primary_color="#9146FF",
                secondary_color="#00FFFF",
                accent_color="#FF4655",
                font_family="Rajdhani-Bold",
                title_style="glitch",
                animation_speed="fast",
                effect_intensity=8,
            ),
            intro_duration=2.0,
            outro_duration=3.0,
            caption_style="gaming_overlay",
            recommended_music_genres=["electronic", "dubstep"],
            suggested_effects=["glitch", "flash"],
            optimal_duration_range=(15, 60),
            best_posting_times=["18:00-22:00"],
            hashtag_recommendations=["gaming", "gamer"],
        )

    def test_list_templates(self):
        client = self._get_client()
        resp = client.get("/templates")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 8)
        niches = [t["niche"] for t in data["templates"]]
        self.assertIn("gaming", niches)
        self.assertIn("education", niches)

    def test_get_template_gaming(self):
        client = self._get_client()
        resp = client.get("/templates/gaming")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["template"]["niche"], "gaming")
        self.assertIn("style", data["template"])
        self.assertIn("timing", data["template"])

    def test_get_template_fitness(self):
        client = self._get_client()
        resp = client.get("/templates/fitness")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["template"]["niche"], "fitness")

    def test_get_template_invalid(self):
        client = self._get_client()
        resp = client.get("/templates/alien_content")
        self.assertEqual(resp.status_code, 400)

    def test_optimal_settings(self):
        client = self._get_client()
        settings = {
            "template": "Gaming Pro",
            "style_config": {"primary_color": "#9146FF"},
            "timing": {"intro_seconds": 2.0, "recommended_duration": 45},
            "content": {"recommended_music": ["electronic"]},
            "posting": {"best_times": ["18:00-22:00"]},
            "platform_adjustments": {"aspect_ratio": "9:16"},
        }
        with patch(
            "src.services.dynamic_templates.DynamicTemplateSystem.get_optimal_settings",
            return_value=settings,
        ):
            resp = client.post("/templates/optimal-settings", json={
                "niche": "gaming",
                "content_duration": 45,
                "target_platform": "tiktok",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["settings"]["template"], "Gaming Pro")

    def test_optimal_settings_invalid_niche(self):
        client = self._get_client()
        resp = client.post("/templates/optimal-settings", json={
            "niche": "magic",
            "content_duration": 30,
        })
        self.assertEqual(resp.status_code, 400)

    def test_style_config(self):
        client = self._get_client()
        config = {
            "template_name": "Gaming Pro",
            "niche": "gaming",
            "colors": {"primary": "#9146FF"},
            "typography": {"main_font": "Rajdhani-Bold"},
            "effects": {"intensity": 8},
            "audio": {"recommended_genres": ["electronic"]},
            "platform": {"aspect_ratio": "9:16"},
            "recommendations": {"hashtags": ["gaming"]},
        }
        with patch(
            "src.services.dynamic_templates.DynamicTemplateSystem.generate_complete_style_config",
            return_value=config,
        ):
            resp = client.post("/templates/style-config", json={
                "niche": "gaming",
                "content_type": "gameplay",
                "target_platform": "tiktok",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["config"]["niche"], "gaming")

    def test_style_config_fallback_niche(self):
        client = self._get_client()
        resp = client.post("/templates/style-config", json={"niche": "alchemy"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("config", resp.json())

    def test_suggest_templates(self):
        client = self._get_client()
        suggestions = [
            {"niche": "gaming", "template_name": "Gaming Pro", "score": 30, "confidence": 100, "config_preview": {}},
            {"niche": "comedy", "template_name": "Comedy Central", "score": 10, "confidence": 50, "config_preview": {}},
        ]
        with patch(
            "src.services.dynamic_templates.DynamicTemplateSystem.suggest_templates_for_content",
            return_value=suggestions,
        ):
            resp = client.post("/templates/suggest", json={
                "content_description": "epic gaming montage with funny moments",
                "keywords": ["gaming", "funny", "montage"],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["suggestions"][0]["niche"], "gaming")

    def test_suggest_no_input(self):
        client = self._get_client()
        resp = client.post("/templates/suggest", json={
            "content_description": "",
            "keywords": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_niches(self):
        client = self._get_client()
        resp = client.get("/templates/niches/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("gaming", data["niches"])
        self.assertIn("finance", data["niches"])
        self.assertIn("motivation", data["niches"])


if __name__ == "__main__":
    unittest.main()
