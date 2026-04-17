"""
SFX Auto Service — Automatic SFX overlay on video clips using FFmpeg amix.
NO GPU. Never crashes the pipeline — always returns a valid path even on error.
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


SFX_LIBRARY: Dict[str, str] = {
    "whoosh_fast": "sfx/whoosh_fast.wav",
    "whoosh_soft": "sfx/whoosh_soft.wav",
    "impact_heavy": "sfx/impact_heavy.wav",
    "impact_light": "sfx/impact_light.wav",
    "clap": "sfx/clap.wav",
    "riser": "sfx/riser.wav",
    "drum_hit": "sfx/drum_hit.wav",
    "glitch": "sfx/glitch.wav",
    "cash_register": "sfx/cash_register.wav",
    "notification": "sfx/notification.wav",
}


@dataclass
class SFXEvent:
    sfx_name: str
    timestamp: float
    volume: float
    fade_in: float
    fade_out: float


MOOD_SFX_MAP: Dict[str, List[SFXEvent]] = {
    "inspirational": [
        SFXEvent("riser", 0.5, 0.4, 0.1, 0.3),
        SFXEvent("impact_light", 4.5, 0.6, 0.05, 0.2),
    ],
    "dramatic": [
        SFXEvent("whoosh_fast", 0.2, 0.7, 0.0, 0.1),
        SFXEvent("impact_heavy", 3.0, 0.8, 0.0, 0.3),
        SFXEvent("riser", 14.0, 0.5, 0.2, 0.5),
    ],
    "hype": [
        SFXEvent("drum_hit", 0.0, 0.7, 0.0, 0.1),
        SFXEvent("whoosh_fast", 7.8, 0.8, 0.0, 0.05),
        SFXEvent("impact_heavy", 8.0, 0.9, 0.0, 0.2),
    ],
    "educational": [
        SFXEvent("notification", 0.3, 0.3, 0.05, 0.3),
    ],
}


class SFXAutoService:
    """
    Automatic SFX overlay service using FFmpeg amix.
    CPU-only, never crashes the pipeline.
    """

    def __init__(self, sfx_base_path: str = "static"):
        self.sfx_base_path = Path(sfx_base_path)

    async def apply_sfx(
        self,
        input_path: Path,
        output_path: Path,
        mood: str,
        clip_duration: float = 30.0,
        custom_events: Optional[List[SFXEvent]] = None,
    ) -> str:
        """
        Apply SFX overlay to a video clip.

        Args:
            input_path: Source video file
            output_path: Destination for SFX-enhanced video
            mood: Preset key from MOOD_SFX_MAP
            clip_duration: Actual clip duration for validation
            custom_events: Optional custom SFX events (overrides mood)

        Returns:
            output_path on success, input_path on failure (never raises)
        """
        input_path = Path(input_path)
        output_path = Path(output_path)

        # Get SFX events
        if custom_events:
            events = custom_events
        else:
            events = MOOD_SFX_MAP.get(mood, [])

        if not events:
            logger.debug(f"[SFX] No events for mood '{mood}', returning input unchanged")
            return str(input_path)

        # Validate events and filter out invalid ones
        valid_events: List[SFXEvent] = []
        for event in events:
            # Check SFX name exists in library
            if event.sfx_name not in SFX_LIBRARY:
                logger.debug(f"[SFX] Unknown sfx_name '{event.sfx_name}', skipping")
                continue

            # Check timestamp is within clip duration
            if event.timestamp >= clip_duration:
                logger.debug(f"[SFX] Event at {event.timestamp}s exceeds duration {clip_duration}s, skipping")
                continue

            # Check file exists
            sfx_file = self.sfx_base_path / SFX_LIBRARY[event.sfx_name]
            if not sfx_file.exists():
                logger.debug(f"[SFX] File not found: {sfx_file}, skipping")
                continue

            valid_events.append(event)

        if not valid_events:
            logger.debug(f"[SFX] No valid events after validation, returning input unchanged")
            return str(input_path)

        # Build FFmpeg command
        filter_complex = self._build_sfx_filter(valid_events)
        n_inputs = 1 + len(valid_events)  # video + all sfx files

        cmd: List[str] = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),
        ]

        # Add SFX files as additional inputs
        for event in valid_events:
            sfx_file = self.sfx_base_path / SFX_LIBRARY[event.sfx_name]
            cmd.extend(["-i", str(sfx_file)])

        # Add filter and output settings
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "0:v",  # Copy video from input
            "-map", "[aout]",  # Use mixed audio
            "-c:v", "copy",  # No video re-encode
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path),
        ])

        logger.info(f"[SFX] Applying {len(valid_events)} SFX to {input_path.name} (mood={mood})")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="ignore")[-200:]
                logger.warning(f"[SFX] FFmpeg failed, returning input: {stderr_text}")
                return str(input_path)

            logger.info(f"[SFX] Success: {output_path.name}")
            return str(output_path)

        except Exception as e:
            logger.warning(f"[SFX] Exception during processing, returning input: {e}")
            return str(input_path)

    def _build_sfx_filter(self, events: List[SFXEvent]) -> str:
        """
        Build FFmpeg filter_complex string for SFX mixing.

        Format:
          [1:a]adelay=500|500,volume=0.4,afade=t=in:st=0.5:d=0.1,afade=t=out:st=0.8:d=0.3[sfx0];
          [2:a]adelay=4500|4500,volume=0.6,afade=t=in:st=4.5:d=0.05,afade=t=out:st=4.7:d=0.2[sfx1];
          [0:a][sfx0][sfx1]amix=inputs=3:duration=first:dropout_transition=0[aout]
        """
        filter_parts: List[str] = []
        sfx_labels: List[str] = []

        for i, event in enumerate(events):
            # Convert seconds to milliseconds for adelay
            delay_ms = int(event.timestamp * 1000)

            # Build individual SFX processing chain
            # adelay → volume → afade(in) → afade(out)
            fade_out_start = event.timestamp + event.fade_out

            filter_chain = (
                f"[{i+1}:a]"
                f"adelay={delay_ms}|{delay_ms},"
                f"volume={event.volume},"
                f"afade=t=in:st={event.timestamp}:d={event.fade_in},"
                f"afade=t=out:st={fade_out_start}:d={event.fade_out}"
                f"[sfx{i}]"
            )
            filter_parts.append(filter_chain)
            sfx_labels.append(f"[sfx{i}]")

        # Build amix concat
        n_inputs = 1 + len(events)  # original audio + all sfx
        all_inputs = "[0:a]" + "".join(sfx_labels)
        amix_filter = (
            f"{all_inputs}"
            f"amix=inputs={n_inputs}:duration=first:dropout_transition=0"
            f"[aout]"
        )
        filter_parts.append(amix_filter)

        return ";".join(filter_parts)


# Module-level singleton
sfx_auto_service = SFXAutoService()

__all__ = [
    "SFXAutoService",
    "SFXEvent",
    "MOOD_SFX_MAP",
    "sfx_auto_service",
]
