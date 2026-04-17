"""
onnx_inference_service.py — Phase 8.4
=======================================
ONNX Runtime inference service for mobile/edge deployment of ViraClip models.

Exports and runs:
  - ViralScorerService MLP → ONNX (scikit-learn via skl2onnx)
  - EngagementPredictionService LSTM/CNN → ONNX (PyTorch torch.onnx)

Benefits:
  - 3-5× faster CPU inference than sklearn/PyTorch forward pass
  - Single binary per model (~2-5MB) — deployable to mobile/edge
  - No Python ML framework needed for inference (ONNX Runtime only)
  - Enables CoreML / TFLite conversion for iOS/Android

Usage:
    from services.onnx_inference_service import OnnxInferenceService

    svc = OnnxInferenceService()
    score = svc.predict_virality("Amazing secret nobody knows...", duration=22.0)
    result = svc.predict_engagement(words=[...], duration=30.0)

Export:
    python /app/scripts/export_to_onnx.py
"""

import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

import numpy as np

logger = logging.getLogger(__name__)

ONNX_DIR = Path(os.getenv("ONNX_MODEL_DIR", "/app/models/onnx"))
VIRAL_SCORER_ONNX = ONNX_DIR / "viral_scorer.onnx"
ENGAGEMENT_ONNX = ONNX_DIR / "engagement_predictor.onnx"


# ─────────────────────────────────────────────────────────────────────────────
#  ONNX exporter
# ─────────────────────────────────────────────────────────────────────────────

def export_viral_scorer_to_onnx(
    model_pkl_path: Optional[Path] = None,
    onnx_output_path: Optional[Path] = None,
) -> bool:
    """
    Export ViralScorerService sklearn Pipeline to ONNX.
    Requires skl2onnx: pip install skl2onnx

    Returns True on success.
    """
    try:
        import pickle
        from services.viral_scorer_service import MODEL_PATH

        pkl_path = Path(model_pkl_path or MODEL_PATH)
        out_path = Path(onnx_output_path or VIRAL_SCORER_ONNX)

        if not pkl_path.exists():
            logger.warning(f"[onnx] viral_scorer.pkl not found at {pkl_path}")
            return False

        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
        model = data["model"]

        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType

        # Input: (N, n_features) float32
        # 3 structural + 10 viral keywords + 15 audio (6 scalars + 8 mfcc + 1 pause) = 28
        n_features = 28  # see viral_scorer_service extract_features
        initial_types = [("float_input", FloatTensorType([None, n_features]))]
        onnx_model = convert_sklearn(model, initial_types=initial_types)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(onnx_model.SerializeToString())

        size_kb = out_path.stat().st_size // 1024
        logger.info(f"[onnx] viral_scorer exported → {out_path} ({size_kb}KB)")
        return True

    except ImportError as e:
        logger.warning(f"[onnx] Export requires skl2onnx: {e}")
        return False
    except Exception as e:
        logger.warning(f"[onnx] viral_scorer export failed: {e}")
        return False


