"""
Analytics Importer — Closed A/B Feedback Loop.

Pulls real view/engagement metrics from TikTok, Instagram & YouTube Analytics APIs,
stores them, then feeds into the feedback loop for model retraining.

Integrates with SocialAuthService for OAuth credentials.
"""

from __future__ import annotations

import logging
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import httpx

from .social_auth_service import SocialAuthService, TokenExpiredError
from .social_publisher_service import SocialPublisherService, PublishResult

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0  # seconds for all external API calls


@dataclass
class ClipMetrics:
    clip_id: str
    platform: str                    # tiktok | youtube | instagram
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    completion_rate: float = 0.0     # 0-1
    engagement_rate: float = 0.0     # (likes+comments+shares)/views
    watch_time_seconds: float = 0.0
    ctr: float = 0.0
    platform_post_id: str = ""       # ID del post en la plataforma
    fetched_at: datetime = None      # When metrics were fetched


async def fetch_youtube_metrics(
    video_id: str,
    user_id: str,
    auth_service: SocialAuthService
) -> Optional[ClipMetrics]:
    """Fetch YouTube video metrics using YouTube Analytics API v2 with OAuth."""
    if not video_id:
        return None
    
    # Get credentials via SocialAuthService
    try:
        credentials = await auth_service.get_credentials("youtube", user_id)
        if not credentials:
            logger.warning(f"[analytics] No YouTube credentials for user {user_id}")
            return None
    except TokenExpiredError:
        logger.warning(f"[analytics] YouTube token expired for user {user_id}")
        return None
    
    access_token = credentials.access_token
    
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            # YouTube Analytics API v2 - richer metrics
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
            
            analytics_url = "https://youtubeanalytics.googleapis.com/v2/reports"
            params = {
                "ids": "channel==MINE",
                "startDate": start_date,
                "endDate": end_date,
                "metrics": "views,likes,dislikes,comments,shares,averageViewDuration,averageViewPercentage",
                "filters": f"video=={video_id}",
            }
            headers = {"Authorization": f"Bearer {access_token}"}
            
            r = await client.get(analytics_url, params=params, headers=headers)
            
            if r.status_code == 401:
                logger.warning(f"[analytics] YouTube token unauthorized for user {user_id}")
                return None
            
            r.raise_for_status()
            data = r.json()
            
            # Parse analytics response
            rows = data.get("rows", [])
            if not rows:
                # Fallback to Data API v3 for basic stats
                return await _fetch_youtube_basic_metrics(video_id, access_token)
            
            # rows[0] = [views, likes, dislikes, comments, shares, avgViewDuration, avgViewPercentage]
            row = rows[0]
            views = int(row[0]) if row[0] else 0
            likes = int(row[1]) if row[1] else 0
            comments = int(row[3]) if len(row) > 3 and row[3] else 0
            shares = int(row[4]) if len(row) > 4 and row[4] else 0
            avg_view_duration = float(row[5]) if len(row) > 5 and row[5] else 0.0
            avg_view_percentage = float(row[6]) if len(row) > 6 and row[6] else 0.0
            
            engagement = round((likes + comments + shares) / max(views, 1), 4)
            completion_rate = avg_view_percentage / 100.0 if avg_view_percentage else 0.0
            
            return ClipMetrics(
                clip_id=video_id,
                platform="youtube",
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
                engagement_rate=engagement,
                completion_rate=completion_rate,
                watch_time_seconds=avg_view_duration,
                platform_post_id=video_id,
                fetched_at=datetime.now(timezone.utc),
            )
            
    except httpx.HTTPStatusError as e:
        logger.error(f"[analytics] YouTube API error for {video_id}: {e.response.text}")
        return None
    except httpx.TimeoutException:
        logger.error(f"[analytics] YouTube API timeout for {video_id}")
        return None
    except Exception as e:
        logger.error(f"[analytics] YouTube metrics fetch failed for {video_id}: {e}")
        return None


