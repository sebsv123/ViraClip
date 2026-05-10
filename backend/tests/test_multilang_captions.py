"""Tests for multilang caption detection and ASS color coding."""
from src.services.caption_service import (
    detect_multilang_segments,
    build_multilang_ass_events,
    LANGUAGE_COLORS,
)


def test_single_language_not_multilang():
    """Single language → not multilang."""
    whisper_result = {
        "language": "es",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hola", "language": "es"},
            {"start": 2.0, "end": 4.0, "text": "Mundo", "language": "es"},
        ],
    }
    is_multi, langs = detect_multilang_segments(whisper_result)
    assert is_multi is False


def test_two_languages_above_threshold_is_multilang():
    """Two languages above 15% threshold → multilang."""
    segments = []
    for i in range(16):
        segments.append({"start": i, "end": i + 1, "text": f"es_{i}", "language": "es"})
    for i in range(4):
        segments.append({"start": 16 + i, "end": 17 + i, "text": f"en_{i}", "language": "en"})

    whisper_result = {"language": "es", "segments": segments}
    is_multi, langs = detect_multilang_segments(whisper_result)
    assert is_multi is True
    assert "es" in langs
    assert "en" in langs


def test_minor_language_below_threshold_ignored():
    """Minor language below 15% threshold → not multilang."""
    segments = []
    for i in range(19):
        segments.append({"start": i, "end": i + 1, "text": f"es_{i}", "language": "es"})
    segments.append({"start": 19, "end": 20, "text": "hello", "language": "en"})

    whisper_result = {"language": "es", "segments": segments}
    is_multi, langs = detect_multilang_segments(whisper_result)
    assert is_multi is False


def test_ass_color_conversion_correct():
    """ASS events have color override."""
    seg = {"start": 0.0, "end": 2.0, "text": "Hello"}
    lang_segments = {"en": [seg], "es": [seg]}
    events = build_multilang_ass_events(lang_segments, {})
    for event in events:
        assert "\\c&H" in event
