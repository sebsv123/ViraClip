"""
Analytics Importer — Closed A/B Feedback Loop.

Pulls real view/engagement metrics from TikTok & YouTube Analytics APIs,
stores them on GeneratedClip rows, then retrains the virality scorer so
the model learns from actual performance data.

Environment variables:
  TIKTOK_ACCESS_TOKEN  — TikTok for Developers OAuth access token
  YOUTUBE_API_KEY      — YouTube Data API v3 key
  ANALYTICS_POLL_INTERVAL_HOURS — how often cron job fires (default: 24)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TIKTOK_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "")
POLL_INTERVAL_HOURS = int(os.getenv("ANALYTICS_POLL_INTERVAL_HOURS", "24"))


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


async def fetch_youtube_metrics(video_id: str) -> Optional[ClipMetrics]:
    """Fetch YouTube video statistics using Data API v3."""
    if not YOUTUBE_KEY or not video_id:
        return None
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "id": video_id,
        "part": "statistics,contentDetails",
        "key": YOUTUBE_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=params)
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
            )
    except Exception as e:
        logger.warning("YouTube metrics fetch failed for %s: %s", video_id, e)
        return None


async def fetch_tiktok_metrics(video_id: str) -> Optional[ClipMetrics]:
    """Fetch TikTok video statistics using Research API."""
    if not TIKTOK_TOKEN or not video_id:
        return None
    url = "https://open.tiktokapis.com/v2/video/query/"
    headers = {"Authorization": f"Bearer {TIKTOK_TOKEN}",
               "Content-Type": "application/json"}
    body = {
        "filters": {"video_ids": [video_id]},
        "fields": ["id", "view_count", "like_count", "comment_count",
                   "share_count", "play_count"],
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json().get("data", {}).get("videos", [])
            if not data:
                return None
            v = data[0]
            views = v.get("view_count") or v.get("play_count", 0)
            likes = v.get("like_count", 0)
            comments = v.get("comment_count", 0)
            shares = v.get("share_count", 0)
            engagement = round((likes + comments + shares) / max(views, 1), 4)
            return ClipMetrics(
                clip_id=video_id,
                platform="tiktok",
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
                engagement_rate=engagement,
            )
    except Exception as e:
        logger.warning("TikTok metrics fetch failed for %s: %s", video_id, e)
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
    youtube_video_id: Optional[str],
    tiktok_video_id: Optional[str],
) -> list[ClipMetrics]:
    """Fetch metrics for all platforms a clip was published to."""
    results: list[ClipMetrics] = []

    if youtube_video_id:
        m = await fetch_youtube_metrics(youtube_video_id)
        if m:
            m.clip_id = clip_id
            results.append(m)

    if tiktok_video_id:
        m = await fetch_tiktok_metrics(tiktok_video_id)
        if m:
            m.clip_id = clip_id
            results.append(m)

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


async def run_feedback_import(clips_data: list[dict]) -> dict:
    """
    Main entry: given a list of clip dicts with platform IDs,
    fetch metrics, compute actual scores, return update payloads.

    clips_data items: {clip_id, youtube_video_id, tiktok_video_id,
                        predicted_virality, feature_vector}
    """
    updates = []
    training_samples = []

    for clip in clips_data:
        clip_id = clip.get("clip_id", "")
        metrics_list = await import_metrics_for_clip(
            clip_id,
            clip.get("youtube_video_id"),
            clip.get("tiktok_video_id"),
        )
        for m in metrics_list:
            actual = compute_actual_virality_score(m)
            updates.append({
                "clip_id": clip_id,
                "platform": m.platform,
                "views": m.views,
                "likes": m.likes,
                "comments": m.comments,
                "shares": m.shares,
                "engagement_rate": m.engagement_rate,
                "completion_rate": m.completion_rate,
                "actual_virality": actual,
            })
            predicted = float(clip.get("predicted_virality", 0))
            if clip.get("feature_vector"):
                training_samples.append(
                    build_training_sample(
                        clip_id, predicted, actual, clip["feature_vector"]
                    )
                )

    return {"updates": updates, "training_samples": training_samples}
