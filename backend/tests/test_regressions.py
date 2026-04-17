"""
Regression tests for bugs found during real-world test on 2026-04-01.

Bug 1: FFmpeg received absolute timestamp (ss=122s) for a 6s pre-extracted segment → timeout.
Bug 2: Groq returned segments of 5-9s ignoring the 10s minimum in the prompt.

Pattern: validate at the boundary, never trust the caller.
"""

import pytest
from unittest.mock import patch
from pydantic import ValidationError

from src.ai import TranscriptSegment, ViralityAnalysis
from src.video_processing.ffmpeg_guard import validate_segment_call


def _make_virality() -> dict:
    return {
        "hook_score": 20,
        "engagement_score": 20,
        "value_score": 20,
        "shareability_score": 20,
        "total_score": 80,
        "hook_type": "story",
        "virality_reasoning": "test",
    }


def _make_segment(start: str, end: str, relevance: float = 0.8) -> TranscriptSegment:
    return TranscriptSegment(
        start_time=start,
        end_time=end,
        text="Test segment text for regression.",
        relevance_score=relevance,
        reasoning="regression test",
        virality=ViralityAnalysis(**_make_virality()),
    )


class TestSegmentValidation:
    """Regressions for Bug 2: LLM ignores 10s minimum."""

    def test_short_segment_gets_extended(self):
        """Groq returned 5s segment (00:36→00:41) — must be extended to 10s."""
        seg = _make_segment("00:36", "00:41")
        duration = _ts(seg.end_time) - _ts(seg.start_time)
        assert duration >= 10.0, f"Segment must be >= 10s, got {duration:.1f}s"

    def test_very_short_segment_gets_extended(self):
        """Groq returned 6s segment (03:22→03:28)."""
        seg = _make_segment("03:22", "03:28")
        duration = _ts(seg.end_time) - _ts(seg.start_time)
        assert duration >= 10.0

    def test_exactly_45s_segment_unchanged(self):
        """Segment exactly at 45s (current MIN_DURATION) must not be modified."""
        seg = _make_segment("01:00", "01:45")
        assert seg.end_time == "01:45"

    def test_longer_segment_unchanged(self):
        """Segment of 50s (above MIN_DURATION=45s) must remain untouched."""
        seg = _make_segment("02:00", "02:50")
        assert seg.end_time == "02:50"

    def test_inverted_timestamps_raise(self):
        """end_time <= start_time must raise ValidationError."""
        with pytest.raises(ValidationError, match="must be >"):
            _make_segment("02:30", "02:10")

    def test_equal_timestamps_raise(self):
        """end_time == start_time must raise ValidationError."""
        with pytest.raises(ValidationError, match="must be >"):
            _make_segment("01:00", "01:00")

    def test_relevance_score_normalized_from_100_scale(self):
        """LLM sometimes returns relevance_score in 0-100 instead of 0-1."""
        seg = _make_segment("00:00", "00:30", relevance=85.0)
        assert seg.relevance_score <= 1.0, (
            f"relevance_score must be normalized to [0,1], got {seg.relevance_score}"
        )
        assert abs(seg.relevance_score - 0.85) < 0.01

    def test_relevance_score_valid_range_unchanged(self):
        """relevance_score already in [0,1] must not be modified."""
        seg = _make_segment("00:00", "00:30", relevance=0.75)
        assert seg.relevance_score == 0.75


class TestFfmpegGuard:
    """Regressions for Bug 1: absolute ss on pre-extracted segment."""

    def _mocks(self, duration: float):
        """Patch both Path.exists (→ True) and get_duration (→ duration)."""
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch("src.video_processing.ffmpeg_guard.Path.exists", return_value=True))
        stack.enter_context(patch("src.video_processing.ffmpeg_guard.get_duration", return_value=duration))
        return stack

    def test_absolute_ss_on_short_file_raises(self):
        """Bug: ss=122s applied to 6s pre-extracted file must raise."""
        with self._mocks(6.0):
            with pytest.raises(ValueError, match="supera duración"):
                validate_segment_call(
                    source_path="fake_segment_6s.mp4",
                    ss=122.0,
                    to=128.0,
                    context="regression_absolute_ss",
                )

    def test_valid_params_on_short_file_pass(self):
        """ss=0, to=6 on 6s file must NOT raise."""
        with self._mocks(6.0):
            validate_segment_call(
                source_path="fake_segment_6s.mp4",
                ss=0.0,
                to=6.0,
                context="regression_valid",
            )

    def test_negative_ss_raises(self):
        with self._mocks(60.0):
            with pytest.raises(ValueError, match="ss negativo"):
                validate_segment_call("fake.mp4", ss=-1.0, to=5.0)

    def test_zero_duration_raises(self):
        with self._mocks(60.0):
            with pytest.raises(ValueError, match="duración 0"):
                validate_segment_call("fake.mp4", ss=5.0, to=5.0)

    def test_sub_second_duration_raises(self):
        with self._mocks(60.0):
            with pytest.raises(ValueError, match="demasiado corto"):
                validate_segment_call("fake.mp4", ss=5.0, to=5.4)

    def test_to_exceeds_duration_warns_not_raises(self, caplog):
        """to > source_duration should warn but not raise (FFmpeg truncates)."""
        import logging
        with self._mocks(6.0):
            with caplog.at_level(logging.WARNING, logger="src.video_processing.ffmpeg_guard"):
                validate_segment_call("fake.mp4", ss=0.0, to=8.0, context="overrun_test")
        assert "supera duración" in caplog.text

    def test_missing_file_raises_file_not_found(self):
        """File not yet written or still being extracted must raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Archivo no encontrado"):
            validate_segment_call(
                source_path="/nonexistent/segment_being_written.mp4",
                ss=0.0,
                to=6.0,
                context="regression_missing_file",
            )


# ── helpers ──────────────────────────────────────────────────────────────────

def _ts(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])
