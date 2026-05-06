"""
engagement_prediction_service.py — Phase 8.3
==============================================
LSTM/CNN hybrid for time-series viewer engagement prediction.

Predicts:
  - Drop-off probability curve (per second)
  - Optimal hook insertion points
  - Retention score (0-100)
  - Drift detection flag (retraining needed)

Architecture:
  Features per time-step (10-dim):
    - word_confidence, speech_rate_local, energy, spectral_centroid
    - is_filler, silence_gap, virality_keyword_density
    - hook_type_encoding, segment_position_normalized, duration_normalized

  Model: 1D-CNN (local patterns) → BiLSTM (temporal context) → Dense → dropout
  Training target: viewer retention rate per second (from feedback DB)
  Without trained model: heuristic sigmoid curve based on virality features

Integration:
  - Called post-analysis in video_service.py
  - Exposed on clip result dict as `engagement_curve`, `drop_off_points`, `retention_score`
  - ComfyUI node: `EngagementPredictionNode` in viraclip_advanced_ml.py

Training:
  python /app/scripts/train_engagement_predictor.py
"""

import logging
import os
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(os.getenv("ENGAGEMENT_MODEL", "/app/models/engagement_predictor.pkl"))

# Drift threshold: if mean absolute error vs. recent actuals > this → trigger retrain
DRIFT_THRESHOLD = float(os.getenv("ENGAGEMENT_DRIFT_THRESHOLD", "15.0"))

# ─────────────────────────────────────────────────────────────────────────────
#  Feature extraction from transcript words + audio
# ─────────────────────────────────────────────────────────────────────────────

_FILLER_WORDS = {"um", "uh", "like", "you know", "basically", "literally", "actually", "right"}

_HOOK_KEYWORDS = {
    "question": ["what", "why", "how", "who", "when"],
    "shock": ["shocking", "never", "secret", "revealed", "exposed", "truth"],
    "number": ["1", "2", "3", "top", "best", "first"],
    "call_to_action": ["watch", "see", "look", "listen", "wait"],
}


def extract_time_series_features(
    words: List[Dict[str, Any]],
    audio_features: Optional[Dict] = None,
    duration: float = 30.0,
    resolution: float = 1.0,
) -> np.ndarray:
    """
    Extract a time-series feature matrix at `resolution`-second intervals.

    Args:
        words:         Word-level transcript (each has start_ms, end_ms, text, confidence)
        audio_features: Audio analysis result dict
        duration:      Total clip duration in seconds
        resolution:    Time step in seconds (default 1.0s)

    Returns:
        np.ndarray of shape (T, 10) — float32, where T = ceil(duration / resolution)
    """
    T = max(1, int(np.ceil(duration / resolution)))
    F = 10
    matrix = np.zeros((T, F), dtype=np.float32)

    af = audio_features or {}
    global_energy = float(af.get("rms_energy", 0.05))
    global_centroid = float(af.get("spectral_centroid", 2000.0))
    energy_peaks = set(int(t) for t in af.get("energy_peaks_timestamps", []) or [])

    # Build per-second word buckets
    for t_idx in range(T):
        t_start = t_idx * resolution
        t_end = t_start + resolution

        # Words in this window
        bucket = [
            w for w in words
            if w.get("start", 0) / 1000.0 < t_end
            and w.get("end", 0) / 1000.0 > t_start
        ]
        texts = [w.get("text", "").lower().strip() for w in bucket]
        n_words = max(len(bucket), 1)

        # Feature 0: mean word confidence
        confs = [w.get("confidence", 0.8) for w in bucket]
        matrix[t_idx, 0] = float(np.mean(confs)) if confs else 0.5

        # Feature 1: local speech rate (words/sec)
        matrix[t_idx, 1] = min(len(bucket) / resolution / 5.0, 1.0)

        # Feature 2: normalised energy
        matrix[t_idx, 2] = min(global_energy / 0.5, 1.0)

        # Feature 3: spectral centroid normalised
        matrix[t_idx, 3] = min(global_centroid / 8000.0, 1.0)

        # Feature 4: filler word ratio
        filler_count = sum(1 for t in texts if any(f in t for f in _FILLER_WORDS))
        matrix[t_idx, 4] = filler_count / n_words

        # Feature 5: silence gap (words absent = 1.0)
        matrix[t_idx, 5] = 0.0 if bucket else 1.0

        # Feature 6: viral keyword density
        kw_count = sum(
            1 for t in texts
            for kws in _HOOK_KEYWORDS.values()
            for kw in kws if kw in t
        )
        matrix[t_idx, 6] = min(kw_count / max(n_words, 1), 1.0)

        # Feature 7: energy peak flag
        matrix[t_idx, 7] = 1.0 if int(t_start) in energy_peaks else 0.0

        # Feature 8: position in clip (0 = start, 1 = end)
        matrix[t_idx, 8] = t_start / max(duration, 1.0)

        # Feature 9: hook zone (first 3s get 1.0, fades linearly)
        matrix[t_idx, 9] = max(0.0, 1.0 - t_start / 3.0)

    return matrix


