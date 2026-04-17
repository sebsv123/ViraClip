"""
Social Media Integration API — ViraClip

Endpoints for connecting social accounts via OAuth, publishing clips,
scheduling posts, and viewing publishing history.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.social_integration import (
    SocialPlatform,
    get_social_media_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/social-media", tags=["social-media"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ConnectRequest(BaseModel):
    user_id: str
    platform: str
    auth_code: str


class PublishRequest(BaseModel):
    account_id: str
    clip_path: str
    caption: str
    hashtags: List[str]
    options: Optional[Dict[str, Any]] = None


class ScheduleRequest(BaseModel):
    account_id: str
    clip_path: str
    caption: str
    hashtags: List[str]
    schedule_time: str          # ISO datetime
    options: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_platform(value: str) -> SocialPlatform:
    try:
        return SocialPlatform(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platform '{value}'. Valid: {[p.value for p in SocialPlatform]}",
        )


def _fmt_result(r) -> Dict[str, Any]:
    return {
        "success": r.success,
        "platform": r.platform.value,
        "post_id": r.post_id,
        "post_url": r.post_url,
        "error_message": r.error_message,
        "published_at": r.published_at,
        "engagement_prediction": r.engagement_prediction,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/accounts/connect")
async def connect_account(body: ConnectRequest):
    """
    Connect a social media account via OAuth.

    `auth_code` is the OAuth authorization code received after the user
    authorises ViraClip on the platform. Returns the new account record
    or 400 if the OAuth exchange fails.
    """
    platform = _parse_platform(body.platform)
    svc = get_social_media_service()
    account = await svc.connect_account(body.user_id, platform, body.auth_code)
    if account is None:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect {body.platform} account — OAuth exchange returned no tokens",
        )
    return {
        "status": "connected",
        "account": {
            "account_id": account.account_id,
            "user_id": account.user_id,
            "platform": account.platform.value,
            "account_name": account.account_name,
            "is_active": account.is_active,
        },
    }


@router.get("/accounts/{user_id}")
def list_accounts(user_id: str):
    """List all connected social media accounts for a user."""
    svc = get_social_media_service()
    accounts = svc.get_user_accounts(user_id)
    return {"count": len(accounts), "accounts": accounts}


@router.delete("/accounts/{account_id}/disconnect")
async def disconnect_account(account_id: str):
    """Disconnect a social media account and revoke its token."""
    svc = get_social_media_service()
    success = await svc.disconnect_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    return {"status": "disconnected", "account_id": account_id}


@router.post("/publish")
async def publish_clip(body: PublishRequest):
    """
    Immediately publish a clip to a connected social media account.

    Returns `success`, `post_id`, `post_url`, and `engagement_prediction`.
    """
    if not body.caption.strip():
        raise HTTPException(status_code=400, detail="caption must not be empty")
    svc = get_social_media_service()
    try:
        result = await svc.publish_clip(
            body.account_id,
            Path(body.clip_path),
            body.caption,
            body.hashtags,
            body.options,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error_message or "Publish failed")
    return {"status": "published", "result": _fmt_result(result)}


@router.post("/schedule")
async def schedule_post(body: ScheduleRequest):
    """
    Schedule a clip to be published at a future time.

    `schedule_time` must be an ISO 8601 datetime string.
    """
    if not body.caption.strip():
        raise HTTPException(status_code=400, detail="caption must not be empty")
    if not body.schedule_time.strip():
        raise HTTPException(status_code=400, detail="schedule_time must not be empty")
    svc = get_social_media_service()
    try:
        scheduled = await svc.schedule_post(
            body.account_id,
            Path(body.clip_path),
            body.caption,
            body.hashtags,
            body.schedule_time,
            body.options,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "scheduled", "schedule": scheduled}


@router.get("/history/{user_id}")
def get_history(user_id: str, platform: Optional[str] = None, limit: int = 50):
    """Get publishing history for a user, optionally filtered by `platform`."""
    platform_type = _parse_platform(platform) if platform else None
    svc = get_social_media_service()
    history = svc.get_publishing_history(user_id, platform_type, limit)
    return {"count": len(history), "history": history}


@router.get("/platforms")
def list_platforms():
    """List all supported social media platforms."""
    return {"platforms": [p.value for p in SocialPlatform]}
