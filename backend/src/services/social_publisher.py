"""
Direct Social Publishing — TikTok v2, Instagram Graph API, YouTube Data API.

Handles video upload, caption generation, scheduling, and status polling.
API keys/tokens are read from environment variables; never hardcoded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class Platform(str, Enum):
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"


class PublishStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    FAILED = "failed"


@dataclass
class PublishResult:
    platform: str
    status: PublishStatus
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    scheduled_at: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class PublishRequest:
    video_path: str
    caption: str
    platform: Platform
    hashtags: List[str] = field(default_factory=list)
    schedule_iso: Optional[str] = None    # ISO-8601 timestamp for scheduling
    cover_image_path: Optional[str] = None
    title: Optional[str] = None           # YouTube only
    privacy: str = "public"               # public | friends | private


# ── Optimal posting time helpers ─────────────────────────────────────────────

# Research-based best hours (UTC) per platform/day
_BEST_HOURS: Dict[str, List[int]] = {
    "tiktok":    [6, 10, 19, 21],
    "instagram": [8, 11, 17, 19],
    "youtube":   [14, 15, 16, 20],
}

def get_optimal_post_time(platform: str, timezone_offset_hours: float = 0) -> str:
    """Return next optimal posting time as ISO-8601 string (UTC)."""
    import datetime
    now = datetime.datetime.utcnow()
    best = _BEST_HOURS.get(platform.lower(), [12, 18])
    local_hour = (now.hour + timezone_offset_hours) % 24

    # Find next best hour
    next_hour = None
    for h in sorted(best):
        if h > local_hour:
            next_hour = h
            break
    if next_hour is None:
        next_hour = best[0]
        now += datetime.timedelta(days=1)

    post_time = now.replace(
        hour=int((next_hour - timezone_offset_hours) % 24),
        minute=0, second=0, microsecond=0
    )
    return post_time.isoformat() + "Z"


# ── TikTok Publisher ──────────────────────────────────────────────────────────

async def _publish_tiktok(req: PublishRequest) -> PublishResult:
    """
    Publish via TikTok Content Posting API v2.
    Requires TIKTOK_ACCESS_TOKEN env var.
    Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
    """
    token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
    if not token:
        return PublishResult(
            platform="tiktok",
            status=PublishStatus.FAILED,
            error="TIKTOK_ACCESS_TOKEN not set",
        )

    try:
        import aiohttp
        video_size = Path(req.video_path).stat().st_size
        caption = req.caption
        if req.hashtags:
            caption += " " + " ".join(f"#{h.lstrip('#')}" for h in req.hashtags)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        # Step 1: Init upload
        init_payload = {
            "post_info": {
                "title": caption[:2200],
                "privacy_level": req.privacy.upper(),
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,
                "total_chunk_count": 1,
            },
        }
        if req.schedule_iso:
            import datetime
            ts = int(datetime.datetime.fromisoformat(
                req.schedule_iso.replace("Z", "+00:00")
            ).timestamp())
            init_payload["post_info"]["scheduled_publish_time"] = ts

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://open.tiktokapis.com/v2/post/publish/video/init/",
                headers=headers,
                json=init_payload,
            ) as resp:
                init_data = await resp.json()

            if "error" in init_data and init_data["error"].get("code") != "ok":
                return PublishResult(
                    platform="tiktok", status=PublishStatus.FAILED,
                    error=str(init_data["error"]), raw_response=init_data,
                )

            upload_url = init_data.get("data", {}).get("upload_url", "")
            publish_id = init_data.get("data", {}).get("publish_id", "")

            # Step 2: Upload video bytes
            with open(req.video_path, "rb") as f:
                video_data = f.read()

            upload_headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(video_size),
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            }
            async with session.put(
                upload_url, data=video_data, headers=upload_headers
            ) as upload_resp:
                if upload_resp.status not in (200, 201, 206):
                    return PublishResult(
                        platform="tiktok", status=PublishStatus.FAILED,
                        error=f"Upload failed: HTTP {upload_resp.status}",
                    )

        status = PublishStatus.SCHEDULED if req.schedule_iso else PublishStatus.PROCESSING
        return PublishResult(
            platform="tiktok",
            status=status,
            post_id=publish_id,
            scheduled_at=req.schedule_iso,
            raw_response=init_data,
        )

    except Exception as exc:
        logger.exception("[tiktok] publish failed")
        return PublishResult(
            platform="tiktok", status=PublishStatus.FAILED, error=str(exc)
        )


# ── Instagram Publisher ───────────────────────────────────────────────────────

async def _publish_instagram(req: PublishRequest) -> PublishResult:
    """
    Publish via Instagram Graph API (Reels).
    Requires INSTAGRAM_ACCESS_TOKEN + INSTAGRAM_ACCOUNT_ID env vars.
    The video must be publicly accessible (requires a CDN URL).
    """
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    cdn_base = os.environ.get("VIRACLIP_CDN_URL", "")

    if not token or not account_id:
        return PublishResult(
            platform="instagram", status=PublishStatus.FAILED,
            error="INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_ACCOUNT_ID not set",
        )

    try:
        import aiohttp
        caption = req.caption
        if req.hashtags:
            caption += "\n\n" + " ".join(f"#{h.lstrip('#')}" for h in req.hashtags)

        video_filename = Path(req.video_path).name
        video_url = f"{cdn_base.rstrip('/')}/{video_filename}" if cdn_base else ""

        if not video_url:
            return PublishResult(
                platform="instagram", status=PublishStatus.FAILED,
                error="VIRACLIP_CDN_URL not set — Instagram requires a public video URL",
            )

        base = f"https://graph.facebook.com/v19.0/{account_id}"
        async with aiohttp.ClientSession() as session:
            # Step 1: Create media container
            container_payload = {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption[:2200],
                "access_token": token,
            }
            if req.cover_image_path:
                container_payload["thumb_offset"] = "0"

            async with session.post(
                f"{base}/media", data=container_payload
            ) as resp:
                container_data = await resp.json()

            container_id = container_data.get("id")
            if not container_id:
                return PublishResult(
                    platform="instagram", status=PublishStatus.FAILED,
                    error=str(container_data), raw_response=container_data,
                )

            # Step 2: Publish container
            publish_payload = {
                "creation_id": container_id,
                "access_token": token,
            }
            async with session.post(
                f"{base}/media_publish", data=publish_payload
            ) as resp:
                pub_data = await resp.json()

        post_id = pub_data.get("id", "")
        return PublishResult(
            platform="instagram",
            status=PublishStatus.PUBLISHED if post_id else PublishStatus.FAILED,
            post_id=post_id,
            post_url=f"https://www.instagram.com/reel/{post_id}/" if post_id else None,
            raw_response=pub_data,
        )

    except Exception as exc:
        logger.exception("[instagram] publish failed")
        return PublishResult(
            platform="instagram", status=PublishStatus.FAILED, error=str(exc)
        )


# ── YouTube Publisher ─────────────────────────────────────────────────────────

async def _publish_youtube(req: PublishRequest) -> PublishResult:
    """
    Publish via YouTube Data API v3 (resumable upload).
    Requires YOUTUBE_ACCESS_TOKEN env var (OAuth2 bearer).
    """
    token = os.environ.get("YOUTUBE_ACCESS_TOKEN", "")
    if not token:
        return PublishResult(
            platform="youtube", status=PublishStatus.FAILED,
            error="YOUTUBE_ACCESS_TOKEN not set",
        )

    try:
        import aiohttp
        title = req.title or req.caption[:100]
        description = req.caption
        if req.hashtags:
            description += "\n\n" + " ".join(f"#{h.lstrip('#')}" for h in req.hashtags)

        tags = [h.lstrip("#") for h in req.hashtags]
        video_size = Path(req.video_path).stat().st_size

        metadata = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:30],
                "categoryId": "22",   # People & Blogs
            },
            "status": {
                "privacyStatus": req.privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(video_size),
            "Content-Type": "application/json; charset=UTF-8",
        }

        async with aiohttp.ClientSession() as session:
            # Step 1: Initiate resumable upload
            async with session.post(
                "https://www.googleapis.com/upload/youtube/v3/videos"
                "?uploadType=resumable&part=snippet,status",
                headers=headers,
                json=metadata,
            ) as resp:
                upload_url = resp.headers.get("Location", "")
                if not upload_url:
                    err = await resp.text()
                    return PublishResult(
                        platform="youtube", status=PublishStatus.FAILED,
                        error=f"Failed to get upload URL: {err}",
                    )

            # Step 2: Upload video
            with open(req.video_path, "rb") as f:
                video_data = f.read()

            async with session.put(
                upload_url,
                data=video_data,
                headers={"Content-Type": "video/mp4", "Content-Length": str(video_size)},
            ) as upload_resp:
                upload_data = await upload_resp.json()

        video_id = upload_data.get("id", "")
        return PublishResult(
            platform="youtube",
            status=PublishStatus.PROCESSING if video_id else PublishStatus.FAILED,
            post_id=video_id,
            post_url=f"https://youtu.be/{video_id}" if video_id else None,
            raw_response=upload_data,
        )

    except Exception as exc:
        logger.exception("[youtube] publish failed")
        return PublishResult(
            platform="youtube", status=PublishStatus.FAILED, error=str(exc)
        )


# ── Public API ────────────────────────────────────────────────────────────────

async def publish_clip(req: PublishRequest) -> PublishResult:
    """Route publish request to the correct platform handler."""
    handlers = {
        Platform.TIKTOK: _publish_tiktok,
        Platform.INSTAGRAM: _publish_instagram,
        Platform.YOUTUBE: _publish_youtube,
    }
    handler = handlers.get(req.platform)
    if not handler:
        return PublishResult(
            platform=str(req.platform),
            status=PublishStatus.FAILED,
            error=f"Unsupported platform: {req.platform}",
        )
    return await handler(req)


async def publish_to_all(
    video_path: str,
    caption: str,
    hashtags: Optional[List[str]] = None,
    platforms: Optional[List[str]] = None,
    schedule_iso: Optional[str] = None,
) -> List[PublishResult]:
    """Publish to multiple platforms concurrently."""
    _platforms = platforms or ["tiktok", "instagram", "youtube"]
    _hashtags = hashtags or []

    requests = [
        PublishRequest(
            video_path=video_path,
            caption=caption,
            platform=Platform(p),
            hashtags=_hashtags,
            schedule_iso=schedule_iso,
        )
        for p in _platforms
        if p in Platform.__members__.values() or p in [e.value for e in Platform]
    ]

    results = await asyncio.gather(
        *[publish_clip(r) for r in requests], return_exceptions=True
    )

    out: List[PublishResult] = []
    for r in results:
        if isinstance(r, Exception):
            out.append(PublishResult(
                platform="unknown", status=PublishStatus.FAILED, error=str(r)
            ))
        else:
            out.append(r)
    return out
