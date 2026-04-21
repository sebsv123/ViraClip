"""
Social Auth API Routes — OAuth Endpoints for TikTok, Instagram, YouTube
========================================================================

FastAPI routes for OAuth flows:
  - GET /api/v1/social/auth/{platform}/url      → Generate auth URL
  - GET /api/v1/social/auth/{platform}/callback → OAuth callback
  - DELETE /api/v1/social/auth/{platform}       → Revoke credentials
  - GET /api/v1/social/auth/status              → Get connection status

All routes require JWT authentication.
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from ...services.social_auth_service import (
    SocialAuthService,
    OAuthCredentials,
    TokenExpiredError,
    InvalidStateError,
    PlatformAuthError,
)
from ...dependencies import get_current_user, get_redis  # Adjust imports based on your auth setup

logger = logging.getLogger(__name__)

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/social/auth", tags=["social_auth"])


def _get_callback_base_url(request: Request) -> str:
    """Get base URL for callbacks."""
    # Use forwarded headers if behind a proxy
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}"
    
    # Fallback to request URL
    return str(request.base_url).rstrip("/")


@router.get("/{platform}/url")
async def get_auth_url(
    platform: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    redis = Depends(get_redis),
) -> Dict[str, str]:
    """
    Generate OAuth authorization URL for a platform.
    
    Platforms: tiktok, instagram, youtube
    """
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    
    # Validate platform
    valid_platforms = ["tiktok", "instagram", "youtube"]
    if platform not in valid_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid platform. Must be one of: {', '.join(valid_platforms)}"
        )
    
    try:
        auth_service = SocialAuthService(redis)
        
        # Build callback URL
        base_url = _get_callback_base_url(request)
        redirect_uri = f"{base_url}/api/v1/social/auth/{platform}/callback"
        
        auth_url = await auth_service.generate_auth_url(
            platform=platform,
            user_id=user_id,
            redirect_uri=redirect_uri,
        )
        
        logger.info(f"[social_auth] Generated auth URL for {platform} user {user_id}")
        return {"auth_url": auth_url}
        
    except ValueError as e:
        logger.error(f"[social_auth] Configuration error for {platform}: {e}")
        raise HTTPException(
            status_code=503,
            detail={"error": "platform_not_configured", "message": str(e)}
        )
    except Exception as e:
        logger.error(f"[social_auth] Error generating auth URL for {platform}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate auth URL")


@router.get("/{platform}/callback")
async def oauth_callback(
    platform: str,
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    redis = Depends(get_redis),
):
    """
    OAuth callback endpoint. Called by social platforms after user authorization.
    Redirects to dashboard with success or error status.
    """
    base_url = _get_callback_base_url(request)
    dashboard_url = f"{base_url}/dashboard"
    
    # Check for OAuth errors from the platform
    if error:
        logger.error(
            f"[social_auth] OAuth error from {platform}: {error} - {error_description}"
        )
        return RedirectResponse(
            url=f"{dashboard_url}?error=auth_failed&platform={platform}&reason={error}",
            status_code=302,
        )
    
    if not code or not state:
        logger.error(f"[social_auth] Missing code or state in {platform} callback")
        return RedirectResponse(
            url=f"{dashboard_url}?error=auth_failed&platform={platform}&reason=missing_params",
            status_code=302,
        )
    
    try:
        auth_service = SocialAuthService(redis)
        
        # Build redirect URI (must match the one used in generate_auth_url)
        redirect_uri = f"{base_url}/api/v1/social/auth/{platform}/callback"
        
        # Exchange code for tokens
        credentials: OAuthCredentials = await auth_service.exchange_code(
            platform=platform,
            code=code,
            state=state,
            redirect_uri=redirect_uri,
        )
        
        logger.info(
            f"[social_auth] Successfully connected {platform} for user {credentials.user_id}"
        )
        
        # Redirect to dashboard with success
        return RedirectResponse(
            url=f"{dashboard_url}?connected={platform}",
            status_code=302,
        )
        
    except InvalidStateError as e:
        logger.error(f"[social_auth] Invalid state in {platform} callback: {e}")
        return RedirectResponse(
            url=f"{dashboard_url}?error=auth_failed&platform={platform}&reason=invalid_state",
            status_code=302,
        )
    except PlatformAuthError as e:
        logger.error(f"[social_auth] Platform auth error for {platform}: {e}")
        return RedirectResponse(
            url=f"{dashboard_url}?error=auth_failed&platform={platform}&reason=platform_error",
            status_code=302,
        )
    except Exception as e:
        logger.error(f"[social_auth] Unexpected error in {platform} callback: {e}", exc_info=True)
        return RedirectResponse(
            url=f"{dashboard_url}?error=auth_failed&platform={platform}&reason=server_error",
            status_code=302,
        )


@router.delete("/{platform}")
async def revoke_platform_auth(
    platform: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    redis = Depends(get_redis),
) -> Dict[str, bool]:
    """
    Revoke OAuth credentials for a platform.
    """
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    
    # Validate platform
    valid_platforms = ["tiktok", "instagram", "youtube"]
    if platform not in valid_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid platform. Must be one of: {', '.join(valid_platforms)}"
        )
    
    try:
        auth_service = SocialAuthService(redis)
        revoked = await auth_service.revoke_credentials(platform, user_id)
        
        if revoked:
            logger.info(f"[social_auth] Revoked {platform} for user {user_id}")
            return {"revoked": True}
        else:
            logger.warning(f"[social_auth] No credentials to revoke for {platform} user {user_id}")
            return {"revoked": False}
            
    except TokenExpiredError as e:
        logger.error(f"[social_auth] Token expired for {platform} user {user_id}: {e}")
        raise HTTPException(
            status_code=401,
            detail={"error": "token_expired", "platform": platform}
        )
    except PlatformAuthError as e:
        logger.error(f"[social_auth] Platform error revoking {platform}: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "platform_error", "detail": str(e)}
        )
    except Exception as e:
        logger.error(f"[social_auth] Error revoking {platform}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to revoke credentials")


@router.get("/status")
async def get_auth_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
    redis = Depends(get_redis),
) -> Dict[str, bool]:
    """
    Get connection status for all platforms.
    Returns: {"tiktok": true, "instagram": false, "youtube": true}
    """
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    
    try:
        auth_service = SocialAuthService(redis)
        
        platforms = ["tiktok", "instagram", "youtube"]
        status: Dict[str, bool] = {}
        
        for platform in platforms:
            try:
                credentials = await auth_service.get_credentials(platform, user_id)
                status[platform] = credentials is not None
            except TokenExpiredError:
                status[platform] = False
            except Exception:
                status[platform] = False
        
        logger.info(f"[social_auth] Status for user {user_id}: {status}")
        return status
        
    except Exception as e:
        logger.error(f"[social_auth] Error getting status for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get auth status")
