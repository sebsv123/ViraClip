"""
Gamification API — ViraClip

Endpoints for points, levels, achievements, badges, streaks, and leaderboards.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.gamification_service import (
    get_gamification_service,
    record_user_activity,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gamification", tags=["gamification"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class RecordActivityRequest(BaseModel):
    activity_type: str               # clip_created | video_processed | clip_exported | collaboration | feedback_submitted
    metadata: Dict[str, Any] = {}


# ------------------------------------------------------------------
# Profile & progression
# ------------------------------------------------------------------

@router.get("/profile")
async def get_profile(request: Request):
    """
    Get the current user's gamification profile: points, level, rank,
    streak, unlocked features, and level-up progress.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_gamification_service()
    profile = svc.get_profile(user_id)
    return {"status": "success", "profile": profile}


@router.get("/profile/{user_id}")
async def get_profile_by_id(user_id: str):
    """Get the gamification profile for a specific user (admin / public leaderboard view)."""
    svc = get_gamification_service()
    profile = svc.get_profile(user_id)
    return {"status": "success", "profile": profile}


@router.post("/activity")
async def record_activity(request: Request, body: RecordActivityRequest):
    """
    Record a user activity and automatically check / award achievements.
    Returns a list of newly unlocked achievements.

    **activity_type** values:
    - `clip_created` — metadata: `virality_score`, `quality_score`, `niche`
    - `video_processed`
    - `clip_exported` — metadata: `platform`
    - `collaboration`
    - `feedback_submitted`
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    try:
        new_achievements = await record_user_activity(
            user_id=user_id,
            activity_type=body.activity_type,
            metadata=body.metadata,
        )
        return {
            "status": "recorded",
            "new_achievements": [
                {
                    "id": a.achievement_id,
                    "name": a.name,
                    "description": a.description,
                    "icon": a.icon,
                    "points": a.points,
                    "rarity": a.rarity,
                }
                for a in new_achievements
            ],
            "achievements_unlocked": len(new_achievements),
        }
    except Exception as e:
        logger.error(f"[Gamification] record_activity failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Achievements
# ------------------------------------------------------------------

@router.get("/achievements")
async def get_achievements(request: Request):
    """
    Get all achievements with earned/unearned status for the current user.
    Each entry includes name, description, points, rarity, and criteria.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_gamification_service()
    achievements = svc.get_achievements(user_id)
    earned = [a for a in achievements if a["earned"]]
    return {
        "status": "success",
        "total": len(achievements),
        "earned_count": len(earned),
        "achievements": achievements,
    }


# ------------------------------------------------------------------
# Leaderboard
# ------------------------------------------------------------------

@router.get("/leaderboard")
def get_leaderboard(limit: int = 10):
    """Top users ranked by total points. Returns rank, user_id, points, level, and rank tier."""
    svc = get_gamification_service()
    board = svc.get_leaderboard(limit=limit)
    return {"status": "success", "count": len(board), "leaderboard": board}
