"""
TikTok API Integration — Auto-Upload Service
===============================================

Handles OAuth2 and video upload to TikTok via Content Posting API v2.

Usage:
    from services.tiktok_upload_service import TikTokUploadService
    
    service = TikTokUploadService()
    result = await service.upload_video(
        video_path="/app/clips/viral_001.mp4",
        title="Amazing Ocean Waves!",
        description="Watch these incredible waves...",
        credentials=user_credentials
    )

Environment:
    TIKTOK_CLIENT_KEY=your_client_key
    TIKTOK_CLIENT_SECRET=your_client_secret
    TIKTOK_REDIRECT_URI=http://localhost:8000/auth/tiktok/callback
"""
from __future__ import annotations

import os
import httpx
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from ..constants import TIKTOK_HASHTAG_LIMIT, YOUTUBE_TITLE_LENGTH
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# TikTok API configuration
TIKTOK_CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI", "http://localhost:8000/auth/tiktok/callback")


@dataclass
class TikTokCredentials:
    """TikTok OAuth2 credentials."""
    access_token: str
    refresh_token: str
    open_id: str  # TikTok user ID
    expires_at: datetime
    token_type: str = "Bearer"
    
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at - timedelta(minutes=5)


@dataclass
class TikTokUploadResult:
    """Result of TikTok upload."""
    success: bool
    video_id: Optional[str] = None
    share_url: Optional[str] = None
    error_message: Optional[str] = None
    upload_time_seconds: float = 0.0


@dataclass
class TikTokAnalytics:
    """TikTok video metrics."""
    video_id: str
    views: int
    likes: int
    comments: int
    shares: int
    play_time: float  # Total play time in seconds
    average_watch_time: float
    completion_rate: float  # Percentage who watched full video
    date_retrieved: datetime


class TikTokUploadService:
    """
    Service for uploading videos to TikTok via Content Posting API.
    """
    
    def __init__(self):
        self.api_base = "https://open-api.tiktok.com"
        self.auth_base = "https://open-api.tiktok.com/oauth"
    
    def get_oauth_url(self, state: str = "") -> str:
        """Generate TikTok OAuth URL."""
        from urllib.parse import urlencode
        
        scopes = [
            "video.upload",
            "video.list",
            "user.info.basic",
        ]
        
        params = {
            "client_key": TIKTOK_CLIENT_KEY,
            "redirect_uri": TIKTOK_REDIRECT_URI,
            "scope": ",".join(scopes),
            "response_type": "code",
            "state": state,
        }
        
        return f"{self.auth_base}/connect?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> TikTokCredentials:
        """Exchange auth code for tokens."""
        import httpx
        
        payload = {
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": TIKTOK_REDIRECT_URI,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_base}/oauth/access_token/",
                data=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        if data.get("error_code"):
            raise ValueError(f"TikTok auth error: {data}")
        
        access_info = data["data"]
        expires_in = access_info.get("expires_in", 86400)  # Default 24h
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        return TikTokCredentials(
            access_token=access_info["access_token"],
            refresh_token=access_info["refresh_token"],
            open_id=access_info["open_id"],
            expires_at=expires_at,
        )
    
    async def refresh_token(self, credentials: TikTokCredentials) -> TikTokCredentials:
        """Refresh expired access token."""
        import httpx
        
        payload = {
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh_token,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_base}/oauth/refresh_token/",
                data=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        if data.get("error_code"):
            raise ValueError(f"TikTok refresh error: {data}")
        
        access_info = data["data"]
        expires_at = datetime.utcnow() + timedelta(seconds=access_info["expires_in"])
        
        return TikTokCredentials(
            access_token=access_info["access_token"],
            refresh_token=access_info.get("refresh_token", credentials.refresh_token),
            open_id=credentials.open_id,
            expires_at=expires_at,
        )
    
    async def _ensure_valid_token(self, credentials: TikTokCredentials) -> TikTokCredentials:
        """Refresh if expired."""
        if credentials.is_expired():
            logger.info("[TikTok] Token expired, refreshing...")
            return await self.refresh_token(credentials)
        return credentials
    
    async def upload_video(
        self,
        video_path: Path | str,
        title: str,
        credentials: TikTokCredentials,
        description: str = "",
        privacy_level: str = "public",  # public, private, friends
        disable_duet: bool = False,
        disable_comment: bool = False,
        cover_image_path: Optional[Path] = None,
    ) -> TikTokUploadResult:
        """
        Upload video to TikTok via 3-step flow:
        1. Initialize upload
        2. Upload video file
        3. Publish video
        """
        import time
        import httpx
        
        start_time = time.time()
        credentials = await self._ensure_valid_token(credentials)
        
        try:
            # Step 1: Initialize upload
            logger.info("[TikTok] Step 1: Initialize upload")
            
            headers = {
                "Authorization": f"Bearer {credentials.access_token}",
                "Content-Type": "application/json",
            }
            
            init_payload = {
                "source_info": {
                    "source": "PULL_FROM_URL",  # Or FILE_UPLOAD
                    "video_url": "",  # For file upload, we'll use direct upload
                },
                "title": title[:100],  # TikTok limit
                "description": description[:150],
                "privacy_level": privacy_level,
                "disable_duet": disable_duet,
                "disable_comment": disable_comment,
            }
            
            # For actual implementation, use FILE_UPLOAD with direct binary
            # This is a simplified version using PULL_FROM_URL
            # Real implementation would use direct file upload endpoint
            
            async with httpx.AsyncClient() as client:
                # Initialize
                init_response = await client.post(
                    f"{self.api_base}/video/init/",
                    headers=headers,
                    json=init_payload,
                    timeout=30.0
                )
                init_response.raise_for_status()
                init_data = init_response.json()
                
                if init_data.get("error_code"):
                    raise ValueError(f"Init failed: {init_data}")
                
                publish_id = init_data["data"]["publish_id"]
                upload_url = init_data["data"]["upload_url"]
                
                # Step 2: Upload video binary
                logger.info("[TikTok] Step 2: Uploading video")
                
                with open(video_path, "rb") as f:
                    video_data = f.read()
                
                upload_headers = {
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{len(video_data)-1}/{len(video_data)}",
                }
                
                upload_response = await client.put(
                    upload_url,
                    headers=upload_headers,
                    content=video_data,
                    timeout=300.0,
                )
                upload_response.raise_for_status()
                
                # Step 3: Publish
                logger.info("[TikTok] Step 3: Publishing")
                
                publish_payload = {
                    "publish_id": publish_id,
                }
                
                publish_response = await client.post(
                    f"{self.api_base}/video/publish/",
                    headers=headers,
                    json=publish_payload,
                    timeout=30.0
                )
                publish_response.raise_for_status()
                publish_data = publish_response.json()
                
                if publish_data.get("error_code"):
                    raise ValueError(f"Publish failed: {publish_data}")
                
                upload_time = time.time() - start_time
                
                return TikTokUploadResult(
                    success=True,
                    video_id=publish_id,
                    share_url=f"https://tiktok.com/@user/video/{publish_id}",
                    upload_time_seconds=upload_time,
                )
                
        except Exception as e:
            logger.error(f"[TikTok] Upload failed: {e}")
            return TikTokUploadResult(
                success=False,
                error_message=str(e),
            )
    
    async def get_video_metrics(
        self,
        video_id: str,
        credentials: TikTokCredentials,
    ) -> Optional[TikTokAnalytics]:
        """Get video analytics from TikTok."""
        import httpx
        
        credentials = await self._ensure_valid_token(credentials)
        
        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_base}/video/query/",
                headers=headers,
                params={"filters": json.dumps({"video_ids": [video_id]})},
                timeout=30.0,
            )
            
            if response.status_code != 200:
                logger.error(f"[TikTok] Metrics fetch failed: {response.text}")
                return None
            
            data = response.json()
            
            if data.get("error_code") or not data.get("data", {}).get("list"):
                return None
            
            video_data = data["data"]["list"][0]
            
            return TikTokAnalytics(
                video_id=video_id,
                views=video_data.get("view_count", 0),
                likes=video_data.get("like_count", 0),
                comments=video_data.get("comment_count", 0),
                shares=video_data.get("share_count", 0),
                play_time=video_data.get("play_time", 0),
                average_watch_time=video_data.get("average_watch_time", 0),
                completion_rate=video_data.get("completion_rate", 0),
                date_retrieved=datetime.utcnow(),
            )


