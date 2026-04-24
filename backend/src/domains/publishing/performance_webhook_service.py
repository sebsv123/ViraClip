"""
Performance Feedback Webhook Service.

Receives real-time performance events from TikTok/Instagram/YouTube,
auto-flags high-performing clip templates, and feeds data back into
the virality scorer training pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Performance store path (JSON file, upgradeable to DB)
_PERF_STORE = Path(os.environ.get("PERF_STORE_PATH", "/app/data/performance_events.json"))

# Thresholds for auto-flagging
VIRAL_VIEW_THRESHOLD = 100_000      # views to be considered viral
VIRAL_ENGAGEMENT_RATE = 0.08        # 8% engagement rate threshold
HIGH_RETENTION_THRESHOLD = 0.65     # 65% average view duration


@dataclass
class PerformanceEvent:
    clip_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    watch_time_seconds: float = 0.0
    avg_view_duration_pct: float = 0.0
    posted_at: Optional[str] = None
    received_at: float = field(default_factory=time.time)
    raw_payload: Optional[Dict[str, Any]] = None

    @property
    def engagement_rate(self) -> float:
        if self.views <= 0:
            return 0.0
        return (self.likes + self.comments + self.shares + self.saves) / self.views

    @property
    def is_viral(self) -> bool:
        return (
            self.views >= VIRAL_VIEW_THRESHOLD
            or self.engagement_rate >= VIRAL_ENGAGEMENT_RATE
            or self.avg_view_duration_pct >= HIGH_RETENTION_THRESHOLD
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "platform": self.platform,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "saves": self.saves,
            "watch_time_seconds": self.watch_time_seconds,
            "avg_view_duration_pct": self.avg_view_duration_pct,
            "posted_at": self.posted_at,
            "received_at": self.received_at,
            "engagement_rate": self.engagement_rate,
            "is_viral": self.is_viral,
        }


@dataclass
class TemplatePerformance:
    template_name: str
    total_uses: int = 0
    total_views: int = 0
    viral_count: int = 0
    avg_engagement_rate: float = 0.0
    avg_retention: float = 0.0

    @property
    def viral_rate(self) -> float:
        return self.viral_count / max(1, self.total_uses)

    @property
    def avg_views(self) -> float:
        return self.total_views / max(1, self.total_uses)


def _load_store() -> Dict[str, Any]:
    """Load performance event store from disk."""
    if not _PERF_STORE.exists():
        return {"events": [], "template_stats": {}}
    try:
        return json.loads(_PERF_STORE.read_text())
    except Exception:
        return {"events": [], "template_stats": {}}


def _save_store(data: Dict[str, Any]) -> None:
    """Persist performance event store to disk."""
    _PERF_STORE.parent.mkdir(parents=True, exist_ok=True)
    _PERF_STORE.write_text(json.dumps(data, indent=2))


def record_performance_event(
    event: PerformanceEvent,
    caption_template: Optional[str] = None,
    music_genre: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record a performance event and update template statistics.

    Args:
        event: PerformanceEvent with views/likes/etc.
        caption_template: The caption template used in this clip
        music_genre: The BGM genre used in this clip

    Returns:
        Dict with stored event + viral flag.
    """
    store = _load_store()
    event_dict = event.to_dict()
    event_dict["caption_template"] = caption_template
    event_dict["music_genre"] = music_genre
    store["events"].append(event_dict)

    # Update template stats
    if caption_template:
        ts = store.setdefault("template_stats", {})
        tmpl = ts.setdefault(caption_template, {
            "total_uses": 0, "total_views": 0, "viral_count": 0,
            "total_engagement": 0.0, "total_retention": 0.0,
        })
        tmpl["total_uses"] += 1
        tmpl["total_views"] += event.views
        tmpl["total_engagement"] += event.engagement_rate
        tmpl["total_retention"] += event.avg_view_duration_pct
        if event.is_viral:
            tmpl["viral_count"] += 1

    _save_store(store)
    logger.info(
        "[perf_webhook] Recorded event clip=%s views=%d viral=%s",
        event.clip_id, event.views, event.is_viral,
    )
    return event_dict


def get_top_templates(limit: int = 10) -> List[Dict[str, Any]]:
    """Return top-performing caption templates ranked by viral rate."""
    store = _load_store()
    stats = store.get("template_stats", {})
    results = []
    for name, s in stats.items():
        uses = max(1, s.get("total_uses", 1))
        results.append({
            "template": name,
            "total_uses": s.get("total_uses", 0),
            "total_views": s.get("total_views", 0),
            "viral_count": s.get("viral_count", 0),
            "viral_rate": s.get("viral_count", 0) / uses,
            "avg_views": s.get("total_views", 0) / uses,
            "avg_engagement": s.get("total_engagement", 0.0) / uses,
            "avg_retention": s.get("total_retention", 0.0) / uses,
        })
    return sorted(results, key=lambda x: x["viral_rate"], reverse=True)[:limit]


