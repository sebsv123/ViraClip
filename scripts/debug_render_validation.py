#!/usr/bin/env python3
"""
VPI Render Validation Harness — Debug / Fake Data Script (FASE 9)
==================================================================

Generates minimal fake clip data to test the validation pipeline without
real rendered clips.  Tests scoring, repetition detection, report
generation, and graceful failure when ffprobe is unavailable.

Usage:
  python scripts/debug_render_validation.py
  python scripts/debug_render_validation.py --out /tmp/vpi_debug
  python scripts/debug_render_validation.py --no-ffprobe  (skip ffprobe tests)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
log = logging.getLogger("vpi_debug")

# ── Import the validation module ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from scripts.validate_vpi_render_quality import (
        compute_visual_publishability_score,
        derive_taskshort,
        detect_broll_repetition,
        find_task_outputs,
        generate_csv_report,
        generate_json_report,
        generate_markdown_report,
        load_metadata_jsons,
        probe_video,
        technical_qc,
        traffic_light,
        validate_branding,
        validate_broll_for_weak_intro,
        validate_hook,
        validate_silence_edit,
        validate_smart_reframe,
        validate_subtitles,
        WEAK_INTRO_TYPES,
        STRONG_HOOK_TYPES,
    )
except ImportError as e:
    log.error("Cannot import validation module: %s", e)
    log.error("Make sure scripts/validate_vpi_render_quality.py exists and is valid.")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# Fake data generators
# ══════════════════════════════════════════════════════════════════════════════

def make_fake_probe(
    has_audio: bool = True,
    has_video: bool = True,
    width: int = 1080,
    height: int = 1920,
    duration: float = 30.0,
    fps: float = 30.0,
    video_codec: str = "h264",
    audio_codec: str = "aac",
    file_size_mb: float = 15.0,
) -> Dict[str, Any]:
    """Create a fake ffprobe result."""
    return {
        "path": "/fake/path.mp4",
        "exists": True,
        "file_size_bytes": int(file_size_mb * 1024 * 1024),
        "file_size_mb": file_size_mb,
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "has_audio": has_audio,
        "has_video": has_video,
        "aspect_ratio": f"{width}:{height}",
        "is_vertical_1080x1920": width == 1080 and height == 1920,
    }


def make_fake_clip(
    clip_index: int = 0,
    editorial_type: str = "weak_intro",
    hook_quality: str = "weak_intro",
    broll_count: int = 0,
    broll_assets: Optional[List[Dict]] = None,
    watermark_applied: bool = True,
    has_subtitles: bool = True,
    smart_reframe_skipped: bool = False,
    silence_edit_errors: Optional[str] = None,
    probe: Optional[Dict] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a fake clip dict for testing."""
    if probe is None:
        probe = make_fake_probe()

    if filename is None:
        filename = f"clip_{clip_index:02d}.mp4"

    broll_assets = broll_assets or []

    clip = {
        "path": f"/fake/{filename}",
        "clip_index": clip_index,
        "filename": filename,
        "probe": probe,
        "editorial_type": editorial_type,
        "hook_quality": hook_quality,
        "broll_count": broll_count,
        "broll_assets": broll_assets,
        "broll_sources": "pexels" if broll_count > 0 else "none",
        "watermark_applied": watermark_applied,
        "subtitle_intelligence": {"has_subtitles": has_subtitles},
        "smart_reframe": {"skipped": smart_reframe_skipped, "reason": "test"},
        "silence_edit_plan": {"errors": silence_edit_errors},
        "branding": {"watermark_applied": watermark_applied},
        "subtitles": {"captions_present": has_subtitles},
        "smart_reframe": {"applied": not smart_reframe_skipped, "reason": "test"},
        "silence_edit": {"applied": silence_edit_errors is None, "errors": silence_edit_errors},
        "all_warnings": [],
    }
    return clip


