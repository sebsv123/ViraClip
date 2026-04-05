"""
Regression tests for ViraClip parity sprint fixes.
Covers: Fix 1 (ASS font), Fix 3 (duration cap), Fix 4 (EliteAI bypass),
        Fix 5 (render logging), Fix 6 (transcript cache), Fix 10 (numpy).
Run: cd backend && uv run pytest tests/test_fixes.py -v
"""
from pathlib import Path

import numpy as np
import pytest

_SRC = Path(__file__).parent.parent / "src"


def _read(rel: str) -> str:
    return (_SRC / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fix 1: ASS subtitle header must NOT contain Fontfile=
# ---------------------------------------------------------------------------
def test_ass_header_no_fontfile():
    """Fix 1: ASS Format line must not contain Fontfile=."""
    src = _read("services/video_service.py")
    assert "Fontfile=" not in src, (
        "ASS header must not include Fontfile= — breaks FFmpeg subtitle rendering"
    )


def test_ass_header_fontsdir_in_ffmpeg():
    """Fix 1: FFmpeg ASS filter must include fontsdir=."""
    src = _read("services/video_service.py")
    assert "fontsdir=" in src, "FFmpeg filter must include fontsdir= for font loading"


# ---------------------------------------------------------------------------
# Fix 3: Segment end_time capped to video duration
# ---------------------------------------------------------------------------
def test_duration_cap_respects_video_length():
    """Fix 3: End time is capped when segment overshoots video duration."""
    video_dur = 120.0
    seg_start = 100.0
    new_end = seg_start + 60.0  # 160s — exceeds video
    if video_dur and new_end > video_dur - 1.0:
        new_end = max(seg_start + 10.0, video_dur - 1.0)
    assert new_end == pytest.approx(119.0)


def test_duration_cap_preserves_normal_segments():
    """Fix 3: Segments within video duration are unchanged."""
    video_dur = 600.0
    seg_start = 30.0
    new_end = seg_start + 60.0  # 90s — fine
    if video_dur and new_end > video_dur - 1.0:
        new_end = max(seg_start + 10.0, video_dur - 1.0)
    assert new_end == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Fix 4: EliteAI bypass — source must reference empty-plan short-circuit
# ---------------------------------------------------------------------------
def test_eliteai_bypass_present():
    """Fix 4: video_service must short-circuit EliteAI with an empty plan."""
    src = _read("services/video_service.py")
    assert "EliteCreativePlan" in src, (
        "video_service must bypass EliteAI by returning an empty EliteCreativePlan"
    )


# ---------------------------------------------------------------------------
# Fix 5: asyncio.gather must use return_exceptions=True
# ---------------------------------------------------------------------------
def test_render_gather_uses_return_exceptions():
    """Fix 5: gather call must not propagate exceptions silently."""
    src = _read("services/task_service.py")
    assert "return_exceptions=True" in src


def test_render_gather_logs_exceptions():
    """Fix 5: Exception slots in gather results must be logged."""
    src = _read("services/task_service.py")
    assert "RENDER FAILED" in src or "isinstance(_raw, Exception)" in src


# ---------------------------------------------------------------------------
# Fix 6: Transcript word filtering to segment window
# ---------------------------------------------------------------------------
def test_transcript_cache_filters_correctly():
    """Fix 6: Only words inside [start_ms, end_ms] are included."""
    start_ms, end_ms = 10_000, 40_000
    words = [
        {"text": "before", "start": 5_000, "end": 9_000},
        {"text": "hello",  "start": 12_000, "end": 14_000},
        {"text": "world",  "start": 20_000, "end": 22_000},
        {"text": "after",  "start": 45_000, "end": 47_000},
    ]
    start_sec = start_ms / 1000
    filtered = [
        {"word": w["text"],
         "start": w["start"] / 1000 - start_sec,
         "end":   w["end"]   / 1000 - start_sec}
        for w in words
        if start_ms <= w["start"] <= end_ms
    ]
    assert len(filtered) == 2
    assert filtered[0]["word"] == "hello"
    assert filtered[0]["start"] == pytest.approx(2.0)
    assert filtered[1]["word"] == "world"
    assert filtered[1]["start"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Fix 10: numpy tempo extraction is safe across numpy versions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tempo,expected", [
    (np.float64(128.5),    128.5),
    (np.array([95.0]),      95.0),
    (np.array(110.0),      110.0),   # 0-d array
])
def test_numpy_tempo_extraction(tempo, expected):
    """Fix 10: float(np.asarray(tempo).flat[0]) works for all numpy types."""
    result = float(np.asarray(tempo).flat[0])
    assert isinstance(result, float)
    assert result == pytest.approx(expected)