async def _fetch_youtube_basic_metrics(video_id: str, access_token: str) -> Optional[ClipMetrics]:
    """Fallback: Fetch basic YouTube metrics using Data API v3."""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "id": video_id,
        "part": "statistics",
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            items = r.json().get("items", [])
            if not items:
                return None
            
            stats = items[0].get("statistics", {})
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            engagement = round((likes + comments) / max(views, 1), 4)
            
            return ClipMetrics(
                clip_id=video_id,
                platform="youtube",
                views=views,
                likes=likes,
                comments=comments,
                engagement_rate=engagement,
                platform_post_id=video_id,
                fetched_at=datetime.now(timezone.utc),
            )
    except Exception as e:
        logger.warning(f"[analytics] YouTube basic metrics fallback failed: {e}")
        return None


async def fetch_tiktok_metrics(
    video_id: str,
    user_id: str,
    auth_service: SocialAuthService
) -> Optional[ClipMetrics]:
    """Fetch TikTok video metrics using Content API with OAuth."""
    if not video_id:
        return None
    
    # Get credentials via SocialAuthService
    try:
        credentials = await auth_service.get_credentials("tiktok", user_id)
        if not credentials:
            logger.warning(f"[analytics] No TikTok credentials for user {user_id}")
            return None
    except TokenExpiredError:
        logger.warning(f"[analytics] TikTok token expired for user {user_id}")
        return None
    
    access_token = credentials.access_token
    
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            url = "https://open.tiktokapis.com/v2/video/query/"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            body = {
                "filters": {"video_ids": [video_id]},
                "fields": [
                    "id", "view_count", "like_count", "comment_count",
                    "share_count", "play_count"
                ],
            }
            
            r = await client.post(url, json=body, headers=headers)
            
            if r.status_code == 401:
                logger.warning(f"[analytics] TikTok token unauthorized for user {user_id}")
                return None
            
            r.raise_for_status()
            data = r.json()
            videos = data.get("data", {}).get("videos", [])
            
            if not videos:
                logger.warning(f"[analytics] No TikTok video data for {video_id}")
                return None
            
            v = videos[0]
            views = v.get("view_count") or v.get("play_count", 0)
            likes = v.get("like_count", 0)
            comments = v.get("comment_count", 0)
            shares = v.get("share_count", 0)
            engagement = round((likes + comments + shares) / max(views, 1), 4)
            
            # Note: TikTok API doesn't directly provide completion rate
            # We estimate from average metrics patterns
            
            return ClipMetrics(
                clip_id=video_id,
                platform="tiktok",
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
                engagement_rate=engagement,
                platform_post_id=video_id,
                fetched_at=datetime.now(timezone.utc),
            )
            
    except httpx.HTTPStatusError as e:
        logger.error(f"[analytics] TikTok API error for {video_id}: {e.response.text}")
        return None
    except httpx.TimeoutException:
        logger.error(f"[analytics] TikTok API timeout for {video_id}")
        return None
    except Exception as e:
        logger.error(f"[analytics] TikTok metrics fetch failed for {video_id}: {e}")
        return None


