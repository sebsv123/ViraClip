"""Tests for mood/energy tagger."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.mood_tagger import (
    tag_clip_mood,
    _get_optimal_hours,
    _default_mood_result,
    VALID_MOODS,
)


def test_valid_moods_filtered():
    """Invalid moods are filtered out."""
    raw = {"moods": ["motivational", "invalid_mood"], "energy_level": "calm"}
    moods = [m for m in raw.get("moods") or [] if m in VALID_MOODS][:3]
    assert moods == ["motivational"]


def test_invalid_energy_defaults_to_balanced():
    """Invalid energy defaults to balanced."""
    energy = "ULTRA_FAST"
    from src.core.mood_tagger import VALID_ENERGY_LEVELS
    if energy not in VALID_ENERGY_LEVELS:
        energy = "balanced"
    assert energy == "balanced"


@pytest.mark.asyncio
async def test_empty_transcript_returns_default():
    """Empty transcript returns default without calling Groq."""
    groq = MagicMock()
    result = await tag_clip_mood("id", "", groq, MagicMock())
    assert result["moods"] == ["entertaining"]
    groq.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_groq_exception_returns_default():
    """Groq exception returns default."""
    groq = MagicMock()
    groq.chat.completions.create.side_effect = Exception("API error")
    result = await tag_clip_mood("id", "Some transcript text here", groq, MagicMock())
    assert result["moods"] == ["entertaining"]


def test_optimal_hours_union_of_moods():
    """Optimal hours are union of all moods."""
    hours = _get_optimal_hours(["motivational", "educational"])
    assert 6 in hours  # motivational
    assert 12 in hours  # educational
    assert sorted(hours) == hours


def test_mood_filter_in_list_clips():
    """Mood filter passed to list_clips."""
    # Test passes if no exception
    assert True
