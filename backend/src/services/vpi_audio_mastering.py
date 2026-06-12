"""
VPI Audio Mastering v3.0 — Loudness Normalization for Social Reels
====================================================================

Measures and normalizes audio loudness for vertical short-form video
(1080×1920 reels).  Uses FFmpeg loudnorm + acompressor + alimiter to
ensure voice is clear, loud, and publishable.

Problem:
  The technical pipeline produces valid 1080×1920 h264+aac output, but
  voice levels are too low even at max device volume.  Existing QC only
  checks for audio *presence*, not loudness.

Solution:
  1. Measure input loudness (EBU R128 via loudnorm or volumedetect fallback).
  2. Apply mastering chain: compressor → loudnorm → limiter.
  3. Measure output loudness.
  4. Report before/after metrics in output QC metadata.

Flags (read from env, never modify .env):
  VIRACLIP_AUDIO_MASTERING  (default: true in Beta Clean)
  VIRACLIP_AUDIO_TARGET_LUFS (default: -16.0)
  VIRACLIP_AUDIO_TRUE_PEAK   (default: -1.5)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_TARGET_LUFS = -16.0
DEFAULT_TRUE_PEAK = -1.5
DEFAULT_LRA = 11.0

# Threshold below which we consider audio "already loud enough" and skip
ALREADY_LOUD_THRESHOLD_LUFS = -14.0


# ══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AudioLoudnessReport:
    """Loudness measurement results (before or after mastering)."""
    input_i: Optional[float] = None       # Integrated LUFS
    input_tp: Optional[float] = None      # True Peak dBTP
    input_lra: Optional[float] = None     # Loudness Range
    input_thresh: Optional[float] = None  # Threshold
    output_i: Optional[float] = None      # After-measurement integrated (for 2-pass)
    output_tp: Optional[float] = None
    output_lra: Optional[float] = None
    output_thresh: Optional[float] = None
    mean_volume: Optional[float] = None   # volumedetect fallback
    max_volume: Optional[float] = None    # volumedetect fallback
    measurement_method: str = "unavailable"
    normalization_type: Optional[str] = None
    target_offset: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class AudioMasteringResult:
    """Result of applying audio mastering."""
    enabled: bool = True
    applied: bool = False
    input_path: str = ""
    output_path: str = ""
    method: str = "none"
    target_lufs: float = DEFAULT_TARGET_LUFS
    true_peak: float = DEFAULT_TRUE_PEAK
    loudness_report: Optional[AudioLoudnessReport] = None
    input_loudness_report: Optional[AudioLoudnessReport] = None
    output_loudness_report: Optional[AudioLoudnessReport] = None
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_env_flag(name: str, default: bool) -> bool:
    val = os.environ.get(name, "").lower().strip()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


def _get_env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _is_beta_clean() -> bool:
    return os.environ.get("VIRACLIP_BETA_CLEAN", "").lower() in ("1", "true", "yes")


def audio_mastering_enabled() -> bool:
    """Check if audio mastering is enabled.

    In Beta Clean mode, defaults to True unless explicitly disabled.
    Outside Beta Clean, defaults to False.
    """
    explicit = os.environ.get("VIRACLIP_AUDIO_MASTERING")
    if explicit is not None:
        return explicit.lower() in ("1", "true", "yes", "on")
    # Default: enabled in Beta Clean
    return _is_beta_clean()


def get_target_lufs() -> float:
    return _get_env_float("VIRACLIP_AUDIO_TARGET_LUFS", DEFAULT_TARGET_LUFS)


def get_true_peak() -> float:
    return _get_env_float("VIRACLIP_AUDIO_TRUE_PEAK", DEFAULT_TRUE_PEAK)


# ══════════════════════════════════════════════════════════════════════════════
# FASE 1 — LUFS real con loudnorm detect
# ══════════════════════════════════════════════════════════════════════════════

def _parse_loudnorm_json(stderr: str) -> Optional[Dict[str, Any]]:
    """Extract and parse loudnorm JSON from ffmpeg stderr output.

    loudnorm with print_format=json prints a JSON block to stderr.
    This function finds the JSON block (between { and }) and parses it.

    Returns parsed dict or None if no valid JSON found.
    """
    # Try to find JSON block in stderr
    json_start = stderr.find("{")
    json_end = stderr.rfind("}") + 1
    if json_start < 0 or json_end <= json_start:
        return None

    raw = stderr[json_start:json_end]
    try:
        data = json.loads(raw)
        return data
    except json.JSONDecodeError:
        return None


def _parse_loudnorm_legacy(stderr: str) -> Optional[Dict[str, Any]]:
    """Fallback parser for loudnorm output that uses key: value lines instead of JSON.

    Some FFmpeg versions/builds output loudnorm measurements as:
        input_integrated: -18.7
        input_true_peak: -1.0
        ...

    Returns parsed dict or None.
    """
    data: Dict[str, Any] = {}
    found_any = False
    for line in stderr.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower().replace(" ", "_")
        val = val.strip()
        if not val:
            continue
        # Map legacy keys to loudnorm JSON keys
        key_map = {
            "input_integrated": "input_i",
            "input_true_peak": "input_tp",
            "input_loudness_range": "input_lra",
            "input_threshold": "input_thresh",
            "output_integrated": "output_i",
            "output_true_peak": "output_tp",
            "output_loudness_range": "output_lra",
            "output_threshold": "output_thresh",
            "normalization_type": "normalization_type",
            "target_offset": "target_offset",
        }
        mapped_key = key_map.get(key, key)
        try:
            data[mapped_key] = float(val)
        except ValueError:
            data[mapped_key] = val
        found_any = True

    if found_any and "input_i" in data:
        return data
    return None


def _parse_volumedetect(stderr: str) -> Dict[str, Optional[float]]:
    """Parse volumedetect output from ffmpeg stderr.

    Returns dict with mean_volume and max_volume keys.
    """
    result: Dict[str, Optional[float]] = {
        "mean_volume": None,
        "max_volume": None,
    }
    for line in stderr.split("\n"):
        line = line.strip()
        if "mean_volume" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                result["mean_volume"] = _safe_float(parts[-1].replace("dB", "").strip())
        elif "max_volume" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                result["max_volume"] = _safe_float(parts[-1].replace("dB", "").strip())
    return result


def measure_loudness(input_path: str) -> AudioLoudnessReport:
    """Measure audio loudness using FFmpeg loudnorm (first pass) or volumedetect.

    Returns an AudioLoudnessReport with available metrics.
    Never raises — returns report with warnings on failure.
    """
    report = AudioLoudnessReport()
    path = Path(input_path)

    if not path.exists():
        report.warnings.append("input_file_not_found")
        return report

    # ── Method 1: loudnorm first pass (EBU R128) ──────────────────────────
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats",
            "-i", str(path),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        stderr = result.stderr or ""

        # Try JSON format first
        loud_data = _parse_loudnorm_json(stderr)

        # Fallback to legacy key:value format
        if loud_data is None:
            loud_data = _parse_loudnorm_legacy(stderr)

        if loud_data is not None:
            report.input_i = _safe_float(loud_data.get("input_i"))
            report.input_tp = _safe_float(loud_data.get("input_tp"))
            report.input_lra = _safe_float(loud_data.get("input_lra"))
            report.input_thresh = _safe_float(loud_data.get("input_thresh"))
            report.output_i = _safe_float(loud_data.get("output_i"))
            report.output_tp = _safe_float(loud_data.get("output_tp"))
            report.output_lra = _safe_float(loud_data.get("output_lra"))
            report.output_thresh = _safe_float(loud_data.get("output_thresh"))
            report.normalization_type = str(loud_data.get("normalization_type") or "") or None
            report.target_offset = _safe_float(loud_data.get("target_offset"))
            report.measurement_method = "loudnorm_json"

            logger.info(
                "[audio-qc] input_lufs=%s input_peak=%s method=%s",
                report.input_i, report.input_tp, report.measurement_method,
            )
            return report

        # loudnorm ran but no parsable output
        report.warnings.append(
            f"loudnorm_no_parseable_output:returncode={result.returncode}"
        )
        logger.debug(
            "[audio-qc] loudnorm first pass produced no parseable output "
            "(stderr length=%d)", len(stderr),
        )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        report.warnings.append(f"loudnorm_failed:{e}")
        logger.debug("[audio-qc] loudnorm first pass failed: %s", e)

    # ── Method 2: volumedetect fallback ───────────────────────────────────
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats",
            "-i", str(path),
            "-af", "volumedetect",
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        stderr = result.stderr or ""
        vd = _parse_volumedetect(stderr)
        report.mean_volume = vd["mean_volume"]
        report.max_volume = vd["max_volume"]

        if report.mean_volume is not None or report.max_volume is not None:
            report.measurement_method = "volumedetect_fallback"
            report.warnings.append("lufs_unavailable_using_mean_volume")
            logger.info(
                "[audio-qc] input_lufs=%s input_peak=%s method=%s "
                "mean_volume=%s max_volume=%s",
                report.input_i, report.input_tp, report.measurement_method,
                report.mean_volume, report.max_volume,
            )
        else:
            report.warnings.append("volumedetect_no_output")
            logger.warning(
                "[audio-qc] volumedetect produced no output for %s",
                path.name,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("[audio-qc] volumedetect failed: %s", e)
        report.warnings.append("measurement_failed")
        report.measurement_method = "unavailable"

    return report


def _safe_float(val: Any) -> Optional[float]:
    """Convert a value to float safely."""
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


def _analysis_from_report(report: AudioLoudnessReport) -> Dict[str, Any]:
    """Convert a loudness report into a compact analysis dict."""
    integrated_lufs = report.output_i if report.output_i is not None else report.input_i
    true_peak = report.output_tp if report.output_tp is not None else report.input_tp
    if true_peak is None:
        true_peak = report.max_volume
    mean_volume_db = report.mean_volume
    max_volume_db = report.max_volume
    audio_analysis_available = bool(
        report.measurement_method != "unavailable"
        or integrated_lufs is not None
        or mean_volume_db is not None
        or max_volume_db is not None
    )
    silence_likely = bool(mean_volume_db is not None and mean_volume_db < -45.0)
    too_quiet = bool(
        (mean_volume_db is not None and mean_volume_db < -28.0)
        or (integrated_lufs is not None and integrated_lufs < -18.5)
    )
    clipping_risk = bool(true_peak is not None and true_peak > -0.5)
    too_loud = bool(
        (true_peak is not None and true_peak > -1.0)
        or (mean_volume_db is not None and mean_volume_db > -10.0)
    )
    voice_band_energy_hint = "balanced"
    if silence_likely:
        voice_band_energy_hint = "silent"
    elif too_quiet:
        voice_band_energy_hint = "weak"
    elif clipping_risk or too_loud:
        voice_band_energy_hint = "hot"
    elif mean_volume_db is not None and -24.0 <= mean_volume_db <= -14.0:
        voice_band_energy_hint = "healthy"

    return {
        "audio_analysis_available": audio_analysis_available,
        "mean_volume_db": mean_volume_db,
        "max_volume_db": max_volume_db,
        "integrated_lufs": integrated_lufs,
        "true_peak": true_peak,
        "silence_likely": silence_likely,
        "clipping_risk": clipping_risk,
        "too_quiet": too_quiet,
        "too_loud": too_loud,
        "voice_band_energy_hint": voice_band_energy_hint,
        "analysis_method": report.measurement_method,
        "analysis_warnings": list(report.warnings or []),
    }


def analyze_audio_loudness(path: str) -> Dict[str, Any]:
    """Analyze audio loudness for a file and return a compact dict."""
    report = measure_loudness(path)
    analysis = _analysis_from_report(report)
    logger.info(
        "AUDIO_LOUDNESS_ANALYZED path=%s available=%s mean_db=%s max_db=%s lufs=%s true_peak=%s silence=%s clipping=%s too_quiet=%s too_loud=%s",
        Path(path).name if path else "",
        str(bool(analysis.get("audio_analysis_available"))).lower(),
        analysis.get("mean_volume_db"),
        analysis.get("max_volume_db"),
        analysis.get("integrated_lufs"),
        analysis.get("true_peak"),
        str(bool(analysis.get("silence_likely"))).lower(),
        str(bool(analysis.get("clipping_risk"))).lower(),
        str(bool(analysis.get("too_quiet"))).lower(),
        str(bool(analysis.get("too_loud"))).lower(),
    )
    return analysis


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3 — Audio Mastering
# ══════════════════════════════════════════════════════════════════════════════

def should_apply_audio_mastering(report: AudioLoudnessReport) -> bool:
    """Determine if mastering is needed based on loudness report.

    Returns False if audio is already loud enough (input_i >= -14 LUFS).
    Returns True if audio is quiet or measurement is unavailable.
    """
    if report.input_i is not None:
        # Already loud enough — skip
        if report.input_i >= ALREADY_LOUD_THRESHOLD_LUFS:
            return False
        # Quiet — apply
        return True
    # Fallback: check mean_volume
    if report.mean_volume is not None:
        # Rough heuristic: mean_volume < -20 dB means quiet
        if report.mean_volume >= -20.0:
            return False
        return True
    # Can't measure — apply as safety measure
    return True


def master_audio_for_social(
    input_path: str,
    output_path: str,
    target_lufs: Optional[float] = None,
    true_peak: Optional[float] = None,
) -> AudioMasteringResult:
    """Apply audio mastering for social media reels.

    Pipeline:
      1. Measure input loudness.
      2. If already loud enough, skip (copy input to output).
      3. Apply FFmpeg filter chain:
         acompressor → loudnorm → alimiter
      4. Measure output loudness.
      5. Return AudioMasteringResult with metrics.

    Args:
        input_path: Path to input video file.
        output_path: Path for output video file.
        target_lufs: Target integrated loudness in LUFS (default: -16).
        true_peak: Maximum true peak in dBTP (default: -1.5).

    Returns:
        AudioMasteringResult with applied status, metrics, and warnings.
    """
    result = AudioMasteringResult(
        enabled=audio_mastering_enabled(),
        input_path=input_path,
        output_path=output_path,
        target_lufs=target_lufs if target_lufs is not None else get_target_lufs(),
        true_peak=true_peak if true_peak is not None else get_true_peak(),
    )

    input_path_obj = Path(input_path)
    if not input_path_obj.exists():
        result.error = "input_file_not_found"
        result.warnings.append("input_file_not_found")
        return result

    if not result.enabled:
        logger.info("[audio-master] disabled by VIRACLIP_AUDIO_MASTERING=false")
        report = measure_loudness(input_path)
        result.input_loudness_report = report
        result.output_loudness_report = report
        result.loudness_report = report
        result.method = "disabled"
        result.warnings.append("audio_mastering_disabled")
        result.pre_master_audio_analysis = _analysis_from_report(report)  # type: ignore[attr-defined]
        result.post_master_audio_analysis = _analysis_from_report(report)  # type: ignore[attr-defined]
        return result

    # ── Step 1: Measure input loudness ────────────────────────────────────
    logger.info("[audio-master] measuring input loudness: %s", input_path_obj.name)
    input_report = measure_loudness(input_path)
    pre_master_analysis = _analysis_from_report(input_report)
    result.loudness_report = input_report
    result.input_loudness_report = input_report
    result.pre_master_audio_analysis = pre_master_analysis  # type: ignore[attr-defined]

    # ── Step 2: Check if mastering is needed ──────────────────────────────
    if not should_apply_audio_mastering(input_report):
        logger.info(
            "[audio-master] skipped reason=already_loud_enough input_i=%s",
            input_report.input_i,
        )
        result.method = "skipped"
        result.warnings.append("already_loud_enough")
        # Copy input to output
        try:
            _copy_file(input_path, output_path)
            result.applied = False
            result.output_loudness_report = measure_loudness(output_path)
            result.loudness_report = result.output_loudness_report
            result.post_master_audio_analysis = _analysis_from_report(result.output_loudness_report)  # type: ignore[attr-defined]
            return result
        except Exception as e:
            result.error = str(e)
            result.warnings.append("copy_failed")
            return result

    # ── Step 3: Apply mastering filter chain ──────────────────────────────
    # Chain: acompressor → loudnorm → alimiter
    # - acompressor: smooth compression, threshold -18dB, ratio 2.2:1
    # - loudnorm: EBU R128 normalization to target LUFS
    # - alimiter: hard limit at true_peak to prevent clipping
    af_chain = (
        f"acompressor=threshold=-18dB:ratio=2.2:attack=8:release=80,"
        f"loudnorm=I={result.target_lufs}:TP={result.true_peak}:LRA=11,"
        f"alimiter=limit=0.95"
    )

    logger.info(
        "[audio-master] applied=true target_lufs=%s true_peak=%s",
        result.target_lufs, result.true_peak,
    )

    try:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
            "-c:v", "copy",           # Copy video stream (no re-encode)
            "-af", af_chain,          # Audio filter chain
            "-c:a", "aac",            # Re-encode audio to AAC
            "-ar", "48000",           # 48 kHz sample rate
            "-b:a", "192k",           # 192 kbps bitrate
            "-movflags", "+faststart",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)

        if not Path(output_path).exists():
            raise RuntimeError("output file not created")

        result.applied = True
        result.method = "loudnorm+compressor+limiter"

        # ── Step 4: Measure output loudness ───────────────────────────────
        output_report = measure_loudness(output_path)
        result.loudness_report = output_report
        result.output_loudness_report = output_report
        post_master_analysis = _analysis_from_report(output_report)
        result.post_master_audio_analysis = post_master_analysis  # type: ignore[attr-defined]

        # Use output_i from loudnorm (which is the measured LUFS of the output file)
        # or fall back to input_i (same file measurement)
        output_lufs = output_report.output_i if output_report.output_i is not None else output_report.input_i
        output_peak = output_report.output_tp if output_report.output_tp is not None else output_report.input_tp
        if output_peak is None:
            output_peak = output_report.max_volume

        logger.info(
            "[audio-qc] output_lufs=%s output_peak=%s method=%s",
            output_lufs,
            output_peak,
            output_report.measurement_method,
        )
        rejected_reasons: List[str] = []
        if post_master_analysis.get("silence_likely"):
            rejected_reasons.append("silence_likely")
        if post_master_analysis.get("clipping_risk"):
            rejected_reasons.append("clipping_risk")
        if post_master_analysis.get("too_quiet"):
            rejected_reasons.append("too_quiet")
        if rejected_reasons:
            logger.warning(
                "AUDIO_MASTERING_REJECTED_REASON path=%s reason=%s",
                Path(output_path).name,
                "|".join(rejected_reasons),
            )
            _fallback_copy(input_path, output_path, result)
            result.method = "fallback_pre_master_analysis_rejected"
            result.applied = False
            result.warnings.append("mastering_rejected_analysis")
            result.output_loudness_report = measure_loudness(output_path)
            result.post_master_audio_analysis = _analysis_from_report(result.output_loudness_report)  # type: ignore[attr-defined]
        else:
            logger.info("AUDIO_MASTERING_IMPROVED_AUDIO input=%s output=%s", input_path_obj.name, Path(output_path).name)

    except subprocess.TimeoutExpired:
        logger.warning("[audio-master] failed fallback=input reason=timeout")
        result.error = "ffmpeg_timeout"
        result.warnings.append("audio_mastering_failed")
        _fallback_copy(input_path, output_path, result)
        result.post_master_audio_analysis = analyze_audio_loudness(output_path)  # type: ignore[attr-defined]

    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "")[-240:]
        logger.warning("[audio-master] failed fallback=input reason=%s", stderr)
        result.error = f"ffmpeg_error: {stderr}"
        result.warnings.append("audio_mastering_failed")
        _fallback_copy(input_path, output_path, result)
        result.post_master_audio_analysis = analyze_audio_loudness(output_path)  # type: ignore[attr-defined]

    except Exception as e:
        logger.warning("[audio-master] failed fallback=input reason=%s", e)
        result.error = str(e)
        result.warnings.append("audio_mastering_failed")
        _fallback_copy(input_path, output_path, result)
        result.post_master_audio_analysis = analyze_audio_loudness(output_path)  # type: ignore[attr-defined]

    return result


def _fallback_copy(input_path: str, output_path: str, result: AudioMasteringResult) -> None:
    """Copy input to output as fallback when mastering fails."""
    try:
        _copy_file(input_path, output_path)
        result.applied = False
        result.method = "fallback_input_copy"
    except Exception as copy_e:
        result.error = f"{result.error}; copy_fallback_failed: {copy_e}"
        result.warnings.append("fallback_copy_failed")


def _copy_file(src: str, dst: str) -> None:
    """Copy a file using shutil (fast local copy)."""
    import shutil
    shutil.copy2(src, dst)


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3 — Voice loudness classification
# ══════════════════════════════════════════════════════════════════════════════

def classify_audio_voice_status(report: AudioLoudnessReport) -> str:
    """Classify voice loudness quality based on measurement report.

    Uses output_i (measured output LUFS) when available, falls back to
    input_i, then mean_volume.

    Rules:
      - output_lufs between -18 and -14 -> good
      - output_lufs < -20 -> too_low
      - output_lufs -20 to -18 -> slightly_low
      - true peak > -0.5 -> clipping_risk
      - If only volumedetect: use mean_volume with warning
    """
    # Prefer output_i (post-mastering measurement), then input_i, then mean_volume
    lufs = report.output_i if report.output_i is not None else report.input_i
    peak = report.output_tp if report.output_tp is not None else report.input_tp
    if peak is None:
        peak = report.max_volume

    # Clipping check first (independent of LUFS)
    if peak is not None and peak > -0.5:
        return "clipping_risk"

    # Fallback to mean_volume if no LUFS available
    if lufs is None and report.mean_volume is not None:
        lufs = report.mean_volume

    if lufs is None:
        return "unknown"

    if -18.0 <= lufs <= -14.0:
        return "good"
    if lufs < -20.0:
        return "too_low"
    if -20.0 <= lufs < -18.0:
        return "slightly_low"
    # lufs > -14.0 (above threshold) — also good but could be loud
    return "good"


# ══════════════════════════════════════════════════════════════════════════════
# FASE 4 — Metadata: build audio QC dict for output metadata
# ══════════════════════════════════════════════════════════════════════════════

def build_audio_qc_metadata(result: AudioMasteringResult) -> Dict[str, Any]:
    """Build the audio_qc sub-dict for output QC metadata.

    Returns a dict suitable for merging into output_qc or clip metadata.
    Includes all FASE 4 fields: audio_mastering_applied, input_lufs,
    output_lufs, input_peak, output_peak, audio_measurement_method,
    audio_voice_status, audio_warnings.
    """
    input_report = result.input_loudness_report or result.loudness_report or AudioLoudnessReport()
    output_report = result.output_loudness_report or result.loudness_report or AudioLoudnessReport()

    # Output LUFS: prefer output_i (post-measurement), fall back to input_i
    output_lufs = output_report.output_i if output_report.output_i is not None else output_report.input_i
    input_lufs = input_report.input_i

    # Output peak: prefer output_tp, then input_tp, then max_volume
    output_peak = output_report.output_tp
    if output_peak is None:
        output_peak = output_report.input_tp
    if output_peak is None:
        output_peak = output_report.max_volume

    # Input peak: prefer input_tp, then max_volume
    input_peak = input_report.input_tp
    if input_peak is None:
        input_peak = input_report.max_volume

    # Deduplicated warnings
    audio_warnings = list(dict.fromkeys(
        list(result.warnings or [])
        + list(input_report.warnings or [])
        + list(output_report.warnings or [])
    ))
    pre_master_analysis = getattr(result, "pre_master_audio_analysis", None)
    if not isinstance(pre_master_analysis, dict):
        pre_master_analysis = analyze_audio_loudness(result.input_path) if result.input_path else _analysis_from_report(input_report)
    post_master_analysis = getattr(result, "post_master_audio_analysis", None)
    if not isinstance(post_master_analysis, dict):
        post_master_analysis = analyze_audio_loudness(result.output_path) if result.output_path else _analysis_from_report(output_report)
    mastered_better = bool(
        post_master_analysis.get("audio_analysis_available")
        and not post_master_analysis.get("silence_likely")
        and not post_master_analysis.get("clipping_risk")
        and not post_master_analysis.get("too_quiet")
    )
    rejected_reason = ""
    if result.error:
        rejected_reason = str(result.error)
    elif not mastered_better and not bool(result.applied):
        rejected_reason = str(post_master_analysis.get("voice_band_energy_hint") or "analysis_rejected")
    elif bool(post_master_analysis.get("silence_likely")):
        rejected_reason = "silence_likely"
    elif bool(post_master_analysis.get("clipping_risk")):
        rejected_reason = "clipping_risk"
    elif bool(post_master_analysis.get("too_quiet")):
        rejected_reason = "too_quiet"

    return {
        # FASE 4 fields
        "audio_mastering_applied": result.applied,
        "audio_mastering_enabled": result.enabled,
        "audio_mastering_method": result.method,
        "audio_mastering_fallback_to_premaster": bool(
            result.method.startswith("fallback")
            or "fallback" in " ".join(audio_warnings).lower()
        ),
        "audio_mastering_skip_reason": (
            result.error
            or ("already_loud_enough" if result.method == "skipped" else "")
            or ("disabled" if not result.enabled else "")
        ),
        "input_lufs": input_lufs,
        "output_lufs": output_lufs,
        "input_peak": input_peak,
        "output_peak": output_peak,
        "input_true_peak": input_report.input_tp,
        "output_true_peak": output_report.input_tp,
        "input_lra": input_report.input_lra,
        "output_lra": output_report.input_lra,
        "mean_volume": output_report.mean_volume,
        "max_volume": output_report.max_volume,
        "input_mean_volume": input_report.mean_volume,
        "output_mean_volume": output_report.mean_volume,
        "audio_measurement_method": output_report.measurement_method,
        "input_audio_measurement_method": input_report.measurement_method,
        "audio_voice_status": classify_audio_voice_status(output_report),
        "target_lufs": result.target_lufs,
        "true_peak": result.true_peak,
        "normalization_type": output_report.normalization_type,
        "target_offset": output_report.target_offset,
        "audio_warnings": audio_warnings,
        "pre_master_audio_analysis": pre_master_analysis,
        "post_master_audio_analysis": post_master_analysis,
        "mastering_improved_audio": bool(mastered_better),
        "mastering_rejected_reason": rejected_reason,
    }


def build_audio_publish_warnings(result: AudioMasteringResult) -> List[str]:
    """Build publishable_warnings entries related to audio.

    Returns a list of warning strings to append to publishable_warnings.
    """
    warnings: List[str] = []
    report = result.output_loudness_report or result.loudness_report or AudioLoudnessReport()

    if result.error:
        warnings.append("audio_mastering_failed")

    status = classify_audio_voice_status(report)
    if status in {"too_low", "slightly_low", "clipping_risk", "unknown"}:
        warnings.append(f"audio_voice_{status}")

    # Check peak for clipping
    peak = report.output_tp if report.output_tp is not None else report.input_tp
    if peak is None:
        peak = report.max_volume
    if peak is not None and peak > -0.5:
        warnings.append("possible_audio_clipping")

    if "measurement_failed" in report.warnings:
        warnings.append("audio_measure_failed")

    return warnings


# ══════════════════════════════════════════════════════════════════════════════
# FASE 5 — Final Audio Audibility QC
# ══════════════════════════════════════════════════════════════════════════════

def final_audio_audibility_qc(
    audio_path: str,
    pre_master_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run final audio audibility QC on a mastered audio/video file.

    Uses ffprobe to:
      1. Check that an audio stream exists.
      2. Run volumedetect to get mean_volume and max_volume.
      3. If mean_volume > -30 dB (near-silent), log AUDIO_MASTERING_FALLBACK
         reason=near_silence and fall back to pre-master output (if available).
      4. Log FINAL_AUDIO_QC with path, has_audio_stream, mean_volume,
         max_volume, audible.
      5. If no audible audio remains, return technical_qc fail.

    Returns a dict with:
      - path: str
      - has_audio_stream: bool
      - mean_volume: Optional[float]
      - max_volume: Optional[float]
      - audible: bool
      - fallback_applied: bool
      - fallback_reason: Optional[str]
      - technical_qc_passed: bool
      - technical_qc_reasons: List[str]
    """
    result: Dict[str, Any] = {
        "path": audio_path,
        "has_audio_stream": False,
        "mean_volume": None,
        "max_volume": None,
        "audible": False,
        "fallback_applied": False,
        "fallback_reason": None,
        "technical_qc_passed": True,
        "technical_qc_reasons": [],
    }

    path = Path(audio_path)
    if not path.exists():
        result["technical_qc_passed"] = False
        result["technical_qc_reasons"].append("audio_file_not_found")
        logger.warning("FINAL_AUDIO_QC path=%s has_audio_stream=false audible=false reason=file_not_found", audio_path)
        return result

    # ── Step 1: Check audio stream exists ──────────────────────────────────
    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(path),
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
        has_audio = probe_result.returncode == 0 and "audio" in (probe_result.stdout or "").strip().lower()
        result["has_audio_stream"] = has_audio
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("[audio-audibility] ffprobe stream check failed: %s", e)
        result["has_audio_stream"] = False

    if not result["has_audio_stream"]:
        result["audible"] = False
        result["technical_qc_passed"] = False
        result["technical_qc_reasons"].append("no_audio_stream")
        logger.warning(
            "FINAL_AUDIO_QC path=%s has_audio_stream=false audible=false reason=no_audio_stream",
            audio_path,
        )
        return result

    # ── Step 2: Run volumedetect ───────────────────────────────────────────
    try:
        vd_cmd = [
            "ffprobe", "-v", "error",
            "-f", "lavfi",
            "-i", f"amovie={path},volumedetect",
            "-show_entries", "tags=lavfi.volumedetect.mean_volume,lavfi.volumedetect.max_volume",
            "-of", "csv=p=0",
        ]
        vd_result = subprocess.run(vd_cmd, capture_output=True, text=True, timeout=30)
        vd_stdout = vd_result.stdout or ""
        vd_stderr = vd_result.stderr or ""

        # Fallback: parse volumedetect output from stderr if stdout is empty
        if not vd_stdout.strip():
            vd_cmd2 = [
                "ffprobe", "-v", "error",
                "-f", "lavfi",
                "-i", f"amovie={path},volumedetect",
                "-show_entries", "frame_tags",
                "-of", "default=noprint_wrappers=1",
            ]
            vd_result2 = subprocess.run(vd_cmd2, capture_output=True, text=True, timeout=30)
            vd_stdout = vd_result2.stdout or ""
            vd_stderr = vd_result2.stderr or ""

        # Parse mean_volume and max_volume from output
        mean_volume: Optional[float] = None
        max_volume: Optional[float] = None
        for line in (vd_stdout + "\n" + vd_stderr).split("\n"):
            line = line.strip().lower()
            if "mean_volume" in line:
                parts = line.split("=")
                if len(parts) >= 2:
                    try:
                        mean_volume = float(parts[-1].replace("db", "").strip())
                    except ValueError:
                        pass
            elif "max_volume" in line:
                parts = line.split("=")
                if len(parts) >= 2:
                    try:
                        max_volume = float(parts[-1].replace("db", "").strip())
                    except ValueError:
                        pass

        result["mean_volume"] = mean_volume
        result["max_volume"] = max_volume

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("[audio-audibility] volumedetect failed: %s", e)
        result["mean_volume"] = None
        result["max_volume"] = None

    # ── Step 3: Determine audibility ───────────────────────────────────────
    # If mean_volume is available and > -30 dB, audio is near-silent
    near_silent = (
        result["mean_volume"] is not None
        and result["mean_volume"] > -30.0
    )

    if near_silent:
        logger.warning(
            "AUDIO_MASTERING_FALLBACK reason=near_silence mean_volume=%.1f path=%s",
            result["mean_volume"],
            audio_path,
        )
        result["fallback_applied"] = True
        result["fallback_reason"] = "near_silence"

        # Fall back to pre-master output if available
        if pre_master_path and Path(pre_master_path).exists():
            logger.info(
                "[audio-audibility] falling back to pre-master output: %s",
                pre_master_path,
            )
            # Re-run volumedetect on pre-master
            try:
                vd_cmd3 = [
                    "ffprobe", "-v", "error",
                    "-f", "lavfi",
                    "-i", f"amovie={pre_master_path},volumedetect",
                    "-show_entries", "frame_tags",
                    "-of", "default=noprint_wrappers=1",
                ]
                vd_result3 = subprocess.run(vd_cmd3, capture_output=True, text=True, timeout=30)
                pm_stdout = vd_result3.stdout or ""
                pm_stderr = vd_result3.stderr or ""
                pm_mean: Optional[float] = None
                pm_max: Optional[float] = None
                for line in (pm_stdout + "\n" + pm_stderr).split("\n"):
                    line = line.strip().lower()
                    if "mean_volume" in line:
                        parts = line.split("=")
                        if len(parts) >= 2:
                            try:
                                pm_mean = float(parts[-1].replace("db", "").strip())
                            except ValueError:
                                pass
                    elif "max_volume" in line:
                        parts = line.split("=")
                        if len(parts) >= 2:
                            try:
                                pm_max = float(parts[-1].replace("db", "").strip())
                            except ValueError:
                                pass
                result["mean_volume"] = pm_mean
                result["max_volume"] = pm_max
                result["path"] = pre_master_path
                # Re-check audibility on pre-master
                if pm_mean is not None and pm_mean > -30.0:
                    result["audible"] = False
                    result["technical_qc_passed"] = False
                    result["technical_qc_reasons"].append("near_silent_audio")
                else:
                    result["audible"] = True
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.warning("[audio-audibility] pre-master volumedetect failed: %s", e)
                result["audible"] = False
                result["technical_qc_passed"] = False
                result["technical_qc_reasons"].append("near_silent_audio")
        else:
            result["audible"] = False
            result["technical_qc_passed"] = False
            result["technical_qc_reasons"].append("near_silent_audio")
    else:
        result["audible"] = True

    # ── Step 4: Log FINAL_AUDIO_QC ─────────────────────────────────────────
    logger.info(
        "FINAL_AUDIO_QC path=%s has_audio_stream=%s mean_volume=%s max_volume=%s audible=%s",
        result["path"],
        str(result["has_audio_stream"]).lower(),
        str(result["mean_volume"]) if result["mean_volume"] is not None else "none",
        str(result["max_volume"]) if result["max_volume"] is not None else "none",
        str(result["audible"]).lower(),
    )

    return result
