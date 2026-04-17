"""
Engagement Prediction API — ViraClip

Endpoints for predicting viewer retention curves, finding drop-off
points, training the LSTM/CNN model, and recording actual outcomes
for drift detection.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.engagement_prediction_service import get_engagement_predictor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/engagement", tags=["engagement"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class PredictCurveRequest(BaseModel):
    words: List[Dict[str, Any]] = []
    audio_features: Optional[Dict[str, Any]] = None
    duration: float = 30.0
    resolution: float = 1.0


class TrainRequest(BaseModel):
    samples: List[Dict[str, Any]]   # each: words, audio_features, duration, retention_curve
    epochs: int = 50
    learning_rate: float = 1e-3


class RecordActualRequest(BaseModel):
    predicted_retention: float
    actual_retention: float


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/predict")
def predict_engagement(body: PredictCurveRequest):
    """
    Predict the viewer retention curve for a clip.

    Pass `words` (word-level transcript with `start`, `end`, `confidence`),
    optional `audio_features` dict, `duration` in seconds, and `resolution`
    (time-step size). Returns:
    - **curve** — retention % at each time-step (0-100)
    - **drop_off_points** — seconds where retention drops >5%
    - **hook_points** — optimal hook insertion timestamps
    - **retention_score** — mean retention (0-100)
    - **predicted_by** — `lstm_cnn` or `heuristic`
    """
    if body.duration <= 0:
        raise HTTPException(status_code=400, detail="duration must be > 0")
    if body.resolution <= 0:
        raise HTTPException(status_code=400, detail="resolution must be > 0")

    predictor = get_engagement_predictor()
    try:
        result = predictor.predict_engagement_curve(
            words=body.words,
            audio_features=body.audio_features,
            duration=body.duration,
            resolution=body.resolution,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", **result}


@router.post("/train")
def train_model(body: TrainRequest):
    """
    Train the LSTM/CNN engagement model with real retention data.

    Each sample must contain:
    - `words` — word-level transcript
    - `audio_features` — dict (optional)
    - `duration` — float (seconds)
    - `retention_curve` — list of float (actual retention % per second)

    Requires at least 10 samples. Returns training summary.
    """
    if len(body.samples) < 1:
        raise HTTPException(status_code=400, detail="samples must not be empty")

    predictor = get_engagement_predictor()
    try:
        summary = predictor.train(
            samples=body.samples,
            epochs=body.epochs,
            lr=body.learning_rate,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if summary.get("status") == "failed":
        raise HTTPException(status_code=422, detail=summary.get("reason", "Training failed"))

    return {"status": summary.get("status", "trained"), "summary": summary}


@router.post("/record-actual")
def record_actual(body: RecordActualRequest):
    """
    Report actual vs. predicted retention to enable drift detection.
    Returns `retrain_recommended: true` when the model's error has
    drifted beyond the acceptable threshold over the last 20+ samples.
    """
    predictor = get_engagement_predictor()
    retrain = predictor.record_actual(body.predicted_retention, body.actual_retention)
    return {
        "status": "recorded",
        "retrain_recommended": retrain,
    }


@router.get("/status")
def get_status():
    """Check whether the LSTM/CNN model is loaded or heuristic fallback is active."""
    predictor = get_engagement_predictor()
    return {
        "model_available": predictor.is_available(),
        "prediction_mode": "lstm_cnn" if predictor.is_available() else "heuristic",
    }
