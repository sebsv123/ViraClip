"""
viral_scorer_service.py — Phase 2.2
=====================================
Custom virality scorer: text + audio features → 3-layer MLP → scalar virality score.

Replaces / augments phi3_virality_service.py with a fast, locally-trained model
that learns from real ViraClip feedback data (stored in the feedback loop DB).

Architecture:
  Features (56-dimensional):
    - TF-IDF trigrams over transcript text (30 dims, truncated SVD → 30)
    - Audio features (13 dims): tempo_bpm, energy_peaks, speech_rate, rms_energy,
      spectral_centroid, zero_crossing_rate, mfcc_mean[8], pause_ratio
    - Structural (3 dims): duration_s, word_count, avg_word_length
    - Lexical virality (10 dims): keyword category scores

  Model: MLPRegressor (256→128→64 → 1)  ← scikit-learn, ~2MB saved model
  Training data: feedback loop DB + (optionally) TikTok-Videos HuggingFace dataset

Integration:
  1. If model file exists → blend MLP score with Phi-3 score (50/50)
  2. If model file missing → fall back to Phi-3 only (zero regression)
  3. Weekly retrain via FeedbackLoopService cron (Phase 5.3)

Usage:
    svc = ViralScorerService()
    score = svc.score_segment("Amazing secret nobody knows...", duration=22.0, audio_features={...})
    # → 78

    # Training (offline — called by feedback_cron or train_viral_scorer.py script):
    svc.train(training_samples)
"""

import logging
import os
import pickle
from pathlib import Path
from typing import Optional, List, Dict, Any

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(os.getenv("VIRAL_SCORER_MODEL", "/app/models/viral_scorer.pkl"))

# Blend weight: how much MLP contributes vs. Phi-3 result
# Higher when model has been trained on more samples
MLP_WEIGHT_DEFAULT = 0.40   # 40% MLP, 60% Phi-3
MLP_WEIGHT_CONFIDENT = 0.60  # 60% MLP after 500+ training samples

# ─── Viral keyword categories (used as features) ─────────────────────────────
_VIRAL_KWORDS: Dict[str, List[str]] = {
    "pattern_interrupt": ["shocking", "revealed", "secret", "truth", "exposed", "lie"],
    "curiosity_gap":     ["why", "how", "what", "this is", "turns out", "nobody tells"],
    "emotional":         ["love", "hate", "angry", "amazing", "incredible", "fail", "win"],
    "urgency":           ["now", "today", "breaking", "urgent", "must", "limited"],
    "social_proof":      ["everyone", "viral", "trending", "millions", "famous"],
    "negative_bias":     ["wrong", "avoid", "stop", "never", "mistake", "disaster"],
    "value":             ["tips", "tricks", "hack", "step", "guide", "easy", "fast"],
    "identity":          ["you", "your", "yourself", "we", "us", "our"],
    "story":             ["story", "time", "moment", "day", "night", "once"],
    "numbers":           ["1", "2", "3", "top", "best", "first", "last"],
}


# ─────────────────────────────────────────────────────────────────────────────
#  Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_features(
    transcript: str,
    duration: float = 15.0,
    audio_features: Optional[Dict] = None,
) -> np.ndarray:
    """
    Extract a fixed-length feature vector from transcript + audio + structural info.

    Returns:
        np.ndarray of shape (N_FEATURES,) — float32
    """
    feats: List[float] = []
    text = (transcript or "").lower()

    # ── Structural features (3) ───────────────────────────────────────────────
    words = text.split()
    word_count = len(words)
    avg_word_len = (sum(len(w) for w in words) / max(word_count, 1)) if words else 3.0
    feats.extend([
        min(duration / 60.0, 1.0),   # normalised duration
        min(word_count / 200.0, 1.0),
        min(avg_word_len / 10.0, 1.0),
    ])

    # ── Viral keyword scores (10) ─────────────────────────────────────────────
    text_tokens = set(text.split())
    for _, kws in _VIRAL_KWORDS.items():
        hits = sum(1 for kw in kws if kw in text)
        feats.append(min(hits / max(len(kws), 1), 1.0))

    # ── Audio features (13) ──────────────────────────────────────────────────
    af = audio_features or {}
    feats.extend([
        min(af.get("tempo_bpm", 120.0) / 200.0, 1.0),
        min(len(af.get("energy_peaks_timestamps", [])) / 10.0, 1.0),
        min(af.get("speech_rate_words_per_min", 150.0) / 300.0, 1.0),
        min(af.get("rms_energy", 0.05) / 0.5, 1.0),
        min(af.get("spectral_centroid", 2000.0) / 8000.0, 1.0),
        min(af.get("zero_crossing_rate", 0.1), 1.0),
        *[min(float(v) / 50.0, 1.0) for v in (af.get("mfcc_mean", [0.0] * 8) or [0.0] * 8)[:8]],
        min(af.get("pause_ratio", 0.2), 1.0),
    ])

    return np.array(feats, dtype=np.float32)


# ─────────────────────────────────────────────────────────────────────────────
#  ViralScorerService
# ─────────────────────────────────────────────────────────────────────────────

