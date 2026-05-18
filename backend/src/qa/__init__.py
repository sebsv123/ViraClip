"""
ViraClip QA — sanity checks for real clip output.

This module provides offline QA validation that runs on rendered clips
to catch visual/audio defects that unit tests cannot detect.

Usage
-----
    python -m src.qa.generate_test_clips --preset=tiktok_basic --limit=10
    python -m src.qa.report_last_run

All checks are non-blocking for the production pipeline; they are intended
for staging / CI / manual QA runs.
"""

from src.qa.clip_sanity_checks import (
    check_no_triple_subtitles,
    check_broll_diversity,
    check_stable_framing,
    check_audio_sync_and_loudness,
    run_all_sanity_checks,
    SanityCheckResult,
    SanityReport,
)

__all__ = [
    "check_no_triple_subtitles",
    "check_broll_diversity",
    "check_stable_framing",
    "check_audio_sync_and_loudness",
    "run_all_sanity_checks",
    "SanityCheckResult",
    "SanityReport",
]
