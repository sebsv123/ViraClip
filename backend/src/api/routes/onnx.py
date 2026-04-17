"""
ONNX Inference API Routes
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.onnx_inference_service import get_onnx_service

router = APIRouter(prefix="/onnx", tags=["ONNX Inference"])


class ViralityRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    duration: float = Field(15.0, gt=0, le=300)
    audio_features: Optional[Dict[str, Any]] = None


class EngagementRequest(BaseModel):
    words: List[Dict[str, Any]] = Field(..., min_length=1)
    audio_features: Optional[Dict[str, Any]] = None
    duration: float = Field(15.0, gt=0, le=300)
    resolution: str = "1080x1920"


@router.get("/capabilities")
async def get_capabilities() -> Dict[str, Any]:
    """Report which ONNX models are loaded and available."""
    svc = get_onnx_service()
    return svc.get_capabilities()


@router.post("/predict/virality")
async def predict_virality(body: ViralityRequest) -> Dict[str, Any]:
    """Predict virality score (0-100) using fast ONNX inference."""
    svc = get_onnx_service()
    try:
        score = svc.predict_virality(
            transcript=body.transcript,
            duration=body.duration,
            audio_features=body.audio_features,
        )
        return {
            "transcript_length": len(body.transcript),
            "duration": body.duration,
            "virality_score": score,
            "model": "onnx" if svc.is_viral_scorer_available() else "fallback",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict/engagement")
async def predict_engagement(body: EngagementRequest) -> Dict[str, Any]:
    """Predict viewer engagement curve using ONNX engagement model."""
    svc = get_onnx_service()
    try:
        result = svc.predict_engagement(
            words=body.words,
            audio_features=body.audio_features,
            duration=body.duration,
            resolution=body.resolution,
        )
        return {
            "word_count": len(body.words),
            "duration": body.duration,
            "model": "onnx" if svc.is_engagement_available() else "fallback",
            **result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
