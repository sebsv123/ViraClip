"""
Social Distribution Service — TikTok + Instagram Reels publishing.

Supports:
- OAuth 2.0 flow to connect TikTok and Instagram Business accounts
- Video upload with title, hashtags, privacy setting
- Publish status tracking per clip
- Clean error handling (no crashes on API errors)

Does NOT implement scheduling or YouTube yet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# ── TikTok OAuth & API config ────────────────────────────────────────────────
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:3000/auth/tiktok/callback")
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"

# ── Instagram Graph API config ───────────────────────────────────────────────
INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")
INSTAGRAM_REDIRECT_URI = os.getenv("INSTAGRAM_REDIRECT_URI", "http://localhost:3000/auth/instagram/callback")
INSTAGRAM_API_BASE = "https://graph.facebook.com/v22.0"

# ── YouTube Data API config ─────────────────────────────────────────────────
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:3000/auth/youtube/callback")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_OAUTH_BASE = "https://oauth2.googleapis.com"


@dataclass
class PublishResult:
    """Result of a TikTok publish attempt."""
    success: bool
    platform: str
    video_id: Optional[str] = None
    status: str = "skipped"  # skipped | published | failed
    error: Optional[str] = None
    error_code: Optional[str] = None


class TikTokOAuthError(Exception):
    """TikTok OAuth or API error."""
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(f"[{code}] {message}" if code else message)


class InstagramGraphError(Exception):
    """Instagram Graph API error."""
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(f"[{code}] {message}" if code else message)


class YouTubeAPIError(Exception):
    """YouTube Data API error."""
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(f"[{code}] {message}" if code else message)


class SocialDistributionService:
    """
    Publish clips to TikTok via OAuth 2.0 + Content API.

    Usage:
        svc = SocialDistributionService()
        # 1. Get OAuth URL for user to connect
        auth_url = svc.get_tiktok_auth_url()
        # 2. Exchange code for token
        token = await svc.exchange_code(code)
        # 3. Publish clip
        result = await svc.publish_clip(
            video_path=Path("/clips/output.mp4"),
            platform="tiktok",
            caption="Check this out! #viral",
            hashtags=["fyp", "viral"],
            privacy_level="public",
            user_auth_token=token,
        )
    """

    @staticmethod
    def get_tiktok_auth_url(state: str = "") -> str:
        """
        Build TikTok OAuth authorization URL.

        Args:
            state: Optional CSRF state parameter.

        Returns:
            Full TikTok OAuth URL for user redirect.
        """
        if not TIKTOK_CLIENT_KEY:
            logger.warning("[TikTok] TIKTOK_CLIENT_KEY not set — OAuth URL will be invalid")
        params = {
            "client_key": TIKTOK_CLIENT_KEY,
            "scope": "user.info.basic,video.publish,video.upload",
            "redirect_uri": TIKTOK_REDIRECT_URI,
            "response_type": "code",
        }
        if state:
            params["state"] = state
        return f"https://www.tiktok.com/v2/auth/authorize/?{urlencode(params)}"

    @staticmethod
    async def exchange_code(code: str) -> Dict[str, Any]:
        """
        Exchange OAuth authorization code for access + refresh tokens.

        Args:
            code: Authorization code from TikTok OAuth callback.

        Returns:
            Dict with access_token, refresh_token, expires_in, open_id.

        Raises:
            TikTokOAuthError on API failure.
        """
        if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
            raise TikTokOAuthError("TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET not set", "MISSING_CONFIG")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{TIKTOK_API_BASE}/oauth/token/",
                    data={
                        "client_key": TIKTOK_CLIENT_KEY,
                        "client_secret": TIKTOK_CLIENT_SECRET,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": TIKTOK_REDIRECT_URI,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("error"):
                    err = data.get("error_description", data.get("error", "Unknown OAuth error"))
                    raise TikTokOAuthError(err, str(resp.status_code))
                logger.info("[TikTok] OAuth token exchange successful")
                return {
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", ""),
                    "expires_in": data.get("expires_in", 0),
                    "open_id": data.get("open_id", ""),
                }
        except TikTokOAuthError:
            raise
        except Exception as e:
            raise TikTokOAuthError(str(e), "NETWORK_ERROR")

    @staticmethod
    async def refresh_token(refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an expired TikTok access token.

        Args:
            refresh_token: The refresh token from a previous OAuth exchange.

        Returns:
            Dict with new access_token, refresh_token, expires_in.
        """
        if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
            raise TikTokOAuthError("TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET not set", "MISSING_CONFIG")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{TIKTOK_API_BASE}/oauth/token/",
                    data={
                        "client_key": TIKTOK_CLIENT_KEY,
                        "client_secret": TIKTOK_CLIENT_SECRET,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("error"):
                    err = data.get("error_description", data.get("error", "Unknown refresh error"))
                    raise TikTokOAuthError(err, str(resp.status_code))
                logger.info("[TikTok] Token refresh successful")
                return {
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", refresh_token),
                    "expires_in": data.get("expires_in", 0),
                }
        except TikTokOAuthError:
            raise
        except Exception as e:
            raise TikTokOAuthError(str(e), "NETWORK_ERROR")

    @staticmethod
    async def _upload_video(
        video_path: Path,
        access_token: str,
        open_id: str,
    ) -> str:
        """
        Upload video to TikTok and return publish_id.

        Uses TikTok Content API /video/upload/ endpoint.
        """
        if not video_path.exists():
            raise TikTokOAuthError(f"Video file not found: {video_path}", "FILE_NOT_FOUND")

        file_size = video_path.stat().st_size
        logger.info("[TikTok] Uploading video: %s (%d bytes)", video_path.name, file_size)

        async with httpx.AsyncClient(timeout=300) as client:
            # Step 1: Initialize upload
            init_resp = await client.post(
                f"{TIKTOK_API_BASE}/video/upload/",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "open_id": open_id,
                    "source": "FILE",
                    "file_size": file_size,
                    "file_name": video_path.name,
                },
            )
            init_data = init_resp.json()
            if init_resp.status_code != 200 or init_data.get("error"):
                err = init_data.get("error", {}).get("message", "Upload init failed")
                raise TikTokOAuthError(err, str(init_resp.status_code))

            upload_url = init_data["data"]["upload_url"]
            publish_id = init_data["data"]["publish_id"]

            # Step 2: Upload file chunks
            file_content = video_path.read_bytes()
            chunk_resp = await client.post(
                upload_url,
                content=file_content,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                    "Content-Length": str(file_size),
                },
            )
            if chunk_resp.status_code not in (200, 201):
                raise TikTokOAuthError(f"Upload failed: HTTP {chunk_resp.status_code}", "UPLOAD_FAILED")

            logger.info("[TikTok] Upload complete: publish_id=%s", publish_id)
            return publish_id

    @staticmethod
    async def _publish_video(
        publish_id: str,
        access_token: str,
        open_id: str,
        caption: str = "",
        hashtags: Optional[List[str]] = None,
        privacy_level: str = "public",
    ) -> Dict[str, Any]:
        """
        Publish an uploaded video with metadata.

        Args:
            publish_id: ID from upload step.
            access_token: TikTok access token.
            open_id: TikTok user open_id.
            caption: Video caption text.
            hashtags: List of hashtags (without # prefix).
            privacy_level: "public", "friends", or "private".

        Returns:
            Dict with video_id and status.
        """
        hashtags = hashtags or []
        hashtag_str = " ".join(f"#{h.strip('#')}" for h in hashtags)
        full_caption = f"{caption}\n{hashtag_str}".strip()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{TIKTOK_API_BASE}/video/publish/",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "open_id": open_id,
                    "publish_id": publish_id,
                    "caption": full_caption,
                    "privacy_level": privacy_level,
                    "disable_duet": False,
                    "disable_stitch": False,
                    "disable_comment": False,
                    "brand_organic_opt_in": False,
                },
            )
            data = resp.json()
            if resp.status_code != 200 or data.get("error"):
                err = data.get("error", {}).get("message", "Publish failed")
                raise TikTokOAuthError(err, str(resp.status_code))

            video_id = data["data"].get("video_id", "")
            logger.info("[TikTok] Published: video_id=%s", video_id)
            return {"video_id": video_id, "status": "published"}

    @staticmethod
    async def _check_publish_status(
        publish_id: str,
        access_token: str,
        open_id: str,
    ) -> Dict[str, Any]:
        """Check the status of a video publish request."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{TIKTOK_API_BASE}/video/publish/status/",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "open_id": open_id,
                    "publish_id": publish_id,
                },
            )
            data = resp.json()
            if resp.status_code != 200 or data.get("error"):
                err = data.get("error", {}).get("message", "Status check failed")
                raise TikTokOAuthError(err, str(resp.status_code))
            return data["data"]

    @classmethod
    async def publish_clip(
        cls,
        video_path: Path,
        platform: str,
        caption: str = "",
        hashtags: Optional[List[str]] = None,
        privacy_level: str = "public",
        user_auth_token: Optional[str] = None,
        open_id: Optional[str] = None,
        **kwargs: Any,
    ) -> PublishResult:
        """
        Publish a clip to TikTok or Instagram Reels.

        Args:
            video_path: Path to the video file to publish.
            platform: "tiktok" or "instagram" (others return skipped).
            caption: Video caption text.
            hashtags: List of hashtags (without # prefix).
            privacy_level: "public", "friends", or "private".
            user_auth_token: OAuth access token.
            open_id: User ID (TikTok open_id or Instagram page_id).

        Returns:
            PublishResult with success/fail status.
        """
        if platform == "youtube":
            return await cls._publish_youtube_short(
                video_path=video_path,
                title=caption or "ViraClip Short",
                description=caption,
                tags=hashtags,
                privacy_status=privacy_level,
                access_token=user_auth_token,
            )

        if platform == "instagram":
            return await cls._publish_instagram_reel(
                video_path=video_path,
                caption=caption,
                hashtags=hashtags,
                privacy_level=privacy_level,
                access_token=user_auth_token,
                page_id=open_id,
            )

        if platform != "tiktok":
            logger.info("[SocialDistribution] Skipping unsupported platform: %s", platform)
            return PublishResult(success=False, platform=platform, status="skipped")

        if not user_auth_token or not open_id:
            logger.warning("[TikTok] Missing auth token or open_id — cannot publish")
            return PublishResult(
                success=False, platform="tiktok", status="failed",
                error="TikTok account not connected. Use OAuth to connect first.",
                error_code="NO_AUTH",
            )

        if not TIKTOK_CLIENT_KEY:
            logger.warning("[TikTok] TIKTOK_CLIENT_KEY not set — cannot publish")
            return PublishResult(
                success=False, platform="tiktok", status="failed",
                error="TikTok API not configured. Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET.",
                error_code="MISSING_CONFIG",
            )

        try:
            # Step 1: Upload video
            publish_id = await cls._upload_video(video_path, user_auth_token, open_id)

            # Step 2: Publish with metadata
            result = await cls._publish_video(
                publish_id=publish_id,
                access_token=user_auth_token,
                open_id=open_id,
                caption=caption,
                hashtags=hashtags,
                privacy_level=privacy_level,
            )

            logger.info(
                "[TikTok] ✅ Published %s: video_id=%s",
                video_path.name, result.get("video_id", "?"),
            )
            return PublishResult(
                success=True,
                platform="tiktok",
                video_id=result.get("video_id"),
                status="published",
            )

        except TikTokOAuthError as e:
            logger.error("[TikTok] ❌ Publish failed: [%s] %s", e.code, e.message)
            return PublishResult(
                success=False, platform="tiktok", status="failed",
                error=e.message, error_code=e.code,
            )
        except Exception as e:
            logger.error("[TikTok] ❌ Unexpected error: %s", e)
            return PublishResult(
                success=False, platform="tiktok", status="failed",
                error=str(e), error_code="UNEXPECTED",
            )

    # ── Instagram Reels ────────────────────────────────────────────────────

    @staticmethod
    def get_instagram_auth_url(state: str = "") -> str:
        """
        Build Instagram OAuth authorization URL (Facebook Login).

        Args:
            state: Optional CSRF state parameter.

        Returns:
            Full Instagram OAuth URL for user redirect.
        """
        if not INSTAGRAM_APP_ID:
            logger.warning("[Instagram] INSTAGRAM_APP_ID not set — OAuth URL will be invalid")
        params = {
            "client_id": INSTAGRAM_APP_ID,
            "redirect_uri": INSTAGRAM_REDIRECT_URI,
            "scope": "instagram_basic,instagram_content_publish,pages_read_engagement",
            "response_type": "code",
        }
        if state:
            params["state"] = state
        return f"https://www.facebook.com/v22.0/dialog/oauth?{urlencode(params)}"

    @staticmethod
    async def exchange_instagram_code(code: str) -> Dict[str, Any]:
        """
        Exchange Instagram OAuth code for a long-lived access token.

        Args:
            code: Authorization code from Instagram OAuth callback.

        Returns:
            Dict with access_token, token_type, expires_in.

        Raises:
            InstagramGraphError on API failure.
        """
        if not INSTAGRAM_APP_ID or not INSTAGRAM_APP_SECRET:
            raise InstagramGraphError("INSTAGRAM_APP_ID or INSTAGRAM_APP_SECRET not set", "MISSING_CONFIG")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Step 1: Exchange code for short-lived token
                resp = await client.get(
                    f"{INSTAGRAM_API_BASE}/oauth/access_token",
                    params={
                        "client_id": INSTAGRAM_APP_ID,
                        "client_secret": INSTAGRAM_APP_SECRET,
                        "redirect_uri": INSTAGRAM_REDIRECT_URI,
                        "code": code,
                    },
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("error"):
                    err = data.get("error", {}).get("message", data.get("error_description", "Unknown OAuth error"))
                    raise InstagramGraphError(err, str(resp.status_code))

                short_token = data["access_token"]

                # Step 2: Exchange short-lived for long-lived token (60 days)
                long_resp = await client.get(
                    f"{INSTAGRAM_API_BASE}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": INSTAGRAM_APP_ID,
                        "client_secret": INSTAGRAM_APP_SECRET,
                        "fb_exchange_token": short_token,
                    },
                )
                long_data = long_resp.json()
                if long_resp.status_code != 200 or long_data.get("error"):
                    err = long_data.get("error", {}).get("message", "Token exchange failed")
                    raise InstagramGraphError(err, str(long_resp.status_code))

                logger.info("[Instagram] OAuth token exchange successful")
                return {
                    "access_token": long_data["access_token"],
                    "token_type": "bearer",
                    "expires_in": long_data.get("expires_in", 0),
                }
        except InstagramGraphError:
            raise
        except Exception as e:
            raise InstagramGraphError(str(e), "NETWORK_ERROR")

    @staticmethod
    async def _get_instagram_page_id(access_token: str) -> str:
        """
        Get the Instagram Business page ID from the access token.

        Args:
            access_token: Facebook/Instagram long-lived access token.

        Returns:
            Instagram Business page ID string.

        Raises:
            InstagramGraphError if no page found.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{INSTAGRAM_API_BASE}/me/accounts",
                params={"access_token": access_token},
            )
            data = resp.json()
            if resp.status_code != 200 or data.get("error"):
                err = data.get("error", {}).get("message", "Failed to get pages")
                raise InstagramGraphError(err, str(resp.status_code))

            pages = data.get("data", [])
            if not pages:
                raise InstagramGraphError(
                    "No Facebook Pages found. Create a Facebook Page and connect Instagram.",
                    "NO_PAGE",
                )
            # Return the first page's ID
            return pages[0]["id"]

    @staticmethod
    async def _get_instagram_business_id(page_id: str, access_token: str) -> str:
        """
        Get the Instagram Business Account ID from a Facebook Page.

        Args:
            page_id: Facebook Page ID.
            access_token: Facebook long-lived access token.

        Returns:
            Instagram Business Account ID.

        Raises:
            InstagramGraphError if Instagram not connected to page.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{INSTAGRAM_API_BASE}/{page_id}",
                params={
                    "access_token": access_token,
                    "fields": "instagram_business_account",
                },
            )
            data = resp.json()
            if resp.status_code != 200 or data.get("error"):
                err = data.get("error", {}).get("message", "Failed to get Instagram account")
                raise InstagramGraphError(err, str(resp.status_code))

            ig_account = data.get("instagram_business_account")
            if not ig_account:
                raise InstagramGraphError(
                    "No Instagram Business Account connected to this Facebook Page. "
                    "Connect Instagram in Facebook Page settings.",
                    "NO_INSTAGRAM",
                )
            return ig_account["id"]

    @classmethod
    async def _publish_instagram_reel(
        cls,
        video_path: Path,
        caption: str = "",
        hashtags: Optional[List[str]] = None,
        privacy_level: str = "public",
        access_token: Optional[str] = None,
        page_id: Optional[str] = None,
    ) -> PublishResult:
        """
        Publish a video as an Instagram Reel via the Graph API.

        Uses the Instagram Content Publishing API:
        1. Get Instagram Business Account ID from page
        2. Create media container (video)
        3. Publish the container

        Args:
            video_path: Path to the video file.
            caption: Reel caption text.
            hashtags: List of hashtags.
            privacy_level: "public" or "private".
            access_token: Facebook long-lived access token.
            page_id: Facebook Page ID (if None, fetched from token).

        Returns:
            PublishResult with success/fail status.
        """
        if not INSTAGRAM_APP_ID:
            return PublishResult(
                success=False, platform="instagram", status="failed",
                error="Instagram API not configured. Set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET.",
                error_code="MISSING_CONFIG",
            )

        if not access_token:
            return PublishResult(
                success=False, platform="instagram", status="failed",
                error="Instagram account not connected. Use OAuth to connect first.",
                error_code="NO_AUTH",
            )

        if not video_path.exists():
            return PublishResult(
                success=False, platform="instagram", status="failed",
                error=f"Video file not found: {video_path}",
                error_code="FILE_NOT_FOUND",
            )

        try:
            # Step 1: Get page ID if not provided
            if not page_id:
                page_id = await cls._get_instagram_page_id(access_token)

            # Step 2: Get Instagram Business Account ID
            ig_id = await cls._get_instagram_business_id(page_id, access_token)

            # Step 3: Upload video and create media container
            hashtag_str = " ".join(f"#{h.strip('#')}" for h in (hashtags or []))
            full_caption = f"{caption}\n{hashtag_str}".strip()[:2200]  # Instagram 2200 char limit

            async with httpx.AsyncClient(timeout=300) as client:
                # Create media container
                create_resp = await client.post(
                    f"{INSTAGRAM_API_BASE}/{ig_id}/media",
                    params={
                        "access_token": access_token,
                        "media_type": "REELS",
                        "video_url": "",  # Will use file upload
                        "caption": full_caption,
                        "share_to_feed": privacy_level == "public",
                    },
                )
                create_data = create_resp.json()
                if create_resp.status_code != 200 or create_data.get("error"):
                    err = create_data.get("error", {}).get("message", "Media creation failed")
                    raise InstagramGraphError(err, str(create_resp.status_code))

                container_id = create_data.get("id", "")

                # Step 4: Upload video file to the container
                file_content = video_path.read_bytes()
                upload_resp = await client.post(
                    f"{INSTAGRAM_API_BASE}/{container_id}",
                    params={"access_token": access_token},
                    files={"file": ("video.mp4", file_content, "video/mp4")},
                )
                if upload_resp.status_code not in (200, 201):
                    raise InstagramGraphError(f"Upload failed: HTTP {upload_resp.status_code}", "UPLOAD_FAILED")

                # Step 5: Publish the container
                publish_resp = await client.post(
                    f"{INSTAGRAM_API_BASE}/{ig_id}/media_publish",
                    params={
                        "access_token": access_token,
                        "creation_id": container_id,
                    },
                )
                publish_data = publish_resp.json()
                if publish_resp.status_code != 200 or publish_data.get("error"):
                    err = publish_data.get("error", {}).get("message", "Publish failed")
                    raise InstagramGraphError(err, str(publish_resp.status_code))

                media_id = publish_data.get("id", "")
                logger.info("[Instagram] ✅ Published Reel: media_id=%s", media_id)
                return PublishResult(
                    success=True,
                    platform="instagram",
                    video_id=media_id,
                    status="published",
                )

        except InstagramGraphError as e:
            logger.error("[Instagram] ❌ Publish failed: [%s] %s", e.code, e.message)
            return PublishResult(
                success=False, platform="instagram", status="failed",
                error=e.message, error_code=e.code,
            )
        except Exception as e:
            logger.error("[Instagram] ❌ Unexpected error: %s", e)
            return PublishResult(
                success=False, platform="instagram", status="failed",
                error=str(e), error_code="UNEXPECTED",
            )

    # ── YouTube Shorts ─────────────────────────────────────────────────────

    @staticmethod
    def get_youtube_auth_url(state: str = "") -> str:
        """
        Build YouTube OAuth authorization URL.

        Args:
            state: Optional CSRF state parameter.

        Returns:
            Full Google OAuth URL for user redirect.
        """
        if not YOUTUBE_CLIENT_ID:
            logger.warning("[YouTube] YOUTUBE_CLIENT_ID not set — OAuth URL will be invalid")
        params = {
            "client_id": YOUTUBE_CLIENT_ID,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "scope": "https://www.googleapis.com/auth/youtube.upload",
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"{YOUTUBE_OAUTH_BASE}/auth?{urlencode(params)}"

    @staticmethod
    async def exchange_youtube_code(code: str) -> Dict[str, Any]:
        """
        Exchange YouTube OAuth code for access + refresh tokens.

        Args:
            code: Authorization code from Google OAuth callback.

        Returns:
            Dict with access_token, refresh_token, expires_in.

        Raises:
            YouTubeAPIError on API failure.
        """
        if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
            raise YouTubeAPIError("YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET not set", "MISSING_CONFIG")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{YOUTUBE_OAUTH_BASE}/token",
                    data={
                        "client_id": YOUTUBE_CLIENT_ID,
                        "client_secret": YOUTUBE_CLIENT_SECRET,
                        "code": code,
                        "redirect_uri": YOUTUBE_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("error"):
                    err = data.get("error_description", data.get("error", "Unknown OAuth error"))
                    raise YouTubeAPIError(err, str(resp.status_code))
                logger.info("[YouTube] OAuth token exchange successful")
                return {
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", ""),
                    "expires_in": data.get("expires_in", 0),
                }
        except YouTubeAPIError:
            raise
        except Exception as e:
            raise YouTubeAPIError(str(e), "NETWORK_ERROR")

    @staticmethod
    async def refresh_youtube_token(refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an expired YouTube access token.

        Args:
            refresh_token: The refresh token from a previous OAuth exchange.

        Returns:
            Dict with new access_token, expires_in.
        """
        if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
            raise YouTubeAPIError("YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET not set", "MISSING_CONFIG")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{YOUTUBE_OAUTH_BASE}/token",
                    data={
                        "client_id": YOUTUBE_CLIENT_ID,
                        "client_secret": YOUTUBE_CLIENT_SECRET,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("error"):
                    err = data.get("error_description", data.get("error", "Token refresh failed"))
                    raise YouTubeAPIError(err, str(resp.status_code))
                logger.info("[YouTube] Token refresh successful")
                return {
                    "access_token": data["access_token"],
                    "expires_in": data.get("expires_in", 0),
                }
        except YouTubeAPIError:
            raise
        except Exception as e:
            raise YouTubeAPIError(str(e), "NETWORK_ERROR")

    @classmethod
    async def _publish_youtube_short(
        cls,
        video_path: Path,
        title: str = "ViraClip Short",
        description: str = "",
        tags: Optional[List[str]] = None,
        privacy_status: str = "public",
        access_token: Optional[str] = None,
    ) -> PublishResult:
        """
        Publish a video as a YouTube Short via the Data API.

        Uses resumable media upload to the youtube.videos.insert endpoint.
        Marks the video as #Shorts by adding "#Shorts" to the title/description.

        Args:
            video_path: Path to the video file.
            title: Video title (appended with #Shorts).
            description: Video description.
            tags: List of video tags.
            privacy_status: "public", "unlisted", or "private".
            access_token: Google OAuth access token.

        Returns:
            PublishResult with success/fail status.
        """
        if not YOUTUBE_CLIENT_ID:
            return PublishResult(
                success=False, platform="youtube", status="failed",
                error="YouTube API not configured. Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET.",
                error_code="MISSING_CONFIG",
            )

        if not access_token:
            return PublishResult(
                success=False, platform="youtube", status="failed",
                error="YouTube account not connected. Use OAuth to connect first.",
                error_code="NO_AUTH",
            )

        if not video_path.exists():
            return PublishResult(
                success=False, platform="youtube", status="failed",
                error=f"Video file not found: {video_path}",
                error_code="FILE_NOT_FOUND",
            )

        try:
            # Mark as Short: append #Shorts to title
            short_title = title
            if "#Shorts" not in short_title:
                short_title = f"{short_title} #Shorts"

            tags_list = tags or []
            if "#Shorts" not in tags_list:
                tags_list.append("#Shorts")

            # Build metadata JSON for the insert request
            body = {
                "snippet": {
                    "title": short_title[:100],
                    "description": (description or "")[:5000],
                    "tags": tags_list[:30],
                    "categoryId": "22",  # People & Blogs
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            }

            file_size = video_path.stat().st_size
            file_content = video_path.read_bytes()

            async with httpx.AsyncClient(timeout=600) as client:
                # Step 1: Initiate resumable upload
                init_resp = await client.post(
                    f"{YOUTUBE_API_BASE}/videos?part=snippet,status&uploadType=resumable",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=utf-8",
                        "X-Upload-Content-Length": str(file_size),
                        "X-Upload-Content-Type": "video/*",
                    },
                    json=body,
                )
                if init_resp.status_code != 200:
                    err_data = init_resp.json()
                    err = err_data.get("error", {}).get("message", f"Upload init failed: HTTP {init_resp.status_code}")
                    raise YouTubeAPIError(err, str(init_resp.status_code))

                upload_url = init_resp.headers.get("Location", "")
                if not upload_url:
                    raise YouTubeAPIError("No upload URL in response", "NO_UPLOAD_URL")

                # Step 2: Upload video bytes
                upload_resp = await client.put(
                    upload_url,
                    content=file_content,
                    headers={
                        "Content-Type": "video/*",
                        "Content-Length": str(file_size),
                    },
                )
                if upload_resp.status_code not in (200, 201, 204):
                    err_data = upload_resp.json()
                    err = err_data.get("error", {}).get("message", f"Upload failed: HTTP {upload_resp.status_code}")
                    raise YouTubeAPIError(err, str(upload_resp.status_code))

                result = upload_resp.json()
                video_id = result.get("id", "")
                logger.info("[YouTube] ✅ Published Short: video_id=%s title='%s'", video_id, short_title)
                return PublishResult(
                    success=True,
                    platform="youtube",
                    video_id=video_id,
                    status="published",
                )

        except YouTubeAPIError as e:
            logger.error("[YouTube] ❌ Publish failed: [%s] %s", e.code, e.message)
            return PublishResult(
                success=False, platform="youtube", status="failed",
                error=e.message, error_code=e.code,
            )
        except Exception as e:
            logger.error("[YouTube] ❌ Unexpected error: %s", e)
            return PublishResult(
                success=False, platform="youtube", status="failed",
                error=str(e), error_code="UNEXPECTED",
            )

    @staticmethod
    def get_oauth_url(platform: str, state: str = "") -> str:
        """
        Get OAuth authorization URL for a platform.

        Args:
            platform: "tiktok", "instagram", or "youtube" (others return empty string).
            state: Optional CSRF state parameter.

        Returns:
            OAuth URL for user redirect, or empty string if platform not supported.
        """
        if platform == "tiktok":
            return SocialDistributionService.get_tiktok_auth_url(state)
        if platform == "instagram":
            return SocialDistributionService.get_instagram_auth_url(state)
        if platform == "youtube":
            return SocialDistributionService.get_youtube_auth_url(state)
        logger.warning("[SocialDistribution] OAuth not implemented for platform: %s", platform)
        return ""

    @staticmethod
    async def get_viral_hashtags(
        transcript: str,
        platform: str = "tiktok",
        **kwargs: Any,
    ) -> List[str]:
        """
        Get viral hashtags for a transcript.

        Falls back to trending hashtags from ViralTrendService.
        """
        try:
            from ...domains.virality.viral_trend_service import ViralTrendService
            trend_svc = ViralTrendService()
            trending = trend_svc.get_trending_hashtags(platform=platform, limit=10)
            if trending:
                return trending[:10]
        except Exception as e:
            logger.debug("[SocialDistribution] Hashtag fetch failed: %s", e)

        # Hardcoded fallback
        platform_defaults = {
            "tiktok": ["fyp", "viral", "foryou", "trending", "contentcreator"],
        }
        return platform_defaults.get(platform, ["viral", "trending"])


__all__ = ["SocialDistributionService", "PublishResult", "TikTokOAuthError"]
