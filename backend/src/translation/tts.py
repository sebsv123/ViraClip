"""
Text-to-speech synthesis module using Coqui TTS.

Provides fully local speech synthesis with per-language models.
Falls back to pyttsx3 if Coqui TTS is unavailable.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Mapping of language code → lightest available Coqui TTS model
TTS_MODELS: Dict[str, str] = {
    "es": "tts_models/es/css10/vits",
    "en": "tts_models/en/ljspeech/vits",
    "fr": "tts_models/fr/css10/vits",
    "de": "tts_models/de/thorsten/vits",
    "pt": "tts_models/pt/cv/vits",
    "it": "tts_models/it/mai_female/vits",
    "ja": "tts_models/ja/kokoro/tacotron2-DDC",
}

# Singleton cache: language → loaded TTS instance
_tts_cache: Dict[str, object] = {}


def _load_tts_model(language: str) -> Optional[object]:
    """Load (and cache) the Coqui TTS model for *language*."""
    if language in _tts_cache:
        return _tts_cache[language]

    try:
        from TTS.api import TTS as CoquiTTS  # type: ignore[import-untyped]

        model_name = TTS_MODELS.get(language)
        if not model_name:
            logger.warning("No TTS model configured for language '%s'", language)
            return None

        logger.info("Loading Coqui TTS model '%s' …", model_name)
        tts = CoquiTTS(model_name=model_name, progress_bar=False, gpu=False)
        _tts_cache[language] = tts
        logger.info("Coqui TTS model '%s' loaded", model_name)
        return tts
    except Exception as exc:
        logger.warning("Failed to load Coqui TTS model for '%s': %s", language, exc)
        return None


def adjust_audio_speed(audio_path: Path, target_duration: float) -> Path:
    """
    Stretch or compress *audio_path* so its duration matches *target_duration*
    seconds, without changing pitch (uses the ffmpeg *atempo* filter).

    Returns the path to the adjusted file (a new temporary WAV alongside the
    original), or the original path unchanged when adjustment is not needed.
    """
    if target_duration <= 0:
        return audio_path

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        current_duration = float(result.stdout.strip())
    except Exception as exc:
        logger.warning("Could not determine audio duration: %s", exc)
        return audio_path

    if abs(current_duration - target_duration) < 0.05:
        return audio_path

    speed_ratio = current_duration / target_duration
    # atempo supports 0.5–2.0; chain filters for extreme ratios
    tempo_filters = _build_atempo_chain(speed_ratio)
    if not tempo_filters:
        return audio_path

    adjusted_path = audio_path.with_suffix(".adjusted.wav")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-filter:a",
                ",".join(tempo_filters),
                str(adjusted_path),
            ],
            capture_output=True,
            check=True,
            timeout=120,
        )
        return adjusted_path
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "ffmpeg atempo adjustment failed: %s — using original", exc.stderr
        )
        return audio_path


def _build_atempo_chain(ratio: float) -> list[str]:
    """
    Build a chain of atempo filters to handle ratios outside the 0.5–2.0 range.
    Returns an empty list when the ratio is outside a reasonable range.
    """
    if ratio <= 0.1 or ratio >= 10.0:
        return []

    filters: list[str] = []
    remaining = ratio

    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0

    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5

    filters.append(f"atempo={remaining:.6f}")
    return filters


def _synthesize_with_pyttsx3(text: str, output_path: Path) -> bool:
    """Fallback TTS using pyttsx3."""
    try:
        import pyttsx3  # type: ignore[import-untyped]

        engine = pyttsx3.init()
        engine.save_to_file(text, str(output_path))
        engine.runAndWait()
        return True
    except Exception as exc:
        logger.warning("pyttsx3 fallback failed: %s", exc)
        return False


def synthesize_speech(
    text: str,
    language: str,
    output_path: Path,
    speed: float = 1.0,
    original_duration: Optional[float] = None,
) -> Path:
    """
    Synthesize *text* in *language* and write a WAV file to *output_path*.

    If *original_duration* is given, the resulting audio is speed-adjusted so
    it fits within that time window (avoids lip-sync desynchronisation).

    Returns the path to the synthesized (and possibly speed-adjusted) WAV file.
    Falls back to pyttsx3 when Coqui TTS is unavailable, and raises
    RuntimeError only when both engines fail.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tts = _load_tts_model(language)
    success = False

    if tts is not None:
        try:
            tts.tts_to_file(text=text, file_path=str(output_path))
            success = True
        except Exception as exc:
            logger.warning(
                "Coqui TTS synthesis failed for language '%s': %s — trying fallback",
                language,
                exc,
            )

    if not success:
        # Try Japanese multilingual fallback
        if language == "ja" and "ja" in TTS_MODELS:
            try:
                from TTS.api import TTS as CoquiTTS  # type: ignore[import-untyped]

                fallback_model = "tts_models/multilingual/multi-dataset/xtts_v2"
                logger.info("Trying multilingual fallback for Japanese: %s", fallback_model)
                tts_ml = CoquiTTS(model_name=fallback_model, progress_bar=False, gpu=False)
                tts_ml.tts_to_file(text=text, file_path=str(output_path), language="ja")
                success = True
            except Exception as exc2:
                logger.warning("Multilingual TTS fallback also failed: %s", exc2)

    if not success:
        logger.warning(
            "All Coqui TTS models failed for '%s'; using pyttsx3 fallback", language
        )
        success = _synthesize_with_pyttsx3(text, output_path)

    if not success:
        raise RuntimeError(
            f"All TTS engines failed for language '{language}'. "
            "Install 'TTS' (Coqui) or 'pyttsx3' to enable speech synthesis."
        )

    if original_duration is not None and original_duration > 0:
        output_path = adjust_audio_speed(output_path, original_duration)

    return output_path
