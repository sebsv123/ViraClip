from __future__ import annotations

"""Transcription utilities extracted from video_utils."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import os
import hashlib

# Register NVIDIA CUDA DLL paths so ctranslate2/faster-whisper can find
# cublas64_12.dll on Windows when installed via pip (nvidia-cublas-cu12 etc.)
def _register_cuda_dll_paths() -> None:
    import site, ctypes
    dll_dirs = []
    for sp in (site.getsitepackages() or []) + [site.getusersitepackages()]:
        nv_base = os.path.join(sp, "nvidia")
        if not os.path.isdir(nv_base):
            continue
        for pkg_dir in os.listdir(nv_base):
            bin_dir = os.path.join(nv_base, pkg_dir, "bin")
            if os.path.isdir(bin_dir):
                dll_dirs.append(bin_dir)
                # Add to PATH for all DLL search mechanisms
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(bin_dir)
                    except Exception:
                        pass

    # Explicitly preload CUDA libs so Windows caches them before ctranslate2 lazy-loads
    _cuda_dlls = ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn_ops64_9.dll", "cudnn64_9.dll"]
    for dll_dir in dll_dirs:
        for dll_name in _cuda_dlls:
            dll_path = os.path.join(dll_dir, dll_name)
            if os.path.isfile(dll_path):
                try:
                    ctypes.CDLL(dll_path)
                except Exception:
                    pass

_register_cuda_dll_paths()

from ..config import Config

logger = logging.getLogger(__name__)


def resolve_whisper_device() -> Tuple[str, str]:
    requested = os.environ.get("WHISPER_DEVICE", "cpu").strip().lower()
    torch_cuda_enabled = os.environ.get("VIRACLIP_ENABLE_TORCH_CUDA", "false").lower() in (
        "1", "true", "yes"
    )

    if requested == "cuda":
        if not torch_cuda_enabled:
            logger.info(
                "[TRANSCRIPTION] CUDA requested but disabled by "
                "VIRACLIP_ENABLE_TORCH_CUDA=false; using CPU"
            )
            return "cpu", "int8"
        try:
            from ..utils.gpu_utils import is_torch_cuda_available
            if not is_torch_cuda_available():
                logger.info("[TRANSCRIPTION] CUDA requested but torch runtime unavailable; using CPU")
                return "cpu", "int8"
        except Exception as exc:
            logger.info("[TRANSCRIPTION] CUDA probe failed (%s); using CPU", exc)
            return "cpu", "int8"

        try:
            import ctranslate2
            types = ctranslate2.get_supported_compute_types("cuda")
            if len(types) > 0:
                return "cuda", "float16"
            logger.info("[TRANSCRIPTION] CUDA requested but ctranslate2 runtime unavailable; using CPU")
        except Exception as exc:
            logger.info("[TRANSCRIPTION] CUDA ctranslate2 probe failed (%s); using CPU", exc)

    return "cpu", "int8"
config = Config()

_TRANSCRIPT_CACHE_SCHEMA_VERSION = 2
_TRANSCRIPT_HASH_CACHE_DIR = Path("/tmp/viraclip_transcript_cache")
_TRANSCRIPT_REDIS_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

_whisper_model = None
_whisper_model_config = None


async def get_redis_transcript_cache(video_hash: str) -> Optional[Dict[str, Any]]:
    """Get transcript from Redis cache by video hash."""
    try:
        from ..utils.redis_pool import get_redis_client
        
        redis_client = await get_redis_client()
        cache_key = f"transcript:{video_hash}"
        cached_data = await redis_client.get(cache_key)
        
        if cached_data:
            data = json.loads(cached_data)
            logger.info(f"[TRANSCRIPTION] Redis cache HIT for hash {video_hash[:16]}...")
            return data
            
    except Exception as exc:
        logger.debug(f"[TRANSCRIPTION] Redis cache lookup failed: {exc}")
        
    return None


async def set_redis_transcript_cache(video_hash: str, transcript_data: Dict[str, Any]) -> None:
    """Store transcript in Redis cache with TTL."""
    try:
        from ..utils.redis_pool import get_redis_client
        
        redis_client = await get_redis_client()
        cache_key = f"transcript:{video_hash}"
        await redis_client.setex(
            cache_key,
            _TRANSCRIPT_REDIS_TTL_SECONDS,
            json.dumps(transcript_data)
        )
        
        logger.info(f"[TRANSCRIPTION] Cached to Redis: {video_hash[:16]}... (TTL={_TRANSCRIPT_REDIS_TTL_SECONDS}s)")
        
    except Exception as exc:
        logger.warning(f"[TRANSCRIPTION] Redis cache write failed: {exc}")


def _get_video_hash(video_path: Path) -> Optional[str]:
    """Generate SHA256 hash of first 1MB for cache key."""
    try:
        with open(video_path, "rb") as handle:
            chunk = handle.read(1_048_576)
        return hashlib.sha256(chunk).hexdigest()
    except Exception as e:
        logger.error(f"[TRANSCRIPTION] Failed to generate file hash: {e}")
        return None


def snap_to_word_boundary(timestamp_ms: int, words: List[Dict], is_start: bool = True) -> int:
    """Snap a timestamp to the nearest word boundary.
    
    Args:
        timestamp_ms: The timestamp in milliseconds
        words: List of word dictionaries with 'start' and 'end' timestamps
        is_start: If True, snap to word start; if False, snap to word end
        
    Returns:
        The adjusted timestamp in milliseconds
    """
    if not words:
        return timestamp_ms
    
    # Find the closest word boundary
    closest_time = timestamp_ms
    min_diff = float('inf')
    
    for word in words:
        if is_start:
            word_time = int(word.get('start', 0) * 1000)
        else:
            word_time = int(word.get('end', 0) * 1000)
        
        diff = abs(word_time - timestamp_ms)
        if diff < min_diff:
            min_diff = diff
            closest_time = word_time
    
    return closest_time


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


def get_whisper_model():
    """Get or create a singleton faster-whisper model with smart device detection."""
    global _whisper_model, _whisper_model_config

    model_size = os.environ.get("WHISPER_MODEL_SIZE", "medium")
    device, compute_type = resolve_whisper_device()

    current_config = (model_size, device, compute_type)
    if _whisper_model is not None and _whisper_model_config == current_config:
        return _whisper_model

    from faster_whisper import WhisperModel

    model_path = model_size
    _models_root = os.environ.get("WHISPER_MODELS_DIR") or (
        "/app/models" if os.path.isdir("/app/models") else None
    )
    try:
        _whisper_model = WhisperModel(
            model_path,
            device=device,
            compute_type=compute_type,
            **( {"download_root": _models_root} if _models_root else {} ),
        )
    except Exception as e:
        if device != "cpu":
            logger.warning(f"[TRANSCRIPTION] WhisperModel failed on {device} ({e}) — retrying on CPU")
            device = "cpu"
            compute_type = "int8"
            _whisper_model = WhisperModel(
                model_path, device="cpu", compute_type="int8",
                **( {"download_root": _models_root} if _models_root else {} ),
            )
    _whisper_model_config = current_config
    logger.info(
        "WHISPER_RUNTIME_DEVICE device=%s compute_type=%s cuda_available=%s model=%s",
        device,
        compute_type,
        str(device == "cuda").lower(),
        model_size,
    )
    return _whisper_model


def _format_cached_words_to_lines(words: List[Dict[str, Any]]) -> str:
    """Rebuild the canonical "[MM:SS - MM:SS] text" transcript from cached v2 words.

    The fresh-transcription path returns bracketed timestamped lines, but cache
    hits used to return the plain `text` field — losing every timestamp and
    silently blinding all transcript-line consumers (semantic boundary
    adjustment, anti-backstage trimming). Word times are in milliseconds.
    """
    lines: List[str] = []
    current: List[str] = []
    current_start: Optional[int] = None
    last_end = 0

    def _flush() -> None:
        nonlocal current, current_start
        if not current or current_start is None:
            return
        # MM:SS resolution: guarantee end > start or the line parser drops it.
        end_ms = max(last_end, current_start + 1000)
        if (end_ms // 1000) <= (current_start // 1000):
            end_ms = (current_start // 1000 + 1) * 1000
        lines.append(
            f"[{format_ms_to_timestamp(current_start)} - {format_ms_to_timestamp(end_ms)}] "
            + " ".join(current)
        )
        current = []
        current_start = None

    for word in words or []:
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        try:
            w_start = int(word.get("start") or 0)
            w_end = int(word.get("end") or w_start)
        except Exception:
            continue
        if current_start is None:
            current_start = w_start
        current.append(text)
        last_end = w_end
        span_ms = last_end - current_start
        if (len(current) >= 8 and span_ms >= 1500) or (
            text.endswith((".", "!", "?", "…")) and span_ms >= 1200
        ) or len(current) >= 14:
            _flush()
    _flush()
    return "\n".join(lines)


async def get_video_transcript(
    video_path: Path, 
    speech_model: str = "best",
    use_cache: bool = True
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Transcribe video locally with faster-whisper, with Redis caching.
    
    Args:
        video_path: Path to video file
        speech_model: Model to use (best, tiny, base, small, medium, large)
        use_cache: Whether to check/save to Redis cache
        
    Returns:
        Tuple of (transcript_text, transcript_data_dict)
    """
    video_hash = None
    
    # Check Redis cache first, then local file cache
    if use_cache:
        video_hash = _get_video_hash(video_path)
        if video_hash:
            cached_data = await get_redis_transcript_cache(video_hash)
            if cached_data:
                text = cached_data.get("text", "")
                if "[" not in (text or "")[:48] and cached_data.get("words"):
                    rebuilt = _format_cached_words_to_lines(cached_data.get("words") or [])
                    if rebuilt:
                        text = rebuilt
                        logger.info(
                            "[TRANSCRIPTION] cache HIT text normalized to timestamped lines (%d chars)",
                            len(rebuilt),
                        )
                logger.info(f"[TRANSCRIPTION] Redis cache HIT - skipping Whisper for {video_path.name}")
                return text, cached_data

        # Redis miss/unavailable — fall back to local file cache
        file_cached = load_cached_transcript_data(video_path)
        if file_cached:
            text = file_cached.get("text", "")
            if "[" not in (text or "")[:48] and file_cached.get("words"):
                rebuilt = _format_cached_words_to_lines(file_cached.get("words") or [])
                if rebuilt:
                    text = rebuilt
                    logger.info(
                        "[TRANSCRIPTION] file cache HIT text normalized to timestamped lines (%d chars)",
                        len(rebuilt),
                    )
            if text:
                logger.info(f"[TRANSCRIPTION] File cache HIT - skipping Whisper for {video_path.name}")
                return text, file_cached
    
    logger.info(f"[TRANSCRIPTION] Cache MISS - transcribing with faster-whisper: {video_path}")
    
    model = get_whisper_model()
    
    try:
        segments, info = model.transcribe(
            str(video_path),
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        
        logger.info(f"Language detected: {info.language} ({info.language_probability:.2f})")
        logger.info(f"Audio duration: {info.duration:.1f}s")
        
        formatted_lines = []
        all_segments = []
        for segment in segments:
            start = format_ms_to_timestamp(int(segment.start * 1000))
            end = format_ms_to_timestamp(int(segment.end * 1000))
            formatted_lines.append(f"[{start} - {end}] {segment.text}")
            all_segments.append(segment)
        
        result = "\n".join(formatted_lines)
        logger.info(f"Transcript complete: {len(result)} chars, {len(formatted_lines)} segments")
        
        # Cache to local file and Redis
        cache_transcript_data(video_path, all_segments)
        transcript_data = load_cached_transcript_data(video_path)
        logger.info(
            "[TRANSCRIPTION] cached transcript words=%d utterances=%d",
            len((transcript_data or {}).get("words") or []),
            len((transcript_data or {}).get("utterances") or []),
        )
        
        # Also cache to Redis for distributed access
        if use_cache:
            if transcript_data and video_hash:
                await set_redis_transcript_cache(video_hash, transcript_data)
        
        return result, transcript_data
        
    except Exception as exc:
        logger.error(f"faster-whisper error: {exc}")
        raise


def _hash_cache_path(video_hash: str) -> Path:
    return _TRANSCRIPT_HASH_CACHE_DIR / f"{video_hash}.transcript_cache.json"


def cache_transcript_data(video_path: Path, transcript) -> None:
    cache_path = video_path.with_suffix(".transcript_cache.json")

    words_data = []
    utterances_data = []
    full_text = ""

    if isinstance(transcript, list):
        all_words = []
        text_parts = []
        for segment in transcript:
            text_parts.append(segment.text.strip())
            if hasattr(segment, "words") and segment.words:
                for word in segment.words:
                    all_words.append(
                        {
                            "text": getattr(word, "word", getattr(word, "text", "")),
                            "start": int(word.start * 1000),
                            "end": int(word.end * 1000),
                            "confidence": getattr(word, "probability", 1.0),
                            "speaker": None,
                        }
                    )
        words_data = all_words
        full_text = " ".join(text_parts)
    else:
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
        "version": _TRANSCRIPT_CACHE_SCHEMA_VERSION,
        "words": words_data,
        "utterances": utterances_data,
        "text": full_text,
    }

    with open(cache_path, "w") as handle:
        json.dump(cache_data, handle)

    try:
        video_hash = _get_video_hash(video_path)
        if video_hash:
            _TRANSCRIPT_HASH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            hash_path = _hash_cache_path(video_hash)
            with open(hash_path, "w") as handle:
                json.dump(cache_data, handle)
    except Exception as exc:
        logger.debug(f"Hash cache write skipped: {exc}")


