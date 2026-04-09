"""
Instagram Graph API Integration — Reels Auto-Upload
====================================================

Uploads videos to Instagram Reels via Graph API.

Usage:
    from services.instagram_upload_service import InstagramUploadService
    
    service = InstagramUploadService()
    result = await service.upload_reel(
        video_path="/app/clips/viral_001.mp4",
        caption="Amazing ocean waves! 🌊",
        credentials=user_credentials
    )

Environment:
    INSTAGRAM_APP_ID=your_app_id
    INSTAGRAM_APP_SECRET=your_app_secret
    INSTAGRAM_REDIRECT_URI=http://localhost:8000/auth/instagram/callback
"""
from __future__ import annotations

import httpx
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from ..constants import INSTAGRAM_HASHTAG_LIMIT
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

INSTAGRAM_APP_ID = os.environ.get("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET = os.environ.get("INSTAGRAM_APP_SECRET", "")
INSTAGRAM_REDIRECT_URI = os.environ.get("INSTAGRAM_REDIRECT_URI", "http://localhost:8000/auth/instagram/callback")


@dataclass
class InstagramCredentials:
    """Instagram Graph API credentials."""
    access_token: str
    user_id: str  # Instagram Business/Creator Account ID
    expires_at: datetime
    token_type: str = "Bearer"
    
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at - timedelta(minutes=5)


@dataclass
class InstagramUploadResult:
    """Result of Instagram upload."""
    success: bool
    media_id: Optional[str] = None
    permalink: Optional[str] = None
    error_message: Optional[str] = None
    upload_time_seconds: float = 0.0


@dataclass
class InstagramInsights:
    """Instagram post metrics."""
    media_id: str
    impressions: int
    reach: int
    engagement: int
    likes: int
    comments: int
    shares: int
    saves: int
    video_views: int
    date_retrieved: datetime


class InstagramUploadService:
    """Service for uploading Reels to Instagram via Graph API."""
    
    def __init__(self):
        self.graph_base = "https://graph.facebook.com/v18.0"
    
    def get_oauth_url(self, state: str = "") -> str:
        """Generate Instagram OAuth URL."""
        from urllib.parse import urlencode
        
        scopes = [
            "instagram_basic",
            "instagram_content_publish",
            "pages_read_engagement",
        ]
        
        params = {
            "client_id": INSTAGRAM_APP_ID,
            "redirect_uri": INSTAGRAM_REDIRECT_URI,
            "scope": ",".join(scopes),
            "response_type": "code",
            "state": state,
        }
        
        return f"https://www.facebook.com/v18.0/dialog/oauth?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange code for access token and get IG account."""
        import httpx
        
        # Step 1: Exchange code for token
        token_payload = {
            "client_id": INSTAGRAM_APP_ID,
            "client_secret": INSTAGRAM_APP_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": INSTAGRAM_REDIRECT_URI,
        }
        
        async with httpx.AsyncClient() as client:
            token_response = await client.get(
                f"{self.graph_base}/oauth/access_token",
                params=token_payload,
                timeout=30.0,
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            
            access_token = token_data["access_token"]
            
            # Step 2: Get Instagram Business Account ID
            me_response = await client.get(
                f"{self.graph_base}/me",
                params={
                    "access_token": access_token,
                    "fields": "instagram_business_account",
                },
                timeout=30.0,
            )
            me_response.raise_for_status()
            me_data = me_response.json()
            
            ig_account = me_data.get("instagram_business_account", {}).get("id")
            
            if not ig_account:
                raise ValueError("No Instagram Business Account linked")
            
            expires_at = datetime.utcnow() + timedelta(days=60)  # Long-lived tokens
            
            return InstagramCredentials(
                access_token=access_token,
                user_id=ig_account,
                expires_at=expires_at,
            )
    
    async def upload_reel(
        self,
        video_path: Path | str,
        caption: str,
        credentials: InstagramCredentials,
        share_to_feed: bool = True,
        thumb_offset: int = 0,  # Thumbnail time offset in ms
    ) -> InstagramUploadResult:
        """
        Upload a Reel to Instagram.
        
        Flow:
        1. Create media container (reel)
        2. Upload video
        3. Publish container
        """
        import time
        import httpx
        
        start_time = time.time()
        
        try:
            video_url = self._get_video_url(video_path)
            
            async with httpx.AsyncClient() as client:
                # Step 1: Create media container
                logger.info("[Instagram] Step 1: Creating media container")
                
                container_payload = {
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption[:2200],  # Instagram limit
                    "access_token": credentials.access_token,
                }
                
                if thumb_offset > 0:
                    container_payload["thumb_offset"] = thumb_offset
                
                container_response = await client.post(
                    f"{self.graph_base}/{credentials.user_id}/media",
                    data=container_payload,
                    timeout=30.0,
                )
                container_response.raise_for_status()
                container_data = container_response.json()
                
                if "error" in container_data:
                    raise ValueError(f"Container creation failed: {container_data['error']}")
                
                creation_id = container_data["id"]
                
                # Step 2: Wait for processing (poll status)
                logger.info("[Instagram] Step 2: Waiting for processing")
                
                max_wait = 300  # 5 minutes
                wait_interval = 5
                waited = 0
                
                while waited < max_wait:
                    status_response = await client.get(
                        f"{self.graph_base}/{creation_id}",
                        params={
                            "fields": "status_code",
                            "access_token": credentials.access_token,
                        },
                        timeout=30.0,
                    )
                    status_data = status_response.json()
                    
                    status = status_data.get("status_code", "UNKNOWN")
                    
                    if status == "FINISHED":
                        break
                    elif status == "ERROR":
                        raise ValueError(f"Video processing failed: {status_data}")
                    
                    await asyncio.sleep(wait_interval)
                    waited += wait_interval
                    logger.debug(f"[Instagram] Processing... {waited}s elapsed")
                
                # Step 3: Publish
                logger.info("[Instagram] Step 3: Publishing")
                
                publish_payload = {
                    "creation_id": creation_id,
                    "access_token": credentials.access_token,
                    "share_to_feed": share_to_feed,
                }
                
                publish_response = await client.post(
                    f"{self.graph_base}/{credentials.user_id}/media_publish",
                    data=publish_payload,
                    timeout=30.0,
                )
                publish_response.raise_for_status()
                publish_data = publish_response.json()
                
                if "error" in publish_data:
                    raise ValueError(f"Publish failed: {publish_data['error']}")
                
                media_id = publish_data["id"]
                
                upload_time = time.time() - start_time
                
                return InstagramUploadResult(
                    success=True,
                    media_id=media_id,
                    permalink=f"https://instagram.com/p/{media_id}",
                    upload_time_seconds=upload_time,
                )
                
        except Exception as e:
            logger.error(f"[Instagram] Upload failed: {e}")
            return InstagramUploadResult(
                success=False,
                error_message=str(e),
            )
    
    def _get_video_url(self, video_path: Path | str) -> str:
        """
        Get publicly accessible URL for video.
        
        For production, this would upload to a CDN (S3, etc.) and return URL.
        For development, use a temporary file server.
        """
        # Placeholder: In production, upload to S3/CDN
        # For now, assume file is accessible at a base URL
        base_url = os.environ.get("CDN_BASE_URL", "https://temp-cdn.example.com")
        filename = Path(video_path).name
        return f"{base_url}/clips/{filename}"
    
    async def get_insights(
        self,
        media_id: str,
        credentials: InstagramCredentials,
    ) -> Optional[InstagramInsights]:
        """Get post insights/analytics."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.graph_base}/{media_id}/insights",
                params={
                    "metric": "impressions,reach,engagement,likes,comments,shares,saves,video_views",
                    "access_token": credentials.access_token,
                },
                timeout=30.0,
            )
            
            if response.status_code != 200:
                logger.error(f"[Instagram] Insights fetch failed: {response.text}")
                return None
            
            data = response.json()
            
            if "error" in data:
                return None
            
            metrics = {m["name"]: m["values"][0]["value"] for m in data.get("data", [])}
            
            return InstagramInsights(
                media_id=media_id,
                impressions=metrics.get("impressions", 0),
                reach=metrics.get("reach", 0),
                engagement=metrics.get("engagement", 0),
                likes=metrics.get("likes", 0),
                comments=metrics.get("comments", 0),
                shares=metrics.get("shares", 0),
                saves=metrics.get("saves", 0),
                video_views=metrics.get("video_views", 0),
                date_retrieved=datetime.utcnow(),
            )


class InstagramAutoPublisher:
    """Automatic publisher for Instagram."""
    
    def __init__(self):
        self.upload_service = InstagramUploadService()
    
    async def publish_clip(
        self,
        clip_id: str,
        credentials: InstagramCredentials,
        publish_options: Dict[str, Any],
    ) -> InstagramUploadResult:
        """Publish a clip to Instagram."""
        from ...database import get_db
        from sqlalchemy import select
        from ...models import GeneratedClip
        
        async for db in get_db():
            result = await db.execute(
                select(GeneratedClip).where(GeneratedClip.id == clip_id)
            )
            clip = result.scalar_one_or_none()
            
            if not clip:
                return InstagramUploadResult(
                    success=False,
                    error_message=f"Clip not found: {clip_id}"
                )
            
            caption = self._generate_caption(clip)
            
            result = await self.upload_service.upload_reel(
                video_path=Path(clip.file_path),
                caption=caption,
                credentials=credentials,
                share_to_feed=publish_options.get("share_to_feed", True),
            )
            
            if result.success:
                clip.instagram_media_id = result.media_id
                await db.commit()
            
            return result
    
    def _generate_caption(self, clip) -> str:
        """Generate Instagram caption with hashtags."""
        lines = []
        
        # Main text
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("description"):
                    lines.append(metadata["description"])
                elif metadata.get("title"):
                    lines.append(metadata["title"])
            except (json.JSONDecodeError, KeyError) as e:
                # FIX: Invalid metadata
                logger.debug(f"Failed to parse caption from metadata: {e}")
                pass
        
        if not lines and clip.text:
            lines.append(clip.text[:150])
        
        # Hashtags
        hashtags = []
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("hashtags"):
                    hashtags = metadata["hashtags"][:INSTAGRAM_HASHTAG_LIMIT]
            except (json.JSONDecodeError, KeyError) as e:
                # FIX: Invalid metadata
                logger.debug(f"Failed to parse hashtags from metadata: {e}")
                pass
        
        if not hashtags:
            hashtags = ["viral", "reels", "trending", "viraclip"]
        
        lines.append("\n" + " ".join(f"#{tag}" for tag in hashtags))
        
        return "\n".join(lines)


__all__ = [
    "InstagramUploadService",
    "InstagramAutoPublisher",
    "InstagramCredentials",
    "InstagramUploadResult",
    "InstagramInsights",
]