def make_fake_metadata_by_index(
    num_clips: int = 3,
    with_repeats: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """Create fake metadata dicts keyed by clip_index."""
    meta: Dict[int, Dict[str, Any]] = {}
    for i in range(num_clips):
        broll_assets = [
            {
                "asset_id": f"asset_{i}_1",
                "provider_video_id": f"prov_{i}_1",
                "visual_fingerprint": f"fp_{i}_1",
                "category": "business",
                "source": "pexels",
                "query": "office work",
            },
            {
                "asset_id": f"asset_{i}_2",
                "provider_video_id": f"prov_{i}_2",
                "visual_fingerprint": f"fp_{i}_2",
                "category": "technology",
                "source": "pexels",
                "query": "coding",
            },
        ]
        if with_repeats and i > 0:
            # Repeat first clip's first asset
            broll_assets[0] = {
                "asset_id": "asset_0_1",
                "provider_video_id": "prov_0_1",
                "visual_fingerprint": "fp_0_1",
                "category": "business",
                "source": "pexels",
                "query": "office work",
            }
        meta[i] = {
            "clip_index": i,
            "broll_assets": broll_assets,
            "broll_count": len(broll_assets),
            "broll_sources": "pexels",
        }
    return meta


# ══════════════════════════════════════════════════════════════════════════════
# Test suites
# ══════════════════════════════════════════════════════════════════════════════

def test_scoring() -> int:
    """Test compute_visual_publishability_score with various scenarios."""
    log.info("─" * 50)
    log.info("TEST: Scoring")
    log.info("─" * 50)
    failures = 0

    # Test 1: Perfect clip
    clip = make_fake_clip(
        editorial_type="client_objection",
        hook_quality="strong",
        broll_count=3,
    )
    probe = clip["probe"]
    repetition = detect_broll_repetition(make_fake_metadata_by_index(1))
    result = compute_visual_publishability_score(clip, probe, repetition)
    score = result["score"]
    classification = result["classification"]
    log.info("  Perfect clip: score=%d, classification=%s", score, classification)
    if score < 85:
        log.warning("    ✗ Expected score >= 85, got %d", score)
        failures += 1
    if classification != "READY_TO_UPLOAD":
        log.warning("    ✗ Expected READY_TO_UPLOAD, got %s", classification)
        failures += 1

    # Test 2: No audio
    clip2 = make_fake_clip(probe=make_fake_probe(has_audio=False))
    result2 = compute_visual_publishability_score(clip2, clip2["probe"], repetition)
    log.info("  No audio: score=%d, classification=%s", result2["score"], result2["classification"])
    if result2["score"] > 20:
        log.warning("    ✗ Expected score <= 20 for no audio, got %d", result2["score"])
        failures += 1

    # Test 3: weak_intro with B-roll (should be penalized heavily)
    clip3 = make_fake_clip(
        editorial_type="weak_intro",
        hook_quality="weak_intro",
        broll_count=2,
    )
    result3 = compute_visual_publishability_score(clip3, clip3["probe"], repetition)
    log.info("  weak_intro + broll: score=%d, classification=%s", result3["score"], result3["classification"])
    if result3["score"] > 30:
        log.warning("    ✗ Expected score <= 30 for weak_intro with broll, got %d", result3["score"])
        failures += 1

    # Test 4: Bad resolution
    clip4 = make_fake_clip(probe=make_fake_probe(width=640, height=480))
    result4 = compute_visual_publishability_score(clip4, clip4["probe"], repetition)
    log.info("  Bad resolution: score=%d, classification=%s", result4["score"], result4["classification"])
    if result4["score"] > 50:
        log.warning("    ✗ Expected score <= 50 for bad resolution, got %d", result4["score"])
        failures += 1

    # Test 5: Hook missing for strong editorial
    clip5 = make_fake_clip(
        editorial_type="client_objection",
        hook_quality="missing",
    )
    result5 = compute_visual_publishability_score(clip5, clip5["probe"], repetition)
    log.info("  Hook missing (strong editorial): score=%d, classification=%s", result5["score"], result5["classification"])
    if "hook_missing_penalty" not in result5.get("breakdown", {}):
        log.warning("    ✗ Expected hook_missing_penalty in breakdown")
        failures += 1

    # Test 6: Exact repeated broll
    meta_with_repeats = make_fake_metadata_by_index(3, with_repeats=True)
    repetition_repeats = detect_broll_repetition(meta_with_repeats)
    clip6 = make_fake_clip(
        editorial_type="statistic",
        hook_quality="strong",
        broll_count=2,
        broll_assets=meta_with_repeats[0].get("broll_assets", []),
    )
    result6 = compute_visual_publishability_score(clip6, clip6["probe"], repetition_repeats)
    log.info("  With repeats: score=%d, classification=%s", result6["score"], result6["classification"])
    if "exact_repeat_penalty" not in result6.get("breakdown", {}):
        log.warning("    ✗ Expected exact_repeat_penalty in breakdown")
        failures += 1

    if failures == 0:
        log.info("  ✅ All scoring tests passed")
    else:
        log.warning("  ❌ %d scoring test(s) failed", failures)

    return failures


def test_repetition_detection() -> int:
    """Test B-roll repetition detection."""
    log.info("─" * 50)
    log.info("TEST: Repetition Detection")
    log.info("─" * 50)
    failures = 0

    # No repeats
    meta_no_repeats = make_fake_metadata_by_index(3, with_repeats=False)
    result = detect_broll_repetition(meta_no_repeats)
    log.info("  No repeats: %d exact, %d provider, %d fingerprint",
             len(result["exact_repeats"]),
             len(result["provider_repeats"]),
             len(result["fingerprint_repeats"]))
    if result["exact_repeats"]:
        log.warning("    ✗ Expected no exact repeats, got %s", result["exact_repeats"])
        failures += 1

    # With repeats
    meta_with_repeats = make_fake_metadata_by_index(3, with_repeats=True)
    result2 = detect_broll_repetition(meta_with_repeats)
    log.info("  With repeats: %d exact, %d provider, %d fingerprint",
             len(result2["exact_repeats"]),
             len(result2["provider_repeats"]),
             len(result2["fingerprint_repeats"]))
    if not result2["exact_repeats"]:
        log.warning("    ✗ Expected exact repeats, got none")
        failures += 1

    if failures == 0:
        log.info("  ✅ All repetition tests passed")
    else:
        log.warning("  ❌ %d repetition test(s) failed", failures)

    return failures


def test_report_generation(tmp_dir: Path) -> int:
    """Test all three report generators."""
    log.info("─" * 50)
    log.info("TEST: Report Generation")
    log.info("─" * 50)
    failures = 0

    clips = [
        make_fake_clip(clip_index=0, editorial_type="weak_intro", hook_quality="weak_intro"),
        make_fake_clip(clip_index=1, editorial_type="client_objection", hook_quality="strong", broll_count=3),
        make_fake_clip(clip_index=2, editorial_type="statistic", hook_quality="acceptable", broll_count=1),
    ]

    # Compute scores for each clip
    meta = make_fake_metadata_by_index(3)
    repetition = detect_broll_repetition(meta)
    for clip in clips:
        vp = compute_visual_publishability_score(clip, clip["probe"], repetition)
        clip["visual_publishability"] = vp

    task_id = "test-task-1234"
    taskshort = "test1234"

    # Markdown
    try:
        md_result = generate_markdown_report(clips, repetition, task_id, taskshort, tmp_dir)
        md_path = tmp_dir / f"render_validation_{task_id}.md"
        with open(md_path, "w") as f:
            f.write(md_result)
        log.info("  Markdown report: %s (%d bytes)", md_path.name, md_path.stat().st_size)
    except Exception as e:
        log.warning("  ✗ Markdown report failed: %s", e)
        failures += 1

    # CSV
    try:
        csv_result = generate_csv_report(clips, repetition, tmp_dir)
        log.info("  CSV report: %s", csv_result)
    except Exception as e:
        log.warning("  ✗ CSV report failed: %s", e)
        failures += 1

    # JSON
    try:
        json_result = generate_json_report(clips, repetition, tmp_dir, task_id)
        log.info("  JSON report: %s", json_result)
    except Exception as e:
        log.warning("  ✗ JSON report failed: %s", e)
        failures += 1

    if failures == 0:
        log.info("  ✅ All report generation tests passed")
    else:
        log.warning("  ❌ %d report test(s) failed", failures)

    return failures


def test_editorial_validation() -> int:
    """Test editorial validation functions."""
    log.info("─" * 50)
    log.info("TEST: Editorial Validation")
    log.info("─" * 50)
    failures = 0

    hook_bank = {
        "client_objection": [
            {"hook_type": "bold_statement", "text": "Most people get this wrong..."},
            {"hook_type": "statistic", "text": "87% of businesses fail..."},
        ],
        "weak_intro": {"rules": "no_hook_expected"},
    }

    # Test validate_hook
    quality, warnings = validate_hook("client_objection", {"hook_plan": {"hook_type": "bold_statement"}}, hook_bank)
    log.info("  Hook (client_objection, bold_statement): quality=%s, warnings=%s", quality, warnings)
    if quality not in ("strong", "acceptable"):
        log.warning("    ✗ Expected acceptable/strong, got %s", quality)
        failures += 1

    quality2, warnings2 = validate_hook("weak_intro", {}, hook_bank)
    log.info("  Hook (weak_intro): quality=%s, warnings=%s", quality2, warnings2)
    if quality2 != "weak_intro":
        log.warning("    ✗ Expected weak_intro, got %s", quality2)
        failures += 1

    # Test validate_broll_for_weak_intro
    bw = validate_broll_for_weak_intro("weak_intro", {"broll_count": 2, "broll_assets": [{"id": "a"}]}, True)
    log.info("  B-roll weak_intro check: %d warnings", len(bw))
    if not bw:
        log.warning("    ✗ Expected warnings for weak_intro with broll")
        failures += 1

    bw2 = validate_broll_for_weak_intro("client_objection", {"broll_count": 2}, False)
    log.info("  B-roll non-weak_intro check: %d warnings", len(bw2))
    if bw2:
        log.warning("    ✗ Expected no warnings for non-weak_intro")
        failures += 1

    # Test validate_branding
    br = validate_branding({"watermark_applied": False})
    log.info("  Branding (no watermark): %d warnings", len(br))
    if not br:
        log.warning("    ✗ Expected warning for missing watermark")
        failures += 1

    br2 = validate_branding({"watermark_applied": True})
    log.info("  Branding (with watermark): %d warnings", len(br2))
    if br2:
        log.warning("    ✗ Expected no warnings for watermark present")
        failures += 1

    # Test validate_subtitles
    sb = validate_subtitles({"subtitle_intelligence": {"has_subtitles": False}})
    log.info("  Subtitles (missing): %d warnings", len(sb))
    if not sb:
        log.warning("    ✗ Expected warning for missing subtitles")
        failures += 1

    # Test validate_smart_reframe
    sr = validate_smart_reframe({"smart_reframe": {"skipped": True}})
    log.info("  Smart reframe (skipped): %d warnings", len(sr))
    if not sr:
        log.warning("    ✗ Expected warning for skipped smart reframe")
        failures += 1

    # Test validate_silence_edit
    se = validate_silence_edit({"silence_edit_plan": {"errors": "timeout"}})
    log.info("  Silence edit (errors): %d warnings", len(se))
    if not se:
        log.warning("    ✗ Expected warning for silence edit errors")
        failures += 1

    if failures == 0:
        log.info("  ✅ All editorial validation tests passed")
    else:
        log.warning("  ❌ %d editorial validation test(s) failed", failures)

    return failures


def test_ffprobe_graceful_failure(tmp_dir: Path) -> int:
    """Test that probe_video handles missing ffprobe gracefully."""
    log.info("─" * 50)
    log.info("TEST: ffprobe Graceful Failure")
    log.info("─" * 50)
    failures = 0

    # Create a fake non-video file
    fake_file = tmp_dir / "not_a_video.txt"
    fake_file.write_text("this is not a video file")

    result = probe_video(fake_file)
    log.info("  probe_video on non-video: exists=%s, has_video=%s, has_audio=%s",
             result.get("exists"), result.get("has_video"), result.get("has_audio"))
    # Should not crash - ffprobe will fail but we handle it
    if "ffprobe_error" not in result:
        log.info("  (ffprobe may have succeeded or returned empty data)")
    else:
        log.info("  ffprobe error: %s", result["ffprobe_error"])

    # Test technical_qc on empty probe
    empty_probe = {"exists": False, "file_size_bytes": 0, "has_video": False, "has_audio": False, "duration": 0, "video_codec": ""}
    passed, warnings = technical_qc(empty_probe)
    log.info("  technical_qc on empty: passed=%s, %d warnings", passed, len(warnings))
    if passed:
        log.warning("    ✗ Expected technical_qc to fail on empty probe")
        failures += 1

    if failures == 0:
        log.info("  ✅ All ffprobe graceful failure tests passed")
    else:
        log.warning("  ❌ %d ffprobe test(s) failed", failures)

    return failures


def test_traffic_light() -> int:
    """Test traffic_light function."""
    log.info("─" * 50)
    log.info("TEST: Traffic Light")
    log.info("─" * 50)
    failures = 0

    tests = {
        "READY_TO_UPLOAD": "🟢",
        "REVIEW_MANUALLY": "🟡",
        "NEEDS_FIX": "🔴",
        "DO_NOT_UPLOAD": "⛔",
        "UNKNOWN": "⚪",
    }

    for status, expected_emoji in tests.items():
        result = traffic_light(status)
        if result != expected_emoji:
            log.warning("  ✗ traffic_light('%s') = '%s', expected '%s'", status, result, expected_emoji)
            failures += 1
        else:
            log.info("  traffic_light('%s') = '%s' ✅", status, result)

    if failures == 0:
        log.info("  ✅ All traffic light tests passed")
    else:
        log.warning("  ❌ %d traffic light test(s) failed", failures)

    return failures


def test_taskshort_and_discovery(tmp_dir: Path) -> int:
    """Test UUID→taskshort and exports/clips discovery."""
    log.info("─" * 50)
    log.info("TEST: Taskshort + Discovery")
    log.info("─" * 50)
    failures = 0
    old_cwd = Path.cwd()
    task_id = "d60e9e53-aac3-41e2-8bd8-e009b9ebbf81"
    taskshort = "d60e9e53"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(tmp_dir)
        clips_dir = tmp_dir / "exports" / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        (clips_dir / f"mastered_brand_sub_silence_clip_{taskshort}_1_viral_40_0020-0050.mp4").write_bytes(b"fake")
        out_dir = tmp_dir / "outputs" / "vpi" / "2026-05-27" / f"task_{taskshort}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"clip_{taskshort}_1_metadata.json").write_text(json.dumps({"clip_index": 1}), encoding="utf-8")

        derived = derive_taskshort(task_id, None)
        log.info("  Derived taskshort: %s", derived)
        if derived != taskshort:
            failures += 1

        discovery = find_task_outputs(task_id=task_id, taskshort=None, clips_dir=None)
        log.info(
            "  Discovery: clips=%d metadata=%d clips_dir=%s",
            len(discovery.get("clips", [])),
            len(discovery.get("metadata_jsons", [])),
            discovery.get("clips_dir"),
        )
        if len(discovery.get("clips", [])) != 1:
            failures += 1
        if len(discovery.get("metadata_jsons", [])) < 1:
            failures += 1
        if str(discovery.get("clips_dir")) != "exports/clips":
            failures += 1
    finally:
        os.chdir(old_cwd)

    if failures == 0:
        log.info("  ✅ Taskshort/discovery tests passed")
    else:
        log.warning("  ❌ %d taskshort/discovery test(s) failed", failures)
    return failures


def test_metadata_missing_review_status() -> int:
    """Metadata missing + technical pass should review manually, not needs fix."""
    log.info("─" * 50)
    log.info("TEST: Metadata Missing Technical Pass")
    log.info("─" * 50)
    clip = make_fake_clip(
        filename="mastered_brand_sub_silence_clip_d60e9e53_1_viral_40_0020-0050.mp4",
        hook_quality="acceptable",
    )
    clip["metadata_missing"] = True
    clip["technical_qc"] = {"passed": True, "status": "PASS", "warnings": []}
    clip["all_warnings"] = ["metadata_not_found_but_technical_qc_passed"]
    result = compute_visual_publishability_score(clip, clip["probe"], detect_broll_repetition({}))
    log.info("  Metadata missing: score=%d classification=%s", result["score"], result["classification"])
    if result["classification"] != "REVIEW_MANUALLY":
        log.warning("    ✗ Expected REVIEW_MANUALLY")
        return 1
    log.info("  ✅ Metadata missing status test passed")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VPI Render Validation Debug / Fake Data Script (FASE 9)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory for test reports (default: temp dir)",
    )
    parser.add_argument(
        "--no-ffprobe",
        action="store_true",
        help="Skip ffprobe tests (useful in CI without ffmpeg)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    log.info("=" * 60)
    log.info("VPI Render Validation — Debug Suite (FASE 9)")
    log.info("Started: %s", datetime.now().isoformat())
    log.info("=" * 60)

    # Create temp output directory
    if args.out:
        tmp_dir = Path(args.out)
        tmp_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_dir = Path(tempfile.mkdtemp(prefix="vpi_debug_"))

    log.info("Output directory: %s", tmp_dir)
    log.info("")

    total_failures = 0

    # Run test suites
    total_failures += test_scoring()
    total_failures += test_repetition_detection()
    total_failures += test_report_generation(tmp_dir)
    total_failures += test_editorial_validation()
    total_failures += test_traffic_light()
    total_failures += test_taskshort_and_discovery(tmp_dir / "discovery")
    total_failures += test_metadata_missing_review_status()

    if not args.no_ffprobe:
        total_failures += test_ffprobe_graceful_failure(tmp_dir)
    else:
        log.info("─" * 50)
        log.info("SKIP: ffprobe tests (--no-ffprobe)")
        log.info("─" * 50)

    # Summary
    log.info("")
    log.info("=" * 60)
    if total_failures == 0:
        log.info("RESULT: ✅ ALL TESTS PASSED")
    else:
        log.warning("RESULT: ❌ %d TEST(S) FAILED", total_failures)
    log.info("Reports in: %s", tmp_dir)
    log.info("=" * 60)

    # List generated files
    log.info("Generated files:")
    for f in sorted(tmp_dir.iterdir()):
        log.info("  - %s (%d bytes)", f.name, f.stat().st_size)

    return total_failures


if __name__ == "__main__":
    sys.exit(main())
