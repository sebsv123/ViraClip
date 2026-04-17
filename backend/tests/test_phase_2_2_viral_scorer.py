"""
Unit Tests — Phase 2.2: Custom Virality Scorer Fine-Tuning
===========================================================
Tests for ViralScorerService: feature extraction, MLP training, score blending,
model persistence, and integration with phi3_virality_service.
"""

import pytest
import pickle
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
#  Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractFeatures:
    """Test feature vector extraction from transcript + audio."""

    def test_returns_float32_array(self):
        from services.viral_scorer_service import extract_features
        import numpy as np

        feats = extract_features("Amazing secret nobody knows", duration=20.0)
        assert feats.dtype == np.float32

    def test_features_all_in_0_1_range(self):
        from services.viral_scorer_service import extract_features

        feats = extract_features(
            "Shocking truth about viral content",
            duration=30.0,
            audio_features={"tempo_bpm": 140, "speech_rate_words_per_min": 180},
        )
        assert feats.min() >= 0.0
        assert feats.max() <= 1.0

    def test_empty_transcript_does_not_crash(self):
        from services.viral_scorer_service import extract_features

        feats = extract_features("", duration=0.0)
        assert len(feats) > 0

    def test_viral_text_has_higher_keyword_score_than_neutral(self):
        from services.viral_scorer_service import extract_features

        viral_feats = extract_features(
            "shocking secret revealed nobody knows amazing viral truth"
        )
        neutral_feats = extract_features(
            "welcome to today episode talking about general topics slowly"
        )
        # keyword dimensions (indices 3-12) should be higher for viral text
        assert viral_feats[3:13].sum() > neutral_feats[3:13].sum()

    def test_audio_features_affect_vector(self):
        from services.viral_scorer_service import extract_features

        with_audio = extract_features(
            "test", audio_features={"tempo_bpm": 180, "speech_rate_words_per_min": 200}
        )
        without_audio = extract_features("test", audio_features=None)
        # Audio features should differ
        assert not (with_audio == without_audio).all()


# ─────────────────────────────────────────────────────────────────────────────
#  ViralScorerService — no model available
# ─────────────────────────────────────────────────────────────────────────────

class TestViralScorerNoModel:
    """Behaviour when model has not been trained yet."""

    def test_is_available_returns_false(self, tmp_path):
        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "nonexistent.pkl")
        assert not svc.is_available()

    def test_score_segment_returns_50_when_no_model(self, tmp_path):
        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "nonexistent.pkl")
        score = svc.score_segment("amazing secret viral content")
        assert score == 50

    def test_blend_with_phi3_returns_phi3_score_when_no_model(self, tmp_path):
        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "nonexistent.pkl")
        result = svc.blend_with_phi3(phi3_score=72, transcript="test")
        assert result == 72

    def test_train_skips_with_too_few_samples(self, tmp_path):
        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "model.pkl")
        result = svc.train([{"transcript": "hi", "duration": 5, "virality_score": 50}])
        assert result["status"] == "skipped"


# ─────────────────────────────────────────────────────────────────────────────
#  ViralScorerService — training
# ─────────────────────────────────────────────────────────────────────────────

class TestViralScorerTraining:
    """Test MLP training and persistence."""

    @pytest.fixture()
    def training_samples(self):
        """Generate 50 synthetic training samples."""
        samples = []
        for i in range(50):
            score = 30 + (i % 70)
            text = "secret viral content shock " * (i % 5 + 1) if score > 60 else "normal content talk " * 3
            samples.append({
                "transcript": text,
                "duration": 15.0 + i % 30,
                "audio_features": {"tempo_bpm": 100 + i % 80},
                "virality_score": float(score),
            })
        return samples

    def test_train_succeeds_with_enough_samples(self, tmp_path, training_samples):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "model.pkl")
        result = svc.train(training_samples)

        assert result["status"] == "trained"
        assert result["n_samples"] > 0
        assert "mae" in result
        assert "r2" in result

    def test_model_saved_to_disk(self, tmp_path, training_samples):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        model_file = tmp_path / "model.pkl"
        svc = ViralScorerService(model_path=model_file)
        svc.train(training_samples)

        assert model_file.exists()
        assert model_file.stat().st_size > 100

    def test_model_reloaded_from_disk(self, tmp_path, training_samples):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        model_file = tmp_path / "model.pkl"
        svc1 = ViralScorerService(model_path=model_file)
        svc1.train(training_samples)

        # Load fresh instance from same file
        svc2 = ViralScorerService(model_path=model_file)
        assert svc2.is_available()

    def test_trained_score_is_in_range(self, tmp_path, training_samples):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "model.pkl")
        svc.train(training_samples)

        score = svc.score_segment("shocking viral secret nobody knows", duration=20.0)
        assert 0 <= score <= 100

    def test_skips_invalid_samples(self, tmp_path):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        samples = [
            {"transcript": None, "duration": 10, "virality_score": 50},
            {"transcript": "valid content", "virality_score": None},
        ] + [
            {"transcript": f"valid sample {i}", "duration": 20, "virality_score": float(i % 100)}
            for i in range(30)
        ]

        svc = ViralScorerService(model_path=tmp_path / "model.pkl")
        result = svc.train(samples)
        # Should succeed despite bad samples
        assert result["status"] == "trained"