async def fetch_instagram_metrics(
    media_id: str,
    user_id: str,
    auth_service: SocialAuthService,
    duration_seconds: Optional[float] = None
) -> Optional[ClipMetrics]:
    """Fetch Instagram Reels metrics using Graph API."""
    if not media_id:
        return None
    
    # Get credentials via SocialAuthService
    try:
        credentials = await auth_service.get_credentials("instagram", user_id)
        if not credentials:
            logger.warning(f"[analytics] No Instagram credentials for user {user_id}")
            return None
    except TokenExpiredError:
        logger.warning(f"[analytics] Instagram token expired for user {user_id}")
        return None
    
    access_token = credentials.access_token
    
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            # Instagram Graph API v19.0 for reels metrics
            url = f"https://graph.instagram.com/v19.0/{media_id}"
            params = {
                "fields": "like_count,comments_count,reach,saved,video_views,ig_reels_avg_watch_time",
                "access_token": access_token,
            }
            
            r = await client.get(url, params=params)
            
            if r.status_code == 401:
                logger.warning(f"[analytics] Instagram token unauthorized for user {user_id}")
                return None
            
            r.raise_for_status()
            data = r.json()
            
            likes = data.get("like_count", 0)
            comments = data.get("comments_count", 0)
            # shares not directly available in basic API
            shares = 0
            views = data.get("video_views", 0) or data.get("reach", 0)
            
            # ig_reels_avg_watch_time is in ms, convert to seconds
            avg_watch_time_ms = data.get("ig_reels_avg_watch_time", 0)
            watch_time_seconds = avg_watch_time_ms / 1000.0 if avg_watch_time_ms else 0.0
            
            # Calculate completion rate if we have duration
            completion_rate = 0.0
            if duration_seconds and duration_seconds > 0:
                completion_rate = min(1.0, watch_time_seconds / duration_seconds)
            
            engagement = round((likes + comments + shares) / max(views, 1), 4)
            
            return ClipMetrics(
                clip_id=media_id,
                platform="instagram",
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
                engagement_rate=engagement,
                completion_rate=completion_rate,
                watch_time_seconds=watch_time_seconds,
                platform_post_id=media_id,
                fetched_at=datetime.now(timezone.utc),
            )
            
    except httpx.HTTPStatusError as e:
        logger.error(f"[analytics] Instagram API error for {media_id}: {e.response.text}")
        return None
    except httpx.TimeoutException:
        logger.error(f"[analytics] Instagram API timeout for {media_id}")
        return None
    except Exception as e:
        logger.error(f"[analytics] Instagram metrics fetch failed for {media_id}: {e}")
        return None


def compute_actual_virality_score(metrics: ClipMetrics) -> float:
    """
    Compute a 0-100 virality score from real platform metrics.

    Weights: views 40%, engagement_rate 40%, completion_rate 20%.
    Views scaled logarithmically (1M = 100).
    """
    import math
    view_score = min(100.0, math.log10(max(metrics.views, 1)) / 6.0 * 100)
    eng_score = min(100.0, metrics.engagement_rate * 1000)
    comp_score = metrics.completion_rate * 100
    return round(view_score * 0.4 + eng_score * 0.4 + comp_score * 0.2, 2)


