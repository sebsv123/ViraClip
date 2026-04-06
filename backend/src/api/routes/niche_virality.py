"""Niche-Aware Virality Scoring API routes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/niche-virality", tags=["niche-virality"])


class NicheScoreRequest(BaseModel):
    niche: str
    base_virality_score: float
    hook_score: float = 50.0
    pacing_score: float = 50.0
    emotion_score: float = 50.0
    audio_energy: float = 0.5
    clip_duration: float = 45.0


class RetrainRequest(BaseModel):
    niche: str
    performance_events: List[Dict[str, Any]]


@router.post("/score")
def score_for_niche(body: NicheScoreRequest):
    """
    Compute a niche-calibrated virality score blending base score
    with per-niche feature weights and duration sweet spots.
    """
    from ...services.niche_virality_service import score_for_niche as _score
    result = _score(
        niche=body.niche,
        base_virality_score=body.base_virality_score,
        hook_score=body.hook_score,
        pacing_score=body.pacing_score,
        emotion_score=body.emotion_score,
        audio_energy=body.audio_energy,
        clip_duration=body.clip_duration,
    )
    from ...services.niche_virality_service import get_niche_recommendations
    recs = get_niche_recommendations(body.niche, result)
    return {
        "niche_score": result.niche_score,
        "base_score": result.base_score,
        "niche": result.niche,
        "duration_ok": result.duration_ok,
        "recommended_duration_range": result.recommended_duration_range,
        "feature_contributions": result.feature_contributions,
        "weights_used": result.weights_used,
        "retrained_from_data": result.retrained_from_data,
        "recommendations": recs,
    }


@router.post("/retrain")
def retrain_niche_model(body: RetrainRequest):
    """
    Retrain niche-specific feature weights using real performance data.
    Requires at least 10 events with feature fields present.
    """
    if len(body.performance_events) < 10:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 10 events, got {len(body.performance_events)}"
        )
    from ...services.niche_virality_service import retrain_niche_weights
    new_weights = retrain_niche_weights(body.niche, body.performance_events)
    return {"niche": body.niche, "new_weights": new_weights, "status": "retrained"}


@router.get("/weights/{niche}")
def get_weights(niche: str):
    """Return current feature weights for a niche."""
    from ...services.niche_virality_service import get_weights_for_niche
    return {"niche": niche, "weights": get_weights_for_niche(niche)}


@router.get("/niches")
def list_niches():
    """List all supported niches with their duration sweet spots."""
    from ...services.niche_virality_service import _DEFAULT_WEIGHTS, _DURATION_SWEET_SPOTS
    return {
        "niches": [
            {
                "niche": k,
                "duration_range_seconds": _DURATION_SWEET_SPOTS.get(k, (20, 75)),
            }
            for k in _DEFAULT_WEIGHTS
        ]
    }
