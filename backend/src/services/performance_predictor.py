"""
Clip performance prediction based on quality score + user history.
"""
import json
import logging
import math
import os
from datetime import datetime

logger = logging.getLogger(__name__)

PREDICTION_BANDS = [
    {"min_score": 85, "label": "🔥 Alto potencial",
     "views_range": (10000, 100000), "confidence": "high"},
    {"min_score": 70, "label": "📈 Buen potencial",
     "views_range": (2000, 20000), "confidence": "medium"},
    {"min_score": 55, "label": "📊 Potencial medio",
     "views_range": (500, 5000), "confidence": "medium"},
    {"min_score": 0, "label": "⚠️ Potencial bajo",
     "views_range": (0, 1000), "confidence": "low"},
]

PLATFORM_MULTIPLIERS = {
    "tiktok": 1.0, "reels": 0.85, "shorts": 0.70,
    "twitter": 0.40, "linkedin": 0.25,
}


async def _compute_user_multiplier(user_id: str, platform: str, db) -> float:
    """Compute multiplier based on user's historical performance."""
    try:
        stats = await db.fetch_one(
            """
            SELECT AVG(ca.views) AS avg_views, COUNT(*) AS total_clips
            FROM clip_analytics ca
            JOIN clips c ON ca.clip_id = c.id
            WHERE c.user_id = :uid AND ca.platform = :platform
              AND ca.recorded_at > NOW() - INTERVAL '90 days'
            """,
            {"uid": user_id, "platform": platform},
        )
        if not stats or not stats["total_clips"] or stats["total_clips"] < 3:
            return 1.0
        avg_views = stats["avg_views"] or 0
        if avg_views <= 0:
            return 1.0
        return min(2.0, max(0.5, 1.0 + math.log10(avg_views / 1000) * 0.3))
    except Exception:
        return 1.0


async def _find_similar_past_clips(
    user_id: str, platform: str, score: int, db,
) -> list[dict]:
    """Find user's past clips with similar score."""
    try:
        rows = await db.fetch_all(
            """
            SELECT c.id, c.title, c.quality_score, ca.views, ca.likes, ca.shares
            FROM clips c
            JOIN clip_analytics ca ON ca.clip_id = c.id
            WHERE c.user_id = :uid AND ca.platform = :platform
              AND ABS(c.quality_score - :score) <= 15
              AND ca.views IS NOT NULL
            ORDER BY ca.views DESC LIMIT 3
            """,
            {"uid": user_id, "platform": platform, "score": score},
        )
        return [
            {"clip_id": str(r["id"]), "title": r["title"],
             "score": r["quality_score"], "views": r["views"],
             "likes": r["likes"]}
            for r in rows
        ]
    except Exception:
        return []


def _compute_impact_factors(breakdown: dict, duration_s: float, platform: str) -> list[dict]:
    factors = [
        {"name": "Hook strength", "value": breakdown.get("hook_strength", 50), "weight": 0.30},
        {"name": "Audio quality", "value": breakdown.get("audio_quality", 50), "weight": 0.20},
        {"name": "Pacing", "value": breakdown.get("pacing", 50), "weight": 0.15},
        {"name": "Visual energy", "value": breakdown.get("visual_energy", 50), "weight": 0.15},
        {"name": "Caption clarity", "value": breakdown.get("caption_readability", 50), "weight": 0.20},
    ]
    return sorted(factors, key=lambda f: f["weight"] * f["value"], reverse=True)[:3]


def _get_improvement_tips(breakdown: dict, platform: str) -> list[str]:
    tips = []
    if breakdown.get("hook_strength", 100) < 65:
        tips.append("Empieza con una pregunta o afirmación impactante en los primeros 2s")
    if breakdown.get("pacing", 100) < 60:
        tips.append(f"El ritmo es lento para {platform} — activa silence removal")
    if breakdown.get("audio_quality", 100) < 65:
        tips.append("Sube el volumen — el audio bajo reduce retención en móvil")
    return tips[:2]


async def predict_clip_performance(
    clip_id: str, platform: str, user_id: str, db, redis,
) -> dict:
    """Predict clip performance based on quality score + user history."""
    clip = await db.get_clip(clip_id)
    if not clip:
        raise ValueError(f"Clip {clip_id} not found")

    score = clip.quality_score or 50
    breakdown = json.loads(clip.quality_breakdown or "{}")
    hook_strength = breakdown.get("hook_strength", 50)
    duration_s = clip.duration_s or 30
    platform_mult = PLATFORM_MULTIPLIERS.get(platform.lower(), 0.5)

    band = next((b for b in PREDICTION_BANDS if score >= b["min_score"]), PREDICTION_BANDS[-1])
    base_min, base_max = band["views_range"]

    user_mult = await _compute_user_multiplier(user_id, platform, db)
    optimal_duration = {"tiktok": 30, "reels": 25, "shorts": 45, "twitter": 60, "linkedin": 120}.get(platform, 30)
    duration_penalty = max(0.6, 1.0 - abs(duration_s - optimal_duration) / 120)
    hook_mult = 0.7 + (hook_strength / 100) * 0.6

    final_min = int(base_min * platform_mult * user_mult * duration_penalty * hook_mult)
    final_max = int(base_max * platform_mult * user_mult * duration_penalty * hook_mult)

    similar = await _find_similar_past_clips(user_id, platform, score, db)
    factors = _compute_impact_factors(breakdown, duration_s, platform)
    tips = _get_improvement_tips(breakdown, platform)

    result = {
        "clip_id": clip_id, "platform": platform,
        "prediction": {
            "label": band["label"],
            "views_min": max(0, final_min),
            "views_max": max(0, final_max),
            "confidence": band["confidence"],
            "score_used": score,
        },
        "factors": factors,
        "similar_clips": similar[:3],
        "tips": tips,
        "disclaimer": (
            "Prediction based on your historical performance and clip quality. "
            "Actual results depend on posting time, hashtags, and platform algorithm."
        ),
    }

    env = os.getenv("APP_ENV", "production")
    cache_key = f"{env}:perf_pred:{clip_id}:{platform}"
    await redis.setex(cache_key, 3600, json.dumps(result))
    return result
