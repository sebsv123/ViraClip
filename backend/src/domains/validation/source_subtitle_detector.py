"""
Source Subtitle Detector — Lightweight preflight check for burned-in subtitles.

Detects whether the source video already has burned-in (hardsubbed) text in the
bottom band of the frame — the same zone where ViraClip normally burns captions.

Strategy
--------
Uses FFmpeg to sample N frames at regular intervals, crops to the bottom 25%
of the frame (the caption zone), then applies lightweight OpenCV heuristics to
detect text-like regions:

  1. Convert to grayscale
  2. Apply adaptive threshold to isolate high-contrast regions
  3. Find contours and filter by aspect ratio / area (text-like rectangles)
  4. Compute horizontal edge density (text produces dense horizontal edges)
  5. Score each frame and aggregate across all samples

Thresholds
----------
  subtitle_presence_ratio < 0.05  → ignore (no significant burned-in text)
  0.05 <= ratio < 0.20            → warn (move captions higher)
  ratio >= 0.20                   → action (skip captions or move significantly higher)

Future OCR
----------
This detector uses heuristic-only analysis. For production-grade detection,
integrate an OCR engine (e.g., Tesseract, EasyOCR, or PaddleOCR) to verify
text content and distinguish subtitles from UI elements. The current approach
is intentionally lightweight — no heavy models, no GPU required.

Usage
-----
    result = await detect_source_subtitles(video_path)
    if result.subtitle_presence_ratio >= 0.20:
        logger.warning("Burned-in subtitles detected — adjusting caption strategy")
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# How many frames to sample (spread evenly across the video)
DEFAULT_NUM_SAMPLES = 15

# Bottom band to analyze (fraction of height from bottom)
BOTTOM_BAND_FRACTION = 0.25

# Thresholds for text detection
TEXT_MIN_AREA = 50          # minimum contour area (px²) to be considered text
TEXT_MAX_AREA_RATIO = 0.3   # max contour area as fraction of frame (avoid full-frame artifacts)
TEXT_MIN_ASPECT = 1.5       # text regions tend to be wider than tall
TEXT_MAX_ASPECT = 15.0      # very wide = likely a subtitle bar
EDGE_DENSITY_THRESHOLD = 0.08  # fraction of edge pixels in the band

# Detection thresholds
SUBTITLE_PRESENCE_RATIO_WARN = 0.05   # >= 5% frames → warn
SUBTITLE_PRESENCE_RATIO_ACTION = 0.20 # >= 20% frames → take action

# Caption offset adjustments (pixels on 1920-tall canvas)
CAPTION_OFFSET_WARN = 120    # move captions 120px higher when warned
CAPTION_OFFSET_ACTION = 240  # move captions 240px higher when action required


@dataclass
class SubtitleDetectionResult:
    """Result of the source subtitle detection analysis."""

    subtitle_presence_ratio: float = 0.0
    """Fraction of sampled frames that appear to contain burned-in text (0.0–1.0)."""

    subtitle_band_bounds: Tuple[int, int] = (0, 0)
    """(y_top, y_bottom) bounding box of the detected text band in the frame."""

    frames_analyzed: int = 0
    """Number of frames sampled from the video."""

    frames_with_text: int = 0
    """Number of frames where text-like regions were detected."""

    avg_confidence: float = 0.0
    """Average detection confidence across all frames (0.0–1.0)."""

    caption_strategy: str = "normal"
    """Recommended caption strategy: 'normal', 'offset_up', or 'skip_captions'."""

    caption_offset_y: int = 0
    """Suggested vertical offset (px) to shift captions upward."""

    def to_dict(self) -> dict:
        return {
            "subtitle_presence_ratio": self.subtitle_presence_ratio,
            "subtitle_band_bounds": list(self.subtitle_band_bounds),
            "frames_analyzed": self.frames_analyzed,
            "frames_with_text": self.frames_with_text,
            "avg_confidence": self.avg_confidence,
            "caption_strategy": self.caption_strategy,
            "caption_offset_y": self.caption_offset_y,
        }


# ── FFmpeg frame extraction ───────────────────────────────────────────────────

async def _probe_video_info(video_path: Path) -> Tuple[float, int, int]:
    """Get video duration (seconds), width, height using ffprobe."""
    import json as _json
    import subprocess as _sp

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", str(video_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        info = _json.loads(stdout)

        duration = 0.0
        width, height = 0, 0
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                duration = float(stream.get("duration", 0) or 0)
                width = int(stream.get("width", 0) or 0)
                height = int(stream.get("height", 0) or 0)
                break

        # Fallback: get duration from format
        if not duration:
            fmt = info.get("format", {})
            duration = float(fmt.get("duration", 0) or 0)

        return duration, width, height
    except Exception as e:
        logger.warning(f"[subtitle_detector] ffprobe failed: {e}")
        return 0.0, 0, 0


async def _extract_frames(
    video_path: Path,
    output_dir: Path,
    num_samples: int = DEFAULT_NUM_SAMPLES,
) -> List[Path]:
    """
    Extract evenly-spaced frames from the video using FFmpeg.

    Returns list of extracted frame file paths.
    """
    duration, width, height = await _probe_video_info(video_path)
    if duration <= 0 or width <= 0 or height <= 0:
        logger.warning(
            f"[subtitle_detector] Could not determine video dimensions "
            f"(dur={duration}, w={width}, h={height})"
        )
        return []

    # Sample interval: ensure we get num_samples evenly spaced frames
    # For very short videos (< 5s), sample at least 3 frames
    actual_samples = max(3, min(num_samples, int(duration / 0.5)))
    interval = max(0.5, duration / actual_samples)

    frame_paths: List[Path] = []
    tasks = []

    for i in range(actual_samples):
        timestamp = i * interval
        if timestamp >= duration:
            break
        output_path = output_dir / f"frame_{i:04d}.png"
        frame_paths.append(output_path)

        tasks.append(
            _extract_single_frame(video_path, timestamp, output_path)
        )

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = [
        p for p, r in zip(frame_paths, results)
        if not isinstance(r, Exception) and p.exists() and p.stat().st_size > 0
    ]

    logger.info(
        f"[subtitle_detector] Extracted {len(successful)}/{len(tasks)} frames "
        f"(interval={interval:.1f}s, duration={duration:.1f}s)"
    )
    return successful


async def _extract_single_frame(
    video_path: Path, timestamp: float, output_path: Path
) -> None:
    """Extract a single frame at the given timestamp."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg frame extraction failed at {timestamp:.1f}s: "
            f"{stderr.decode()[-300:]}"
        )


