"""
Utility functions for video-related operations.
Optimized for MoviePy v2, AssemblyAI integration, and high-quality output.

DEPRECATION NOTICE: This module is being phased out. 
Please use the new modular imports from video_processing package:
- video_processing.transcription (get_video_transcript)
- video_processing.subtitles (create_*_subtitles)
- video_processing.face_detection (detect_faces_in_clip, detect_face_trajectory)
- video_processing.audio (mix_background_music, get_background_music_for_niche)
- video_processing.clip_creation (create_optimized_clip)
"""

import warnings
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import os
import logging
import numpy as np
import json
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import multiprocessing
import zipfile
import subprocess

# Optional cv2 import - not required for basic functionality
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    cv2 = None

from moviepy import VideoFileClip, CompositeVideoClip, TextClip, ColorClip
from moviepy.video.fx import CrossFadeIn, CrossFadeOut, FadeIn, FadeOut

try:
    import assemblyai as aai
    AAI_AVAILABLE = True
except ImportError:
    AAI_AVAILABLE = False
    aai = None

try:
    import srt
    SRT_AVAILABLE = True
except ImportError:
    SRT_AVAILABLE = False
    srt = None

from datetime import timedelta

from .config import Config
from .caption_templates import get_template, CAPTION_TEMPLATES
from .font_registry import find_font_path
from .utils.resource_management import ResourceGuard
from .utils.motion_utils import create_ken_burns_clip
from .spacetimedb.schema import broadcast_telemetry

logger = logging.getLogger(__name__)
config = Config()
TRANSCRIPT_CACHE_SCHEMA_VERSION = 2

# DEPRECATION: Functions in this file are being migrated to video_processing package
# This module will be removed in a future version. Please update your imports.
warnings.warn(
    "video_utils.py is deprecated. Use video_processing package instead. "
    "See: video_processing.transcription, subtitles, face_detection, audio, clip_creation",
    DeprecationWarning,
    stacklevel=2
)

# B-4 fix: shared directory for content-hash-based transcript caches
# Lets the same video file re-use its transcript even if downloaded to a different path.
_TRANSCRIPT_HASH_CACHE_DIR = Path("/tmp/supoclip_transcript_cache")


def _get_video_content_hash(video_path: Path) -> Optional[str]:
    """Return SHA256 hex digest of the first 1 MB of a video file.

    Used as a content-based cache key so re-downloads don't re-transcribe.
    Returns None if the file can't be read.
    """
    import hashlib
    try:
        with open(video_path, "rb") as fh:
            chunk = fh.read(1_048_576)  # 1 MB
        return hashlib.sha256(chunk).hexdigest()
    except Exception:
        return None


def _hash_cache_path(video_hash: str) -> Path:
    return _TRANSCRIPT_HASH_CACHE_DIR / f"{video_hash}.transcript_cache.json"


class VideoProcessor:
    """Handles video processing operations with optimized settings."""

    def __init__(
        self,
        font_family: str = "THEBOLDFONT",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
    ):
        self.font_family = font_family
        self.font_size = font_size
        self.font_color = font_color
        resolved_font = find_font_path(font_family, allow_all_user_fonts=True)
        if not resolved_font:
            resolved_font = find_font_path("TikTokSans-Regular")
        if not resolved_font:
            resolved_font = find_font_path("THEBOLDFONT")
        # Last-resort fallback: pick ANY .ttf/.otf in the fonts dir so TextClip never
        # receives an empty font string (which crashes MoviePy with an unhelpful error).
        if not resolved_font:
            from .font_registry import FONTS_DIR, SUPPORTED_FONT_EXTENSIONS
            for _ext in SUPPORTED_FONT_EXTENSIONS:
                _candidates = sorted(FONTS_DIR.glob(f"*{_ext}"))
                if _candidates:
                    resolved_font = _candidates[0]
                    logger.warning(
                        f"⚠️ Font '{font_family}' not found — falling back to {resolved_font.name}"
                    )
                    break
        if not resolved_font:
            logger.error(
                "❌ No fonts found in fonts directory. TextClip will use ImageMagick default. "
                "Add .ttf files to backend/fonts/ to fix this."
            )
        self.font_path = str(resolved_font) if resolved_font else ""

    def get_optimal_encoding_settings(
        self, target_quality: str = "high"
    ) -> Dict[str, Any]:
        """
        Get optimal encoding settings with high-quality audio and video.
        Uses libx264 (CPU) — stable and verified.

        Quality improvements:
        - CRF values optimized for short-form video virality
        - AAC audio at high bitrates (192k min) for clarity
        - Hardware profiles for modern devices
        - Optimized presets for speed vs. quality tradeoff
        """
        use_nvenc = False
        logger.info("🎬 Using CPU encoding (libx264) with optimized audio — high quality for viral shorts")

        settings = {
            "high": {
                "codec": "libx264",
                "audio_codec": "aac",
                "preset": "fast",       # fast: 2-3x faster than medium, visually identical
                "ffmpeg_params": [
                    "-crf", "21",       # IMPROVED: 21 instead of 23 — noticeably better for TikTok/Reels
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",  # NEW: Main profile for broad device compatibility
                    "-level", "4.0",    # NEW: Level 4.0 for HD+ on all devices
                    "-b:a", "256k",     # IMPROVED: 256k instead of 192k — richer audio
                    "-ar", "48000",     # NEW: 48kHz audio (standard for video)
                ],
            },
            "medium": {
                "codec": "libx264",
                "audio_codec": "aac",
                "preset": "veryfast",
                "ffmpeg_params": [
                    "-crf", "24",       # IMPROVED: 24 instead of 26 — better quality
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.0",
                    "-b:a", "192k",     # 192k audio
                    "-ar", "48000",
                ],
            },
        }
        return settings.get(target_quality, settings["high"])


# === Singleton model cache for faster-whisper (avoid reloading per video) ===
_whisper_model = None
_whisper_model_config = None

# V3 Phase 4: Auto-Emoji Synthesis mapping
SENTIMENT_EMOJIS = {
    "DINERO": "💰", "CASH": "💵", "GUERRA": "⚔️", "MUERTE": "💀", "PELIGRO": "⚠️",
    "ERROR": "❌", "FALTA": "🚫", "DANGER": "🔥", "STOP": "🛑", "WOW": "😲",
    "INCREÍBLE": "🤯", "LOCO": "🤪", "AMAZING": "✨", "CRAZY": "🌀", "BRUTAL": "🦾",
    "GENIAL": "🚀", "BESTIAL": "🦁", "AHORA": "⏳", "YA": "🔔", "MIRA": "👀",
    "ESCUCHA": "👂", "LISTEN": "📣", "WATCH": "🎬", "LOVE": "❤️", "FIRE": "🔥",
    "WIN": "🏆", "GOAL": "⚽", "TIME": "⏰", "MONEY": "💸", "SECRET": "🤫"
}

def inject_emoji(text: str) -> str:
    """Inject a relevant emoji if the uppercase word matches a sentiment key."""
    clean_text = text.upper().strip(".,!?;:")
    emoji = SENTIMENT_EMOJIS.get(clean_text)
    return f"{text} {emoji}" if emoji else text


def _get_whisper_model():
    """Get or create a singleton faster-whisper model with smart device detection."""
    global _whisper_model, _whisper_model_config

    model_size = os.environ.get("WHISPER_MODEL_SIZE", "medium")
    device_setting = os.environ.get("WHISPER_DEVICE", "auto")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8_float16")

    # Auto-detect device
    if device_setting == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                gpu_name = torch.cuda.get_device_name(0)
                vram_mb = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
                logger.info(f"🚀 GPU detected: {gpu_name} ({vram_mb}MB VRAM)")
            else:
                device = "cpu"
                compute_type = "int8"  # float16 not supported on CPU
                logger.info("⚙️ No GPU detected, using CPU mode")
        except Exception as e:
            logger.error(f"⚠️ PyTorch/CUDA error during detection: {e}")
            device = "cpu"
            compute_type = "int8"
            logger.info("⚙️ Falling back to CPU mode")
    else:
        device = device_setting
        if device == "cpu":
            compute_type = "int8"

    current_config = (model_size, device, compute_type)

    # Return cached model if config unchanged
    if _whisper_model is not None and _whisper_model_config == current_config:
        logger.info(f"♻️ Reusing cached whisper model: {model_size} on {device}")
        return _whisper_model

    # Create new model
    from faster_whisper import WhisperModel

    logger.info(f"🔄 Loading whisper model: {model_size} | device={device} | compute={compute_type}")
    
    model_path = model_size

    _whisper_model = WhisperModel(
        model_path,
        device=device,
        compute_type=compute_type,
        download_root="/app/models"
    )
    _whisper_model_config = current_config
    logger.info(f"✅ Whisper model loaded: {model_size} on {device}")
    return _whisper_model


