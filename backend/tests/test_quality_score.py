"""Tests for quality score normalization."""
from src.services.coordinator import _normalize_health_to_score, _score_to_grade


def test_score_calculation_weighted():
    """Score calculation with weighted metrics."""
    report = {
        "hook_strength": 1.0,
        "audio_quality": 0.5,
        "caption_readability": 1.0,
        "visual_energy": 0.8,
        "pacing": 0.9,
    }
    score, breakdown, tips = _normalize_health_to_score(report)
    assert 0 <= score <= 100
    assert breakdown["hook_strength"] == 100
    assert breakdown["audio_quality"] == 50


def test_low_hook_generates_tip():
    """Low hook score generates tip."""
    report = {
        "hook_strength": 0.4,
        "audio_quality": 0.9,
        "caption_readability": 0.9,
        "visual_energy": 0.9,
        "pacing": 0.9,
    }
    _, _, tips = _normalize_health_to_score(report)
    assert len(tips) >= 1
    assert "hook" in tips[0].lower()


def test_max_3_tips_returned():
    """Max 3 tips returned."""
    report = {
        "hook_strength": 0.3,
        "audio_quality": 0.3,
        "caption_readability": 0.3,
        "visual_energy": 0.3,
        "pacing": 0.3,
    }
    _, _, tips = _normalize_health_to_score(report)
    assert len(tips) <= 3


def test_score_to_grade_mapping():
    """Score to grade mapping."""
    assert _score_to_grade(95) == "A"
    assert _score_to_grade(80) == "B"
    assert _score_to_grade(65) == "C"
    assert _score_to_grade(50) == "D"
    assert _score_to_grade(30) == "F"
