"""
YouTube API Integration — Auto-Upload Service
===============================================

Handles OAuth2 authentication and video upload to YouTube.
Supports title, description, tags, thumbnails, and privacy settings.

Usage:
    from services.youtube_upload_service import YouTubeUploadService
    
    service = YouTubeUploadService()
    result = await service.upload_video(
        video_path="/app/clips/viral_001.mp4",
        title="Amazing Ocean Waves!",
        description="Watch these incredible waves...",
        tags=["ocean", "waves", "viral"],
        privacy="public",
        credentials=user_credentials
    )

Environment:
    YOUTUBE_CLIENT_ID=your_client_id
    YOUTUBE_CLIENT_SECRET=your_client_secret
    YOUTUBE_REDIRECT_URI=http://localhost:8000/auth/youtube/callback
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# OAuth2 configuration
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REDIRECT_URI = os.environ.get("YOUTUBE_REDIRECT_URI", "http://localhost:8000/auth/youtube/callback")
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


@dataclass
class YouTubeCredentials:
    """YouTube OAuth2 credentials storage."""
    access_token: str
    refresh_token: str
    expires_at: datetime
    token_type: str = "Bearer"
    
    def is_expired(self) -> bool:
        """Check if token is expired or about to expire (5 min buffer)."""
        return datetime.now(timezone.utc) >= self.expires_at - timedelta(minutes=5)


@dataclass
class YouTubeUploadResult:
    """Result of YouTube upload operation."""
    success: bool
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    upload_time_seconds: float = 0.0


@dataclass
class YouTubeAnalytics:
    """YouTube video performance metrics."""
    video_id: str
    views: int
    likes: int
    comments: int
    estimated_minutes_watched: float
    average_view_duration: float
    ctr: float  # Click-through rate
    date_retrieved: datetime


class YouTubeUploadService:
    """
    Service for uploading videos to YouTube via Data API v3.
    """
    
    def __init__(self):
        self.api_base = "https://www.googleapis.com/youtube/v3"
        self.auth_base = "https://oauth2.googleapis.com"
        
    def get_oauth_url(self, state: str = "") -> str:
        """
        Generate OAuth2 authorization URL for user consent.
        
        Args:
            state: CSRF protection state parameter
            
        Returns:
            Full OAuth2 URL to redirect user to
        """
        from urllib.parse import urlencode
        
        params = {
            "client_id": YOUTUBE_CLIENT_ID,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "scope": " ".join(YOUTUBE_SCOPES),
            "response_type": "code",
            "access_type": "offline",  # Request refresh token
            "prompt": "consent",  # Force consent to get refresh token
            "state": state,
        }
        
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> YouTubeCredentials:
        """
        Exchange authorization code for access/refresh tokens.
        
        Args:
            code: Authorization code from OAuth callback
            
        Returns:
            YouTubeCredentials with tokens
        """
        import httpx
        
        payload = {
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": YOUTUBE_REDIRECT_URI,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.auth_base}/token",
                data=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        expires_in = data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        return YouTubeCredentials(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=expires_at,
            token_type=data.get("token_type", "Bearer"),
        )
    
    async def refresh_token(self, credentials: YouTubeCredentials) -> YouTubeCredentials:
        """
        Refresh expired access token using refresh token.
        
        Args:
            credentials: Current (expired) credentials
            
        Returns:
            New credentials with fresh access token
        """
        import httpx
        
        if not credentials.refresh_token:
            raise ValueError("No refresh token available")
        
        payload = {
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": credentials.refresh_token,
            "grant_type": "refresh_token",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.auth_base}/token",
                data=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        expires_in = data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        return YouTubeCredentials(
            access_token=data["access_token"],
            refresh_token=credentials.refresh_token,  # Keep original refresh token
            expires_at=expires_at,
            token_type=data.get("token_type", "Bearer"),
        )
    
    async def _ensure_valid_token(self, credentials: YouTubeCredentials) -> YouTubeCredentials:
        """Refresh token if expired."""
        if credentials.is_expired():
            logger.info("[YouTube] Access token expired, refreshing...")
            return await self.refresh_token(credentials)
        return credentials
    
    async def upload_video(
        self,
        video_path: Path | str,
        title: str,
        description: str,
        credentials: YouTubeCredentials,
        tags: List[str] = None,
        category_id: str = "22",  # 22 = People & Blogs
        privacy_status: str = "private",  # private, unlisted, public
        thumbnail_path: Optional[Path] = None,
        made_for_kids: bool = False,
    ) -> YouTubeUploadResult:
        """
        Upload a video to YouTube.
        
        Args:
            video_path: Path to video file
            title: Video title (max 100 chars)
            description: Video description (max 5000 chars)
            credentials: OAuth2 credentials
            tags: List of tags (max 500 chars total)
            category_id: YouTube category ID
            privacy_status: Privacy setting
            thumbnail_path: Optional thumbnail image
            made_for_kids: COPPA compliance flag
            
        Returns:
            YouTubeUploadResult with video ID or error
        """
        import time
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
        
        start_time = time.time()
        
        # Ensure valid token
        credentials = await self._ensure_valid_token(credentials)
        
        try:
            # Build YouTube API client
            creds = Credentials(
                token=credentials.access_token,
                refresh_token=credentials.refresh_token,
                token_uri=f"{self.auth_base}/token",
                client_id=YOUTUBE_CLIENT_ID,
                client_secret=YOUTUBE_CLIENT_SECRET,
                scopes=YOUTUBE_SCOPES,
            )
            
            youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
            
            # Prepare video metadata
            body = {
                "snippet": {
                    "title": title[:100],  # Max 100 chars
                    "description": description[:5000],  # Max 5000 chars
                    "tags": tags or [],
                    "categoryId": category_id,
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": made_for_kids,
                },
            }
            
            # Upload video
            media = MediaFileUpload(
                str(video_path),
                mimetype="video/mp4",
                resumable=True,
            )
            
            logger.info(f"[YouTube] Starting upload: {video_path}")
            
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
                notifySubscribers=True,
            )
            
            response = request.execute()
            video_id = response["id"]
            
            logger.info(f"[YouTube] Upload complete: {video_id}")
            
            # Upload thumbnail if provided
            if thumbnail_path and thumbnail_path.exists():
                try:
                    media_thumbnail = MediaFileUpload(
                        str(thumbnail_path),
                        mimetype="image/jpeg",
                    )
                    youtube.thumbnails().set(
                        videoId=video_id,
                        media_body=media_thumbnail,
                    ).execute()
                    logger.info(f"[YouTube] Thumbnail uploaded: {video_id}")
                except Exception as e:
                    logger.warning(f"[YouTube] Thumbnail upload failed: {e}")
            
            upload_time = time.time() - start_time
            
            return YouTubeUploadResult(
                success=True,
                video_id=video_id,
                video_url=f"https://youtube.com/watch?v={video_id}",
                upload_time_seconds=upload_time,
            )
            
        except HttpError as e:
            error_details = e.error_details if hasattr(e, 'error_details') else str(e)
            logger.error(f"[YouTube] Upload failed: {error_details}")
            return YouTubeUploadResult(
                success=False,
                error_message=str(error_details),
            )
        except Exception as e:
            logger.error(f"[YouTube] Unexpected error: {e}")
            return YouTubeUploadResult(
                success=False,
                error_message=str(e),
            )
    
    async def get_video_analytics(
        self,
        video_id: str,
        credentials: YouTubeCredentials,
        days_back: int = 30,
    ) -> Optional[YouTubeAnalytics]:
        """
        Retrieve video analytics from YouTube Analytics API.
        
        Args:
            video_id: YouTube video ID
            credentials: OAuth2 credentials
            days_back: How many days of data to fetch
            
        Returns:
            YouTubeAnalytics with performance metrics
        """
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        
        credentials = await self._ensure_valid_token(credentials)
        
        try:
            creds = Credentials(
                token=credentials.access_token,
                refresh_token=credentials.refresh_token,
                token_uri=f"{self.auth_base}/token",
                client_id=YOUTUBE_CLIENT_ID,
                client_secret=YOUTUBE_CLIENT_SECRET,
                scopes=YOUTUBE_SCOPES,
            )
            
            # Build Analytics API client
            youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
            
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
            
            response = youtube_analytics.reports().query(
                ids=f"channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,likes,comments,estimatedMinutesWatched,averageViewDuration,ctr",
                filters=f"video=={video_id}",
            ).execute()
            
            if not response.get("rows"):
                return None
            
            row = response["rows"][0]
            
            return YouTubeAnalytics(
                video_id=video_id,
                views=row[0],
                likes=row[1],
                comments=row[2],
                estimated_minutes_watched=row[3],
                average_view_duration=row[4],
                ctr=row[5],
                date_retrieved=datetime.now(timezone.utc),
            )
            
        except HttpError as e:
            logger.error(f"[YouTube] Analytics fetch failed: {e}")
            return None
        except Exception as e:
            logger.error(f"[YouTube] Unexpected analytics error: {e}")
            return None


class YouTubeAutoPublisher:
    """
    Automatic publisher that uploads clips to YouTube on completion.
    """
    
    def __init__(self):
        self.upload_service = YouTubeUploadService()
    
    async def publish_clip(
        self,
        clip_id: str,
        credentials: YouTubeCredentials,
        publish_options: Dict[str, Any],
    ) -> YouTubeUploadResult:
        """
        Publish a generated clip to YouTube.
        
        Args:
            clip_id: GeneratedClip.id
            credentials: User's YouTube credentials
            publish_options: {
                "privacy": "public|unlisted|private",
                "category": "22",
                "custom_title": "...",  # Optional override
                "custom_description": "...",  # Optional override
            }
        """
        from ...database import get_db
        from sqlalchemy import select
        from ...models import GeneratedClip
        
        # Fetch clip from database
        async for db in get_db():
            result = await db.execute(
                select(GeneratedClip).where(GeneratedClip.id == clip_id)
            )
            clip = result.scalar_one_or_none()
            
            if not clip:
                return YouTubeUploadResult(
                    success=False,
                    error_message=f"Clip not found: {clip_id}"
                )
            
            # Get metadata
            title = publish_options.get("custom_title") or self._generate_title(clip)
            description = publish_options.get("custom_description") or self._generate_description(clip)
            tags = self._extract_tags(clip)
            
            # Upload
            result = await self.upload_service.upload_video(
                video_path=Path(clip.file_path),
                title=title,
                description=description,
                credentials=credentials,
                tags=tags,
                privacy_status=publish_options.get("privacy", "private"),
                thumbnail_path=Path(clip.thumbnail_path) if clip.thumbnail_path else None,
            )
            
            # Store result in database
            if result.success:
                clip.platform_urls = clip.platform_urls or {}
                clip.platform_urls["youtube"] = result.video_url
                clip.youtube_video_id = result.video_id
                await db.commit()
            
            return result
    
    def _generate_title(self, clip: Any) -> str:
        """Generate YouTube title from clip metadata."""
        # Use viral metadata if available
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("title"):
                    return metadata["title"]
            except:
                pass
        
        # Fallback: Use transcript text
        if clip.text:
            # First sentence or first 60 chars
            title = clip.text.split(".")[0][:60]
            return title
        
        return f"Viral Clip #{clip.clip_order}"
    
    def _generate_description(self, clip: Any) -> str:
        """Generate YouTube description from clip metadata."""
        lines = []
        
        # Use viral metadata if available
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("description"):
                    lines.append(metadata["description"])
            except:
                pass
        
        # Add transcript
        if clip.text:
            lines.append("\n📝 Transcript:")
            lines.append(clip.text[:500])  # First 500 chars
        
        # Add virality info
        lines.append(f"\n🔥 Virality Score: {clip.virality_score or 'N/A'}/100")
        if clip.strategic_advice:
            lines.append(f"💡 Why this works: {clip.strategic_advice}")
        
        # Add hashtags
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("hashtags"):
                    lines.append("\n#" + " #".join(metadata["hashtags"][:10]))
            except:
                pass
        
        # Footer
        lines.append("\n---")
        lines.append("🎬 Created with ViraClip AI")
        
        return "\n".join(lines)
    
    def _extract_tags(self, clip: Any) -> List[str]:
        """Extract YouTube tags from clip metadata."""
        tags = []
        
        # From viral metadata
        if clip.clip_metadata:
            try:
                metadata = json.loads(clip.clip_metadata)
                if metadata.get("hashtags"):
                    tags.extend(metadata["hashtags"])
            except:
                pass
        
        # Default tags
        tags.extend(["viral", "shorts", "trending", "viraclip"])
        
        return tags[:15]  # YouTube allows max 500 chars total


__all__ = [
    "YouTubeUploadService",
    "YouTubeAutoPublisher",
    "YouTubeCredentials",
    "YouTubeUploadResult",
    "YouTubeAnalytics",
]