def get_performance_summary(clip_id: Optional[str] = None) -> Dict[str, Any]:
    """Return performance summary, optionally filtered by clip_id."""
    store = _load_store()
    events = store.get("events", [])
    if clip_id:
        events = [e for e in events if e.get("clip_id") == clip_id]

    if not events:
        return {"total_events": 0, "total_views": 0, "viral_clips": 0}

    return {
        "total_events": len(events),
        "total_views": sum(e.get("views", 0) for e in events),
        "viral_clips": sum(1 for e in events if e.get("is_viral", False)),
        "avg_engagement_rate": (
            sum(e.get("engagement_rate", 0) for e in events) / len(events)
        ),
        "avg_retention": (
            sum(e.get("avg_view_duration_pct", 0) for e in events) / len(events)
        ),
    }


def parse_tiktok_webhook(payload: Dict[str, Any]) -> Optional[PerformanceEvent]:
    """Parse a TikTok webhook payload into a PerformanceEvent."""
    try:
        data = payload.get("data", {})
        video = data.get("video", {}) or data
        return PerformanceEvent(
            clip_id=str(data.get("video_id", data.get("id", ""))),
            platform="tiktok",
            views=int(video.get("play_count", video.get("views", 0))),
            likes=int(video.get("digg_count", video.get("likes", 0))),
            comments=int(video.get("comment_count", video.get("comments", 0))),
            shares=int(video.get("share_count", video.get("shares", 0))),
            avg_view_duration_pct=float(
                video.get("average_watch_time_pct", video.get("avg_retention", 0))
            ),
            raw_payload=payload,
        )
    except Exception as exc:
        logger.debug("[perf_webhook] TikTok parse error: %s", exc)
        return None


def parse_instagram_webhook(payload: Dict[str, Any]) -> Optional[PerformanceEvent]:
    """Parse an Instagram webhook payload into a PerformanceEvent."""
    try:
        entry = (payload.get("entry") or [{}])[0]
        changes = (entry.get("changes") or [{}])[0]
        value = changes.get("value", {}) or entry
        return PerformanceEvent(
            clip_id=str(value.get("media_id", value.get("id", ""))),
            platform="instagram",
            views=int(value.get("video_views", value.get("impressions", 0))),
            likes=int(value.get("like_count", 0)),
            comments=int(value.get("comments_count", 0)),
            shares=int(value.get("shares", 0)),
            saves=int(value.get("saved", 0)),
            raw_payload=payload,
        )
    except Exception as exc:
        logger.debug("[perf_webhook] Instagram parse error: %s", exc)
        return None


def auto_update_creator_template(
    user_id: str,
    min_viral_posts: int = 5,
) -> Optional[str]:
    """
    Inspect top-performing templates and auto-update the creator profile
    when a template has ≥ min_viral_posts viral clips.

    Returns the winning template name if an update was made, else None.
    """
    templates = get_top_templates(limit=1)
    if not templates:
        return None
    winner = templates[0]
    if winner.get("viral_count", 0) < min_viral_posts:
        return None

    template_name = winner["template"]
    try:
        from ..domains.feedback.creator_profile_service import get_profile, save_profile, update_profile
        profile = get_profile(user_id)
        if profile and getattr(profile, "caption_style", None) != template_name:
            update_profile(user_id, {"caption_style": template_name})
            logger.info(
                "[ab_winner] User %s → auto-updated caption_style to '%s' "
                "(viral_count=%d)",
                user_id, template_name, winner["viral_count"],
            )
            return template_name
    except Exception as exc:
        logger.debug("[ab_winner] Could not update creator profile: %s", exc)
    return None


def parse_youtube_webhook(payload: Dict[str, Any]) -> Optional[PerformanceEvent]:
    """Parse a YouTube webhook payload into a PerformanceEvent."""
    try:
        stats = payload.get("statistics", payload)
        video_id = payload.get("id", payload.get("video_id", ""))
        return PerformanceEvent(
            clip_id=str(video_id),
            platform="youtube",
            views=int(stats.get("viewCount", 0)),
            likes=int(stats.get("likeCount", 0)),
            comments=int(stats.get("commentCount", 0)),
            avg_view_duration_pct=float(stats.get("averageViewPercentage", 0)) / 100,
            watch_time_seconds=float(stats.get("watchTimeMinutes", 0)) * 60,
            raw_payload=payload,
        )
    except Exception as exc:
        logger.debug("[perf_webhook] YouTube parse error: %s", exc)
        return None
