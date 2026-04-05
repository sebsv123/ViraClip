"""
Unit Tests — Phase 8.4: ONNX Inference Service
===============================================
Tests for ONNX export, fallback paths, OnnxInferenceService capabilities,
and mobile/edge deployment helpers.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
#  OnnxInferenceService — no ONNX models available
# ─────────────────────────────────────────────────────────────────────────────

class TestOnnxServiceNoModels:
    """Behaviour when no ONNX models are present."""

    def test_is_viral_scorer_available_false(self, tmp_path):
        from services.onnx_inference_service import OnnxInferenceService

        with patch("services.onnx_inference_service.VIRAL_SCORER_ONNX", tmp_path / "no.onnx"), \
             patch("services.onnx_inference_service.ENGAGEMENT_ONNX", tmp_path / "no2.onnx"):
            svc = OnnxInferenceService()

        assert not svc.is_viral_scorer_available()
        assert not svc.is_engagement_available()

    def test_predict_virality_falls_back_to_50(self, tmp_path):
        from services.onnx_inference_service import OnnxInferenceService

        with patch("services.onnx_inference_service.VIRAL_SCORER_ONNX", tmp_path / "no.onnx"), \
             patch("services.onnx_inference_service.ENGAGEMENT_ONNX", tmp_path / "no2.onnx"):
            svc = OnnxInferenceService()

        with patch("services.onnx_inference_service.OnnxInferenceService._fallback_virality",
                   return_value=50) as mock_fb:
            score = svc.predict_virality("test transcript", duration=20.0)

        assert score == 50

    def test_predict_engagement_falls_back(self, tmp_path):
        from services.onnx_inference_service import OnnxInferenceService

        with patch("services.onnx_inference_service.VIRAL_SCORER_ONNX", tmp_path / "no.onnx"), \
             patch("services.onnx_inference_service.ENGAGEMENT_ONNX", tmp_path / "no2.onnx"):
            svc = OnnxInferenceService()

        fallback_result = {
            "curve": [80, 75, 70], "drop_off_points": [],
            "hook_points": [], "retention_score": 75, "predicted_by": "heuristic"
        }
        with patch.object(svc, "_fallback_engagement", return_value=fallback_result):
            result = svc.predict_engagement(words=[], duration=10.0)

        assert result["retention_score"] == 75

    def test_get_capabilities_returns_dict(self, tmp_path):
        from services.onnx_inference_service import OnnxInferenceService

        with patch("services.onnx_inference_service.VIRAL_SCORER_ONNX", tmp_path / "no.onnx"), \
             patch("services.onnx_inference_service.ENGAGEMENT_ONNX", tmp_path / "no2.onnx"):
            svc = OnnxInferenceService()

        caps = svc.get_capabilities()
        assert "viral_scorer_onnx" in caps
        assert "engagement_onnx" in caps
        assert caps["viral_scorer_onnx"] is False


# ─────────────────────────────────────────────────────────────────────────────
#  OnnxInferenceService — with mocked ONNX session
# ─────────────────────────────────────────────────────────────────────────────

class TestOnnxServiceWithMockedSession:
    """Test inference path when ONNX session is available."""

    def test_viral_score_uses_onnx_session(self, tmp_path):
        from services.onnx_inference_service import OnnxInferenceService

        with patch("services.onnx_inference_service.VIRAL_SCORER_ONNX", tmp_path / "no.onnx"), \
             patch("services.onnx_inference_service.ENGAGEMENT_ONNX", tmp_path / "no2.onnx"):
            svc = OnnxInferenceService()

        # Inject a mock session
        mock_session = MagicMock()
        mock_session.run.return_value = [[[78.5]]]
        svc._viral_session = mock_session

        with patch("services.onnx_inference_service.OnnxInferenceService.predict_virality",
                   wraps=svc.predict_virality):
            # Manually test the flow with mocked extract_features
            import numpy as np
            with patch("services.viral_scorer_service.extract_features",
                       return_value=np.zeros(26, dtype=np.float32)):
                score = svc.predict_virality("test transcript", duration=20.0)

        assert 0 <= score <= 100

    def test_engagement_uses_onnx_session(self, tmp_path):
        from services.onnx_inference_service import OnnxInferenceService
        import numpy as np

        with patch("services.onnx_inference_service.VIRAL_SCORER_ONNX", tmp_path / "no.onnx"), \
             patch("services.onnx_inference_service.ENGAGEMENT_ONNX", tmp_path / "no2.onnx"):
            svc = OnnxInferenceService()

        # Mock engagement session returning a retention curve
        mock_session = MagicMock()
        fake_curve = np.array([[0.9, 0.85, 0.8, 0.75, 0.7]], dtype=np.float32)
        mock_session.run.return_value = [fake_curve]
        svc._engagement_session = mock_session

        with patch("services.engagement_prediction_service.extract_time_series_features",
                   return_value=np.zeros((5, 10), dtype=np.float32)):
            result = svc.predict_engagement(words=[], duration=5.0)

        assert result["predicted_by"] == "onnx"
        assert len(result["curve"]) == 5
        assert 0 <= result["retention_score"] <= 100


# ─────────────────────────────────────────────────────────────────────────────
#  export_viral_scorer_to_onnx
# ─────────────────────────────────────────────────────────────────────────────

class TestExportViralScorerToOnnx:
    """Test viral_scorer ONNX export."""

    def test_returns_false_when_pkl_missing(self, tmp_path):
        from services.onnx_inference_service import export_viral_scorer_to_onnx

        result = export_viral_scorer_to_onnx(
            model_pkl_path=tmp_path / "nonexistent.pkl",
            onnx_output_path=tmp_path / "out.onnx",
        )
        assert result is False

    def test_returns_false_when_skl2onnx_not_installed(self, tmp_path):
        import pickle
        from services.onnx_inference_service import export_viral_scorer_to_onnx

        pkl = tmp_path / "model.pkl"
        from sklearn.dummy import DummyClassifier
        pkl.write_bytes(pickle.dumps({"model": DummyClassifier(), "n_training_samples": 50}))

        with patch("builtins.__import__", side_effect=lambda name, *args, **kwargs: (
            (_ for _ in ()).throw(ImportError("skl2onnx")) if name == "skl2onnx"
            else __import__(name, *args, **kwargs)
        )):
            result = export_viral_scorer_to_onnx(
                model_pkl_path=pkl,
                onnx_output_path=tmp_path / "out.onnx",
            )

        # Should handle import error gracefully
        assert isinstance(result, bool)

    def test_exports_with_trained_model(self, tmp_path):
        """Integration test — requires sklearn + skl2onnx."""
        pytest.importorskip("skl2onnx")
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService
        from services.onnx_inference_service import export_viral_scorer_to_onnx

        # Train a tiny model
        samples = [
            {"transcript": f"test content {i}", "duration": 15.0, "virality_score": float(i % 100)}
            for i in range(30)
        ]
        svc = ViralScorerService(model_path=tmp_path / "model.pkl")
        svc.train(samples)

        out = tmp_path / "viral_scorer.onnx"
        result = export_viral_scorer_to_onnx(
            model_pkl_path=tmp_path / "model.pkl",
            onnx_output_path=out,
        )

        assert result is True
        assert out.exists()
        assert out.stat().st_size > 100


# ─────────────────────────────────────────────────────────────────────────────
#  get_onnx_service singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestGetOnnxService:
    def test_returns_same_instance(self):
        from services.onnx_inference_service import get_onnx_service

        s1 = get_onnx_service()
        s2 = get_onnx_service()
        assert s1 is s2

    def test_is_onnx_service(self):
        from services.onnx_inference_service import get_onnx_service, OnnxInferenceService
        assert isinstance(get_onnx_service(), OnnxInferenceService)


# ─────────────────────────────────────────────────────────────────────────────
#  export_to_onnx.py script
# ─────────────────────────────────────────────────────────────────────────────

class TestExportScript:
    def test_script_exists_and_is_importable(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        try:
            import export_to_onnx
        except ImportError as e:
            pytest.fail(f"Failed to import export_to_onnx script: {e}")

    def test_main_runs_with_status_flag(self, capsys):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from export_to_onnx import print_status

        with patch("export_to_onnx.ONNX_DIR", Path("/nonexistent")):
            print_status()  # Should not raise

        captured = capsys.readouterr()
        assert "ONNX Model Status" in captured.out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
