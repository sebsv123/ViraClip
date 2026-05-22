"""
OAuth callback routes for TikTok, Instagram, and YouTube.

Handles the OAuth redirect from each platform, exchanges the code for tokens,
and stores them in the user record. Redirects to the frontend dashboard on success.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...database import get_db
from ...config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

FRONTEND_URL = "http://localhost:3000"


def _get_user_id_from_headers(request: Request) -> str:
    """Get user ID from request headers."""
    config = get_config()
    if config.monetization_enabled:
        from ...auth_headers import get_signed_user_id
        return get_signed_user_id(request, config)
    user_id = request.headers.get("user_id") or request.headers.get("x-viraclip-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")
    return user_id


@router.get("/tiktok/callback")
async def tiktok_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    TikTok OAuth callback.

    Exchanges the authorization code for tokens and stores them in the user record.
    Redirects to the frontend dashboard on success.
    """
    if error:
        logger.warning("[TikTok] OAuth error: %s", error)
        return {"error": f"TikTok OAuth error: {error}"}

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        from ...domains.publishing.social_distribution_service import SocialDistributionService

        tokens = await SocialDistributionService.exchange_code(code)
        user_id = _get_user_id_from_headers(request)

        # Store tokens in user record
        async with db as session:
            await session.execute(
                text("""
                    UPDATE users
                    SET tiktok_credentials = :credentials
                    WHERE id = :user_id
                """),
                {
                    "credentials": json.dumps(tokens),
                    "user_id": user_id,
                },
            )
            await session.commit()

        logger.info("[TikTok] OAuth tokens stored for user %s", user_id[:12])
        return {"status": "connected", "platform": "tiktok", "redirect": f"{FRONTEND_URL}/dashboard"}

    except Exception as e:
        logger.error("[TikTok] OAuth callback failed: %s", e)
        raise HTTPException(status_code=502, detail=f"TikTok OAuth failed: {str(e)}")


@router.get("/instagram/callback")
async def instagram_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Instagram OAuth callback (Facebook Login).

    Exchanges the authorization code for a long-lived token and stores it.
    Redirects to the frontend dashboard on success.
    """
    if error:
        logger.warning("[Instagram] OAuth error: %s", error)
        return {"error": f"Instagram OAuth error: {error}"}

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        from ...domains.publishing.social_distribution_service import SocialDistributionService

        tokens = await SocialDistributionService.exchange_instagram_code(code)
        user_id = _get_user_id_from_headers(request)

        async with db as session:
            await session.execute(
                text("""
                    UPDATE users
                    SET instagram_credentials = :credentials
                    WHERE id = :user_id
                """),
                {
                    "credentials": json.dumps(tokens),
                    "user_id": user_id,
                },
            )
            await session.commit()

        logger.info("[Instagram] OAuth tokens stored for user %s", user_id[:12])
        return {"status": "connected", "platform": "instagram", "redirect": f"{FRONTEND_URL}/dashboard"}

    except Exception as e:
        logger.error("[Instagram] OAuth callback failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Instagram OAuth failed: {str(e)}")


@router.get("/youtube/callback")
async def youtube_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    YouTube OAuth callback (Google OAuth).

    Exchanges the authorization code for access + refresh tokens and stores them.
    Redirects to the frontend dashboard on success.
    """
    if error:
        logger.warning("[YouTube] OAuth error: %s", error)
        return {"error": f"YouTube OAuth error: {error}"}

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        from ...domains.publishing.social_distribution_service import SocialDistributionService

        tokens = await SocialDistributionService.exchange_youtube_code(code)
        user_id = _get_user_id_from_headers(request)

        async with db as session:
            await session.execute(
                text("""
                    UPDATE users
                    SET youtube_credentials = :credentials
                    WHERE id = :user_id
                """),
                {
                    "credentials": json.dumps(tokens),
                    "user_id": user_id,
                },
            )
            await session.commit()

        logger.info("[YouTube] OAuth tokens stored for user %s", user_id[:12])
        return {"status": "connected", "platform": "youtube", "redirect": f"{FRONTEND_URL}/dashboard"}

    except Exception as e:
        logger.error("[YouTube] OAuth callback failed: %s", e)
        raise HTTPException(status_code=502, detail=f"YouTube OAuth failed: {str(e)}")
