"""
Social Publisher Service — Publish clips to TikTok, Instagram, YouTube
=======================================================================

Handles video upload, scheduling, status polling, and retry logic.
All publishing operations are async using httpx and stored in Redis.

Redis key patterns:
  - publish_result:{clip_id}:{platform} → PublishResult (TTL 90 days)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from .social_auth_service import OAuthCredentials, SocialAuthService, TokenExpiredError

__all__ = [
    "PublishRequest",
    "PublishResult",
    "SocialPublisherService",
    "PublishError",
]

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """Raised when publishing to a platform fails."""
    def __init__(self, platform: str, message: str):
        self.platform = platform
        super().__init__(f"{platform} publish error: {message}")


@dataclass
class PublishRequest:
    clip_id: str
    user_id: str
    platform: str
    cdn_url: str
    title: str
    description: str
    hashtags: list[str]
    cover_time_offset: float = 0.0
    privacy: str = "public"          # "public" | "private" | "friends"
    schedule_at: Optional[datetime] = None


@dataclass
class PublishResult:
    clip_id: str
    platform: str
    status: str     # "published" | "scheduled" | "failed" | "pending"
    platform_post_id: Optional[str]
    platform_url: Optional[str]
    error_message: Optional[str]
    published_at: Optional[datetime]
    retry_count: int = 0


class SocialPublisherService:
    """Publish clips to social media platforms."""

    def __init__(self, redis_client, auth_service: SocialAuthService):
        self.redis = redis_client
        self.auth_service = auth_service
        self._httpx_timeout = 30.0

    async def publish(self, request: PublishRequest) -> PublishResult:
        """Publish a clip to the specified platform."""
        # Get credentials
        credentials = await self.auth_service.get_credentials(request.platform, request.user_id)
        if not credentials:
            result = PublishResult(
                clip_id=request.clip_id,
                platform=request.platform,
                status="failed",
                platform_post_id=None,
                platform_url=None,
                error_message=f"No credentials for {request.platform}",
                published_at=None,
                retry_count=0,
            )
            await self._save_result(result)
            return result

        # Route to platform-specific publisher
        try:
            if request.platform == "tiktok":
                result = await self._publish_tiktok(request, credentials)
            elif request.platform == "instagram":
                result = await self._publish_instagram(request, credentials)
            elif request.platform == "youtube":
                result = await self._publish_youtube(request, credentials)
            else:
                raise PublishError(request.platform, f"Unsupported platform: {request.platform}")
        except Exception as e:
            logger.error(f"[publish] {request.platform} failed for clip {request.clip_id}: {e}", exc_info=True)
            result = PublishResult(
                clip_id=request.clip_id,
                platform=request.platform,
                status="failed",
                platform_post_id=None,
                platform_url=None,
                error_message=str(e),
                published_at=None,
                retry_count=request.retry_count if hasattr(request, 'retry_count') else 0,
            )

        # Save result to Redis
        await self._save_result(result)
        return result

    async def _save_result(self, result: PublishResult) -> None:
        """Save publish result to Redis with 90 day TTL."""
        ttl = 90 * 24 * 3600  # 90 days
        key = f"publish_result:{result.clip_id}:{result.platform}"
        # Convert datetime to ISO format for serialization
        data = result.__dict__.copy()
        if data.get("published_at"):
            data["published_at"] = data["published_at"].isoformat()
        if data.get("schedule_at"):
            data["schedule_at"] = data["schedule_at"].isoformat()
        await self.redis.setex(key, ttl, data)

    async def _publish_tiktok(
        self, request: PublishRequest, credentials: OAuthCredentials
    ) -> PublishResult:
        """Publish to TikTok using Content Posting API v2."""
        privacy_map = {"public": "PUBLIC", "private": "PRIVATE", "friends": "FRIENDS"}
        privacy_level = privacy_map.get(request.privacy, "PUBLIC")

        # Step 1: Initialize video upload
        init_payload = {
            "source_type": "PULL_FROM_URL",
            "video_url": request.cdn_url,
            "title": request.title,
            "privacy_level": privacy_level,
            "video_cover_timestamp_ms": int(request.cover_time_offset * 1000),
        }

        headers = {"Authorization": f"Bearer {credentials.access_token}"}

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            try:
                init_response = await client.post(
                    "https://open.tiktokapis.com/v2/post/publish/video/init/",
                    headers=headers,
                    json=init_payload,
                )
                init_response.raise_for_status()
                init_data = init_response.json()

                publish_id = init_data.get("data", {}).get("publish_id")
                if not publish_id:
                    raise PublishError("tiktok", "No publish_id in init response")

            except httpx.HTTPStatusError as e:
                logger.error(f"[tiktok] Init failed for clip {request.clip_id}: {e.response.text}")
                raise PublishError("tiktok", f"Init failed: {e.response.text}")
            except httpx.TimeoutException:
                logger.error(f"[tiktok] Init timeout for clip {request.clip_id}")
                raise PublishError("tiktok", "Init timeout")

        # Step 2: Poll for status
        status_payload = {"publish_id": publish_id}
        max_poll_time = 120  # seconds
        poll_interval = 3    # seconds
        elapsed = 0

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            while elapsed < max_poll_time:
                try:
                    status_response = await client.post(
                        "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                        headers=headers,
                        json=status_payload,
                    )
                    status_response.raise_for_status()
                    status_data = status_response.json()

                    status = status_data.get("data", {}).get("status")

                    if status == "PUBLISH_COMPLETE":
                        share_url = status_data.get("data", {}).get("share_url", "")
                        return PublishResult(
                            clip_id=request.clip_id,
                            platform="tiktok",
                            status="published",
                            platform_post_id=publish_id,
                            platform_url=share_url,
                            error_message=None,
                            published_at=datetime.now(timezone.utc),
                        )
                    elif status == "FAILED":
                        fail_reason = status_data.get("data", {}).get("fail_reason", "Unknown")
                        raise PublishError("tiktok", f"Publish failed: {fail_reason}")

                except httpx.HTTPStatusError as e:
                    logger.error(f"[tiktok] Status poll failed: {e.response.text}")
                except httpx.TimeoutException:
                    logger.warning(f"[tiktok] Status poll timeout")

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

        # Timeout reached
        return PublishResult(
            clip_id=request.clip_id,
            platform="tiktok",
            status="pending",
            platform_post_id=publish_id,
            platform_url=None,
            error_message="Polling timeout, publish in progress",
            published_at=None,
        )

    async def _publish_instagram(
        self, request: PublishRequest, credentials: OAuthCredentials
    ) -> PublishResult:
        """Publish to Instagram using Graph API."""
        caption = f"{request.title}\n\n{request.description}"
        if request.hashtags:
            caption += "\n\n" + " ".join(f"#{tag}" for tag in request.hashtags)

        # Step 1: Create media container
        container_payload = {
            "media_type": "REELS",
            "video_url": request.cdn_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": credentials.access_token,
        }

        container_url = f"https://graph.instagram.com/v19.0/{credentials.platform_user_id}/media"

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            try:
                container_response = await client.post(container_url, data=container_payload)
                container_response.raise_for_status()
                container_data = container_response.json()

                container_id = container_data.get("id")
                if not container_id:
                    raise PublishError("instagram", f"No container_id: {container_data}")

            except httpx.HTTPStatusError as e:
                logger.error(f"[instagram] Container creation failed for clip {request.clip_id}: {e.response.text}")
                raise PublishError("instagram", f"Container failed: {e.response.text}")
            except httpx.TimeoutException:
                logger.error(f"[instagram] Container timeout for clip {request.clip_id}")
                raise PublishError("instagram", "Container timeout")

        # Step 2: Poll for container status
        status_url = f"https://graph.instagram.com/v19.0/{container_id}"
        max_poll_time = 180  # seconds
        poll_interval = 4    # seconds
        elapsed = 0

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            while elapsed < max_poll_time:
                try:
                    status_response = await client.get(
                        status_url,
                        params={"fields": "status_code", "access_token": credentials.access_token},
                    )
                    status_response.raise_for_status()
                    status_data = status_response.json()

                    status_code = status_data.get("status_code")

                    if status_code == "FINISHED":
                        # Step 3: Publish the container
                        publish_url = f"https://graph.instagram.com/v19.0/{credentials.platform_user_id}/media_publish"
                        publish_payload = {
                            "creation_id": container_id,
                            "access_token": credentials.access_token,
                        }
                        publish_response = await client.post(publish_url, data=publish_payload)
                        publish_response.raise_for_status()
                        publish_data = publish_response.json()

                        media_id = publish_data.get("id")
                        permalink = f"https://instagram.com/reel/{media_id}" if media_id else ""

                        return PublishResult(
                            clip_id=request.clip_id,
                            platform="instagram",
                            status="published",
                            platform_post_id=media_id,
                            platform_url=permalink,
                            error_message=None,
                            published_at=datetime.now(timezone.utc),
                        )
                    elif status_code == "ERROR":
                        raise PublishError("instagram", "Container processing failed")

                except httpx.HTTPStatusError as e:
                    logger.error(f"[instagram] Status poll failed: {e.response.text}")
                except httpx.TimeoutException:
                    logger.warning(f"[instagram] Status poll timeout")

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

        # Timeout reached
        return PublishResult(
            clip_id=request.clip_id,
            platform="instagram",
            status="pending",
            platform_post_id=container_id,
            platform_url=None,
            error_message="Polling timeout, publish in progress",
            published_at=None,
        )

    async def _publish_youtube(
        self, request: PublishRequest, credentials: OAuthCredentials
    ) -> PublishResult:
        """Publish to YouTube using Data API v3 resumable upload."""
        privacy_map = {"public": "public", "private": "private", "friends": "unlisted"}
        privacy_status = privacy_map.get(request.privacy, "public")

        # Build metadata
        metadata = {
            "snippet": {
                "title": request.title[:100],  # YouTube title limit
                "description": f"{request.description}\n\n{' '.join(f'#{tag}' for tag in request.hashtags)}",
                "tags": request.hashtags[:15],  # Max 15 tags
            },
            "status": {
                "privacyStatus": privacy_status,
            },
        }

        # Step 1: Initiate resumable upload
        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "Content-Type": "application/json",
            "X-Upload-Content-Type": "video/*",
        }

        async with httpx.AsyncClient(timeout=self._httpx_timeout) as client:
            try:
                init_response = await client.post(
                    "https://www.googleapis.com/upload/youtube/v3/videos",
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers=headers,
                    json=metadata,
                )
                init_response.raise_for_status()
                upload_url = init_response.headers.get("Location")
                if not upload_url:
                    raise PublishError("youtube", "No upload URL in response")
            except httpx.HTTPStatusError as e:
                logger.error(f"[youtube] Upload init failed for clip {request.clip_id}: {e.response.text}")
                raise PublishError("youtube", f"Upload init failed: {e.response.text}")
            except httpx.TimeoutException:
                logger.error(f"[youtube] Upload init timeout for clip {request.clip_id}")
                raise PublishError("youtube", "Upload init timeout")

        # Step 2: Download from CDN and upload in chunks
        chunk_size = 8 * 1024 * 1024  # 8MB chunks
        uploaded_bytes = 0

        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                # Get video size first
                head_response = await client.head(request.cdn_url)
                total_bytes = int(head_response.headers.get("content-length", 0))

                # Stream download and upload
                async with client.stream("GET", request.cdn_url) as stream:
                    buffer = b""
                    async for chunk in stream.aiter_bytes(chunk_size=1024 * 1024):
                        buffer += chunk
                        if len(buffer) >= chunk_size:
                            # Upload chunk
                            chunk_end = uploaded_bytes + len(buffer) - 1
                            if total_bytes:
                                content_range = f"bytes {uploaded_bytes}-{chunk_end}/{total_bytes}"
                            else:
                                content_range = f"bytes {uploaded_bytes}-{chunk_end}/*"

                            upload_response = await client.put(
                                upload_url,
                                headers={
                                    "Content-Range": content_range,
                                    "Content-Type": "video/*",
                                },
                                content=buffer,
                            )

                            if upload_response.status_code in (200, 201):
                                # Upload complete
                                result_data = upload_response.json()
                                video_id = result_data.get("id")
                                video_url = f"https://youtube.com/watch?v={video_id}" if video_id else ""

                                return PublishResult(
                                    clip_id=request.clip_id,
                                    platform="youtube",
                                    status="published",
                                    platform_post_id=video_id,
                                    platform_url=video_url,
                                    error_message=None,
                                    published_at=datetime.now(timezone.utc),
                                )
                            elif upload_response.status_code == 308:
                                # Resume Incomplete - continue
                                range_header = upload_response.headers.get("Range", "")
                                if range_header:
                                    # Parse bytes=0-{last_byte}
                                    uploaded_bytes = int(range_header.split("-")[1]) + 1
                                else:
                                    uploaded_bytes += len(buffer)
                                buffer = b""
                            else:
                                upload_response.raise_for_status()

                    # Upload final chunk
                    if buffer:
                        chunk_end = uploaded_bytes + len(buffer) - 1
                        if total_bytes:
                            content_range = f"bytes {uploaded_bytes}-{chunk_end}/{total_bytes}"
                        else:
                            content_range = f"bytes {uploaded_bytes}-{chunk_end}/*"

                        final_response = await client.put(
                            upload_url,
                            headers={
                                "Content-Range": content_range,
                                "Content-Type": "video/*",
                            },
                            content=buffer,
                        )
                        final_response.raise_for_status()

                        if final_response.status_code in (200, 201):
                            result_data = final_response.json()
                            video_id = result_data.get("id")
                            video_url = f"https://youtube.com/watch?v={video_id}" if video_id else ""

                            return PublishResult(
                                clip_id=request.clip_id,
                                platform="youtube",
                                status="published",
                                platform_post_id=video_id,
                                platform_url=video_url,
                                error_message=None,
                                published_at=datetime.now(timezone.utc),
                            )

            except httpx.HTTPStatusError as e:
                logger.error(f"[youtube] Upload failed for clip {request.clip_id}: {e.response.text}")
                raise PublishError("youtube", f"Upload failed: {e.response.text}")
            except httpx.TimeoutException:
                logger.error(f"[youtube] Upload timeout for clip {request.clip_id}")
                raise PublishError("youtube", "Upload timeout")

        raise PublishError("youtube", "Upload completed but no video ID received")

    async def get_publish_status(self, clip_id: str, platform: str) -> Optional[PublishResult]:
        """Get publish status from Redis."""
        key = f"publish_result:{clip_id}:{platform}"
        data = await self.redis.get(key)

        if not data:
            return None

        # Parse ISO datetime strings back to datetime objects
        if data.get("published_at"):
            data["published_at"] = datetime.fromisoformat(data["published_at"])

        return PublishResult(**data)

    async def retry_failed(self, clip_id: str, platform: str, user_id: str) -> PublishResult:
        """Retry a failed publish."""
        # Get previous result
        prev_result = await self.get_publish_status(clip_id, platform)
        if not prev_result:
            return PublishResult(
                clip_id=clip_id,
                platform=platform,
                status="failed",
                platform_post_id=None,
                platform_url=None,
                error_message="No previous publish found",
                published_at=None,
                retry_count=0,
            )

        # Check retry limit
        if prev_result.retry_count >= 3:
            return PublishResult(
                clip_id=clip_id,
                platform=platform,
                status="failed",
                platform_post_id=prev_result.platform_post_id,
                platform_url=prev_result.platform_url,
                error_message="Max retries exceeded",
                published_at=prev_result.published_at,
                retry_count=prev_result.retry_count,
            )

        # Create new request from previous result (we need to reconstruct it)
        # Note: The actual request data should be stored separately or passed in
        # For now, we'll create a minimal request with the clip_id
        # In production, you'd want to store the original request
        logger.info(f"[retry_failed] Retrying {platform} publish for clip {clip_id} (attempt {prev_result.retry_count + 1})")

        # Return a result indicating retry was attempted
        # In a real implementation, you'd reconstruct the PublishRequest from stored data
        return PublishResult(
            clip_id=clip_id,
            platform=platform,
            status="failed",
            platform_post_id=None,
            platform_url=None,
            error_message="Retry requires original request data - not implemented",
            published_at=None,
            retry_count=prev_result.retry_count + 1,
        )