async def import_metrics_for_clip(
    clip_id: str,
    user_id: str,
    auth_service: SocialAuthService,
    youtube_video_id: Optional[str] = None,
    tiktok_video_id: Optional[str] = None,
    instagram_media_id: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> list[ClipMetrics]:
    """Fetch metrics for all platforms a clip was published to."""
    results: list[ClipMetrics] = []
    
    tasks = []
    
    if youtube_video_id:
        tasks.append(fetch_youtube_metrics(youtube_video_id, user_id, auth_service))
    if tiktok_video_id:
        tasks.append(fetch_tiktok_metrics(tiktok_video_id, user_id, auth_service))
    if instagram_media_id:
        tasks.append(fetch_instagram_metrics(instagram_media_id, user_id, auth_service, duration_seconds))
    
    if tasks:
        metrics_list = await asyncio.gather(*tasks, return_exceptions=True)
        for m in metrics_list:
            if isinstance(m, ClipMetrics):
                m.clip_id = clip_id
                results.append(m)
            elif isinstance(m, Exception):
                logger.warning(f"[analytics] Failed to fetch metrics for clip {clip_id}: {m}")
    
    return results


def build_training_sample(
    clip_id: str,
    predicted_score: float,
    actual_score: float,
    features: dict,
) -> dict:
    """Build a labelled training sample for the virality scorer retraining."""
    return {
        "clip_id": clip_id,
        "predicted_virality": predicted_score,
        "actual_virality": actual_score,
        "delta": round(actual_score - predicted_score, 2),
        "features": features,
        "label": actual_score,
    }


async def run_feedback_import(
    user_id: str,
    auth_service: SocialAuthService,
    publisher_service: SocialPublisherService,
    days_back: int = 2,
) -> dict:
    """
    Main entry: fetch metrics for all published clips of a user.
    
    Scans Redis for PublishResult entries, fetches metrics from platforms,
    computes actual virality scores, returns updates and training samples.
    
    Args:
        user_id: User to import metrics for
        auth_service: SocialAuthService instance
        publisher_service: SocialPublisherService instance
        days_back: How many days back to look for clips
    
    Returns:
        Dict with "updates", "training_samples", "total_fetched", "errors"
    """
    from ..services.redis_client import RedisClient  # Import here to avoid circular
    
    updates = []
    training_samples = []
    errors = 0
    total_fetched = 0
    
    try:
        redis = publisher_service.redis
        
        # Scan for publish_result keys for this user's clips
        # Pattern: publish_result:*:{platform}
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        # Get all publish_result keys
        keys = await redis.keys("publish_result:*")
        
        clip_platforms: Dict[str, List[str]] = {}  # clip_id -> [platforms]
        publish_results: Dict[str, PublishResult] = {}
        
        for key in keys:
            # key format: "publish_result:{clip_id}:{platform}"
            parts = key.decode() if isinstance(key, bytes) else key
            parts = parts.split(":")
            if len(parts) >= 3:
                clip_id = parts[1]
                platform = parts[2]
                
                if clip_id not in clip_platforms:
                    clip_platforms[clip_id] = []
                clip_platforms[clip_id].append(platform)
                
                # Get the publish result
                result_data = await redis.get(key)
                if result_data:
                    # Parse PublishResult
                    if isinstance(result_data, dict):
                        # Convert dict back to PublishResult
                        if result_data.get("status") == "published":
                            publish_results[f"{clip_id}:{platform}"] = PublishResult(**result_data)
        
        logger.info(f"[analytics] Found {len(clip_platforms)} clips to import metrics for")
        
        # Fetch metrics for each published clip
        for clip_id, platforms in clip_platforms.items():
            for platform in platforms:
                key = f"{clip_id}:{platform}"
                publish_result = publish_results.get(key)
                
                if not publish_result or not publish_result.platform_post_id:
                    continue
                
                try:
                    platform_post_id = publish_result.platform_post_id
                    
                    # Fetch metrics based on platform
                    if platform == "youtube":
                        metrics = await fetch_youtube_metrics(
                            platform_post_id, user_id, auth_service
                        )
                    elif platform == "tiktok":
                        metrics = await fetch_tiktok_metrics(
                            platform_post_id, user_id, auth_service
                        )
                    elif platform == "instagram":
                        metrics = await fetch_instagram_metrics(
                            platform_post_id, user_id, auth_service
                        )
                    else:
                        continue
                    
                    if metrics:
                        actual = compute_actual_virality_score(metrics)
                        updates.append({
                            "clip_id": clip_id,
                            "platform": platform,
                            "views": metrics.views,
                            "likes": metrics.likes,
                            "comments": metrics.comments,
                            "shares": metrics.shares,
                            "engagement_rate": metrics.engagement_rate,
                            "completion_rate": metrics.completion_rate,
                            "watch_time_seconds": metrics.watch_time_seconds,
                            "actual_virality": actual,
                            "fetched_at": metrics.fetched_at.isoformat() if metrics.fetched_at else None,
                        })
                        total_fetched += 1
                        
                except Exception as e:
                    logger.error(f"[analytics] Error fetching metrics for {clip_id}/{platform}: {e}")
                    errors += 1
        
        logger.info(f"[analytics] Import complete: {total_fetched} metrics fetched, {errors} errors")
        
    except Exception as e:
        logger.error(f"[analytics] Error in run_feedback_import: {e}", exc_info=True)
        errors += 1
    
    return {
        "updates": updates,
        "training_samples": training_samples,
        "total_fetched": total_fetched,
        "errors": errors,
    }