def load_cached_transcript_data(video_path: Path) -> Optional[Dict[str, Any]]:
    def _parse_cache(path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r") as handle:
                payload = json.load(handle)
            if "version" not in payload:
                payload["version"] = _TRANSCRIPT_CACHE_SCHEMA_VERSION
                payload.setdefault("utterances", [])
            return payload
        except Exception as exc:
            logger.warning(f"Failed to parse transcript cache {path}: {exc}")
            return None

    cache_path = video_path.with_suffix(".transcript_cache.json")
    if cache_path.exists():
        data = _parse_cache(cache_path)
        if data is not None:
            return data

    try:
        video_hash = _get_video_hash(video_path)
        if video_hash:
            hash_path = _hash_cache_path(video_hash)
            if hash_path.exists():
                data = _parse_cache(hash_path)
                if data is not None:
                    return data
    except Exception as exc:
        logger.debug(f"Hash-cache lookup failed: {exc}")

    return None


def _serialize_transcript_word(word) -> Dict[str, Any]:
    return {
        "text": getattr(word, "text", ""),
        "start": getattr(word, "start", 0),
        "end": getattr(word, "end", 0),
        "confidence": getattr(word, "confidence", 1.0),
        "speaker": getattr(word, "speaker", None),
    }


def format_ms_to_timestamp(ms: int) -> str:
    seconds = ms // 1000
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes:02d}:{seconds:02d}"