# ── OpenCV-based text detection ───────────────────────────────────────────────

def _detect_text_in_band(frame_path: Path, band_fraction: float = BOTTOM_BAND_FRACTION) -> Tuple[bool, float, Tuple[int, int]]:
    """
    Analyze a single frame for text-like regions in the bottom band.

    Returns:
        (has_text, confidence, (band_top, band_bottom))
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning(
            "[subtitle_detector] OpenCV (cv2) not available — "
            "cannot perform text detection. Install opencv-python."
        )
        return False, 0.0, (0, 0)

    try:
        img = cv2.imread(str(frame_path))
        if img is None:
            return False, 0.0, (0, 0)

        height, width = img.shape[:2]

        # Crop to bottom band
        band_top = int(height * (1.0 - band_fraction))
        band = img[band_top:, :]

        # Convert to grayscale
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)

        # Apply adaptive threshold to isolate high-contrast regions
        # (text is high-contrast against background)
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 15, 4
        )

        # Morphological close to connect nearby text components
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        # Find contours
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Filter contours by area and aspect ratio (text-like regions)
        band_area = band.shape[0] * band.shape[1]
        text_contours = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < TEXT_MIN_AREA:
                continue
            if area > band_area * TEXT_MAX_AREA_RATIO:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / max(h, 1)
            if aspect < TEXT_MIN_ASPECT or aspect > TEXT_MAX_ASPECT:
                continue

            text_contours.append(cnt)

        # Compute horizontal edge density (text produces dense horizontal edges)
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_x = np.abs(sobel_x)
        _, edge_mask = cv2.threshold(sobel_x, 50, 255, cv2.THRESH_BINARY)
        edge_density = np.sum(edge_mask > 0) / (band.shape[0] * band.shape[1])

        # Decision: text present if we have enough text-like contours
        # OR high horizontal edge density
        has_text_contours = len(text_contours) >= 3
        has_edge_density = edge_density > EDGE_DENSITY_THRESHOLD

        # Confidence based on both signals
        contour_confidence = min(1.0, len(text_contours) / 15.0)
        edge_confidence = min(1.0, edge_density / 0.3)
        confidence = max(contour_confidence, edge_confidence)

        has_text = has_text_contours or has_edge_density

        # Compute bounding box of detected text band
        if text_contours:
            all_points = np.vstack([cnt.reshape(-1, 2) for cnt in text_contours])
            y_min = int(np.min(all_points[:, 1])) + band_top
            y_max = int(np.max(all_points[:, 1])) + band_top
        else:
            y_min = band_top
            y_max = height

        return has_text, confidence, (y_min, y_max)

    except Exception as e:
        logger.debug(f"[subtitle_detector] Frame analysis error: {e}")
        return False, 0.0, (0, 0)


# ── Main detection function ───────────────────────────────────────────────────

async def detect_source_subtitles(
    video_path: Path,
    num_samples: int = DEFAULT_NUM_SAMPLES,
) -> SubtitleDetectionResult:
    """
    Detect burned-in subtitles in the source video.

    Samples frames evenly across the video, analyzes the bottom band for
    text-like patterns, and returns a detection result with recommended action.

    Args:
        video_path: Path to the source video file.
        num_samples: Number of frames to sample (default: 15).

    Returns:
        SubtitleDetectionResult with detection metrics and recommended strategy.
    """
    if not video_path.exists():
        logger.warning(f"[subtitle_detector] Video not found: {video_path}")
        return SubtitleDetectionResult()

    # Create temp directory for frame extraction
    temp_dir = Path(tempfile.mkdtemp(prefix="subtitle_detect_"))
    try:
        # Step 1: Extract frames
        frame_paths = await _extract_frames(video_path, temp_dir, num_samples)

        if not frame_paths:
            logger.warning("[subtitle_detector] No frames extracted — skipping detection")
            return SubtitleDetectionResult()

        # Step 2: Analyze each frame
        frames_with_text = 0
        total_confidence = 0.0
        band_bounds_list: List[Tuple[int, int]] = []

        for frame_path in frame_paths:
            has_text, confidence, band_bounds = _detect_text_in_band(frame_path)
            if has_text:
                frames_with_text += 1
                total_confidence += confidence
                band_bounds_list.append(band_bounds)

        # Step 3: Aggregate results
        frames_analyzed = len(frame_paths)
        presence_ratio = frames_with_text / max(frames_analyzed, 1)
        avg_confidence = total_confidence / max(frames_with_text, 1)

        # Compute average band bounds
        if band_bounds_list:
            avg_y_top = int(sum(b[0] for b in band_bounds_list) / len(band_bounds_list))
            avg_y_bottom = int(sum(b[1] for b in band_bounds_list) / len(band_bounds_list))
            subtitle_band_bounds = (avg_y_top, avg_y_bottom)
        else:
            subtitle_band_bounds = (0, 0)

        # Step 4: Determine strategy
        if presence_ratio >= SUBTITLE_PRESENCE_RATIO_ACTION:
            caption_strategy = "skip_captions"
            caption_offset_y = CAPTION_OFFSET_ACTION
            logger.warning(
                f"[subtitle_detector] ⚠️ Strong burned-in subtitle signal: "
                f"{frames_with_text}/{frames_analyzed} frames ({presence_ratio:.1%}) — "
                f"recommending caption skip"
            )
        elif presence_ratio >= SUBTITLE_PRESENCE_RATIO_WARN:
            caption_strategy = "offset_up"
            caption_offset_y = CAPTION_OFFSET_WARN
            logger.info(
                f"[subtitle_detector] ⚠️ Possible burned-in subtitles: "
                f"{frames_with_text}/{frames_analyzed} frames ({presence_ratio:.1%}) — "
                f"moving captions up by {CAPTION_OFFSET_WARN}px"
            )
        else:
            caption_strategy = "normal"
            caption_offset_y = 0
            logger.info(
                f"[subtitle_detector] ✅ No significant burned-in subtitles: "
                f"{frames_with_text}/{frames_analyzed} frames ({presence_ratio:.1%})"
            )

        return SubtitleDetectionResult(
            subtitle_presence_ratio=round(presence_ratio, 4),
            subtitle_band_bounds=subtitle_band_bounds,
            frames_analyzed=frames_analyzed,
            frames_with_text=frames_with_text,
            avg_confidence=round(avg_confidence, 4),
            caption_strategy=caption_strategy,
            caption_offset_y=caption_offset_y,
        )

    except Exception as e:
        logger.error(f"[subtitle_detector] Detection failed: {e}", exc_info=True)
        return SubtitleDetectionResult()
    finally:
        # Cleanup temp frames
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


# ── Convenience wrapper ───────────────────────────────────────────────────────

async def check_source_subtitles_and_adjust(
    video_path: Path,
    add_subtitles: bool,
    target_platform: str = "tiktok",
) -> dict:
    """
    Run source subtitle detection and return adjusted caption parameters.

    This is the main entry point for pipeline integration.

    Args:
        video_path: Path to the source video.
        add_subtitles: Whether the pipeline intends to add captions.
        target_platform: Target platform for caption positioning.

    Returns:
        Dict with:
            - source_subtitle_detection: SubtitleDetectionResult.to_dict()
            - add_subtitles: Possibly modified (False if burned-in subs detected)
            - caption_offset_y: Vertical offset for captions (px)
            - caption_strategy: 'normal', 'offset_up', or 'skip_captions'
    """
    result = await detect_source_subtitles(video_path)

    adjusted_add_subtitles = add_subtitles
    caption_offset_y = 0

    if result.caption_strategy == "skip_captions" and add_subtitles:
        logger.warning(
            "[preflight] Source has significant burned-in subtitles "
            f"({result.subtitle_presence_ratio:.1%} frames). "
            "Disabling ViraClip captions to avoid double-subtitle clutter."
        )
        adjusted_add_subtitles = False
        caption_offset_y = result.caption_offset_y
    elif result.caption_strategy == "offset_up" and add_subtitles:
        logger.info(
            "[preflight] Source has mild burned-in subtitles "
            f"({result.subtitle_presence_ratio:.1%} frames). "
            f"Shifting captions up by {result.caption_offset_y}px."
        )
        caption_offset_y = result.caption_offset_y

    return {
        "source_subtitle_detection": result.to_dict(),
        "add_subtitles": adjusted_add_subtitles,
        "caption_offset_y": caption_offset_y,
        "caption_strategy": result.caption_strategy,
    }
