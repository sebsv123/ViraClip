"""
TTS Narration Service — Phase 3.4
===================================
Local Coqui XTTS v2 for AI narrator voiceovers.
Applied when source audio SNR is below threshold or narration explicitly requested.

Models:
  - xtts-v2  (tts_models/multilingual/multi-dataset/xtts_v2)  ~3.5 GB VRAM / CPU
  - tortoise  (tortoise-tts)  high quality, very slow
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TTS_MODEL       = os.environ.get("TTS_MODEL", "xtts-v2")
TTS_CACHE_DIR   = Path(os.environ.get("TTS_CACHE_DIR", "/app/models/tts"))
TEMP_DIR        = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads"))
TTS_SNR_THRESH  = float(os.environ.get("TTS_SNR_THRESHOLD_DB", "15.0"))   # below → consider narration

_LOADED: Dict[str, Any] = {}


def _load_xtts():
    """Lazy-load Coqui XTTS v2 (cached in module)."""
    if "xtts" in _LOADED:
        return _LOADED["xtts"]

    logger.info("[TTS] Loading Coqui XTTS v2 …")
    from TTS.api import TTS
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tts = TTS(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        gpu=(device == "cuda"),
    )
    TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _LOADED["xtts"] = tts
    logger.info(f"[TTS] XTTS v2 loaded on {device}.")
    return tts


class TTSService:
    """
    Generate speech audio from text using Coqui XTTS v2.

    Usage:
        service = TTSService()
        result  = await service.synthesize(text="Hello world!", language="en")
        # → {"audio_path": "/tmp/tts_xxx.wav", "duration": 2.3, "language": "en"}
    """

    SUPPORTED_LANGUAGES = [
        "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
        "nl", "cs", "ar", "zh-cn", "ja", "ko", "hu",
    ]

    def __init__(self):
        self.out_dir = TEMP_DIR / "tts_outputs"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def synthesize(
        self,
        text: str,
        speaker_sample: Optional[str] = None,
        language: str = "en",
        model: str = TTS_MODEL,
        output_path: Optional[str] = None,
        speed: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Synthesise *text* to a WAV audio file.

        Args:
            text:           Text to synthesise (max ~500 words per call)
            speaker_sample: Path to 3–10s WAV sample for voice cloning (optional)
            language:       ISO language code (see SUPPORTED_LANGUAGES)
            model:          "xtts-v2" | "tortoise"
            output_path:    Desired output .wav path (auto-generated if None)
            speed:          Speech rate multiplier (0.5–2.0)

        Returns:
            {"audio_path": str, "duration": float, "language": str}
        """
        if language not in self.SUPPORTED_LANGUAGES:
            logger.warning(f"[TTS] Unsupported language '{language}', defaulting to 'en'")
            language = "en"

        if output_path is None:
            output_path = str(self.out_dir / f"tts_{int(time.time())}.wav")

        dest = Path(output_path)
        loop = asyncio.get_event_loop()

        await loop.run_in_executor(
            None,
            self._synthesize_sync,
            text, speaker_sample, language, dest, speed,
        )

        duration = self._get_duration(dest)
        logger.info(f"[TTS] ✓ Synthesised {dest.name} ({duration:.1f}s, lang={language})")
        return {"audio_path": str(dest), "duration": duration, "language": language}

    async def synthesize_batch(
        self,
        texts: List[str],
        language: str = "en",
        speaker_sample: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Synthesise multiple texts sequentially, returning a list of results."""
        results = []
        for text in texts:
            try:
                r = await self.synthesize(text, speaker_sample=speaker_sample, language=language)
                results.append(r)
            except Exception as exc:
                logger.warning(f"[TTS] Batch item failed: {exc}")
                results.append({"audio_path": None, "duration": 0.0, "language": language})
        return results

    @staticmethod
    def is_available() -> bool:
        """True if Coqui TTS is installed and importable."""
        try:
            import TTS  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Sync internals ────────────────────────────────────────────────────────

    def _synthesize_sync(
        self,
        text: str,
        speaker_sample: Optional[str],
        language: str,
        dest: Path,
        speed: float,
    ) -> None:
        tts = _load_xtts()
        dest.parent.mkdir(parents=True, exist_ok=True)

        kwargs: Dict[str, Any] = {
            "text":      text,
            "language":  language,
            "file_path": str(dest),
            "speed":     speed,
        }
        if speaker_sample and Path(speaker_sample).exists():
            kwargs["speaker_wav"] = speaker_sample
        else:
            kwargs["speaker"] = "Ana Florence"   # default built-in speaker

        tts.tts_to_file(**kwargs)

    @staticmethod
    def _get_duration(path: Path) -> float:
        """Return WAV duration in seconds via ffprobe (fallback: 0.0)."""
        try:
            import subprocess, json
            out = subprocess.check_output(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", str(path)],
                stderr=subprocess.DEVNULL,
            )
            streams = json.loads(out).get("streams", [])
            if streams:
                return float(streams[0].get("duration", 0))
        except Exception:
            pass
        return 0.0


# ── Convenience: SNR-based narration gate ────────────────────────────────────

async def maybe_add_narration(
    video_path: Path,
    segment_text: str,
    output_path: Path,
    language: str = "en",
    snr_threshold: float = TTS_SNR_THRESH,
) -> bool:
    """
    Add AI narration to *video_path* if the audio SNR is below *snr_threshold*.
    Returns True if narration was injected, False if skipped.
    """
    if not TTSService.is_available():
        return False

    try:
        from ..video_processing.audio_analysis import measure_snr
        snr = await measure_snr(str(video_path))
        if snr >= snr_threshold:
            logger.debug(f"[TTS] SNR={snr:.1f}dB ≥ threshold={snr_threshold} — skipping narration")
            return False
    except Exception:
        return False

    try:
        svc = TTSService()
        result = await svc.synthesize(segment_text, language=language)
        audio_path = result.get("audio_path")
        if not audio_path or not Path(audio_path).exists():
            return False

        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", audio_path,
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first:weights=0.6 0.4[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"[TTS] ✓ Narration injected (SNR was {snr:.1f}dB < {snr_threshold}dB)")
        return True
    except Exception as exc:
        logger.warning(f"[TTS] Narration injection failed: {exc}")
        return False
