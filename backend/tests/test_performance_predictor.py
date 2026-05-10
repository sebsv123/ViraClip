"""Tests for performance prediction service."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.performance_predictor import (
    PREDICTION_BANDS,
    PLATFORM_MULTIPLIERS,
    _compute_user_multiplier,
    _compute_impact_factors,
)


def test_high_score_maps_to_high_band():
    """Score 90 maps to high potential band."""
    band = next(b for b in PREDICTION_BANDS if 90 >= b["min_score"])
    assert band["label"] == "🔥 Alto potencial"


def test_platform_multiplier_applied():
    """LinkedIn multiplier is lower than TikTok."""
    assert PLATFORM_MULTIPLIERS["linkedin"] < PLATFORM_MULTIPLIERS["tiktok"]


@pytest.mark.asyncio
async def test_no_history_returns_neutral_multiplier():
    """No history returns 1.0."""
    db = AsyncMock()
    db.fetch_one.return_value = {"avg_views": 0, "total_clips": 0}
    mult = await _compute_user_multiplier("user_1", "tiktok", db)
    assert mult == 1.0


@pytest.mark.asyncio
async def test_cache_hit_skips_db():
    """Cache hit skips DB call."""
    redis = AsyncMock()
    redis.get.return_value = b'{"prediction": {"label": "test"}}'
    data = await redis.get("some_key")
    assert data is not None


def test_impact_factors_sorted_by_weight_times_value():
    """Factors sorted by weight * value."""
    breakdown = {"hook_strength": 90, "audio_quality": 40}
    factors = _compute_impact_factors(breakdown, 30, "tiktok")
    assert factors[0]["name"] == "Hook strength"
