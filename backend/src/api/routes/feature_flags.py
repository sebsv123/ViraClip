"""
Feature Flags API — ViraClip

Endpoints for managing feature flags: creating, toggling, updating
rollout percentages, and checking flag status per user.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.feature_flags import (
    FeatureFlagManager,
    RolloutStrategy,
    get_feature_flag_manager,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateFlagRequest(BaseModel):
    name: str
    enabled: bool = False
    strategy: str = "all_users"         # all_users | percentage | user_list | gradual | canary
    rollout_percentage: int = 0
    allowed_users: List[str] = []
    metadata: Dict[str, Any] = {}


class UpdateRolloutRequest(BaseModel):
    percentage: int


class UserFlagRequest(BaseModel):
    user_id: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_strategy(value: str) -> RolloutStrategy:
    try:
        return RolloutStrategy(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid strategy '{value}'. Choose: {[s.value for s in RolloutStrategy]}",
        )


def _flag_not_found(name: str):
    raise HTTPException(status_code=404, detail=f"Feature flag '{name}' not found")


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------

@router.post("")
def create_flag(body: CreateFlagRequest):
    """Create a new feature flag."""
    mgr = get_feature_flag_manager()
    if body.name in mgr.flags:
        raise HTTPException(status_code=409, detail=f"Flag '{body.name}' already exists")

    flag = mgr.create_flag(
        name=body.name,
        enabled=body.enabled,
        strategy=_parse_strategy(body.strategy),
        rollout_percentage=body.rollout_percentage,
        allowed_users=body.allowed_users,
        metadata=body.metadata,
    )
    return {"status": "created", "flag": mgr.get_flag_status(flag.name)}


@router.get("")
def list_flags():
    """List all feature flags and their current configuration."""
    mgr = get_feature_flag_manager()
    return {"status": "success", "flags": mgr.get_all_flags()}


@router.get("/{flag_name}")
def get_flag(flag_name: str):
    """Get configuration and status of a single feature flag."""
    mgr = get_feature_flag_manager()
    status = mgr.get_flag_status(flag_name)
    if status is None:
        _flag_not_found(flag_name)
    return {"status": "success", "flag": status}


@router.delete("/{flag_name}")
def delete_flag(flag_name: str):
    """Delete a feature flag."""
    mgr = get_feature_flag_manager()
    success = mgr.delete_flag(flag_name)
    if not success:
        _flag_not_found(flag_name)
    return {"status": "deleted", "flag_name": flag_name}


# ------------------------------------------------------------------
# Toggle & rollout
# ------------------------------------------------------------------

@router.post("/{flag_name}/toggle")
def toggle_flag(flag_name: str):
    """Toggle a feature flag on or off."""
    mgr = get_feature_flag_manager()
    success = mgr.toggle_flag(flag_name)
    if not success:
        _flag_not_found(flag_name)
    return {"status": "toggled", "flag": mgr.get_flag_status(flag_name)}


@router.patch("/{flag_name}/rollout")
def update_rollout(flag_name: str, body: UpdateRolloutRequest):
    """Update the rollout percentage for a flag (0–100)."""
    if not (0 <= body.percentage <= 100):
        raise HTTPException(status_code=400, detail="percentage must be 0–100")
    mgr = get_feature_flag_manager()
    success = mgr.update_rollout(flag_name, body.percentage)
    if not success:
        _flag_not_found(flag_name)
    return {"status": "updated", "flag": mgr.get_flag_status(flag_name)}


# ------------------------------------------------------------------
# Per-user overrides
# ------------------------------------------------------------------

@router.post("/{flag_name}/enable-user")
def enable_for_user(flag_name: str, body: UserFlagRequest):
    """Add a user to the allow-list for a flag (overrides percentage strategy)."""
    mgr = get_feature_flag_manager()
    success = mgr.enable_for_user(flag_name, body.user_id)
    if not success:
        _flag_not_found(flag_name)
    return {"status": "enabled", "flag_name": flag_name, "user_id": body.user_id}


@router.post("/{flag_name}/disable-user")
def disable_for_user(flag_name: str, body: UserFlagRequest):
    """Add a user to the block-list for a flag."""
    mgr = get_feature_flag_manager()
    success = mgr.disable_for_user(flag_name, body.user_id)
    if not success:
        _flag_not_found(flag_name)
    return {"status": "disabled", "flag_name": flag_name, "user_id": body.user_id}


# ------------------------------------------------------------------
# Check
# ------------------------------------------------------------------

@router.get("/{flag_name}/check")
def check_flag(flag_name: str, request: Request, user_id: Optional[str] = None):
    """
    Check if a feature flag is enabled for a given user.
    If `user_id` is not provided, the current authenticated user is used.
    """
    mgr = get_feature_flag_manager()
    auth_user = getattr(request.state, "user", None)
    uid = user_id or (auth_user.id if auth_user else None)

    enabled = mgr.is_enabled(flag_name, uid)
    return {"flag_name": flag_name, "user_id": uid, "enabled": enabled}


@router.get("/strategies/list")
def list_strategies():
    """List all available rollout strategies."""
    return {"strategies": [s.value for s in RolloutStrategy]}