class TikTokAutoPublisher:
    """Automatic publisher for TikTok."""
    
    def __init__(self):
        self.upload_service = TikTokUploadService()
    
    async def publish_clip(
        self,
        clip_id: str,
        credentials: TikTokCredentials,
        publish_options: Dict[str, Any],
    ) -> TikTokUploadResult:
        """Publish a clip to TikTok."""
        from ...database import get_db
        from sqlalchemy import select
        from ...models import GeneratedClip
        
        async for db in get_db():
            result = await db.execute(
                select(GeneratedClip).where(GeneratedClip.id == clip_id)
            )
            clip = result.scalar_one_or_none()
            
            if not clip:
                return TikTokUploadResult(
                    success=False,
                    error_message=f"Clip not found: {clip_id}"
                )
            
            title = self._generate_title(clip)
            description = self._generate_description(clip)
            
            result = await self.upload_service.upload_video(
                video_path=Path(clip.file_path),
                title=title,
                credentials=credentials,
                description=description,
                privacy_level=publish_options.get("privacy", "public"),
                disable_duet=publish_options.get("disable_duet", False),
                disable_comment=publish_options.get("disable_comment", False),
            )
            
            if result.success:
                clip.tiktok_video_id = result.video_id
                await db.commit()
            
            return result
    
    def _generate_title(self, clip) -> str:
        """Generate TikTok title."""
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("title"):
                    return metadata["title"][:YOUTUBE_TITLE_LENGTH]
            except (json.JSONDecodeError, KeyError) as e:
                # FIX: Invalid metadata
                logger.debug(f"Failed to parse title from metadata: {e}")
                pass
        return clip.text[:YOUTUBE_TITLE_LENGTH] if clip.text else f"Viral Clip #{clip.clip_order}"
    
    def _generate_description(self, clip) -> str:
        """Generate TikTok description with hashtags."""
        lines = []
        
        if clip.text:
            lines.append(clip.text[:150])
        
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("hashtags"):
                    lines.append("\n" + " ".join(f"#{tag}" for tag in metadata["hashtags"][:TIKTOK_HASHTAG_LIMIT]))
            except (json.JSONDecodeError, KeyError) as e:
                # FIX: Invalid metadata
                logger.debug(f"Failed to parse hashtags from metadata: {e}")
                pass
        
        return "\n".join(lines)


__all__ = [
    "TikTokUploadService",
    "TikTokAutoPublisher",
    "TikTokCredentials",
    "TikTokUploadResult",
    "TikTokAnalytics",
]
