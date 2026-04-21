"""
Social Auth Service — OAuth 2.0 Management for TikTok, Instagram, YouTube
============================================================================

Handles OAuth flows, token refresh, credential storage in Redis, and revocation.
All secrets are read from environment variables only.

Supported platforms:
  - TikTok (Content Posting API v2)
  - Instagram (Graph API)
  - YouTube (Data API v3)

Redis key patterns:
  - oauth_state:{state_token} → OAuthState (TTL 10 min)
  - oauth:{platform}:{user_id} → OAuthCredentials (TTL = token expiry)
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

__all__ = [
    "OAuthCredentials",
    "OAuthState",
    "SocialAuthService",
    "TokenExpiredError",
    "InvalidStateError",
    "PlatformAuthError",
]


class TokenExpiredError(Exception):
    """Raised when a refresh token is invalid or expired."""
    def __init__(self, platform: str, user_id: str):
        self.platform = platform
        self.user_id = user_id
        super().__init__(f"Token expired for {platform} user {user_id}")


class InvalidStateError(Exception):
    """Raised when OAuth state token is invalid or expired."""
    pass


class PlatformAuthError(Exception):
    """Raised when a platform returns an authentication error."""
    def __init__(self, platform: str, message: str):
        self.platform = platform
        super().__init__(f"{platform} auth error: {message}")


@dataclass
class OAuthCredentials:
    platform: str          # "tiktok" | "instagram" | "youtube"
    user_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str
    platform_user_id: str
    platform_username: str


@dataclass
class OAuthState:
    state_token: str       # CSRF token
    user_id: str
    platform: str
    redirect_uri: str
    created_at: datetime


class SocialAuthService:
    """OAuth 2.0 service for social platform authentication."""

    # OAuth endpoints and scopes
    AUTH_URLS = {
        "tiktok": "https://www.tiktok.com/v2/auth/authorize/",
        "instagram": "https://api.instagram.com/oauth/authorize",
        "youtube": "https://accounts.google.com/o/oauth2/v2/auth",
    }

    TOKEN_URLS = {
        "tiktok": "https://open.tiktokapis.com/v2/oauth/token/",
        "instagram": "https://api.instagram.com/oauth/access_token",
        "youtube": "https://oauth2.googleapis.com/token",
    }

    SCOPES = {
        "tiktok": "video.upload,video.publish",
        "instagram": "instagram_basic,instagram_content_publish",
        "youtube": "https://www.googleapis.com/auth/youtube.upload",
    }

    REFRESH_URLS = {
        "tiktok": "https://open.tiktokapis.com/v2/oauth/token/",
        "instagram": "https://graph.instagram.com/access_token",  # Long-lived token refresh
        "youtube": "https://oauth2.googleapis.com/token",
    }

    REVOKE_URLS = {
        "tiktok": "https://open.tiktokapis.com/v2/oauth/revoke/",
        "instagram": None,  # No formal revocation, just delete local
        "youtube": "https://oauth2.googleapis.com/revoke",
    }

    def __init__(self, redis_client):
        self.redis = redis_client
        self._httpx_timeout = 30.0

    def _get_client_credentials(self, platform: str) -> dict:
        """Get client credentials from environment variables."""
        if platform == "tiktok":
            client_key = os.environ.get("TIKTOK_CLIENT_KEY")
            client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
            if not client_key or not client_secret:
                raise ValueError("TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET must be set")
            return {"client_key": client_key, "client_secret": client_secret}
        elif platform == "instagram":
            app_id = os.environ.get("INSTAGRAM_APP_ID")
            app_secret = os.environ.get("INSTAGRAM_APP_SECRET")
            if not app_id or not app_secret:
                raise ValueError("INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET must be set")
            return {"app_id": app_id, "app_secret": app_secret}
        elif platform == "youtube":
            client_id = os.environ.get("YOUTUBE_CLIENT_ID")
            client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
            if not client_id or not client_secret:
                raise ValueError("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set")
            return {"client_id": client_id, "client_secret": client_secret}
        else:
            raise ValueError(f"Unsupported platform: {platform}")

    async def generate_auth_url(self, platform: str, user_id: str, redirect_uri: str) -> str:
        """Generate OAuth authorization URL with CSRF state token."""
        state_token = secrets.token_hex(16)
        oauth_state = OAuthState(
            state_token=state_token,
            user_id=user_id,
            platform=platform,
            redirect_uri=redirect_uri,
            created_at=datetime.now(timezone.utc),
        )

        # Store state in Redis with 10 minute TTL
        await self.redis.setex(
            f"oauth_state:{state_token}",
            600,  # 10 minutes
            oauth_state.__dict__,
        )

        creds = self._get_client_credentials(platform)
        scopes = self.SCOPES[platform]

        if platform == "tiktok":
            return (
                f"{self.AUTH_URLS[platform]}"
                f"?client_key={creds['client_key']}"
                f"&redirect_uri={redirect_uri}"
                f"&scope={scopes}"
                f"&state={state_token}"
            )
        elif platform == "instagram":
            return (
                f"{self.AUTH_URLS[platform]}"
                f"?client_id={creds['app_id']}"
                f"&redirect_uri={redirect_uri}"
                f"&scope={scopes}"
                f"&response_type=code"
                f"&state={state_token}"
            )
        elif platform == "youtube":
            return (
                f"{self.AUTH_URLS[platform]}"
                f"?client_id={creds['client_id']}"
                f"&redirect_uri={redirect_uri}"
                f"&scope={scopes}"
                f"&response_type=code"
                f"&access_type=offline"
                f"&prompt=consent"
                f"&state={state_token}"
            )

    async def exchange_code(
        self, platform: str, code: str, state: str, redirect_uri: str
    ) -> OAuthCredentials:
        """Exchange OAuth code for access/refresh tokens."""
        # Validate state token
        state_data = await self.redis.get(f"oauth_state:{state}")
        if not state_data:
            raise InvalidStateError("Invalid or expired state token")

        # Delete state token (one-time use)
        await self.redis.delete(f"oauth_state:{state}")

        creds = self._get_client_credentials(platform)
        token_url = self.TOKEN_URLS[platform]

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            if platform == "tiktok":
                data = {
                    "client_key": creds["client_key"],
                    "client_secret": creds["client_secret"],
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                }
            elif platform == "instagram":
                data = {
                    "app_id": creds["app_id"],
                    "app_secret": creds["app_secret"],
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                }
            elif platform == "youtube":
                data = {
                    "client_id": creds["client_id"],
                    "client_secret": creds["client_secret"],
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                }

            try:
                response = await client.post(token_url, data=data)
                response.raise_for_status()
                token_data = response.json()
            except httpx.HTTPStatusError as e:
                raise PlatformAuthError(platform, f"Token exchange failed: {e.response.text}")
            except httpx.TimeoutException:
                raise PlatformAuthError(platform, "Token exchange timeout")

        # Parse token response
        if platform == "tiktok":
            access_token = token_data.get("data", {}).get("access_token")
            refresh_token = token_data.get("data", {}).get("refresh_token")
            expires_in = token_data.get("data", {}).get("expires_in", 86400)
            scope = token_data.get("data", {}).get("scope", self.SCOPES["tiktok"])
            platform_user_id = token_data.get("data", {}).get("open_id", "")
            platform_username = token_data.get("data", {}).get("display_name", "")
        elif platform == "instagram":
            access_token = token_data.get("access_token")
            # Instagram short-lived token, need to exchange for long-lived
            long_lived = await self._exchange_instagram_long_lived(access_token, creds)
            access_token = long_lived.get("access_token", access_token)
            expires_in = long_lived.get("expires_in", 5184000)  # 60 days default
            refresh_token = ""  # Instagram uses token refresh endpoint, not refresh_token
            scope = self.SCOPES["instagram"]
            platform_user_id = token_data.get("user_id", "")
            platform_username = ""
        elif platform == "youtube":
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 3600)
            scope = token_data.get("scope", self.SCOPES["youtube"])
            platform_user_id = ""
            platform_username = ""

        if not access_token:
            raise PlatformAuthError(platform, "No access token in response")

        # Get user info for platform_user_id/platform_username if not set
        if not platform_user_id or not platform_username:
            user_info = await self._get_user_info(platform, access_token)
            platform_user_id = user_info.get("id", platform_user_id)
            platform_username = user_info.get("username", platform_username)

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        oauth_creds = OAuthCredentials(
            platform=platform,
            user_id=state_data.get("user_id", ""),
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            platform_user_id=str(platform_user_id),
            platform_username=platform_username,
        )

        # Store in Redis with TTL = expires_in
        await self._save_credentials(oauth_creds)

        return oauth_creds

    async def _exchange_instagram_long_lived(self, short_lived_token: str, creds: dict) -> dict:
        """Exchange Instagram short-lived token for long-lived token."""
        url = "https://graph.instagram.com/access_token"
        params = {
            "grant_type": "ig_exchange_token",
            "client_secret": creds["app_secret"],
            "access_token": short_lived_token,
        }
        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return {}

    async def _get_user_info(self, platform: str, access_token: str) -> dict:
        """Get user info from platform API."""
        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            try:
                if platform == "tiktok":
                    response = await client.get(
                        "https://open.tiktokapis.com/v2/user/info/",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={"fields": "open_id,display_name"},
                    )
                elif platform == "instagram":
                    response = await client.get(
                        "https://graph.instagram.com/me",
                        params={"access_token": access_token, "fields": "id,username"},
                    )
                elif platform == "youtube":
                    response = await client.get(
                        "https://www.googleapis.com/youtube/v3/channels",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={"part": "snippet", "mine": "true"},
                    )
                    data = response.json()
                    items = data.get("items", [])
                    if items:
                        return {
                            "id": items[0].get("id", ""),
                            "username": items[0].get("snippet", {}).get("title", ""),
                        }
                    return {}
                else:
                    return {}

                response.raise_for_status()
                data = response.json()

                if platform == "tiktok":
                    return {
                        "id": data.get("data", {}).get("user", {}).get("open_id", ""),
                        "username": data.get("data", {}).get("user", {}).get("display_name", ""),
                    }
                elif platform == "instagram":
                    return {
                        "id": data.get("id", ""),
                        "username": data.get("username", ""),
                    }
            except httpx.HTTPError:
                return {}

    async def refresh_token_if_needed(self, credentials: OAuthCredentials) -> OAuthCredentials:
        """Refresh access token if expiring within 5 minutes."""
        now = datetime.now(timezone.utc)
        expires_at = credentials.expires_at

        # If expires_at is naive, assume UTC
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        # Check if token expires within 5 minutes
        if (expires_at - now) > timedelta(minutes=5):
            return credentials

        # Need to refresh
        creds = self._get_client_credentials(credentials.platform)
        refresh_url = self.REFRESH_URLS[credentials.platform]

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            try:
                if credentials.platform == "tiktok":
                    data = {
                        "client_key": creds["client_key"],
                        "client_secret": creds["client_secret"],
                        "grant_type": "refresh_token",
                        "refresh_token": credentials.refresh_token,
                    }
                    response = await client.post(refresh_url, data=data)
                elif credentials.platform == "instagram":
                    # Instagram refreshes by getting a new long-lived token
                    params = {
                        "grant_type": "ig_refresh_token",
                        "access_token": credentials.access_token,
                    }
                    response = await client.get(refresh_url, params=params)
                elif credentials.platform == "youtube":
                    data = {
                        "client_id": creds["client_id"],
                        "client_secret": creds["client_secret"],
                        "grant_type": "refresh_token",
                        "refresh_token": credentials.refresh_token,
                    }
                    response = await client.post(refresh_url, data=data)

                if response.status_code in (400, 401):
                    # Token expired or revoked
                    await self.revoke_credentials(credentials.platform, credentials.user_id)
                    raise TokenExpiredError(credentials.platform, credentials.user_id)

                response.raise_for_status()
                token_data = response.json()

                # Update credentials
                if credentials.platform == "tiktok":
                    new_access = token_data.get("data", {}).get("access_token", credentials.access_token)
                    new_refresh = token_data.get("data", {}).get("refresh_token", credentials.refresh_token)
                    expires_in = token_data.get("data", {}).get("expires_in", 86400)
                elif credentials.platform == "instagram":
                    new_access = token_data.get("access_token", credentials.access_token)
                    new_refresh = ""  # Instagram doesn't use refresh tokens
                    expires_in = token_data.get("expires_in", 5184000)
                elif credentials.platform == "youtube":
                    new_access = token_data.get("access_token", credentials.access_token)
                    new_refresh = token_data.get("refresh_token", credentials.refresh_token)
                    expires_in = token_data.get("expires_in", 3600)

                new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

                updated_creds = OAuthCredentials(
                    platform=credentials.platform,
                    user_id=credentials.user_id,
                    access_token=new_access,
                    refresh_token=new_refresh,
                    expires_at=new_expires_at,
                    scope=credentials.scope,
                    platform_user_id=credentials.platform_user_id,
                    platform_username=credentials.platform_username,
                )

                await self._save_credentials(updated_creds)
                return updated_creds

            except httpx.HTTPStatusError as e:
                if e.response.status_code in (400, 401):
                    await self.revoke_credentials(credentials.platform, credentials.user_id)
                    raise TokenExpiredError(credentials.platform, credentials.user_id)
                raise PlatformAuthError(credentials.platform, f"Refresh failed: {e.response.text}")
            except httpx.TimeoutException:
                raise PlatformAuthError(credentials.platform, "Token refresh timeout")

    async def _save_credentials(self, credentials: OAuthCredentials) -> None:
        """Save credentials to Redis with TTL based on expiry."""
        now = datetime.now(timezone.utc)
        expires_at = credentials.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        ttl = int((expires_at - now).total_seconds())
        if ttl < 0:
            ttl = 3600  # Default 1 hour if already expired

        key = f"oauth:{credentials.platform}:{credentials.user_id}"
        await self.redis.setex(key, ttl, credentials.__dict__)

    async def get_credentials(self, platform: str, user_id: str) -> Optional[OAuthCredentials]:
        """Get credentials from Redis, auto-refreshing if needed."""
        key = f"oauth:{platform}:{user_id}"
        data = await self.redis.get(key)

        if not data:
            return None

        # Reconstruct dataclass
        creds = OAuthCredentials(
            platform=data.get("platform", platform),
            user_id=data.get("user_id", user_id),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_at=datetime.fromisoformat(data.get("expires_at", "")),
            scope=data.get("scope", ""),
            platform_user_id=data.get("platform_user_id", ""),
            platform_username=data.get("platform_username", ""),
        )

        # Refresh if needed
        return await self.refresh_token_if_needed(creds)

    async def revoke_credentials(self, platform: str, user_id: str) -> bool:
        """Revoke credentials locally and on platform if possible."""
        # Delete from Redis first
        key = f"oauth:{platform}:{user_id}"
        data = await self.redis.get(key)
        await self.redis.delete(key)

        if not data:
            return False

        access_token = data.get("access_token", "")
        creds = self._get_client_credentials(platform)
        revoke_url = self.REVOKE_URLS.get(platform)

        if not revoke_url:
            return True  # Platform doesn't support revocation (Instagram)

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            try:
                if platform == "tiktok":
                    response = await client.post(
                        revoke_url,
                        json={
                            "client_key": creds["client_key"],
                            "client_secret": creds["client_secret"],
                            "token": access_token,
                        },
                    )
                elif platform == "youtube":
                    response = await client.post(
                        revoke_url,
                        data={
                            "token": access_token,
                            "client_id": creds["client_id"],
                            "client_secret": creds["client_secret"],
                        },
                    )

                response.raise_for_status()
                return True
            except httpx.HTTPError:
                # Log but don't fail — local credentials already deleted
                return True