def export_engagement_predictor_to_onnx(
    model_pkl_path: Optional[Path] = None,
    onnx_output_path: Optional[Path] = None,
    sequence_length: int = 60,
) -> bool:
    """
    Export EngagementPredictionService LSTM/CNN to ONNX.
    Requires PyTorch.

    Args:
        sequence_length: Fixed input sequence length for export (default 60s clips)

    Returns True on success.
    """
    try:
        import pickle
        import torch
        from services.engagement_prediction_service import MODEL_PATH as ENG_PATH

        pkl_path = Path(model_pkl_path or ENG_PATH)
        out_path = Path(onnx_output_path or ENGAGEMENT_ONNX)

        if not pkl_path.exists():
            logger.warning(f"[onnx] engagement_predictor.pkl not found at {pkl_path}")
            return False

        with open(pkl_path, "rb") as f:
            data = pickle.load(f)

        # Engagement predictor is saved as state_dict (not full nn.Module)
        from services.engagement_prediction_service import LSTMCNNModel
        state = data.get("state_dict")
        if state is None:
            logger.warning("[onnx] engagement pickle has no state_dict key")
            return False
        model = LSTMCNNModel(n_features=10)
        model.load_state_dict(state)

        if not hasattr(model, "forward"):
            logger.warning("[onnx] engagement model is not a nn.Module — skipping")
            return False

        model.eval()
        dummy_input = torch.zeros(1, sequence_length, 10, dtype=torch.float32)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        torch.onnx.export(
            model,
            dummy_input,
            str(out_path),
            input_names=["features"],
            output_names=["retention"],
            dynamic_axes={"features": {1: "sequence_length"}},
            opset_version=17,
            verbose=False,
        )

        size_kb = out_path.stat().st_size // 1024
        logger.info(f"[onnx] engagement_predictor exported → {out_path} ({size_kb}KB)")
        return True

    except ImportError as e:
        logger.warning(f"[onnx] PyTorch required for engagement export: {e}")
        return False
    except Exception as e:
        logger.warning(f"[onnx] engagement export failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  OnnxInferenceService — fast CPU inference via ONNX Runtime
# ─────────────────────────────────────────────────────────────────────────────

class OnnxInferenceService:
    """
    Drop-in replacement for ViralScorerService + EngagementPredictionService
    using ONNX Runtime for faster CPU inference.

    3-5× faster than sklearn/PyTorch on typical hardware.
    ~2MB memory footprint (vs 50-200MB for full ML frameworks).
    """

    def __init__(self):
        self._viral_session = None
        self._engagement_session = None
        self._engagement_scaler = None
        self._load_sessions()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_viral_scorer_available(self) -> bool:
        return self._viral_session is not None

    def is_engagement_available(self) -> bool:
        return self._engagement_session is not None

    def predict_virality(
        self,
        transcript: str,
        duration: float = 15.0,
        audio_features: Optional[Dict] = None,
    ) -> int:
        """
        Predict virality score (0-100) using ONNX Runtime.
        Falls back to ViralScorerService if ONNX not available.
        """
        if self._viral_session is None:
            return self._fallback_virality(transcript, duration, audio_features)

        try:
            from services.viral_scorer_service import extract_features
            features = extract_features(transcript, duration, audio_features)
            inp = features.reshape(1, -1).astype(np.float32)
            output = self._viral_session.run(None, {"float_input": inp})
            score = float(output[0][0])
            return min(100, max(0, int(round(score))))
        except Exception as e:
            logger.warning(f"[onnx] Virality inference failed: {e}")
            return self._fallback_virality(transcript, duration, audio_features)

    def predict_engagement(
        self,
        words: List[Dict[str, Any]],
        audio_features: Optional[Dict] = None,
        duration: float = 30.0,
        resolution: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Predict engagement curve using ONNX Runtime.
        Falls back to EngagementPredictionService if ONNX not available.
        """
        if self._engagement_session is None:
            return self._fallback_engagement(words, audio_features, duration, resolution)

        try:
            from services.engagement_prediction_service import extract_time_series_features
            import numpy as np

            features = extract_time_series_features(words, audio_features, duration, resolution)
            T, F = features.shape

            if self._engagement_scaler is not None:
                features = self._engagement_scaler.transform(features).astype(np.float32)

            inp = features.reshape(1, T, F).astype(np.float32)
            output = self._engagement_session.run(None, {"features": inp})
            curve = (output[0][0] * 100.0).tolist()
            curve = [max(5.0, min(100.0, v)) for v in curve]

            from services.engagement_prediction_service import EngagementPredictionService
            _svc = EngagementPredictionService.__new__(EngagementPredictionService)
            drops = _svc._find_drop_off_points(curve, resolution)
            hooks = _svc._find_hook_insertion_points(curve, resolution)

            return {
                "curve": [round(v, 1) for v in curve],
                "drop_off_points": drops,
                "hook_points": hooks,
                "retention_score": int(np.mean(curve)),
                "predicted_by": "onnx",
            }
        except Exception as e:
            logger.warning(f"[onnx] Engagement inference failed: {e}")
            return self._fallback_engagement(words, audio_features, duration, resolution)

    def get_capabilities(self) -> Dict[str, Any]:
        """Report which ONNX models are loaded."""
        return {
            "viral_scorer_onnx": self.is_viral_scorer_available(),
            "engagement_onnx": self.is_engagement_available(),
            "onnx_dir": str(ONNX_DIR),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_sessions(self) -> None:
        try:
            import onnxruntime as ort
            try:
                from gpu_utils import onnx_providers
                providers = onnx_providers()
            except ImportError:
                providers = ["CPUExecutionProvider"]

            if VIRAL_SCORER_ONNX.exists():
                self._viral_session = ort.InferenceSession(
                    str(VIRAL_SCORER_ONNX),
                    providers=providers,
                )
                logger.info(f"[onnx] viral_scorer loaded with {providers[0]}")

            if ENGAGEMENT_ONNX.exists():
                self._engagement_session = ort.InferenceSession(
                    str(ENGAGEMENT_ONNX),
                    providers=providers,
                )
                # Load scaler
                try:
                    import pickle
                    with open(Path(os.getenv("ENGAGEMENT_MODEL", "/app/models/engagement_predictor.pkl")), "rb") as f:
                        data = pickle.load(f)
                    self._engagement_scaler = data.get("scaler")
                except Exception:
                    pass
                logger.info(f"[onnx] engagement_predictor loaded")

        except ImportError:
            logger.debug("[onnx] onnxruntime not installed — ONNX inference unavailable")
        except Exception as e:
            logger.warning(f"[onnx] Session load failed: {e}")

    def _fallback_virality(self, transcript, duration, audio_features) -> int:
        try:
            from services.viral_scorer_service import get_viral_scorer
            return get_viral_scorer().score_segment(transcript, duration, audio_features)
        except Exception:
            return 50

    def _fallback_engagement(self, words, audio_features, duration, resolution) -> Dict[str, Any]:
        try:
            from services.engagement_prediction_service import get_engagement_predictor
            return get_engagement_predictor().predict_engagement_curve(
                words, audio_features, duration, resolution
            )
        except Exception:
            return {"curve": [], "drop_off_points": [], "hook_points": [],
                    "retention_score": 50, "predicted_by": "unavailable"}


# ─────────────────────────────────────────────────────────────────────────────
#  Singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[OnnxInferenceService] = None


def get_onnx_service() -> OnnxInferenceService:
    global _instance
    if _instance is None:
        _instance = OnnxInferenceService()
    return _instance
