#!/usr/bin/env python3
"""
debug_publishable_gate.py — VPI Publishable Gate v3.1 diagnostic script.

Runs 5 test cases through evaluate_clip_publishability() and rank_clips()
to verify classification logic:

  1. Strong emotional hook, no B-roll, good silence → REVIEW_MANUALLY or READY
  2. weak_intro hook → NEEDS_FIX / REVIEW_MANUALLY, discard_recommended
  3. Forbidden B-roll asset → DO_NOT_UPLOAD
  4. Technical OK + generic documents_admin B-roll → REVIEW_MANUALLY / NEEDS_FIX
  5. Strong objection hook, good everything → READY_TO_UPLOAD

Usage:
    cd /app && python scripts/debug_publishable_gate.py
"""

import sys
import json
import logging
from pathlib import Path

# Ensure backend/src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend/src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s | %(message)s",
)
logger = logging.getLogger("debug_publishable_gate")

from services.vpi_publishable_gate import (
    evaluate_clip_publishability,
    rank_clips,
    PublishableStatus,
    UploadRecommendation,
)


def _make_segment(
    editorial_type: str = "emotional_protection",
    vpi_score: float = 75.0,
    matched_patterns: list = None,
) -> dict:
    return {
        "editorial_type": editorial_type,
        "vpi_score": vpi_score,
        "matched_patterns": matched_patterns or [],
        "vpi_reason": "test",
        "suggested_broll_cue_type": None,
        "final_rank_score": 0.8,
        "editorial_score": 70.0,
        "virality_score": 65,
    }


def _make_hook_plan(
    hook_type: str = "emotional_hook",
    hook_first_4s_score: float = 3.0,
    low_publish_priority: bool = False,
) -> dict:
    return {
        "hook_type": hook_type,
        "hook_first_4s_score": hook_first_4s_score,
        "low_publish_priority": low_publish_priority,
        "headline_text": "Test headline",
        "rendered": True,
        "hook_contract_satisfied": True,
        "overlay_rendered": True,
    }


def _make_editing_plan(activity_score: float = 7.0) -> dict:
    return {
        "editing_activity_score": activity_score,
        "hook_strategy": "test",
        "reframe_strategy": "center",
        "broll_strategy": "editorial",
    }


def _make_broll(category: str = "speaker_focus", asset_path: str = "/tmp/test.mp4") -> list:
    return [
        {
            "category": category,
            "asset_path": asset_path,
            "asset_id": "test_001",
            "asset_source": "pexels",
            "cue_type": "visual_aid",
            "effective_duration": 3.0,
            "visual_query": "test",
        }
    ]


def _make_output_qc(passed: bool = True) -> dict:
    return {
        "passed": passed,
        "overall_score": 85.0 if passed else 30.0,
        "quality_level": "good" if passed else "poor",
        "checks": [
            {"name": "resolution", "passed": passed},
            {"name": "duration", "passed": passed},
            {"name": "audio", "passed": passed},
            {"name": "bitrate", "passed": passed},
        ],
    }


def _make_audio_qc(passed: bool = True) -> dict:
    return {
        "voice_loudness_classification": "good" if passed else "too_low",
        "input_lufs": -16.0 if passed else -28.0,
        "output_lufs": -14.0 if passed else -14.0,
        "input_peak": -2.0 if passed else -0.5,
    }


def _make_silence_plan(mode: str = "moderate", cuts: int = 3) -> dict:
    return {
        "mode": mode,
        "enabled": True,
        "total_removed_s": 2.5,
        "summary": {"total_cuts_applied": cuts},
    }


def _make_clip_info(
    editing_plan: dict = None,
    hook_plan: dict = None,
    broll: list = None,
    output_qc: dict = None,
    audio_qc: dict = None,
    silence_plan: dict = None,
    has_words: bool = True,
    branding_applied: bool = True,
) -> dict:
    info = {
        "editing_plan": editing_plan or _make_editing_plan(),
        "hook_plan": hook_plan or _make_hook_plan(),
        "editorial_broll": broll or _make_broll(),
        "output_qc": output_qc or _make_output_qc(),
        "audio_qc": audio_qc or _make_audio_qc(),
        "silence_edit_plan": silence_plan or _make_silence_plan(),
        "filename": "test_clip.mp4",
        "path": "/tmp/test_clip.mp4",
        "start_time": "00:00",
        "end_time": "00:30",
        "duration": 30.0,
        "text": "This is a test clip for publishable gate debugging.",
        "virality_score": 65,
        "hook_score": 8,
        "engagement_score": 7,
        "value_score": 6,
        "shareability_score": 7,
    }
    if has_words:
        info["words"] = [{"text": "test", "start": 0.0, "end": 1.0}]
    if branding_applied:
        info["brand_treatment"] = {"applied": True}
    return info


