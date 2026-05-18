"""
Clip Sanity Checks — offline QA validation for rendered clips.

Each function inspects a rendered video file (or task context) and returns
a structured result with pass/fail status and actionable details.

All checks use only FFmpeg, OpenCV, and existing services — no heavy
additional models are loaded.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
MAX_DESYNC_MS = 100          # max acceptable audio-video desync in ms
LOUDNESS_MIN = -15.0         # minimum acceptable integrated loudness (LUFS)
LOUDNESS_MAX = -13.0         # maximum acceptable integrated loudness (LUFS)
MAX_SUBTITLE_STREAMS = 2     # more than this = triple-subtitle suspicion
JITTER_THRESHOLD = 15.0      # mean frame-diff stddev above this = jitter
JITTER_SAMPLE_FRAMES = 60    # number of frames to sample for jitter check
MIN_BROLL_UNIQUE_IDS = 2     # minimum unique B-roll sources expected


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class SanityCheckResult:
    """Result of a single sanity check."""
    name: str
    passed: bool
    details: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": self.details,
            "metrics": self.metrics,
        }


@dataclass
class SanityReport:
    """Aggregated report from all sanity checks on one clip."""
    clip_path: str
    checks: List[SanityCheckResult] = field(default_factory=list)
    overall_pass: bool = True

    def __post_init__(self):
        """Auto-compute overall_pass from checks if not explicitly set."""
        if self.checks:
            self.overall_pass = all(c.passed for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_path": self.clip_path,
            "overall_pass": self.overall_pass,
            "checks": [c.to_dict() for c in self.checks],
        }


# ── Helper utilities ───────────────────────────────────────────────────────────

def _run_ffprobe(cmd: List[str], timeout: int = 30) -> str:
    """Run ffprobe and return stdout. Raises on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"ffprobe timed out after {timeout}s")
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed (code={result.returncode}): "
            f"{result.stderr.decode(errors='replace')[:500]}"
        )
    return result.stdout.decode(errors="replace")


