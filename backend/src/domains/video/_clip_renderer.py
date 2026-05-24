"""Single clip renderer — the heart of the video processing pipeline.

`create_single_clip` takes one segment and produces a finished, polished
short-form video with subtitles, b-roll, transitions, audio polish, and
viral metadata. This is the largest single piece of business logic in the
backend; subdividing it further is tracked as a follow-up refactor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, cast

import shutil

from ...utils.async_helpers import run_in_thread
from ... import gpu_utils
from ...ai import get_most_relevant_parts_by_transcript
from ...comfyui_bridge import COMFYUI_ENABLED
from ...config import Config
from ...core.cache_manager import (
    cache_transcript_smart,
    get_cache_manager,
    get_cached_transcript_smart,
)
from ...core.concurrency_optimizer import (
    ParallelBatchProcessor,
    parallel_map,
    run_with_timeout,
)
from ...core.error_handler import execute_with_recovery, get_circuit_breaker, with_retry
from ...core.metrics_service import get_metrics_collector, timed_stage
from ...domains.ai.elite_ai_service import EliteAIService
from ...domains.ai.llm_service import LLMService
try:
    from ...domains.ai.phi3_virality_service import Phi3ViralityService, get_phi3_service
    _PHI3_IMPORT_OK = True
except ImportError:
    _PHI3_IMPORT_OK = False
    def get_phi3_service():  # type: ignore
        raise RuntimeError("phi3_virality_service not available — LLMRouter fallback will handle scoring")
from ...domains.audio.sound_design_service import SoundDesignService, add_viral_sound_effects
from ...audio_placement import detect_audio_events, apply_audio_events
from ...domains.broll.broll_service import BrollService
from ...core.job_context import JobContext
from ...domains.broll.hook_visual_service import HookVisualService
from ...domains.broll.semantic_broll_service import SemanticBrollService

from ...domains.detection.face_detection_service import FaceDetectionService
from ...domains.publishing.social_distribution_service import SocialDistributionService
from ...domains.virality.viral_metadata_service import generate_viral_metadata
from ...video_processing import (
    create_clips_with_transitions,
    create_optimized_clip,
    generate_clip_thumbnail,
)
from ...video_processing.audio import apply_voice_enhancement, denoise_audio
from ...video_processing.audio_analysis import (
    analyze_audio_virality,
    extract_audio_from_video,
)
from ...video_processing.editing_pipeline import EditingPipeline
from ...video_processing.export_profiles import (
    ExportService,
    Platform,
    get_ffmpeg_export_command,
)
from ...video_processing.hook_analysis import analyze_segment_virality, compare_hook_strength
from ...video_processing.narrative_cut_engine import NarrativeCutEngine, detect_hesitations
from ...video_processing.niche_analysis import analyze_content_niche, optimize_for_platform
from ...video_processing.nonlinear_edit_engine import NonLinearEditingEngine
from ...video_processing.silence_removal import (
    MIN_SILENCE_SAVINGS,
    SILENCE_MODE,
    SILENCE_THRESHOLD,
    build_keep_intervals,
    remove_silences,
    speed_ramp_silences,
)
from ...video_processing.thumbnail_selector import select_best_thumbnail
from ...video_processing.utils import parse_timestamp_to_seconds
from ...video_processing.virality_tuner import get_tuner
from ...youtube_utils import (
    async_get_youtube_video_info,
    get_youtube_video_id,
)

# Guarded import for ConfidenceSubtitleGenerator
try:
    from ...domains.captions.confidence_subtitle_service import ConfidenceSubtitleGenerator
    _confidence_subtitle_available = True
except (ImportError, Exception):
    _confidence_subtitle_available = False
    ConfidenceSubtitleGenerator = None  # type: ignore

from ...domains.virality.viral_scorer_service import get_viral_scorer
from . import _clip_polish as _polish
from . import _helpers, _subtitles, _transcript
from ._helpers import get_ffmpeg_exe, get_service_config
from .vfx_service import VFXService

logger = logging.getLogger(__name__)

# ── Duration guard helper ────────────────────────────────────────────────
# Validates that no video-processing step truncates the clip below min_ratio
# of the input duration. Called after every step that writes a new MP4.
def _get_duration(path: str) -> float:
    """Return video duration in seconds via ffprobe, or 0 on failure.
    
    Uses the video stream's actual duration (not the container duration)
    to detect frozen-frame issues where the container says 60s but the
    video stream only has 9s of real frames.
    """
    try:
        import subprocess as _sp, json as _json
        # First try video stream duration (more accurate — detects frozen frames)
        r = _sp.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=10,
        )
        data = _json.loads(r.stdout)
        streams = data.get("streams", [])
        if streams and "duration" in streams[0]:
            return float(streams[0]["duration"])
        # Fallback to container duration
        r = _sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(_json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        return 0.0

def _guard_output_duration(input_path: str, output_path: str, step_name: str, min_ratio: float = 0.8, declared_duration: Optional[float] = None) -> None:
    """Revert output to input if output duration < min_ratio of input duration.
    
    When declared_duration is provided (e.g., the platform-capped render duration),
    compare against that instead of the input file duration. This prevents false
    positives when the input is a pre-extracted segment (90s) but the declared
    render duration is shorter (60s due to TikTok cap).
    """
    in_dur = _get_duration(input_path)
    out_dur = _get_duration(output_path)
    ref_dur = declared_duration if declared_duration is not None else in_dur
    if ref_dur > 0 and out_dur < ref_dur * min_ratio:
        logger.warning(
            "[RENDERER GUARD] %s truncated clip: ref=%.2fs output=%.2fs min=%.2fs — reverting",
            step_name, ref_dur, out_dur, ref_dur * min_ratio,
        )
        shutil.copy2(input_path, output_path)

# ── RULE 4: Concept-level tracking across clips ──
# Persists seen b-roll concepts per task_id so repeated concepts are avoided
# across multiple clips of the same task.
_seen_concepts_per_task: Dict[str, set] = {}

def _get_seen_concepts(task_id: str) -> set:
    """Get or create the seen_concepts set for a given task_id."""
    if task_id not in _seen_concepts_per_task:
        _seen_concepts_per_task[task_id] = set()
    return _seen_concepts_per_task[task_id]


async def create_single_clip(
    video_path: Path,
    segment: Dict[str, Any],
    clip_index: int,
    output_dir: Path,
    font_family: str = "TikTokSans-Regular",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
    add_subtitles: bool = True,
    caption_offset_y: int = 0,
    broll_suggestions: Optional[List[Dict[str, Any]]] = None,
    split_screen: bool = False,
    hook_title: Optional[str] = None,
    auto_center_face: bool = True,
    eye_contact_correction: bool = False,
    target_language: Optional[str] = None,
    task_id: str = "unknown",
    elite_metadata: Optional[Dict[str, Any]] = None,
    camera_plan: Optional[Dict[str, Any]] = None,
    sync_offset: float = 0.0,
    secondary_video_path: Optional[Path] = None,
    gpu_encoding_settings: Optional[Dict[str, Any]] = None,
    use_extracted_segment: bool = False,
    target_platform: str = "tiktok",
    preferred_music_category: Optional[str] = None,
    jump_cut: bool = True,
    job_ctx: Optional[JobContext] = None,
) -> Optional[Dict[str, Any]]:

    """Render a single clip in the thread pool and return clip_info dict, or None on failure."""
    # Feature A: launch Pexels B-Roll prefetch concurrently at the start of render
    _broll_prefetch_task = None
    try:
        from ...config import get_config as _get_cfg_fa
        _cfg_fa = _get_cfg_fa()
        if getattr(_cfg_fa, "broll_enabled", False) and getattr(_cfg_fa, "pexels_api_key", ""):
            from ...domains.broll.pexels_service import prefetch_broll_for_clip as _pfetch
            _broll_cache_dir = Path(tempfile.gettempdir()) / "viraclip_broll"
            _broll_theme = segment.get("theme") or "nature"
            _broll_prefetch_task = asyncio.create_task(
                _pfetch(_broll_theme, _cfg_fa.pexels_api_key, _broll_cache_dir)
            )
    except Exception as _fa_init_e:
        logger.debug(f"B-Roll prefetch task init skipped: {_fa_init_e}")

    logger.info(f"[create_single_clip] START clip {clip_index+1}: {segment.get('start_time')} → {segment.get('end_time')}, video={video_path}")
    try:
        start_seconds = parse_timestamp_to_seconds(segment["start_time"])
        end_seconds = parse_timestamp_to_seconds(segment["end_time"])
        duration = end_seconds - start_seconds
    except Exception as _parse_e:
        logger.error(f"Failed to parse timestamps: {_parse_e}")
        return None

    # Platform minimum enforcement — respect the LLM's natural speech boundary.
    # Only extend clips that are genuinely too short (< 30s); never pad a
    # well-bounded segment just because it has a high virality score.
    _vscore_pre = segment.get("virality_score", 50)
    _FLOOR = 30.0  # hard platform minimum — 30s minimum for viable short-form content
    if duration < _FLOOR:
        if _vscore_pre >= 70:
            _target_dur = 60.0
        elif _vscore_pre >= 50:
            _target_dur = 45.0
        else:
            _target_dur = _FLOOR
        end_seconds = start_seconds + _target_dur
        duration = _target_dur
        logger.info(f"  Duration extended to {duration:.0f}s (was too short, virality={_vscore_pre})")

    # Platform duration cap (TikTok=60s, Reels=90s, Shorts=60s)
    try:
        _platform_enum = Platform.TIKTOK if target_platform in ["all", "tiktok"] else \
                         Platform.REELS if target_platform == "reels" else \
                         Platform.SHORTS if target_platform == "shorts" else \
                         Platform.UNIVERSAL
        _export_svc_dur = ExportService()
        _capped = _export_svc_dur.enforce_clip_duration(duration, _platform_enum)
        if _capped != duration:
            end_seconds = start_seconds + _capped
            duration = _capped
        logger.info(f"[create_single_clip] clip {clip_index+1}: duration={duration:.1f}s, platform={_platform_enum}")
    except Exception as _plat_e:
        logger.error(f"[create_single_clip] Platform/duration error clip {clip_index+1}: {_plat_e}", exc_info=True)
        return None

    if duration <= 0:
        logger.warning(
            f"Skipping clip {clip_index + 1}: invalid duration {duration:.1f}s"
        )
        return None

    # FIX Problema 1: PHI3_ENABLED env var + LLMRouter fallback
    _phi3_enabled = os.environ.get("PHI3_ENABLED", "true").lower() == "true"
    virality_result = None
    if _phi3_enabled:
        logger.info(f"[Clip {clip_index+1}] Step 1: Phi-3-mini virality scoring...")
        try:
            phi3_service = get_phi3_service()
            virality_result = await asyncio.wait_for(
                phi3_service.score_segment(
                    segment_text=segment.get("text", ""),
                    duration=duration,
                    audio_features=None,
                ),
                timeout=20.0,  # Increased from 5s to 20s — Phi-3 model may not be in cache
            )
            # Phase 2.2: blend Phi-3 score with locally-trained MLP scorer
            try:
                _mlp = get_viral_scorer()
                if _mlp.is_available():
                    _blended = _mlp.blend_with_phi3(
                        phi3_score=virality_result.total_score,
                        transcript=segment.get("text", ""),
                        duration=duration,
                    )
                    logger.info(
                        f"  ↳ MLP blend: Phi3={virality_result.total_score} "
                        f"→ blended={_blended}"
                    )
                    virality_result.total_score = _blended
            except Exception as _mlp_e:
                logger.debug(f"  MLP blend skipped: {_mlp_e}")

            # Actualizar segment con resultados Phi-3
            segment["virality_score"] = virality_result.total_score
            segment["phi3_hook_type"] = virality_result.primary_hook_type
            segment["scroll_stop_probability"] = virality_result.scroll_stop_probability
            segment["recommended_duration"] = virality_result.recommended_duration
            logger.info(
                f"  ✓ Phi-3 score: {virality_result.total_score}/100, "
                f"Hook: {virality_result.primary_hook_type}"
            )
        except Exception as phi3_e:
            logger.warning(f"  Phi-3 scoring failed: {phi3_e} — trying LLMRouter fallback")
            try:
                from ...domains.ai.llm_router import LLMRouter
                llm_router = LLMRouter()
                _llm_fallback = await llm_router.score_segments(
                    [segment.get("text", "")], language="es", num_clips=1
                )
                # Defensive JSON parsing: LLM may return string instead of dict
                if isinstance(_llm_fallback, str):
                    try:
                        _llm_fallback = json.loads(_llm_fallback)
                    except (json.JSONDecodeError, ValueError):
                        _llm_fallback = {}
                _llm_segments = _llm_fallback.get("segments", _llm_fallback.get("analysis", []))
                if _llm_fallback and _llm_segments:
                    _item = _llm_segments[0]
                    _raw_vs = float(_item.get("viral_score", _item.get("virality_score", 5)) or 5)
                    _vscore = min(100, round(_raw_vs * 10)) if _raw_vs <= 10 else int(_raw_vs)
                    class _LLMFallbackScore:
                        def __init__(self, score, hook_type, scroll_stop, rec_dur):
                            self.total_score = score
                            self.primary_hook_type = hook_type
                            self.scroll_stop_probability = scroll_stop
                            self.recommended_duration = rec_dur
                    virality_result = _LLMFallbackScore(
                        score=_vscore,
                        hook_type=_item.get("hook_type") or "Content",
                        scroll_stop=_item.get("scroll_stop_probability", 0.5),
                        rec_dur=_item.get("recommended_duration", "30-60s"),
                    )
                    segment["virality_score"] = virality_result.total_score
                    segment["phi3_hook_type"] = virality_result.primary_hook_type
                    segment["scroll_stop_probability"] = virality_result.scroll_stop_probability
                    segment["recommended_duration"] = virality_result.recommended_duration
                    logger.info(
                        f"  ✓ LLMRouter fallback score: {virality_result.total_score}/100"
                    )
            except Exception as _llm_fb_e:
                logger.warning(f"  LLMRouter fallback also failed: {_llm_fb_e}")
                virality_result = None
    
    # PASO 2: Audio spectral analysis — run in parallel with transcription
    # when transcript exists, so narrative cut engine gets silence/energy data.
    audio_features = {}
    _has_transcript = bool(segment.get("text", "").strip())
    if _has_transcript:
        logger.info(f"[Clip {clip_index+1}] Step 2: Audio spectral analysis (parallel with transcript)...")
    else:
        logger.info(f"[Clip {clip_index+1}] Step 2: Audio spectral analysis (no transcript)...")
    try:
        from tempfile import NamedTemporaryFile
        audio_temp = NamedTemporaryFile(suffix='.wav', delete=False)
        audio_temp.close()
        audio_ss = 0.0 if use_extracted_segment else start_seconds
        cmd = [get_ffmpeg_exe(), "-y", "-ss", str(audio_ss), "-i", str(video_path),
               "-t", str(duration), "-vn", "-acodec", "pcm_s16le",
               "-ar", "16000", "-ac", "1", audio_temp.name]
        subprocess.run(cmd, capture_output=True, timeout=60)
        if Path(audio_temp.name).exists():
            audio_features = analyze_audio_virality(audio_temp.name)
            Path(audio_temp.name).unlink()
    except Exception as audio_e:
        logger.warning(f"  Audio analysis failed: {audio_e}")
    
    # PASO 3: Detectar cortes narrativos inteligentes (Capa A)
    logger.info(f"[Clip {clip_index+1}] Step 3: Narrative cut detection...")
    try:
        cut_engine = NarrativeCutEngine(min_silence_duration=0.5)
        
        # Extraer palabras del segmento (usar el texto)
        words = segment.get("words", [])
        if not words:
            # Crear palabras mock del texto
            words = [{"word": w, "start": 0, "end": 1} for w in segment.get("text", "").split()]
        
        silence_periods = audio_features.get("pause_moments", [])
        silences = [(p["start"], p["start"] + p["duration"]) for p in silence_periods]
        
        cut_points = cut_engine.find_narrative_cuts(
            transcript=segment.get("text", ""),
            words_with_timestamps=words,
            audio_silences=silences,
            audio_energy=audio_features.get("energy_peaks_timestamps", [])
        )
        
        if cut_points:
            logger.info(f"  ✓ Found {len(cut_points)} narrative cuts")
            for cp in cut_points[:3]:
                logger.info(f"    - {cp.timestamp:.1f}s: {cp.reason} ({cp.confidence:.0%})")
        else:
            logger.info(f"  No narrative cuts needed")
        
        segment["narrative_cuts"] = [{
            "timestamp": cp.timestamp,
            "confidence": cp.confidence,
            "reason": cp.reason,
            "transition": cp.suggested_transition
        } for cp in cut_points]
        
    except Exception as cut_e:
        logger.warning(f"  Narrative cut detection failed: {cut_e}")
        cut_points = []

    # ── Clip Intelligence Profile ────────────────────────────────────
    # Single analysis pass that drives: LUT, caption style, B-roll
    # density/duration, BGM category, SFX emphasis, zoom intensity.
    try:
        from ...domains.virality.clip_intelligence import build_clip_profile_async as _build_profile_async
        _clip_profile = await _build_profile_async(
            segment=segment,
            duration=duration,
            clip_index=clip_index,
            caption_template=caption_template or "viral",
        )
    except Exception as _ci_e:
        logger.debug(f"  ClipIntelligence skipped: {_ci_e}")
        _clip_profile = None

    # PASO 4: Word-level confidence subtitles (Fase 3 del plan)
    words_with_confidence = []
    
    # Definir clip_path antes de usarlo
    clip_filename = (
        f"clip_{clip_index + 1}_viral_{int(segment.get('virality_score', 0))}_"
        f"{segment['start_time'].replace(':', '')}-"
        f"{segment['end_time'].replace(':', '')}.mp4"
    )
    clip_path = output_dir / clip_filename
    
    if add_subtitles:
        logger.info(f"[Clip {clip_index+1}] Step 4: Generating subtitles...")

        # ── Priority 1: AssemblyAI transcript cache ──────────────────
        # The cache is keyed on the ORIGINAL source video, not the
        # pre-extracted segment.  segment["_source_video_path"] is
        # injected by task_service.py before the render loop.
        try:
            from ...video_processing.transcription import load_cached_transcript_data as _load_aai
            _orig_video = Path(segment.get("_source_video_path", str(video_path)))
            _transcript = _load_aai(_orig_video)
            if _transcript and _transcript.get("words"):
                _start_ms = start_seconds * 1000.0
                _end_ms   = end_seconds   * 1000.0
                for _w in _transcript["words"]:
                    _ws = float(_w.get("start", 0))
                    _we = float(_w.get("end", _ws + 400))
                    # Filter strictly: only words whose start is within the segment
                    # (no clamping — a word before segment_start must not appear)
                    if _ws < _start_ms or _ws > _end_ms:
                        continue
                    words_with_confidence.append({
                        "word":       (_w.get("text") or "").strip(),
                        "start":      _ws / 1000.0 - start_seconds,
                        "end":        _we / 1000.0 - start_seconds,
                        "confidence": float(_w.get("confidence", 0.9)),
                        "is_emphasis": float(_w.get("confidence", 0.9)) < 0.80,
                    })
                if words_with_confidence:
                    logger.info(
                        f"  ✅ {len(words_with_confidence)} words from AssemblyAI cache"
                    )
        except Exception as _aai_e:
            logger.warning(f"  AssemblyAI cache lookup failed: {_aai_e}")

        # ── Priority 1.5: Groq Whisper API — fast cloud transcription (5s vs 5min) ──
        if not words_with_confidence:
            try:
                _gw_key = os.environ.get("GROQ_API_KEY", "")
                _audio_for_groq = output_dir / f"audio_gw_{clip_index}.wav"
                _audio_ss_gw = 0.0 if use_extracted_segment else start_seconds
                _cmd_gw = [
                    get_ffmpeg_exe(), "-y",
                    "-ss", str(_audio_ss_gw), "-i", str(video_path),
                    "-t", str(min(duration, 60.0)),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(_audio_for_groq),
                ]
                subprocess.run(_cmd_gw, capture_output=True, timeout=30)
                if _gw_key and _audio_for_groq.exists():
                    import httpx as _httpx
                    with open(str(_audio_for_groq), "rb") as _af:
                        _audio_bytes = _af.read()
                    async with _httpx.AsyncClient(timeout=25.0) as _gwc:
                        _gwr = await _gwc.post(
                            "https://api.groq.com/openai/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {_gw_key}"},
                            files={"file": ("audio.wav", _audio_bytes, "audio/wav")},
                            data={
                                "model": "whisper-large-v3-turbo",
                                "response_format": "verbose_json",
                                "timestamp_granularities[]": "word",
                            },
                        )
                    if _gwr.status_code == 200:
                        for _gw in _gwr.json().get("words", []):
                            words_with_confidence.append({
                                "word":       _gw.get("word", "").strip(),
                                "start":      float(_gw.get("start", 0)),
                                "end":        float(_gw.get("end", 0)),
                                "confidence": 0.95,
                                "is_emphasis": False,
                            })
                        logger.info(f"  ✅ {len(words_with_confidence)} words from Groq Whisper API")
                _audio_for_groq.unlink(missing_ok=True)
            except Exception as _gw_e:
                logger.warning(f"  Groq Whisper failed: {_gw_e}")

        # ── Priority 2: faster-whisper local (last resort) ──────────────
        if not words_with_confidence and _confidence_subtitle_available:
            try:
                _whisper_device = os.environ.get("WHISPER_DEVICE", "cpu")
                subtitle_gen = ConfidenceSubtitleGenerator(model_size="tiny", device=_whisper_device)
                audio_temp_path = output_dir / f"audio_temp_{clip_index}.wav"
                audio_ss2 = 0.0 if use_extracted_segment else start_seconds
                cmd_extract = [
                    get_ffmpeg_exe(), "-y",
                    "-ss", str(audio_ss2), "-i", str(video_path),
                    "-t", str(duration),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(audio_temp_path),
                ]
                subprocess.run(cmd_extract, capture_output=True, timeout=60)
                if audio_temp_path.exists():
                    colored_segs = subtitle_gen.transcribe_with_confidence(
                        str(audio_temp_path)
                    )
                    for seg_cs in colored_segs:
                        for _w in seg_cs.words:
                            # faster-whisper word.start/end are ABSOLUTE timestamps
                            # in the audio file — do NOT add seg_cs.start
                            words_with_confidence.append({
                                "word":       _w.text,
                                "start":      getattr(_w, "start", 0) or 0,
                                "end":        getattr(_w, "end",   0.5) or 0.5,
                                "confidence": getattr(_w, "confidence", 0.9),
                                "is_emphasis": getattr(_w, "is_emphasis", False),
                            })
                    audio_temp_path.unlink(missing_ok=True)
                    if words_with_confidence:
                        logger.info(
                            f"  ✅ {len(words_with_confidence)} words from Whisper"
                        )
            except Exception as sub_e:
                logger.warning(f"  Whisper subtitle generation failed: {sub_e}")

    # Fallback: no transcript cache and no Whisper — build from segment.text.
    # Emit one entry per word so the ASS karaoke grouper (3 words / line) works
    # correctly; even spacing is imprecise but still watchable.
    if not words_with_confidence and segment.get("text"):
        # Try Whisper tiny on the extracted audio for real timings
        _whisper_timings = None
        try:
            import subprocess as _sp
            import json as _json
            import tempfile as _tf
            # Extract audio segment for Whisper
            _audio_tmp = Path(_tf.mktemp(suffix=".wav"))
            _extract = _sp.run(
                ["ffmpeg", "-y", "-i", str(temp_segment_path or video_path),
                 "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                 str(_audio_tmp)],
                capture_output=True, text=True, timeout=30,
            )
            if _extract.returncode == 0 and _audio_tmp.exists():
                # Use faster-whisper if available (already installed)
                try:
                    from faster_whisper import WhisperModel
                    _model = WhisperModel("tiny", device="cpu", compute_type="int8")
                    _segments, _info = _model.transcribe(str(_audio_tmp), language="es")
                    _whisper_timings = []
                    for _seg in _segments:
                        for _word in _seg.words:
                            _whisper_timings.append({
                                "word": _word.word.strip(),
                                "start": round(_word.start, 3),
                                "end": round(_word.end, 3),
                                "confidence": round(_word.probability, 3),
                            })
                    del _model  # free memory
                except ImportError:
                    logger.debug("[SUBTITLE] faster-whisper not available for fallback")
            _audio_tmp.unlink(missing_ok=True)
        except Exception as _whisper_e:
            logger.debug("[SUBTITLE] Whisper tiny fallback failed: %s", _whisper_e)

        if _whisper_timings:
            words_with_confidence = _whisper_timings
            logger.info(
                "[SUBTITLE-FALLBACK] ✅ %d words from Whisper tiny",
                len(words_with_confidence),
            )
        else:
            logger.warning("[SUBTITLE-FALLBACK] No cache / Whisper — building from segment.text")
            _words_list = [w for w in segment["text"].split() if w.strip()]
            if _words_list:
                # Use ORIGINAL speech duration (not extended clip duration) to avoid
                # subtitles appearing 2-3x slower than the speaker when clips are padded.
                _orig_speech_dur = (
                    parse_timestamp_to_seconds(segment["end_time"])
                    - parse_timestamp_to_seconds(segment["start_time"])
                )
                # Proportional timing: distribute duration by character length.
                # Short filler words (a, the, in…) get 50% of their share.
                _FILLER = {"a","an","the","is","in","at","to","of","i","and",
                           "or","but","on","it","he","she","we","so","do","be"}
                _char_weights = [
                    max(1, len(_w)) * (0.5 if _w.lower() in _FILLER else 1.0)
                    for _w in _words_list
                ]
                _total_weight = sum(_char_weights) or 1
                _cursor = 0.0
                _EMPHASIS_RE = {"secret","truth","never","always","stop","wrong",
                                "hack","real","exposed","shocking","actually"}
                for _w, _cw in zip(_words_list, _char_weights):
                    _wdur = max(0.06, _orig_speech_dur * _cw / _total_weight)
                    words_with_confidence.append({
                        "word":       _w,
                        "start":      round(_cursor, 3),
                        "end":        round(_cursor + _wdur, 3),
                        "confidence": 0.9,
                        "is_emphasis": _w.lower().strip(".,!?") in _EMPHASIS_RE,
                    })
                    _cursor += _wdur
                logger.info(
                    f"[SUBTITLE-FALLBACK] {len(words_with_confidence)} words from text split"
                )
    
    # When using pre-extracted segment, timestamps are relative to segment start (0)
    # Otherwise, use original timestamps from full video
    if use_extracted_segment:
        # Segment already trimmed to [start_time, end_time] by ffmpeg
        # So we render from 0 to duration
        render_start = 0.0
        render_end = duration
        # Cap duration to actual segment file duration to prevent FFmpeg
        # from requesting more video than exists (e.g., platform cap extends
        # duration to 60s but segment is only 10s near video end).
        try:
            import subprocess as _sp, json as _json
            _probe = _sp.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(video_path)],
                capture_output=True, text=True, timeout=10
            )
            _seg_dur = float(_json.loads(_probe.stdout).get("format", {}).get("duration", 0))
            if _seg_dur > 0 and render_end > _seg_dur:
                logger.info(
                    f"Duration capped: {render_end:.1f}s → {_seg_dur:.1f}s "
                    f"(segment file limit)"
                )
                render_end = _seg_dur
        except Exception as _probe_e:
            logger.debug(f"Could not probe segment duration: {_probe_e}")
        logger.debug(f"Rendering from pre-extracted segment: 0-{render_end:.1f}s")
    else:
        # Render from full video using original timestamps
        render_start = start_seconds
        render_end = end_seconds
        logger.debug(f"Rendering from full video: {start_seconds:.1f}-{end_seconds:.1f}s")

    # FFmpegGuard: validate segment params before FFmpeg — catches bad coordinates early
    try:
        from ...video_processing.ffmpeg_guard import validate_segment_call
        validate_segment_call(
            source_path=str(video_path),
            ss=render_start,
            to=render_end,
            context=f"clip_{clip_index + 1}",
        )
    except (ValueError, FileNotFoundError) as _fg_err:
        logger.error(f"  [FFmpegGuard] Invalid segment params: {_fg_err}")
        return None
    except Exception as _fg_e:
        logger.debug(f"  [FFmpegGuard] skipped: {_fg_e}")

    success = await run_in_thread(
        create_optimized_clip,
        video_path,
        render_start,
        render_end,
        clip_path,
        add_subtitles,
        font_family,
        font_size,
        font_color,
        caption_template,
        output_format,
        split_screen,
        hook_title,
        elite_metadata=elite_metadata,
        gpu_encoding_settings=gpu_encoding_settings,
        target_platform=target_platform,
        use_extracted_segment=use_extracted_segment,
    )

    if not success:
        logger.error(f"Failed to create base clip {clip_index + 1}")
        return None

    output_path = clip_path
    _guard_output_duration(str(video_path), str(output_path), "create_optimized_clip",
                           declared_duration=(render_end - render_start))
    _flash_ts: List[float] = []  # cut-boundary timestamps for flash overlay

    # ── Step 4.0b: Re-alineacion precisa de subtitulos ──────────────
    # Re-transcribir el clip ya cortado para eliminar drift acumulado
    # del video original. Solo si hay words_with_confidence disponibles.
    #
    # TIMING PATH (exact flow for subtitle timestamps):
    #   1. Original transcript → words_with_confidence (from AssemblyAI/Groq/faster-whisper)
    #   2. Re-alignment via ConfidenceSubtitleGenerator.realign_on_segment():
    #      a. Extract audio from the cut clip (16kHz mono WAV)
    #      b. Re-transcribe with faster-whisper (small model by default)
    #      c. Compare similarity between original and re-transcribed text
    #      d. FALLBACK RULE:
    #         - similarity >= 70% (SIMILARITY_SAFE_THRESHOLD): use re-transcription (text + timestamps)
    #         - 30% <= similarity < 70%: use original texts (preserves accents/punctuation) + re-transcription timestamps
    #         - similarity < 30% (SIMILARITY_CRITICAL_THRESHOLD): ⛔ REJECT re-transcription entirely
    #           → return original_words with original timestamps
    #           → caller applies cumulative offsets for jump-cuts/silence removal
    #   3. Cumulative offset adjustment (lines 1365-1399): shift word timestamps for removed intervals
    #   4. Word-level cut-point snapping (lines 1405-1439): fix words straddling cut boundaries
    #   5. Phrase-aware grouping (lines 1444-1477): merge isolated words
    #   6. Final timing pass (lines 1279-1356): probe rendered clip audio for speech segments
    #   7. ASS caption burn-in with clip_start=0.0 (words already rebased to clip timeline)
    _realign_enabled = os.environ.get("SUBTITLE_REALIGN_ENABLED", "true").lower() == "true"
    logger.info(
        f"[RE-ALIGN] Check: enabled={_realign_enabled} "
        f"words={len(words_with_confidence) if words_with_confidence else 0} "
        f"path_exists={os.path.exists(str(output_path))} "
        f"| TIMING PATH: original_transcript → re-align → cumulative_offset → "
        f"cut_snapping → phrase_grouping → final_timing_pass → ASS_burn"
    )
    if _realign_enabled and words_with_confidence and os.path.exists(str(output_path)):
        try:
            _realign_model = os.environ.get("SUBTITLE_REALIGN_MODEL", "small")
            _whisper_device = os.environ.get("WHISPER_DEVICE", "auto")
            _anticipation_ms = float(os.environ.get("SUBTITLE_ANTICIPATION_MS", "0"))

            from ...domains.captions.confidence_subtitle_service import ConfidenceSubtitleGenerator
            _realigner = ConfidenceSubtitleGenerator(
                model_size=_realign_model,
                device=_whisper_device
            )
            _realigned = _realigner.realign_on_segment(
                segment_video_path=str(output_path),
                original_words=words_with_confidence,
                language=target_language,
                anticipation_offset_ms=_anticipation_ms,
                clip_start=start_seconds
            )
            if _realigned:
                # Log the exact timing path decision
                _orig_text_preview = ' '.join(
                    w.get('word', w.get('text', '')) for w in words_with_confidence[:5]
                )
                _real_text_preview = ' '.join(
                    w.get('word', w.get('text', '')) for w in _realigned[:5]
                )
                logger.info(
                    f"[CLIP] Re-alineacion OK: {len(words_with_confidence)} → {len(_realigned)} palabras | "
                    f"FALLBACK RULE applied by realign_on_segment() | "
                    f"Original preview: '{_orig_text_preview}...' | "
                    f"Realigned preview: '{_real_text_preview}...'"
                )
                words_with_confidence = _realigned
            else:
                logger.warning("[CLIP] Re-alineacion retorno vacio, manteniendo originales")
        except Exception as e:
            logger.warning(f"[CLIP] Re-alineacion fallo ({e}), manteniendo originales")

    # Step 4.0c: Semantic Edit Planning — word-level B-roll and SFX cues.
    # Runs after words_with_confidence is finalised (post-realignment).
    _sem_plan = None
    try:
        from ...agents.semantic_edit_planner import SemanticEditPlanner
        _sem_plan = await SemanticEditPlanner().plan(
            words=words_with_confidence,
            duration=duration,
            hook_type=(segment.get("hook_type") or "insight_reveal"),
            category=getattr(_clip_profile, "content_category", "unknown"),
            clip_path=str(output_path) if output_path.exists() else None,
        )
        segment["_semantic_plan"] = _sem_plan
    except Exception as _spe:
        logger.debug("[SemanticPlanner] skipped: %s", _spe)

    # Step 4.0d: Master Director — section-aware decisions for THIS clip.
    # Slices clip into hook/build/payoff/cta and assigns per-section overrides
    # for SFX volume, zoom intensity, B-roll allowance, flash, captions.
    _render_plan = None
    try:
        from ...agents.master_director import MasterDirector
        _render_plan = await MasterDirector().direct(
            segment       = segment,
            words         = words_with_confidence,
            duration      = duration,
            category      = getattr(_clip_profile, "content_category", "motivation_mindset"),
            narrative     = getattr(_clip_profile, "narrative", None),
            profile       = _clip_profile,
            semantic_plan = _sem_plan,
            platform      = (target_platform or "universal").lower(),
        )
        segment["_render_plan"] = _render_plan
        logger.info(
            "  [Director] %d sections | %s",
            len(_render_plan.sections),
            " | ".join(
                f"{s.name}@[{s.t_start:.1f}-{s.t_end:.1f}s "
                f"sfx={s.sfx_volume_mult:.2f}× zoom≤{s.zoom_factor_max:.2f}× "
                f"broll={'Y' if s.broll_allowed else 'N'}]"
                for s in _render_plan.sections
            ),
        )
    except Exception as _md_e:
        logger.debug("[Director] skipped: %s", _md_e)

    # Step 4.0e: Hook reorder — physically move the strongest hook to t=0
    # if HookEngine flagged it AND duration permits. Words are remapped.
    if (_render_plan
            and _render_plan.hook_reorder
            and os.environ.get("HOOK_REORDER_ENABLED", "true").lower() != "false"
            and output_path.exists()):
        try:
            from .hook_reorder import reorder_hook
            _hr_out = output_path.with_name(f"hr_{output_path.name}")
            _hr_words = await reorder_hook(
                video_path=str(output_path),
                output_path=str(_hr_out),
                source_t=_render_plan.hook_source_t,
                duration=duration,
                words=words_with_confidence,
            )
            if _hr_words is not None and _hr_out.exists():
                _hr_out.replace(output_path)
                if _hr_words:
                    words_with_confidence = _hr_words
                logger.info(
                    "  ✓ Hook reorder applied: t=%.1fs → t=0 (semantic plan & sections "
                    "remain valid for new timeline)",
                    _render_plan.hook_source_t,
                )
        except Exception as _hr_e:
            logger.debug("[HookReorder] skipped: %s", _hr_e)

    # Hook-type opening treatment: inject strategic flash at t=0.15s.
    # scroll_stop / pattern_interrupt → immediate white flash punch.
    # cliffhanger / dramatic → silence is the tool, no flash.
    _hook_type_str = (
        segment.get("phi3_hook_type") or segment.get("hook_type") or ""
    ).lower().replace(" ", "_")
    _FLASH_HOOKS = {"scroll_stop", "pattern_interrupt", "curiosity_gap"}
    _clip_profile_zoom = getattr(_clip_profile, "zoom_intensity", "medium") if _clip_profile else "medium"
    if _hook_type_str in _FLASH_HOOKS and _clip_profile_zoom != "off":
        _flash_ts.append(0.15)
        logger.info("  ✓ Hook flash injected at t=0.15s (hook=%s)", _hook_type_str)

    # Step 4.1b: ESRGAN Video Upscaling (Phase 3.3 — GPU only, opt-in)
    _esrgan_enabled = os.environ.get("ESRGAN_ENABLED", "false").lower() == "true"
    if _esrgan_enabled:
        try:
            from ...domains.upscaling.upscaling_service import UpscalingService
            _esrgan_svc = UpscalingService()
            if _esrgan_svc.is_available():
                _esrgan_out = output_path.with_name(f"up_{output_path.name}")
                _esrgan_res = await _esrgan_svc.upscale(
                    str(output_path),
                    scale_factor=int(os.environ.get("ESRGAN_SCALE", "2")),
                    output_path=str(_esrgan_out),
                )
                if _esrgan_out.exists():
                    output_path = _esrgan_out
                    logger.info(
                        f"  ✓ ESRGAN: {_esrgan_res.get('original_resolution')} → "
                        f"{_esrgan_res.get('output_resolution')}"
                    )
        except Exception as _esrgan_e:
            logger.debug(f"  ESRGAN upscaling skipped: {_esrgan_e}")

    # Step 4.2: Audio denoising — now merged into EditingPipeline (afftdn in filter_complex)
    # Step 4.3: B-Roll overlay — moved to after EditingPipeline (see below).

    # Step 4.2b: RVC Voice Enhancement (Phase 3.2 — vocal clarity + presence boost)
    _rvc_enabled = os.environ.get("RVC_ENABLED", "false").lower() == "true"
    if _rvc_enabled:
        try:
            _rvc_out = output_path.with_name(f"rvc_{output_path.name}")
            _rvc_ok = await apply_voice_enhancement(
                str(output_path), str(_rvc_out),
                model_path=os.environ.get("RVC_MODEL_PATH", ""),
            )
            if _rvc_ok and _rvc_out.exists():
                output_path = _rvc_out
                logger.info("  ✓ RVC voice enhancement applied")
        except Exception as _rvc_e:
            logger.debug(f"  RVC skipped: {_rvc_e}")

    # Step 4.2c: TTS Narration — inject AI narrator via VoiceSynthesisService (ElevenLabs/OpenAI TTS)
    _tts_enabled = os.environ.get("TTS_NARRATION_ENABLED", "false").lower() == "true"
    if _tts_enabled:
        try:
            from ...domains.audio.voice_synthesis import VoiceSynthesisService, VoiceStyle
            _vs_svc = VoiceSynthesisService()
            _tts_out = output_path.with_name(f"tts_{output_path.name}")
            _vs_result = await _vs_svc.narrate_video(
                video_path=output_path,
                output_path=_tts_out,
                text=segment.get("text", "") if segment else "",
                style=VoiceStyle.CONVERSATIONAL,
                language=os.environ.get("TTS_LANGUAGE", "en"),
            )
            if _vs_result and _tts_out.exists():
                output_path = _tts_out
                logger.info(f"  ✓ Voice synthesis narration injected (provider={_vs_result.get('provider','auto')})")
        except Exception as _tts_e:
            logger.debug(f"  Voice synthesis skipped: {_tts_e}")

    # ── Content Profiler: classify clip type → conditional service activation ──
    _content_profile: Dict[str, Any] = {"type": "unknown", "recommended_zoom": True, "recommended_jump_cuts": True}
    try:
        from ...domains.autopilot.content_profiler import profile_content
        _content_profile = profile_content(
            video_path=str(output_path),
            words=words_with_confidence or [],
            duration=duration,
        )
        logger.info(
            "  [Profiler] type=%s speech=%.2f scenes=%d zoom=%s jump=%s",
            _content_profile["type"], _content_profile["speech_ratio"],
            _content_profile["scene_changes"],
            _content_profile["recommended_zoom"],
            _content_profile["recommended_jump_cuts"],
        )
    except Exception as _prof_e:
        logger.debug("  [Profiler] skipped: %s", _prof_e)

    # Step 4.2-jc: Silence handling — jump-cut OR speed-ramp based on SILENCE_MODE.
    # Must happen BEFORE subtitle burn so ASS timestamps stay in sync.
    # Only activate for talking_head (high speech ratio, few scene changes).
    # Initialize _jc_keep to safe default BEFORE any conditional logic so that
    # downstream code (cumulative offset, cut-point snapping) never crashes with
    # UnboundLocalError when jump cuts are disabled, skipped, or produce no intervals.
    _jc_keep: Optional[List[Tuple[float, float]]] = None
    _jump_cut_active = jump_cut and _content_profile.get("recommended_jump_cuts", True)
    if words_with_confidence and _jump_cut_active:
        logger.info("  [JC] Jump-cut active — attempting silence removal")
        try:
            _silence_thresh = float(
                os.environ.get("SILENCE_THRESHOLD_SECONDS", str(SILENCE_THRESHOLD))
            )
            _jc_keep, _jc_saved = build_keep_intervals(
                words_with_confidence, duration, _silence_thresh
            )
            if _jc_saved >= MIN_SILENCE_SAVINGS and len(_jc_keep) >= 2:
                _jc_path = output_path.with_name(f"jc_{output_path.name}")
                if SILENCE_MODE == "ramp":
                    _jc_ok = await speed_ramp_silences(
                        str(output_path), str(_jc_path),
                        words_with_confidence, duration, _silence_thresh,
                    )
                else:
                    _jc_ok = await remove_silences(
                        str(output_path), str(_jc_path),
                        words_with_confidence, duration, _silence_thresh,
                    )
                if _jc_ok and _jc_path.exists():
                    _prev_path = str(output_path)
                    output_path = _jc_path
                    _guard_output_duration(_prev_path, str(output_path), "silence_removal")
                    words_with_confidence = _helpers.adjust_words_for_cuts(
                        words_with_confidence, _jc_keep
                    )
                    # Compute flash positions in the NEW (post-cut) timeline
                    # Each flash fires at the cumulative end of previous segment
                    _flash_ts = []
                    _cumulative = 0.0
                    for _fs, _fe in _jc_keep:
                        if _cumulative > 0.1:
                            _flash_ts.append(_cumulative)
                        _cumulative += (_fe - _fs)
                    mode_label = "Speed-ramp" if SILENCE_MODE == "ramp" else "Jump cuts"
                    logger.info(
                        f"  ✓ {mode_label} applied ({_jc_saved:.1f}s handled), "
                        f"subtitle timestamps adjusted"
                    )
                    # BUG H: Re-probe duration after silence removal — the cut changes
                    # the clip length, and downstream steps (b-roll, EP) use the
                    # original duration which can cause misalignment.
                    _new_dur = _get_duration(str(output_path))
                    if _new_dur > 0:
                        logger.info(
                            f"  Duration re-probed after silence removal: "
                            f"{duration:.1f}s → {_new_dur:.1f}s"
                        )
                        duration = _new_dur
                    else:
                        logger.warning(
                            "  Could not re-probe duration after silence removal — "
                            "keeping original duration %.1fs", duration
                        )
        except Exception as _jc_e:
            logger.debug(f"  Silence handling skipped: {_jc_e}")

    # Step 4.2d: Cut Zoom — dynamic zoom punches at jump-cut points (Hormozi/MrBeast)
    # Priority: vision zoom_cues (precise) > word-boundary cuts (structural)
    if os.environ.get("CUT_ZOOM_ENABLED", "true").lower() == "true":
        try:
            from .cut_zoom_service import apply_cut_zooms
            # Seed with word boundaries (structural rhythm)
            _cut_points = [
                w["end"] for w in (words_with_confidence or [])
                if w.get("end") and w.get("probability", 1.0) > 0.85
            ][::4]  # every 4th word boundary to avoid over-zooming
            # Inject vision zoom_cues at the FRONT — they get priority in the [:8] cap
            _vision_zoom_ts = [
                z.timestamp for z in (getattr(_sem_plan, "zoom_cues", None) or [])
            ]
            if _vision_zoom_ts:
                logger.info(
                    "  [Zoom] Vision zoom cues: %s",
                    [f"{t:.1f}s" for t in _vision_zoom_ts],
                )
                _cut_points = _vision_zoom_ts + [
                    t for t in _cut_points
                    if all(abs(t - vt) > 1.5 for vt in _vision_zoom_ts)
                ]

            # Section-aware filter: drop zoom points in sections with
            # zoom_factor_max <= 1.0 (CTA) and pick zoom intensity from
            # the strongest section that still has zoom enabled.
            _section_zoom_max = 1.08  # default
            if _render_plan:
                _filtered = [
                    t for t in _cut_points
                    if (_sec := _render_plan.section_at(t)) and _sec.zoom_factor_max > 1.0
                ]
                if len(_filtered) < len(_cut_points):
                    logger.info(
                        "  [Zoom] Director dropped %d cut points (CTA / zoom-off sections)",
                        len(_cut_points) - len(_filtered),
                    )
                _cut_points = _filtered
                # Use the max zoom across allowed sections (typically payoff)
                _section_zoom_max = max(
                    (s.zoom_factor_max for s in _render_plan.sections if s.zoom_factor_max > 1.0),
                    default=1.08,
                )

            if _cut_points:
                _cz_out = output_path.with_name(f"cz_{output_path.name}")
                _cz_ok = await apply_cut_zooms(
                    video_path=str(output_path),
                    output_path=str(_cz_out),
                    cut_points=_cut_points[:8],  # max 8 zoom points
                    zoom_factor=_section_zoom_max,
                )
                if _cz_ok and _cz_out.exists():
                    _cz_out.replace(output_path)
                    logger.info(f"  ✓ Cut zooms applied ({len(_cut_points[:8])} points, "
                                f"{len(_vision_zoom_ts)} from vision, factor={_section_zoom_max:.2f}×)")
        except Exception as _cz_e:
            logger.debug(f"  Cut zoom skipped: {_cz_e}")

    # Step 4.3: B-Roll overlay — moved to after EditingPipeline (see below).

    # Step 4.9: Crop already handled — create_optimized_clip applies
    # crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920 via _PLATFORM_VF
    # during FFmpeg pre-extraction. The output is already 1080×1920.
    # Re-running face-detection crop on 1080×1920 generates wrong
    # dimensions and adds black bars — do NOT apply a second crop here.

    # Step 4.4: ASS Karaoke captions — moved to after EditingPipeline (see below).

    # Step 4.5: Advanced Polish (Auto-centering, Eye Contact, Background Blur)
    if auto_center_face or eye_contact_correction:
        _face_centered = False
        if auto_center_face:
            polished_path = output_path.with_name(f"centered_{output_path.name}")
            # EnhancedTrackingService: SAM2 multi-subject tracking (GPU) when enabled
            _sam2_active = os.environ.get("SAM2_ENABLED", "false").lower() == "true"
            if _sam2_active:
                try:
                    from ...core.enhanced_tracking_service import EnhancedTrackingService
                    _ets = EnhancedTrackingService()
                    _trajectory = await _ets.track_subject(
                        video_path=output_path,
                        start_time=0.0,
                        end_time=duration,
                    )
                    if _trajectory:
                        # Apply dynamic reframe: crop to face centroid trajectory
                        _avg_cx = int(sum(pt[1] for pt in _trajectory) / len(_trajectory))
                        _avg_cy = int(sum(pt[2] for pt in _trajectory) / len(_trajectory))
                        import subprocess as _sp2
                        # Codec con aceleración hardware automática (NVENC/VAAPI/CPU)
                        _codec_flags = gpu_utils.ffmpeg_codec_flags()
                        _ef_cmd = [
                            get_ffmpeg_exe(), "-y", "-i", str(output_path),
                            "-vf", f"crop=in_w:in_h:{max(0,_avg_cx-540)}:{max(0,_avg_cy-960)},scale=1080:1920",
                            *_codec_flags,
                            "-c:a", "copy",
                            str(polished_path),
                        ]
                        _ef_res = _sp2.run(_ef_cmd, capture_output=True, timeout=60)
                        if _ef_res.returncode == 0 and polished_path.exists():
                            output_path = polished_path
                            _face_centered = True
                            logger.info(f"  ✓ SAM2 enhanced tracking: centroid ({_avg_cx},{_avg_cy})")
                except Exception as _ets_e:
                    logger.debug(f"  EnhancedTracking skipped: {_ets_e}")

            # Fallback: MediaPipe VideoPolishService
            if not _face_centered:
                from .video_polish_service import VideoPolishService
                polisher = VideoPolishService()
                _face_centered = await polisher.auto_center_face(output_path, polished_path)
                if _face_centered and polished_path.exists():
                    _prev_path = str(output_path)
                    output_path = polished_path
                    _guard_output_duration(_prev_path, str(output_path), "face_centering")

        # Talking-head auto-detection: if face was found AND audio has words
        # → we're looking at a speaker clip → auto-apply eye contact correction.
        # Override via EYE_CONTACT_AUTO=false to disable.
        _eye_contact_auto = os.environ.get("EYE_CONTACT_AUTO", "true").lower() != "false"
        _is_talking_head = _face_centered and bool(words_with_confidence)
        if eye_contact_correction or (_is_talking_head and _eye_contact_auto):
            try:
                if "polisher" not in dir():
                    from .video_polish_service import VideoPolishService
                    polisher = VideoPolishService()
                polished_path = output_path.with_name(f"gaze_{output_path.name}")
                await polisher.apply_eye_contact_correction(output_path, polished_path)
                if polished_path.exists():
                    _prev_path = str(output_path)
                    output_path = polished_path
                    _guard_output_duration(_prev_path, str(output_path), "gaze_correction")
                    if _is_talking_head and not eye_contact_correction:
                        logger.info("  ✓ Eye contact correction auto-applied (talking head detected)")
            except Exception as _ec_e:
                logger.debug("  Eye contact correction skipped: %s", _ec_e)

    # Step 4.5c: Portrait background blur (MediaPipe Selfie Segmentation).
    # Enabled via BACKGROUND_BLUR_ENABLED=true.  Defaults off — adds ~10s/clip.
    if os.environ.get("BACKGROUND_BLUR_ENABLED", "false").lower() == "true":
        try:
            from .video_polish_service import VideoPolishService as _VPS
            _blur_out = output_path.with_name(f"blur_{output_path.name}")
            _blur_ok = await _VPS().blur_background(output_path, _blur_out)
            if _blur_ok and _blur_out.exists():
                output_path = _blur_out
                logger.info("  ✓ Background blur applied (Selfie Segmentation)")
        except Exception as _bl_e:
            logger.debug("  Background blur skipped: %s", _bl_e)

    # Step 4.7: Hook Visual Overlay — delayed when captions are active to avoid
    # text overlap between the hook text and the karaoke subtitle.
    from ...config import get_config as _get_cfg_hook
    _cfg_hook = _get_cfg_hook()
    captions_enabled = bool(add_subtitles and words_with_confidence)
    hook_delay = _cfg_hook.hook_visual_delay_if_captions if captions_enabled else 0.0
    try:
        hook_service = HookVisualService()
        hook = hook_service.generate_hook_from_segment(segment, duration=2.0, clip_index=clip_index)
        hook.start_time = hook_delay

        hooked_path = output_path.with_name(f"hook_{output_path.name}")
        await hook_service.add_hook_to_video(
            str(output_path),
            str(hooked_path),
            hook,
            subtitle_path=segment.get("colored_subtitle_path")
        )
        if Path(hooked_path).exists():
            output_path = hooked_path
            logger.info(f"  ✓ Hook overlay added (delay={hook_delay}s): {hook.text[:30]}...")
    except Exception as hook_e:
        logger.warning(f"  Hook overlay failed: {hook_e}")

    # Step 4.5b: Beat-sync BPM detection — derive beat timestamps for
    # edit-point alignment BEFORE EditingPipeline so zoom punches land on beats.
    # Try to detect BPM from the BGM track (if available) so zooms align with
    # music beats rather than voice pauses/silence gaps.
    _beat_times: List[float] = []
    _beat_bpm: float = 0.0
    try:
        from ...domains.audio.beat_sync_service import analyse_bpm as _analyse_bpm
        # Try to find BGM path early for beat detection on music, not voice
        _bgm_for_bpm: Optional[Path] = None
        try:
            from ...domains.audio.beat_sync_service import select_bgm, _scan_bgm_library, BGM_LIBRARY_DIR
            _tracks = _scan_bgm_library(BGM_LIBRARY_DIR)
            if _tracks:
                _bgm_track = select_bgm(120.0, _tracks, prefer_category=preferred_music_category or (_clip_profile.bgm_category if _clip_profile else None))
                if _bgm_track:
                    _bgm_for_bpm = _bgm_track.path
                    logger.info(f"  [BPM] Using BGM for beat detection: {_bgm_track.name}")
        except Exception as _bgm_sel_e:
            logger.debug(f"  [BPM] BGM selection for beat detection skipped: {_bgm_sel_e}")

        _bpm_result = await _analyse_bpm(audio_path=output_path, bgm_path=_bgm_for_bpm)
        _beat_bpm   = _bpm_result.get("bpm", 0.0)
        _beat_times = _bpm_result.get("beat_times", [])
        if _beat_times:
            _source_label = "BGM" if _bgm_for_bpm else "voice"
            logger.info(f"  ✓ BPM detected from {_source_label}: {_beat_bpm:.1f} ({len(_beat_times)} beats)")
    except Exception as _bpm_e:
        logger.debug(f"  BPM detection skipped: {_bpm_e}")

    # Merge beat timestamps into flash_timestamps so zoom punches land on beats.
    if _beat_times:
        _flash_ts = sorted(set(_flash_ts) | {
            t for t in _beat_times
            if 0.5 < t < (duration - 0.5)
        })

    # Inject narrative strategic moments (payoff flash, hook zoom) from Editorial Brain
    _narrative = getattr(_clip_profile, "narrative", None) if _clip_profile else None
    if _narrative:
        _cat_rule_flash = True  # default allow
        try:
            from ...domains.ai.editorial_brain import CATEGORY_RULES as _CAT_RULES
            _cat_key = getattr(_clip_profile, "content_category", "")
            _cat_rule_flash = _CAT_RULES.get(_cat_key, list(_CAT_RULES.values())[0]).flash_allowed if _cat_key else True
        except Exception:
            pass
        if _cat_rule_flash and _narrative.flash_moments:
            _flash_ts = sorted(set(_flash_ts) | {
                t for t in _narrative.flash_moments
                if 0.5 < t < (duration - 0.5)
            })
            logger.info("  ✓ Narrative payoff flash at %s",
                        [f"{t:.1f}s" for t in _narrative.flash_moments])

    # Cap flash timestamps — scale by energy: chill=0, medium=1, high=3.
    _flash_cap = 0 if (_clip_profile and _clip_profile.zoom_intensity == "off") else \
                 1 if (_clip_profile and _clip_profile.energy < 0.45) else \
                 2 if (_clip_profile and _clip_profile.energy < 0.70) else 3
    _flash_min_gap = 5.0 if (_clip_profile and _clip_profile.energy < 0.5) else 4.0
    _flash_ts_capped: List[float] = []
    _last_flash_t = -10.0
    for _ft in _flash_ts:
        if _ft - _last_flash_t >= _flash_min_gap:
            _flash_ts_capped.append(_ft)
            _last_flash_t = _ft
        if len(_flash_ts_capped) >= _flash_cap:
            break
    _flash_ts = _flash_ts_capped

    # Director section-aware flash filter: drop flashes in sections where
    # flash_allowed=False (CTA always, calm categories outside payoff).
    if _render_plan and _flash_ts:
        _before = len(_flash_ts)
        _flash_ts = [
            t for t in _flash_ts
            if (_sec := _render_plan.section_at(t)) and _sec.flash_allowed
        ]
        if len(_flash_ts) < _before:
            logger.info(
                "  [Flash] Director dropped %d flashes (section flash_allowed=False)",
                _before - len(_flash_ts),
            )

    # Step 4.6: Editing Pipeline — color grading, cinematic look, vignette,
    # zoom punch-in / Ken Burns / pattern interrupts, lower thirds,
    # progress bar, loudness normalization (single FFmpeg pass).
    _lut_preset_ep = ""  # pre-init so always defined even if EP try block fails early
    _lut_vf_ep = ""
    try:
        _ep = EditingPipeline()
        _ep_out = output_path.with_name(f"ep_{output_path.name}")
        _ep_segment_text = segment.get("text", "")[:60] if segment else ""
        # Resolve LUT filter string here so EP can bake it in one pass
        # Use JobContext-based rotation when available, otherwise fall back
        # to the legacy clip_index rotation.
        from .lut_service import select_lut_by_context as _select_lut_ctx
        from .lut_service import select_lut as _select_lut
        _total_clips = max(1, segment.get("_total_clips", 1))
        _visual_style = segment.get("visual_style", "")
        if job_ctx is not None:
            _lut_vf_ep = _select_lut_ctx(
                ctx=job_ctx,
                clip_index=clip_index,
                visual_style=_visual_style,
            )
            _lut_preset_ep = _lut_vf_ep  # store the filter string directly
        else:
            _lut_preset_ep = (
                (_clip_profile.lut if _clip_profile else None)
                or _select_lut(clip_index=clip_index, total_clips=_total_clips)
            )
            _lut_vf_ep = ""
            if _lut_preset_ep and _lut_preset_ep.lower() not in ("none", "off", "false", ""):
                try:
                    from .lut_service import get_lut_vf_filter as _get_lut_vf
                    _lut_vf_ep = _get_lut_vf(_lut_preset_ep) or ""
                except Exception:
                    _lut_vf_ep = ""


        _ep_result = await _ep.apply(
            video_path=output_path,
            words=words_with_confidence,
            output_path=_ep_out,
            segment_text=_ep_segment_text,
            flash_timestamps=_flash_ts or None,  # Subtle flashes (intensidad reducida via EP_FLASH_INTENSITY)
            gpu_settings=gpu_encoding_settings if gpu_encoding_settings else None,
            energy_level=_clip_profile.energy if _clip_profile else 0.5,
            zoom_intensity=_clip_profile.zoom_intensity if _clip_profile else "medium",
            grain_override=_clip_profile.grain if _clip_profile else 0,
            lut_vf=_lut_vf_ep,
            denoise_audio=True,
            sections=(_render_plan.sections if _render_plan else None),
        )
        if _ep_result == _ep_out and _ep_out.exists():
            output_path = _ep_out
            logger.info("  ✓ EditingPipeline: color+cine+vignette+zoom+PI+lower-third+progress+loudnorm")
    except Exception as _ep_e:
        logger.warning(f"  EditingPipeline failed: {_ep_e}")

    # Step 4.6b: LUT now merged into EditingPipeline — standalone pass removed.
    if _lut_vf_ep:
        logger.info(f"  ✓ LUT '{_lut_preset_ep}' baked into EditingPipeline pass")

    # Step 4.3: B-Roll overlay — after EP so vignette/LUT don't darken B-roll.
    # This is the SINGLE authoritative B-roll path. If it succeeds, Step 4.3b
    # (ContextualOverlayEngine) is skipped to prevent duplicate independent
    # planners writing conflicting visuals to the same clip.
    _broll_planned = False
    from ...config import get_config as _get_cfg_broll
    _broll_cfg = _get_cfg_broll()
    logger.info(f"[BRoll] Gate check: broll_enabled={_broll_cfg.broll_enabled}")
    if _broll_cfg.broll_enabled:
        try:
            from ...domains.broll.broll_service import BrollService
            _broll_svc = BrollService()
            _broll_out = output_path.with_name(f"broll_{output_path.name}")
            _broll_kw_override = (_clip_profile.ai_keywords
                                  if _clip_profile and _clip_profile.ai_keywords
                                  else None)
            # RULE 4: Get or create seen_concepts set for this task
            _seen_concepts = _get_seen_concepts(task_id)
            # Snapshot pre-clip concepts to distinguish within-task vs cross-clip repeats
            _pre_clip_concepts = set(_seen_concepts)
            _broll_result = await _broll_svc.process_clip(
                video_path=str(output_path),
                output_path=str(_broll_out),
                segment_text=segment.get("text", ""),
                clip_duration=duration,
                max_overlays=_clip_profile.broll_count if _clip_profile else 3,
                overlay_duration_s=_clip_profile.broll_duration if _clip_profile else 3.0,
                words_with_timestamps=words_with_confidence or None,
                precomputed_keywords=_broll_kw_override,
                broll_fade_s=_clip_profile.broll_fade_s if _clip_profile else 0.6,
                lut_vf=_lut_vf_ep,  # Apply same LUT grade to B-roll for visual consistency
                task_id=task_id,  # Pass task_id for anti-repetition across clips
                seen_concepts=_seen_concepts,  # RULE 4: concept-level tracking across clips
                pre_clip_concepts=_pre_clip_concepts,  # RULE 4: snapshot for within-task vs cross-clip logging
            )
            if Path(_broll_result).exists() and _broll_result != str(output_path):
                output_path = Path(_broll_result)
                _broll_planned = True  # Mark as planned so Step 4.3b is skipped
                logger.info(f"  ✓ B-roll overlay applied (post-EP)")
        except Exception as _broll_e:
            logger.warning(f"  B-roll overlay failed: {_broll_e}")

    # Step 4.3b: Contextual Overlay Engine — keyword→image/video overlays (viral TikTok feature)
    # Only runs if Step 4.3 did NOT place any B-roll (single authoritative planner).
    _ctx_overlays_env = os.environ.get("CONTEXTUAL_OVERLAYS_ENABLED", "true").lower() == "true"
    if _ctx_overlays_env and not _broll_planned and segment and words_with_confidence:
        try:
            from ...domains.broll.contextual_overlay_engine import ContextualOverlayEngine
            _ctx_engine = ContextualOverlayEngine()
            _ctx_out = output_path.with_name(f"ctx_{output_path.name}")
            _ctx_result = await _ctx_engine.apply_overlays(
                video_path=output_path,
                output_path=_ctx_out,
                transcript=segment.get("text", ""),
                word_timings=words_with_confidence,
                virality_score=getattr(_clip_profile, "virality_score", 70.0) if _clip_profile else 70.0,
                overlay_frequency="adaptive",
            )
            if _ctx_result.success and _ctx_out.exists():
                output_path = _ctx_out
                logger.info(f"  ✓ Contextual overlays: {_ctx_result.overlays_applied} applied ({_ctx_result.keywords_detected} keywords)")
        except Exception as _ctx_e:
            logger.debug(f"  Contextual overlay engine skipped: {_ctx_e}")

    # Step 4.3c: Viral Effects — content-aware visual enhancement
    _viral_fx_env = os.environ.get("VIRAL_EFFECTS_ENABLED", "true").lower() == "true"
    if _viral_fx_env:
        try:
            from ...video_processing.viral_effects import analyze_content_type_for_effects, get_effects_for_content
            _seg_text = segment.get("text", "") if segment else ""
            _content_type = analyze_content_type_for_effects(_seg_text)
            _fx_list = get_effects_for_content(_content_type)
            if _fx_list:
                logger.info(f"  ✓ Viral effects profile: {_content_type} ({len(_fx_list)} effects queued)")
        except Exception as _vfx_e:
            logger.debug(f"  Viral effects skipped: {_vfx_e}")

        # ── Hook subtitle from frame 0: force first word to start at t=0 ──
        if words_with_confidence and words_with_confidence[0]["start"] > 0:
            logger.info(
                "[HOOK-SUB] Forcing first word start from "
                f"{words_with_confidence[0]['start']:.3f}s → 0.0s"
            )
            words_with_confidence[0]["start"] = 0.0

        # ── Final subtitle timing pass using the rendered clip timeline ──
        # After all cuts, silence removal, and overlays, probe the rendered
        # clip to find actual word boundaries. Shift subtitles that are too
        # early or too late relative to the visual cue.
        if words_with_confidence and output_path.exists():
            try:
                import subprocess as _sp_final
                import json as _json_final
                import re as _re_final
                
                # Probe the rendered clip's audio to find speech segments
                _probe_cmd = [
                    "ffmpeg", "-v", "quiet", "-i", str(output_path),
                    "-af", "silencedetect=noise=-30dB:d=0.3,ametadata=mode=print:file=-",
                    "-f", "null", "-",
                ]
                _probe_res = _sp_final.run(_probe_cmd, capture_output=True, text=True, timeout=30)
                _probe_out = _probe_res.stderr
                
                # Parse silence start/end timestamps
                _speech_segments = []
                _silence_starts = []
                _silence_ends = []
                for _line in _probe_out.splitlines():
                    _m = _re_final.search(r"silence_start: ([0-9.]+)", _line)
                    if _m:
                        _silence_starts.append(float(_m.group(1)))
                    _m = _re_final.search(r"silence_end: ([0-9.]+)", _line)
                    if _m:
                        _silence_ends.append(float(_m.group(1)))
                
                # Build speech segments (inverse of silence)
                _speech_segments = []
                _cursor = 0.0
                for _ss, _se in zip(_silence_starts, _silence_ends):
                    if _ss > _cursor:
                        _speech_segments.append((_cursor, _ss))
                    _cursor = _se
                if _cursor < duration:
                    _speech_segments.append((_cursor, duration))
                
                if _speech_segments:
                    # Adjust each word to align with the nearest speech segment
                    _final_words = []
                    for _w in words_with_confidence:
                        _ws = float(_w.get("start", 0))
                        _we = float(_w.get("end", 0))
                        
                        # Find the speech segment this word belongs to
                        for _seg_start, _seg_end in _speech_segments:
                            if _seg_start <= _ws <= _seg_end:
                                # Word is inside a speech segment — keep as-is
                                break
                            elif _ws < _seg_start and _we > _seg_start:
                                # Word starts before speech but overlaps — shift forward
                                _shift = _seg_start - _ws
                                if _shift < 0.3:  # safe margin
                                    _ws = _seg_start + 0.02
                                    _we = min(_we + _shift, _seg_end)
                                    logger.debug(
                                        "[SUBTITLE] Final timing: shifted word '%s' forward by %.2fs",
                                        _w.get("word", ""), _shift,
                                    )
                                break
                            elif _ws > _seg_end and _seg_end < duration:
                                # Word is after this speech segment — check next
                                continue
                    
                        _final_words.append({
                            "word": _w.get("word", ""),
                            "start": max(0, _ws),
                            "end": max(0, _we),
                        })
                    
                    if len(_final_words) == len(words_with_confidence):
                        words_with_confidence = _final_words
                        logger.info(
                            "[SUBTITLE] Final timing pass: adjusted %d words using rendered clip timeline",
                            len(words_with_confidence),
                        )
            except Exception as _final_e:
                logger.debug("[SUBTITLE] Final timing pass skipped: %s", _final_e)

        # Step 4.4: ASS Karaoke captions — after B-roll so text burns on top.
    _caption_system_used: str = "none"
    if add_subtitles and words_with_confidence:
        # ── FIX: Cumulative offset removed — words are already clip-relative ──
        # After realign_on_segment() rebases timestamps to clip-relative, applying
        # cumulative offset again causes double-subtraction and subtitle drift.
        # The cut_snapping and phrase_grouping steps below handle boundary alignment.
        
        # ── Word-level cut-point snapping ──
        # If a word overlaps a cut point, snap the word start/end to the
        # nearest valid boundary. Keep word groups together when they
        # belong to the same phrase. Do not leave a single word isolated.
        if _jc_keep and len(_jc_keep) > 1:
            _cut_boundaries = [_ke for _, _ke in _jc_keep[:-1]]  # cut points between keep segments
            if _cut_boundaries:
                _snapped_words = []
                for _w in words_with_confidence:
                    _ws = float(_w.get("start", 0))
                    _we = float(_w.get("end", 0))
                    _word_text = _w.get("word", "")
                    
                    # Check if this word overlaps a cut boundary
                    for _cb in _cut_boundaries:
                        if _ws < _cb < _we:
                            # Word straddles a cut — snap to nearest side
                            _dist_to_start = _cb - _ws
                            _dist_to_end = _we - _cb
                            if _dist_to_start < _dist_to_end:
                                # Snap start to cut boundary
                                _ws = _cb + 0.02
                            else:
                                # Snap end to cut boundary
                                _we = _cb - 0.02
                            logger.debug(
                                "[SUBTITLE] Snapped word '%s' at cut t=%.2fs (start=%.2f→%.2f, end=%.2f→%.2f)",
                                _word_text, _cb,
                                float(_w.get("start", 0)), _ws,
                                float(_w.get("end", 0)), _we,
                            )
                            break
                    
                    _snapped_words.append({
                        "word": _word_text,
                        "start": max(0, _ws),
                        "end": max(0, _we),
                    })
                words_with_confidence = _snapped_words
        
        # ── Phrase-aware grouping: merge single isolated words ──
        # If a word is the only one in its line (gap > 0.8s on both sides),
        # merge it with the previous or next group.
        if len(words_with_confidence) > 2:
            _merged_words = []
            for i, _w in enumerate(words_with_confidence):
                _ws = float(_w.get("start", 0))
                _we = float(_w.get("end", 0))
                _prev_end = float(words_with_confidence[i-1].get("end", 0)) if i > 0 else -1
                _next_start = float(words_with_confidence[i+1].get("start", 0)) if i < len(words_with_confidence) - 1 else 999
                
                # Check if this word is isolated (gap > 0.8s on both sides)
                _gap_prev = _ws - _prev_end if i > 0 else 999
                _gap_next = _next_start - _we if i < len(words_with_confidence) - 1 else 999
                
                if _gap_prev > 0.8 and _gap_next > 0.8 and len(words_with_confidence) > 2:
                    # Merge with the closer neighbor
                    if _gap_prev < _gap_next and i > 0:
                        # Merge with previous word
                        _merged_words[-1]["end"] = _we
                        logger.debug(
                            "[SUBTITLE] Merged isolated word '%s' with previous (gap=%.2fs)",
                            _w.get("word", ""), _gap_prev,
                        )
                    elif i < len(words_with_confidence) - 1:
                        # Merge with next word by extending this word's end
                        _w["end"] = _next_start + 0.1
                        _merged_words.append(_w)
                        logger.debug(
                            "[SUBTITLE] Extended isolated word '%s' to next (gap=%.2fs)",
                            _w.get("word", ""), _gap_next,
                        )
                    else:
                        _merged_words.append(_w)
                else:
                    _merged_words.append(_w)
            words_with_confidence = _merged_words
        try:
            from ...domains.captions.caption_service import CaptionService as _CS, burn_captions as _burn_caps
            logger.info(f"  Burning ASS captions ({len(words_with_confidence)} words)...")
            _cap_style_raw = (_clip_profile.caption_style if _clip_profile else None) or _CS.style_for_template(caption_template, target_platform)
            _cap_style = "highlight" if _cap_style_raw == "minimal" else _cap_style_raw
            subtitled_path = output_path.with_name(f"sub_{output_path.name}")
            _cap_ok = await _burn_caps(
                output_path, subtitled_path,
                words_with_confidence,
                style=_cap_style,
                platform=target_platform,
                caption_offset_y=caption_offset_y,
                clip_index=clip_index,
                clip_start=0.0,  # Words already rebased to clip-relative timeline after cumulative offset adjustments (lines 1346-1384)
            )

            if _cap_ok and subtitled_path.exists():
                output_path = subtitled_path
                _caption_system_used = "captionservice"
                logger.info(f"  ✓ ASS captions burned (style={_cap_style}, platform={target_platform})")
            else:
                raise RuntimeError("caption_service returned False")
        except Exception as burn_e:
            logger.error(
                "[CAPTION] CaptionService failed: %s — falling back to legacy subtitles",
                burn_e, exc_info=True,
            )
            try:
                subtitled_path = output_path.with_name(f"sub_{output_path.name}")
                await _subtitles.burn_subtitles_word_level(
                    str(output_path), words_with_confidence, str(subtitled_path),
                    style=_cap_style if _cap_style in ("hormozi", "mrbeast") else "hormozi",
                )
                if subtitled_path.exists():
                    output_path = subtitled_path
                    _caption_system_used = "legacy_subtitles"
                    logger.info("  ✓ Legacy subtitles burned (fallback)")
            except Exception as _fb_e:
                logger.error(
                    "[CAPTION] Legacy subtitle fallback also failed: %s",
                    _fb_e, exc_info=True,
                )

    # Step 4.7: [Reservado] Real-ESRGAN upscale vía ComfyUI.
    #   Implementación anterior llamaba `ComfyUIBridge.enhance_video()`,
    #   un método que no existía → AttributeError capturado en silencio.
    #   Para reactivarlo hace falta:
    #     1) Instalar ComfyUI-ReActor o ComfyUI_UltimateSDUpscale en custom_nodes.
    #     2) Añadir un workflow en ComfyUIOrchestrator (p.ej. `enhance_video`).
    #     3) Exponerlo por `comfyui_integration.process_with_comfyui("enhance")`.
    #   Mantenemos el bloque desactivado para no generar ruido en logs.

    # Step 4.8: Audio events — detect and apply SFX based on transcript analysis.
    # Uses audio_placement.detect_audio_events (LLM + keyword) to find moments
    # where sound effects enhance the viewing experience, then mixes them in.
    # Graceful degradation: on any failure, the clip is returned unmodified.
    try:
        _transcript_text = segment.get("text", "")
        if _transcript_text and len(_transcript_text.strip()) > 10:
            _audio_events = await detect_audio_events(
                transcript=_transcript_text,
                language=target_language or "es",
                video_duration=duration,
            )
            if _audio_events:
                _sfx_path = output_path.with_name(f"sfx_{output_path.name}")
                _sfx_result = await apply_audio_events(
                    clip_path=str(output_path),
                    events=_audio_events,
                    output_path=str(_sfx_path),
                )
                if _sfx_result and Path(_sfx_result).exists() and _sfx_result != str(output_path):
                    output_path = Path(_sfx_result)
                    logger.info(
                        "  ✓ %d audio events applied (transcript-based SFX)",
                        len(_audio_events),
                    )
                else:
                    logger.debug("  Audio events: apply_audio_events returned no change")
            else:
                logger.debug("  Audio events: no events detected from transcript")
        else:
            logger.debug("  Audio events: no transcript available, skipping")
    except Exception as _audio_ev_e:
        logger.warning("  Audio events detection/application failed: %s", _audio_ev_e)

    # Step 4.10: Platform export — only re-encode when burning hardsubs.
    # When no subtitle file exists use stream copy (near-instant, no quality loss).
    # IMPORTANT: Skip if captions were already burned in Step 4.4 (ASS karaoke)
    # to prevent double-subtitle rendering.
    _sub_path = segment.get("colored_subtitle_path")
    if _sub_path and Path(str(_sub_path)).exists() and _caption_system_used == "none":
        try:
            platform_enum = Platform.TIKTOK if target_platform in ["all", "tiktok"] else \
                            Platform.REELS if target_platform == "reels" else \
                            Platform.SHORTS if target_platform == "shorts" else \
                            Platform.UNIVERSAL
            export_service = ExportService()
            final_path = output_path.with_name(f"final_{output_path.name}")
            cmd = export_service.build_ffmpeg_command(
                str(output_path), str(final_path), platform_enum,
                burn_subtitles=_sub_path,
            )
            import subprocess as _sp
            _sp.run(cmd, capture_output=True, timeout=300)
            if Path(final_path).exists():
                output_path = final_path
                logger.info("  ✓ Platform export with hardsubs")
        except Exception as export_e:
            logger.warning(f"  Platform export failed: {export_e}")
    else:
        logger.info("  ✓ Platform export: skipped (no hardsubs) — stream copy used in BGM pass")

    # Step 4.6: Translation & Dubbing
    try:
        output_path = await _polish.apply_translation_dubbing(
            output_path, target_language,
            absolute_offset_ms=int(start_seconds * 1000),
        )
    except Exception as _trans_e:
        logger.warning(f"Translation/dubbing failed: {_trans_e}. Skipping.")


    # Beat-synced BGM: use BeatSyncService (auto BPM match + adaptive ducking).
    # Falls back to niche-based static track when BGM library is empty.
    try:
        from ...domains.audio.beat_sync_service import get_beat_sync_service as _get_bs
        _music_out = output_path.with_name(f"music_{output_path.name}")
        _speech_segs = [
            {"start": w["start"], "end": w.get("end", w["start"] + 0.3)}
            for w in (words_with_confidence or [])[::3]
        ]
        # Director-driven BGM volume: average the bgm_volume_curve to get a
        # clip-unique baseline. Clips with strong payoff sections get louder
        # BGM; clips dominated by hook/CTA get quieter BGM.
        _bgm_base = float(os.environ.get("BGM_VOLUME", "0.40"))
        if _render_plan and _render_plan.bgm_volume_curve:
            _curve = _render_plan.bgm_volume_curve
            _curve_avg = sum(_curve) / len(_curve)
            # 0.55 is the "neutral" reference (build section default)
            _bgm_vol = round(_bgm_base * (_curve_avg / 0.55), 3)
            _bgm_vol = max(0.15, min(0.65, _bgm_vol))  # safety clamp
            logger.info(
                "  [Director] BGM volume = %.2f (curve avg=%.2f, base=%.2f)",
                _bgm_vol, _curve_avg, _bgm_base,
            )
        else:
            _bgm_vol = _bgm_base
        _bs_result = await _get_bs().mix_bgm_beat_synced(
            video_path=output_path,
            output_path=_music_out,
            speech_segments=_speech_segs,
            bgm_volume=_bgm_vol,
            preferred_category=preferred_music_category or (_clip_profile.bgm_category if _clip_profile else None),
            word_timings=words_with_confidence or None,
        )
        if _bs_result.get("success") and _music_out.exists():
            _music_out.replace(output_path)
            _bgm_name = (_bs_result.get("bgm_used") or "").split("/")[-1] or "?"
            logger.info(
                "  ✓ Beat-synced BGM: %.1f BPM / %s / %s",
                _bs_result.get("bpm", 0), _bs_result.get("category", "?"), _bgm_name
            )
        else:
            raise RuntimeError("beat_sync returned no output — using niche fallback")
    except Exception as _music_e:
        logger.debug(f"  BeatSync BGM skipped ({_music_e}), trying niche fallback")
        try:
            from ...video_processing.audio import get_background_music_for_niche, mix_background_music as _mix_bg
            from ...config import get_config as _get_cfg
            _cfg = _get_cfg()
            _music_path = get_background_music_for_niche(segment.get("theme") or "general", _cfg)
            if _music_path:
                _music_tmp = output_path.with_name(f"music_fb_{output_path.name}")
                if _mix_bg(output_path, _music_tmp, music_volume=0.35, music_path=_music_path, word_timings=words_with_confidence or None):  # Aumentado de 0.22
                    if _music_tmp.exists():
                        _music_tmp.replace(output_path)
                        logger.info(f"  ✓ Background music (niche fallback): {_music_path.name}")
        except Exception as _fb_music_e:
            logger.warning(f"  All music paths skipped: {_fb_music_e}")

    # Step 4.10b: Audio ducking
    try:
        output_path = await _polish.apply_audio_ducking(output_path, words_with_confidence)
    except Exception as _duck_e:
        logger.warning(f"Audio ducking failed: {_duck_e}. Skipping.")

    # Step 4.11: Pexels B-Roll overlay (Feature A — await prefetch task)
    try:
        output_path = await _polish.apply_pexels_broll(
            output_path, segment, _broll_prefetch_task,
            broll_already_applied=_get_cfg_broll().broll_enabled,
        )
    except Exception as _pexels_e:
        logger.warning(f"Pexels B-Roll overlay failed: {_pexels_e}. Skipping.")

    logger.info(f"Created clip {clip_index + 1}: {duration:.1f}s")

    # ClipValidator: post-render A/V sync + quality check
    try:
        await _polish.validate_clip_output(output_path, duration, words_with_confidence)
    except Exception as _val_e:
        logger.warning(f"Clip validation failed: {_val_e}. Skipping.")

    # Phase 3.5: Hook slow-motion (opt-in)
    try:
        _polish.apply_hook_slowmo(output_path, segment.get("virality_score", 0), clip_index)
    except Exception as _slowmo_e:
        logger.warning(f"Hook slow-motion failed: {_slowmo_e}. Skipping.")

    # ── V4 Elite: Visual scoring + Scene rhythm ──────────────────────
    text_virality = segment.get("virality_score", 0)
    final_virality = text_virality
    vision_data: dict = {}
    rhythm_data: dict = {}

    # Scene rhythm analysis (PySceneDetect)
    try:
        rhythm_data = _polish.analyze_scene_rhythm(output_path)
    except Exception as _rhythm_e:
        logger.warning(f"Scene rhythm analysis failed: {_rhythm_e}. Skipping.")


    # ViralityEngine: unified hook+pacing+emotion+phi3 score (replaces manual blend)
    try:
        from ...domains.virality.virality_engine import get_virality_engine
        _ve = get_virality_engine()
        _ve_pred = await _ve.predict(
            transcript=segment.get("text", ""),
            words=words_with_confidence or [],
            audio_features=audio_features or {},
            timeline_events=segment.get("timeline_events") or [],
        )
        final_virality = _ve_pred.score
        text_virality = _ve_pred.score
        if _ve_pred.improvements:
            logger.info(f"  ✓ ViralityEngine score={_ve_pred.score} improvements={_ve_pred.improvements[:2]}")
    except Exception as _ve_e:
        logger.debug(f"  ViralityEngine skipped: {_ve_e}")

    # Visual scoring via Ollama + Qwen3-VL (GPU optional, graceful fallback)
    try:
        from ...config import get_config
        cfg = get_config()
        if getattr(cfg, "vision_analysis_enabled", True):
            from ...domains.ai.vision_service import analyze_clip_visually, blend_with_text_score
            vision_score = await analyze_clip_visually(
                output_path,
                transcript=segment.get("text", ""),
                n_frames=8,
            )
            final_virality = blend_with_text_score(text_virality, vision_score)
            vision_data = {
                "visual_hook": vision_score.visual_hook,
                "facial_energy": vision_score.facial_energy,
                "visual_virality": vision_score.visual_virality,
                "vision_model": vision_score.model_used,
                "vision_recommendations": vision_score.recommendations,
                # Phase 2.4: scene intelligence
                "scene_context": vision_score.scene_context,
                "boring_frames": vision_score.boring_frames,
                "broll_keywords": vision_score.broll_keywords,
            }
            if vision_score.boring_frames:
                logger.info(
                    f"  ↳ Boring frames detected: {vision_score.boring_frames} "
                    f"→ B-roll injection candidates"
                )
            if vision_score.broll_keywords:
                logger.info(
                    f"  ↳ B-roll keywords: {vision_score.broll_keywords}"
                )
    except Exception as e:
        logger.debug(f"Vision scoring skipped: {e}")

    # Thumbnail: Qwen3-VL quality scoring → pick best among 5 candidate frames
    thumbnail_filename = None
    try:
        from ...config import get_config
        cfg = get_config()
        if getattr(cfg, "vision_analysis_enabled", True):
            from ...domains.ai.vision_service import score_thumbnail_frame
            from ...utils.scene_analysis import extract_representative_frames
            import tempfile, shutil

            # Extract 5 candidate frames
            candidates = extract_representative_frames(output_path, n_frames=5)
            if candidates:
                scored = []
                for fp in candidates:
                    result = await score_thumbnail_frame(fp)
                    scored.append((result.get("score", 0), fp))
                scored.sort(key=lambda x: x[0], reverse=True)
                best_score, best_frame = scored[0]
                thumb_path = output_path.with_suffix(".jpg")
                shutil.copy2(str(best_frame), str(thumb_path))
                thumbnail_filename = thumb_path.name
                logger.info(
                    f"  ✓ Qwen3-VL thumbnail selected (score={best_score}): "
                    f"{thumbnail_filename}"
                )
                for _, fp in candidates:
                    try:
                        fp.unlink(missing_ok=True)
                    except Exception:
                        pass

        if not thumbnail_filename:
            raise RuntimeError("Vision thumbnail skipped — fallback")
    except Exception:
        # Fallback: sharpness-based smart thumbnail
        try:
            thumb_path = str(output_path.with_suffix(".jpg"))
            result_thumb = await select_best_thumbnail(str(output_path), thumb_path)
            if result_thumb and Path(result_thumb).exists():
                thumbnail_filename = Path(result_thumb).name
                logger.info(f"  ✓ Smart thumbnail selected: {thumbnail_filename}")
            else:
                thumbnail_path = output_path.with_suffix(".jpg")
                if generate_clip_thumbnail(output_path, thumbnail_path, seek_seconds=1.0):
                    thumbnail_filename = thumbnail_path.name
        except Exception as e:
            logger.debug(f"Thumbnail generation failed: {e}")

    # AI Thumbnail variants — generate viral-optimized thumbnail alternatives
    if os.environ.get("AI_THUMBNAIL_ENABLED", "true").lower() == "true":
        try:
            from ...domains.ai.ai_thumbnail_service import AIThumbnailService, ThumbnailStyle
            _thumb_svc = AIThumbnailService(output_dir=output_path.parent)
            _thumb_result = await _thumb_svc.generate_thumbnail(
                video_path=output_path,
                style=ThumbnailStyle.FACE_FOCUS,
                add_text=bool(segment and segment.get("text")),
                text_content=segment.get("text", "")[:60] if segment else "",
            )
            if _thumb_result and _thumb_result.output_path.exists():
                thumbnail_filename = _thumb_result.output_path.name
                logger.info(
                    f"  ✓ AI Thumbnail generated (viral_potential={_thumb_result.viral_potential:.2f}): "
                    f"{thumbnail_filename}"
                )
        except Exception as _aith_e:
            logger.debug(f"  AI Thumbnail skipped: {_aith_e}")

    # Viral metadata: LLM-generated hashtags + SEO title
    try:
        viral_meta = await _polish.generate_viral_metadata_safe(segment, target_platform)
    except Exception as _meta_e:
        logger.warning(f"Viral metadata generation failed: {_meta_e}. Skipping.")
        viral_meta = {}

    # Phase 8.3: LSTM/CNN engagement prediction (drop-off curve)
    try:
        engagement_data = await _polish.predict_engagement(
            words_with_confidence or [], audio_features or {}, duration,
        )
    except Exception as _eng_e:
        logger.warning(f"Engagement prediction failed: {_eng_e}. Skipping.")
        engagement_data = {}


    # ── Recommendation Engine — personalized suggestions per user ─────
    _recommendations: list = []
    try:
        from ...domains.virality.recommendation_engine import get_recommendation_engine
        _rec_engine = get_recommendation_engine()
        _user_id_rec = segment.get("user_id", "") or ""
        if _user_id_rec:
            _rec_engine.track_user_action(
                user_id=_user_id_rec,
                action="clip_generated",
                metadata={
                    "platform": target_platform,
                    "duration": duration,
                    "virality_score": final_virality,
                    "content_category": getattr(_clip_profile, "content_category", "general") if _clip_profile else "general",
                }
            )
            _recs = _rec_engine.get_recommendations(
                user_id=_user_id_rec,
                context={"platform": target_platform, "virality_score": final_virality}
            )
            _recommendations = [
                {"type": r.type, "title": r.title, "action": r.action, "confidence": r.confidence}
                for r in _recs[:3]
            ]
            if _recommendations:
                logger.info(f"  ✓ Recommendations: {[r['title'] for r in _recommendations]}")
    except Exception as _rec_e:
        logger.debug(f"  Recommendation engine skipped: {_rec_e}")

    # ── Social Publisher — auto-publish si auto_publish_enabled ────────
    _publish_results: list = []
    _auto_publish = os.environ.get("AUTO_PUBLISH_ENABLED", "false").lower() == "true"
    if _auto_publish and segment.get("auto_publish_platforms"):
        try:
            from ...domains.publishing.social_publisher import publish_to_all, PublishRequest, Platform as SocialPlatform
            _platforms = segment.get("auto_publish_platforms", [target_platform])
            _caption = viral_meta.get("description") or segment.get("text", "")[:200]
            _hashtags = viral_meta.get("hashtags", [])
            _pub_results = await publish_to_all(
                video_path=str(output_path),
                caption=_caption,
                hashtags=_hashtags,
                platforms=_platforms,
            )
            _publish_results = [
                {"platform": r.platform, "status": r.status, "post_url": r.post_url, "error": r.error}
                for r in _pub_results
            ]
            logger.info(f"  ✓ Auto-published to: {[r['platform'] for r in _publish_results if r['status'] == 'published']}")
        except Exception as _pub_e:
            logger.debug(f"  Auto-publish skipped: {_pub_e}")
    # ── Quality Validator ─────────────────────────────────────────────
    try:
        _quality_report = _polish.validate_quality(output_path, duration, final_virality)
    except Exception as _qual_e:
        logger.warning(f"Quality validation failed: {_qual_e}. Skipping.")
        _quality_report = {}

    # ── Audio Recommendation ──────────────────────────────────────────
    try:
        _audio_recs = await _polish.recommend_audio(output_path)
    except Exception as _aud_e:
        logger.warning(f"Audio recommendation failed: {_aud_e}. Skipping.")
        _audio_recs = {}


    # ── Variant Generator — generar variante A/B automática ────────────
    _variants: list = []
    if os.environ.get("AB_VARIANTS_ENABLED", "false").lower() == "true":
        try:
            from .variant_generator import generate_clip_variants
            _var_results = await generate_clip_variants(
                clip_path=output_path,
                words=words_with_confidence or [],
                primary_caption_style=getattr(_clip_profile, "caption_style", "tiktok") if _clip_profile else "tiktok",
                platform=target_platform,
            )
            if _var_results:
                _variants = [str(v) for v in _var_results if v]
                logger.info(f"  ✓ {len(_variants)} A/B variant(s) generated")
        except Exception as _var_e:
            logger.debug(f"  Variant generator skipped: {_var_e}")

    # ── Clip Health Service ───────────────────────────────────────────
    try:
        _clip_health = _polish.generate_clip_health_report(
            clip_index, final_virality, segment, duration, target_platform, viral_meta,
        )
    except Exception as _health_e:
        logger.warning(f"Clip health report failed: {_health_e}. Skipping.")
        _clip_health = {}
    # ─────────────────────────────────────────────────────────────────

    # LTXV Intro (opt-in via LTXV_INTRO_ENABLED=true)
    try:
        output_path = await _polish.maybe_prepend_intro(output_path, segment, final_virality)
    except Exception as _intro_e:
        logger.warning(f"LTXV intro failed: {_intro_e}. Skipping.")


    # Cancel B-roll prefetch if still running (must be before return)
    if _broll_prefetch_task is not None and not _broll_prefetch_task.done():
        _broll_prefetch_task.cancel()

    return {
        "clip_id": clip_index + 1,
        "filename": output_path.name,
        "path": str(output_path),
        "start_time": segment["start_time"],
        "end_time": segment["end_time"],
        "duration": duration,
        "text": segment.get("text", ""),
        "relevance_score": segment.get("relevance_score", 0.0),
        "reasoning": segment.get("reasoning", ""),
        "virality_score": final_virality,  # blended text+visual
        "hook_score": segment.get("hook_score", 0),
        "engagement_score": segment.get("engagement_score", 0),
        "value_score": segment.get("value_score", 0),
        "shareability_score": segment.get("shareability_score", 0),
        "hook_type": segment.get("hook_type"),
        "social_title": segment.get("suggested_title"),
        "suggested_hashtags": viral_meta.get("hashtags") or segment.get("suggested_hashtags", []),
        "seo_title":          viral_meta.get("title") or segment.get("suggested_title", ""),
        "seo_description":    viral_meta.get("description", ""),
        "face_detected": segment.get("face_detected"),
        "translated_text": segment.get("translated_text"),
        "thumbnail_filename": thumbnail_filename,
        # V4 extras
        "rhythm_score": rhythm_data.get("rhythm_score"),
        "edit_pace": rhythm_data.get("edit_pace"),
        "scene_count": rhythm_data.get("scene_count"),
        "loop_potential": rhythm_data.get("can_loop", False),
        **vision_data,
        # Phase 8.3: engagement prediction
        **engagement_data,
        # Phase 9: Creative Engine — passed to creative_pipeline.enhance()
        "words": words_with_confidence,
        "audio_features": audio_features,
        # Recommendation & publishing
        "recommendations": _recommendations,
        "publish_results": _publish_results,
        # Quality, health & variants
        "quality_report": _quality_report,
        "clip_health": _clip_health,
        "audio_recommendations": _audio_recs,
        "ab_variants": _variants,
        "caption_system_used": _caption_system_used,
    }
    # (Prefetch cancellation moved before return above)