def test_case_1_strong_emotional_no_broll():
    """Strong emotional hook, no B-roll, good silence → REVIEW_MANUALLY or READY."""
    logger.info("=" * 60)
    logger.info("TEST CASE 1: Strong emotional hook, no B-roll, good silence")
    logger.info("=" * 60)

    clip = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=8.0),
        hook_plan=_make_hook_plan(hook_type="emotional_hook", hook_first_4s_score=4.0),
        broll=[],  # No B-roll
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=2),
    )
    segment = _make_segment(editorial_type="emotional_protection", vpi_score=80.0)

    result = evaluate_clip_publishability(clip, segment)
    logger.info("  Status: %s", result.publishable_status.value)
    logger.info("  Score:  %.1f", result.publishable_score)
    logger.info("  Reasons: %s", result.publishable_reasons)
    logger.info("  Warnings: %s", result.publishable_warnings)
    logger.info("  Recommendation: %s", result.upload_recommendation.value)
    logger.info("  Best candidate: %s", result.best_candidate)
    logger.info("  Discard recommended: %s", result.discard_recommended)

    # Expected: REVIEW_MANUALLY (no B-roll penalty but no B-roll = not perfect)
    # or READY if score >= 70
    assert result.publishable_status in (
        PublishableStatus.REVIEW_MANUALLY,
        PublishableStatus.READY_TO_UPLOAD,
    ), f"Expected REVIEW_MANUALLY or READY, got {result.publishable_status}"
    assert result.publishable_score >= 50, f"Expected score >= 50, got {result.publishable_score}"
    logger.info("  ✅ PASSED\n")
    return result


def test_case_2_weak_intro():
    """weak_intro hook → NEEDS_FIX / REVIEW_MANUALLY, discard_recommended."""
    logger.info("=" * 60)
    logger.info("TEST CASE 2: weak_intro hook")
    logger.info("=" * 60)

    clip = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=6.0),
        hook_plan=_make_hook_plan(
            hook_type="weak_intro",
            hook_first_4s_score=1.0,
            low_publish_priority=True,
        ),
        broll=_make_broll(category="speaker_focus"),
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=3),
    )
    segment = _make_segment(editorial_type="actionable_advice", vpi_score=60.0)

    result = evaluate_clip_publishability(clip, segment)
    logger.info("  Status: %s", result.publishable_status.value)
    logger.info("  Score:  %.1f", result.publishable_score)
    logger.info("  Reasons: %s", result.publishable_reasons)
    logger.info("  Warnings: %s", result.publishable_warnings)
    logger.info("  Recommendation: %s", result.upload_recommendation.value)
    logger.info("  Best candidate: %s", result.best_candidate)
    logger.info("  Discard recommended: %s", result.discard_recommended)
    logger.info("  Weak intro detected: %s", result.weak_intro_detected)

    # Expected: NEEDS_FIX or REVIEW_MANUALLY (weak intro penalty)
    assert result.publishable_status in (
        PublishableStatus.NEEDS_FIX,
        PublishableStatus.REVIEW_MANUALLY,
    ), f"Expected NEEDS_FIX or REVIEW_MANUALLY, got {result.publishable_status}"
    assert result.weak_intro_detected, "Expected weak_intro_detected=True"
    assert result.publishable_score < 70, f"Expected score < 70, got {result.publishable_score}"
    logger.info("  ✅ PASSED\n")
    return result


def test_case_3_forbidden_broll():
    """Forbidden B-roll asset → DO_NOT_UPLOAD."""
    logger.info("=" * 60)
    logger.info("TEST CASE 3: Forbidden B-roll asset")
    logger.info("=" * 60)

    # Simulate a forbidden asset by using a broll entry with a known forbidden path
    clip = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=7.0),
        hook_plan=_make_hook_plan(hook_type="objection_hook", hook_first_4s_score=3.5),
        broll=_make_broll(
            category="documents_admin",
            asset_path="/app/assets/broll/forbidden/medical_procedure.mp4",
        ),
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=2),
    )
    # Mark the broll item as forbidden
    clip["editorial_broll"][0]["forbidden"] = True
    clip["editorial_broll"][0]["forbidden_reason"] = "medical_content"
    segment = _make_segment(editorial_type="risk_warning", vpi_score=70.0)

    result = evaluate_clip_publishability(clip, segment)
    logger.info("  Status: %s", result.publishable_status.value)
    logger.info("  Score:  %.1f", result.publishable_score)
    logger.info("  Reasons: %s", result.publishable_reasons)
    logger.info("  Warnings: %s", result.publishable_warnings)
    logger.info("  Recommendation: %s", result.upload_recommendation.value)
    logger.info("  Forbidden B-roll detected: %s", result.forbidden_broll_detected)

    # Expected: DO_NOT_UPLOAD
    assert result.publishable_status == PublishableStatus.DO_NOT_UPLOAD, (
        f"Expected DO_NOT_UPLOAD, got {result.publishable_status}"
    )
    assert result.forbidden_broll_detected, "Expected forbidden_broll_detected=True"
    assert result.publishable_score < 30, f"Expected score < 30, got {result.publishable_score}"
    logger.info("  ✅ PASSED\n")
    return result


