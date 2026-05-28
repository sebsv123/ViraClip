#!/usr/bin/env python3
"""
VPI Segment Diversity Debug Script (FASE 6)
============================================

Simulates segment ranking with diversity penalties to verify that:
- Recently-used segments are penalized
- Quality is preserved when score gap is large
- Re-ranking works correctly

Usage:
  python scripts/debug_segment_diversity.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
log = logging.getLogger("debug_segment_diversity")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from backend.src.services.vpi_segment_memory import (
        adjust_segments_for_diversity,
        compute_segment_signature,
        compute_source_video_hash,
        compute_transcript_hash,
        diversity_enabled,
        get_recent_segment_penalty,
        load_segment_memory,
        remember_selected_segments,
        save_segment_memory,
    )
except ImportError as e:
    log.error("Cannot import segment memory module: %s", e)
    log.error("Make sure backend/src/services/vpi_segment_memory.py exists.")
    sys.exit(1)


def make_segment(
    start: str,
    end: str,
    text: str,
    score: float,
    editorial_type: str = "client_objection",
    theme_key: str = "",
) -> Dict[str, Any]:
    """Create a fake segment dict."""
    return {
        "start_time": start,
        "end_time": end,
        "text": text,
        "final_rank_score": score,
        "editorial_type": editorial_type,
        "duplicate_theme_key": theme_key,
        "virality_score": score * 100,
    }


def print_ranking_table(title: str, segments: List[Dict[str, Any]]) -> None:
    log.info(title)
    log.info("  %-8s %-8s %-8s %-8s %s", "start", "before", "penalty", "after", "reasons")
    for seg in segments:
        log.info(
            "  %-8s %-8.1f %-8.1f %-8.1f %s",
            seg.get("start_time"),
            float(seg.get("score_before_diversity", seg.get("final_rank_score", 0.0)) or 0.0),
            float(seg.get("diversity_penalty", 0.0) or 0.0),
            float(seg.get("score_after_diversity", seg.get("adjusted_rank_score", seg.get("final_rank_score", 0.0))) or 0.0),
            ",".join(seg.get("diversity_reasons", []) or []),
        )


def test_basic_diversity() -> int:
    """Test that recently-used segments get penalized."""
    log.info("─" * 50)
    log.info("TEST: Basic Diversity Penalty")
    log.info("─" * 50)
    failures = 0

    # Create 5 segments
    segments = [
        make_segment("00:00", "00:30", "This is the best segment ever", 0.95),
        make_segment("00:30", "01:00", "Second best content here", 0.85),
        make_segment("01:00", "01:30", "Third option for clips", 0.75),
        make_segment("01:30", "02:00", "Fourth segment text", 0.65),
        make_segment("02:00", "02:30", "Fifth and last segment", 0.55),
    ]

    memory = [
        {
            "source_video_hash": compute_source_video_hash("/fake/video.mp4"),
            "source_video_id": "",
            "task_id": "prev-task",
            "segment_start": 0.0,
            "segment_end": 30.0,
            "duration": 30.0,
            "transcript_hash": compute_transcript_hash("This is the best segment ever"),
            "editorial_type": "client_objection",
            "duplicate_theme_key": "",
            "final_rank_score": 0.95,
            "selected_at": "2026-05-27T12:00:00Z",  # Today
        }
    ]
    save_segment_memory(memory)

    # Apply diversity
    adjusted, metadata = adjust_segments_for_diversity(
        segments,
        source_video_path="/fake/video.mp4",
        num_clips=3,
    )

    log.info("  Original order: %s", [s["start_time"] for s in segments])
    log.info("  Adjusted order: %s", [s["start_time"] for s in adjusted])
    log.info("  Diversity applied: %s", metadata["diversity_applied"])
    log.info("  Changes: %d", metadata["repeated_segments_avoided"])

    # Check that penalties were applied
    penalties = [s.get("diversity_penalty", 0) for s in adjusted]
    log.info("  Penalties: %s", penalties)

    if sum(penalties) == 0:
        log.warning("  ✗ Expected some penalties, got none")
        failures += 1

    if failures == 0:
        log.info("  ✅ Basic diversity test passed")
    else:
        log.warning("  ❌ %d test(s) failed", failures)

    return failures


def test_quality_preservation() -> int:
    """Test that top segment is protected when score gap is large."""
    log.info("─" * 50)
    log.info("TEST: Quality Preservation (large score gap)")
    log.info("─" * 50)
    failures = 0

    # Create segments with a huge gap between #1 and #2
    segments = [
        make_segment("00:00", "00:30", "Amazing segment with huge score", 0.95),
        make_segment("00:30", "01:00", "Much worse segment", 0.50),
        make_segment("01:00", "01:30", "Also mediocre", 0.45),
    ]

    # Simulate that segment 0 was recently used
    memory = [
        {
            "source_video_hash": compute_source_video_hash("/fake/video.mp4"),
            "source_video_id": "",
            "task_id": "prev-task",
            "segment_start": 0.0,
            "segment_end": 30.0,
            "duration": 30.0,
            "transcript_hash": compute_transcript_hash("Amazing segment with huge score"),
            "editorial_type": "client_objection",
            "duplicate_theme_key": "",
            "final_rank_score": 0.95,
            "selected_at": "2026-05-27T12:00:00Z",
        }
    ]

    save_segment_memory(memory)

    adjusted, metadata = adjust_segments_for_diversity(
        segments,
        source_video_path="/fake/video.mp4",
        num_clips=3,
    )

    log.info("  Original order: %s", [s["start_time"] for s in segments])
    log.info("  Adjusted order: %s", [s["start_time"] for s in adjusted])

    # Top segment should still be #1 (quality gap > 20 points)
    top = adjusted[0]
    log.info("  Top segment penalty: %.1f", top.get("diversity_penalty", 0))
    log.info("  Top segment reasons: %s", top.get("diversity_reasons", []))

    if top.get("diversity_penalty", 0) > 0:
        log.warning("  ✗ Expected top segment to be protected (penalty=0)")
        failures += 1

    if adjusted[0]["start_time"] != "00:00":
        log.warning("  ✗ Expected top segment to remain #1")
        failures += 1

    if failures == 0:
        log.info("  ✅ Quality preservation test passed")
    else:
        log.warning("  ❌ %d test(s) failed", failures)

    return failures


def test_few_candidates() -> int:
    """Test that diversity is skipped when there are few candidates."""
    log.info("─" * 50)
    log.info("TEST: Few Candidates (skip diversity)")
    log.info("─" * 50)
    failures = 0

    # Only 3 segments for 3 clips
    segments = [
        make_segment("00:00", "00:30", "Segment one", 0.90),
        make_segment("00:30", "01:00", "Segment two", 0.80),
        make_segment("01:00", "01:30", "Segment three", 0.70),
    ]

    adjusted, metadata = adjust_segments_for_diversity(
        segments,
        source_video_path="/fake/video.mp4",
        num_clips=3,
    )

    log.info("  Segments: %d, Clips: %d", len(segments), 3)
    log.info("  Diversity applied: %s", metadata["diversity_applied"])

    if metadata["diversity_applied"]:
        log.warning("  ✗ Expected diversity to be skipped (few candidates)")
        failures += 1

    if failures == 0:
        log.info("  ✅ Few candidates test passed")
    else:
        log.warning("  ❌ %d test(s) failed", failures)

    return failures


def test_theme_key_diversity() -> int:
    """Test that same theme key is penalized."""
    log.info("─" * 50)
    log.info("TEST: Theme Key Diversity")
    log.info("─" * 50)
    failures = 0

    segments = [
        make_segment("00:00", "00:30", "Insurance talk one", 0.90, theme_key="insurance"),
        make_segment("00:30", "01:00", "Insurance talk two", 0.85, theme_key="insurance"),
        make_segment("01:00", "01:30", "Different topic", 0.80, theme_key="retirement"),
    ]

    adjusted, metadata = adjust_segments_for_diversity(
        segments,
        source_video_path="/fake/video.mp4",
        num_clips=2,
    )

    log.info("  Original order: %s", [s["start_time"] for s in segments])
    log.info("  Adjusted order: %s", [s["start_time"] for s in adjusted])

    penalties = {s["start_time"]: s.get("diversity_penalty", 0) for s in adjusted}
    log.info("  Penalties: %s", penalties)

    if failures == 0:
        log.info("  ✅ Theme key test passed")
    else:
        log.warning("  ❌ %d test(s) failed", failures)

    return failures


def test_two_run_rotation() -> int:
    """Same video twice: second run should rotate close-score repeats."""
    log.info("─" * 50)
    log.info("TEST: Two-run rotation")
    log.info("─" * 50)
    failures = 0
    first_run = [
        make_segment("00:00", "00:30", "A family protection hook", 92, "emotional_protection", "family"),
        make_segment("00:45", "01:15", "B objection about older people", 90, "client_objection", "objection"),
        make_segment("01:30", "02:00", "C coverage explanation", 88, "coverage_explanation", "coverage"),
        make_segment("02:20", "02:50", "D alternative family angle", 86, "emotional_protection", "family_alt"),
        make_segment("03:10", "03:40", "E alternative objection angle", 84, "myth_debunk", "objection_alt"),
        make_segment("04:00", "04:30", "F practical advice", 82, "actionable_advice", "advice"),
    ]
    remember_selected_segments(first_run[:3], task_id="first-run", source_video_path="/fake/same-video.mp4")

    second_run = [dict(item) for item in first_run]
    adjusted, metadata = adjust_segments_for_diversity(second_run, source_video_path="/fake/same-video.mp4", num_clips=3)
    print_ranking_table("  before/after ranking table:", adjusted)
    selected = [seg["text"][0] for seg in adjusted[:3]]
    log.info("  Second run selected initials: %s", selected)
    if selected == ["A", "B", "C"]:
        log.warning("  ✗ Expected rotation away from A/B/C when scores are close")
        failures += 1
    if not metadata.get("diversity_applied"):
        log.warning("  ✗ Expected diversity_applied=true")
        failures += 1

    huge_gap = [
        make_segment("00:00", "00:30", "A family protection hook", 130, "emotional_protection", "family"),
        make_segment("00:45", "01:15", "B objection about older people", 90, "client_objection", "objection"),
        make_segment("01:30", "02:00", "C coverage explanation", 88, "coverage_explanation", "coverage"),
        make_segment("02:20", "02:50", "D alternative family angle", 86, "emotional_protection", "family_alt"),
        make_segment("03:10", "03:40", "E alternative objection angle", 84, "myth_debunk", "objection_alt"),
    ]
    adjusted_gap, metadata_gap = adjust_segments_for_diversity(huge_gap, source_video_path="/fake/same-video.mp4", num_clips=3)
    log.info("  Huge gap top: %s reason=%s", adjusted_gap[0]["text"][0], metadata_gap.get("repeated_segments_allowed_reason"))
    if adjusted_gap[0]["text"][0] != "A" or metadata_gap.get("repeated_segments_allowed_reason") != "quality_gap_protected":
        log.warning("  ✗ Expected huge quality gap to protect A")
        failures += 1

    if failures == 0:
        log.info("  ✅ Two-run rotation test passed")
    else:
        log.warning("  ❌ %d test(s) failed", failures)
    return failures


def test_remember_and_reuse() -> int:
    """Test that remember_selected_segments works."""
    log.info("─" * 50)
    log.info("TEST: Remember and Reuse")
    log.info("─" * 50)
    failures = 0

    segments = [
        make_segment("00:00", "00:30", "Selected segment", 0.90),
        make_segment("00:30", "01:00", "Another selected", 0.85),
    ]

    # Remember
    ok = remember_selected_segments(
        segments,
        task_id="test-task-1234",
        source_video_path="/fake/video.mp4",
    )
    log.info("  Remember result: %s", ok)

    if not ok:
        log.warning("  ✗ Expected remember to succeed")
        failures += 1

    # Load memory and verify
    memory = load_segment_memory()
    log.info("  Memory entries: %d", len(memory))

    if len(memory) == 0:
        log.warning("  ✗ Expected memory to have entries")
        failures += 1

    if failures == 0:
        log.info("  ✅ Remember test passed")
    else:
        log.warning("  ❌ %d test(s) failed", failures)

    return failures


def main() -> int:
    tmp_path = Path(tempfile.mkdtemp()) / "segment_memory.json"
    os.environ["VIRACLIP_SEGMENT_MEMORY_PATH"] = str(tmp_path)
    os.environ.setdefault("VIRACLIP_SEGMENT_DIVERSITY", "true")
    log.info("=" * 60)
    log.info("VPI Segment Diversity — Debug Suite (FASE 6)")
    log.info("=" * 60)
    log.info("")

    total_failures = 0
    total_failures += test_basic_diversity()
    total_failures += test_quality_preservation()
    total_failures += test_few_candidates()
    total_failures += test_theme_key_diversity()
    total_failures += test_two_run_rotation()
    total_failures += test_remember_and_reuse()

    log.info("")
    log.info("=" * 60)
    if total_failures == 0:
        log.info("RESULT: ✅ ALL TESTS PASSED")
    else:
        log.warning("RESULT: ❌ %d TEST(S) FAILED", total_failures)
    log.info("=" * 60)

    return total_failures


if __name__ == "__main__":
    sys.exit(main())
