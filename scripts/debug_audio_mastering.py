#!/usr/bin/env python3
"""
VPI Audio Mastering Debug Script (FASE 7)
==========================================

Measures loudness, applies mastering, and prints before/after metrics.
Updated for v3.0: reports LUFS, mean_volume fallback, max_volume, status.

Usage:
  python scripts/debug_audio_mastering.py --input path/to/video.mp4 --out /tmp/audio_master_test.mp4
  python scripts/debug_audio_mastering.py --latest --clips-dir temp/uploads/clips
"""

from __future__ import annotations

import argparse
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
log = logging.getLogger("debug_audio_mastering")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from backend.src.services.vpi_audio_mastering import (
        AudioLoudnessReport,
        AudioMasteringResult,
        audio_mastering_enabled,
        build_audio_qc_metadata,
        build_audio_publish_warnings,
        classify_audio_voice_status,
        get_target_lufs,
        get_true_peak,
        master_audio_for_social,
        measure_loudness,
        should_apply_audio_mastering,
    )
except ImportError as e:
    log.error("Cannot import audio mastering module: %s", e)
    log.error("Make sure backend/src/services/vpi_audio_mastering.py exists.")
    sys.exit(1)


def find_latest_clip(clips_dir: str) -> Optional[Path]:
    """Find the latest clip file in the clips directory."""
    candidates = [Path(clips_dir), Path("exports/clips"), Path("temp/uploads/clips")]
    mp4_files = []
    for clips_path in candidates:
        if clips_path.exists():
            mp4_files.extend(clips_path.glob("*.mp4"))
    if not mp4_files:
        return None
    return max(mp4_files, key=lambda path: path.stat().st_mtime)


