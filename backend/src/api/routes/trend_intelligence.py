"""Trend Intelligence API routes."""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/trend-intelligence", tags=["trend-intelligence"])


@router.get("/hooks")
def get_hooks(niche: str = "auto", platform: str = "tiktok", limit: int = 5):
    """Return ranked hook phrase suggestions for a creator niche."""
    from ...services.trend_intelligence_service import get_hook_suggestions
    suggestions = get_hook_suggestions(niche, limit=limit, platform=platform)
    return {
        "niche": niche,
        "platform": platform,
        "hooks": [
            {"phrase": s.phrase, "engagement_boost": s.estimated_engagement_boost, "source": s.source}
            for s in suggestions
        ],
    }


@router.get("/caption-patterns")
def get_caption_patterns(platform: str = "tiktok", limit: int = 5):
    """Return top viral caption structural patterns for a platform."""
    from ...services.trend_intelligence_service import get_caption_patterns
    return {"platform": platform, "patterns": get_caption_patterns(platform, limit)}


@router.get("/posting-times")
def get_posting_times(
    platform: str = "tiktok",
    is_weekend: bool = False,
    timezone_offset_hours: float = 0,
):
    """Return optimal posting hours (UTC) for a platform."""
    from ...services.trend_intelligence_service import get_best_posting_times
    hours = get_best_posting_times(platform, is_weekend, timezone_offset_hours)
    return {"platform": platform, "best_hours_utc": hours}


@router.get("/report")
def get_report(
    niche: str = "auto",
    platform: str = "tiktok",
    timezone_offset_hours: float = 0,
):
    """Full trend intelligence report: hooks + patterns + hashtags + timing + trending."""
    from ...services.trend_intelligence_service import build_intelligence_report
    report = build_intelligence_report(niche, platform, timezone_offset_hours)
    return {
        "niche": report.niche,
        "platform": platform,
        "hooks": [
            {"phrase": s.phrase, "engagement_boost": s.estimated_engagement_boost}
            for s in report.hook_suggestions
        ],
        "caption_patterns": report.caption_patterns,
        "hashtags": report.hashtags,
        "best_posting_hours": report.best_posting_hours,
        "trending_topics": report.trending_topics,
        "generated_at": report.generated_at,
    }


@router.get("/niches")
def list_niches():
    """List all supported niche categories."""
    from ...services.trend_intelligence_service import get_supported_niches
    return {"niches": get_supported_niches()}


@router.get("/hashtags")
def get_hashtags(niche: str = "auto"):
    """Return recommended hashtag cluster for a niche."""
    from ...services.trend_intelligence_service import _HASHTAG_CLUSTERS
    tags = _HASHTAG_CLUSTERS.get(niche.lower(), ["viral", "fyp", "foryou"])
    return {"niche": niche, "hashtags": tags}
