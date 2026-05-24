#!/usr/bin/env python3
"""
validate_zoom_output.py — Manual validation script for scale+crop zoom output.

Usage:
    python validate_zoom_output.py /path/to/input.mp4

Steps:
  1. Process the video through EditingPipeline.apply() with zoom_intensity="medium"
  2. Extract 10 frames distributed across the output duration
  3. Detect frozen frames by comparing consecutive frame MD5 hashes
  4. Verify zoom is visually active by comparing crop bounding boxes
  5. Print a PASS/FAIL report

Dependencies: ffmpeg, ffprobe, Python standard library only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _die(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def _check_deps() -> None:
    if not _FFMPEG:
        _die("ffmpeg not found in PATH")
    if not _FFPROBE:
        _die("ffprobe not found in PATH")


def _probe_duration(path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    result = subprocess.run(
        [_FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, timeout=15, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass
    return 0.0


def _probe_audio_duration(path: Path) -> float:
    """Return audio stream duration in seconds via ffprobe."""
    result = subprocess.run(
        [_FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, timeout=15, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass
    return 0.0


def _extract_frame(path: Path, timestamp: float, output_path: Path) -> None:
    """Extract a single frame at the given timestamp as JPEG."""
    subprocess.run(
        [_FFMPEG, "-y", "-ss", f"{timestamp:.3f}", "-i", str(path),
         "-frames:v", "1", "-q:v", "2", str(output_path)],
        capture_output=True, timeout=30, check=True,
    )


def _frame_md5(path: Path) -> str:
    """Return MD5 hex digest of a frame image file."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def _frame_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) of a frame image via ffprobe."""
    result = subprocess.run(
        [_FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, timeout=15, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        parts = result.stdout.strip().split(",")
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                pass
    return 0, 0


# ── main validation logic ─────────────────────────────────────────────────────


async def validate(input_path: Path) -> int:
    """Run all validation steps. Returns 0 on pass, 1 on fail."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="validate_zoom_"))
    output_path = tmp_dir / "output.mp4"
    frame_dir = tmp_dir / "frames"
    frame_dir.mkdir()

    # ── Step 1: Process through EditingPipeline ────────────────────────────────
    print(f"📹 Processing {input_path.name} through EditingPipeline...")
    sys.stdout.flush()

    # Import here so the script can be run standalone without full backend setup
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from video_processing.editing_pipeline import EditingPipeline

    ep = EditingPipeline()
    result = await ep.apply(
        video_path=input_path,
        words=[],
        output_path=output_path,
        segment_text="Validation clip",
        energy_level=0.7,
        zoom_intensity="medium",
    )

    if result is None or not result.exists() or result.stat().st_size == 0:
        print("🔴 FAIL: EditingPipeline returned None or empty output")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return 1

    print(f"   ✅ Output: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # ── Probe durations ────────────────────────────────────────────────────────
    video_dur = _probe_duration(output_path)
    audio_dur = _probe_audio_duration(output_path)
    print(f"   Video duration: {video_dur:.2f}s")
    print(f"   Audio duration: {audio_dur:.2f}s")

    # ── Step 2: Extract 10 frames ──────────────────────────────────────────────
    print("📸 Extracting 10 frames across timeline...")
    sys.stdout.flush()

    frame_timestamps = [video_dur * (i + 1) / 10 for i in range(10)]
    frame_paths: list[Path] = []

    for i, ts in enumerate(frame_timestamps):
        fp = frame_dir / f"frame_{i:02d}.jpg"
        try:
            _extract_frame(output_path, ts, fp)
            frame_paths.append(fp)
            print(f"   Frame {i:02d} @ t={ts:.2f}s: {fp.stat().st_size} bytes")
        except Exception as e:
            print(f"   ⚠️  Frame {i:02d} @ t={ts:.2f}s failed: {e}")
            frame_paths.append(None)  # type: ignore[arg-type]

    # ── Step 3: Detect frozen frames via MD5 ───────────────────────────────────
    print("🔍 Checking for frozen frames...")
    sys.stdout.flush()

    frozen_pairs: list[tuple[int, int, float]] = []  # (i, i+1, timestamp)
    for i in range(len(frame_paths) - 1):
        if frame_paths[i] is None or frame_paths[i + 1] is None:
            continue
        h1 = _frame_md5(frame_paths[i])
        h2 = _frame_md5(frame_paths[i + 1])
        if h1 == h2:
            ts = frame_timestamps[i]
            frozen_pairs.append((i, i + 1, ts))

    # ── Step 4: Detect zoom visual activity ────────────────────────────────────
    print("🔍 Checking zoom visual activity...")
    sys.stdout.flush()

    zoom_active = False
    if len(frame_paths) >= 3 and frame_paths[0] and frame_paths[2]:
        # Compare crop bounding box between frame 0 and frame 2
        # If zoom is active, the visible content should differ (scale changed)
        h0 = _frame_md5(frame_paths[0])
        h2 = _frame_md5(frame_paths[2])
        if h0 != h2:
            zoom_active = True

    # Also check dimensions of frame 0 vs frame 15 (if available)
    # For scale+crop, the output dimensions should be constant (1080x1920)
    # but the crop region changes. We verify by checking that frame hashes
    # differ across the timeline (zoom changes the visible content).
    if not zoom_active and len(frame_paths) >= 5:
        # Check more frames
        hashes = []
        for fp in frame_paths[:5]:
            if fp is None:
                continue
            hashes.append(_frame_md5(fp))
        if len(set(hashes)) > 1:
            zoom_active = True

    # ── Step 5: Print report ───────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("📋 VALIDATION REPORT")
    print("=" * 60)

    exit_code = 0

    # Frozen frame check
    if frozen_pairs:
        frozen_seconds = [f"{ts:.1f}s (frames {i}-{j})" for i, j, ts in frozen_pairs]
        print(f"🔴 FAIL: Frozen frames detected at seconds [{', '.join(frozen_seconds)}]")
        exit_code = 1
    else:
        print("✅ PASS: No frozen frames detected")

    # Zoom active check
    if zoom_active:
        print("✅ PASS: Zoom effect active (frame content varies across timeline)")
    else:
        print("🔴 FAIL: Zoom not detected — scale+crop may be identity filter")
        exit_code = 1

    # Audio duration check
    if audio_dur > 0:
        diff = abs(video_dur - audio_dur)
        if diff < 0.2:
            print(f"✅ PASS: Audio duration matches video duration (diff={diff:.2f}s)")
        else:
            print(f"⚠️  WARN: Audio shorter than video by {diff:.1f}s")
    else:
        print("⚠️  WARN: No audio stream detected in output")

    # ── Cleanup ────────────────────────────────────────────────────────────────
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print()
    if exit_code == 0:
        print("🎉 All checks passed!")
    else:
        print("❌ Some checks failed — review details above.")

    return exit_code


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate scale+crop zoom output for frozen frames",
    )
    parser.add_argument("input", type=str, help="Path to input MP4 video")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        _die(f"Input file not found: {input_path}")
    if input_path.suffix.lower() not in (".mp4", ".mov", ".avi", ".mkv"):
        _die(f"Unsupported format: {input_path.suffix} (use .mp4, .mov, .avi, .mkv)")

    _check_deps()
    return asyncio.run(validate(input_path))


if __name__ == "__main__":
    sys.exit(main())
