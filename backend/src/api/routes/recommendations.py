"""
Recommendation Engine API — ViraClip

Endpoints for personalized content recommendations, user profile
management, virality optimization tips, and performance prediction.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.recommendation_engine import get_recommendation_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["recommendations"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateProfileRequest(BaseModel):
    user_id: str
    initial_data: Optional[Dict[str, Any]] = None


class UpdateBehaviorRequest(BaseModel):
    user_id: str
    action: str            # clip_exported | effect_used | platform_selected
    metadata: Dict[str, Any] = {}


class ViralityTipsRequest(BaseModel):
    user_id: Optional[str] = None
    clip_data: Dict[str, Any]   # virality_score, niche, duration, has_hook


class PredictRequest(BaseModel):
    clip_features: Dict[str, Any]   # virality_score, niche, has_hook, duration


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/profile")
def create_profile(body: CreateProfileRequest):
    """
    Create or update a user's recommendation profile.

    Accepts optional `initial_data` with keys:
    - `niches` — list of niche strings
    - `duration` — preferred clip duration (seconds)
    - `effects` — list of favourite effect names
    - `platforms` — preferred platforms
    - `threshold` — minimum virality score (0-100)
    - `style` — `educational` | `entertaining` | `promotional`
    - `language` — ISO code (e.g. `en`)
    """
    engine = get_recommendation_engine()
    profile = engine.create_user_profile(body.user_id, body.initial_data)
    return {
        "status": "created",
        "profile": {
            "user_id": profile.user_id,
            "preferred_niches": profile.preferred_niches,
            "preferred_duration": profile.preferred_duration,
            "favorite_effects": profile.favorite_effects,
            "top_platforms": profile.top_platforms,
            "content_style": profile.content_style,
            "language_preference": profile.language_preference,
        },
    }


@router.post("/behavior")
def update_behavior(body: UpdateBehaviorRequest):
    """
    Record a user behaviour event to refine their recommendation profile.

    Supported `action` values:
    - `clip_exported` — pass `metadata.niche` and `metadata.duration`
    - `effect_used` — pass `metadata.effect`
    - `platform_selected` — pass `metadata.platform`
    """
    engine = get_recommendation_engine()
    engine.update_profile_from_behavior(body.user_id, body.action, body.metadata)
    return {"status": "updated", "user_id": body.user_id, "action": body.action}


@router.get("/user/{user_id}")
def get_recommendations(user_id: str, current_niche: Optional[str] = None):
    """
    Get up to 5 personalised content recommendations for a user.

    Pass `current_niche` query-param for context-aware hook suggestions.
    Returns recommendations sorted by confidence descending, each with
    a type (niche / style / effect / time / music / caption / hook),
    a description, confidence score, and an action string.
    """
    engine = get_recommendation_engine()
    context = {"current_niche": current_niche} if current_niche else None
    recs = engine.get_recommendations(user_id, context)
    return {
        "status": "success",
        "user_id": user_id,
        "count": len(recs),
        "recommendations": [
            {
                "recommendation_id": r.recommendation_id,
                "type": r.type,
                "title": r.title,
                "description": r.description,
                "confidence": round(r.confidence, 3),
                "action": r.action,
                "metadata": r.metadata,
            }
            for r in recs
        ],
    }


@router.post("/virality-tips")
def virality_tips(body: ViralityTipsRequest):
    """
    Get actionable tips to improve a clip's virality score.

    `clip_data` should include:
    - `virality_score` (0-100)
    - `niche` (e.g. `gaming`, `finance`)
    - `duration` (seconds)
    - `has_hook` (bool)
    """
    if not body.clip_data:
        raise HTTPException(status_code=400, detail="clip_data must not be empty")
    engine = get_recommendation_engine()
    tips = engine.get_virality_optimization_tips(
        body.user_id or "anonymous", body.clip_data
    )
    return {"status": "success", "count": len(tips), "tips": tips}


@router.post("/predict-performance")
def predict_performance(body: PredictRequest):
    """
    Predict clip performance based on its features.

    Returns:
    - **predicted_views_range** — (low, high) estimate
    - **virality_tier** — `high` / `medium` / `low`
    - **optimization_potential** — how much room to improve (0-100)
    - **estimated_engagement_rate** — rough % estimate
    """
    if not body.clip_features:
        raise HTTPException(status_code=400, detail="clip_features must not be empty")
    engine = get_recommendation_engine()
    result = engine.predict_performance(body.clip_features)
    return {"status": "success", "prediction": result}
