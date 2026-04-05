"""
ML Virality Predictor API — ViraClip

Endpoints for predicting clip virality using ML feature weights,
training the model with real performance data, and inspecting model stats.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.ml_virality_predictor import (
    MLFeatureSet,
    get_ml_predictor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/virality/ml", tags=["virality-ml"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class PredictRequest(BaseModel):
    clip_data: Dict[str, Any] = {}
    transcript: str = ""
    audio_analysis: Optional[Dict[str, Any]] = None
    visual_analysis: Optional[Dict[str, Any]] = None


class TrainRequest(BaseModel):
    clip_data: Dict[str, Any] = {}
    transcript: str = ""
    audio_analysis: Optional[Dict[str, Any]] = None
    visual_analysis: Optional[Dict[str, Any]] = None
    actual_virality_score: float


class ExtractFeaturesRequest(BaseModel):
    clip_data: Dict[str, Any] = {}
    transcript: str = ""
    audio_analysis: Optional[Dict[str, Any]] = None
    visual_analysis: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/predict")
def predict_virality(body: PredictRequest):
    """
    Predict the virality score for a clip using the ML model.

    Pass clip metadata, transcript, and optionally audio/visual analysis.
    Returns `predicted_score` (0-100), `confidence`, top-5 `feature_importance`,
    and an actionable `recommendation`.
    """
    predictor = get_ml_predictor()
    try:
        features = predictor.extract_features(
            clip_data=body.clip_data,
            transcript=body.transcript,
            audio_analysis=body.audio_analysis,
            visual_analysis=body.visual_analysis,
        )
        prediction = predictor.predict_virality(features)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "predicted_score": round(prediction.predicted_score, 2),
        "confidence": round(prediction.confidence, 3),
        "feature_importance": {
            k: round(v, 4) for k, v in prediction.feature_importance.items()
        },
        "model_version": prediction.model_version,
        "prediction_time": prediction.prediction_time,
        "recommendation": prediction.recommendation,
    }


@router.post("/features")
def extract_features(body: ExtractFeaturesRequest):
    """
    Extract the ML feature vector from clip data without running the prediction.
    Useful for debugging or inspecting what features the model will use.
    """
    predictor = get_ml_predictor()
    try:
        features = predictor.extract_features(
            clip_data=body.clip_data,
            transcript=body.transcript,
            audio_analysis=body.audio_analysis,
            visual_analysis=body.visual_analysis,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "features": predictor._features_to_vector(features),
    }


@router.post("/train")
def train_model(body: TrainRequest):
    """
    Submit a real-world performance sample to improve the model's weights.

    Call this once you have actual engagement data for a clip that was
    previously predicted. The model re-weights every 100 samples.
    """
    if not (0 <= body.actual_virality_score <= 100):
        raise HTTPException(
            status_code=400,
            detail="actual_virality_score must be between 0 and 100",
        )

    predictor = get_ml_predictor()
    try:
        features = predictor.extract_features(
            clip_data=body.clip_data,
            transcript=body.transcript,
            audio_analysis=body.audio_analysis,
            visual_analysis=body.visual_analysis,
        )
        predictor.train(features, body.actual_virality_score)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    stats = predictor.get_model_stats()
    return {
        "status": "trained",
        "training_samples": stats["training_samples"],
        "accuracy_estimate": round(stats["accuracy_estimate"], 1),
    }


@router.get("/stats")
def get_model_stats():
    """
    Get current model metadata: version, training sample count,
    feature weights, and estimated accuracy.
    """
    predictor = get_ml_predictor()
    stats = predictor.get_model_stats()
    return {"status": "success", "model": stats}