def test_case_4_generic_docs_broll():
    """Technical OK + generic documents_admin B-roll → REVIEW_MANUALLY / NEEDS_FIX."""
    logger.info("=" * 60)
    logger.info("TEST CASE 4: Technical OK + generic documents_admin B-roll")
    logger.info("=" * 60)

    clip = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=7.0),
        hook_plan=_make_hook_plan(hook_type="emotional_hook", hook_first_4s_score=3.0),
        broll=_make_broll(
            category="documents_admin",
            asset_path="/app/assets/broll/documents_admin/03.jpg",
        ),
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=2),
    )
    segment = _make_segment(editorial_type="emotional_protection", vpi_score=75.0)

    result = evaluate_clip_publishability(clip, segment)
    logger.info("  Status: %s", result.publishable_status.value)
    logger.info("  Score:  %.1f", result.publishable_score)
    logger.info("  Reasons: %s", result.publishable_reasons)
    logger.info("  Warnings: %s", result.publishable_warnings)
    logger.info("  Recommendation: %s", result.upload_recommendation.value)
    logger.info("  Generic B-roll detected: %s", result.generic_broll_detected)

    # Expected: REVIEW_MANUALLY or NEEDS_FIX (generic B-roll penalty)
    assert result.publishable_status in (
        PublishableStatus.REVIEW_MANUALLY,
        PublishableStatus.NEEDS_FIX,
    ), f"Expected REVIEW_MANUALLY or NEEDS_FIX, got {result.publishable_status}"
    assert result.generic_broll_detected, "Expected generic_broll_detected=True"
    assert result.publishable_score < 70, f"Expected score < 70, got {result.publishable_score}"
    logger.info("  ✅ PASSED\n")
    return result


def test_case_5_strong_objection_hook():
    """Strong objection hook, good everything → READY_TO_UPLOAD."""
    logger.info("=" * 60)
    logger.info("TEST CASE 5: Strong objection hook, everything good")
    logger.info("=" * 60)

    clip = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=9.0),
        hook_plan=_make_hook_plan(
            hook_type="objection_hook",
            hook_first_4s_score=5.0,
            low_publish_priority=False,
        ),
        broll=_make_broll(category="speaker_focus"),
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=1),
        has_words=True,
        branding_applied=True,
    )
    segment = _make_segment(editorial_type="client_objection", vpi_score=90.0)

    result = evaluate_clip_publishability(clip, segment)
    logger.info("  Status: %s", result.publishable_status.value)
    logger.info("  Score:  %.1f", result.publishable_score)
    logger.info("  Reasons: %s", result.publishable_reasons)
    logger.info("  Warnings: %s", result.publishable_warnings)
    logger.info("  Recommendation: %s", result.upload_recommendation.value)
    logger.info("  Best candidate: %s", result.best_candidate)
    logger.info("  Discard recommended: %s", result.discard_recommended)

    # Expected: READY_TO_UPLOAD
    assert result.publishable_status == PublishableStatus.READY_TO_UPLOAD, (
        f"Expected READY_TO_UPLOAD, got {result.publishable_status}"
    )
    assert result.publishable_score >= 70, f"Expected score >= 70, got {result.publishable_score}"
    assert not result.discard_recommended, "Expected discard_recommended=False"
    logger.info("  ✅ PASSED\n")
    return result


