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
config = Config()

_TRANSCRIPT_CACHE_SCHEMA_VERSION = 2
_TRANSCRIPT_HASH_CACHE_DIR = Path("/tmp/viraclip_transcript_cache")
_TRANSCRIPT_REDIS_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

_whisper_model = None
_whisper_model_config = None

# AssemblyAI transcriber singleton
_assemblyai_transcriber = None

def get_assemblyai_transcriber():
    """Get or create singleton AssemblyAI transcriber."""
    global _assemblyai_transcriber
    if _assemblyai_transcriber is None:
        api_key = os.environ.get("ASSEMBLY_AI_API_KEY", "")
        if api_key:
            try:
                import assemblyai as aai
                aai.settings.api_key = api_key
                _assemblyai_transcriber = aai.Transcriber()
                logger.info("[Transcription] AssemblyAI transcriber initialized (primary)")
            except Exception as e:
                logger.warning("[Transcription] Failed to init AssemblyAI: %s — will use Whisper fallback", e)
                _assemblyai_transcriber = False  # Sentinel: don't retry
        else:
            _assemblyai_transcriber = False
            logger.info("[Transcription] No ASSEMBLY_AI_API_KEY — using Whisper GPU (fallback)")
    return _assemblyai_transcriber if _assemblyai_transcriber else None


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
    device_setting = os.environ.get("WHISPER_DEVICE", "auto")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8_float16")

    def _cuda_available_via_ct2() -> bool:
        """Check CUDA via ctranslate2 (works even when torch is CPU-only build)."""
        try:
            import ctranslate2
            types = ctranslate2.get_supported_compute_types("cuda")
            return len(types) > 0
        except Exception:
            return False

    if device_setting == "auto":
        if _cuda_available_via_ct2():
            device = "cuda"
            compute_type = "float16"
        else:
            device = "cpu"
            compute_type = "int8"
    else:
        device = device_setting
        if device == "cpu":
            compute_type = "int8"
        elif device == "cuda":
            if not _cuda_available_via_ct2():
                logger.warning("[TRANSCRIPTION] CUDA not available via ctranslate2 — falling back to CPU")
                device = "cpu"
                compute_type = "int8"
            else:
                compute_type = "float16"

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
    return _whisper_model


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
                logger.info(f"[TRANSCRIPTION] Redis cache HIT - skipping Whisper for {video_path.name}")
                return text, cached_data

        # Redis miss/unavailable — fall back to local file cache
        file_cached = load_cached_transcript_data(video_path)
        if file_cached:
            text = file_cached.get("text", "")
            if text:
                logger.info(f"[TRANSCRIPTION] File cache HIT - skipping Whisper for {video_path.name}")
                return text, file_cached
    
    # Try AssemblyAI first (primary), fall back to Whisper GPU
    _aai = get_assemblyai_transcriber()
    if _aai:
        logger.info(f"[TRANSCRIPTION] Transcribing with AssemblyAI (primary): {video_path.name}")
        try:
            import assemblyai as aai
            _config = aai.TranscriptionConfig(
                speaker_labels=True,
                language_code="es",
                punctuate=True,
                format_text=True,
            )
            _transcript = _aai.transcribe(str(video_path), config=_config)
            if _transcript.status == aai.TranscriptStatus.error:
                logger.error(f"[TRANSCRIPTION] AssemblyAI error: {_transcript.error} — falling back to Whisper")
            else:
                text = _transcript.text or ""
                words_data = []
                for word in _transcript.words:
                    words_data.append({
                        "text": word.text,
                        "start": word.start,
                        "end": word.end,
                        "confidence": word.confidence,
                        "speaker": getattr(word, "speaker", None),
                    })
                utterances_data = []
                for utt in (_transcript.utterances or []):
                    utterances_data.append({
                        "text": utt.text,
                        "start": utt.start,
                        "end": utt.end,
                        "speaker": getattr(utt, "speaker", None),
                        "words": [{"text": w.text, "start": w.start, "end": w.end, "confidence": w.confidence, "speaker": getattr(w, "speaker", None)} for w in (utt.words or [])],
                    })
                transcript_data = {
                    "version": _TRANSCRIPT_CACHE_SCHEMA_VERSION,
                    "words": words_data,
                    "utterances": utterances_data,
                    "text": text,
                }
                logger.info(f"[TRANSCRIPTION] AssemblyAI complete: {len(text)} chars, {len(words_data)} words")
                # Cache to Redis
                if use_cache and video_hash:
                    await set_redis_transcript_cache(video_hash, transcript_data)
                return text, transcript_data
        except Exception as _aai_e:
            logger.warning(f"[TRANSCRIPTION] AssemblyAI failed ({_aai_e}) — falling back to Whisper")
    
    # Fallback: faster-whisper GPU
    logger.info(f"[TRANSCRIPTION] Transcribing with faster-whisper (fallback): {video_path.name}")
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
        
        # Also cache to Redis for distributed access
        if use_cache:
            transcript_data = load_cached_transcript_data(video_path)
            if transcript_data and video_hash:
                await set_redis_transcript_cache(video_hash, transcript_data)
        
        return result, transcript_data if 'transcript_data' in dir() else None
        
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
