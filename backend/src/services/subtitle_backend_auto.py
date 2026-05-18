"""
Subtitle Backend — Auto-Subtitle Adapter
=========================================

Adapter that wraps the core logic from m1guelpf/auto-subtitle (MIT license)
into a clean Python API for ViraClip's caption pipeline.

Uses Whisper directly for transcription and FFmpeg for subtitle burn-in,
without depending on the auto-subtitle CLI.

License notice:
  Portions of this code are derived from auto-subtitle
  (https://github.com/m1guelpf/auto-subtitle), MIT License.
  Copyright (c) 2022 Miguel Piedrafita <soy@miguelpiedrafita.com>
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src import gpu_utils

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SRT helpers (ported from auto-subtitle/utils.py)
# ---------------------------------------------------------------------------

def _format_timestamp(seconds: float, always_include_hours: bool = False) -> str:
    """Format seconds as SRT timestamp HH:MM:SS,mmm."""
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)

    hours = milliseconds // 3_600_000
    milliseconds -= hours * 3_600_000

    minutes = milliseconds // 60_000
    milliseconds -= minutes * 60_000

    secs = milliseconds // 1_000
    milliseconds -= secs * 1_000

    hours_marker = f"{hours:02d}:" if always_include_hours or hours > 0 else ""
    return f"{hours_marker}{minutes:02d}:{secs:02d},{milliseconds:03d}"


def _write_srt(segments: List[Dict[str, Any]], file_path: Path) -> None:
    """Write Whisper segments to an SRT file."""
    with open(file_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            f.write(
                f"{i}\n"
                f"{_format_timestamp(segment['start'], always_include_hours=True)} --> "
                f"{_format_timestamp(segment['end'], always_include_hours=True)}\n"
                f"{segment['text'].strip().replace('-->', '->')}\n\n"
            )


# ---------------------------------------------------------------------------
# Audio extraction (ported from auto-subtitle/cli.py)
# ---------------------------------------------------------------------------

async def _extract_audio(video_path: Path, output_wav: Path) -> bool:
    """Extract mono 16kHz WAV audio from video using FFmpeg.

    Audio sync fix (from auto-subtitle issues #32, #33):
      - ``-async 1``  : resamples audio to a constant rate, fixing desync
        caused by variable frame rate (VFR) source videos.
      - ``-max_muxing_queue_size 1024`` : prevents muxing queue overflow
        errors on long or complex encodes.
    """
    import ffmpeg  # noqa: F811
    try:
        (
            ffmpeg
            .input(str(video_path))
            .output(
                str(output_wav),
                acodec="pcm_s16le", ac=1, ar="16k",
                **{"async": "1", "max_muxing_queue_size": "1024"},
            )
            .run(quiet=True, overwrite_output=True)
        )
        return True
    except Exception as exc:
        logger.error("[auto_sub] Audio extraction failed for %s: %s", video_path.name, exc)
        return False


# ---------------------------------------------------------------------------
# Main adapter class
# ---------------------------------------------------------------------------

class AutoSubtitleBackend:
    """
    Adapter that wraps Whisper transcription + FFmpeg subtitle burn-in.

    This class provides two main methods:
      - ``generate_subtitles(video_path, lang, task)`` → Path to SRT file
      - ``burn_subtitles(video_path, srt_path, output_path, style_preset)`` → Path

    It degrades gracefully: if Whisper is not installed or transcription fails,
    it logs a clear warning and returns None so callers can fall back.
    """

    def __init__(
        self,
        model_name: str = "small",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ):
        """
        Args:
            model_name: Whisper model name (e.g. "tiny", "small", "medium", "large").
            device: "cpu", "cuda", or None for auto-detect.
            compute_type: "float16", "int8", or None for auto-detect.
        """
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._model = None  # lazy-loaded

    # ── Public API ────────────────────────────────────────────────────────

    async def generate_subtitles(
        self,
        video_path: Path,
        lang: str = "auto",
        task: str = "transcribe",
    ) -> Optional[Path]:
        """
        Transcribe a video file and produce an SRT subtitle file.

        Args:
            video_path: Path to the input video.
            lang: Language code ("auto" for auto-detect, or e.g. "en", "es").
            task: "transcribe" (X→X) or "translate" (X→en).

        Returns:
            Path to the generated .srt file, or None on failure.
        """
        if not video_path.exists():
            logger.error("[auto_sub] Video not found: %s", video_path)
            return None

        # 1. Extract audio to temp WAV
        tmp_wav = Path(tempfile.gettempdir()) / f"{video_path.stem}_audio.wav"
        try:
            ok = await _extract_audio(video_path, tmp_wav)
            if not ok:
                return None
        except Exception as exc:
            logger.error("[auto_sub] Audio extraction error: %s", exc)
            return None

        # 2. Transcribe with Whisper
        try:
            result = await self._transcribe(tmp_wav, lang=lang, task=task)
        except Exception as exc:
            logger.error("[auto_sub] Whisper transcription failed: %s", exc)
            return None
        finally:
            # Clean up temp WAV
            try:
                tmp_wav.unlink(missing_ok=True)
            except Exception:
                pass

        if not result or "segments" not in result:
            logger.warning("[auto_sub] Whisper returned no segments")
            return None

        # 3. Write SRT
        srt_path = video_path.with_suffix(".srt")
        try:
            _write_srt(result["segments"], srt_path)
            logger.info(
                "[auto_sub] Generated SRT (%d segments) → %s",
                len(result["segments"]), srt_path.name,
            )
            return srt_path
        except Exception as exc:
            logger.error("[auto_sub] Failed to write SRT: %s", exc)
            return None

    async def burn_subtitles(
        self,
        video_path: Path,
        srt_path: Path,
        output_path: Path,
        style_preset: str = "default",
    ) -> Optional[Path]:
        """
        Burn subtitles from an SRT file into a video using FFmpeg.

        Args:
            video_path: Input video.
            srt_path: Path to the .srt subtitle file.
            output_path: Where to write the subtitled video.
            style_preset: Visual style preset name (see _STYLE_MAP).

        Returns:
            output_path on success, None on failure.
        """
        if not video_path.exists():
            logger.error("[auto_sub] Video not found: %s", video_path)
            return None
        if not srt_path.exists():
            logger.error("[auto_sub] SRT not found: %s", srt_path)
            return None

        # Map style preset to FFmpeg subtitle filter options
        style_opts = _STYLE_MAP.get(style_preset, _STYLE_MAP["default"])

        try:
            import ffmpeg  # noqa: F811

            safe_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
            vf = f"subtitles='{safe_srt}':force_style='{style_opts}'"

            (
                ffmpeg
                .input(str(video_path))
                .output(
                    str(output_path),
                    vf=vf,
                    **gpu_utils.ffmpeg_codec_flags("high"),
                    acodec="copy",
                )
                .run(quiet=True, overwrite_output=True)
            )

            logger.info("[auto_sub] Burned subtitles → %s", output_path.name)
            return output_path

        except Exception as exc:
            logger.error("[auto_sub] FFmpeg burn-in failed: %s", exc)
            return None

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _transcribe(
        self,
        audio_path: Path,
        lang: str = "auto",
        task: str = "transcribe",
    ) -> Optional[Dict[str, Any]]:
        """Run Whisper transcription on an audio file."""
        model = self._load_model()
        if model is None:
            return None

        transcribe_kwargs: Dict[str, Any] = {
            "task": task,
            # Enable word-level timestamps for better sync accuracy
            # (from auto-subtitle issue #84 / whisper discussion #1888)
            "word_timestamps": True,
        }

        # Handle English-only models
        if self._model_name.endswith(".en"):
            warnings.warn(
                f"{self._model_name} is an English-only model, forcing English detection."
            )
            transcribe_kwargs["language"] = "en"
        elif lang != "auto":
            transcribe_kwargs["language"] = lang

        # Run transcription in a thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            result = await loop.run_in_executor(
                None,
                lambda: model.transcribe(str(audio_path), **transcribe_kwargs),
            )

        return result

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._model is not None:
            return self._model

        try:
            import whisper  # noqa: F811
        except ImportError:
            logger.error(
                "[auto_sub] openai-whisper is not installed. "
                "Install it with: pip install openai-whisper"
            )
            return None

        try:
            logger.info("[auto_sub] Loading Whisper model '%s' ...", self._model_name)
            self._model = whisper.load_model(self._model_name)
            logger.info("[auto_sub] Whisper model '%s' loaded.", self._model_name)
            return self._model
        except Exception as exc:
            logger.error("[auto_sub] Failed to load Whisper model '%s': %s",
                         self._model_name, exc)
            return None


# ---------------------------------------------------------------------------
# FFmpeg subtitle style presets (for burn_subtitles)
# ---------------------------------------------------------------------------
# These map to FFmpeg's force_style parameter for the subtitles filter.
# The format is a comma-separated list of ASS-style overrides.
#
# Reference: https://ffmpeg.org/ffmpeg-filters.html#subtitles

_STYLE_MAP: Dict[str, str] = {
    "default": (
        "FontName=TikTokSans-Bold,FontSize=18,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H40000000,"
        "BorderStyle=3,Outline=1,Shadow=0,"
        "Alignment=2,MarginV=24"
    ),
    "tiktok": (
        "FontName=TikTokSans-Bold,FontSize=20,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H40000000,"
        "BorderStyle=3,Outline=2,Shadow=0,"
        "Alignment=2,MarginV=28"
    ),
    "minimal": (
        "FontName=Montserrat-Bold,FontSize=16,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H40000000,"
        "BorderStyle=3,Outline=1,Shadow=0,"
        "Alignment=2,MarginV=20"
    ),
    "high_contrast": (
        "FontName=TikTokSans-Bold,FontSize=20,"
        "PrimaryColour=&H0000FFFF,OutlineColour=&H40000000,"
        "BorderStyle=3,Outline=3,Shadow=0,"
        "Alignment=2,MarginV=28"
    ),
}


# ---------------------------------------------------------------------------
# Singleton / factory
# ---------------------------------------------------------------------------

_backend_instance: Optional[AutoSubtitleBackend] = None


def get_auto_subtitle_backend(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
) -> AutoSubtitleBackend:
    """Get or create the singleton AutoSubtitleBackend instance."""
    global _backend_instance
    if _backend_instance is None:
        from src.config import get_config
        cfg = get_config()
        _backend_instance = AutoSubtitleBackend(
            model_name=model_name or getattr(cfg, "caption_model", "small"),
            device=device or os.getenv("WHISPER_DEVICE", "cpu"),
        )
    return _backend_instance