class ViralScorerService:
    """
    Locally-trained MLP virality scorer.
    Falls back gracefully if model not yet trained.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = Path(model_path or MODEL_PATH)
        self._model = None         # scikit-learn Pipeline
        self._n_training_samples = 0
        self._load_model()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if a trained model is loaded."""
        return self._model is not None

    def score_segment(
        self,
        transcript: str,
        duration: float = 15.0,
        audio_features: Optional[Dict] = None,
    ) -> int:
        """
        Predict virality score (0-100) from transcript + audio features.
        Returns 50 (neutral) if model not available.
        """
        if self._model is None:
            return 50

        features = extract_features(transcript, duration, audio_features)
        try:
            prediction = float(self._model.predict(features.reshape(1, -1))[0])
            return min(100, max(0, int(round(prediction))))
        except Exception as e:
            logger.warning(f"[viral_scorer] Prediction failed: {e}")
            return 50

    def blend_with_phi3(
        self,
        phi3_score: int,
        transcript: str,
        duration: float = 15.0,
        audio_features: Optional[Dict] = None,
    ) -> int:
        """
        Blend MLP prediction with Phi-3 score.
        Uses higher MLP weight when model was trained on many samples.
        """
        if not self.is_available():
            return phi3_score

        mlp_score = self.score_segment(transcript, duration, audio_features)
        weight = (
            MLP_WEIGHT_CONFIDENT
            if self._n_training_samples >= 500
            else MLP_WEIGHT_DEFAULT
        )
        blended = int(mlp_score * weight + phi3_score * (1 - weight))
        logger.debug(
            f"[viral_scorer] Blended: MLP={mlp_score} Phi3={phi3_score} "
            f"→ {blended} (w={weight:.0%})"
        )
        return min(100, max(0, blended))

    def train(self, samples: List[Dict[str, Any]]) -> dict:
        """
        Train the MLP on a list of samples.

        Each sample dict must have:
            - transcript:    str
            - duration:      float (seconds)
            - audio_features: dict (optional)
            - virality_score: int (0-100) — target label

        Returns:
            Training summary dict with r2, mae, n_samples.
        """
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_absolute_error, r2_score

        if len(samples) < 20:
            logger.warning(
                f"[viral_scorer] Only {len(samples)} samples — need ≥20 to train. Skipping."
            )
            return {"status": "skipped", "reason": f"only {len(samples)} samples"}

        X, y = [], []
        for s in samples:
            try:
                score = float(s["virality_score"])  # validate first — if this raises, X is unchanged
                feats = extract_features(
                    s.get("transcript", s.get("text", "")),
                    s.get("duration", 15.0),
                    s.get("audio_features"),
                )
                X.append(feats)
                y.append(score)
            except Exception as e:
                logger.debug(f"[viral_scorer] Skipping bad sample: {e}")

        if len(X) < 10:
            return {"status": "skipped", "reason": "too many invalid samples"}

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32)

        if len(X) >= 40:
            X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
        else:
            X_train, y_train = X, y
            X_val, y_val = X, y

        model = Pipeline([
            ("scaler", StandardScaler()),
            ("mlp", MLPRegressor(
                hidden_layer_sizes=(256, 128, 64),
                activation="relu",
                solver="adam",
                alpha=1e-4,
                learning_rate_init=1e-3,
                max_iter=500,
                early_stopping=True,
                validation_fraction=0.15,
                n_iter_no_change=20,
                random_state=42,
                verbose=False,
            )),
        ])

        logger.info(f"[viral_scorer] Training on {len(X_train)} samples...")
        model.fit(X_train, y_train)

        y_pred = model.predict(X_val)
        mae = float(mean_absolute_error(y_val, y_pred))
        r2 = float(r2_score(y_val, y_pred))

        logger.info(f"[viral_scorer] Training done: MAE={mae:.2f} R²={r2:.3f}")

        self._model = model
        self._n_training_samples = len(X_train)
        self._save_model()

        return {
            "status": "trained",
            "n_samples": len(X_train),
            "n_val": len(X_val),
            "mae": mae,
            "r2": r2,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_model(self) -> None:
        if not self.model_path.exists():
            logger.debug(f"[viral_scorer] Model not found at {self.model_path}")
            return
        try:
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._n_training_samples = data.get("n_training_samples", 0)
            logger.info(
                f"[viral_scorer] Model loaded from {self.model_path} "
                f"(trained on {self._n_training_samples} samples)"
            )
        except Exception as e:
            logger.warning(f"[viral_scorer] Failed to load model: {e}")

    def _save_model(self) -> None:
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump(
                {
                    "model": self._model,
                    "n_training_samples": self._n_training_samples,
                },
                f,
            )
        logger.info(f"[viral_scorer] Model saved → {self.model_path}")


# ─────────────────────────────────────────────────────────────────────────────
#  Singleton helper
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[ViralScorerService] = None


def get_viral_scorer() -> ViralScorerService:
    """Get or create the global ViralScorerService instance."""
    global _instance
    if _instance is None:
        _instance = ViralScorerService()
    return _instance