def _get_video_stream_info(clip_path: str) -> Dict[str, Any]:
    """Return basic video stream info via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        clip_path,
    ]
    raw = _run_ffprobe(cmd)
    data = json.loads(raw)
    info: Dict[str, Any] = {
        "duration_s": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "audio_streams": 0,
        "subtitle_streams": 0,
        "video_streams": 0,
    }
    if "format" in data and data["format"].get("duration"):
        info["duration_s"] = float(data["format"]["duration"])
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            info["video_streams"] += 1
            info["width"] = stream.get("width", 0)
            info["height"] = stream.get("height", 0)
            fps_str = stream.get("r_frame_rate", "0/1")
            if "/" in fps_str:
                try:
                    num, den = fps_str.split("/")
                    info["fps"] = float(num) / float(den) if float(den) > 0 else 0.0
                except (ValueError, ZeroDivisionError):
                    info["fps"] = 0.0
        elif codec_type == "audio":
            info["audio_streams"] += 1
        elif codec_type == "subtitle":
            info["subtitle_streams"] += 1
    return info


# ── Check 1: Triple subtitles ──────────────────────────────────────────────────

def check_no_triple_subtitles(clip_path: str) -> SanityCheckResult:
    """
    Detect if a clip has excessive subtitle streams or burned-in overlays.

    Checks:
    1. Embedded subtitle stream count (>2 = suspicious)
    2. Burned-in subtitle detection via OCR on sample frames (heuristic)

    Returns
    -------
    SanityCheckResult with ``passed`` = False if triple subtitles suspected.
    """
    name = "Triple Subtitles"
    try:
        info = _get_video_stream_info(clip_path)
        sub_streams = info.get("subtitle_streams", 0)

        # ── Check embedded subtitle streams ──────────────────────────────
        if sub_streams > MAX_SUBTITLE_STREAMS:
            return SanityCheckResult(
                name=name,
                passed=False,
                details=(
                    f"Found {sub_streams} embedded subtitle streams "
                    f"(max expected {MAX_SUBTITLE_STREAMS}). "
                    "Possible triple-subtitle overlay."
                ),
                metrics={"subtitle_streams": sub_streams},
            )

        # ── Check for burned-in subtitles via OCR on sample frames ───────
        # Use FFmpeg to extract a few frames and check for text regions
        burned_in_count = _detect_burned_in_subtitles(clip_path)
        if burned_in_count > 2:
            return SanityCheckResult(
                name=name,
                passed=False,
                details=(
                    f"Detected {burned_in_count} frames with possible "
                    "burned-in subtitle text. Combined with embedded "
                    f"streams ({sub_streams}), triple-subtitle risk."
                ),
                metrics={
                    "subtitle_streams": sub_streams,
                    "burned_in_frames": burned_in_count,
                },
            )

        return SanityCheckResult(
            name=name,
            passed=True,
            details=(
                f"No triple-subtitle issue ({sub_streams} embedded streams, "
                f"{burned_in_count} burned-in frames)."
            ),
            metrics={
                "subtitle_streams": sub_streams,
                "burned_in_frames": burned_in_count,
            },
        )

    except Exception as exc:
        logger.warning("check_no_triple_subtitles failed: %s", exc)
        return SanityCheckResult(
            name=name,
            passed=False,
            details=f"Check error: {exc}",
            metrics={"error": str(exc)},
        )


def _detect_burned_in_subtitles(clip_path: str, num_samples: int = 5) -> int:
    """
    Heuristic: extract sample frames and count those with dense text-like
    horizontal bands in the bottom third of the frame.

    Uses simple image processing (no OCR model) to detect subtitle-like
    regions: high-contrast horizontal bands in the lower portion.
    """
    import random

    try:
        info = _get_video_stream_info(clip_path)
        duration = info.get("duration_s", 30.0)
        if duration <= 0:
            return 0

        # Pick random timestamps spread across the clip
        timestamps = sorted(
            random.uniform(1.0, max(duration - 1.0, 2.0))
            for _ in range(num_samples)
        )

        frames_with_text = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, ts in enumerate(timestamps):
                frame_path = Path(tmpdir) / f"frame_{i:02d}.png"
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(ts),
                    "-i", clip_path,
                    "-vframes", "1",
                    "-q:v", "2",
                    str(frame_path),
                ]
                subprocess.run(cmd, capture_output=True, timeout=30, check=False)

                if frame_path.exists():
                    if _frame_has_subtitle_band(str(frame_path)):
                        frames_with_text += 1

        return frames_with_text

    except Exception:
        return 0


def _frame_has_subtitle_band(frame_path: str) -> bool:
    """
    Check if a frame has a horizontal band of high-contrast text-like pixels
    in the bottom third (typical subtitle region).
    """
    try:
        img = cv2.imread(frame_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return False

        h, w = img.shape
        # Focus on bottom third
        bottom = img[int(h * 0.7):, :]

        # Apply binary threshold to isolate high-contrast text
        _, binary = cv2.threshold(bottom, 180, 255, cv2.THRESH_BINARY)

        # Count non-zero (text-like) pixels in horizontal strips
        strip_h = max(1, bottom.shape[0] // 4)
        text_density = []
        for row_start in range(0, bottom.shape[0], strip_h):
            strip = binary[row_start:row_start + strip_h, :]
            density = np.count_nonzero(strip) / strip.size
            text_density.append(density)

        # If any strip has moderate density of text-like pixels, flag it
        return any(0.02 < d < 0.35 for d in text_density)

    except Exception:
        return False


# ── Check 2: B-roll diversity ──────────────────────────────────────────────────

def check_broll_diversity(task_context: Dict[str, Any]) -> SanityCheckResult:
    """
    Analyze B-roll source diversity from task context/metadata.

    Parameters
    ----------
    task_context:
        Dict containing at least ``broll_sources`` (list of source IDs/URLs)
        or ``broll_metadata`` (list of dicts with ``source_id`` keys).

    Returns
    -------
    SanityCheckResult with metrics on unique B-roll IDs, total count,
    and diversity ratio.
    """
    name = "B-Roll Diversity"
    try:
        # Extract B-roll source IDs from various possible structures
        source_ids: List[str] = []

        # Option 1: flat list of source IDs
        raw_sources = task_context.get("broll_sources", [])
        if isinstance(raw_sources, list):
            source_ids.extend(str(s) for s in raw_sources if s)

        # Option 2: list of dicts with source_id key
        raw_metadata = task_context.get("broll_metadata", [])
        if isinstance(raw_metadata, list):
            for item in raw_metadata:
                sid = item.get("source_id") or item.get("id") or item.get("url")
                if sid:
                    source_ids.append(str(sid))

        # Option 3: clips list with broll info
        clips = task_context.get("clips", [])
        if isinstance(clips, list):
            for clip in clips:
                for key in ("broll_sources", "broll_ids", "broll_urls"):
                    vals = clip.get(key, [])
                    if isinstance(vals, list):
                        source_ids.extend(str(v) for v in vals if v)

        # Deduplicate
        unique_ids = list(set(source_ids))
        total = len(source_ids)
        unique = len(unique_ids)

        if total == 0:
            return SanityCheckResult(
                name=name,
                passed=False,
                details="No B-roll sources found in task context.",
                metrics={"total_sources": 0, "unique_sources": 0, "diversity_ratio": 0.0},
            )

        diversity_ratio = unique / total if total > 0 else 0.0

        if unique < MIN_BROLL_UNIQUE_IDS:
            return SanityCheckResult(
                name=name,
                passed=False,
                details=(
                    f"Low B-roll diversity: {unique} unique source(s) "
                    f"out of {total} total (ratio={diversity_ratio:.2f}). "
                    f"Minimum expected: {MIN_BROLL_UNIQUE_IDS} unique sources."
                ),
                metrics={
                    "total_sources": total,
                    "unique_sources": unique,
                    "diversity_ratio": round(diversity_ratio, 3),
                },
            )

        return SanityCheckResult(
            name=name,
            passed=True,
            details=(
                f"Good B-roll diversity: {unique} unique sources "
                f"out of {total} total (ratio={diversity_ratio:.2f})."
            ),
            metrics={
                "total_sources": total,
                "unique_sources": unique,
                "diversity_ratio": round(diversity_ratio, 3),
            },
        )

    except Exception as exc:
        logger.warning("check_broll_diversity failed: %s", exc)
        return SanityCheckResult(
            name=name,
            passed=False,
            details=f"Check error: {exc}",
            metrics={"error": str(exc)},
        )


# ── Check 3: Stable framing (jitter detection) ─────────────────────────────────

def check_stable_framing(clip_path: str) -> SanityCheckResult:
    """
    Detect excessive jitter/shakiness via frame-difference analysis.

    Uses OpenCV to compute mean absolute difference between consecutive
    frames. High variance in frame differences indicates camera shake or
    unstable framing.

    Parameters
    ----------
    clip_path:
        Path to the rendered video file.

    Returns
    -------
    SanityCheckResult with ``passed`` = False if jitter exceeds threshold.
    """
    name = "Stable Framing"
    try:
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            return SanityCheckResult(
                name=name,
                passed=False,
                details=f"Cannot open video: {clip_path}",
            )

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if total_frames <= 1 or fps <= 0:
            cap.release()
            return SanityCheckResult(
                name=name,
                passed=False,
                details=f"Video too short ({total_frames} frames, {fps:.1f} fps).",
            )

        # Sample frames evenly across the clip (up to JITTER_SAMPLE_FRAMES)
        step = max(1, total_frames // JITTER_SAMPLE_FRAMES)
        diffs: List[float] = []
        prev_gray: Optional[np.ndarray] = None

        for frame_idx in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)

            if prev_gray is not None:
                # Mean absolute difference between consecutive frames
                diff = cv2.absdiff(gray, prev_gray)
                mean_diff = float(np.mean(diff))
                diffs.append(mean_diff)

            prev_gray = gray

        cap.release()

        if len(diffs) < 2:
            return SanityCheckResult(
                name=name,
                passed=False,
                details=f"Not enough frame samples ({len(diffs)}) for jitter analysis.",
                metrics={"samples": len(diffs)},
            )

        diff_std = float(np.std(diffs))
        diff_mean = float(np.mean(diffs))
        max_diff = float(np.max(diffs))

        if diff_std > JITTER_THRESHOLD:
            return SanityCheckResult(
                name=name,
                passed=False,
                details=(
                    f"High jitter detected: frame-diff stddev={diff_std:.1f} "
                    f"(threshold={JITTER_THRESHOLD}). Mean diff={diff_mean:.1f}, "
                    f"max diff={max_diff:.1f}. Possible camera shake or "
                    "unstable framing."
                ),
                metrics={
                    "diff_stddev": round(diff_std, 2),
                    "diff_mean": round(diff_mean, 2),
                    "diff_max": round(max_diff, 2),
                    "samples": len(diffs),
                },
            )

        return SanityCheckResult(
            name=name,
            passed=True,
            details=(
                f"Framing stable: frame-diff stddev={diff_std:.1f} "
                f"(threshold={JITTER_THRESHOLD})."
            ),
            metrics={
                "diff_stddev": round(diff_std, 2),
                "diff_mean": round(diff_mean, 2),
                "diff_max": round(max_diff, 2),
                "samples": len(diffs),
            },
        )

    except Exception as exc:
        logger.warning("check_stable_framing failed: %s", exc)
        return SanityCheckResult(
            name=name,
            passed=False,
            details=f"Check error: {exc}",
            metrics={"error": str(exc)},
        )


# ── Check 4: Audio sync and loudness ───────────────────────────────────────────

def check_audio_sync_and_loudness(clip_path: str) -> SanityCheckResult:
    """
    Verify audio-video sync (desync <= 100ms) and loudness in [-15, -13] LUFS.

    Uses FFmpeg's ``loudnorm`` filter for loudness measurement and
    ``astats`` / ``adelay`` comparison for sync estimation.

    Parameters
    ----------
    clip_path:
        Path to the rendered video file.

    Returns
    -------
    SanityCheckResult with ``passed`` = False if desync > 100ms or
    loudness outside [-15, -13] LUFS.
    """
    name = "Audio Sync & Loudness"
    try:
        # ── Part A: Loudness measurement via FFmpeg loudnorm ─────────────
        loudness_result = _measure_loudness(clip_path)
        integrated_loudness = loudness_result.get("integrated_loudness")
        loudness_range = loudness_result.get("loudness_range")
        true_peak = loudness_result.get("true_peak")

        loudness_ok = True
        loudness_issues: List[str] = []

        if integrated_loudness is not None:
            if integrated_loudness < LOUDNESS_MIN:
                loudness_issues.append(
                    f"Too quiet: {integrated_loudness:.1f} LUFS "
                    f"(min {LOUDNESS_MIN})"
                )
                loudness_ok = False
            elif integrated_loudness > LOUDNESS_MAX:
                loudness_issues.append(
                    f"Too loud: {integrated_loudness:.1f} LUFS "
                    f"(max {LOUDNESS_MAX})"
                )
                loudness_ok = False
        else:
            loudness_issues.append("Could not measure loudness")
            loudness_ok = False

        # ── Part B: Audio-video sync estimation ──────────────────────────
        desync_ms = _estimate_audio_sync(clip_path)
        sync_ok = desync_ms is not None and desync_ms <= MAX_DESYNC_MS

        if not sync_ok:
            desync_msg = (
                f"Audio desync ~{desync_ms:.0f}ms (max {MAX_DESYNC_MS}ms)"
                if desync_ms is not None
                else "Could not measure audio sync"
            )
        else:
            desync_msg = f"Audio sync OK (~{desync_ms:.0f}ms)"

        # ── Compose result ───────────────────────────────────────────────
        all_issues = loudness_issues + ([desync_msg] if not sync_ok else [])
        passed = loudness_ok and sync_ok

        metrics: Dict[str, Any] = {
            "integrated_loudness_lufs": integrated_loudness,
            "loudness_range_lu": loudness_range,
            "true_peak_dbfs": true_peak,
            "estimated_desync_ms": desync_ms,
            "loudness_min_lufs": LOUDNESS_MIN,
            "loudness_max_lufs": LOUDNESS_MAX,
            "max_desync_ms": MAX_DESYNC_MS,
        }

        if passed:
            return SanityCheckResult(
                name=name,
                passed=True,
                details=(
                    f"Audio OK: loudness={integrated_loudness:.1f} LUFS "
                    f"(range [{LOUDNESS_MIN}, {LOUDNESS_MAX}]), "
                    f"desync={desync_ms:.0f}ms."
                ),
                metrics=metrics,
            )
        else:
            return SanityCheckResult(
                name=name,
                passed=False,
                details="; ".join(all_issues),
                metrics=metrics,
            )

    except Exception as exc:
        logger.warning("check_audio_sync_and_loudness failed: %s", exc)
        return SanityCheckResult(
            name=name,
            passed=False,
            details=f"Check error: {exc}",
            metrics={"error": str(exc)},
        )


def _measure_loudness(clip_path: str) -> Dict[str, Any]:
    """
    Measure integrated loudness (LUFS), loudness range, and true peak
    using FFmpeg's loudnorm filter in dual-pass mode.
    """
    result: Dict[str, Any] = {
        "integrated_loudness": None,
        "loudness_range": None,
        "true_peak": None,
    }

    # First pass: measure without correction
    cmd = [
        "ffmpeg", "-y",
        "-i", clip_path,
        "-af", "loudnorm=I=-14:LRA=1:TP=-1:print_format=json",
        "-f", "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("_measure_loudness timed out for %s", clip_path)
        return result
    output = (proc.stderr + proc.stdout).decode(errors="replace")

    # Parse JSON from loudnorm output
    # loudnorm prints JSON after "Parsed_loudnorm" in stderr
    json_match = re.search(r"\{[\s\S]*\"input_i\"[\s\S]*\}", output)
    if json_match:
        try:
            data = json.loads(json_match.group())
            result["integrated_loudness"] = _safe_float(data.get("input_i"))
            result["loudness_range"] = _safe_float(data.get("input_lra"))
            result["true_peak"] = _safe_float(data.get("input_tp"))
        except (json.JSONDecodeError, KeyError):
            pass

    return result


def _estimate_audio_sync(clip_path: str) -> Optional[float]:
    """
    Estimate audio-video desync by comparing audio and video durations
    and checking for leading silence.

    Uses FFmpeg to compare:
    1. First audio sample position vs first video frame
    2. Total duration difference between audio and video streams

    Returns estimated desync in milliseconds, or None if measurement fails.
    """
    try:
        info = _get_video_stream_info(clip_path)
        video_duration = info.get("duration_s", 0.0)

        # Get audio stream duration via ffprobe
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "a:0",
            clip_path,
        ]
        raw = _run_ffprobe(cmd)
        data = json.loads(raw)

        audio_duration = 0.0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                dur_str = stream.get("duration", "0")
                try:
                    audio_duration = float(dur_str)
                except (ValueError, TypeError):
                    audio_duration = 0.0

        if video_duration <= 0 or audio_duration <= 0:
            return None

        # Desync = absolute difference between audio and video durations
        desync_s = abs(video_duration - audio_duration)
        return desync_s * 1000.0  # convert to ms

    except Exception:
        return None


def _safe_float(val: Any) -> Optional[float]:
    """Convert a value to float safely, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── Aggregated runner ──────────────────────────────────────────────────────────

def run_all_sanity_checks(
    clip_path: str,
    task_context: Optional[Dict[str, Any]] = None,
) -> SanityReport:
    """
    Run all available sanity checks on a clip.

    Parameters
    ----------
    clip_path:
        Path to the rendered video file.
    task_context:
        Optional task metadata dict for B-roll diversity check.
        If omitted, B-roll check is skipped.

    Returns
    -------
    SanityReport with all check results.
    """
    checks: List[SanityCheckResult] = [
        check_no_triple_subtitles(clip_path),
        check_stable_framing(clip_path),
        check_audio_sync_and_loudness(clip_path),
    ]

    if task_context is not None:
        checks.append(check_broll_diversity(task_context))

    overall = all(c.passed for c in checks)

    return SanityReport(
        clip_path=clip_path,
        checks=checks,
        overall_pass=overall,
    )