# ─────────────────────────────────────────────────────────────────────────────
#  EngagementPredictionService
# ─────────────────────────────────────────────────────────────────────────────

class EngagementPredictionService:
    """
    LSTM/CNN engagement predictor.
    Falls back to heuristic sigmoid curve when model not trained.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = Path(model_path or MODEL_PATH)
        self._model = None          # PyTorch module
        self._scaler = None         # sklearn StandardScaler for features
        self._drift_buffer: List[float] = []
        self._load_model()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self._model is not None

    def predict_engagement_curve(
        self,
        words: List[Dict[str, Any]],
        audio_features: Optional[Dict] = None,
        duration: float = 30.0,
        resolution: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Predict viewer retention over time.

        Returns:
            {
              "curve":            [float]  # retention % at each second (0-100)
              "drop_off_points":  [float]  # seconds where retention drops >5%
              "hook_points":      [float]  # optimal hook insertion seconds
              "retention_score":  int      # mean retention 0-100
              "predicted_by":     str      # "lstm_cnn" | "heuristic"
            }
        """
        features = extract_time_series_features(words, audio_features, duration, resolution)

        if self._model is not None:
            try:
                curve = self._predict_with_model(features)
                method = "lstm_cnn"
            except Exception as e:
                logger.warning(f"[engagement] Model prediction failed: {e} — using heuristic")
                curve = self._heuristic_curve(features, duration, resolution)
                method = "heuristic"
        else:
            curve = self._heuristic_curve(features, duration, resolution)
            method = "heuristic"

        # Post-process
        curve = np.clip(curve, 0.0, 100.0).tolist()
        drop_off_points = self._find_drop_off_points(curve, resolution, threshold=5.0)
        hook_points = self._find_hook_insertion_points(curve, resolution)
        retention_score = int(np.mean(curve))

        return {
            "curve": [round(v, 1) for v in curve],
            "drop_off_points": drop_off_points,
            "hook_points": hook_points,
            "retention_score": retention_score,
            "predicted_by": method,
        }

    def train(
        self,
        samples: List[Dict[str, Any]],
        epochs: int = 50,
        lr: float = 1e-3,
    ) -> dict:
        """
        Train the LSTM/CNN model.

        Each sample must have:
            - words:           list of word dicts
            - audio_features:  dict (optional)
            - duration:        float (seconds)
            - retention_curve: list[float] (target — retention % per second)

        Returns training summary dict.
        """
        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset
            from sklearn.preprocessing import StandardScaler
        except ImportError as e:
            return {"status": "failed", "reason": f"Missing dependency: {e}"}

        if len(samples) < 10:
            return {"status": "skipped", "reason": f"need ≥10 samples, got {len(samples)}"}

        X_list, y_list = [], []
        for s in samples:
            try:
                dur = float(s.get("duration", 30.0))
                feats = extract_time_series_features(
                    s.get("words", []),
                    s.get("audio_features"),
                    duration=dur,
                )
                curve = s.get("retention_curve", [])
                if not curve:
                    continue
                # Pad/truncate curve to match T
                T = feats.shape[0]
                if len(curve) < T:
                    curve = curve + [curve[-1]] * (T - len(curve))
                curve = np.array(curve[:T], dtype=np.float32) / 100.0
                X_list.append(feats)
                y_list.append(curve)
            except Exception as e:
                logger.debug(f"[engagement] Bad sample: {e}")

        if len(X_list) < 5:
            return {"status": "skipped", "reason": "too many invalid samples"}

        # Pad to uniform length
        max_T = max(x.shape[0] for x in X_list)
        X_padded = np.zeros((len(X_list), max_T, 10), dtype=np.float32)
        y_padded = np.zeros((len(X_list), max_T), dtype=np.float32)
        for i, (x, y) in enumerate(zip(X_list, y_list)):
            T = x.shape[0]
            X_padded[i, :T] = x
            y_padded[i, :T] = y

        # Normalise features
        scaler = StandardScaler()
        shape = X_padded.shape
        X_flat = X_padded.reshape(-1, shape[-1])
        X_flat = scaler.fit_transform(X_flat).astype(np.float32)
        X_padded = X_flat.reshape(shape)

        X_tensor = torch.FloatTensor(X_padded)
        y_tensor = torch.FloatTensor(y_padded)

        # Split
        n_train = max(1, int(len(X_list) * 0.8))
        X_train, X_val = X_tensor[:n_train], X_tensor[n_train:]
        y_train, y_val = y_tensor[:n_train], y_tensor[n_train:]

        model = _make_model(n_features=10)
        if model is None:
            return {"status": "failed", "reason": "PyTorch unavailable — cannot build LSTM/CNN model"}
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        criterion = nn.MSELoss()

        train_ds = TensorDataset(X_train, y_train)
        loader = DataLoader(train_ds, batch_size=min(16, n_train), shuffle=True)

        logger.info(f"[engagement] Training on {n_train} samples for {epochs} epochs...")
        best_val_loss = float("inf")
        patience_count = 0

        for epoch in range(epochs):
            model.train()
            for xb, yb in loader:
                optimizer.zero_grad()
                pred = model(xb)
                loss = criterion(pred, yb)
                loss.backward()
                optimizer.step()

            if len(X_val) > 0:
                model.eval()
                with torch.no_grad():
                    val_pred = model(X_val)
                    val_loss = criterion(val_pred, y_val).item()
                if val_loss < best_val_loss - 0.001:
                    best_val_loss = val_loss
                    patience_count = 0
                else:
                    patience_count += 1
                    if patience_count >= 10:
                        logger.debug(f"[engagement] Early stop at epoch {epoch}")
                        break

        self._model = model
        self._scaler = scaler
        self._save_model()

        return {
            "status": "trained",
            "n_samples": n_train,
            "best_val_loss": best_val_loss,
            "epochs": epoch + 1,
        }

    def record_actual(self, predicted_retention: float, actual_retention: float) -> bool:
        """
        Record actual vs. predicted for drift detection.
        Returns True if retraining is recommended.
        """
        self._drift_buffer.append(abs(predicted_retention - actual_retention))
        if len(self._drift_buffer) > 100:
            self._drift_buffer = self._drift_buffer[-100:]

        if len(self._drift_buffer) >= 20:
            mean_error = float(np.mean(self._drift_buffer))
            if mean_error > DRIFT_THRESHOLD:
                logger.warning(
                    f"[engagement] Drift detected: MAE={mean_error:.1f} > "
                    f"threshold={DRIFT_THRESHOLD} — retraining recommended"
                )
                return True
        return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _predict_with_model(self, features: np.ndarray) -> np.ndarray:
        import torch

        T, F = features.shape
        if self._scaler is not None:
            features = self._scaler.transform(features).astype(np.float32)

        x = torch.FloatTensor(features).unsqueeze(0)  # (1, T, F)
        self._model.eval()
        with torch.no_grad():
            pred = self._model(x)[0]  # (T,)
        return pred.numpy() * 100.0

    def _heuristic_retention(self, duration_s: float, has_hook: bool, niche: str) -> float:
        """Retention estimate based on content characteristics."""
        base = 0.72 if has_hook else 0.55
        # Longer clips lose retention
        if duration_s > 45:
            base -= 0.10
        elif duration_s > 30:
            base -= 0.05
        # Insurance/finance niche has higher intent retention
        if niche in ("insurance", "finance", "mortgage", "legal", "seguros", "hipoteca"):
            base += 0.08
        return min(0.95, max(0.30, base))

    def _heuristic_curve(
        self,
        features: np.ndarray,
        duration: float,
        resolution: float,
        has_hook: bool = False,
        niche: str = "",
    ) -> np.ndarray:
        """
        Heuristic sigmoid retention curve based on audio energy and keyword density.
        No model required. Generally accurate for well-structured content.
        Uses dynamic retention base from _heuristic_retention().
        """
        T = features.shape[0]
        t = np.linspace(0, 1, T)

        # Dynamic base retention from content characteristics
        _retention_pct = self._heuristic_retention(duration, has_hook, niche) * 100.0
        # Base retention: starts at 100%, decays to _retention_pct at end
        base = 100.0 - (100.0 - _retention_pct) * t

        # Boost from hook quality in first 3s
        hook_boost = features[:, 9] * 20.0

        # Energy peaks add temporary boosts
        energy_boost = features[:, 7] * 8.0

        # Filler words drag down retention
        filler_drag = features[:, 4] * 10.0

        # Silence gaps further drag
        silence_drag = features[:, 5] * 8.0

        curve = base + hook_boost + energy_boost - filler_drag - silence_drag
        # Add smooth noise for realism
        rng = np.random.default_rng(42)
        curve += rng.normal(0, 1.5, T)
        return np.clip(curve, 5.0, 100.0)

    def _find_drop_off_points(
        self,
        curve: List[float],
        resolution: float,
        threshold: float = 5.0,
    ) -> List[float]:
        """Return timestamps where retention drops by > threshold% in one step."""
        points = []
        for i in range(1, len(curve)):
            drop = curve[i - 1] - curve[i]
            if drop > threshold:
                points.append(round(i * resolution, 1))
        return points

    def _find_hook_insertion_points(
        self,
        curve: List[float],
        resolution: float,
    ) -> List[float]:
        """Return timestamps just before significant drop-offs — ideal hook positions."""
        drops = self._find_drop_off_points(curve, resolution, threshold=7.0)
        # Suggest inserting hooks 1–2s before drop-off
        return [max(0.0, round(t - 1.5, 1)) for t in drops[:3]]

    def _load_model(self) -> None:
        if not self.model_path.exists():
            return
        try:
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
            self._scaler = data.get("scaler")
            # Load PyTorch state_dict into a fresh model instance
            state = data.get("state_dict")
            if state is not None:
                try:
                    import torch
                    model = LSTMCNNModel(n_features=10)
                    model.load_state_dict(state)
                    model.eval()
                    self._model = model
                except Exception as _te:
                    logger.warning(f"[engagement] state_dict load failed: {_te}")
            logger.info(f"[engagement] Model loaded from {self.model_path}")
        except Exception as e:
            logger.warning(f"[engagement] Failed to load model: {e}")

    def _save_model(self) -> None:
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        # Save state_dict (not nn.Module directly) to avoid local-class pickle issues
        state = None
        try:
            import torch
            if self._model is not None and hasattr(self._model, "state_dict"):
                state = self._model.state_dict()
        except Exception:
            pass
        with open(self.model_path, "wb") as f:
            pickle.dump({"state_dict": state, "scaler": self._scaler}, f)
        logger.info(f"[engagement] Model saved → {self.model_path}")