def print_report(report: AudioLoudnessReport, label: str = "Input") -> None:
    """Print a loudness report (v3.0 — shows all available metrics)."""
    log.info("  %s Loudness Report:", label)

    # ── LUFS (prefer output_i, fallback input_i) ──────────────────────────
    lufs = report.output_i if report.output_i is not None else report.input_i
    if lufs is not None:
        log.info("    Integrated LUFS: %.1f", lufs)
    else:
        log.info("    Integrated LUFS: N/A")

    # ── True Peak (prefer output_tp, fallback input_tp) ───────────────────
    tp = report.output_tp if report.output_tp is not None else report.input_tp
    if tp is not None:
        log.info("    True Peak (dBTP): %.1f", tp)
    else:
        log.info("    True Peak (dBTP): N/A")

    # ── LRA ───────────────────────────────────────────────────────────────
    lra = report.output_lra if report.output_lra is not None else report.input_lra
    if lra is not None:
        log.info("    LRA: %.1f", lra)
    else:
        log.info("    LRA: N/A")

    # ── Threshold ─────────────────────────────────────────────────────────
    thresh = report.output_thresh if report.output_thresh is not None else report.input_thresh
    if thresh is not None:
        log.info("    Threshold: %.1f", thresh)
    else:
        log.info("    Threshold: N/A")

    # ── Measurement method ────────────────────────────────────────────────
    log.info("    Method: %s", report.measurement_method)

    # ── Voice status ──────────────────────────────────────────────────────
    log.info("    Voice Status: %s", classify_audio_voice_status(report))

    # ── Normalization info ────────────────────────────────────────────────
    if report.normalization_type:
        log.info("    Normalization: %s", report.normalization_type)
    if report.target_offset is not None:
        log.info("    Target Offset: %.1f", report.target_offset)

    # ── volumedetect fallback metrics ─────────────────────────────────────
    if report.mean_volume is not None:
        log.info("    Mean Volume (dB): %.1f", report.mean_volume)
    if report.max_volume is not None:
        log.info("    Max Volume (dB): %.1f", report.max_volume)

    # ── Raw fields (for debugging) ────────────────────────────────────────
    if report.input_i is not None:
        log.info("    [raw] input_i: %.1f", report.input_i)
    if report.input_tp is not None:
        log.info("    [raw] input_tp: %.1f", report.input_tp)
    if report.output_i is not None:
        log.info("    [raw] output_i: %.1f", report.output_i)
    if report.output_tp is not None:
        log.info("    [raw] output_tp: %.1f", report.output_tp)

    # ── Warnings ──────────────────────────────────────────────────────────
    if report.warnings:
        log.info("    Warnings: %s", ", ".join(report.warnings))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="VPI Audio Mastering Debug Script",
    )
    parser.add_argument("--input", default=None, help="Path to input video file")
    parser.add_argument("--out", default=None, help="Output path for mastered video")
    parser.add_argument("--latest", action="store_true", help="Use latest clip from clips dir")
    parser.add_argument("--clips-dir", default="temp/uploads/clips", help="Clips directory")
    parser.add_argument("--target-lufs", type=float, default=None, help="Target LUFS")
    parser.add_argument("--true-peak", type=float, default=None, help="True peak dBTP")
    args = parser.parse_args(argv)

    # Resolve input file
    input_path: Optional[Path] = None
    if args.input:
        input_path = Path(args.input)
    elif args.latest:
        clip = find_latest_clip(args.clips_dir)
        if clip:
            input_path = clip
            log.info("Using latest clip: %s", clip)
        else:
            log.error("No clips found in %s", args.clips_dir)
            return 1
    else:
        clip = find_latest_clip(args.clips_dir)
        if clip:
            input_path = clip
            log.info("No --input provided; using latest clip: %s", clip)
        else:
            log.error("Provide --input or --latest")
            return 1

    if not input_path or not input_path.exists():
        log.error("Input file not found: %s", input_path)
        return 1

    log.info("=" * 60)
    log.info("VPI Audio Mastering Debug (v3.0)")
    log.info("Input: %s", input_path)
    log.info("File size: %.1f MB", input_path.stat().st_size / (1024 * 1024))
    log.info("Enabled: %s", audio_mastering_enabled())
    log.info("Target LUFS: %s", args.target_lufs or get_target_lufs())
    log.info("True Peak: %s", args.true_peak or get_true_peak())
    log.info("=" * 60)

    # Step 1: Measure input loudness
    log.info("")
    log.info("[1/3] Measuring input loudness...")
    input_report = measure_loudness(str(input_path))
    print_report(input_report, "Input")

    # Log fallback info
    if input_report.measurement_method == "volumedetect_fallback":
        log.info("    ⚠ LUFS unavailable; using mean_volume as fallback estimate")
    elif input_report.measurement_method == "unavailable":
        log.info("    ❌ No measurement available")

    # Step 2: Check if mastering is needed
    log.info("")
    log.info("[2/3] Should apply mastering? %s", should_apply_audio_mastering(input_report))

    # Step 3: Apply mastering
    log.info("")
    log.info("[3/3] Applying audio mastering...")

    if args.out:
        output_path = args.out
    else:
        output_path = str(input_path.parent / f"mastered_{input_path.name}")

    result = master_audio_for_social(
        input_path=str(input_path),
        output_path=output_path,
        target_lufs=args.target_lufs,
        true_peak=args.true_peak,
    )

    log.info("")
    log.info("=" * 60)
    log.info("RESULT")
    log.info("=" * 60)
    log.info("  Applied: %s", result.applied)
    log.info("  Method: %s", result.method)
    log.info("  Output: %s", result.output_path)

    if result.applied and Path(result.output_path).exists():
        out_size = Path(result.output_path).stat().st_size / (1024 * 1024)
        log.info("  Output size: %.1f MB", out_size)

    # Print output loudness report
    if result.output_loudness_report:
        log.info("")
        print_report(result.output_loudness_report, "Output")
    elif result.loudness_report:
        log.info("")
        print_report(result.loudness_report, "Output (fallback)")

    # Print input loudness report (separate)
    if result.input_loudness_report and result.input_loudness_report is not result.output_loudness_report:
        log.info("")
        print_report(result.input_loudness_report, "Input (from result)")

    if result.warnings:
        log.info("  Warnings: %s", ", ".join(result.warnings))

    if result.error:
        log.error("  Error: %s", result.error)

    # Print QC metadata
    log.info("")
    log.info("QC Metadata:")
    qc_meta = build_audio_qc_metadata(result)
    for k, v in qc_meta.items():
        log.info("  %s: %s", k, v)

    pub_warnings = build_audio_publish_warnings(result)
    if pub_warnings:
        log.info("  Publish warnings: %s", ", ".join(pub_warnings))

    log.info("=" * 60)

    # Return 0 if we got any measurement (even fallback)
    qc_method = qc_meta.get("audio_measurement_method", "unavailable")
    has_measurement = qc_method not in ("unavailable",)
    has_lufs = qc_meta.get("output_lufs") is not None or qc_meta.get("input_lufs") is not None
    return 0 if (result.applied or result.method in {"skipped", "disabled"} or has_measurement or has_lufs) else 1


if __name__ == "__main__":
    sys.exit(main())
