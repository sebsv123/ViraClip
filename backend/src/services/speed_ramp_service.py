"""
Speed Ramp Service — Cinematic speed ramps using FFmpeg only.
NO GPU, NO torch, NO transformers — 100% CPU to preserve VRAM for Whisper.
"""
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class RampStyle(Enum):
    DRAMATIC = "dramatic"
    HYPE = "hype"
    CINEMATIC = "cinematic"
    SUBTLE = "subtle"


@dataclass
class SpeedPoint:
    time: float
    speed: float
    transition: float


@dataclass
class SpeedRampResult:
    output_path: Path
    ramp_points: List[SpeedPoint]
    style_applied: RampStyle
    duration_original: float
    duration_final: float


# RAMP_PRESETS calibrated for 30s clips
RAMP_PRESETS: dict[str, List[SpeedPoint]] = {
    "inspirational": [
        SpeedPoint(0.0, 1.0, 0),
        SpeedPoint(2.0, 0.4, 1.5),
        SpeedPoint(4.0, 1.0, 0.8),
        SpeedPoint(18.0, 1.8, 1.0),
        SpeedPoint(22.0, 1.0, 1.0),
    ],
    "dramatic": [
        SpeedPoint(0.0, 1.5, 0),
        SpeedPoint(3.0, 0.3, 2.0),
        SpeedPoint(6.0, 1.0, 1.0),
    ],
    "hype": [
        SpeedPoint(0.0, 1.0, 0),
        SpeedPoint(8.0, 2.5, 0.5),
        SpeedPoint(10.0, 1.0, 0.3),
    ],
    "educational": [
        SpeedPoint(0.0, 1.0, 0),
        SpeedPoint(5.0, 0.8, 1.0),
    ],
}