def get_video_transcript(video_path: Path, speech_model: str = "best") -> str:
    """Transcripción 100% local con faster-whisper + auto-detección GPU/CPU."""
    logger.info(f"🔥 Transcribiendo con faster-whisper local: {video_path}")

    model = _get_whisper_model()

    try:
        segments, info = model.transcribe(
            str(video_path),
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        logger.info(f"Idioma detectado: {info.language} (probabilidad {info.language_probability:.2f})")
        logger.info(f"Duración del audio: {info.duration:.1f}s")

        # Format output compatible with downstream code
        formatted_lines = []
        all_segments = []
        for segment in segments:
            start = format_ms_to_timestamp(int(segment.start * 1000))
            end = format_ms_to_timestamp(int(segment.end * 1000))
            formatted_lines.append(f"[{start} - {end}] {segment.text}")
            all_segments.append(segment)

        # Cache transcript data for subtitle generation
        cache_transcript_data(video_path, all_segments)

        result = "\n".join(formatted_lines)
        logger.info(f"✅ Transcripción completada: {len(result)} caracteres, {len(formatted_lines)} segmentos")
        return result

    except Exception as e:
        logger.error(f"❌ Error en faster-whisper: {e}")

        # Fallback to AssemblyAI with speaker diarization when faster-whisper fails
        if AAI_AVAILABLE:
            try:
                logger.info("🔄 Falling back to AssemblyAI transcription with speaker labels…")
                config_aai = aai.TranscriptionConfig(speaker_labels=True)
                transcriber = aai.Transcriber()
                transcript = transcriber.transcribe(str(video_path), config=config_aai)
                if transcript.status == aai.TranscriptStatus.completed:
                    lines = []
                    if transcript.utterances:
                        for utterance in transcript.utterances:
                            lines.append(f"Speaker {utterance.speaker}: {utterance.text}")
                    elif transcript.text:
                        lines.append(transcript.text)
                    return "\n".join(lines)
            except Exception as aai_e:
                logger.error(f"❌ AssemblyAI fallback failed: {aai_e}")

        raise


def cache_transcript_data(video_path: Path, transcript) -> None:
    """Cache transcript data for subtitle generation.

    Accepts either:
    - A list of faster-whisper Segment objects (from local transcription)
    - An AssemblyAI transcript object (legacy)
    """
    cache_path = video_path.with_suffix(".transcript_cache.json")

    words_data = []
    utterances_data = []
    full_text = ""

    # Detect if this is a list of faster-whisper segments
    if isinstance(transcript, list):
        # faster-whisper segments
        all_words = []
        text_parts = []
        for segment in transcript:
            text_parts.append(segment.text.strip())
            if hasattr(segment, "words") and segment.words:
                for word in segment.words:
                    all_words.append({
                        "text": word.word if hasattr(word, "word") else word.text,
                        "start": int(word.start * 1000),  # convert to ms
                        "end": int(word.end * 1000),
                        "confidence": getattr(word, "probability", 1.0),
                        "speaker": None,
                    })
        words_data = all_words
        full_text = " ".join(text_parts)
        logger.info(f"Caching faster-whisper data: {len(words_data)} words")
    else:
        # Legacy AssemblyAI transcript object
        if hasattr(transcript, "words") and transcript.words:
            words_data = [_serialize_transcript_word(word) for word in transcript.words]

        if getattr(transcript, "utterances", None):
            utterances_data = [
                {
                    "text": utterance.text,
                    "start": utterance.start,
                    "end": utterance.end,
                    "speaker": getattr(utterance, "speaker", None),
                    "words": [
                        _serialize_transcript_word(word)
                        for word in getattr(utterance, "words", []) or []
                    ],
                }
                for utterance in transcript.utterances
            ]

        full_text = getattr(transcript, "text", "") or ""

    cache_data = {
        "version": TRANSCRIPT_CACHE_SCHEMA_VERSION,
        "words": words_data,
        "utterances": utterances_data,
        "text": full_text,
    }

    with open(cache_path, "w") as f:
        json.dump(cache_data, f)

    logger.info(f"Cached {len(words_data)} words to {cache_path}")

    # B-4 fix: also write to content-hash-based location so the same video
    # re-uses the cache even if downloaded to a different path next time.
    try:
        video_hash = _get_video_content_hash(video_path)
        if video_hash:
            _TRANSCRIPT_HASH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            hash_path = _hash_cache_path(video_hash)
            with open(hash_path, "w") as f:
                json.dump(cache_data, f)
            logger.info(f"Hash-cache written: {hash_path.name}")
    except Exception as _hce:
        logger.debug(f"Hash-cache write skipped: {_hce}")


def load_cached_transcript_data(video_path: Path) -> Optional[Dict]:
    """Load cached transcript data.

    Checks in this order:
    1. Path-adjacent cache  (fast, same-download path)
    2. Content-hash cache   (B-4 fix: works even if the video was re-downloaded to a new path)
    """

    def _parse_cache(path: Path) -> Optional[Dict]:
        try:
            with open(path, "r") as f:
                payload = json.load(f)
            if "version" not in payload:
                payload["version"] = TRANSCRIPT_CACHE_SCHEMA_VERSION
                payload.setdefault("utterances", [])
            return payload
        except Exception as e:
            logger.warning(f"Failed to parse transcript cache {path}: {e}")
            return None

    # 1. Path-adjacent cache (original behaviour)
    cache_path = video_path.with_suffix(".transcript_cache.json")
    if cache_path.exists():
        data = _parse_cache(cache_path)
        if data is not None:
            return data

    # 2. Content-hash cache (B-4 fix)
    try:
        video_hash = _get_video_content_hash(video_path)
        if video_hash:
            hash_path = _hash_cache_path(video_hash)
            if hash_path.exists():
                data = _parse_cache(hash_path)
                if data is not None:
                    logger.info(f"Transcript loaded from hash-cache (path mismatch avoided): {hash_path.name}")
                    return data
    except Exception as _hle:
        logger.debug(f"Hash-cache lookup failed: {_hle}")

    return None

def snap_to_word_boundary(
    video_path: Path, start_time: float, end_time: float, padding: float = 0.1
) -> tuple[float, float]:
    """Snap start and end times to the nearest word boundaries using cache.

    Only searches within a ±3s window around each boundary to avoid pulling
    the clip edge to a distant word (e.g. across a long pause in a 19-min video).
    """
    cache = load_cached_transcript_data(video_path)
    if not cache or not cache.get("words"):
        return start_time, end_time

    words = cache["words"]
    start_ms = start_time * 1000
    end_ms = end_time * 1000
    search_window_ms = 3000  # only consider words within ±3 seconds of target

    # Find closest word start near start_time
    best_start = start_ms
    min_diff = float("inf")
    for w in words:
        diff = abs(w["start"] - start_ms)
        if diff <= search_window_ms and diff < min_diff:
            min_diff = diff
            best_start = w["start"] - (padding * 1000)

    # Find closest word end near end_time
    best_end = end_ms
    min_diff = float("inf")
    for w in words:
        diff = abs(w["end"] - end_ms)
        if diff <= search_window_ms and diff < min_diff:
            min_diff = diff
            best_end = w["end"] + (padding * 1000)

    # Ensure we don't go out of bounds or create negative duration
    new_start = max(0.0, best_start / 1000.0)
    new_end = max(new_start + 1.0, best_end / 1000.0)

    logger.info(
        f"Snapped [{start_time:.2f}-{end_time:.2f}] -> [{new_start:.2f}-{new_end:.2f}]"
    )
    return new_start, new_end


def _serialize_transcript_word(word) -> Dict[str, Any]:
    return {
        "text": word.text,
        "start": word.start,
        "end": word.end,
        "confidence": word.confidence if hasattr(word, "confidence") else 1.0,
        "speaker": getattr(word, "speaker", None),
    }


def format_transcript_for_analysis(transcript) -> List[str]:
    """Format transcripts into readable timestamped segments for AI analysis."""
    utterances = getattr(transcript, "utterances", None) or []
    if utterances:
        formatted_lines = []
        for utterance in utterances:
            start_time = format_ms_to_timestamp(utterance.start)
            end_time = format_ms_to_timestamp(utterance.end)
            speaker = getattr(utterance, "speaker", None)
            speaker_prefix = f"Speaker {speaker}: " if speaker else ""
            formatted_lines.append(
                f"[{start_time} - {end_time}] {speaker_prefix}{utterance.text}"
            )
        return formatted_lines

    formatted_lines = []
    words = getattr(transcript, "words", None) or []
    if not words:
        return formatted_lines

    logger.info(f"Processing {len(words)} words with precise timing")

    current_segment = []
    current_start = None
    segment_word_count = 0
    max_words_per_segment = 8

    for word in words:
        if current_start is None:
            current_start = word.start

        current_segment.append(word.text)
        segment_word_count += 1

        if (
            segment_word_count >= max_words_per_segment
            or word.text.endswith(".")
            or word.text.endswith("!")
            or word.text.endswith("?")
        ):
            if current_segment:
                start_time = format_ms_to_timestamp(current_start)
                end_time = format_ms_to_timestamp(word.end)
                text = " ".join(current_segment)
                formatted_lines.append(f"[{start_time} - {end_time}] {text}")

            current_segment = []
            current_start = None
            segment_word_count = 0

    if current_segment and current_start is not None:
        start_time = format_ms_to_timestamp(current_start)
        end_time = format_ms_to_timestamp(words[-1].end)
        text = " ".join(current_segment)
        formatted_lines.append(f"[{start_time} - {end_time}] {text}")

    return formatted_lines


def format_ms_to_timestamp(ms: int) -> str:
    """Format milliseconds to MM:SS format."""
    seconds = ms // 1000
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def round_to_even(value: int) -> int:
    """Round integer to nearest even number for H.264 compatibility."""
    return value - (value % 2)


def get_scaled_font_size(base_font_size: int, video_width: int) -> int:
    """
    Scale caption font size by output width with sensible bounds.
    Optimized for mobile vertical video (9:16) visibility.

    QUALITY IMPROVEMENT: Increased scaling factor and minimum bounds
    for better TikTok/Reels readability.
    """
    # Increase base size by 30% (was 20%) for mobile-first visibility
    # For 9:16 vertical video, viewers hold phones very close to face
    scaled_size = int(base_font_size * (video_width / 720) * 1.3)
    # IMPROVED: minimum 28 (was 24) for short-form video where readability is critical
    return max(28, min(88, scaled_size))


def get_subtitle_max_width(video_width: int) -> int:
    """Return max subtitle text width with horizontal safe margins."""
    horizontal_padding = max(40, int(video_width * 0.06))
    return max(200, video_width - (horizontal_padding * 2))


def get_safe_vertical_position(
    video_height: int, text_height: int, position_y: float
) -> int:
    """
    Return subtitle y position clamped inside a top/bottom safe area.

    QUALITY IMPROVEMENT: Larger safe zones prevent subtitles from being
    cut off on older/cheap phones with imperfect screens.
    """
    min_top_padding = max(60, int(video_height * 0.08))  # IMPROVED: 60px, 8% (was 40px, 5%)
    min_bottom_padding = max(150, int(video_height * 0.15))  # IMPROVED: 150px, 15% (was 120px, 10%)

    desired_y = int(video_height * position_y - text_height // 2)
    max_y = video_height - min_bottom_padding - text_height
    return max(min_top_padding, min(desired_y, max_y))


def detect_optimal_crop_region(
    video_clip: VideoFileClip,
    start_time: float,
    end_time: float,
    target_ratio: float = 9 / 16,
) -> Tuple[int, int, int, int]:
    """Detect optimal crop region using improved face detection."""
    try:
        original_width, original_height = video_clip.size

        # Calculate target dimensions and ensure they're even
        if original_width / original_height > target_ratio:
            new_width = round_to_even(int(original_height * target_ratio))
            new_height = round_to_even(original_height)
        else:
            new_width = round_to_even(original_width)
            new_height = round_to_even(int(original_width / target_ratio))

        # Try improved face detection
        face_centers = detect_faces_in_clip(video_clip, start_time, end_time)

        # Calculate crop position
        if face_centers:
            # Use weighted average of face centers with temporal consistency
            total_weight = sum(
                area * confidence for _, _, area, confidence in face_centers
            )
            if total_weight > 0:
                weighted_x = (
                    sum(
                        x * area * confidence for x, y, area, confidence in face_centers
                    )
                    / total_weight
                )
                weighted_y = (
                    sum(
                        y * area * confidence for x, y, area, confidence in face_centers
                    )
                    / total_weight
                )

                # Add slight bias towards upper portion for better face framing
                weighted_y = max(0, weighted_y - new_height * 0.1)

                x_offset = max(
                    0, min(int(weighted_x - new_width // 2), original_width - new_width)
                )
                y_offset = max(
                    0,
                    min(
                        int(weighted_y - new_height // 2), original_height - new_height
                    ),
                )

                logger.info(
                    f"Face-centered crop: {len(face_centers)} faces detected with improved algorithm"
                )
            else:
                # Center crop
                x_offset = (
                    (original_width - new_width) // 2
                    if original_width > new_width
                    else 0
                )
                y_offset = (
                    (original_height - new_height) // 2
                    if original_height > new_height
                    else 0
                )
        else:
            # Center crop
            x_offset = (
                (original_width - new_width) // 2 if original_width > new_width else 0
            )
            y_offset = (
                (original_height - new_height) // 2
                if original_height > new_height
                else 0
            )
            logger.info("Using center crop (no faces detected)")

        # Ensure offsets are even too
        x_offset = round_to_even(x_offset)
        y_offset = round_to_even(y_offset)

        logger.info(
            f"Crop dimensions: {new_width}x{new_height} at offset ({x_offset}, {y_offset})"
        )
        return (x_offset, y_offset, new_width, new_height)

    except Exception as e:
        logger.error(f"Error in crop detection: {e}")
        # Fallback to center crop
        original_width, original_height = video_clip.size
        if original_width / original_height > target_ratio:
            new_width = round_to_even(int(original_height * target_ratio))
            new_height = round_to_even(original_height)
        else:
            new_width = round_to_even(original_width)
            new_height = round_to_even(int(original_width / target_ratio))

        x_offset = (
            round_to_even((original_width - new_width) // 2)
            if original_width > new_width
            else 0
        )
        y_offset = (
            round_to_even((original_height - new_height) // 2)
            if original_height > new_height
            else 0
        )

        return (x_offset, y_offset, new_width, new_height)


def detect_faces_in_clip(
    video_clip: VideoFileClip, start_time: float, end_time: float
) -> List[Tuple[int, int, int, float]]:
    """
    Improved face detection using multiple methods and temporal consistency.
    Returns list of (x, y, area, confidence) tuples.
    """
    face_centers = []

    try:
        # Try to use MediaPipe (most accurate)
        mp_face_detection = None
        try:
            import mediapipe as mp

            mp_face_detection = mp.solutions.face_detection.FaceDetection(
                model_selection=0,  # 0 for short-range (better for close faces)
                min_detection_confidence=0.5,
            )
            logger.info("Using MediaPipe face detector")
        except ImportError:
            logger.info("MediaPipe not available, falling back to OpenCV")
        except Exception as e:
            logger.warning(f"MediaPipe face detector failed to initialize: {e}")

        # Initialize OpenCV face detectors as fallback
        haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        # Try to load DNN face detector (more accurate than Haar)
        dnn_net = None
        try:
            # Load OpenCV's DNN face detector
            prototxt_path = cv2.data.haarcascades.replace(
                "haarcascades", "opencv_face_detector.pbtxt"
            )
            model_path = cv2.data.haarcascades.replace(
                "haarcascades", "opencv_face_detector_uint8.pb"
            )

            # If DNN model files don't exist, we'll fall back to Haar cascade
            import os

            if os.path.exists(prototxt_path) and os.path.exists(model_path):
                dnn_net = cv2.dnn.readNetFromTensorflow(model_path, prototxt_path)
                logger.info("OpenCV DNN face detector loaded as backup")
            else:
                logger.info("OpenCV DNN face detector not available")
        except Exception:
            logger.info("OpenCV DNN face detector failed to load")

        # Sample more frames for better face detection (every 0.5 seconds)
        duration = end_time - start_time
        sample_interval = min(0.5, duration / 10)  # At least 10 samples, max every 0.5s
        sample_times = []

        current_time = start_time
        while current_time < end_time:
            sample_times.append(current_time)
            current_time += sample_interval

        # Ensure we always sample the middle and end
        if duration > 1.0:
            middle_time = start_time + duration / 2
            if middle_time not in sample_times:
                sample_times.append(middle_time)

        sample_times = [t for t in sample_times if t < end_time]
        logger.info(f"Sampling {len(sample_times)} frames for face detection")

        for sample_time in sample_times:
            try:
                frame = video_clip.get_frame(sample_time)
                height, width = frame.shape[:2]
                detected_faces = []

                # Try MediaPipe first (most accurate)
                if mp_face_detection is not None:
                    try:
                        # MediaPipe expects RGB format
                        results = mp_face_detection.process(frame)

                        if results.detections:
                            for detection in results.detections:
                                bbox = detection.location_data.relative_bounding_box
                                confidence = detection.score[0]

                                # Convert relative coordinates to absolute
                                x = int(bbox.xmin * width)
                                y = int(bbox.ymin * height)
                                w = int(bbox.width * width)
                                h = int(bbox.height * height)

                                if w > 30 and h > 30:  # Minimum face size
                                    detected_faces.append((x, y, w, h, confidence))
                    except Exception as e:
                        logger.warning(
                            f"MediaPipe detection failed for frame at {sample_time}s: {e}"
                        )

                # If MediaPipe didn't find faces, try DNN detector
                if not detected_faces and dnn_net is not None:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        blob = cv2.dnn.blobFromImage(
                            frame_bgr, 1.0, (300, 300), [104, 117, 123]
                        )
                        dnn_net.setInput(blob)
                        detections = dnn_net.forward()

                        for i in range(detections.shape[2]):
                            confidence = detections[0, 0, i, 2]
                            if confidence > 0.5:  # Confidence threshold
                                x1 = int(detections[0, 0, i, 3] * width)
                                y1 = int(detections[0, 0, i, 4] * height)
                                x2 = int(detections[0, 0, i, 5] * width)
                                y2 = int(detections[0, 0, i, 6] * height)

                                w = x2 - x1
                                h = y2 - y1

                                if w > 30 and h > 30:  # Minimum face size
                                    detected_faces.append((x1, y1, w, h, confidence))
                    except Exception as e:
                        logger.warning(
                            f"DNN detection failed for frame at {sample_time}s: {e}"
                        )

                # If still no faces found, use Haar cascade
                if not detected_faces:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

                        faces = haar_cascade.detectMultiScale(
                            gray,
                            scaleFactor=1.05,  # More sensitive
                            minNeighbors=3,  # Less strict than Haar default (5)
                            minSize=(50, 50),  # IMPROVED: 50x50 instead of 40x40 — reduces false positives
                            maxSize=(
                                int(width * 0.8),  # IMPROVED: 80% instead of 70% — allows larger faces
                                int(height * 0.8),
                            ),
                            flags=cv2.CASCADE_SCALE_IMAGE,  # IMPROVED: explicit flag for accuracy
                        )

                        for x, y, w, h in faces:
                            # Estimate confidence based on face size and position
                            face_area = w * h
                            relative_size = face_area / (width * height)
                            confidence = min(
                                0.9, 0.3 + relative_size * 2
                            )  # Rough confidence estimate
                            detected_faces.append((x, y, w, h, confidence))
                    except Exception as e:
                        logger.warning(
                            f"Haar cascade detection failed for frame at {sample_time}s: {e}"
                        )

                # Process detected faces
                for x, y, w, h, confidence in detected_faces:
                    face_center_x = x + w // 2
                    face_center_y = y + h // 2
                    face_area = w * h

                    # Filter out very small or very large faces
                    frame_area = width * height
                    relative_area = face_area / frame_area

                    if (
                        0.005 < relative_area < 0.3
                    ):  # Face should be 0.5% to 30% of frame
                        face_centers.append(
                            (face_center_x, face_center_y, face_area, confidence)
                        )

            except Exception as e:
                logger.warning(f"Error detecting faces in frame at {sample_time}s: {e}")
                continue

        # Close MediaPipe detector
        if mp_face_detection is not None:
            mp_face_detection.close()

        # Remove outliers (faces that are very far from the median position)
        if len(face_centers) > 2:
            face_centers = filter_face_outliers(face_centers)

        logger.info(f"Detected {len(face_centers)} reliable face centers")
        return face_centers

    except Exception as e:
        logger.error(f"Error in face detection: {e}")
        return []


def filter_face_outliers(
    face_centers: List[Tuple[int, int, int, float]],
) -> List[Tuple[int, int, int, float]]:
    """Remove face detections that are outliers (likely false positives)."""
    if len(face_centers) < 3:
        return face_centers

    try:
        # Calculate median position
        x_positions = [x for x, y, area, conf in face_centers]
        y_positions = [y for x, y, area, conf in face_centers]

        median_x = np.median(x_positions)
        median_y = np.median(y_positions)

        # Calculate standard deviation
        std_x = np.std(x_positions)
        std_y = np.std(y_positions)

        # Filter out faces that are more than 2 standard deviations away
        filtered_faces = []
        for face in face_centers:
            x, y, area, conf = face
            if abs(x - median_x) <= 2 * std_x and abs(y - median_y) <= 2 * std_y:
                filtered_faces.append(face)

        logger.info(
            f"Filtered {len(face_centers)} -> {len(filtered_faces)} faces (removed outliers)"
        )
        return (
            filtered_faces if filtered_faces else face_centers
        )  # Return original if all filtered

    except Exception as e:
        logger.warning(f"Error filtering face outliers: {e}")
        return face_centers


def parse_timestamp_to_seconds(timestamp_str: str) -> float:
    """Parse timestamp string to seconds."""
    try:
        timestamp_str = timestamp_str.strip()
        logger.info(f"Parsing timestamp: '{timestamp_str}'")  # Debug logging

        if ":" in timestamp_str:
            parts = timestamp_str.split(":")
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                result = minutes * 60 + seconds
                logger.info(f"Parsed '{timestamp_str}' -> {result}s")
                return result
            elif len(parts) == 3:  # HH:MM:SS format
                hours, minutes, seconds = map(int, parts)
                result = hours * 3600 + minutes * 60 + seconds
                logger.info(f"Parsed '{timestamp_str}' -> {result}s")
                return result

        # Try parsing as pure seconds
        result = float(timestamp_str)
        logger.info(f"Parsed '{timestamp_str}' as seconds -> {result}s")
        return result

    except (ValueError, IndexError) as e:
        logger.error(f"Failed to parse timestamp '{timestamp_str}': {e}")
        return 0.0


def get_words_in_range(
    transcript_data: Dict, clip_start: float, clip_end: float
) -> List[Dict]:
    """Extract words that fall within a clip timerange."""
    if not transcript_data or not transcript_data.get("words"):
        return []

    clip_start_ms = int(clip_start * 1000)
    clip_end_ms = int(clip_end * 1000)

    relevant_words = []
    for word_data in transcript_data["words"]:
        word_start = word_data["start"]
        word_end = word_data["end"]

        if word_start < clip_end_ms and word_end > clip_start_ms:
            relative_start = max(0, (word_start - clip_start_ms) / 1000.0)
            relative_end = min(
                (clip_end_ms - clip_start_ms) / 1000.0,
                (word_end - clip_start_ms) / 1000.0,
            )

            if relative_end > relative_start:
                relevant_words.append(
                    {
                        "text": word_data["text"],
                        "start": relative_start,
                        "end": relative_end,
                        "confidence": word_data.get("confidence", 1.0),
                    }
                )

    return relevant_words


def adaptive_word_groups(
    words: List[Dict],
    video_width: int,
    font_size: int,
    max_display_seconds: float = 2.5,
) -> List[List[Dict]]:
    """
    Group words into subtitle lines adaptively, respecting:
    - Estimated text width relative to video frame
    - Maximum on-screen duration per group
    - Natural sentence boundaries (. ! ?)

    Replaces hard-coded ``words_per_subtitle = 3`` with a width-aware approach.
    Vertical 9:16 videos get ~3 words; wider videos can accommodate more.
    """
    if not words:
        return []

    # Estimate how many chars fit per line (rough: 0.8 * width / (0.55 * font_size))
    usable_width = video_width * 0.80
    avg_char_width = font_size * 0.55  # rough average for bold/display fonts
    max_chars_per_line = max(15, int(usable_width / avg_char_width))

    groups: List[List[Dict]] = []
    current_group: List[Dict] = []
    current_chars = 0

    for word in words:
        word_chars = len(word["text"]) + 1  # +1 for space

        # Start new group if adding this word would overflow or exceed time limit
        group_duration = (
            (word["end"] - current_group[0]["start"]) if current_group else 0
        )
        # Only break on real sentence endings, NOT commas (commas cause 1-2 word groups = flicker)
        ends_sentence = current_group and current_group[-1]["text"].rstrip().endswith(
            (".", "!", "?")
        )

        should_break = (
            current_chars + word_chars > max_chars_per_line
            or group_duration > max_display_seconds
            or (ends_sentence and len(current_group) >= 2)
        )

        if should_break and current_group:
            groups.append(current_group)
            current_group = []
            current_chars = 0

        current_group.append(word)
        current_chars += word_chars

    if current_group:
        groups.append(current_group)

    return groups


def create_bounce_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[Any]:
    """
    Create bounce-style subtitles: each word springs in with a quick
    scale-up animation (pop → overshoot → settle) for maximum visual impact.
    Uses a critically-damped spring model.
    """
    import math

    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)

    def spring_scale(t: float) -> float:
        """Critically-damped spring: fast pop-up with slight overshoot that settles."""
        # Attack: 0 → 1.25 in 0.07s, Decay: 1.25 → 1.0 in next 0.10s
        attack = 0.07
        settle = 0.17
        peak = 1.25
        if t <= 0:
            return 0.0
        if t < attack:
            return (t / attack) * peak
        if t < settle:
            progress = (t - attack) / (settle - attack)
            return peak - (peak - 1.0) * progress
        return 1.0

    # Elite V3 Upgrade: Sentiment-based coloring
    # Words in these categories get specialized high-impact colors
    INTENSE_WORDS = {"DINERO", "CASH", "GUERRA", "MUERTE", "PELIGRO", "ERROR", "FALTA", "DANGER", "STOP"}
    EXCITED_WORDS = {"INCREÍBLE", "WOW", "LOCO", "AMAZING", "CRAZY", "BRUTAL", "GENIAL", "BESTIAL"}
    ACTION_WORDS = {"AHORA", "YA", "MIRA", "ESCUCHA", "STOP", "GO", "LISTEN", "WATCH"}

    for word in relevant_words:
        word_start = word["start"]
        word_end = word["end"]
        duration = word_end - word_start

        if duration < 0.05:
            continue

        text = word["text"].upper().strip(".,!?;:")
        display_text = inject_emoji(word["text"].upper())
        
        # Elite Sentiment Coloring
        word_color = template["font_color"]
        if text in INTENSE_WORDS:
            word_color = "#FF3131" # Neon Red
        elif text in EXCITED_WORDS:
            word_color = "#39FF14" # Neon Green
        elif text in ACTION_WORDS:
            word_color = "#00F0FF" # Neon Cyan
        elif len(text) > 8:
            word_color = template.get("highlight_color", "#FFFF00") # Important long words

        try:
            base_clip = TextClip(
                text=display_text,
                font=processor.font_path,
                font_size=int(calculated_font_size * 1.15), # V3: Slightly larger for impact
                color=word_color,
                stroke_color=template.get("stroke_color", "black"),
                stroke_width=template.get("stroke_width", 4), # V3: Heavier stroke for depth
                method="label",
            )

            # Apply spring scale: resized() accepts a callable (t) -> scale
            bounced = base_clip.resized(lambda t: max(0.05, spring_scale(t)))

            text_height = base_clip.size[1] if base_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )

            final_clip = (
                bounced
                .with_duration(duration)
                .with_start(word_start)
                .with_position(("center", vertical_position))
            )
            subtitle_clips.append(final_clip)

        except Exception as e:
            logger.warning(f"Failed to create bounce word '{text}': {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} bounce subtitle elements")
    return subtitle_clips


def create_assemblyai_subtitles(
    video_path: Path,
    clip_start: float,
    clip_end: float,
    video_width: int,
    video_height: int,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
) -> List[TextClip]:
    """Create subtitles from word-level transcript cache (faster-whisper) with template support."""
    transcript_data = load_cached_transcript_data(video_path)

    if not transcript_data or not transcript_data.get("words"):
        logger.warning("No cached transcript data available for subtitles")
        return []

    # Get template settings
    template = get_template(caption_template)
    animation_type = template.get("animation", "none")

    effective_font_family = font_family or template["font_family"]
    effective_font_size = int(font_size) if font_size else int(template["font_size"])
    effective_font_color = font_color or template["font_color"]
    effective_template = {
        **template,
        "font_size": effective_font_size,
        "font_color": effective_font_color,
        "font_family": effective_font_family,
    }

    logger.info(
        f"Creating subtitles with template '{caption_template}', animation: {animation_type}"
    )

    # Get words in range
    relevant_words = get_words_in_range(transcript_data, clip_start, clip_end)

    if not relevant_words:
        logger.warning("No words found in clip timerange")
        return []

    # Choose subtitle creation method based on animation type
    if animation_type == "karaoke":
        return create_karaoke_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )
    elif animation_type == "pop":
        return create_pop_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )
    elif animation_type == "fade":
        return create_fade_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )
    elif animation_type == "bounce":
        return create_bounce_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )
    else:
        # Default static subtitles
        return create_static_subtitles(
            relevant_words,
            video_width,
            video_height,
            effective_template,
            effective_font_family,
        )


def create_static_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create standard static subtitles (original behavior)."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    max_text_width = get_subtitle_max_width(video_width)

    # Adaptive grouping: respects frame width and speech timing
    word_groups = adaptive_word_groups(
        relevant_words, video_width, calculated_font_size
    )

    for word_group in word_groups:
        if not word_group:
            continue

        segment_start = word_group[0]["start"]
        segment_end = word_group[-1]["end"]
        segment_duration = segment_end - segment_start

        if segment_duration < 0.1:
            continue

        text = " ".join(word["text"] for word in word_group)

        try:
            stroke_color = template.get("stroke_color", "black")
            stroke_width = template.get("stroke_width", 1)

            text_clip = (
                TextClip(
                    text=text,
                    font=processor.font_path,
                    font_size=calculated_font_size,
                    color=template["font_color"],
                    stroke_color=stroke_color if stroke_color else None,
                    stroke_width=stroke_width if stroke_color else 0,
                    method="caption",
                    size=(max_text_width, None),
                    text_align="center",
                    interline=6,
                )
                .with_duration(segment_duration)
                .with_start(segment_start)
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create subtitle for '{text}': {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} static subtitle elements")
    return subtitle_clips


def create_karaoke_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create karaoke-style subtitles with word-by-word highlighting."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    highlight_color = template.get("highlight_color", "#FFD700")
    normal_color = template["font_color"]
    max_text_width = get_subtitle_max_width(video_width)
    horizontal_padding = max(40, int(video_width * 0.06))

    # B-5 fix: use adaptive grouping instead of hardcoded words_per_group = 3
    adaptive_groups = adaptive_word_groups(relevant_words, video_width, calculated_font_size)

    def measure_word_group_width(word_group: List[Dict], font_size: int) -> List[int]:
        widths: List[int] = []
        for word in word_group:
            temp_clip = TextClip(
                text=word["text"],
                font=processor.font_path,
                font_size=font_size,
                color=normal_color,
                stroke_color=template.get("stroke_color", "black"),
                stroke_width=template.get("stroke_width", 1),
                method="label",
            )
            widths.append(temp_clip.size[0] if temp_clip.size else 50)
            temp_clip.close()
        return widths

    for word_group in adaptive_groups:
        if not word_group:
            continue

        group_start = word_group[0]["start"]
        group_end = word_group[-1]["end"]

        # Pre-compute layout for the whole group once (avoid redundant TextClip measurements)
        font_size_for_group = calculated_font_size
        word_widths = measure_word_group_width(word_group, font_size_for_group)
        space_width = font_size_for_group * 0.28
        total_width = sum(word_widths) + space_width * (len(word_group) - 1)
        if total_width > max_text_width and total_width > 0:
            shrink_ratio = max_text_width / total_width
            font_size_for_group = max(20, int(font_size_for_group * shrink_ratio))
            word_widths = measure_word_group_width(word_group, font_size_for_group)
            space_width = font_size_for_group * 0.28
            total_width = sum(word_widths) + space_width * (len(word_group) - 1)

        # For each word in the group, create a highlighted "tick"
        # KEY FIX: extend each tick to the NEXT word's start (no blank gaps within a group)
        for word_idx, current_word in enumerate(word_group):
            word_start = current_word["start"]
            # Extend duration to eliminate blank gaps between words in the same group
            if word_idx < len(word_group) - 1:
                word_end = word_group[word_idx + 1]["start"]  # fill gap to next word
            else:
                word_end = group_end  # last word extends to end of group
            word_duration = word_end - word_start

            if word_duration < 0.05:
                continue

            try:
                # Build the full line with the current word highlighted — no flickering gaps
                word_clips_for_composite = []

                # Second pass: create positioned clips
                current_x = max(horizontal_padding, (video_width - total_width) / 2)
                text_height = 40

                for w_idx, word in enumerate(word_group):
                    is_current = w_idx == word_idx
                    color = highlight_color if is_current else normal_color
                    # Scale up current word slightly for pop effect
                    size_multiplier = 1.1 if is_current else 1.0

                    word_clip = (
                        TextClip(
                            text=word["text"],
                            font=processor.font_path,
                            font_size=int(font_size_for_group * size_multiplier),
                            color=color,
                            stroke_color=template.get("stroke_color", "black"),
                            stroke_width=template.get("stroke_width", 1),
                            method="label",
                        )
                        .with_duration(word_duration)
                        .with_start(word_start)
                    )

                    text_height = max(
                        text_height, word_clip.size[1] if word_clip.size else 40
                    )
                    vertical_position = get_safe_vertical_position(
                        video_height, text_height, position_y
                    )

                    word_clip = word_clip.with_position(
                        (int(current_x), vertical_position)
                    )
                    word_clips_for_composite.append(word_clip)

                    current_x += word_widths[w_idx] + space_width

                subtitle_clips.extend(word_clips_for_composite)

            except Exception as e:
                logger.warning(
                    f"Failed to create karaoke subtitle for word '{current_word['text']}': {e}"
                )
                continue

    logger.info(f"Created {len(subtitle_clips)} karaoke subtitle elements")
    return subtitle_clips


def create_pop_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create pop-style subtitles where each word appears individually and quickly."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    max_text_width = get_subtitle_max_width(video_width)

    # In "Pop" style, we show one word at a time for maximum engagement
    for word_idx, word in enumerate(relevant_words):
        word_start = word["start"]
        word_end = word["end"]
        # Extend each word to the next word's start to eliminate blank frames between words
        if word_idx < len(relevant_words) - 1:
            word_end = relevant_words[word_idx + 1]["start"]
        word_duration = word_end - word_start
        text = word["text"].upper() # Viral style often uses uppercase
        display_text = inject_emoji(text)

        if word_duration < 0.05:
            continue

        try:
            text_clip = (
                TextClip(
                    text=display_text,
                    font=processor.font_path,
                    font_size=int(calculated_font_size * 1.1), # Slightly larger for pop
                    color=template.get("highlight_color", "#FFFF00"),
                    stroke_color=template.get("stroke_color", "black"),
                    stroke_width=template.get("stroke_width", 3),
                    method="label", # Label is faster and tighter for single words
                )
                .with_duration(word_duration)
                .with_start(word_start)
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create pop word '{text}': {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} fast-pop subtitle elements")
    return subtitle_clips


def create_fade_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_family: str,
) -> List[TextClip]:
    """Create fade-style subtitles with smooth transitions."""
    subtitle_clips = []
    processor = VideoProcessor(
        font_family, template["font_size"], template["font_color"]
    )

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    has_background = template.get("background", False)
    background_color = template.get("background_color", "#00000080")
    max_text_width = get_subtitle_max_width(video_width)

    words_per_group = 4

    for group_idx in range(0, len(relevant_words), words_per_group):
        word_group = relevant_words[group_idx : group_idx + words_per_group]
        if not word_group:
            continue

        group_text = " ".join(w["text"] for w in word_group)
        group_start = word_group[0]["start"]
        group_end = word_group[-1]["end"]
        group_duration = group_end - group_start

        if group_duration < 0.1:
            continue

        try:
            # Create text clip
            text_clip = TextClip(
                text=group_text,
                font=processor.font_path,
                font_size=calculated_font_size,
                color=template["font_color"],
                stroke_color=template.get("stroke_color")
                if template.get("stroke_color")
                else None,
                stroke_width=template.get("stroke_width", 0),
                method="caption",
                size=(max_text_width, None),
                text_align="center",
                interline=6,
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            text_width = text_clip.size[0] if text_clip.size else 200
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )

            # Add background if specified
            if has_background and background_color:
                padding = 10
                # Parse background color (handle alpha)
                bg_color_hex = (
                    background_color[:7]
                    if len(background_color) > 7
                    else background_color
                )

                bg_clip = (
                    ColorClip(
                        size=(text_width + padding * 2, text_height + padding),
                        color=tuple(
                            int(bg_color_hex[i : i + 2], 16) for i in (1, 3, 5)
                        ),
                    )
                    .with_duration(group_duration)
                    .with_start(group_start)
                )

                bg_clip = bg_clip.with_position(
                    ("center", vertical_position - padding // 2)
                )

                # Apply fade to background
                fade_duration = min(0.2, group_duration / 4)
                bg_clip = (
                    bg_clip.with_effects(
                        [CrossFadeIn(fade_duration), CrossFadeOut(fade_duration)]
                    )
                    if group_duration > 0.5
                    else bg_clip
                )

                subtitle_clips.append(bg_clip)

            # Apply timing and position to text
            text_clip = text_clip.with_duration(group_duration).with_start(group_start)
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create fade subtitle: {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} fade subtitle elements")
    return subtitle_clips


def detect_face_trajectory(
    video_clip: VideoFileClip,
    start_time: float,
    end_time: float,
    sample_interval: float = 1.0,
) -> List[Tuple[float, int, int]]:
    """
    Detect face center positions over time to build a movement trajectory.

    Returns a list of (relative_time, cx, cy) tuples, one per sampled frame.
    Times are relative to start_time (i.e. 0.0 = start_time).
    Falls back gracefully to an empty list on any error.
    """
    trajectory: List[Tuple[float, int, int]] = []
    duration = end_time - start_time
    if duration <= 0:
        return trajectory

    # Use the same detector chain as detect_faces_in_clip but track time
    try:
        mp_face_detection = None
        try:
            import mediapipe as mp
            mp_face_detection = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            )
        except Exception:
            pass

        haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        # Sample at regular intervals
        actual_interval = min(sample_interval, duration / max(4, int(duration)))
        sample_times = []
        t = start_time
        while t < end_time:
            sample_times.append(t)
            t += actual_interval

        for abs_t in sample_times:
            try:
                frame = video_clip.get_frame(abs_t)
                height, width = frame.shape[:2]
                faces_found: List[Tuple[int, int, int, int, float]] = []

                # Try MediaPipe first
                if mp_face_detection is not None:
                    try:
                        results = mp_face_detection.process(frame)
                        if results.detections:
                            for det in results.detections:
                                bbox = det.location_data.relative_bounding_box
                                x = int(bbox.xmin * width)
                                y = int(bbox.ymin * height)
                                w = int(bbox.width * width)
                                h = int(bbox.height * height)
                                if w > 30 and h > 30:
                                    faces_found.append((x, y, w, h, det.score[0]))
                    except Exception:
                        pass

                # Haar fallback
                if not faces_found:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                        faces = haar_cascade.detectMultiScale(
                            gray, scaleFactor=1.05, minNeighbors=3,
                            minSize=(40, 40), maxSize=(int(width * 0.7), int(height * 0.7))
                        )
                        for x, y, w, h in faces:
                            area = w * h
                            conf = min(0.9, 0.3 + (area / (width * height)) * 2)
                            faces_found.append((x, y, w, h, conf))
                    except Exception:
                        pass

                if faces_found:
                    # Pick the most confident / largest face as the primary subject
                    primary = max(faces_found, key=lambda f: f[2] * f[3] * f[4])
                    x, y, w, h, _ = primary
                    cx = x + w // 2
                    cy = y + h // 2
                    rel_t = abs_t - start_time
                    trajectory.append((rel_t, cx, cy))
                else:
                    # P1.2 gap-fill: when no face found, repeat the last known position
                    # instead of leaving a gap. np.interp over sparse points creates
                    # large "jumps" between distant known positions — filling the gap
                    # with the last known position keeps the crop stationary until
                    # the face reappears (no camera jump).
                    if trajectory:
                        last_t, last_cx, last_cy = trajectory[-1]
                        rel_t = abs_t - start_time
                        trajectory.append((rel_t, last_cx, last_cy))

            except Exception as e:
                logger.debug(f"Trajectory sample failed at t={abs_t:.2f}: {e}")
                continue

        if mp_face_detection is not None:
            try:
                mp_face_detection.close()
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Face trajectory detection failed: {e}")

    logger.info(f"Face trajectory: {len(trajectory)} samples over {duration:.1f}s")
    return trajectory


# ─────────────────────────────────────────────────────────────────────────────
# P2.3: Multi-speaker detection — identify active speaker in podcasts/interviews
# ─────────────────────────────────────────────────────────────────────────────

def _mouth_openness(landmarks, img_w: int, img_h: int) -> float:
    """
    Estimate mouth openness from FaceMesh landmarks.
    Uses upper lip (13) and lower lip (14) vertical distance.
    Returns a pixel distance — larger means more open (speaking).
    """
    try:
        upper = landmarks[13]
        lower = landmarks[14]
        dy = abs((lower.y - upper.y) * img_h)
        return float(dy)
    except Exception:
        return 0.0


def detect_active_speaker_trajectory(
    video_clip: "VideoFileClip",
    start_time: float,
    end_time: float,
    sample_interval: float = 0.5,
) -> List[Tuple[float, int, int]]:
    """
    Multi-speaker aware face trajectory.

    When a single face is detected, identical to `detect_face_trajectory`.
    When 2+ faces are detected (podcast / interview / two-shot):
      - Uses MediaPipe FaceMesh mouth-landmark delta to identify the speaker
        (the face with the highest mouth-openness = the one talking).
      - Falls back to largest-face heuristic if FaceMesh is unavailable.

    Returns a list of (relative_time, cx, cy) for the *active* speaker.
    """
    trajectory: List[Tuple[float, int, int]] = []
    duration = end_time - start_time
    if duration <= 0:
        return trajectory

    try:
        # ── Init detectors ────────────────────────────────────────────────────
        mp_face_detection = None
        mp_face_mesh = None
        try:
            import mediapipe as mp  # type: ignore
            mp_face_detection = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            )
            mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=4,
                refine_landmarks=True,
                min_detection_confidence=0.5,
            )
        except Exception:
            pass

        haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        # ── Sampling ─────────────────────────────────────────────────────────
        actual_interval = min(sample_interval, duration / max(4, int(duration)))
        sample_times = []
        t = start_time
        while t < end_time:
            sample_times.append(t)
            t += actual_interval

        for abs_t in sample_times:
            try:
                frame = video_clip.get_frame(abs_t)
                height, width = frame.shape[:2]
                rel_t = abs_t - start_time

                # ── Detect all faces ─────────────────────────────────────────
                # Each entry: (x, y, w, h, confidence)
                all_faces: List[Tuple[int, int, int, int, float]] = []

                if mp_face_detection is not None:
                    try:
                        results = mp_face_detection.process(frame)
                        if results.detections:
                            for det in results.detections:
                                bbox = det.location_data.relative_bounding_box
                                x = int(bbox.xmin * width)
                                y = int(bbox.ymin * height)
                                w = int(bbox.width * width)
                                h = int(bbox.height * height)
                                if w > 30 and h > 30:
                                    all_faces.append((x, y, w, h, float(det.score[0])))
                    except Exception:
                        pass

                if not all_faces:
                    # Haar fallback
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                        faces = haar_cascade.detectMultiScale(
                            gray, scaleFactor=1.05, minNeighbors=3,
                            minSize=(40, 40), maxSize=(int(width * 0.7), int(height * 0.7))
                        )
                        for x, y, w, h in faces:
                            area = w * h
                            conf = min(0.9, 0.3 + (area / (width * height)) * 2)
                            all_faces.append((x, y, w, h, conf))
                    except Exception:
                        pass

                if not all_faces:
                    # No face found — hold last known position
                    if trajectory:
                        _, last_cx, last_cy = trajectory[-1]
                        trajectory.append((rel_t, last_cx, last_cy))
                    continue

                # ── Single face: same as before ───────────────────────────────
                if len(all_faces) == 1:
                    x, y, w, h, _ = all_faces[0]
                    trajectory.append((rel_t, x + w // 2, y + h // 2))
                    continue

                # ── Multi-face: identify active speaker ───────────────────────
                # Strategy A: use FaceMesh mouth-openness on each face ROI
                active_face = None
                if mp_face_mesh is not None:
                    best_openness = -1.0
                    for x, y, w, h, _conf in all_faces:
                        # Crop face ROI with padding
                        pad = int(min(w, h) * 0.1)
                        x1 = max(0, x - pad)
                        y1 = max(0, y - pad)
                        x2 = min(width, x + w + pad)
                        y2 = min(height, y + h + pad)
                        roi = frame[y1:y2, x1:x2]
                        if roi.size == 0:
                            continue
                        try:
                            mesh_result = mp_face_mesh.process(roi)
                            if mesh_result.multi_face_landmarks:
                                lm = mesh_result.multi_face_landmarks[0].landmark
                                roi_h, roi_w = roi.shape[:2]
                                openness = _mouth_openness(lm, roi_w, roi_h)
                                if openness > best_openness:
                                    best_openness = openness
                                    active_face = (x, y, w, h)
                        except Exception:
                            continue

                # Strategy B fallback: pick the face closest to frame center
                # (in podcast setups the main speaker is usually centered)
                if active_face is None:
                    frame_cx = width // 2
                    frame_cy = height // 2
                    active_face = min(
                        all_faces,
                        key=lambda f: abs((f[0] + f[2] // 2) - frame_cx) + abs((f[1] + f[3] // 2) - frame_cy),
                    )[:4]  # drop confidence

                x, y, w, h = active_face
                trajectory.append((rel_t, x + w // 2, y + h // 2))

            except Exception as e:
                logger.debug(f"Multi-speaker sample failed at t={abs_t:.2f}: {e}")
                continue

        # ── Cleanup ───────────────────────────────────────────────────────────
        for detector in [mp_face_detection, mp_face_mesh]:
            if detector is not None:
                try:
                    detector.close()
                except Exception:
                    pass

    except Exception as e:
        logger.warning(f"Active speaker trajectory failed: {e}")

    logger.info(
        f"Multi-speaker trajectory: {len(trajectory)} samples over {duration:.1f}s"
    )
    return trajectory


def _smooth_1d(values: List[float], window: int = 5) -> List[float]:
    """Apply a simple moving-average smoothing over a 1-D list."""
    if len(values) < window:
        return values
    smoothed = []
    half = window // 2
    for i, v in enumerate(values):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        smoothed.append(float(np.mean(values[lo:hi])))
    return smoothed


def create_dynamic_crop_clip(
    clip: VideoFileClip,
    trajectory: List[Tuple[float, int, int]],
    target_w: int,
    target_h: int,
) -> Any:
    """
    Create a new clip where the crop window follows the face trajectory.

    Uses per-frame numpy interpolation so the camera smoothly pans between
    detected face positions.  Falls back to a static centre crop when the
    trajectory is empty or the movement is negligible.
    """
    from moviepy import VideoClip

    orig_w, orig_h = clip.w, clip.h

    if not trajectory:
        # No faces detected — simple centre crop
        x0 = round_to_even(max(0, (orig_w - target_w) // 2))
        y0 = round_to_even(max(0, (orig_h - target_h) // 2))
        return clip.cropped(x1=x0, y1=y0, x2=x0 + target_w, y2=y0 + target_h)

    times = [t for t, _cx, _cy in trajectory]
    raw_cx = [float(cx) for _t, cx, _cy in trajectory]
    raw_cy = [float(cy) for _t, _cx, cy in trajectory]

    # Smooth out jitter — V3: Larger window and Gaussian-weighting simulation
    # We use a moving average but decrease the threshold for "static" to 2%
    smooth_cx = _smooth_1d(raw_cx, window=15) # V3: Window 15 for cinematic smoothness
    smooth_cy = _smooth_1d(raw_cy, window=15)

    # Check if movement is significant (> 2 % of frame dimension - V3 Elite Sensitivity)
    x_range = max(smooth_cx) - min(smooth_cx)
    y_range = max(smooth_cy) - min(smooth_cy)
    if x_range < orig_w * 0.02 and y_range < orig_h * 0.02:
        # Static crop at mean position
        cx = float(np.mean(smooth_cx))
        cy = float(np.mean(smooth_cy))
        x0 = round_to_even(max(0, min(int(cx - target_w // 2), orig_w - target_w)))
        y0 = round_to_even(max(0, min(int(cy - target_h // 2), orig_h - target_h)))
        logger.info("Dynamic crop: negligible movement — using static crop")
        return clip.cropped(x1=x0, y1=y0, x2=x0 + target_w, y2=y0 + target_h)

    logger.info(f"Dynamic crop: x_range={x_range:.0f}px y_range={y_range:.0f}px — animating crop")

    times_arr = np.array(times, dtype=float)
    cx_arr = np.array(smooth_cx, dtype=float)
    cy_arr = np.array(smooth_cy, dtype=float)

    clip_duration = clip.duration
    orig_fps = clip.fps or 30

    def make_frame(t: float):
        frame = clip.get_frame(t)
        # Clamp t to trajectory range
        t_clamped = max(times_arr[0], min(t, times_arr[-1]))
        cx = float(np.interp(t_clamped, times_arr, cx_arr))
        cy = float(np.interp(t_clamped, times_arr, cy_arr))

        x = round_to_even(max(0, min(int(cx - target_w // 2), orig_w - target_w)))
        y = round_to_even(max(0, min(int(cy - target_h // 2), orig_h - target_h)))
        return frame[y:y + target_h, x:x + target_w]

    result = VideoClip(frame_function=make_frame, duration=clip_duration)  # MoviePy 2.x: frame_function (not make_frame)
    result.fps = orig_fps
    if clip.audio is not None:
        result = result.with_audio(clip.audio)
    return result


def _get_background_music_path(config_obj=None) -> Optional[Path]:
    """
    Return a random background music track from the music library folder,
    or None if none are available.

    Music folder: {TEMP_DIR}/music/ (user places royalty-free .mp3/.wav/.aac there)
    Falls back to: /app/music/ (pre-bundled tracks in Docker image)
    P6: Also searches the Pixabay cache dir for auto-downloaded tracks.
    """
    _cfg = config_obj or config
    search_dirs = [
        Path(_cfg.temp_dir) / "music",
        Path("/app/music"),
        Path("/app/backend/music"),
        Path("/tmp/supoclip_music_cache"),  # P6: Pixabay auto-downloaded tracks
    ]
    import random as _random
    for music_dir in search_dirs:
        if music_dir.exists():
            tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav")) + list(music_dir.glob("*.aac"))
            if tracks:
                return _random.choice(tracks)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# P6: Pixabay royalty-free music auto-fetch
# ─────────────────────────────────────────────────────────────────────────────

# Niche → Pixabay search query mapping
_NICHE_MUSIC_MOOD: Dict[str, str] = {
    "finance": "corporate background",
    "fitness": "energetic workout",
    "motivation": "inspiring motivational",
    "tech": "technology innovation",
    "education": "study focus",
    "health": "calm wellness",
    "entertainment": "upbeat fun",
    "gaming": "epic gaming",
    "cooking": "pleasant acoustic",
    "travel": "adventure exploration",
    "general": "background cinematic",
}

_PIXABAY_MUSIC_CACHE = Path("/tmp/supoclip_music_cache")


def fetch_pixabay_music(niche: str = "general", api_key: Optional[str] = None) -> Optional[Path]:
    """
    P6: Fetch a royalty-free background music track from Pixabay API.

    Pixabay API: https://pixabay.com/api/docs/ (free, 100 req/min)
    Requires PIXABAY_API_KEY env variable (same key used for B-roll video).

    Caches downloaded tracks in /tmp/supoclip_music_cache/ so repeated calls
    don't re-download. Cache files are named by query + track ID.

    Returns path to downloaded .mp3 or None if unavailable.
    """
    import urllib.request
    import urllib.parse
    import random as _random

    # Use existing Pixabay key from config
    key = api_key or os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        return None  # No key → silent skip

    mood_query = _NICHE_MUSIC_MOOD.get(niche, _NICHE_MUSIC_MOOD["general"])
    safe_query = urllib.parse.quote(mood_query)

    _PIXABAY_MUSIC_CACHE.mkdir(parents=True, exist_ok=True)

    # Check local cache first (any track matching this niche)
    niche_cached = list(_PIXABAY_MUSIC_CACHE.glob(f"{niche}_*.mp3"))
    if niche_cached:
        return _random.choice(niche_cached)

    try:
        # Pixabay Music API endpoint
        api_url = (
            f"https://pixabay.com/api/videos/music/"
            f"?key={key}&q={safe_query}&per_page=10&min_duration=30"
        )
        req = urllib.request.Request(api_url, headers={"User-Agent": "SupoClip/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        hits = data.get("hits", [])
        if not hits:
            logger.debug(f"Pixabay music: no results for query '{mood_query}'")
            return None

        # Pick a random track from results
        track = _random.choice(hits[:5])  # top 5 for quality
        track_id = track.get("id")
        audio_url = track.get("audio_url") or track.get("url")

        if not audio_url:
            return None

        # Download and cache
        cache_filename = _PIXABAY_MUSIC_CACHE / f"{niche}_{track_id}.mp3"
        logger.info(f"🎵 Downloading Pixabay track: {track.get('title', 'unknown')} ({niche})")

        with urllib.request.urlopen(audio_url, timeout=60) as resp:
            cache_filename.write_bytes(resp.read())

        logger.info(f"✅ Pixabay music cached: {cache_filename.name}")
        return cache_filename

    except Exception as _pix_e:
        logger.debug(f"Pixabay music fetch skipped: {_pix_e}")
        return None


def get_background_music_for_niche(niche: str = "general", config_obj=None) -> Optional[Path]:
    """
    P6: Get background music for a specific niche, trying:
    1. Local music folder (user-placed)
    2. Pixabay API (auto-downloaded, cached)
    3. Any available track from cache
    """
    _cfg = config_obj or config
    import random as _random

    # 1. Check local music folder for niche-tagged tracks
    for music_dir in [Path(_cfg.temp_dir) / "music", Path("/app/music")]:
        if music_dir.exists():
            tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
            if tracks:
                return _random.choice(tracks)

    # 2. Try Pixabay API
    pixabay_track = fetch_pixabay_music(niche)
    if pixabay_track:
        return pixabay_track

    # 3. Fallback: any cached track
    if _PIXABAY_MUSIC_CACHE.exists():
        any_tracks = list(_PIXABAY_MUSIC_CACHE.glob("*.mp3"))
        if any_tracks:
            return _random.choice(any_tracks)

    return None


def mix_background_music(
    video_path: Path,
    output_path: Path,
    music_volume: float = 0.12,
    ducking_enabled: bool = False,
) -> bool:
    """
    Mix a random background music track into a video at low volume (default 12%).
    Uses ffmpeg for fast, high-quality audio mixing.

    Returns True on success, False on failure (original file untouched on failure).
    """
    import subprocess as _sp
    music_path = _get_background_music_path()
    if music_path is None:
        logger.info("No background music tracks found — skipping music mix")
        return False

    logger.info(f"🎵 Mixing background music: {music_path.name} @ {int(music_volume*100)}% volume")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),         # main clip (with speech audio)
            "-i", str(music_path),          # background music
            "-filter_complex",
            (
                f"[1:a]volume={music_volume:.3f},aloop=loop=-1:size=2147483647[music];" +
                (f"[0:a][music]sidechaincompress=threshold=0.1:ratio=20:attack=20:release=100[music_ducked];[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]" 
                 if ducking_enabled else 
                 f"[0:a][music]amix=inputs=2:duration=first:normalize=0[aout]")
            ),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",                # no video re-encode
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-shortest",
            str(output_path),
        ]
        result = _sp.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"Music mix failed: {result.stderr[-300:]}")
            return False
        logger.info(f"✅ Background music mixed into {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Music mix error: {e}")
        return False


def create_optimized_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    output_path: Path,
    add_subtitles: bool = True,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
    split_screen: bool = False,
    hook_title: Optional[str] = None,
    camera_plan: Optional[List[Dict[str, Any]]] = None,
    sync_offset: float = 0.0,
    secondary_video_path: Optional[Path] = None,
    segment: Optional[Dict[str, Any]] = None,
    elite_metadata: Optional[Dict[str, Any]] = None,
    gpu_encoding_settings: Optional[Dict[str, Any]] = None,
) -> bool:
    """Create a high-quality clip with Senior-level resource management (ResourceGuard)."""
    if segment is None:
        segment = {}
    guard = ResourceGuard()
    try:
        with guard.manage():
            # 1. Word Boundary Snapping
            start_time, end_time = snap_to_word_boundary(video_path, start_time, end_time)
            duration = end_time - start_time
            if duration <= 0:
                logger.error(f"Invalid clip duration: {duration:.1f}s")
                return False

            keep_original = output_format == "original"
            logger.info(f"🚀 Render Start: {start_time:.1f}s-{end_time:.1f}s (Guard Active)")

            # 2. Fast Path (ffmpeg stream copy) - No Guard needed for objects since none are created
            if not add_subtitles and keep_original and not camera_plan:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(start_time), "-i", str(video_path), "-t", str(duration), "-c", "copy", "-movflags", "+faststart", str(output_path)],
                    capture_output=True, text=True, timeout=300
                )
                if result.returncode == 0:
                    return True

            # 3. Load & Track Master Resources
            main_video = guard.track(VideoFileClip(str(video_path)))
            
            # Multi-Angle Intelligence (Phase 1)
            if camera_plan and secondary_video_path and Path(secondary_video_path).exists():
                logger.info("🎬 Multi-Angle Switcher Active: Orchestrating Cut List")
                secondary_video = guard.track(VideoFileClip(str(secondary_video_path)))
                cut_clips = []
                
                for cut in camera_plan:
                    cut_start = max(start_time, cut["start"])
                    cut_end = min(end_time, cut["end"])
                    
                    if cut_start >= cut_end:
                        continue
                        
                    if cut["angle"] == 0:
                        # Angle 1
                        angle_clip = main_video.subclipped(cut_start, cut_end)
                    else:
                        # Angle 2 (with offset)
                        sec_start = cut_start - sync_offset
                        sec_end = cut_end - sync_offset
                        # Clamp to secondary duration
                        sec_start = max(0, min(sec_start, secondary_video.duration))
                        sec_end = max(0, min(sec_end, secondary_video.duration))
                        if sec_start >= sec_end:
                            angle_clip = main_video.subclipped(cut_start, cut_end)
                        else:
                            angle_clip = secondary_video.subclipped(sec_start, sec_end)
                    
                    cut_clips.append(angle_clip)
                
                if cut_clips:
                    from moviepy import concatenate_videoclips
                    # Concatenate the cuts into a single master clip for further processing (crop/subtitles)
                    clip = guard.track(concatenate_videoclips(cut_clips))
                else:
                    clip = guard.track(main_video.subclipped(start_time, min(end_time, main_video.duration)))
            else:
                clip = guard.track(main_video.subclipped(start_time, min(end_time, main_video.duration)))

            # 4. Process Geometry
            if keep_original:
                processed_clip = clip
                target_width, target_height = round_to_even(clip.w), round_to_even(clip.h)
                if (target_width, target_height) != (clip.w, clip.h):
                    processed_clip = guard.track(clip.resized((target_width, target_height)))
            else:
                # Compute target 9:16 dimensions
                orig_w, orig_h = main_video.w, main_video.h
                target_ratio = 9 / 16
                if orig_w / orig_h > target_ratio:
                    new_width = round_to_even(int(orig_h * target_ratio))
                    new_height = round_to_even(orig_h)
                else:
                    new_width = round_to_even(orig_w)
                    new_height = round_to_even(int(orig_w / target_ratio))
                target_width, target_height = new_width, new_height

                # P2.3: Multi-speaker aware crop — detect_active_speaker_trajectory
                # handles 2+ faces (podcasts/interviews) by identifying who is speaking
                # via MediaPipe FaceMesh mouth-openness analysis, falling back to the
                # most-centered face when FaceMesh is unavailable.
                trajectory = detect_active_speaker_trajectory(
                    main_video, start_time, end_time
                )
                cropped_clip = guard.track(
                    create_dynamic_crop_clip(clip, trajectory, target_width, target_height)
                )
                processed_clip = cropped_clip

            # 4.5 Zoom Punch-In: scale 1.05 → 1.0 over first 0.4s for viral "punch" feel
            # This subtle zoom is characteristic of professional TikTok/Reels editing.
            try:
                _clip_dur = processed_clip.duration or duration
                _punch_dur = min(0.4, _clip_dur * 0.08)  # 0.4s or 8% of clip, whichever smaller
                if _punch_dur > 0.1 and _clip_dur > 1.0:
                    from moviepy import VideoClip as _VC

                    _base_clip = processed_clip  # capture for closure
                    _pw = target_width
                    _ph = target_height

                    def _zoom_frame(t: float):
                        frame = _base_clip.get_frame(t)
                        # Ease-out zoom: starts at 1.05, reaches 1.0 by _punch_dur
                        if t < _punch_dur:
                            progress = t / _punch_dur          # 0 → 1
                            ease = 1.0 - (1.0 - progress) ** 2  # ease-out quad
                            scale = 1.05 - 0.05 * ease          # 1.05 → 1.0
                        else:
                            scale = 1.0
                        if scale <= 1.0 or frame.shape[0] < 2 or frame.shape[1] < 2:
                            return frame
                        # Crop center to simulate zoom
                        h, w = frame.shape[:2]
                        new_h = int(h / scale)
                        new_w = int(w / scale)
                        y0 = (h - new_h) // 2
                        x0 = (w - new_w) // 2
                        cropped = frame[y0:y0 + new_h, x0:x0 + new_w]
                        import cv2 as _cv2
                        return _cv2.resize(cropped, (w, h), interpolation=_cv2.INTER_LINEAR)

                    _zoomed = _VC(frame_function=_zoom_frame, duration=_clip_dur)
                    _zoomed.fps = processed_clip.fps or 30
                    if processed_clip.audio is not None:
                        _zoomed = _zoomed.with_audio(processed_clip.audio)
                    processed_clip = guard.track(_zoomed)
                    logger.debug(f"✨ Zoom punch-in applied ({_punch_dur:.2f}s)")
            except Exception as _zoom_e:
                logger.warning(f"Zoom punch-in skipped: {_zoom_e}")

            # 4.6 V3 Elite VFX Engine (Shake, Pulse)
            try:
                intensity = segment.get("intensity", "medium")
                vfx = segment.get("vfx_trigger")
                
                if intensity == "high" or vfx in ["camera_shake", "zoom_pulse"]:
                    from moviepy import VideoClip as _VC
                    _base_vfx = processed_clip
                    _vw, _vh = target_width, target_height
                    _dur = processed_clip.duration
                    
                    def _vfx_frame(t: float):
                        frame = _base_vfx.get_frame(t)
                        # Base Shake for high intensity
                        dx, dy = 0, 0
                        if intensity == "high" or vfx == "camera_shake":
                            import random
                            dx = random.randint(-4, 4)
                            dy = random.randint(-4, 4)
                        
                        # Rhythmic Pulse for zoom_pulse
                        scale = 1.0
                        if vfx == "zoom_pulse":
                            # Pulse at 2Hz
                            import math
                            scale = 1.0 + 0.02 * math.sin(t * 2 * math.pi * 2)
                        
                        if dx == 0 and dy == 0 and scale == 1.0:
                            return frame
                            
                        h, w = frame.shape[:2]
                        if scale != 1.0:
                            new_h, new_w = int(h / scale), int(w / scale)
                            y0, x0 = (h - new_h) // 2, (w - new_w) // 2
                            frame = frame[y0:y0+new_h, x0:x0+new_w]
                            import cv2
                            frame = cv2.resize(frame, (w, h))
                            
                        # Shift for shake
                        if dx != 0 or dy != 0:
                            M = np.float32([[1, 0, dx], [0, 1, dy]])
                            import cv2
                            frame = cv2.warpAffine(frame, M, (w, h))
                        return frame
                    
                    _vfx_clip = _VC(frame_function=_vfx_frame, duration=_dur)
                    _vfx_clip.fps = processed_clip.fps or 30
                    if processed_clip.audio is not None:
                        _vfx_clip = _vfx_clip.with_audio(processed_clip.audio)
                    processed_clip = guard.track(_vfx_clip)
            except Exception as _vfx_e:
                logger.warning(f"V3 VFX engine skipped: {_vfx_e}")

            # 4.7 V4 Elite Omnimodal VFX Engine
            if elite_metadata:
                try:
                    logger.info("✨ V4 Elite VFX Engine: Applying omnimodal creative cues")
                    vfx_cfg = elite_metadata.get("vfx", {})
                    audio_cfg = elite_metadata.get("audio", {})
                    
                    # A. Dynamic Elite Zoom (Multimodal Grounded)
                    target_zoom = vfx_cfg.get("zoom_level", 1.0)
                    if target_zoom > 1.0:
                        from moviepy import VideoClip as _VC
                        _base_zoom = processed_clip
                        _z_dur = processed_clip.duration
                        
                        def _elite_zoom_frame(t: float):
                            frame = _base_zoom.get_frame(t)
                            # Apply the specific zoom level chosen by the AI Director
                            scale = target_zoom
                            if scale <= 1.0: return frame
                            h, w = frame.shape[:2]
                            new_h, new_w = int(h / scale), int(w / scale)
                            y0, x0 = (h - new_h) // 2, (w - new_w) // 2
                            cropped = frame[y0:y0+new_h, x0:x0+new_w]
                            import cv2
                            return cv2.resize(cropped, (w, h))
                            
                        _zoom_clip = _VC(frame_function=_elite_zoom_frame, duration=_z_dur)
                        _zoom_clip.fps = processed_clip.fps or 30
                        if processed_clip.audio: _zoom_clip = _zoom_clip.with_audio(processed_clip.audio)
                        processed_clip = guard.track(_zoom_clip)

                    # B. Audio Elite Direction (Duck & Sync)
                    if audio_cfg.get("volume_ducking", True) and processed_clip.audio:
                        from moviepy import AudioFileClip
                        # P0: Basic ducking logic — can be expanded in later P2 steps
                        # Ducking logic would typically be applied during final composition mix
                        logger.debug("🎵 Audio Director: volume_ducking enabled")
                        # P0: Re-run music mix with ducking enabled
                        if output_path.exists():
                            temp_duck = output_path.parent / f"duck_{output_path.name}"
                            if mix_background_music(output_path, temp_duck, ducking_enabled=True):
                                import os
                                os.replace(temp_duck, output_path)

                except Exception as _elite_e:
                    logger.warning(f"V4 Elite VFX engine failed: {_elite_e}")

            # 5. Composite Stack
            final_stack = [processed_clip]

            # Subtitles
            if add_subtitles:
                subtitle_clips = create_assemblyai_subtitles(
                    video_path, start_time, end_time, target_width, target_height,
                    font_family, font_size, font_color, caption_template
                )
                for s_clip in subtitle_clips:
                    final_stack.append(guard.track(s_clip))

                # Keyword emoji overlays — small emoji next to captions when viral
                # keywords are spoken (e.g., "dinero" → 💰, "increíble" → 🔥).
                # Non-fatal: silently skipped if Twemoji CDN unreachable or PIL missing.
                try:
                    from .utils.emoji_utils import create_keyword_emoji_overlays
                    from .utils.emoji_utils import KEYWORD_EMOJI_MAP
                    transcript_data = load_cached_transcript_data(video_path)
                    if transcript_data and transcript_data.get("words"):
                        relevant_words = get_words_in_range(transcript_data, start_time, end_time)
                        if relevant_words:
                            # Re-use adaptive grouping to align emoji timing with caption groups
                            _tmpl = get_template(caption_template)
                            _fs = get_scaled_font_size(_tmpl.get("font_size", 28), target_width)
                            _word_groups = adaptive_word_groups(relevant_words, target_width, _fs)
                            _caption_y = _tmpl.get("position_y", 0.75)
                            kw_emoji_clips = create_keyword_emoji_overlays(
                                _word_groups, target_width, target_height, _caption_y
                            )
                            for _kw_clip in kw_emoji_clips:
                                final_stack.append(guard.track(_kw_clip))
                            if kw_emoji_clips:
                                logger.debug(f"✨ {len(kw_emoji_clips)} keyword emoji overlay(s) added")
                except Exception as _kw_e:
                    logger.debug(f"Keyword emoji overlays skipped: {_kw_e}")

            # Split Screen
            if split_screen:
                processed_clip = guard.track(processed_clip.resized(width=target_width, height=target_height // 2).with_position(("center", "top")))
                final_stack[0] = processed_clip
                
                stock_dir = Path(config.temp_dir) / "stock_broll"
                satisfying_videos = list(stock_dir.glob("*.mp4"))
                if satisfying_videos:
                    bottom_clip = guard.track(VideoFileClip(str(satisfying_videos[0])).subclipped(0, duration))
                    bottom_clip = guard.track(bottom_clip.resized(width=target_width, height=target_height // 2).with_position(("center", "bottom")))
                    final_stack.append(bottom_clip)

            # Hook Title
            if hook_title:
                # Resolve hook font to a real file path — never pass an empty string or
                # bare font name to TextClip (MoviePy 2.x requires a valid filesystem path).
                _hook_resolved = (
                    find_font_path(font_family)
                    or find_font_path("TikTokSans-Regular")
                    or find_font_path("THEBOLDFONT")
                )
                if not _hook_resolved:
                    from .font_registry import FONTS_DIR, SUPPORTED_FONT_EXTENSIONS
                    for _ext in SUPPORTED_FONT_EXTENSIONS:
                        _cands = sorted(FONTS_DIR.glob(f"*{_ext}"))
                        if _cands:
                            _hook_resolved = _cands[0]
                            break
                hook_font = str(_hook_resolved) if _hook_resolved else None
                from moviepy import TextClip
                if hook_font is None:
                    logger.warning("⚠️ No font available for hook title — skipping hook overlay")
                else:
                    hook_text = guard.track(
                        TextClip(
                            text=hook_title.upper(),
                            font=hook_font,
                            font_size=min(target_width // 10, 80),
                            color="yellow",
                            stroke_color="black",
                            stroke_width=3,
                            method="label",
                            duration=min(3.0, duration),
                        ).with_position(("center", 0.15), relative=True)
                        .with_effects([FadeIn(0.3), FadeOut(0.3)])
                    )
                    final_stack.append(hook_text)

            # AI B-roll Integration (Phase 2)
            ai_broll_path = segment.get("ai_broll_path")
            if ai_broll_path:
                try:
                    logger.info(f"🎞️ Injecting AI B-roll: {ai_broll_path}")
                    with guard.manage():
                        kb_clip = create_ken_burns_clip(
                            ai_broll_path,
                            duration=3.0, # Standard B-roll duration
                            target_res=(target_width, target_height)
                        )
                        # Position it to cover the main video partially or fully
                        kb_clip = kb_clip.with_start(1.0).with_effects([FadeIn(0.5)]) # Start 1s into segment
                        final_stack.append(kb_clip)
                except Exception as e:
                    logger.error(f"Failed to overlay AI B-roll: {e}")

            # B-roll Overlay
            broll_suggestions = segment.get("broll_suggestions")
            if broll_suggestions and not split_screen:
                # B-6 fix: pass guard so B-roll clips are tracked and closed properly
                final_stack = apply_broll_to_clip_objects(final_stack, broll_suggestions, start_time, end_time, guard=guard)

            # Emoji Overlays — displayed in top-right corner for first 2.5s of clip.
            # Emojis are selected based on hook_type and content niche, downloaded from
            # Twemoji CDN and cached locally. Non-fatal if unavailable.
            try:
                from .utils.emoji_utils import get_clip_emojis, make_emoji_clip
                _hook_t = segment.get("hook_type", "none")
                _niche_t = segment.get("niche", "general")
                _emojis = get_clip_emojis(_hook_t, _niche_t)
                _emoji_size = max(60, target_width // 10)   # responsive size
                _emoji_show_dur = min(2.5, duration * 0.25)  # max 25% of clip

                for _ei, _em in enumerate(_emojis[:2]):
                    _em_clip = make_emoji_clip(_em, _emoji_size, _emoji_show_dur, start=0.0)
                    if _em_clip is not None:
                        # Position: top-right, stacked vertically if 2 emojis
                        _right_margin = max(10, target_width // 20)
                        _top_margin = max(10, target_height // 15) + _ei * (_emoji_size + 8)
                        _em_pos = (target_width - _emoji_size - _right_margin, _top_margin)
                        _em_clip = guard.track(_em_clip.with_position(_em_pos))
                        final_stack.append(_em_clip)
                        logger.debug(f"✨ Emoji overlay added: {_em}")
            except Exception as _emoji_e:
                logger.debug(f"Emoji overlays skipped: {_emoji_e}")

            # 6. Final Composition & Write
            final_clip = guard.track(CompositeVideoClip(final_stack) if len(final_stack) > 1 else processed_clip)

            # 7. Elite Audio Production (Phase 2)
            try:
                _niche = segment.get("niche", "general")
                # A. Viral BGM with Ducking
                final_clip = mix_background_music(final_clip, _niche, guard=guard)
                
                # B. Sync SFX (Dings/Pops) with subtitle events
                if add_subtitles:
                    final_clip = apply_sfx_to_clip(final_clip, subtitle_clips, guard=guard)
                    
                logger.info("🎵 Elite Audio Production complete (BGM + SFX Sync)")
            except Exception as _audio_e:
                logger.warning(f"Elite Audio Production skipped: {_audio_e}")

            # 8. Smooth Fade-in / Fade-out (0.3s each)
            try:
                _fade_dur = min(0.3, final_clip.duration * 0.08)  # never exceed 8% of clip
                if _fade_dur > 0.05 and final_clip.duration > 1.0:
                    final_clip = guard.track(
                        final_clip.with_effects([FadeIn(_fade_dur), FadeOut(_fade_dur)])
                    )
            except Exception as _fade_e:
                logger.debug(f"Fade effects skipped: {_fade_e}")

            # 7. Write final clip with GPU acceleration if available
            processor = VideoProcessor(font_family, font_size, font_color)
            
            # Use GPU settings if provided (passed from task_service), else fallback to CPU
            if gpu_encoding_settings:
                encoding_settings = gpu_encoding_settings
                logger.info(f"✨ Using GPU encoding: {encoding_settings.get('codec')}")
            else:
                encoding_settings = processor.get_optimal_encoding_settings("high")
                logger.info("Using CPU encoding (libx264)")

            # Diagnostic log with full clip properties
            _has_audio = final_clip.audio is not None
            _fps_used = clip.fps or 30
            logger.info(
                f"🎬 Pre-write: output={output_path} | "
                f"size={final_clip.w}x{final_clip.h} | "
                f"duration={final_clip.duration:.1f}s | "
                f"fps={_fps_used} | "
                f"has_audio={_has_audio} | "
                f"codec={encoding_settings.get('codec')} | "
                f"ffmpeg_params={encoding_settings.get('ffmpeg_params')}"
            )
            try:
                final_clip.write_videofile(
                    str(output_path),
                    temp_audiofile=str(output_path.parent / f"temp-audio-{output_path.stem}.m4a"),
                    remove_temp=True, logger=None, fps=_fps_used, **encoding_settings
                )
                logger.info(f"✅ write_videofile finished")
            except Exception as write_e:
                # FIX 1b: If GPU codec (h264_qsv, h264_nvenc, etc.) failed, retry with libx264
                if encoding_settings.get("codec") not in (None, "libx264"):
                    logger.warning(
                        f"⚠️ GPU encoding ({encoding_settings.get('codec')}) failed, "
                        f"retrying with libx264 fallback: {write_e}"
                    )
                    _cpu_fallback = {
                        "codec": "libx264",
                        "audio_codec": "aac",
                        "preset": "fast",
                        "ffmpeg_params": ["-crf", "23", "-pix_fmt", "yuv420p"],
                    }
                    final_clip.write_videofile(
                        str(output_path),
                        temp_audiofile=str(output_path.parent / f"temp-audio-{output_path.stem}.m4a"),
                        remove_temp=True, logger=None, fps=_fps_used, **_cpu_fallback
                    )
                    logger.info(f"✅ write_videofile finished (libx264 fallback)")
                else:
                    import traceback as _tb, datetime as _dt
                    _trace = _tb.format_exc()
                    logger.error(f"❌ write_videofile raised: {write_e}\n{_trace}")
                    # Write to BOTH locations: clips volume AND src mount (accessible from VM)
                    for _debug_dir in [Path("/app/temp/uploads/clips"), Path("/app/src")]:
                        try:
                            _debug_dir.mkdir(parents=True, exist_ok=True)
                            with open(_debug_dir / "render_errors.log", "a") as _f:
                                _f.write(f"\n=== {_dt.datetime.now().isoformat()} ===\n")
                                _f.write(f"output_path: {output_path}\nencoding_settings: {encoding_settings}\nerror: {write_e}\n{_trace}\n")
                        except Exception:
                            pass
                    raise

            logger.info(f"✅ Render Complete: {output_path}")
            return True

    except Exception as e:
        import traceback as _tb2, datetime as _dt2
        tb = _tb2.format_exc()
        logger.error(f"❌ Render Failed [{output_path}]: {e}\n{tb}")
        # Also write outer failures to src mount
        try:
            with open(Path("/app/src") / "render_errors.log", "a") as _f:
                _f.write(f"\n=== {_dt2.datetime.now().isoformat()} [OUTER] ===\n")
                _f.write(f"output_path: {output_path}\nerror: {e}\n{tb}\n")
        except Exception:
            pass
        return False
    # Guard.manage() takes care of cleanup automatically


def _render_segment_task(kwargs):
    """Helper for parallel rendering task."""
    try:
        video_path = kwargs.pop("video_path")
        start_seconds = kwargs.pop("start_seconds")
        end_seconds = kwargs.pop("end_seconds")
        clip_path = kwargs.pop("clip_path")
        segment = kwargs.pop("segment")
        index = kwargs.pop("index")
        task_id = kwargs.get("task_id", "unknown")
        
        broadcast_telemetry(task_id, index + 1, 10, f"Worker {index+1} starting render...")

        success = create_optimized_clip(
            video_path=video_path,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            output_path=clip_path,
            **kwargs
        )
        
        if success:
            duration = end_seconds - start_seconds
            return {
                "clip_id": index + 1,
                "filename": clip_path.name,
                "path": str(clip_path),
                "start_time": segment["start_time"],
                "end_time": segment["end_time"],
                "duration": duration,
                "text": segment["text"],
                "relevance_score": segment["relevance_score"],
                "reasoning": segment["reasoning"],
                "virality_score": segment.get("virality_score", 0),
                "hook_score": segment.get("hook_score", 0),
                "engagement_score": segment.get("engagement_score", 0),
                "value_score": segment.get("value_score", 0),
                "shareability_score": segment.get("shareability_score", 0),
                "hook_type": segment.get("hook_type"),
            }
        return None
    except Exception as e:
        logger.error(f"Parallel task failed: {e}")
        return None

def create_clips_from_segments(
    video_path: Path,
    segments: List[Dict[str, Any]],
    output_dir: Path,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
    add_subtitles: bool = True,
    task_id: str = "unknown",
) -> List[Dict[str, Any]]:
    """Create optimized video clips from segments with parallel multi-processing."""
    logger.info(
        f"🚀 V3 Parallel Engine: Creating {len(segments)} clips [Subtitles={add_subtitles}]"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    clips_info = []
    
    # We limit workers to avoid memory starvation on small VMs/Docker containers
    cpu_count = multiprocessing.cpu_count()
    max_workers = min(len(segments), max(2, cpu_count - 1))
    
    tasks = []
    for i, segment in enumerate(segments):
        start_seconds = parse_timestamp_to_seconds(segment["start_time"])
        end_seconds = parse_timestamp_to_seconds(segment["end_time"])
        
        if (end_seconds - start_seconds) <= 0:
            continue
            
        clip_filename = f"clip_{i + 1}_{segment['start_time'].replace(':', '')}-{segment['end_time'].replace(':', '')}.mp4"
        clip_path = output_dir / clip_filename
        
        tasks.append({
            "video_path": video_path,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "clip_path": clip_path,
            "add_subtitles": add_subtitles,
            "font_family": font_family,
            "font_size": font_size,
            "font_color": font_color,
            "caption_template": caption_template,
            "output_format": output_format,
            "segment": segment,
            "index": i,
            "task_id": task_id
        })

    logger.info(f"⚡ Spawning {max_workers} render workers...")
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_clip = {executor.submit(_render_segment_task, task): task for task in tasks}
        for future in as_completed(future_to_clip):
            result = future.result()
            if result:
                clips_info.append(result)
                broadcast_telemetry(task_id, result['clip_id'], 100, "Clip finalized")
                logger.info(f"✅ Finished clip {result['clip_id']}")

    # Sort results to maintain original order
    clips_info.sort(key=lambda x: x["clip_id"])
    logger.info(f"🚀 V3 Rendering Finished: {len(clips_info)}/{len(segments)} clips successful")

    # Phase 5: Generate High-Contrast AI Thumbnail for each clip
    # We do this after parallel rendering to avoid MoviePy resource conflicts
    from .services.thumbnail_service import generate_viral_thumbnail
    for clip in clips_info:
        thumbnail_filename = clip["filename"].replace(".mp4", ".png")
        thumbnail_path = output_dir / "thumbnails" / thumbnail_filename
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)

        # Get first 3 words for thumbnail text
        words = clip["text"].split()[:3]
        thumb_text = " ".join(words) if words else "WATCH THIS"

        generate_viral_thumbnail(
            video_path=clip["path"],
            output_path=str(thumbnail_path),
            text=thumb_text
        )
        clip["thumbnail"] = str(thumbnail_path)

    # Phase 5: Create Production Bundle (Zip Asset Archive)
    bundle_path = output_dir / "viraclip_production_bundle.zip"
    try:
        with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for clip in clips_info:
                # Add clip mp4
                zipf.write(clip["path"], f"clips/{clip['filename']}")
                # Add thumbnail png
                if "thumbnail" in clip:
                    zipf.write(clip["thumbnail"], f"thumbnails/{Path(clip['thumbnail']).name}")
        logger.info(f"🎁 Production Bundle Ready: {bundle_path.name}")
    except Exception as e:
        logger.error(f"Failed to create production bundle: {e}")

    return clips_info


def apply_broll_to_clip_objects(
    clips: List[Any],
    suggestions: List[Dict[str, Any]],
    start_time: float,
    end_time: float,
    guard: Optional[Any] = None,
) -> List[Any]:
    """Insert B-roll clips over the main video as MoviePy objects.

    Ensures every VideoFileClip opened here is tracked in *guard* (if provided)
    so the ResourceGuard can close them when the clip is done rendering.
    Falls back to manual close-on-error if guard is not supplied.

    B-6 fix: pass guard from create_optimized_clip so clips are never leaked.
    """
    opened_brolls: List[Any] = []  # fallback track for guard-less error paths
    try:
        main_clip = clips[0]
        new_clips = [main_clip]

        for sugg in suggestions:
            broll_path = sugg.get("video_path")
            if not broll_path or not Path(broll_path).exists():
                continue

            # Calculate relative start in the current clip
            timestamp = sugg.get("timestamp") or 0
            rel_start = timestamp - start_time
            if rel_start < 0 or rel_start >= main_clip.duration:
                continue

            broll_raw = None
            try:
                broll_raw = VideoFileClip(str(broll_path))
                opened_brolls.append(broll_raw)

                broll_duration = min(4.0, main_clip.duration - rel_start, broll_raw.duration)
                if broll_duration <= 0.5:
                    continue

                broll_sub = broll_raw.subclipped(0, broll_duration)

                # Ken Burns slow-zoom effect on video B-roll: 1.0→1.12 over the clip
                # Gives B-roll a "cinematic insert" feel used by OpusClip and Quso AI.
                try:
                    _bw, _bh = broll_sub.w, broll_sub.h
                    _bdur = broll_sub.duration
                    _bbase = broll_sub

                    def _kb_frame(t: float):
                        frame = _bbase.get_frame(t)
                        progress = t / max(_bdur, 0.001)
                        scale = 1.0 + 0.12 * progress  # 1.0 → 1.12 linear zoom-in
                        h, w = frame.shape[:2]
                        new_h = int(h / scale)
                        new_w = int(w / scale)
                        y0 = (h - new_h) // 2
                        x0 = (w - new_w) // 2
                        cropped = frame[y0:y0 + new_h, x0:x0 + new_w]
                        import cv2 as _cv2
                        return _cv2.resize(cropped, (w, h), interpolation=_cv2.INTER_LINEAR)

                    from moviepy import VideoClip as _BVC
                    _kb = _BVC(frame_function=_kb_frame, duration=_bdur)
                    _kb.fps = broll_sub.fps or 30
                    broll_sub = _kb
                    logger.debug("Ken Burns zoom applied to B-roll")
                except Exception as _kb_e:
                    logger.debug(f"Ken Burns skipped for B-roll: {_kb_e}")

                broll = (
                    broll_sub
                    .resized(main_clip.size)
                    .with_start(rel_start)
                    .with_position("center")
                    .with_effects([FadeIn(0.25), FadeOut(0.25)])
                )
                # B-6 fix: register with ResourceGuard if available
                if guard is not None:
                    broll = guard.track(broll)
                new_clips.append(broll)

            except Exception as broll_err:
                logger.warning(f"B-roll clip skipped ({broll_path}): {broll_err}")
                continue

        # Return merged list (keeping subtitles/overlays already present)
        return new_clips + clips[1:]

    except Exception as e:
        logger.error(f"B-roll compositing failed: {e}")
        # Close any raw handles that were opened but not yet composited
        for handle in opened_brolls:
            try:
                handle.close()
            except Exception:
                pass
        return clips


def get_available_transitions() -> List[str]:
    """Get list of available transition video files."""
    transitions_dir = Path(__file__).parent.parent / "transitions"
    if not transitions_dir.exists():
        logger.warning("Transitions directory not found")
        return []

    transition_files = []
    for file_path in transitions_dir.glob("*.mp4"):
        transition_files.append(str(file_path))

    logger.info(f"Found {len(transition_files)} transition files")
    return transition_files


def apply_transition_effect(
    clip1_path: Path, clip2_path: Path, transition_path: Path, output_path: Path
) -> bool:
    """Apply transition effect between two clips using a transition video."""
    clip1 = None
    clip2 = None
    transition = None
    clip1_tail = None
    clip2_intro = None
    clip2_remainder = None
    intro_segment = None
    final_clip = None

    try:
        from moviepy import VideoFileClip, CompositeVideoClip, concatenate_videoclips

        # Load clips
        clip1 = VideoFileClip(str(clip1_path))
        clip2 = VideoFileClip(str(clip2_path))
        transition = VideoFileClip(str(transition_path))

        # Keep the transition window within both clips so the output still matches
        # the current clip's duration and metadata.
        transition_duration = min(1.5, transition.duration, clip1.duration, clip2.duration)
        if transition_duration <= 0:
            logger.warning("Transition duration is zero, skipping transition effect")
            return False

        transition = transition.subclipped(0, transition_duration)

        # Resize transition to match clip dimensions
        clip_size = clip2.size
        transition = transition.resized(clip_size)

        # Build a transition intro from the previous clip tail over the first
        # part of the current clip so the exported file keeps clip2's duration.
        clip1_tail_start = max(0, clip1.duration - transition_duration)
        clip1_tail = clip1.subclipped(clip1_tail_start, clip1.duration).with_effects(
            [FadeOut(transition_duration)]
        )
        clip2_intro = clip2.subclipped(0, transition_duration).with_effects(
            [FadeIn(transition_duration)]
        )

        intro_segment = CompositeVideoClip(
            [clip1_tail, clip2_intro, transition], size=clip_size
        ).with_duration(transition_duration)
        if clip2_intro.audio is not None:
            intro_segment = intro_segment.with_audio(clip2_intro.audio)

        final_segments = [intro_segment]
        if clip2.duration > transition_duration:
            clip2_remainder = clip2.subclipped(transition_duration, clip2.duration)
            final_segments.append(clip2_remainder)

        final_clip = (
            concatenate_videoclips(final_segments, method="compose")
            if len(final_segments) > 1
            else intro_segment
        )

        # Write output
        processor = VideoProcessor()
        encoding_settings = processor.get_optimal_encoding_settings("high")

        final_clip.write_videofile(
            str(output_path),
            temp_audiofile=str(output_path.parent / f"temp-audio-{output_path.stem}.m4a"),
            remove_temp=True,
            logger=None,
            **encoding_settings,
        )

        logger.info(f"Applied transition effect: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error applying transition effect: {e}")
        return False
    finally:
        for clip in (
            final_clip,
            intro_segment,
            clip2_remainder,
            clip2_intro,
            clip1_tail,
            transition,
            clip2,
            clip1,
        ):
            if clip is not None:
                try:
                    clip.close()
                except Exception:
                    pass


def create_clips_with_transitions(
    video_path: Path,
    segments: List[Dict[str, Any]],
    output_dir: Path,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
    add_subtitles: bool = True,
    task_id: str = "unknown",
) -> List[Dict[str, Any]]:
    """Create standalone video clips without inter-clip transitions.

    Kept as a backward-compatible wrapper for older call sites.
    """
    logger.info(
        f"Creating {len(segments)} standalone clips subtitles={add_subtitles} template '{caption_template}'"
    )
    logger.info(
        "Inter-clip transitions are disabled for standalone SupoClip exports"
    )
    return create_clips_from_segments(
        video_path,
        segments,
        output_dir,
        font_family,
        font_size,
        font_color,
        caption_template,
        output_format,
        add_subtitles,
        task_id,
    )


# Backward compatibility functions

def create_9_16_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    output_path: Path,
    subtitle_text: str = "",
) -> bool:
    """Backward compatibility wrapper."""
    return create_optimized_clip(
        video_path, start_time, end_time, output_path, add_subtitles=bool(subtitle_text)
    )


# B-Roll compositing functions


def insert_broll_into_clip(
    main_clip_path: Path,
    broll_path: Path,
    insert_time: float,
    broll_duration: float,
    output_path: Path,
    transition_duration: float = 0.3,
) -> bool:
    """
    Insert B-roll footage into a clip at a specified timestamp.

    Args:
        main_clip_path: Path to the main video clip
        broll_path: Path to the B-roll video
        insert_time: When to insert B-roll (seconds from clip start)
        broll_duration: How long to show B-roll (seconds)
        output_path: Where to save the composited clip
        transition_duration: Crossfade duration (seconds)

    Returns:
        True if successful
    """
    try:
        from moviepy import VideoFileClip, CompositeVideoClip, concatenate_videoclips
        from moviepy.video.fx import CrossFadeIn, CrossFadeOut

        # Load clips
        main_clip = VideoFileClip(str(main_clip_path))
        broll_clip = VideoFileClip(str(broll_path))

        # Get main clip dimensions
        target_width, target_height = main_clip.size

        # Resize B-roll to match main clip (9:16 aspect ratio)
        broll_resized = resize_for_916(broll_clip, target_width, target_height)

        # Ensure B-roll doesn't exceed requested duration
        actual_broll_duration = min(broll_duration, broll_resized.duration)
        broll_trimmed = broll_resized.subclipped(0, actual_broll_duration)

        # Ensure insert_time is within clip bounds
        insert_time = max(0, min(insert_time, main_clip.duration - 0.5))

        # Calculate end time for B-roll
        broll_end_time = insert_time + actual_broll_duration

        # Don't let B-roll extend past the main clip
        if broll_end_time > main_clip.duration:
            broll_end_time = main_clip.duration
            actual_broll_duration = broll_end_time - insert_time
            broll_trimmed = broll_resized.subclipped(0, actual_broll_duration)

        # Split main clip into three parts
        part1 = main_clip.subclipped(0, insert_time) if insert_time > 0 else None
        part2_audio = main_clip.subclipped(insert_time, broll_end_time).audio
        part3 = (
            main_clip.subclipped(broll_end_time)
            if broll_end_time < main_clip.duration
            else None
        )

        # Apply crossfade to B-roll
        if transition_duration > 0:
            broll_with_audio = broll_trimmed.with_audio(part2_audio)
            broll_faded = broll_with_audio.with_effects(
                [CrossFadeIn(transition_duration), CrossFadeOut(transition_duration)]
            )
        else:
            broll_faded = broll_trimmed.with_audio(part2_audio)

        # Concatenate parts
        clips_to_concat = []
        if part1:
            clips_to_concat.append(part1)
        clips_to_concat.append(broll_faded)
        if part3:
            clips_to_concat.append(part3)

        if len(clips_to_concat) == 1:
            final_clip = clips_to_concat[0]
        else:
            final_clip = concatenate_videoclips(clips_to_concat, method="compose")

        # Write output
        processor = VideoProcessor()
        encoding_settings = processor.get_optimal_encoding_settings("high")

        final_clip.write_videofile(
            str(output_path),
            temp_audiofile=str(output_path.parent / f"temp-audio-{output_path.stem}.m4a"),
            remove_temp=True,
            logger=None,
            **encoding_settings,
        )

        logger.info(f"Inserted B-roll into clip: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error inserting B-roll into clip: {e}")
        return False
    finally:
        for clip in (final_clip, broll_faded, broll_trimmed, broll_resized, broll_clip, main_clip):
            if clip is not None:
                try:
                    clip.close()
                except Exception:
                    pass

