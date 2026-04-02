"""
Video voice translation pipeline.

Steps:
  1. Extract audio from the video.
  2. Transcribe with faster-whisper (reuses existing singleton model).
  3. Detect source language from transcription metadata.
  4. Translate each segment using argostranslate.
  5. Synthesize translated speech per segment with Coqui TTS.
  6. Reconstruct the full audio track with correct timestamps.
  7. (Optional) Preserve background music by mixing at low volume.
  8. Merge translated audio track with original video.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .translator import SUPPORTED_LANGUAGES, auto_detect_language, translate_text
from .tts import synthesize_speech

logger = logging.getLogger(__name__)

# Progress step labels exposed to callers / frontend
STEP_EXTRACTING = "Extracting audio"
STEP_TRANSCRIBING = "Transcribing"
STEP_TRANSLATING = "Translating"
STEP_SYNTHESIZING = "Synthesizing voice"
STEP_MIXING = "Mixing audio"
STEP_DONE = "Done"

ProgressCallback = Callable[[str, int], None]  # (step_label, percent 0-100)


def _run_ffmpeg(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run ffmpeg with the given arguments, raising CalledProcessError on failure."""
    cmd = ["ffmpeg", "-y", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )
    return result


def _get_video_duration(video_path: Path) -> float:
    """Return the duration of *video_path* in seconds."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    """Extract the full audio track from *video_path* as a PCM WAV."""
    _run_ffmpeg(
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path),
    )


def _transcribe_audio(
    audio_path: Path,
) -> Tuple[str, List[Tuple[float, float, str]]]:
    """
    Transcribe *audio_path* using faster-whisper.

    Returns ``(detected_language, segments)`` where each segment is
    ``(start_sec, end_sec, text)``.
    """
    try:
        from ..video_processing.transcription import get_whisper_model
    except ImportError:
        # Fallback: import from the legacy location
        from ..video_utils import _get_whisper_model as get_whisper_model  # type: ignore[import-untyped]

    model = get_whisper_model()
    segments_iter, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        beam_size=5,
    )
    detected_lang: str = getattr(info, "language", "en") or "en"
    segments: List[Tuple[float, float, str]] = [
        (seg.start, seg.end, seg.text.strip())
        for seg in segments_iter
        if seg.text.strip()
    ]
    return detected_lang, segments


def _build_silent_audio(duration: float, output_path: Path) -> None:
    """Create a silent WAV file of *duration* seconds."""
    _run_ffmpeg(
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-acodec", "pcm_s16le",
        str(output_path),
    )


def _overlay_segment(
    base_path: Path,
    segment_path: Path,
    start_sec: float,
    output_path: Path,
) -> None:
    """
    Overlay *segment_path* on top of *base_path* at *start_sec* and write to
    *output_path*.  Uses ffmpeg's adelay + amix filters.
    """
    delay_ms = int(start_sec * 1000)
    _run_ffmpeg(
        "-i", str(base_path),
        "-i", str(segment_path),
        "-filter_complex",
        f"[1:a]adelay={delay_ms}|{delay_ms}[delayed];[0:a][delayed]amix=inputs=2:duration=first:dropout_transition=0[out]",
        "-map", "[out]",
        "-acodec", "pcm_s16le",
        str(output_path),
    )


def _separate_background_music(audio_path: Path, tmp_dir: Path) -> Optional[Path]:
    """
    Attempt to separate background music from voice using *demucs* or
    *audio-separator*.  Returns the path to the no-voice (accompaniment) track,
    or None if separation is unavailable.
    """
    # Try audio-separator first (lighter)
    try:
        import audio_separator.separator as _sep  # type: ignore[import-untyped]

        sep = _sep.Separator(output_dir=str(tmp_dir))
        outputs = sep.separate(str(audio_path))
        # Typically outputs accompaniment as *_(Instrumental).wav
        for out in outputs:
            if "instrumental" in Path(out).name.lower() or "accompaniment" in Path(out).name.lower():
                return Path(out)
    except Exception:
        pass

    # Try demucs
    try:
        import sys
        subprocess.run(
            [sys.executable, "-m", "demucs", "--two-stems=vocals", "-o", str(tmp_dir), str(audio_path)],
            capture_output=True,
            timeout=600,
            check=True,
        )
        # demucs outputs to <tmp_dir>/htdemucs/<stem>/<filename>
        for p in tmp_dir.rglob("no_vocals.wav"):
            return p
        for p in tmp_dir.rglob("accompaniment.wav"):
            return p
    except Exception:
        pass

    return None


def translate_video_audio(
    video_path: Path,
    target_language: str,
    output_path: Path,
    preserve_background_music: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> Path:
    """
    Full pipeline: translate the speech in *video_path* to *target_language*
    and write the result to *output_path*.

    Parameters
    ----------
    video_path:
        Path to the input video file.
    target_language:
        BCP-47 / ISO-639-1 code for the target language (must be in
        ``SUPPORTED_LANGUAGES``).
    output_path:
        Where to write the translated video.
    preserve_background_music:
        When True, attempt to extract background music and mix it back at low
        volume under the synthesized voice.
    progress_callback:
        Optional callable ``(step_label: str, percent: int)`` for progress
        reporting.

    Returns
    -------
    Path
        The path of the translated video file (same as *output_path*).
    """
    if target_language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Language '{target_language}' is not supported. "
            f"Choose one of: {list(SUPPORTED_LANGUAGES.keys())}"
        )

    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="viraclip_translation_"))
    try:
        _progress(progress_callback, STEP_EXTRACTING, 5)

        # --- Step 1: Extract audio ---
        audio_original = tmp_dir / "audio_original.wav"
        _extract_audio(video_path, audio_original)

        _progress(progress_callback, STEP_TRANSCRIBING, 15)

        # --- Step 2 & 3: Transcribe and detect language ---
        try:
            source_lang, segments = _transcribe_audio(audio_original)
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            raise RuntimeError(f"Transcription failed: {exc}") from exc

        if not segments:
            logger.warning("No speech segments found; copying video unchanged")
            shutil.copy2(video_path, output_path)
            _progress(progress_callback, STEP_DONE, 100)
            return output_path

        logger.info(
            "Detected source language: %s, segments: %d", source_lang, len(segments)
        )

        _progress(progress_callback, STEP_TRANSLATING, 25)

        # --- Step 4: Translate segments ---
        translated: List[Tuple[float, float, str]] = []
        for i, (start, end, text) in enumerate(segments):
            t_text = translate_text(text, source_lang, target_language)
            translated.append((start, end, t_text))
            pct = 25 + int((i + 1) / len(segments) * 20)
            _progress(progress_callback, STEP_TRANSLATING, pct)

        _progress(progress_callback, STEP_SYNTHESIZING, 45)

        # --- Step 5: Synthesize per-segment speech ---
        synth_segments: List[Tuple[float, Path]] = []
        for i, (start, end, text) in enumerate(translated):
            seg_path = tmp_dir / f"seg_{i:04d}.wav"
            original_dur = end - start
            try:
                synth_path = synthesize_speech(
                    text,
                    target_language,
                    seg_path,
                    original_duration=original_dur,
                )
                synth_segments.append((start, synth_path))
            except Exception as exc:
                logger.warning("Skipping segment %d due to TTS error: %s", i, exc)
            pct = 45 + int((i + 1) / len(translated) * 25)
            _progress(progress_callback, STEP_SYNTHESIZING, pct)

        _progress(progress_callback, STEP_MIXING, 70)

        # --- Step 6: Reconstruct full audio track ---
        video_duration = _get_video_duration(video_path)
        silent_base = tmp_dir / "silent_base.wav"
        _build_silent_audio(video_duration, silent_base)

        current_base = silent_base
        for i, (start, seg_path) in enumerate(synth_segments):
            next_base = tmp_dir / f"mixed_{i:04d}.wav"
            try:
                _overlay_segment(current_base, seg_path, start, next_base)
                current_base = next_base
            except Exception as exc:
                logger.warning(
                    "Could not overlay segment %d at %.2fs: %s", i, start, exc
                )
        translated_audio = current_base

        # --- Step 6b: Optionally preserve background music ---
        if preserve_background_music:
            bg_track = _separate_background_music(audio_original, tmp_dir)
            if bg_track:
                mixed_with_bg = tmp_dir / "mixed_with_bg.wav"
                try:
                    _run_ffmpeg(
                        "-i", str(translated_audio),
                        "-i", str(bg_track),
                        "-filter_complex",
                        "[1:a]volume=0.15[bg];[0:a][bg]amix=inputs=2:duration=first[out]",
                        "-map", "[out]",
                        "-acodec", "pcm_s16le",
                        str(mixed_with_bg),
                    )
                    translated_audio = mixed_with_bg
                except Exception as exc:
                    logger.warning(
                        "Background music mixing failed; using voice-only track: %s", exc
                    )
            else:
                logger.info(
                    "Background music separation unavailable; using voice-only track"
                )

        _progress(progress_callback, STEP_MIXING, 88)

        # --- Step 7: Merge translated audio with original video ---
        _run_ffmpeg(
            "-i", str(video_path),
            "-i", str(translated_audio),
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            str(output_path),
        )

        _progress(progress_callback, STEP_DONE, 100)
        logger.info("Translation complete → %s", output_path)
        return output_path

    finally:
        # Clean up temporary files
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _progress(
    callback: Optional[ProgressCallback], step: str, percent: int
) -> None:
    """Safely invoke *callback* if provided."""
    if callback is not None:
        try:
            callback(step, percent)
        except Exception as exc:
            logger.debug("Progress callback error: %s", exc)
