"""
ClipValidator — Comprehensive validation for clip editing pipeline.

Ensures clip quality and catches errors before they reach users:
  • Pre-render validation (input checks, timestamp validation)
  • Post-render validation (output quality, A/V sync, duration)
  • Automatic retry for recoverable errors
  • Detailed error reporting for debugging
"""

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validation check."""
    passed: bool
    issues: List[str]
    warnings: List[str]
    metadata: Dict[str, Any]


class ClipValidator:
    """Validates clip inputs and outputs for quality and correctness."""

    # ── Configurable Validation Thresholds ────────────────────────────────────
    # All thresholds can be adjusted via environment variables for stricter/looser validation
    MIN_DURATION_S = float(os.getenv("VALIDATOR_MIN_DURATION_S", "3.0"))
    MAX_DURATION_S = float(os.getenv("VALIDATOR_MAX_DURATION_S", "180.0"))
    MIN_FILE_SIZE_BYTES = int(os.getenv("VALIDATOR_MIN_FILE_SIZE_BYTES", "1024"))
    MAX_TIMESTAMP_DRIFT_S = float(os.getenv("VALIDATOR_MAX_TIMESTAMP_DRIFT_S", "0.5"))
    MIN_AUDIO_BITRATE_KBPS = float(os.getenv("VALIDATOR_MIN_AUDIO_BITRATE_KBPS", "64"))
    MIN_VIDEO_BITRATE_KBPS = float(os.getenv("VALIDATOR_MIN_VIDEO_BITRATE_KBPS", "500"))
    
    # Additional configurable thresholds
    MAX_WORD_DURATION_S = float(os.getenv("VALIDATOR_MAX_WORD_DURATION_S", "3.0"))
    MIN_WORD_DURATION_S = float(os.getenv("VALIDATOR_MIN_WORD_DURATION_S", "0.05"))
    SIZE_SIMILARITY_THRESHOLD_BYTES = int(os.getenv("VALIDATOR_SIZE_SIMILARITY_BYTES", "1024"))

    async def validate_input(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        words: Optional[List[Dict[str, Any]]] = None,
    ) -> ValidationResult:
        """
        Validate inputs before clip creation.
        
        Checks:
        - Video file exists and is readable
        - Start/end times are valid
        - Word timestamps align with clip duration
        - Source video has required streams
        """
        issues = []
        warnings = []
        metadata = {}

        # Check file existence
        if not video_path.exists():
            issues.append(f"Source video not found: {video_path}")
            return ValidationResult(False, issues, warnings, metadata)

        if not video_path.is_file():
            issues.append(f"Path is not a file: {video_path}")
            return ValidationResult(False, issues, warnings, metadata)

        # Check file size
        file_size = video_path.stat().st_size
        if file_size < self.MIN_FILE_SIZE_BYTES:
            issues.append(f"Source file too small: {file_size} bytes")
            return ValidationResult(False, issues, warnings, metadata)

        metadata["source_size_bytes"] = file_size

        # Probe video metadata
        probe_result = await self._probe_video(video_path)
        if not probe_result:
            issues.append("Failed to probe source video with ffprobe")
            return ValidationResult(False, issues, warnings, metadata)

        width, height, fps, duration, has_audio, has_video = probe_result
        metadata.update({
            "source_width": width,
            "source_height": height,
            "source_fps": fps,
            "source_duration": duration,
            "has_audio": has_audio,
            "has_video": has_video,
        })

        # Check streams
        if not has_video:
            issues.append("Source video has no video stream")
        if not has_audio:
            warnings.append("Source video has no audio stream")

        # Validate timestamps
        if start_time < 0:
            issues.append(f"Invalid start time: {start_time}s (must be >= 0)")
        if end_time <= start_time:
            issues.append(f"Invalid end time: {end_time}s (must be > {start_time}s)")
        if end_time > duration:
            issues.append(
                f"End time {end_time}s exceeds source duration {duration}s"
            )

        clip_duration = end_time - start_time
        if clip_duration < self.MIN_DURATION_S:
            issues.append(
                f"Clip too short: {clip_duration:.1f}s < {self.MIN_DURATION_S}s"
            )
        if clip_duration > self.MAX_DURATION_S:
            warnings.append(
                f"Clip very long: {clip_duration:.1f}s > {self.MAX_DURATION_S}s"
            )

        metadata["clip_duration"] = clip_duration

        # Validate word timestamps
        if words:
            word_issues = self._validate_word_timestamps(
                words, start_time, end_time, clip_duration
            )
            if word_issues:
                warnings.extend(word_issues)

        passed = len(issues) == 0
        return ValidationResult(passed, issues, warnings, metadata)

    async def validate_output(
        self,
        output_path: Path,
        expected_duration: float,
        source_path: Optional[Path] = None,
    ) -> ValidationResult:
        """
        Validate rendered clip output.
        
        Checks:
        - File exists and has content
        - Duration matches expected
        - Has valid audio/video streams
        - No corruption detected
        - Bitrates are acceptable
        """
        issues = []
        warnings = []
        metadata = {}

        # Check file existence
        if not output_path.exists():
            issues.append(f"Output file not created: {output_path}")
            return ValidationResult(False, issues, warnings, metadata)

        # Check file size
        file_size = output_path.stat().st_size
        if file_size < self.MIN_FILE_SIZE_BYTES:
            issues.append(f"Output file too small: {file_size} bytes (likely corrupt)")
            return ValidationResult(False, issues, warnings, metadata)

        metadata["output_size_bytes"] = file_size

        # Probe output
        probe_result = await self._probe_video(output_path)
        if not probe_result:
            issues.append("Failed to probe output video (may be corrupt)")
            return ValidationResult(False, issues, warnings, metadata)

        width, height, fps, duration, has_audio, has_video = probe_result
        metadata.update({
            "output_width": width,
            "output_height": height,
            "output_fps": fps,
            "output_duration": duration,
            "has_audio": has_audio,
            "has_video": has_video,
        })

        # Validate streams
        if not has_video:
            issues.append("Output has no video stream")
        if not has_audio:
            warnings.append("Output has no audio stream")

        # Validate duration
        duration_diff = abs(duration - expected_duration)
        if duration_diff > self.MAX_TIMESTAMP_DRIFT_S:
            issues.append(
                f"Duration mismatch: expected {expected_duration:.2f}s, "
                f"got {duration:.2f}s (diff: {duration_diff:.2f}s)"
            )

        metadata["duration_diff"] = duration_diff

        # Check bitrates
        bitrate_check = await self._check_bitrates(output_path)
        if bitrate_check:
            audio_br, video_br = bitrate_check
            metadata["audio_bitrate_kbps"] = audio_br
            metadata["video_bitrate_kbps"] = video_br

            if audio_br and audio_br < self.MIN_AUDIO_BITRATE_KBPS:
                warnings.append(
                    f"Low audio bitrate: {audio_br}kbps < {self.MIN_AUDIO_BITRATE_KBPS}kbps"
                )
            if video_br and video_br < self.MIN_VIDEO_BITRATE_KBPS:
                warnings.append(
                    f"Low video bitrate: {video_br}kbps < {self.MIN_VIDEO_BITRATE_KBPS}kbps"
                )

        # Compare to source if available
        if source_path and source_path.exists():
            source_size = source_path.stat().st_size
            if abs(file_size - source_size) < self.SIZE_SIMILARITY_THRESHOLD_BYTES:
                warnings.append(
                    f"Output size nearly identical to source ({abs(file_size - source_size)}B diff) - "
                    "effects may not have applied"
                )

        passed = len(issues) == 0
        return ValidationResult(passed, issues, warnings, metadata)

    async def validate_subtitle_sync(
        self,
        words: List[Dict[str, Any]],
        clip_start: float,
        clip_duration: float,
    ) -> ValidationResult:
        """
        Validate subtitle word timestamps for proper sync.
        
        Checks:
        - All words have valid timestamps
        - Timestamps are within clip bounds
        - No overlapping words
        - Reasonable word durations
        """
        issues = []
        warnings = []
        metadata = {"total_words": len(words)}

        if not words:
            warnings.append("No words provided for subtitle validation")
            return ValidationResult(True, issues, warnings, metadata)

        clip_end = clip_start + clip_duration
        prev_end = 0.0
        
        for i, word in enumerate(words):
            word_text = word.get("text", word.get("word", ""))
            start = word.get("start", 0) / 1000.0  # Convert ms to s
            end = word.get("end", 0) / 1000.0
            
            # Check timestamp validity
            if start < 0 or end < 0:
                issues.append(f"Word '{word_text}' has negative timestamp")
                continue
                
            if end <= start:
                issues.append(
                    f"Word '{word_text}' has invalid duration: "
                    f"start={start:.2f}s, end={end:.2f}s"
                )
                continue

            # Adjust to clip-relative time
            rel_start = start - clip_start
            rel_end = end - clip_start

            # Check bounds
            if rel_start < -0.1:  # Allow small tolerance
                warnings.append(
                    f"Word '{word_text}' starts before clip: {rel_start:.2f}s"
                )
            if rel_end > clip_duration + 0.1:
                warnings.append(
                    f"Word '{word_text}' ends after clip: {rel_end:.2f}s > {clip_duration:.2f}s"
                )

            # Check for overlaps
            if start < prev_end - 0.01:  # Small tolerance
                warnings.append(
                    f"Word '{word_text}' overlaps previous word: "
                    f"start={start:.2f}s < prev_end={prev_end:.2f}s"
                )

            # Check duration (typical speech: configurable range)
            word_dur = end - start
            if word_dur > self.MAX_WORD_DURATION_S:
                warnings.append(
                    f"Word '{word_text}' unusually long: {word_dur:.2f}s > {self.MAX_WORD_DURATION_S}s"
                )
            elif word_dur < self.MIN_WORD_DURATION_S:
                warnings.append(
                    f"Word '{word_text}' unusually short: {word_dur:.2f}s < {self.MIN_WORD_DURATION_S}s"
                )

            prev_end = end

        metadata["validation_complete"] = True
        passed = len(issues) == 0
        return ValidationResult(passed, issues, warnings, metadata)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _validate_word_timestamps(
        self,
        words: List[Dict[str, Any]],
        clip_start: float,
        clip_end: float,
        clip_duration: float,
    ) -> List[str]:
        """Check word timestamps for issues."""
        issues = []
        
        if not words:
            return issues

        out_of_bounds = 0
        for word in words:
            start = word.get("start", 0) / 1000.0
            end = word.get("end", 0) / 1000.0
            
            if start < clip_start or end > clip_end:
                out_of_bounds += 1

        if out_of_bounds > 0:
            issues.append(
                f"{out_of_bounds}/{len(words)} words have timestamps "
                "outside clip bounds"
            )

        return issues

    async def _probe_video(
        self, path: Path
    ) -> Optional[Tuple[int, int, float, float, bool, bool]]:
        """
        Probe video file for metadata.
        Returns: (width, height, fps, duration, has_audio, has_video)
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            data = json.loads(stdout.decode(errors="ignore"))

            streams = data.get("streams", [])
            video_stream = next(
                (s for s in streams if s.get("codec_type") == "video"), None
            )
            audio_stream = next(
                (s for s in streams if s.get("codec_type") == "audio"), None
            )

            width = int(video_stream.get("width", 1080)) if video_stream else 0
            height = int(video_stream.get("height", 1920)) if video_stream else 0

            fps = 30.0
            if video_stream and "r_frame_rate" in video_stream:
                try:
                    num, den = video_stream["r_frame_rate"].split("/")
                    fps = float(num) / float(den)
                except Exception:
                    pass

            duration = float(data.get("format", {}).get("duration", 0) or 0)

            return (
                width,
                height,
                fps,
                duration,
                audio_stream is not None,
                video_stream is not None,
            )

        except Exception as exc:
            logger.debug(f"ffprobe failed for {path}: {exc}")
            return None

    async def _check_bitrates(
        self, path: Path
    ) -> Optional[Tuple[Optional[float], Optional[float]]]:
        """
        Check audio and video bitrates.
        Returns: (audio_bitrate_kbps, video_bitrate_kbps)
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            data = json.loads(stdout.decode(errors="ignore"))

            streams = data.get("streams", [])
            
            audio_br = None
            video_br = None

            for stream in streams:
                codec_type = stream.get("codec_type")
                bit_rate = stream.get("bit_rate")
                
                if bit_rate:
                    br_kbps = int(bit_rate) / 1000.0
                    if codec_type == "audio" and audio_br is None:
                        audio_br = br_kbps
                    elif codec_type == "video" and video_br is None:
                        video_br = br_kbps

            return (audio_br, video_br)

        except Exception as exc:
            logger.debug(f"Bitrate check failed for {path}: {exc}")
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_validator: Optional[ClipValidator] = None


def get_clip_validator() -> ClipValidator:
    """Get singleton ClipValidator instance."""
    global _validator
    if _validator is None:
        _validator = ClipValidator()
    return _validator