class SpeedRampService:
    """
    Applies cinematic speed ramps to video clips using FFmpeg.
    CPU-only, no ML models required.
    """

    async def apply_speed_ramp(
        self,
        input_path: Path,
        output_path: Path,
        mood: str,
        style: Optional[RampStyle] = None,
        custom_points: Optional[List[SpeedPoint]] = None,
        clip_duration: float = 30.0,
    ) -> SpeedRampResult:
        """
        Apply speed ramp to a video clip.

        Args:
            input_path: Source video file
            output_path: Destination for speed-ramped video
            mood: Preset key from RAMP_PRESETS
            style: Optional override for RampStyle (auto-inferred if None)
            custom_points: Optional custom speed points (overrides mood)
            clip_duration: Actual clip duration (for scaling 30s presets)

        Returns:
            SpeedRampResult with metadata about the applied ramp
        """
        input_path = Path(input_path)
        output_path = Path(output_path)

        # Get speed points
        if custom_points:
            points = custom_points
        elif mood in RAMP_PRESETS:
            points = RAMP_PRESETS[mood]
        else:
            logger.warning(f"Unknown mood '{mood}', using educational preset")
            points = RAMP_PRESETS["educational"]

        # Scale times if clip_duration differs from 30s calibration
        if clip_duration != 30.0:
            scale_factor = clip_duration / 30.0
            points = [
                SpeedPoint(
                    time=p.time * scale_factor,
                    speed=p.speed,
                    transition=p.transition,
                )
                for p in points
            ]

        # Infer style if not provided
        if style is None:
            style = self._infer_style(mood)

        # Get original duration via ffprobe
        original_duration = await self._get_video_duration(input_path)

        # Build FFmpeg filter complex
        filter_complex = self._build_filter_complex(points, original_duration)

        # Run FFmpeg
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path),
        ]

        logger.info(f"[SpeedRamp] Applying {style.value} ramp to {input_path.name}")
        logger.debug(f"[SpeedRamp] Filter: {filter_complex[:100]}...")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"FFmpeg speed ramp failed: {stderr_text[-500:]}")

        # Calculate final duration
        final_duration = self._estimate_output_duration(points, original_duration)

        logger.info(
            f"[SpeedRamp] Complete: {input_path.name} -> {output_path.name} "
            f"({original_duration:.1f}s -> {final_duration:.1f}s)"
        )

        return SpeedRampResult(
            output_path=output_path,
            ramp_points=points,
            style_applied=style,
            duration_original=original_duration,
            duration_final=final_duration,
        )

    def _build_filter_complex(self, points: List[SpeedPoint], duration: float) -> str:
        """
        Build FFmpeg filter_complex string for speed ramping.

        Creates segments with trim+setpts, adds motion blur on transitions,
        and concatenates everything into [vout].
        """
        if not points:
            return "[0:v]copy[vout]"

        filter_parts: List[str] = []
        segment_labels: List[str] = []

        # Create segments for each interval
        for i, point in enumerate(points):
            # Determine segment end time
            if i + 1 < len(points):
                next_time = points[i + 1].time
            else:
                next_time = duration

            seg_duration = next_time - point.time
            if seg_duration <= 0:
                continue

            label = f"[seg{i}]"
            segment_labels.append(label)

            # Base trim and speed adjustment
            speed = point.speed
            pts_factor = 1.0 / speed if speed > 0 else 1.0

            # Check if we need motion blur for transition
            next_speed = points[i + 1].speed if i + 1 < len(points) else speed
            speed_diff = abs(next_speed - speed)
            use_mblur = point.transition > 0.1 and speed_diff > 0.3

            # Build segment filter
            seg_filter = (
                f"[0:v]trim=start={point.time}:duration={seg_duration},"
                f"setpts={pts_factor}*PTS"
            )

            if use_mblur:
                # Add motion blur interpolation for smooth transition
                seg_filter += (
                    f",minterpolate=fps=60:mi_mode=mci:"
                    f"mc_mode=aobmc:vsbmc=1,fps=30"
                )

            seg_filter += f"[{label[1:-1]}]"
            filter_parts.append(seg_filter)

        if not segment_labels:
            return "[0:v]copy[vout]"

        # Build concat filter
        concat_inputs = "".join(segment_labels)
        concat_filter = f"{concat_inputs}concat=n={len(segment_labels)}:v=1:a=0[vout]"
        filter_parts.append(concat_filter)

        return ";".join(filter_parts)

    def _estimate_output_duration(
        self, points: List[SpeedPoint], original: float
    ) -> float:
        """Estimate the output duration after speed ramping."""
        if not points:
            return original

        total = 0.0
        for i, point in enumerate(points):
            # Determine segment end
            if i + 1 < len(points):
                next_time = points[i + 1].time
            else:
                next_time = original

            seg_duration = next_time - point.time
            if seg_duration > 0 and point.speed > 0:
                total += seg_duration / point.speed

        return total

    def _infer_style(self, mood: str) -> RampStyle:
        """Infer RampStyle from mood string."""
        mood_lower = mood.lower()
        if mood_lower == "inspirational":
            return RampStyle.CINEMATIC
        elif mood_lower == "dramatic":
            return RampStyle.DRAMATIC
        elif mood_lower == "hype":
            return RampStyle.HYPE
        elif mood_lower == "educational":
            return RampStyle.SUBTLE
        else:
            return RampStyle.SUBTLE

    async def _get_video_duration(self, video_path: Path) -> float:
        """Get video duration using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.warning(f"ffprobe failed, defaulting to 30s duration")
            return 30.0

        try:
            duration = float(stdout.decode().strip())
            return duration
        except (ValueError, TypeError):
            logger.warning(f"Could not parse duration, defaulting to 30s")
            return 30.0


# Module-level singleton
speed_ramp_service = SpeedRampService()

__all__ = [
    "SpeedRampService",
    "SpeedRampResult",
    "RampStyle",
    "SpeedPoint",
    "speed_ramp_service",
]