def test_rank_clips():
    """Test rank_clips() with multiple clips to verify best_candidate/discard_recommended."""
    logger.info("=" * 60)
    logger.info("TEST RANK: rank_clips() with 3 clips")
    logger.info("=" * 60)

    # Clip A: strong objection hook → READY
    clip_a = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=9.0),
        hook_plan=_make_hook_plan(hook_type="objection_hook", hook_first_4s_score=5.0),
        broll=_make_broll(category="speaker_focus"),
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=1),
    )
    clip_a["filename"] = "clip_a.mp4"

    # Clip B: weak_intro → NEEDS_FIX
    clip_b = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=5.0),
        hook_plan=_make_hook_plan(hook_type="weak_intro", hook_first_4s_score=1.0, low_publish_priority=True),
        broll=_make_broll(category="speaker_focus"),
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=3),
    )
    clip_b["filename"] = "clip_b.mp4"

    # Clip C: forbidden B-roll → DO_NOT_UPLOAD
    clip_c = _make_clip_info(
        editing_plan=_make_editing_plan(activity_score=7.0),
        hook_plan=_make_hook_plan(hook_type="emotional_hook", hook_first_4s_score=3.0),
        broll=_make_broll(category="documents_admin", asset_path="/app/assets/broll/forbidden/surgery.mp4"),
        output_qc=_make_output_qc(passed=True),
        audio_qc=_make_audio_qc(passed=True),
        silence_plan=_make_silence_plan(mode="moderate", cuts=2),
    )
    clip_c["editorial_broll"][0]["forbidden"] = True
    clip_c["editorial_broll"][0]["forbidden_reason"] = "medical_content"
    clip_c["filename"] = "clip_c.mp4"

    render_results = [
        (0, clip_a, 10.5),
        (1, clip_b, 12.3),
        (2, clip_c, 9.8),
    ]

    ranked = rank_clips(render_results)
    logger.info("  Ranked %d clips:", len(ranked))

    for r in ranked:
        logger.info(
            "    %s → status=%s score=%.1f best=%s discard=%s rec=%s",
            r.get("filename"),
            r.get("publishable_status"),
            r.get("publishable_score", 0),
            r.get("best_candidate"),
            r.get("discard_recommended"),
            r.get("upload_recommendation"),
        )

    # Verify best_candidate is set on clip A (the best one)
    best = [r for r in ranked if r.get("best_candidate")]
    assert len(best) == 1, f"Expected exactly 1 best_candidate, got {len(best)}"
    assert best[0]["filename"] == "clip_a.mp4", f"Expected clip_a as best, got {best[0]['filename']}"

    # Verify discard_recommended on clip B (weak_intro) and clip C (forbidden)
    discarded = [r for r in ranked if r.get("discard_recommended")]
    assert len(discarded) >= 2, f"Expected at least 2 discard_recommended, got {len(discarded)}"
    discarded_filenames = {r["filename"] for r in discarded}
    assert "clip_b.mp4" in discarded_filenames, "Expected clip_b to be discard_recommended"
    assert "clip_c.mp4" in discarded_filenames, "Expected clip_c to be discard_recommended"

    logger.info("  ✅ PASSED\n")
    return ranked


def main():
    logger.info("")
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║   VPI Publishable Gate v3.1 — Diagnostic Script        ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info("")

    results = {}

    try:
        r1 = test_case_1_strong_emotional_no_broll()
        results["test_1_strong_emotional_no_broll"] = r1.publishable_status.value
    except AssertionError as e:
        logger.error("  ❌ FAILED: %s", e)
        results["test_1_strong_emotional_no_broll"] = f"FAILED: {e}"

    try:
        r2 = test_case_2_weak_intro()
        results["test_2_weak_intro"] = r2.publishable_status.value
    except AssertionError as e:
        logger.error("  ❌ FAILED: %s", e)
        results["test_2_weak_intro"] = f"FAILED: {e}"

    try:
        r3 = test_case_3_forbidden_broll()
        results["test_3_forbidden_broll"] = r3.publishable_status.value
    except AssertionError as e:
        logger.error("  ❌ FAILED: %s", e)
        results["test_3_forbidden_broll"] = f"FAILED: {e}"

    try:
        r4 = test_case_4_generic_docs_broll()
        results["test_4_generic_docs_broll"] = r4.publishable_status.value
    except AssertionError as e:
        logger.error("  ❌ FAILED: %s", e)
        results["test_4_generic_docs_broll"] = f"FAILED: {e}"

    try:
        r5 = test_case_5_strong_objection_hook()
        results["test_5_strong_objection_hook"] = r5.publishable_status.value
    except AssertionError as e:
        logger.error("  ❌ FAILED: %s", e)
        results["test_5_strong_objection_hook"] = f"FAILED: {e}"

    try:
        test_rank_clips()
        results["test_rank_clips"] = "PASSED"
    except AssertionError as e:
        logger.error("  ❌ FAILED: %s", e)
        results["test_rank_clips"] = f"FAILED: {e}"

    logger.info("")
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║   SUMMARY                                               ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    all_passed = True
    for name, status in results.items():
        mark = "✅" if "FAILED" not in str(status) else "❌"
        if "FAILED" in str(status):
            all_passed = False
        logger.info("  %s %s: %s", mark, name, status)

    logger.info("")
    if all_passed:
        logger.info("  🎉 All tests passed!")
    else:
        logger.info("  ⚠️  Some tests failed — review output above.")
    logger.info("")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