# ─────────────────────────────────────────────────────────────────────────────
#  PyTorch model — module-level so it can be pickled / torch.save'd
# ─────────────────────────────────────────────────────────────────────────────

try:
    import torch
    import torch.nn as nn

    class LSTMCNNModel(nn.Module):
        """
        1D-CNN (local patterns) + BiLSTM (temporal context) engagement predictor.
        Lightweight: <500K parameters. Module-level for pickle compatibility.
        """

        def __init__(self, n_features: int = 10):
            super().__init__()
            self.cnn = nn.Sequential(
                nn.Conv1d(n_features, 32, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Conv1d(32, 64, kernel_size=3, padding=1),
                nn.ReLU(),
            )
            self.lstm = nn.LSTM(
                input_size=64,
                hidden_size=64,
                num_layers=2,
                batch_first=True,
                bidirectional=True,
                dropout=0.2,
            )
            self.head = nn.Sequential(
                nn.Linear(128, 32),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(32, 1),
                nn.Sigmoid(),
            )

        def forward(self, x):
            x_t = x.permute(0, 2, 1)           # (B, F, T)
            cnn_out = self.cnn(x_t)             # (B, 64, T)
            cnn_out = cnn_out.permute(0, 2, 1)  # (B, T, 64)
            lstm_out, _ = self.lstm(cnn_out)    # (B, T, 128)
            return self.head(lstm_out).squeeze(-1)  # (B, T)

except ImportError:
    # PyTorch not available — training will fail gracefully
    class LSTMCNNModel:  # type: ignore[no-redef]
        def __init__(self, n_features: int = 10):
            pass


def _make_model(n_features: int = 10):
    """Instantiate LSTMCNNModel; returns None when torch is unavailable."""
    try:
        return LSTMCNNModel(n_features)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Singleton helper
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[EngagementPredictionService] = None


def get_engagement_predictor() -> EngagementPredictionService:
    global _instance
    if _instance is None:
        _instance = EngagementPredictionService()
    return _instance