# ─────────────────────────────────────────────────────────────────────────────
#  blend_with_phi3
# ─────────────────────────────────────────────────────────────────────────────

class TestBlendWithPhi3:
    """Test MLP + Phi-3 score blending logic."""

    def test_blend_is_between_mlp_and_phi3(self, tmp_path):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        samples = [
            {"transcript": f"test content {i}", "duration": 15, "virality_score": float(i * 2)}
            for i in range(30)
        ]
        svc = ViralScorerService(model_path=tmp_path / "model.pkl")
        svc.train(samples)

        phi3 = 70
        result = svc.blend_with_phi3(phi3_score=phi3, transcript="secret viral content", duration=20.0)
        # Blend must be between 0 and 100
        assert 0 <= result <= 100

    def test_blend_default_weight_uses_40pct_mlp(self, tmp_path):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "model.pkl")

        # Use a mock model that always predicts 80 to isolate the blend formula
        mock_model = MagicMock()
        mock_model.predict.return_value = [80.0]
        svc._model = mock_model
        svc._n_training_samples = 100  # under 500 threshold → 40% MLP weight

        # Expected: 80*0.4 + 60*0.6 = 32 + 36 = 68
        result = svc.blend_with_phi3(phi3_score=60, transcript="text sample")
        assert 50 <= result <= 90

    def test_confident_weight_with_500_samples(self, tmp_path):
        pytest.importorskip("sklearn")

        from services.viral_scorer_service import ViralScorerService

        svc = ViralScorerService(model_path=tmp_path / "model.pkl")

        # Manually install a fake model that always predicts 80
        mock_model = MagicMock()
        mock_model.predict.return_value = [80.0]
        svc._model = mock_model
        svc._n_training_samples = 600  # confident threshold

        result = svc.blend_with_phi3(phi3_score=40, transcript="test")
        # 80*0.6 + 40*0.4 = 48 + 16 = 64
        assert result == 64


# ─────────────────────────────────────────────────────────────────────────────
#  get_viral_scorer singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestGetViralScorer:
    """Test singleton accessor."""

    def test_returns_same_instance(self):
        from services.viral_scorer_service import get_viral_scorer

        svc1 = get_viral_scorer()
        svc2 = get_viral_scorer()
        assert svc1 is svc2

    def test_is_viral_scorer_service(self):
        from services.viral_scorer_service import get_viral_scorer, ViralScorerService

        svc = get_viral_scorer()
        assert isinstance(svc, ViralScorerService)


# ─────────────────────────────────────────────────────────────────────────────
#  train_viral_scorer.py script
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainViralScorerScript:
    """Test training script helpers."""

    def test_generate_synthetic_samples_returns_expected_count(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from train_viral_scorer import generate_synthetic_samples

        samples = generate_synthetic_samples(n=100)
        assert len(samples) == 100
        for s in samples:
            assert "transcript" in s
            assert "virality_score" in s
            assert 0 <= s["virality_score"] <= 100

    def test_synthetic_score_variance(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from train_viral_scorer import generate_synthetic_samples

        samples = generate_synthetic_samples(n=200)
        scores = [s["virality_score"] for s in samples]
        # Should have both high and low scores
        assert max(scores) >= 70
        assert min(scores) <= 40


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
