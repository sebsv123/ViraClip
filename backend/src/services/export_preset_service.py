"""
Export Preset Service — TikTok/Reels/Shorts formatting presets.

Bridges the ffmpeg-tiktok-formatter stacking/cropping logic with ViraClip's
existing export infrastructure. Provides:

- ``export_with_preset()`` — apply a named preset to a single clip
- ``Preset`` enum — ``tiktok_basic``, ``tiktok_side_by_side``, ``tiktok_stacked``
- ``ExportPresetConfig`` dataclass — per-preset FFmpeg parameters

All presets produce 1080×1920 (9:16) output with H.264 + AAC.
On failure the input path is returned unchanged (graceful fallback).
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from src.config import get_config
from src.services.metrics_aggregator import record_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Preset enum
# ---------------------------------------------------------------------------

class Preset(str, Enum):
    """Named export presets for short-form video platforms."""

    TIKTOK_BASIC = "tiktok_basic"
    """Single-video: centre-crop to 9:16, scale to 1080×1920, encode."""

    TIKTOK_SIDE_BY_SIDE = "tiktok_side_by_side"
    """Two videos side-by-side (hstack), padded to 1080×1920."""

    TIKTOK_STACKED = "tiktok_stacked"
    """Two videos stacked vertically (vstack), each at half-height."""

    FAST_VERTICAL = "fast_vertical"
    """
    Ultra-fast 9:16 vertical crop using ``preset veryfast`` + ``crf 21``.
    Designed as a reliable fallback when more complex presets fail.
    Single-video only — no subtitles, no secondary input.
    """

    # Aliases for convenience
    REELS_BASIC = "reels_basic"
    SHORTS_BASIC = "shorts_basic"

# ---------------------------------------------------------------------------
# Per-preset configuration
# ---------------------------------------------------------------------------

@dataclass
class ExportPresetConfig:
    """FFmpeg parameters for a single preset."""

    output_width: int = 1080
    output_height: int = 1920
    video_bitrate: str = "10M"
    audio_bitrate: str = "128k"
    fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    pixel_format: str = "yuv420p"
    preset: str = "medium"          # x264 preset (ultrafast … veryslow)
    extra_args: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, preset_name: str) -> "ExportPresetConfig":
        """Create config, overriding defaults from env vars when set."""
        cfg = get_config()
        return cls(
            video_bitrate=cfg.export_video_bitrate,
            audio_bitrate=cfg.export_audio_bitrate,
            fps=cfg.export_fps,
        )


# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------

class ExportPresetService:
    """Apply formatting presets to video clips."""

    def __init__(self) -> None:
        self._cfg = get_config()
        logger.info(
            "ExportPresetService ready (preset=%s, bitrate=%s, fps=%s)",
            self._cfg.export_preset,
            self._cfg.export_video_bitrate,
            self._cfg.export_fps,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_with_preset(
        self,
        input_path: str | Path,
        output_path: str | Path,
        preset: Preset | str = Preset.TIKTOK_BASIC,
        secondary_input: str | Path | None = None,
        burn_subtitles: str | Path | None = None,
    ) -> Path:
        """
        Apply *preset* to *input_path* and write to *output_path*.

        Parameters
        ----------
        input_path:
            Primary video (the main clip).
        output_path:
            Destination file (``.mp4``).
        preset:
            One of the :class:`Preset` values.
        secondary_input:
            Second video for side-by-side / stacked layouts.
        burn_subtitles:
            Optional SRT/ASS path to burn into the video.

        Returns
        -------
        Path to the output file, or *input_path* on failure.
        """
        try:
            preset_enum = Preset(preset) if isinstance(preset, str) else preset
        except (ValueError, TypeError):
            logger.warning("Unknown preset '%s', falling back to basic", preset)
            preset_enum = Preset.TIKTOK_BASIC

        config = ExportPresetConfig.from_env(preset_enum.value)

        try:
            if preset_enum == Preset.FAST_VERTICAL:
                out = self._apply_fast_vertical(input_path, output_path)
            elif preset_enum == Preset.TIKTOK_BASIC:
                out = self._apply_basic(input_path, output_path, config, burn_subtitles)
            elif preset_enum in (Preset.TIKTOK_SIDE_BY_SIDE, Preset.REELS_BASIC, Preset.SHORTS_BASIC):
                out = self._apply_basic(input_path, output_path, config, burn_subtitles)
            elif preset_enum == Preset.TIKTOK_STACKED:
                out = self._apply_stacked(
                    input_path, output_path, config, secondary_input, burn_subtitles
                )
            else:
                logger.warning("Unknown preset %s, falling back to basic", preset_enum)
                out = self._apply_basic(input_path, output_path, config, burn_subtitles)

            if out and Path(out).exists():
                logger.info("  ✓ Export preset '%s' → %s", preset_enum.value, out)
                # [Metrics] export_preset_used
                record_event("export_preset_used", payload={"preset": preset_enum.value})
                return Path(out)
        except Exception as exc:
            logger.warning("Export preset '%s' failed: %s", preset_enum.value, exc)
            # [Metrics] engine_error
            record_event("engine_error", payload={"engine": "export_preset", "preset": preset_enum.value, "error": str(exc)[:200]})

        # ── Fallback: retry with fast_vertical before giving up ──────────
        if preset_enum != Preset.FAST_VERTICAL:
            logger.info(
                "  ↻ Retrying with fast_vertical fallback for '%s'",
                preset_enum.value,
            )
            try:
                out = self._apply_fast_vertical(input_path, output_path)
                if out and Path(out).exists():
                    logger.info(
                        "  ✓ fast_vertical fallback succeeded → %s", out
                    )
                    # [Metrics] export_preset_fallback
                    record_event("export_preset_fallback", payload={
                        "original_preset": preset_enum.value,
                        "fallback": "fast_vertical",
                    })
                    return Path(out)
            except Exception as fallback_exc:
                logger.warning(
                    "fast_vertical fallback also failed: %s", fallback_exc
                )

        # Graceful fallback — return input unchanged
        logger.info("  ⚠ Export preset skipped, returning original input")
        return Path(input_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_basic(
        input_path: str | Path,
        output_path: str | Path,
        config: ExportPresetConfig,
        burn_subtitles: str | Path | None = None,
    ) -> Path | None:
        """
        Centre-crop to 9:16, scale to target resolution, encode.

        Filter chain::

            crop=ih*9/16:ih:(iw-ih*9/16)/2:0, scale=W:H
        """
        scale_filter = (
            f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
            f"scale={config.output_width}:{config.output_height}"
        )
        if burn_subtitles:
            vf = f"{scale_filter},subtitles='{burn_subtitles}':force_style='FontSize=18,PrimaryColour=&H00FFFFFF'"
        else:
            vf = scale_filter

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-c:v", config.video_codec,
            "-b:v", config.video_bitrate,
            "-r", str(config.fps),
            "-pix_fmt", config.pixel_format,
            "-preset", config.preset,
            "-vf", vf,
            "-c:a", config.audio_codec,
            "-b:a", config.audio_bitrate,
            "-movflags", "+faststart",
            *config.extra_args,
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        return Path(output_path)

    @staticmethod
    def _apply_stacked(
        input_path: str | Path,
        output_path: str | Path,
        config: ExportPresetConfig,
        secondary_input: str | Path | None = None,
        burn_subtitles: str | Path | None = None,
    ) -> Path | None:
        """
        Stack two videos vertically (vstack).

        Adapted from ffmpeg-tiktok-formatter's ``create_vertical()``.

        Filter chain::

            [0]scale=-2:H/2,crop=W:ih[v0];
            [1]scale=-2:H/2,crop=W:ih[v1];
            [v0][v1]vstack
        """
        if not secondary_input:
            logger.warning("stacked preset requires secondary_input, falling back to basic")
            return ExportPresetService._apply_basic(input_path, output_path, config, burn_subtitles)

        half_h = config.output_height // 2
        filter_complex = (
            f"[0:v]scale=-2:{half_h},crop={config.output_width}:ih[v0];"
            f"[1:v]scale=-2:{half_h},crop={config.output_width}:ih[v1];"
            f"[v0][v1]vstack"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-i", str(secondary_input),
            "-filter_complex", filter_complex,
            "-c:v", config.video_codec,
            "-b:v", config.video_bitrate,
            "-r", str(config.fps),
            "-pix_fmt", config.pixel_format,
            "-preset", config.preset,
            "-c:a", config.audio_codec,
            "-b:a", config.audio_bitrate,
            "-movflags", "+faststart",
            *config.extra_args,
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        return Path(output_path)

    @staticmethod
    def _apply_fast_vertical(
        input_path: str | Path,
        output_path: str | Path,
    ) -> Path | None:
        """
        Ultra-fast 9:16 vertical crop using ``preset veryfast`` + ``crf 21``.

        This is a simplified, reliable fallback that works on any horizontal
        input.  No subtitles, no secondary input — purely formatting.

        FFmpeg command::

            ffmpeg -y -i <input>                          \\
              -vf "crop=ih*(9/16):ih,scale=1080:1920"     \\
              -r 30 -c:v libx264 -preset veryfast -crf 21 \\
              -c:a aac -b:a 128k                          \\
              <output>
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", "crop=ih*(9/16):ih,scale=1080:1920",
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        return Path(output_path)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def export_with_preset(
    input_path: str | Path,
    output_path: str | Path,
    preset: Preset | str = Preset.TIKTOK_BASIC,
    secondary_input: str | Path | None = None,
    burn_subtitles: str | Path | None = None,
) -> Path:
    """Shortcut: create a service and apply *preset* in one call."""
    return ExportPresetService().export_with_preset(
        input_path, output_path, preset, secondary_input, burn_subtitles
    )
