"""Tests for the word-aware ducking filter (build_word_aware_ducking_filter)."""
import pytest


def test_empty_words_returns_base_volume():
    """No words → returns simple volume=music_base_volume."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    result = build_word_aware_ducking_filter([])
    assert result == "volume=0.35"


def test_empty_words_custom_base():
    """No words with custom base → returns volume=custom."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    result = build_word_aware_ducking_filter([], music_base_volume=0.5)
    assert result == "volume=0.5"


def test_single_word_returns_volume_expression():
    """Single word → returns volume expression with eval=frame."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 1.0, "end": 2.5}]
    result = build_word_aware_ducking_filter(words)
    assert "volume=" in result
    assert "eval=frame" in result
    # The word at 1.0 gets a 0.05s pre-roll → first voice keyframe at 0.950
    # Before the first word, there's a pause boost keyframe at 0.000
    assert "0.950" in result


def test_two_words_merged():
    """Two close words (<0.35s gap) → merged into one segment."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [
        {"start": 1.0, "end": 1.5},
        {"start": 1.6, "end": 2.0},  # 0.1s gap → merged
    ]
    result = build_word_aware_ducking_filter(words)
    assert "eval=frame" in result
    # Should have fewer keyframes than if unmerged (2 words merged = 1 segment)
    # Each segment adds 3 keyframes (before, start, end) + 1 final
    # With 1 merged segment: 4 keyframes → 4 if(between) parts
    # With 2 separate segments: 7 keyframes → 7 if(between) parts
    # Count the between() occurrences
    between_count = result.count("between(t,")
    assert between_count <= 5, f"Expected ≤5 between() for merged words, got {between_count}"


def test_two_words_separate():
    """Two distant words (≥0.35s gap) → separate segments."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [
        {"start": 1.0, "end": 1.5},
        {"start": 3.0, "end": 3.5},  # 1.5s gap → separate
    ]
    result = build_word_aware_ducking_filter(words)
    assert "eval=frame" in result
    # 2 separate segments = 7 keyframes (before1, start1, end1, before2, start2, end2, final)
    between_count = result.count("between(t,")
    assert between_count >= 6, f"Expected ≥6 between() for separate words, got {between_count}"


def test_timestamps_in_milliseconds():
    """Timestamps >1000 → treated as ms, converted to seconds."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 1500, "end": 3000}]  # ms
    result = build_word_aware_ducking_filter(words)
    assert "eval=frame" in result
    # Should have converted to seconds (1.5, 3.0)
    # The word at 1.5s gets a 0.05s pre-roll → first voice keyframe at 1.450
    assert "1.450" in result


def test_voice_duck_ratio_affects_volume():
    """Different voice_duck_ratio → different volume levels in expression."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 1.0, "end": 2.0}]
    
    # With ratio=0.25 (default): voice_vol = 0.35 * 0.25 = 0.0875
    result_default = build_word_aware_ducking_filter(words)
    
    # With ratio=0.5: voice_vol = 0.35 * 0.5 = 0.175
    result_half = build_word_aware_ducking_filter(words, voice_duck_ratio=0.5)
    
    assert result_default != result_half
    # The half ratio should have higher volume values
    # Extract the voice volume from the expression (it's the ducked value)
    assert "0.0875" in result_default or "0.088" in result_default
    assert "0.1750" in result_half or "0.175" in result_half


def test_long_pause_boost_capped():
    """Long pause boost capped at 1.0."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [
        {"start": 1.0, "end": 1.5},
        {"start": 5.0, "end": 5.5},  # 3.5s gap → long pause
    ]
    # With long_pause_boost=3.0, should be capped at 1.0
    result = build_word_aware_ducking_filter(words, long_pause_boost=3.0)
    # The base volume is 0.35, capped at 1.0
    # The long pause volume should be 1.0 (capped)
    assert "1.0000" in result


def test_short_pause_boost_capped():
    """Short pause boost capped at 0.85."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [
        {"start": 1.0, "end": 1.5},
        {"start": 2.0, "end": 2.5},  # 0.5s gap → short pause
    ]
    # With short_pause_boost=3.0, should be capped at 0.85
    result = build_word_aware_ducking_filter(words, short_pause_boost=3.0)
    # The short pause volume should be 0.85 (capped)
    assert "0.8500" in result


def test_very_short_pause_keeps_ducked():
    """Very short pause (<0.35s) → keeps ducked volume."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [
        {"start": 1.0, "end": 1.5},
        {"start": 1.7, "end": 2.0},  # 0.2s gap → very short, keep ducked
    ]
    result = build_word_aware_ducking_filter(words)
    # The gap is 0.2s which is < short_pause_threshold (0.35)
    # So the pause volume should be voice_vol (0.0875), not boosted
    # This means the keyframe at 1.5 should have voice_vol
    assert "0.0875" in result


def test_output_format_contains_eval_frame():
    """Output contains eval=frame for smooth transitions."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 1.0, "end": 2.0}]
    result = build_word_aware_ducking_filter(words)
    assert "eval=frame" in result


def test_output_format_contains_volume():
    """Output starts with volume=."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 1.0, "end": 2.0}]
    result = build_word_aware_ducking_filter(words)
    assert result.startswith("volume=")


def test_multiple_words_complex_timeline():
    """Multiple words with varying gaps → correct segment count."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [
        {"start": 0.5, "end": 1.0},
        {"start": 1.2, "end": 1.8},  # 0.2s gap → merged
        {"start": 3.0, "end": 3.5},  # 1.2s gap → separate
        {"start": 3.7, "end": 4.0},  # 0.2s gap → merged with previous
        {"start": 6.0, "end": 6.5},  # 2.0s gap → separate
    ]
    result = build_word_aware_ducking_filter(words)
    assert "eval=frame" in result
    # Merged segments: [0.5-1.8], [3.0-4.0], [6.0-6.5] = 3 segments
    # Each segment: before, start, end = 3 keyframes
    # 3 segments × 3 = 9 + 1 final = 10 keyframes
    between_count = result.count("between(t,")
    # Allow some flexibility due to edge conditions
    assert 8 <= between_count <= 12, f"Expected 8-12 between() for 3 segments, got {between_count}"


def test_word_without_end_uses_default():
    """Word without 'end' key → uses start + 0.3."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 2.0}]  # no end
    result = build_word_aware_ducking_filter(words)
    assert "eval=frame" in result
    # Should have a keyframe around 2.0 + 0.3 + 0.15 = 2.45
    assert "2.450" in result or "2.45" in result


def test_word_with_zero_start():
    """Word starting at 0.0 → handled correctly."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 0.0, "end": 1.0}]
    result = build_word_aware_ducking_filter(words)
    assert "eval=frame" in result
    # Should have keyframe at 0.0 (or 0.000)
    assert "0.000" in result or "0.00" in result


def test_custom_music_base_volume():
    """Custom music_base_volume → reflected in output."""
    from src.domains.audio.audio_ducking_service import build_word_aware_ducking_filter
    words = [{"start": 1.0, "end": 2.0}]
    result = build_word_aware_ducking_filter(words, music_base_volume=0.5)
    # voice_vol = 0.5 * 0.25 = 0.125
    assert "0.1250" in result or "0.125" in result
    # base volume should be 0.5
    assert "0.5000" in result or "0.50" in result
