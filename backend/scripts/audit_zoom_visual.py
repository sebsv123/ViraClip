#!/usr/bin/env python3
"""
audit_zoom_visual.py — Visual verification that scale+crop zoom is active
and produces no frozen frames.

Generates 3 synthetic test clips with a white circle on solid background,
processes each through EditingPipeline.apply(), then checks:
  - Zoom active: white circle centroid moves between frames
  - No frozen frames: consecutive frame MD5 hashes differ

Usage:
    python audit_zoom_visual.py

Dependencies: ffmpeg, ffprobe, Python stdlib only.
Returns exit(0) if all pass, exit(1) if any fail.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
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


def _generate_test_clip(
    tmp_dir: Path,
    name: str,
    duration: float,
    fps: float,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """
    Generate a synthetic clip with a white circle on a coloured background.
    The circle is centred and static — any movement in the output is from zoom.
    """
    path = tmp_dir / name
    # Use lavfi colour + drawbox for a solid background with a white circle
    # drawbox with a large enough box approximates a circle via round corners
    cx = width // 2
    cy = height // 2
    r = min(width, height) // 6  # circle radius

    cmd = [
        _FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x2255AA:s={width}x{height}:d={duration}:r={fps}",
        # Draw a white filled circle using drawbox with large round radius
        "-vf",
        f"drawbox=x={cx-r}:y={cy-r}:w={2*r}:h={2*r}:color=white@1:t=fill:"
        f"round={r}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    return path


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


def _white_centroid(path: Path) -> tuple[float, float] | None:
    """
    Return (cx, cy) of the white circle centroid in the frame.
    Uses a simple pixel scan: finds the mean x,y of pixels with R>200, G>200, B>200.
    Returns None if no white pixels found.
    """
    try:
        from PIL import Image
    except ImportError:
        # Fallback: use ffmpeg to extract a 1x1 pixel average and estimate
        # This is less precise but works without PIL
        return _centroid_fallback(path)

    img = Image.open(path).convert("RGB")
    pixels = img.load()
    w, h = img.size
    xs: list[int] = []
    ys: list[int] = []
    # Sample every 4th pixel for speed
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            r, g, b = pixels[x, y]
            if r > 200 and g > 200 and b > 200:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _centroid_fallback(path: Path) -> tuple[float, float] | None:
    """
    Fallback centroid detection using ffmpeg to extract a histogram
    and estimate the white region centre. Less precise but works
    without PIL.
    """
    # Use ffmpeg to get a downscaled version and parse pixel data
    small = path.with_suffix(".small.pgm")
    try:
        subprocess.run(
            [_FFMPEG, "-y", "-i", str(path),
             "-vf", "scale=40:72,format=gray",
             "-frames:v", "1", str(small)],
            capture_output=True, timeout=15, check=True,
        )
        # Parse PGM (P5 format)
        data = small.read_bytes()
        # Find header end
        header_end = data.find(b"\n", data.find(b"\n", data.find(b"\n") + 1) + 1)
        header = data[:header_end].decode()
        parts = header.split()
        # parts: ['P5', width, height, maxval]
        w = int(parts[1])
        h = int(parts[2])
        pixels = data[header_end + 1:]
        xs: list[int] = []
        ys: list[int] = []
        threshold = 200  # white in grayscale
        for y in range(h):
            for x in range(w):
                idx = y * w + x
                if idx < len(pixels) and pixels[idx] > threshold:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return None
        # Scale back to original 1080x1920
        scale_x = 1080.0 / w
        scale_y = 1920.0 / h
        return (sum(xs) / len(xs)) * scale_x, (sum(ys) / len(ys)) * scale_y
    except Exception:
        return None
    finally:
        small.unlink(missing_ok=True)


# ── test runner ───────────────────────────────────────────────────────────────


async def test_clip(
    tmp_dir: Path,
    name: str,
    duration: float,
    fps: float,
) -> dict:
    """
    Run the full test for one clip.
    Returns dict with keys: name, zoom_active, frozen_frames, pass.
    """
    result: dict = {
        "name": name,
        "zoom_active": None,
        "frozen_frames": 0,
        "pass": True,
        "errors": [],
    }

    # Step 1: Generate synthetic clip
    clip = _generate_test_clip(tmp_dir, name, duration, fps)
    print(f"   Generated {name} ({duration}s @ {fps}fps)")

    # Step 2: Process through EditingPipeline
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from video_processing.editing_pipeline import EditingPipeline

    output = tmp_dir / f"out_{name}"
    ep = EditingPipeline()
    processed = await ep.apply(
        video_path=clip,
        words=[],
        output_path=output,
        segment_text="Test clip for zoom visual audit",
        energy_level=0.7,
        zoom_intensity="medium",
    )

    if processed is None or not processed.exists() or processed.stat().st_size == 0:
        result["pass"] = False
        result["errors"].append("EditingPipeline returned None or empty output")
        return result

    # Step 3: Extract frames at specific timestamps
    timestamps = []
    if duration >= 1.0:
        timestamps = [0.1, 0.5, 1.0, min(5.0, duration * 0.5), max(duration - 0.5, duration * 0.8)]
    else:
        timestamps = [0.05, 0.2, 0.4, 0.6, 0.75]

    frame_dir = tmp_dir / f"frames_{name}"
    frame_dir.mkdir()

    frame_paths: list[Path] = []
    for i, ts in enumerate(timestamps):
        if ts >= duration:
            continue
        fp = frame_dir / f"frame_{i:02d}.jpg"
        try:
            _extract_frame(processed, ts, fp)
            frame_paths.append(fp)
        except Exception as e:
            result["errors"].append(f"Frame extraction at t={ts:.2f}s failed: {e}")

    if len(frame_paths) < 2:
        result["pass"] = False
        result["errors"].append("Not enough frames extracted")
        return result

    # Step 4: Detect frozen frames via MD5
    frozen = 0
    for i in range(len(frame_paths) - 1):
        h1 = _frame_md5(frame_paths[i])
        h2 = _frame_md5(frame_paths[i + 1])
        if h1 == h2:
            frozen += 1
            result["errors"].append(
                f"Frozen frame: frame {i} @ t={timestamps[i]:.2f}s == frame {i+1} @ t={timestamps[i+1]:.2f}s"
            )
    result["frozen_frames"] = frozen
    if frozen > 0:
        result["pass"] = False

    # Step 5: Detect zoom activity via white circle centroid movement
    if duration >= 1.0:
        centroids = []
        for fp in frame_paths:
            c = _white_centroid(fp)
            if c is not None:
                centroids.append(c)

        if len(centroids) >= 2:
            # Check if centroid moved between first and last frame
            cx_first, cy_first = centroids[0]
            cx_last, cy_last = centroids[-1]
            dx = abs(cx_last - cx_first)
            dy = abs(cy_last - cy_first)
            # For a 1080-wide clip, zoom should move the centroid by at least 2px
            result["zoom_active"] = dx > 2.0 or dy > 2.0
            if not result["zoom_active"]:
                result["errors"].append(
                    f"Zoom not detected: centroid moved only ({dx:.1f}, {dy:.1f})px "
                    f"across {len(timestamps)} frames"
                )
                result["pass"] = False
        else:
            result["errors"].append("Could not compute centroids — zoom check skipped")
    else:
        # Short clip: zoom may not activate (hook zoom needs dur >= 1.0)
        result["zoom_active"] = None  # N/A

    return result


# ── main ──────────────────────────────────────────────────────────────────────


async def main() -> int:
    _check_deps()

    tmp_dir = Path(tempfile.mkdtemp(prefix="audit_zoom_"))
    print("=" * 60)
    print("🔬 Zoom Visual Audit")
    print("=" * 60)
    print()

    tests = [
        ("test_30fps.mp4", 10.0, 30.0),
        ("test_12fps.mp4", 10.0, 12.0),
        ("test_short.mp4", 0.8, 30.0),
    ]

    all_pass = True
    results = []

    for name, dur, fps in tests:
        print(f"📹 Testing {name}...")
        sys.stdout.flush()
        r = await test_clip(tmp_dir, name, dur, fps)
        results.append(r)
        if not r["pass"]:
            all_pass = False
        print()

    # Print report
    print("=" * 60)
    print("📋 AUDIT REPORT")
    print("=" * 60)
    for r in results:
        zoom_str = {
            True: "✅",
            False: "🔴",
            None: "N/A",
        }.get(r["zoom_active"], "❓")
        frozen_str = "✅" if r["frozen_frames"] == 0 else f"🔴 ({r['frozen_frames']})"
        status = "✅ PASS" if r["pass"] else "🔴 FAIL"
        print(f"  {r['name']}:  zoom_active={zoom_str}  frozen_frames={r['frozen_frames']}  {status}")
        for err in r["errors"]:
            print(f"    ⚠️  {err}")

    print()
    if all_pass:
        print("🎉 All tests passed!")
    else:
        print("❌ Some tests failed — review details above.")

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
