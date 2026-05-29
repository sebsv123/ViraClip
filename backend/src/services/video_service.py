"""
Video service - handles video processing business logic.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Awaitable, cast, Tuple
from datetime import datetime
from dataclasses import asdict
import asyncio
import logging
import json
import subprocess
import os
import tempfile

logger = logging.getLogger(__name__)

from ..utils.async_helpers import run_in_thread

VIRACLIP_PREMIUM_EDITING_DEFAULT = True
PREMIUM_LAYERS_REQUESTED = [
    "retention_plan",
    "premium_transitions",
    "visual_effects",
    "music",
    "sfx_design",
    "frame_rhythm",
    "broll_transitions",
    "caption_visual_support",
    "retention_quality_gate",
]


def premium_runtime_contract(*, beta_clean: bool) -> Dict[str, Any]:
    enabled = bool(beta_clean and VIRACLIP_PREMIUM_EDITING_DEFAULT)
    return {
        "premium_runtime_enabled": enabled,
        "premium_layers_requested": list(PREMIUM_LAYERS_REQUESTED) if enabled else [],
        "retention": enabled,
        "transitions": enabled,
        "sfx": enabled,
        "music": enabled,
        "vfx": enabled,
        "frame_rhythm": enabled,
    }


def _log_premium_pipeline_step(step: str, input_path: Path, output_path: Path) -> None:
    logger.info("[premium-pipeline] step=%s input=%s output=%s", step, input_path, output_path)


def verify_final_filename_contract(
    final_path: Path,
    *,
    music: Optional[Dict[str, Any]] = None,
    sfx: Optional[Dict[str, Any]] = None,
    transitions: Optional[Dict[str, Any]] = None,
    visual_effects: Optional[Dict[str, Any]] = None,
    broll_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    name = final_path.name
    broll_count = len(broll_events or [])
    broll_final_verified = any(
        bool((item or {}).get("broll_final_verified"))
        or bool((item or {}).get("broll_transition_applied"))
        or bool((item or {}).get("broll_ken_burns_applied"))
        or bool((item or {}).get("asset_path"))
        or bool((item or {}).get("asset_url"))
        for item in (broll_events or [])
    )
    broll_actual = bool(broll_count > 0 and broll_final_verified and ("broll_" in name or broll_count > 0))
    checks = {
        "music": bool((music or {}).get("music_applied") and "music_" in name),
        "sfx": bool((sfx or {}).get("sfx_applied") and "sfx_" in name),
        "trans": bool((transitions or {}).get("transitions_applied") and "trans_" in name),
        "vfx": bool((visual_effects or {}).get("visual_effects_applied") and "vfx_" in name),
        "broll": broll_actual,
    }
    warnings: List[str] = []
    if (music or {}).get("music_applied") != ("music_" in name):
        warnings.append("music_marker_missing_or_false_positive")
    if (sfx or {}).get("sfx_applied") != ("sfx_" in name):
        warnings.append("sfx_marker_missing_or_false_positive")
    if (transitions or {}).get("transitions_applied") != ("trans_" in name):
        warnings.append("trans_marker_missing_or_false_positive")
    if (visual_effects or {}).get("visual_effects_applied") != ("vfx_" in name):
        warnings.append("vfx_marker_missing_or_false_positive")
    if "broll_" in name and not broll_actual:
        warnings.append("broll_marker_false_positive")
    elif broll_count > 0 and not broll_actual:
        warnings.append("broll_planned_not_final_verified")
    logger.info(
        "[final-contract] music=%s sfx=%s trans=%s vfx=%s broll=%s path=%s",
        str(checks["music"]).lower(),
        str(checks["sfx"]).lower(),
        str(checks["trans"]).lower(),
        str(checks["vfx"]).lower(),
        str(checks["broll"]).lower(),
        final_path,
    )
    for warning in warnings:
        logger.info("[final-contract] warning=%s", warning)
    return {
        "final_contract_ok": not warnings,
        "final_contract": checks,
        "final_contract_warnings": warnings,
    }


def _get_ffmpeg_exe() -> str:
    """Return ffmpeg binary path (imageio_ffmpeg if not in system PATH)."""
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _escape_drawtext_text(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", "\\n")
    )


def _wrap_hook_overlay_text(text: str, max_words_per_line: int = 5) -> str:
    words = (text or "").strip().split()
    if len(words) <= max_words_per_line:
        return " ".join(words)
    midpoint = min(max_words_per_line, max(3, (len(words) + 1) // 2))
    return " ".join(words[:midpoint]) + "\n" + " ".join(words[midpoint:])


def _apply_hook_headline_overlay(video_path: Path, output_path: Path, overlay: Dict[str, Any]) -> Dict[str, Any]:
    text = _wrap_hook_overlay_text(str(overlay.get("text") or ""), 5)
    if not text:
        logger.info("[hook-overlay] skipped reason=empty_text")
        return {"rendered": False, "output_path": str(video_path), "warnings": ["empty_text"]}
    try:
        start = max(0.25, min(0.45, float(overlay.get("start_s", 0.35) or 0.35)))
        duration = max(1.6, min(2.2, float(overlay.get("duration_s", 1.8) or 1.8)))
    except (TypeError, ValueError):
        start, duration = 0.35, 1.8
    end = min(2.7, start + duration)
    safe_text = _escape_drawtext_text(text)
    enable = f"between(t\\,{start:.3f}\\,{end:.3f})"
    vf = (
        f"drawtext=text='{safe_text}':"
        "x=(w-text_w)/2:y=250:"
        "fontsize=56:line_spacing=10:"
        "fontcolor=white@0.96:"
        "box=1:boxcolor=#10243fcc:boxborderw=28:"
        f"enable='{enable}',"
        "drawbox=x=90:y=250:w=8:h=132:color=#f97316@0.82:t=fill:"
        f"enable='{enable}'"
    )
    cmd = [
        _get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            logger.info("[hook-overlay] rendered=true text=%s start=%.2f dur=%.2f", overlay.get("text"), start, end - start)
            return {
                "rendered": True,
                "output_path": str(output_path),
                "text": overlay.get("text"),
                "start_s": round(start, 2),
                "duration_s": round(end - start, 2),
                "warnings": [],
                "method": "ffmpeg_drawtext",
            }
        reason = (result.stderr or "ffmpeg_failed")[-240:]
        logger.warning("[hook-overlay] failed fallback=input reason=%s", reason)
        return {"rendered": False, "output_path": str(video_path), "warnings": ["hook_overlay_ffmpeg_failed"], "reason": reason}
    except Exception as exc:
        logger.warning("[hook-overlay] failed fallback=input reason=%s", exc)
        return {"rendered": False, "output_path": str(video_path), "warnings": [str(exc)], "reason": str(exc)}


def _apply_hook_kickframe(video_path: Path, output_path: Path, event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        start = max(0.16, float(event.get("start_s", 0.45) or 0.45))
        duration = max(0.16, min(0.33, float(event.get("duration_s", 0.22) or 0.22)))
        scale = max(1.03, min(1.05, float(event.get("scale", 1.04) or 1.04)))
    except (TypeError, ValueError):
        start, duration, scale = 0.45, 0.22, 1.04
    end = start + duration
    scale_expr = f"if(between(t,{start:.3f},{end:.3f}),{scale:.3f},1)"
    vf = (
        f"scale=w='ceil(1080*({scale_expr})/2)*2':"
        f"h='ceil(1920*({scale_expr})/2)*2':eval=frame,"
        "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
        f"eq=brightness='if(between(t,{start:.3f},{end:.3f}),0.018,0)':"
        f"contrast='if(between(t,{start:.3f},{end:.3f}),1.025,1)'"
    )
    cmd = [
        _get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            logger.info("[hook-kickframe] applied=true start=%.2f dur=%.2f scale=%.3f", start, duration, scale)
            return {"rendered": True, "output_path": str(output_path), "event": {**event, "start_s": round(start, 2), "duration_s": round(duration, 2), "scale": round(scale, 3)}, "warnings": []}
        reason = (result.stderr or "ffmpeg_failed")[-240:]
        logger.warning("[hook-kickframe] skipped reason=%s", reason)
        return {"rendered": False, "output_path": str(video_path), "warnings": ["hook_kickframe_ffmpeg_failed"], "reason": reason}
    except Exception as exc:
        logger.warning("[hook-kickframe] skipped reason=%s", exc)
        return {"rendered": False, "output_path": str(video_path), "warnings": [str(exc)], "reason": str(exc)}


from ..youtube_utils import (
    async_download_youtube_video,
    async_get_youtube_video_info,
    async_get_youtube_video_title,
    get_youtube_video_id,
)
from ..video_processing import (
    get_video_transcript,
    create_optimized_clip,
    create_clips_with_transitions,
    generate_clip_thumbnail,
)
from ..video_processing.utils import parse_timestamp_to_seconds
from ..ai import get_most_relevant_parts_by_transcript
from ..config import Config
from ..video_processing.hook_analysis import analyze_segment_virality, compare_hook_strength
from ..video_processing.niche_analysis import analyze_content_niche, optimize_for_platform
from ..video_processing.virality_tuner import get_tuner
from .cache_manager import get_cache_manager, cache_transcript_smart, get_cached_transcript_smart
from .metrics_service import get_metrics_collector, timed_stage
from .error_handler import with_retry, execute_with_recovery, get_circuit_breaker
from .concurrency_optimizer import parallel_map, run_with_timeout, ParallelBatchProcessor
from .llm_service import LLMService
from .broll_service import BrollService
from .elite_ai_service import EliteAIService
from .vfx_service import VFXService
from .social_distribution_service import SocialDistributionService
from .phi3_virality_service import Phi3ViralityService, get_phi3_service
# Guarded import for ConfidenceSubtitleGenerator
ConfidenceSubtitleGenerator = None  # Initialize to None before try block
_confidence_subtitle_available = False
try:
    from .confidence_subtitle_service import ConfidenceSubtitleGenerator
    _confidence_subtitle_available = True
except (ImportError, Exception):
    pass  # ConfidenceSubtitleGenerator remains None

# ── WhisperX Singleton for word-level transcription ───────────────────────────
_whisperx_model = None
_whisperx_align_cache: Dict[str, Any] = {}  # {lang: (model, metadata)}
_whisperx_available = False


def resolve_whisper_device() -> Tuple[str, str]:
    requested = os.environ.get("WHISPER_DEVICE", "cpu").strip().lower()
    torch_cuda_enabled = os.environ.get("VIRACLIP_ENABLE_TORCH_CUDA", "false").lower() in (
        "1", "true", "yes"
    )

    if requested == "cuda":
        if not torch_cuda_enabled:
            logger.info(
                "[WhisperX] CUDA requested but disabled by "
                "VIRACLIP_ENABLE_TORCH_CUDA=false; using CPU"
            )
            return "cpu", "int8"
        try:
            from ..utils.gpu_utils import is_torch_cuda_available
            if is_torch_cuda_available():
                return "cuda", "float16"
            logger.info("[WhisperX] CUDA requested but runtime unavailable; using CPU")
        except Exception as exc:
            logger.info("[WhisperX] CUDA probe failed (%s); using CPU", exc)

    return "cpu", "int8"


try:
    import whisperx
    _WX_DEVICE, _WX_COMPUTE = resolve_whisper_device()
    _whisperx_available = True
    _WX_MODEL = "large-v3"
    _WX_BATCH = 24 if _WX_DEVICE == "cuda" else 8
    logger.info(f"[WhisperX] Ready — device={_WX_DEVICE} compute={_WX_COMPUTE}")
except ImportError:
    logger.warning("[WhisperX] Not installed — using standard Whisper fallback")

from .semantic_broll_service import SemanticBrollService
from .sound_design_service import SoundDesignService, add_viral_sound_effects
from .hook_visual_service import HookVisualService
from .face_detection_service import FaceDetectionService
from ..video_processing.export_profiles import ExportService, Platform, get_ffmpeg_export_command
from ..video_processing.audio_analysis import analyze_audio_virality, extract_audio_from_video
from ..video_processing.narrative_cut_engine import NarrativeCutEngine, detect_hesitations
from ..video_processing.nonlinear_edit_engine import NonLinearEditingEngine
from ..video_processing.silence_removal import (
    remove_silences, speed_ramp_silences,
    SILENCE_THRESHOLD, SILENCE_MODE,
    build_keep_intervals, MIN_SILENCE_SAVINGS,
)
from ..video_processing.audio import denoise_audio, apply_voice_enhancement
from .broll_compositor import probe_duration
from ..video_processing.editing_pipeline import EditingPipeline
from ..video_processing.thumbnail_selector import select_best_thumbnail
from .viral_metadata_service import generate_viral_metadata
from ..comfyui_bridge import ComfyUIBridge, COMFYUI_ENABLED
from types import SimpleNamespace

# Global config instance for static methods
_config = None

def get_service_config():
    global _config
    if _config is None:
        from ..config import get_config
        _config = get_config()
    return _config

UPLOAD_URL_PREFIX = "upload://"


# ── WhisperX Transcription Functions ──────────────────────────────────────────

async def transcribe_with_whisperx(audio_path: str, language: str = None) -> dict:
    """
    Transcripción con forced alignment word-level usando WhisperX.
    Cada word tiene: {'word', 'start', 'end', 'score'}
    score = confianza del modelo de alineación (0.0-1.0)
    Un score alto indica pronunciación clara/enfática.
    """
    global _whisperx_model, _whisperx_align_cache

    if not _whisperx_available:
        return await _fallback_transcribe(audio_path, language)

    try:
        import whisperx

        if _whisperx_model is None:
            logger.info("[WhisperX] Loading large-v3 (~3GB, primera vez 3-5min)...")
            os.makedirs("/app/models", exist_ok=True)
            _whisperx_model = whisperx.load_model(
                _WX_MODEL, _WX_DEVICE,
                compute_type=_WX_COMPUTE,
                download_root="/app/models",
                language=language
            )

        audio = whisperx.load_audio(audio_path)
        result = _whisperx_model.transcribe(audio, batch_size=_WX_BATCH, language=language)
        lang = result.get("language", language or "es")

        if lang not in _whisperx_align_cache:
            os.makedirs("/app/models/alignment", exist_ok=True)
            align_model, metadata = whisperx.load_align_model(
                language_code=lang,
                device=_WX_DEVICE,
                model_dir="/app/models/alignment"
            )
            _whisperx_align_cache[lang] = (align_model, metadata)

        align_model, metadata = _whisperx_align_cache[lang]
        result = whisperx.align(
            result["segments"], align_model, metadata,
            audio, _WX_DEVICE, return_char_alignments=False
        )
        result["language"] = lang

        n_words = sum(len(s.get("words", [])) for s in result["segments"])
        logger.info(f"[WhisperX] ✅ {n_words} words aligned — lang={lang}")
        return result

    except Exception as e:
        logger.error(f"[WhisperX] Error: {e} — fallback activado")
        return await _fallback_transcribe(audio_path, language)


async def _fallback_transcribe(audio_path: str, language: str = None) -> dict:
    """Fallback to standard faster-whisper transcription."""
    try:
        from ..video_processing import get_video_transcript
        transcript_text = await get_video_transcript(Path(audio_path), language or "es")
        # Return compatible format without word-level alignment
        return {
            "segments": [{"text": transcript_text, "start": 0.0, "end": 0.0, "words": []}],
            "language": language or "es",
            "text": transcript_text
        }
    except Exception as e:
        logger.error(f"[WhisperX] Fallback transcription failed: {e}")
        return {"segments": [], "language": language or "es", "text": ""}


def burn_word_subtitles(
    video_path: str,
    segments: list,
    output_path: str,
    language: str = "es",
    video_width: int = 1080,
    video_height: int = 1920
) -> str:
    """
    Genera ASS con énfasis basado en word.score (WhisperX)
    y lo quema con FFmpeg. Usa NVENC para encoding acelerado.
    """
    import tempfile

    try:
        from .confidence_subtitle_service import ConfidenceSubtitleGenerator as _LocalConfidenceSubtitleGenerator
        gen = _LocalConfidenceSubtitleGenerator()

        fd, ass_path = tempfile.mkstemp(suffix=".ass")
        os.close(fd)

        result = gen.generate_from_segments(
            segments=segments,
            video_width=video_width,
            video_height=video_height,
            output_path=ass_path
        )

        if not result:
            logger.warning("[Subtitles] ASS vacío — saltando burn")
            return video_path

        ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"ass='{ass_escaped}'",
            "-c:v", "h264_nvenc",   # NVENC hardware encoding — Blackwell
            "-preset", "p4",        # balance calidad/velocidad NVENC
            "-rc", "constqp", "-qp", "18",  # calidad constante (equivale a CRF 18)
            "-c:a", "copy",
            output_path
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if proc.returncode != 0:
            # Fallback a software si NVENC falla
            logger.warning("[Subtitles] NVENC falló, reintentando con libx264")
            cmd[cmd.index("h264_nvenc")] = "libx264"
            cmd[cmd.index("-preset")] = "-preset"
            cmd[cmd.index("p4")] = "fast"
            cmd[cmd.index("-rc")] = "-crf"
            cmd[cmd.index("-qp")] = "17"
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if proc.returncode == 0:
            logger.info(f"[Subtitles] ✅ Burned: {output_path}")
            return output_path
        else:
            logger.error(f"[Subtitles] Burn fallido: {proc.stderr[-300:]}")
            return video_path

    except Exception as e:
        logger.error(f"[Subtitles] burn_word_subtitles error: {e}")
        return video_path

    finally:
        if 'ass_path' in locals() and os.path.exists(ass_path):
            os.remove(ass_path)


class VideoService:
    """Service for video processing operations."""

    @staticmethod
    def _get_file_duration(path: Path) -> Optional[float]:
        """Return video duration in seconds via ffmpeg, or None on failure."""
        import re as _re
        try:
            result = subprocess.run(
                [_get_ffmpeg_exe(), "-v", "error", "-i", str(path)],
                capture_output=True, text=True,
            )
            m = _re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            return None
        except Exception as e:
            logger.warning(f"[VIDEO_DURATION] Failed to get duration for {path}: {e}")
            return None

    @staticmethod
    def resolve_local_video_path(url: str) -> Path:
        """Resolve uploaded-video references without exposing server filesystem paths."""
        cfg = get_service_config()
        if url.startswith(UPLOAD_URL_PREFIX):
            filename = Path(url.removeprefix(UPLOAD_URL_PREFIX)).name
            # cfg.temp_dir already points to /app/temp/uploads (set via TEMP_DIR env var)
            return Path(cfg.temp_dir) / filename
        return Path(url)

    @staticmethod
    async def download_video(url: str, task_id: Optional[str] = None) -> Optional[Path]:
        """
        Download a YouTube video asynchronously.
        """
        logger.info(f"Starting video download: {url}")
        video_path = await async_download_youtube_video(url, 3, task_id)

        if not video_path:
            logger.error(f"Failed to download video: {url}")
            return None

        logger.info(f"Video downloaded successfully: {video_path}")
        return video_path

    @staticmethod
    async def get_video_title(url: str) -> str:
        """
        Get video title asynchronously.
        Returns a default title if retrieval fails.
        """
        try:
            title = await async_get_youtube_video_title(url)
            return title or "YouTube Video"
        except Exception as e:
            logger.warning(f"Failed to get video title: {e}")
            return "YouTube Video"

    @staticmethod
    async def _burn_subtitles_word_level(
        video_path: str,
        words: List[Dict[str, Any]],
        output_path: str,
        style: str = "viral"
    ) -> str:
        """
        Quema subtítulos estilo CapCut/TikTok con animación profesional:
        - 85px bold, shadow + outline grueso
        - Palabra activa en amarillo (o rojo si is_emphasis=True)
        - Animación pop-in: escala 80%→100% en 150ms via ASS \\t()
        - Máx 4 palabras por línea
        - Sin \\r resets (evita el bug libass con \\fscx + \\r)
        """
        import asyncio

        if not words:
            logger.warning("[ASS] No words provided — skipping subtitle burn")
            return output_path

        ass_path = str(Path(video_path).with_suffix("")) + "_subtitles.ass"

        _fonts_dir = Path(__file__).parent.parent.parent / "fonts"
        # Prefer THEBOLDFONT (viral/Hormozi style), fall back in order
        _font_candidates = [
            ("THEBOLDFONT",         "THEBOLDFONT.ttf"),
            ("BarlowCondensed-Bold", "BarlowCondensed-Bold.ttf"),
            ("TikTokSans",          "TikTokSans-Regular.ttf"),
        ]
        _fontname = "Arial"
        for _fn, _ff in _font_candidates:
            if (_fonts_dir / _ff).exists():
                _fontname = _fn
                break

        # ASS colour codes (BBGGRR inline format, no alpha byte)
        _YELLOW  = "&H00FFFF&"   # active word — yellow
        _ORANGE  = "&H0066FF&"   # impact word — orange
        _RED     = "&H0000FF&"   # emphasis word — red
        _WHITE   = "&HFFFFFF&"   # inactive words — white
        _OUTLINE = "&H00000000"  # black outline (AABBGGRR)
        _SHADOW  = "&HA0000000"  # semi-transparent black back box

        # Impact keywords → orange highlight (ES + EN)
        _IMPACT_WORDS = {
            "dinero", "money", "gratis", "free", "peligroso", "dangerous",
            "nuevo", "new", "secreto", "secret", "viral", "increible",
            "incredible", "importante", "important", "urgente", "urgent",
            "millones", "millions", "euros", "dolares", "dollars", "error",
            "hack", "truco", "trick", "boom", "clave", "key", "ahora", "now",
            "unico", "unique", "gratis", "lanzar", "launch", "exclusivo",
        }

        # pop-in bounce: 60%→115% in 100ms then settle to 100% by 200ms (MrBeast style)
        _POPIN = r"{\fscx60\fscy60\t(0,100,\fscx115\fscy115)\t(100,200,\fscx100\fscy100)}"

        ass_header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "PlayResX: 1080\n"
            "PlayResY: 1920\n"
            "Encoding: UTF-8\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            # Fontsize=105, Bold=1, Outline=8, Shadow=4, Alignment=2 (bottom-center)
            f"Style: Viral,{_fontname},105,&H0000FFFF,&H00FFFFFF,{_OUTLINE},"
            f"{_SHADOW},1,0,0,0,100,100,0,0,1,8,4,2,30,30,400,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        WORDS_PER_LINE = 3    # max words per group
        MAX_GAP_S      = 0.35  # REDUCIDO: romper grupo en pausas más cortas (antes 0.6)
        MAX_SPAN_S     = 1.8   # REDUCIDO: grupos más cortos = mejor sync (antes 2.2)
        events: List[str] = []

        # Build groups by TIME PROXIMITY, not word count.
        # This prevents a group from spanning a long pause, which causes perceived desync.
        all_valid = [w for w in words if (w.get("word") or "").strip()]
        groups: List[List[Dict]] = []
        current: List[Dict] = []
        _all_valid_list = list(all_valid)
        for _wi, w in enumerate(_all_valid_list):
            if not current:
                current.append(w)
                continue
            gap  = float(w.get("start", 0)) - float(current[-1].get("end", 0))
            span = float(w.get("end", 0))   - float(current[0].get("start", 0))
            # Detectar inicio de oración: próxima palabra empieza con mayúscula y hay pausa
            _word_text = (w.get("word") or "").strip()
            _is_sentence_start = bool(_word_text) and _word_text[0].isupper()
            _has_natural_pause = gap > 0.2  # 200ms = pausa natural de oración
            if (len(current) >= WORDS_PER_LINE
                    or gap > MAX_GAP_S
                    or span > MAX_SPAN_S
                    or (_is_sentence_start and _has_natural_pause)):
                groups.append(current)
                current = [w]
            else:
                current.append(w)
        if current:
            groups.append(current)

        for group in groups:
            # Filter out empty word entries
            valid = [w for w in group if (w.get("word") or "").strip()]
            if not valid:
                continue

            # ONE event per group — spans from first word start to last word end.
            # This eliminates per-word pop-in chaos: the group appears once with a
            # single animation and stays on screen until all words have been spoken.
            g_start = float(valid[0].get("start", 0.0))
            g_end   = float(valid[-1].get("end", g_start + 0.4 * len(valid)))
            if g_end <= g_start:
                g_end = g_start + 0.4 * len(valid)
            # Compensacion de latencia de renderizado ASS (-33ms)
            # FFmpeg introduce ~33ms de delay al renderizar el filtro 'ass'
            _ASS_RENDER_OFFSET = -0.033
            g_start = max(0.0, g_start + _ASS_RENDER_OFFSET)
            g_end   = max(g_start + 0.1, g_end + _ASS_RENDER_OFFSET)

            # Color: any emphasis word → red highlight, impact keyword → orange, else yellow
            parts: List[str] = []
            for w in valid:
                t = (w.get("word") or "").strip().upper()
                if not t:
                    continue
                if bool(w.get("is_emphasis", False)):
                    parts.append(f"{{\\c{_RED}}}{t}")
                elif t.lower() in _IMPACT_WORDS:
                    parts.append(f"{{\\c{_ORANGE}}}{t}")
                else:
                    parts.append(f"{{\\c{_YELLOW}}}{t}")

            if parts:
                line_text = _POPIN + " ".join(parts) + "{\\r}"
                events.append(
                    f"Dialogue: 0,"
                    f"{VideoService._seconds_to_ass_time(g_start)},"
                    f"{VideoService._seconds_to_ass_time(g_end)},"
                    f"Viral,,0,0,0,,{line_text}"
                )

        if not events:
            logger.warning("[ASS] 0 Dialogue events produced — skipping subtitle burn")
            return output_path

        ass_content = ass_header + "\n".join(events) + "\n"
        with open(ass_path, "w", encoding="utf-8-sig") as f:
            f.write(ass_content)

        logger.info(
            f"[ASS] {len(events)} group events written ({len(all_valid)} words, "
            f"max {WORDS_PER_LINE}/group, gap<{MAX_GAP_S}s, span<{MAX_SPAN_S}s)"
        )

        cmd = [
            _get_ffmpeg_exe(), "-y", "-i", video_path,
            "-vf", f"ass={ass_path}:fontsdir=/app/fonts",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _stdout, _stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(
                f"[ASS] FFmpeg subtitle burn failed (exit {proc.returncode}): "
                f"{_stderr.decode()[:600]}"
            )
        else:
            logger.info(f"[ASS] ✅ Subtitles burned into {Path(output_path).name}")

        Path(ass_path).unlink(missing_ok=True)
        return output_path

    @staticmethod
    def _adjust_words_for_cuts(
        words: List[Dict[str, Any]],
        keep_intervals: List[Tuple[float, float]],
    ) -> List[Dict[str, Any]]:
        """
        Remap word start/end timestamps to the new timeline produced after
        silence/jump-cut removal.  Words that fall entirely inside a removed
        gap are dropped; words that straddle a gap boundary are clamped.
        """
        if not keep_intervals:
            return words

        # Pre-compute cumulative base offset for each kept interval
        cum: List[Tuple[float, float, float]] = []  # (interval_start, interval_end, new_base)
        base = 0.0
        for s, e in keep_intervals:
            cum.append((s, e, base))
            base += e - s

        def remap(t: float) -> float:
            """Map original time t into the post-cut timeline."""
            for s, e, b in cum:
                if t <= e:
                    return b + max(0.0, t - s)
            # Past the last interval — clamp to end
            s, e, b = cum[-1]
            return b + (e - s)

        adjusted: List[Dict[str, Any]] = []
        for word in words:
            w_start = float(word.get("start", 0))
            w_end   = float(word.get("end",   0))
            # Drop words entirely inside a removed gap
            in_kept = any(s <= w_start < e for s, e, _ in cum)
            if not in_kept:
                continue
            new_start = remap(w_start)
            new_end   = remap(w_end)
            if new_end > new_start:
                adjusted.append({**word, "start": new_start, "end": new_end})
        return adjusted

    @staticmethod
    async def _crop_to_vertical_9_16(
        video_path: str,
        output_path: str
    ) -> str:
        """Convierte video a 9:16 centrando horizontalmente (crop + pad)."""
        import subprocess
        import asyncio
        
        cmd = [
            _get_ffmpeg_exe(), "-y", "-i", video_path,
            "-vf", "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.wait()
        return output_path

    @staticmethod
    def _seconds_to_ass_time(seconds: float) -> str:
        """Convierte segundos a formato de tiempo ASS (H:MM:SS.cc)."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    async def generate_transcript(
        video_path: Path, processing_mode: str = "balanced"
    ) -> str:
        """
        Generate transcript from video using faster-whisper.
        Runs in thread pool to avoid blocking.
        """
        cfg = get_service_config()
        logger.info(f"Generating transcript for: {video_path}")
        speech_model = "best"
        if processing_mode == "fast":
            speech_model = cfg.fast_mode_transcript_model

        # FIX: get_video_transcript is async - call directly, not in thread
        transcript_text, transcript_data = await get_video_transcript(video_path, speech_model)
        transcript = cast(str, transcript_text)
        logger.info(f"Transcript generated: {len(transcript)} characters")
        return transcript

    @staticmethod
    async def analyze_transcript(transcript: str, video_duration: float = 0.0, include_broll: bool = False) -> Any:
        """
        Analyze transcript with AI to find relevant segments.
        
        Args:
            transcript: Video transcript text
            video_duration: Total video duration in seconds (0 if unknown)
            include_broll: Whether to include B-roll suggestions
        """
        logger.info(f"[AI ANALYSIS] Starting transcript analysis (duration={video_duration:.1f}s, transcript_length={len(transcript)} chars)")
        logger.info(f"[AI ANALYSIS] LLM model configured: {Config().llm}")
        
        try:
            relevant_parts = await get_most_relevant_parts_by_transcript(
                transcript, 
                include_broll=include_broll,
                video_duration=video_duration
            )
            
            segments_count = len(relevant_parts.most_relevant_segments)
            logger.info(
                f"[AI ANALYSIS] ✅ Complete: {segments_count} segments found"
            )
            
            if segments_count == 0:
                logger.error(
                    f"[AI ANALYSIS] ❌ CRITICAL: LLM returned 0 segments! "
                    f"This will cause 'No Clips Generated' error. "
                    f"Check: 1) LLM is running, 2) API key is valid, 3) Transcript quality"
                )
                logger.error(f"[AI ANALYSIS] Transcript preview (first 500 chars): {transcript[:500]}")
            else:
                # Log first segment details for debugging
                first_seg = relevant_parts.most_relevant_segments[0]
                if isinstance(first_seg, dict):
                    logger.info(f"[AI ANALYSIS] First segment: {first_seg.get('start_time')}-{first_seg.get('end_time')}, virality={first_seg.get('virality_score', 'N/A')}")
                else:
                    logger.info(f"[AI ANALYSIS] First segment: {first_seg.start_time}-{first_seg.end_time}, virality={getattr(first_seg.virality, 'total_score', 'N/A') if hasattr(first_seg, 'virality') else 'N/A'}")
            
            return relevant_parts
            
        except Exception as e:
            logger.error(f"[AI ANALYSIS] ❌ EXCEPTION during transcript analysis: {type(e).__name__}: {e}", exc_info=True)
            raise

    @staticmethod
    async def create_video_clips_parallel(
        video_path: Path,
        segments: List[Dict[str, Any]],
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        output_format: str = "vertical",
        add_subtitles: bool = True,
        task_id: str = "unknown",
        max_concurrent: int = 3,
        include_broll: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Create video clips in parallel using Concurrency Optimizer.
        
        Args:
            max_concurrent: Maximum number of concurrent clip rendering operations
        """
        cfg = get_service_config()
        logger.info(f"Creating {len(segments)} video clips in parallel (max_concurrent={max_concurrent})")
        clips_output_dir = Path(cfg.temp_dir) / "clips"
        clips_output_dir.mkdir(parents=True, exist_ok=True)

        # Use Concurrency Optimizer for parallel clip creation
        processor = ParallelBatchProcessor(max_concurrent=max_concurrent)
        
        async def render_single_clip(segment_with_idx: tuple) -> Optional[Dict[str, Any]]:
            idx, segment = segment_with_idx
            try:
                clip_info = await VideoService.create_single_clip(
                    video_path=video_path,
                    segment=segment,
                    clip_index=idx,
                    output_dir=clips_output_dir,
                    font_family=font_family,
                    font_size=font_size,
                    font_color=font_color,
                    caption_template=caption_template,
                    output_format=output_format,
                    add_subtitles=add_subtitles,
                    task_id=task_id,
                    include_broll=include_broll,
                )
                return clip_info
            except Exception as e:
                logger.error(f"Failed to render clip {idx + 1}: {e}")
                return None
        
        # Process clips in parallel
        segments_with_idx = list(enumerate(segments))
        clips_results = await processor.process_batch(
            segments_with_idx,
            render_single_clip,
            progress_callback=lambda completed, total: logger.info(f"Rendered {completed}/{total} clips")
        )
        
        # Filter out failed clips
        clips_info = [c for c in clips_results if c is not None]
        
        logger.info(f"Successfully created {len(clips_info)}/{len(segments)} clips")
        return cast(List[Dict[str, Any]], clips_info)

    @staticmethod
    async def create_video_clips(
        video_path: Path,
        segments: List[Dict[str, Any]],
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        output_format: str = "vertical",
        add_subtitles: bool = True,
        task_id: str = "unknown",
    ) -> List[Dict[str, Any]]:
        """
        Create standalone video clips from segments with optional subtitles.
        Runs in thread pool as video processing is CPU-intensive.
        """
        cfg = get_service_config()
        logger.info(f"Creating {len(segments)} video clips subtitles={add_subtitles}")
        clips_output_dir = Path(cfg.temp_dir) / "clips"
        clips_output_dir.mkdir(parents=True, exist_ok=True)

        clips_info = await run_in_thread(
            create_clips_with_transitions,
            video_path,
            segments,
            clips_output_dir,
            font_family,
            font_size,
            font_color,
            output_format,
            add_subtitles,
            task_id,
        )

        logger.info(f"Successfully created {len(clips_info)} clips")

        # Phase 3: Generative Viral Artifacts (VFX Hub)
        try:
            # Detect Infinite Loop opportunities (Vidrush 3.0 style)
            logger.info("🌀 V4 Elite: Running Vidrush Loop Detection across clips")
            vfx_hub = VFXService()
            # Explicitly type clips_info to avoid 'Sized' lint errors
            typed_clips: List[Dict[str, Any]] = cast(List[Dict[str, Any]], clips_info)
            for clip_info in typed_clips:
                try:
                    clip_path = Path(clip_info["path"])
                    
                    # 1. Automatic Loop Detection (Vidrush 3.0)
                    loops = vfx_hub.detect_viral_loops(clip_path)
                    if loops:
                        clip_info["is_loop"] = True
                        logger.info(f"✨ Perfect Loop detected for {clip_path.name}")

                    # 2. AI-Suggested Style Transfer (Seedance 2.0)
                    # We look up the elite_metadata for this segment to find 'style_transfer'
                    elite_meta = clip_info.get("elite_metadata", {})
                    vfx_cfg = elite_meta.get("vfx", {}) if elite_meta else {}
                    target_style = vfx_cfg.get("style_transfer")
                    
                    if target_style:
                        logger.info(f"🎨 V4 Elite: Applying AI-requested style '{target_style}'")
                        styled_path = await vfx_hub.apply_generative_style(
                            clip_path, style_references=[], output_format=target_style, task_id=task_id
                        )
                        if styled_path != clip_path:
                            clip_info["path"] = str(styled_path)
                            clip_info["is_styled"] = True
                            clip_info["style_name"] = target_style

                    # 3. Trend-Sync Hashtags (Phase 4)
                    try:
                        hashtags = await SocialDistributionService.get_viral_hashtags(
                            clip_info.get("transcript", ""), platform="tiktok"
                        )
                        clip_info["suggested_hashtags"] = hashtags
                        logger.info(f"🏷️ V4 Elite: Attached {len(hashtags)} trend-synced hashtags")
                    except Exception as tag_e:
                        logger.warning(f"Failed to generate hashtags for {clip_path.name}: {tag_e}")
                except Exception as inner_vfx_e:
                    logger.error(f"Failed VFX processing for clip {clip_info.get('id', 'unknown')}: {inner_vfx_e}")
        except Exception as vfx_e:
            logger.error(f"VFX Hub integration error: {vfx_e}")

        return cast(List[Dict[str, Any]], clips_info)

    @staticmethod
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
        include_broll: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Render a single clip in the thread pool and return clip_info dict, or None on failure."""
        # Feature A: launch Pexels B-Roll prefetch concurrently at the start of render
        _broll_prefetch_task = None
        try:
            from ..config import get_config as _get_cfg_fa
            _cfg_fa = _get_cfg_fa()
            if getattr(_cfg_fa, "broll_enabled", False) and getattr(_cfg_fa, "pexels_api_key", ""):
                from .pexels_service import prefetch_broll_for_clip as _pfetch
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
        logger.info(
            "[editorial-runtime] candidate_id=%s start=%.2f end=%.2f",
            segment.get("id") or segment.get("candidate_id") or clip_index + 1,
            start_seconds,
            end_seconds,
        )

        # ── FASE 2: Editorial boundary adjustment (complete idea) ──────────────
        # Before rendering, check if the segment boundaries can be improved to
        # capture a complete idea. This runs BEFORE any render step so the clip
        # captures a natural thought boundary.
        _editorial_boundary_adjusted = False
        _editorial_boundary_old_start = start_seconds
        _editorial_boundary_old_end = end_seconds
        _editorial_boundary_old_duration = duration
        _complete_idea_metadata: Dict[str, Any] = {}
        try:
            from .vpi_editorial_fluency_service import (
                score_complete_idea as _score_complete_idea,
                expand_to_nearest_complete_idea as _expand_to_nearest_complete_idea,
                _parse_transcript_lines as _parse_transcript_lines_ef,
            )
            _segment_text = segment.get("text", "")
            if _segment_text:
                _transcript_lines = _parse_transcript_lines_ef(_segment_text)
                _idea_result = _score_complete_idea(_segment_text)
                _idea_score = float((_idea_result or {}).get("complete_idea_score") or 0.0)
                _complete_idea_metadata = {
                    "complete_idea_score": _idea_score,
                    "has_opening": bool((_idea_result or {}).get("has_opening")),
                    "has_development": bool((_idea_result or {}).get("has_development")),
                    "has_closure": bool((_idea_result or {}).get("has_closure")),
                    "boundary_adjustment_reason": "already_complete" if _idea_score >= 0.75 else "incomplete_idea",
                }
                if _transcript_lines and _idea_score < 0.75:
                        _expansion = _expand_to_nearest_complete_idea(
                            start_seconds, end_seconds, _transcript_lines
                        )
                        _adjusted_start = _expansion.get("adjusted_start_s", start_seconds)
                        _adjusted_end = _expansion.get("adjusted_end_s", end_seconds)
                        if _adjusted_start != start_seconds or _adjusted_end != end_seconds:
                            _editorial_boundary_adjusted = True
                            _editorial_boundary_old_start = start_seconds
                            _editorial_boundary_old_end = end_seconds
                            start_seconds = _adjusted_start
                            end_seconds = _adjusted_end
                            duration = end_seconds - start_seconds
                            _complete_idea_metadata.update({
                                "complete_idea_score": float(_expansion.get("complete_idea_score", _idea_score) or _idea_score),
                                "has_opening": bool(_expansion.get("has_opening", _complete_idea_metadata["has_opening"])),
                                "has_development": bool(_expansion.get("has_development", _complete_idea_metadata["has_development"])),
                                "has_closure": bool(_expansion.get("has_closure", _complete_idea_metadata["has_closure"])),
                                "boundary_adjustment_reason": str(_expansion.get("reason") or _expansion.get("boundary_adjustment_reason") or "include_closure"),
                            })
                            logger.info(
                                "[complete-idea] boundary_applied=true "
                                "score=%.2f old_start=%.1f old_end=%.1f "
                                "new_start=%.1f new_end=%.1f "
                                "reason=%s",
                                float(_complete_idea_metadata.get("complete_idea_score") or _idea_score),
                                _editorial_boundary_old_start,
                                _editorial_boundary_old_end,
                                start_seconds,
                                end_seconds,
                                _complete_idea_metadata.get("boundary_adjustment_reason", "complete_idea"),
                            )
                if not _editorial_boundary_adjusted:
                    logger.info(
                        "[complete-idea] score=%.2f boundary_applied=false old=%.2f-%.2f new=%.2f-%.2f reason=%s",
                        _idea_score,
                        _editorial_boundary_old_start,
                        _editorial_boundary_old_end,
                        start_seconds,
                        end_seconds,
                        _complete_idea_metadata.get("boundary_adjustment_reason") or ("no_timestamp_lines" if not _transcript_lines else "not_needed"),
                    )
                    if _idea_score < 0.75:
                        logger.info("[complete-idea] reject reason=incomplete_thought")
                segment.update(_complete_idea_metadata)
        except Exception as _ef_e:
            logger.debug("[complete-idea] boundary_adjustment_skipped reason=%s", _ef_e)

        # ── FASE 3: Fluency edit plan (pre-render disfluency detection) ────────
        # Detect disfluencies (false starts, repetitions, filler words) BEFORE
        # rendering so the silence editor or a pre-render step can address them.
        _fluency_edit_plan = None
        _editorial_rhythm_plan = None
        try:
            from .vpi_editorial_fluency_service import (
                build_fluency_edit_plan as _build_fluency_edit_plan,
                build_edit_decision_list as _build_edit_decision_list,
                _parse_transcript_lines as _parse_transcript_lines_fluency,
            )
            _segment_text = segment.get("text", "")
            if _segment_text:
                _transcript_lines = _parse_transcript_lines_fluency(_segment_text)
                if _transcript_lines:
                    _fluency_plan_obj = _build_fluency_edit_plan(_transcript_lines)
                    _fluency_edit_plan = {
                        "enabled": _fluency_plan_obj.enabled,
                        "fluency_score_before": _fluency_plan_obj.fluency_score_before,
                        "fluency_score_after": _fluency_plan_obj.fluency_score_after,
                        "disfluency_count": _fluency_plan_obj.disfluency_count,
                        "false_start_count": _fluency_plan_obj.false_start_count,
                        "repetition_groups": _fluency_plan_obj.repetition_groups,
                        "fluency_edit_applied": _fluency_plan_obj.fluency_edit_applied,
                        "edits": [
                            asdict(e) if hasattr(e, "__dataclass_fields__") else dict(e)
                            for e in (_fluency_plan_obj.edits or [])
                        ],
                    }
                    _editorial_rhythm_obj = _build_edit_decision_list(
                        _transcript_lines,
                        fluency_plan=_fluency_plan_obj,
                        silence_plan={},
                        duration_s=duration,
                    )
                    _editorial_rhythm_plan = asdict(_editorial_rhythm_obj)
                    segment["fluency_edit_plan"] = _fluency_edit_plan
                    segment["fluency_score_before"] = _fluency_edit_plan["fluency_score_before"]
                    segment["fluency_score_after"] = _fluency_edit_plan["fluency_score_after"]
                    segment["disfluency_count"] = _fluency_edit_plan["disfluency_count"]
                    segment["false_start_count"] = _fluency_edit_plan["false_start_count"]
                    segment["repetition_groups"] = _fluency_edit_plan["repetition_groups"]
                    segment["editorial_rhythm"] = _editorial_rhythm_plan
                    logger.info(
                        "[fluency-edit] plan_created=true "
                        "score_before=%.2f score_after=%.2f "
                        "disfluencies=%d false_starts=%d media_applied=false",
                        _fluency_plan_obj.fluency_score_before,
                        _fluency_plan_obj.fluency_score_after,
                        _fluency_plan_obj.disfluency_count,
                        _fluency_plan_obj.false_start_count,
                    )
                    logger.info(
                        "[editorial-rhythm] edl_actions=%d pauses_cut=%d pauses_kept=%d jump_cuts=%d",
                        len(_editorial_rhythm_plan.get("decisions") or []),
                        sum(1 for d in (_editorial_rhythm_plan.get("decisions") or []) if d.get("source") == "silence" and d.get("action") == "cut"),
                        sum(1 for d in (_editorial_rhythm_plan.get("decisions") or []) if d.get("source") == "pause" and d.get("action") == "keep"),
                        int(_editorial_rhythm_plan.get("jump_cuts_count") or 0),
                    )
                else:
                    logger.info("[fluency-edit] plan_created=false cuts=0 media_applied=false reason=no_timestamp_lines")
        except Exception as _fe_e:
            logger.debug("[fluency-edit] plan_skipped reason=%s", _fe_e)

        # ── FASE 4: Hook Fit start adjustment — before media extraction ──────
        # Only adjust when timestamped transcript lines prove a stronger nearby
        # opening exists. Plain metadata-only hook fit happens later as well.
        try:
            from .vpi_hook_engine import (
                assess_hook_fit as _assess_hook_fit_runtime,
                find_better_hook_start as _find_better_hook_start_runtime,
            )
            from .vpi_editorial_fluency_service import _parse_transcript_lines as _parse_transcript_lines_hookfit

            _segment_text_hf_pre = str(segment.get("text") or "")
            _hook_lines_pre = _parse_transcript_lines_hookfit(_segment_text_hf_pre)
            _first_hook_phrase = str((_hook_lines_pre[0] if _hook_lines_pre else {}).get("text") or _segment_text_hf_pre)
            _hook_fit_pre = _assess_hook_fit_runtime(
                _first_hook_phrase,
                editorial_type=str(segment.get("editorial_type") or ""),
                hook_type=str(segment.get("hook_type") or ""),
                hook_plan={"start_s": start_seconds, "duration_s": duration},
            )
            _hook_start_adjustment = _find_better_hook_start_runtime(_first_hook_phrase, _hook_lines_pre)
            _adjusted_hook_start = float(_hook_start_adjustment.get("adjusted_start_s") or 0.0)
            if (
                _hook_start_adjustment.get("adjusted_start")
                and _adjusted_hook_start > start_seconds + 0.05
                and _adjusted_hook_start < end_seconds - 3.0
            ):
                _old_hook_start = start_seconds
                start_seconds = _adjusted_hook_start
                duration = max(end_seconds - start_seconds, 0.1)
                segment["hook_start_adjusted"] = True
                segment["hook_start_adjustment_reason"] = _hook_start_adjustment.get("reason", "stronger_opening_phrase")
                logger.info(
                    "[hook-fit] intent=%s style=%s confidence=%.2f adjusted_start=%.2f reason=%s",
                    _hook_fit_pre.get("intent", "unknown"),
                    _hook_fit_pre.get("style", "unknown"),
                    float(_hook_fit_pre.get("confidence") or 0.0),
                    start_seconds,
                    _hook_start_adjustment.get("reason", ""),
                )
                logger.info(
                    "[hook-fit] adjusted_start from=%.2f to=%.2f reason=%s",
                    _old_hook_start,
                    start_seconds,
                    _hook_start_adjustment.get("reason", ""),
                )
            else:
                logger.info(
                    "[hook-fit] intent=%s style=%s confidence=%.2f adjusted_start=false reason=%s",
                    _hook_fit_pre.get("intent", "unknown"),
                    _hook_fit_pre.get("style", "unknown"),
                    float(_hook_fit_pre.get("confidence") or 0.0),
                    _hook_start_adjustment.get("reason", "no_adjustment"),
                )
        except Exception as _hf_pre_e:
            logger.debug("[hook-fit] pre_render_adjustment_skipped reason=%s", _hf_pre_e)

        _premium_runtime = premium_runtime_contract(beta_clean=False)

        # Platform minimum enforcement — respect the LLM's natural speech boundary.
        # Only extend clips that are genuinely too short (< 30s); never pad a
        # well-bounded segment just because it has a high virality score.
        _vscore_pre = segment.get("virality_score", 50)
        _FLOOR = 30.0  # hard platform minimum
        if duration < _FLOOR:
            if _vscore_pre >= 70:
                _target_dur = min(60.0, duration * 2)
            elif _vscore_pre >= 50:
                _target_dur = min(45.0, duration * 2)
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

        # PASO 1: Phi-3-mini Scroll Stop Test — hard 5s timeout to prevent Ollama hangs
        # [beta-clean] Skipped when VIRACLIP_BETA_CLEAN=true
        _cfg = get_service_config()
        if not _cfg.beta_clean:
            logger.info(f"[Clip {clip_index+1}] Step 1: Phi-3-mini virality scoring...")
            try:
                phi3_service = get_phi3_service()
                virality_result = await asyncio.wait_for(
                    phi3_service.score_segment(
                        segment_text=segment.get("text", ""),
                        duration=duration,
                        audio_features=None,
                    ),
                    timeout=5.0,
                )
                
                # Phase 2.2: blend Phi-3 score with locally-trained MLP scorer
                try:
                    from .viral_scorer_service import get_viral_scorer
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
                
                logger.info(f"  ✓ Phi-3 score: {virality_result.total_score}/100, "
                           f"Hook: {virality_result.primary_hook_type}")
            except Exception as phi3_e:
                logger.warning(f"  Phi-3 scoring failed: {phi3_e}")
                virality_result = None
        else:
            logger.info("[beta-clean] advanced virality scoring skipped")
            virality_result = None
        
        # PASO 2: Audio spectral analysis — skipped when segment text exists (saves 1-3 min)
        # The Groq AI brain already infers energy/mood from transcript text semantically.
        audio_features = {}
        _has_transcript = bool(segment.get("text", "").strip())
        if not _has_transcript:
            logger.info(f"[Clip {clip_index+1}] Step 2: Audio spectral analysis (no transcript)...")
            try:
                from tempfile import NamedTemporaryFile
                audio_temp = NamedTemporaryFile(suffix='.wav', delete=False)
                audio_temp.close()
                audio_ss = 0.0 if use_extracted_segment else start_seconds
                cmd = [_get_ffmpeg_exe(), "-y", "-ss", str(audio_ss), "-i", str(video_path),
                       "-t", str(duration), "-vn", "-acodec", "pcm_s16le",
                       "-ar", "16000", "-ac", "1", audio_temp.name]
                subprocess.run(cmd, capture_output=True, timeout=60)
                if Path(audio_temp.name).exists():
                    audio_features = analyze_audio_virality(audio_temp.name)
                    Path(audio_temp.name).unlink()
            except Exception as audio_e:
                logger.warning(f"  Audio analysis failed: {audio_e}")
        else:
            logger.info(f"[Clip {clip_index+1}] Step 2: Audio analysis skipped (transcript available)")
        
        # PASO 3: Detectar cortes narrativos inteligentes (Capa A)
        if not _cfg.beta_clean:
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
        else:
            logger.info("[beta-clean] advanced cut detection skipped")
            segment["narrative_cuts"] = []
            cut_points = []

        # ── Clip Intelligence Profile ────────────────────────────────────
        # Single analysis pass that drives: LUT, caption style, B-roll
        # density/duration, BGM category, SFX emphasis, zoom intensity.
        if not _cfg.beta_clean:
            try:
                from .clip_intelligence import build_clip_profile_async as _build_profile_async
                _clip_profile = await _build_profile_async(
                    segment=segment,
                    duration=duration,
                    clip_index=clip_index,
                    caption_template=caption_template or "viral",
                )
            except Exception as _ci_e:
                logger.debug(f"  ClipIntelligence skipped: {_ci_e}")
                _clip_profile = None
        else:
            logger.info("[beta-clean] advanced clip profile disabled; using local minimal profile")
            _clip_profile = SimpleNamespace(
                mood="neutral",
                energy=0.5,
                pace=0.5,
                lut="none",
                caption_style="viral",
                broll_keywords=[],
                bgm=None,
                zoom_intensity="off",
                grain=0,
                saturation=1.0,
                contrast=1.0,
                content_category="general",
                ai_keywords=None,
                broll_count=0,
                broll_duration=0.0,
                broll_fade_s=0.0,
                bgm_category=None,
            )

        # PASO 4: Word-level confidence subtitles (Fase 3 del plan)
        words_with_confidence = []
        
        # Definir clip_path antes de usarlo
        _task_short = task_id.replace("-", "")[:8] if task_id else ""
        clip_filename = (
            f"clip_{_task_short}_{clip_index + 1}_viral_{int(segment.get('virality_score', 0))}_"
            f"{segment['start_time'].replace(':', '')}-"
            f"{segment['end_time'].replace(':', '')}.mp4"
        )
        clip_path = output_dir / clip_filename
        logger.info(
            "[render-output] task_id=%s clip_filename=%s",
            task_id, clip_filename,
        )

        def _words_from_cached_transcript(_cached: Dict[str, Any], _source_label: str) -> List[Dict[str, Any]]:
            _seg_start_ms = start_seconds * 1000.0
            _seg_end_ms = end_seconds * 1000.0
            _clip_dur_s = duration
            _real_words: List[Dict[str, Any]] = []
            for _w in _cached.get("words", []) or []:
                _ws = float(_w.get("start", 0))
                _we = float(_w.get("end", _ws + 200))
                if _we <= _seg_start_ms or _ws >= _seg_end_ms:
                    continue
                _rel_s = max(0.0, (_ws - _seg_start_ms) / 1000.0)
                _rel_e = min(_clip_dur_s, (_we - _seg_start_ms) / 1000.0)
                if _rel_e <= _rel_s:
                    continue
                _real_words.append({
                    "word": (_w.get("text") or "").strip(),
                    "start": round(_rel_s, 3),
                    "end": round(_rel_e, 3),
                    "confidence": float(_w.get("confidence", 0.9)),
                    "is_emphasis": float(_w.get("confidence", 0.9)) < 0.80,
                })
            if _real_words:
                logger.info(
                    "[caption-timeline] using cached word timestamps words=%d "
                    "segment_start=%.1f segment_end=%.1f source=%s",
                    len(_real_words), start_seconds, end_seconds, _source_label,
                )
                logger.info(
                    "[caption-timeline] first_abs=%.1f first_rel=%.3f",
                    _real_words[0]["start"] + start_seconds,
                    _real_words[0]["start"],
                )
                logger.info(
                    "[caption-timeline] last_abs=%.1f last_rel=%.3f",
                    _real_words[-1]["end"] + start_seconds,
                    _real_words[-1]["end"],
                )
            return _real_words

        def _load_cached_caption_words() -> List[Dict[str, Any]]:
            try:
                from ..video_processing.transcription import load_cached_transcript_data as _load_cache_words
            except Exception as _cache_import_e:
                logger.debug("[caption-cache] import failed: %s", _cache_import_e)
                return []

            candidates: List[Path] = []
            for _candidate in (
                segment.get("_source_video_path"),
                segment.get("source_video_path"),
                segment.get("original_video_path"),
                str(video_path),
            ):
                if _candidate:
                    _p = Path(str(_candidate))
                    if _p not in candidates:
                        candidates.append(_p)
                    _upload_p = Path("/app/temp/uploads") / _p.name
                    if _upload_p not in candidates:
                        candidates.append(_upload_p)

            for _candidate in candidates:
                logger.info("[caption-cache] trying transcript cache candidate=%s", _candidate)
                _cached = _load_cache_words(_candidate)
                if _cached and _cached.get("words"):
                    _real_words = _words_from_cached_transcript(_cached, str(_candidate))
                    if _real_words:
                        logger.info("[caption-cache] hit candidate=%s", _candidate)
                        return _real_words
                logger.info("[caption-cache] miss candidate=%s", _candidate)

            _segment_text = " ".join((segment.get("text") or "").lower().split())
            _needle = " ".join(_segment_text.split()[:8])
            if _needle:
                for _cache_path in Path("/app/temp/uploads").glob("*.transcript_cache.json"):
                    logger.info("[caption-cache] trying transcript cache candidate=%s", _cache_path)
                    try:
                        _cached = json.loads(_cache_path.read_text(encoding="utf-8"))
                    except Exception as _cache_parse_e:
                        logger.info("[caption-cache] miss candidate=%s", _cache_path)
                        logger.debug("[caption-cache] parse failed: %s", _cache_parse_e)
                        continue
                    _cache_text = " ".join((_cached.get("text") or "").lower().split())
                    if _needle not in _cache_text:
                        logger.info("[caption-cache] miss candidate=%s", _cache_path)
                        continue
                    _real_words = _words_from_cached_transcript(_cached, str(_cache_path))
                    if _real_words:
                        logger.info("[caption-cache] hit candidate=%s", _cache_path)
                        return _real_words
                    logger.info("[caption-cache] miss candidate=%s", _cache_path)

            return []
        
        if add_subtitles:
            logger.info(f"[Clip {clip_index+1}] Step 4: Generating subtitles...")

            # ── Priority 1: AssemblyAI transcript cache ──────────────────
            # The cache is keyed on the ORIGINAL source video, not the
            # pre-extracted segment.  segment["_source_video_path"] is
            # injected by task_service.py before the render loop.
            try:
                from ..video_processing.transcription import load_cached_transcript_data as _load_aai
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

            if not words_with_confidence:
                words_with_confidence = _load_cached_caption_words()

            # ── Priority 1.5: Groq Whisper API — fast cloud transcription (5s vs 5min) ──
            if not _cfg.beta_clean and not words_with_confidence:
                try:
                    _gw_key = os.environ.get("GROQ_API_KEY", "")
                    _audio_for_groq = output_dir / f"audio_gw_{clip_index}.wav"
                    _audio_ss_gw = 0.0 if use_extracted_segment else start_seconds
                    _cmd_gw = [
                        _get_ffmpeg_exe(), "-y",
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
                                    "timestamp_granularities": "word",
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
            elif _cfg.beta_clean and not words_with_confidence:
                logger.info("[beta-clean] cloud transcription disabled; using local transcription/cache")

            # ── Priority 2: faster-whisper local (last resort) ──────────────
            if not words_with_confidence and _confidence_subtitle_available:
                try:
                    _whisper_device = os.environ.get("WHISPER_DEVICE", "cpu")
                    subtitle_gen = ConfidenceSubtitleGenerator(model_size="tiny", device=_whisper_device)
                    audio_temp_path = output_dir / f"audio_temp_{clip_index}.wav"
                    audio_ss2 = 0.0 if use_extracted_segment else start_seconds
                    cmd_extract = [
                        _get_ffmpeg_exe(), "-y",
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

        # ── Priority 3: cached transcript word timestamps (real, not fallback) ──
        if not words_with_confidence and segment.get("text"):
            words_with_confidence = _load_cached_caption_words()

        # Fallback: no transcript cache and no Whisper — build from segment.text.
        # Emit one entry per word so the ASS karaoke grouper (3 words / line) works
        # correctly; even spacing is imprecise but still watchable.
        if not words_with_confidence and segment.get("text"):
            logger.warning("[SUBTITLE-FALLBACK] no word timestamps available; using text timing approximation")
            _words_list = [w for w in segment["text"].split() if w.strip()]
            if _words_list:
                _orig_speech_dur = (
                    parse_timestamp_to_seconds(segment["end_time"])
                    - parse_timestamp_to_seconds(segment["start_time"])
                )
                # Estimate speech duration from word count (0.38s/word + 1.5s buffer)
                # This prevents subtitle stretch when clip is padded beyond real speech.
                _words_count = len(_words_list)
                _estimated_speech = _words_count * 0.38 + 1.5
                _effective_dur = min(duration, _orig_speech_dur, max(6.0, _estimated_speech))
                # Clamp per-word step to avoid too-fast or too-slow subtitles
                _word_step = _effective_dur / max(_words_count, 1)
                _word_step = max(0.28, min(0.50, _word_step))
                logger.info(
                    "[caption-timeline] fallback=true segment_start=%s clip_duration=%.1f",
                    segment.get("start_time"), duration,
                )
                logger.info(
                    "[caption-timeline] fallback words=%d orig_dur=%.1f effective_dur=%.1f step=%.3f",
                    _words_count, _orig_speech_dur, _effective_dur, _word_step,
                )
                _cursor = 0.0
                _EMPHASIS_RE = {"secret","truth","never","always","stop","wrong",
                                "hack","real","exposed","shocking","actually"}
                for _w in _words_list:
                    _start = _cursor
                    _end = min(_cursor + _word_step, duration)
                    if _end <= _start:
                        break
                    words_with_confidence.append({
                        "word":       _w,
                        "start":      round(_start, 3),
                        "end":        round(_end, 3),
                        "confidence": 0.9,
                        "is_emphasis": _w.lower().strip(".,!?") in _EMPHASIS_RE,
                    })
                    _cursor += _word_step
                if words_with_confidence:
                    logger.info(
                        "[caption-timeline] first_rel=%.2f last_rel=%.2f words_in_clip=%d",
                        words_with_confidence[0]["start"],
                        words_with_confidence[-1]["end"],
                        len(words_with_confidence),
                    )
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
            logger.debug(f"Rendering from pre-extracted segment: 0-{duration:.1f}s")
        else:
            # Render from full video using original timestamps
            render_start = start_seconds
            render_end = end_seconds
            logger.debug(f"Rendering from full video: {start_seconds:.1f}-{end_seconds:.1f}s")

        # FFmpegGuard: validate segment params before FFmpeg — catches bad coordinates early
        try:
            from ..video_processing.ffmpeg_guard import validate_segment_call
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
        )

        if not success:
            logger.error(f"Failed to create base clip {clip_index + 1}")
            return None

        output_path = clip_path
        _flash_ts: List[float] = []  # cut-boundary timestamps for flash overlay

        # ── Step 4.0b: Re-alineacion precisa de subtitulos ──────────────
        # Re-transcribir el clip ya cortado para eliminar drift acumulado
        # del video original. Solo si hay words_with_confidence disponibles.
        _realign_enabled = os.environ.get("SUBTITLE_REALIGN_ENABLED", "true").lower() == "true"
        logger.info(
            f"[RE-ALIGN] Check: enabled={_realign_enabled} "
            f"words={len(words_with_confidence) if words_with_confidence else 0} "
            f"path_exists={os.path.exists(str(output_path))}"
        )
        if _realign_enabled and words_with_confidence and os.path.exists(str(output_path)):
            _realigner = None  # Initialize before try block
            try:
                _realign_model = os.environ.get("SUBTITLE_REALIGN_MODEL", "medium")
                _whisper_device, _ = resolve_whisper_device()
                _anticipation_ms = float(os.environ.get("SUBTITLE_ANTICIPATION_MS", "-80"))

                from .confidence_subtitle_service import ConfidenceSubtitleGenerator as _LocalConfidenceSubtitleGenerator
                if _LocalConfidenceSubtitleGenerator is None:
                    raise ImportError("ConfidenceSubtitleGenerator not available")
                _realigner = _LocalConfidenceSubtitleGenerator(
                    model_size=_realign_model,
                    device=_whisper_device
                )
                logger.info("[RE-ALIGN] initialized ConfidenceSubtitleGenerator OK")
                _realigned = _realigner.realign_on_segment(
                    segment_video_path=str(output_path),
                    original_words=words_with_confidence,
                    language=target_language,
                    anticipation_offset_ms=_anticipation_ms
                )
                if _realigned:
                    _drift_ok = True
                    if words_with_confidence and len(_realigned) >= 3:
                        _common = min(len(words_with_confidence), len(_realigned))
                        _deltas = [
                            abs(float(_realigned[i].get("start", 0)) - float(words_with_confidence[i].get("start", 0)))
                            for i in range(_common)
                        ]
                        _avg_drift = sum(_deltas) / len(_deltas) if _deltas else 0.0
                        if _avg_drift > 0.5:
                            logger.warning("[RE-ALIGN] Avg drift %.3fs > 0.5s — rejecting re-alignment", _avg_drift)
                            _drift_ok = False
                        else:
                            logger.info("[RE-ALIGN] Avg drift %.3fs — within tolerance", _avg_drift)
                    if _drift_ok:
                        logger.info(
                            f"[CLIP] Re-alineacion OK: {len(words_with_confidence)} → {len(_realigned)} palabras"
                        )
                        words_with_confidence = _realigned
                else:
                    logger.warning("[CLIP] Re-alineacion retorno vacio, manteniendo originales")
            except Exception as e:
                logger.warning(f"[CLIP] Re-alineacion fallo ({e}), manteniendo originales")

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
                from .upscaling_service import UpscalingService
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
                from .voice_synthesis import VoiceSynthesisService, VoiceStyle
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

        # Step 4.2-jc: Silence handling — jump-cut OR speed-ramp based on SILENCE_MODE.
        # Must happen BEFORE subtitle burn so ASS timestamps stay in sync.
        if words_with_confidence:
            try:
                _silence_thresh = float(
                    os.environ.get("SILENCE_THRESHOLD_SECONDS", str(SILENCE_THRESHOLD))
                )
                _jc_keep, _jc_saved = build_keep_intervals(
                    words_with_confidence, duration, _silence_thresh
                )
                _max_ratio = float(os.environ.get("SILENCE_MAX_COMPRESSION", "0.30"))
                if (_jc_saved >= MIN_SILENCE_SAVINGS
                        and len(_jc_keep) >= 2
                        and (duration <= 0 or _jc_saved / duration <= _max_ratio)):
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
                        output_path = _jc_path
                        words_with_confidence = VideoService._adjust_words_for_cuts(
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
            except Exception as _jc_e:
                logger.debug(f"  Silence handling skipped: {_jc_e}")

        # Step 4.2d: Cut Zoom — dynamic zoom punches at jump-cut points (Hormozi/MrBeast)
        # [beta-clean] Skipped when VIRACLIP_BETA_CLEAN=true
        if os.environ.get("CUT_ZOOM_ENABLED", "true").lower() == "true" and not _cfg.beta_clean:
            try:
                from .cut_zoom_service import apply_cut_zooms
                # Extract cut points from word boundaries (end of each word = potential cut)
                _cut_points = [
                    w["end"] for w in (words_with_confidence or [])
                    if w.get("end") and w.get("probability", 1.0) > 0.85
                ][::4]  # every 4th word boundary to avoid over-zooming
                if _cut_points:
                    _cz_out = output_path.with_name(f"cz_{output_path.name}")
                    _cz_ok = await apply_cut_zooms(
                        video_path=str(output_path),
                        output_path=str(_cz_out),
                        cut_points=_cut_points[:8],  # max 8 zoom points
                    )
                    if _cz_ok and _cz_out.exists():
                        _cz_out.replace(output_path)
                        logger.info(f"  ✓ Cut zooms applied ({len(_cut_points[:8])} points)")
            except Exception as _cz_e:
                logger.debug(f"  Cut zoom skipped: {_cz_e}")
        elif os.environ.get("CUT_ZOOM_ENABLED", "true").lower() == "true":
            logger.info(f"[beta-clean] Cut zoom skipped (beta_clean mode)")

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
                        from .enhanced_tracking_service import EnhancedTrackingService
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
                            _ef_cmd = [
                                _get_ffmpeg_exe(), "-y", "-i", str(output_path),
                                "-vf", f"crop=in_w:in_h:{max(0,_avg_cx-540)}:{max(0,_avg_cy-960)},scale=1080:1920",
                                "-c:v", "libx264", "-preset", "fast", "-c:a", "copy",
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
                        output_path = polished_path

            # Talking-head auto-detection: if face was found AND audio has words
            # → we're looking at a speaker clip → auto-apply eye contact correction.
            # Override via EYE_CONTACT_AUTO=false to disable.
            _eye_contact_auto = os.environ.get("EYE_CONTACT_AUTO", "true").lower() != "false"
            _is_talking_head = _face_centered and bool(words_with_confidence)
            # [beta-clean] Skipped when VIRACLIP_BETA_CLEAN=true
            if (eye_contact_correction or (_is_talking_head and _eye_contact_auto)) and not _cfg.beta_clean:
                try:
                    if "polisher" not in dir():
                        from .video_polish_service import VideoPolishService
                        polisher = VideoPolishService()
                    polished_path = output_path.with_name(f"gaze_{output_path.name}")
                    await polisher.apply_eye_contact_correction(output_path, polished_path)
                    if polished_path.exists():
                        output_path = polished_path
                        if _is_talking_head and not eye_contact_correction:
                            logger.info("  ✓ Eye contact correction auto-applied (talking head detected)")
                except Exception as _ec_e:
                    logger.debug("  Eye contact correction skipped: %s", _ec_e)
            elif eye_contact_correction or (_is_talking_head and _eye_contact_auto):
                logger.info(f"[beta-clean] Eye contact correction skipped (beta_clean mode)")

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

        _caption_decisions: Dict[str, Any] = {}
        _transition_metadata: Dict[str, Any] = {}
        _sfx_metadata: Dict[str, Any] = {}
        _publishable_metadata: Dict[str, Any] = {}

        # ── VPI Premium Composition Pack v1: build composition decision ──────────
        _composition_decision: Dict[str, Any] = {}
        try:
            from .vpi_visual_effects_service import build_composition_decision as _build_composition_decision
            _hook_intent_for_comp = str((_hook_plan_data or {}).get("hook_intent") or segment.get("editorial_type") or "")
            _composition_decision = _build_composition_decision(
                hook_intent=_hook_intent_for_comp,
                visual_profile=str((_hook_plan_data or {}).get("visual_profile") or ""),
                caption_overlay_pack=_caption_decisions if isinstance(_caption_decisions, dict) else {},
                transition_plan=_transition_metadata if isinstance(_transition_metadata, dict) else {},
                sfx_plan=_sfx_metadata if isinstance(_sfx_metadata, dict) else {},
                private_premium_status=str(_publishable_metadata.get("private_premium_status") or ""),
                segment_text=str(segment.get("text") or ""),
            )
            logger.info(
                "[composition-pack] runtime_connected=true mode=%s priority=%s max_layers=%d",
                _composition_decision.get("composition_mode", "unknown"),
                _composition_decision.get("screen_priority", "unknown"),
                _composition_decision.get("max_simultaneous_layers", 0),
            )
        except Exception as _comp_e:
            logger.debug("[composition-pack] runtime skipped reason=%s", _comp_e)
            _composition_decision = {}

        # Step 4.7: Hook Visual Overlay — ONLY when ASS subtitles are NOT burned.
        # When subtitles are active both layers appear simultaneously (0-2s) causing
        # a double-text overlap. The karaoke subtitle already serves as the visual hook.
        if _cfg.beta_clean:
            logger.info("[beta-clean] HookVisualService skipped")
        elif not words_with_confidence:
            try:
                hook_service = HookVisualService()
                hook = hook_service.generate_hook_from_segment(segment, duration=2.0)
                hooked_path = output_path.with_name(f"hook_{output_path.name}")
                await hook_service.add_hook_to_video(
                    str(output_path),
                    str(hooked_path),
                    hook,
                    subtitle_path=segment.get("colored_subtitle_path")
                )
                if Path(hooked_path).exists():
                    output_path = hooked_path
                    logger.info(f"  ✓ Hook overlay added: {hook.text[:30]}...")
            except Exception as hook_e:
                logger.warning(f"  Hook overlay failed: {hook_e}")

        # Step 4.5b: Beat-sync BPM detection — derive beat timestamps for
        # edit-point alignment BEFORE EditingPipeline so zoom punches land on beats.
        _beat_times: List[float] = []
        _beat_bpm: float = 0.0
        if not _cfg.beta_clean:
            try:
                from .beat_sync_service import analyse_bpm as _analyse_bpm
                _bpm_result = await _analyse_bpm(audio_path=output_path)
                _beat_bpm   = _bpm_result.get("bpm", 0.0)
                _beat_times = _bpm_result.get("beat_times", [])
                if _beat_times:
                    logger.info(f"  ✓ BPM detected: {_beat_bpm:.1f} ({len(_beat_times)} beats)")
            except Exception as _bpm_e:
                logger.debug(f"  BPM detection skipped: {_bpm_e}")
        else:
            logger.info("  [beta-clean] BeatSync BPM analysis skipped")

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
                from .editorial_brain import CATEGORY_RULES as _CAT_RULES
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

        # Step 4.6: Editing Pipeline — color grading, cinematic look, vignette,
        # zoom punch-in / Ken Burns / pattern interrupts, lower thirds,
        # progress bar, loudness normalization (single FFmpeg pass).
        # [beta-clean] Skipped when VIRACLIP_BETA_CLEAN=true
        _lut_preset_ep = ""  # pre-init so always defined even if EP try block fails early
        _lut_vf_ep = ""
        if not _cfg.beta_clean:
            try:
                _ep = EditingPipeline()
                _ep_out = output_path.with_name(f"ep_{output_path.name}")
                _ep_segment_text = segment.get("text", "")[:60] if segment else ""
                # Resolve LUT filter string here so EP can bake it in one pass
                _lut_preset_ep = (
                    (_clip_profile.lut if _clip_profile else None)
                    or os.environ.get("LUT_PRESET", "teal_orange")
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
                    flash_timestamps=None,  # Desactivado - flashes cegadores eliminados
                    gpu_settings=gpu_encoding_settings if gpu_encoding_settings else None,
                    energy_level=_clip_profile.energy if _clip_profile else 0.5,
                    zoom_intensity=_clip_profile.zoom_intensity if _clip_profile else "medium",
                    grain_override=_clip_profile.grain if _clip_profile else 0,
                    lut_vf=_lut_vf_ep,
                    denoise_audio=True,
                )
                if _ep_result == _ep_out and _ep_out.exists():
                    output_path = _ep_out
                    logger.info("  ✓ EditingPipeline: color+cine+vignette+zoom+PI+lower-third+progress+loudnorm")
            except Exception as _ep_e:
                logger.warning(f"  EditingPipeline failed: {_ep_e}")
        else:
            logger.info(f"[beta-clean] EditingPipeline skipped (beta_clean mode)")
        _premium_runtime = premium_runtime_contract(beta_clean=bool(_cfg.beta_clean))
        logger.info(
            "[premium-runtime] enabled=%s retention=%s transitions=%s sfx=%s music=%s vfx=%s frame_rhythm=%s",
            str(_premium_runtime["premium_runtime_enabled"]).lower(),
            str(_premium_runtime["retention"]).lower(),
            str(_premium_runtime["transitions"]).lower(),
            str(_premium_runtime["sfx"]).lower(),
            str(_premium_runtime["music"]).lower(),
            str(_premium_runtime["vfx"]).lower(),
            str(_premium_runtime["frame_rhythm"]).lower(),
        )

        # Step 4.6b: LUT now merged into EditingPipeline — standalone pass removed.
        if _lut_vf_ep:
            logger.info(f"  ✓ LUT '{_lut_preset_ep}' baked into EditingPipeline pass")

        # VPI Daily Publishing: deterministic editing plan + safe smart reframe metadata.
        _editing_plan_data = {}
        _hook_plan_data = {}
        _smart_reframe_metadata = {}
        _silence_edit_plan_data = {}
        _shot_rhythm_metadata = {}
        try:
            from .vpi_broll_intent import detect_clip_theme as _detect_clip_theme
            from .vpi_editing_plan import assess_visual_density as _assess_visual_density
            from .vpi_editing_plan import build_editing_plan as _build_editing_plan
            from .vpi_hook_engine import build_hook_plan as _build_hook_plan
            from .vpi_silence_editor import apply_silence_edit_plan as _apply_silence_edit_plan
            from .vpi_silence_editor import build_silence_edit_plan as _build_silence_edit_plan
            from .vpi_silence_editor import _build_offset_map as _build_silence_offset_map
            from .vpi_silence_editor import remap_events as _remap_silence_events
            from .vpi_silence_editor import remap_hook_plan as _remap_silence_hook_plan
            from .vpi_silence_editor import remap_word_timestamps as _remap_silence_words
            from .vpi_visual_effects_service import build_shot_rhythm_decision as _build_shot_rhythm_decision
            from .smart_reframe_service import SmartReframeService as _SmartReframeService
            _vpi_theme = _detect_clip_theme(
                segment.get("text", ""),
                editorial_type=segment.get("editorial_type"),
                matched_patterns=segment.get("matched_patterns", []),
                suggested_broll_cue_type=segment.get("suggested_broll_cue_type"),
                vpi_score=segment.get("vpi_score"),
            )
            _editing_plan_obj = _build_editing_plan(
                text=segment.get("text", ""),
                editorial_type=segment.get("editorial_type"),
                vpi_score=segment.get("vpi_score"),
                matched_patterns=segment.get("matched_patterns", []),
                clip_duration=duration,
                word_timestamps=words_with_confidence or None,
                theme=_vpi_theme,
                has_broll=False,
            )
            _editing_plan_data = _editing_plan_obj.to_dict()
            _hook_plan_obj = _build_hook_plan(
                text=segment.get("text", ""),
                editorial_type=segment.get("editorial_type"),
                vpi_score=segment.get("vpi_score"),
                matched_patterns=segment.get("matched_patterns", []),
                word_timestamps=words_with_confidence or None,
                clip_duration=duration,
                editing_plan=_editing_plan_data,
                theme=_vpi_theme,
            )
            _hook_plan_data = _hook_plan_obj.to_dict()

            # ── FASE 4: Hook Fit integration (intent + style) ──────────────────
            # After building the hook plan, classify the hook intent and assess
            # hook fit so the render step can use intent-aware visual treatment.
            try:
                from .vpi_hook_engine import (
                    classify_hook_intent as _classify_hook_intent,
                    assess_hook_fit as _assess_hook_fit_hook,
                    choose_hook_style as _choose_hook_style,
                )
                _segment_text_hf = segment.get("text", "")
                _editorial_type_hf = segment.get("editorial_type") or ""
                _hook_intent_result = _classify_hook_intent(
                    _segment_text_hf,
                    editorial_type=_editorial_type_hf,
                )
                _hook_fit_result = _assess_hook_fit_hook(
                    _segment_text_hf,
                    editorial_type=_editorial_type_hf,
                    hook_type=str(_hook_plan_data.get("hook_type") or ""),
                    hook_plan=_hook_plan_data,
                )
                _hook_plan_data["hook_intent"] = _hook_intent_result.get("intent", "unknown")
                _hook_plan_data["hook_intent_confidence"] = _hook_intent_result.get("confidence", 0.0)
                _hook_plan_data["hook_style"] = _hook_fit_result.get("style", "clean_explanation")
                _hook_plan_data["hook_fit_confidence"] = _hook_fit_result.get("confidence", 0.0)
                _hook_plan_data["hook_fit_acceptable"] = _hook_fit_result.get("hook_fit_acceptable", False)
                _hook_plan_data["hook_fit_reason"] = _hook_fit_result.get("hook_fit_reason", "")
                _hook_plan_data["recommended_visual"] = _hook_fit_result.get("recommended_visual", "")
                _hook_plan_data["recommended_sfx"] = _hook_fit_result.get("recommended_sfx", "")
                _hook_plan_data["subtitle_emphasis"] = _hook_fit_result.get("subtitle_emphasis", "")
                _hook_plan_data["hook_start_adjusted"] = _hook_fit_result.get("start_adjusted", False)
                _hook_plan_data["hook_start_adjustment_reason"] = _hook_fit_result.get("start_adjustment_reason", "")
                logger.info(
                    "[hook-fit] intent=%s style=%s confidence=%.2f acceptable=%s",
                    _hook_plan_data["hook_intent"],
                    _hook_plan_data["hook_style"],
                    _hook_plan_data["hook_fit_confidence"],
                    str(_hook_plan_data["hook_fit_acceptable"]).lower(),
                )
            except Exception as _hf_e:
                logger.debug("[hook-fit] integration_skipped reason=%s", _hf_e)
                _hook_plan_data.setdefault("hook_intent", "unknown")
                _hook_plan_data.setdefault("hook_style", "clean_explanation")
                _hook_plan_data.setdefault("hook_fit_acceptable", False)
            if _hook_plan_data.get("zoom_event"):
                _existing_zoom_events = list(_editing_plan_data.get("smart_zoom_events") or [])
                _editing_plan_data["smart_zoom_events"] = [_hook_plan_data["zoom_event"]] + _existing_zoom_events
            _editing_plan_data["hook_plan"] = _hook_plan_data
            _planned_has_broll = (_editing_plan_data or {}).get("broll_strategy") != "no_broll"
            _silence_mode = os.environ.get("VIRACLIP_SILENCE_MODE") or ("safe_trim" if _cfg.beta_clean else "metadata")
            _silence_plan_obj = _build_silence_edit_plan(
                word_timestamps=words_with_confidence or None,
                text=segment.get("text", ""),
                clip_duration=duration,
                editorial_type=segment.get("editorial_type"),
                hook_plan=_hook_plan_data,
                broll_events=[],
                subtitle_terms=list((_editing_plan_data or {}).get("highlighted_terms") or []) + list((_hook_plan_data or {}).get("emphasis_words") or []),
                mode=_silence_mode,
                enabled=True,
            )
            _fluency_media_cuts: List[Dict[str, Any]] = []
            try:
                _fluency_edits = list((_fluency_edit_plan or {}).get("edits") or [])
                _fluency_total_cut = 0.0
                if _fluency_edits and len(_fluency_edits) <= 4:
                    for _edit in _fluency_edits:
                        _raw_start = float((_edit or {}).get("start_s") or 0.0)
                        _raw_end = float((_edit or {}).get("end_s") or _raw_start)
                        _rel_start = _raw_start - start_seconds if _raw_start >= start_seconds else _raw_start
                        _rel_end = _raw_end - start_seconds if _raw_end >= start_seconds else _raw_end
                        _rel_start = max(0.0, min(float(duration or 0.0), _rel_start))
                        _rel_end = max(_rel_start, min(float(duration or 0.0), _rel_end))
                        _removed = round(max(0.0, _rel_end - _rel_start), 3)
                        if _removed < 0.08:
                            continue
                        if _fluency_total_cut + _removed > 3.0:
                            break
                        _fluency_media_cuts.append({
                            "start_s": round(_rel_start, 3),
                            "end_s": round(_rel_end, 3),
                            "removed_s": _removed,
                            "target_duration_s": 0.0,
                            "pause_start_s": round(_rel_start, 3),
                            "pause_end_s": round(_rel_end, 3),
                            "pause_type": "fluency_edit",
                            "action": "cut",
                            "reason": str((_edit or {}).get("reason") or (_edit or {}).get("type") or "fluency_cleanup"),
                        })
                        _fluency_total_cut = round(_fluency_total_cut + _removed, 3)
                    if _fluency_media_cuts:
                        _silence_plan_obj.cuts = sorted(
                            list(_silence_plan_obj.cuts or []) + _fluency_media_cuts,
                            key=lambda item: float(item.get("start_s", 0.0) or 0.0),
                        )
                        _silence_plan_obj.offset_map = _build_silence_offset_map(_silence_plan_obj.cuts)
                        _silence_plan_obj.total_removed_s = round(
                            sum(float(cut.get("removed_s", 0.0) or 0.0) for cut in _silence_plan_obj.cuts),
                            3,
                        )
                        _silence_plan_obj.summary["fluency_cuts_added"] = len(_fluency_media_cuts)
                elif _fluency_edits:
                    logger.info(
                        "[editorial-rhythm] clip rejected reason=too_fragmented_after_fluency_edit cuts=%d",
                        len(_fluency_edits),
                    )
            except Exception as _fluency_cut_e:
                logger.debug("[fluency-edit] media_cut_bridge_skipped reason=%s", _fluency_cut_e)
            try:
                _rhythm_status_hint = str((_publishable_metadata or {}).get("private_premium_status") or "")
                if not _rhythm_status_hint:
                    _rhythm_complete_idea = float(segment.get("complete_idea_score") or 1.0)
                    _rhythm_fluency = float(segment.get("fluency_score_after") or ((_fluency_edit_plan or {}).get("fluency_score_after") if _fluency_edit_plan else 1.0) or 1.0)
                    _rhythm_content_quality = str(segment.get("content_quality_label") or "")
                    _rhythm_hook_score = int((_hook_plan_data or {}).get("hook_first3_score") or 0)
                    _rhythm_hook_fit_ok = bool((_hook_plan_data or {}).get("hook_fit_acceptable"))
                    if _rhythm_content_quality == "reject" or _rhythm_complete_idea < 0.75 or _rhythm_fluency < 0.70:
                        _rhythm_status_hint = "DO_NOT_UPLOAD"
                    elif _rhythm_hook_score < 5 and not _rhythm_hook_fit_ok:
                        _rhythm_status_hint = "PRIVATE_PREMIUM_REVIEW"
                    else:
                        _rhythm_status_hint = "PRIVATE_PREMIUM_READY"
                _shot_rhythm_metadata = _build_shot_rhythm_decision(
                    segment_text=str(segment.get("text") or ""),
                    hook_intent=str((_hook_plan_data or {}).get("hook_intent") or segment.get("editorial_type") or ""),
                    composition_mode=str((_composition_decision or {}).get("composition_mode") or "minimal_safe"),
                    fluency_plan=_fluency_edit_plan or {},
                    silence_plan=_silence_plan_obj.to_dict(),
                    motion_pack_profile=str((_hook_plan_data or {}).get("motion_pack_profile") or (_hook_plan_data or {}).get("visual_profile") or ""),
                    sfx_retention_decision={},
                    broll_editorial_decision={},
                    private_premium_status=_rhythm_status_hint,
                    first3_visual_contract={},
                )
                _shot_microcuts = list((_shot_rhythm_metadata or {}).get("microcuts") or [])
                if _shot_microcuts:
                    _existing_cuts = list(_silence_plan_obj.cuts or [])
                    _existing_ranges = [
                        (
                            float(item.get("start_s") or 0.0),
                            float(item.get("end_s") or float(item.get("start_s") or 0.0)),
                        )
                        for item in _existing_cuts
                    ]
                    _added_microcuts = 0
                    for _cut in _shot_microcuts[:3]:
                        _c_start = float(_cut.get("start_s") or 0.0)
                        _c_end = float(_cut.get("end_s") or _c_start)
                        if _c_end <= _c_start:
                            continue
                        if any(_c_start < _e and _c_end > _s for _s, _e in _existing_ranges):
                            continue
                        _existing_cuts.append({
                            "start_s": round(_c_start, 3),
                            "end_s": round(_c_end, 3),
                            "removed_s": round(max(0.0, _c_end - _c_start), 3),
                            "target_duration_s": 0.0,
                            "pause_start_s": round(_c_start, 3),
                            "pause_end_s": round(_c_end, 3),
                            "pause_type": "shot_rhythm_microcut",
                            "action": "cut",
                            "reason": str(_cut.get("reason") or "shot_rhythm_microcut"),
                        })
                        _existing_ranges.append((_c_start, _c_end))
                        _added_microcuts += 1
                    if _added_microcuts:
                        _silence_plan_obj.cuts = sorted(
                            _existing_cuts,
                            key=lambda item: float(item.get("start_s", 0.0) or 0.0),
                        )
                        _silence_plan_obj.offset_map = _build_silence_offset_map(_silence_plan_obj.cuts)
                        _silence_plan_obj.total_removed_s = round(
                            sum(float(cut.get("removed_s", 0.0) or 0.0) for cut in _silence_plan_obj.cuts),
                            3,
                        )
                        _silence_plan_obj.summary["shot_rhythm_microcuts_added"] = _added_microcuts
                        _shot_rhythm_metadata["microcuts_applied_count"] = _added_microcuts
                        _shot_rhythm_metadata["applied"] = True
                    else:
                        _shot_rhythm_metadata["applied"] = bool((_shot_rhythm_metadata or {}).get("preserved_pauses"))
                else:
                    _shot_rhythm_metadata["applied"] = bool((_shot_rhythm_metadata or {}).get("preserved_pauses"))
                logger.info("[shot-rhythm] runtime_connected=true")
            except Exception as _shot_rhythm_e:
                logger.debug("[shot-rhythm] skipped reason=%s", _shot_rhythm_e)
                _shot_rhythm_metadata = {
                    "should_apply_rhythm": False,
                    "rhythm_profile": "no_rhythm_needed",
                    "microcuts": [],
                    "preserved_pauses": [],
                    "pattern_interruptions": [],
                    "pacing_score_before": 0.0,
                    "pacing_score_after_estimate": 0.0,
                    "applied": False,
                    "reason": f"shot_rhythm_failed:{_shot_rhythm_e}",
                }
            _silence_edit_plan_data = _silence_plan_obj.to_dict()
            _silence_edit_plan_data["shot_rhythm"] = _shot_rhythm_metadata
            _silence_out = output_path.with_name(f"silence_{output_path.name}")
            _silence_input = output_path
            _silence_result = _apply_silence_edit_plan(output_path, _silence_out, _silence_plan_obj, duration)
            if _fluency_media_cuts:
                logger.info(
                    "[fluency-edit] applied=%s removed_seconds=%.2f cuts=%d",
                    str(bool(_silence_result.get("rendered"))).lower(),
                    sum(float(cut.get("removed_s", 0.0) or 0.0) for cut in _fluency_media_cuts),
                    len(_fluency_media_cuts),
                )
                logger.info(
                    "[fluency-edit] media_applied=%s removed_seconds=%.2f",
                    str(bool(_silence_result.get("rendered"))).lower(),
                    sum(float(cut.get("removed_s", 0.0) or 0.0) for cut in _fluency_media_cuts),
                )
            elif (_fluency_edit_plan or {}).get("fluency_edit_applied"):
                logger.info("[fluency-edit] media_applied=false reason=no_safe_cuts")
            _silence_edit_plan_data["rendered"] = bool(_silence_result.get("rendered"))
            _silence_edit_plan_data["output_path"] = _silence_result.get("output_path")
            _silence_edit_plan_data["apply_warnings"] = list(_silence_result.get("warnings") or [])
            if _silence_result.get("rendered") and Path(_silence_result.get("output_path", "")).exists():
                output_path = Path(_silence_result["output_path"])
                _log_premium_pipeline_step("silence", _silence_input, output_path)
                _offset_map = list(_silence_edit_plan_data.get("offset_map") or [])
                try:
                    words_with_confidence = _remap_silence_words(words_with_confidence or [], _offset_map)
                    _editing_plan_data["smart_zoom_events"] = _remap_silence_events(_editing_plan_data.get("smart_zoom_events") or [], _offset_map)
                    _editing_plan_data["emphasis_moments"] = _remap_silence_events(_editing_plan_data.get("emphasis_moments") or [], _offset_map)
                    _hook_plan_data = _remap_silence_hook_plan(_hook_plan_data, _offset_map)
                    _editing_plan_data["hook_plan"] = _hook_plan_data
                    duration = round(max(0.0, float(duration or 0.0) - float(_silence_edit_plan_data.get("total_removed_s") or 0.0)), 3)
                    logger.info(
                        "[silence-remap] words=%d events=%d",
                        len(words_with_confidence or []),
                        len(_editing_plan_data.get("smart_zoom_events") or []),
                    )
                    logger.info("[silence-subtitles] remapped=true")
                    if _hook_plan_data:
                        logger.info("[silence-hook] action=remapped hook_type=%s", _hook_plan_data.get("hook_type"))
                except Exception as _remap_e:
                    _silence_edit_plan_data.setdefault("warnings", []).append("silence_remap_failed")
                    logger.warning("[silence-remap] failed fallback=metadata reason=%s", _remap_e)
            else:
                if _silence_edit_plan_data.get("mode") == "safe_trim" and _silence_edit_plan_data.get("cuts"):
                    _silence_edit_plan_data.setdefault("warnings", []).append("silence_trim_failed")
            _density_preflight = _assess_visual_density(
                editing_plan=_editing_plan_data,
                broll_events=[],
                subtitle_highlight_count=len((_editing_plan_data or {}).get("highlighted_terms") or []),
                watermark_applied=True,
            )
            if _density_preflight.get("smart_zoom_events") != _editing_plan_data.get("smart_zoom_events"):
                _editing_plan_data["smart_zoom_events"] = _density_preflight.get("smart_zoom_events", [])
                _hook_zoom_event = (_hook_plan_data or {}).get("zoom_event")
                if (
                    (_hook_plan_data or {}).get("hook_type") == "emotional_hook"
                    and _hook_zoom_event
                    and not any((event or {}).get("hook") for event in (_editing_plan_data.get("smart_zoom_events") or []))
                ):
                    _editing_plan_data["smart_zoom_events"] = [_hook_zoom_event] + list(_editing_plan_data.get("smart_zoom_events") or [])
                    logger.info("[emotional-hook] density_guard_restored_hook_event=true")
            _editing_plan_data["visual_density_score"] = _density_preflight.get("visual_density_score")
            _editing_plan_data["visual_density_warnings"] = _density_preflight.get("visual_density_warnings", [])
            _editing_plan_data["silence_edit_plan"] = _silence_edit_plan_data
            _editing_plan_data["shot_rhythm"] = _shot_rhythm_metadata
            _smart_reframe_metadata = _SmartReframeService().apply(
                output_path,
                output_path.with_name(f"reframe_{output_path.name}"),
                _editing_plan_data,
                has_broll=bool(_planned_has_broll),
            )
            _editing_plan_data["smart_reframe"] = _smart_reframe_metadata
            if _hook_plan_data:
                _hook_plan_data["rendered"] = bool(
                    _smart_reframe_metadata.get("rendered")
                    and any((event or {}).get("hook") for event in (_smart_reframe_metadata.get("events") or []))
                )
                logger.info(
                    "[hook-render] treatment=%s intent=%s style=%s generic_fallback=%s rendered=%s method=%s",
                    _hook_plan_data.get("visual_treatment"),
                    _hook_plan_data.get("hook_intent") or "unknown",
                    _hook_plan_data.get("hook_style") or "unknown",
                    str((_hook_plan_data.get("hook_intent") in {"", None, "unknown"}) or (_hook_plan_data.get("hook_style") in {"", None})).lower(),
                    str(_hook_plan_data["rendered"]).lower(),
                    _smart_reframe_metadata.get("reason") or _smart_reframe_metadata.get("method") or "smart_reframe",
                )
                if not _hook_plan_data["rendered"] and _hook_plan_data.get("enabled"):
                    _hook_plan_data.setdefault("warnings", []).append("hook_render_failed_or_skipped")
                _editing_plan_data["hook_plan"] = _hook_plan_data
            if _smart_reframe_metadata.get("rendered") and Path(_smart_reframe_metadata.get("output_path", "")).exists():
                _reframe_input = output_path
                output_path = Path(_smart_reframe_metadata["output_path"])
                _log_premium_pipeline_step("hook", _reframe_input, output_path)
            if (
                _hook_plan_data
                and _hook_plan_data.get("hook_type") == "emotional_hook"
                and _hook_plan_data.get("enabled")
                and not _hook_plan_data.get("rendered")
                and _hook_plan_data.get("zoom_event")
            ):
                _dynamic_reason = _smart_reframe_metadata.get("reason") or _smart_reframe_metadata.get("method") or "unknown"
                logger.info("[emotional-hook] dynamic_failed reason=%s", _dynamic_reason)
                _emotional_hook_out = output_path.with_name(f"emotional_hook_{output_path.name}")
                _emotional_fallback = _SmartReframeService().apply_static_hook_push_in(
                    output_path,
                    _emotional_hook_out,
                    _hook_plan_data.get("zoom_event") or {},
                )
                if _emotional_fallback.get("rendered") and Path(_emotional_fallback.get("output_path", "")).exists():
                    output_path = Path(_emotional_fallback["output_path"])
                    _hook_plan_data["rendered"] = True
                    _hook_plan_data["hook_motion_rendered"] = True
                    _hook_plan_data["hook_motion_method"] = "fallback_static_push_in"
                    _hook_plan_data["hook_motion_strength"] = "subtle"
                    _fallback_event = (_emotional_fallback.get("events") or [_hook_plan_data.get("zoom_event") or {}])[0]
                    _hook_plan_data["hook_motion_start_s"] = float((_fallback_event or {}).get("start_s", 0.0) or 0.0)
                    _hook_plan_data["hook_motion_duration_s"] = float((_fallback_event or {}).get("duration_s", 0.0) or 0.0)
                    _hook_plan_data.setdefault("warnings", []).append("emotional_hook_dynamic_fallback")
                    logger.info("[emotional-hook] fallback_static_push_in applied=true output=%s", output_path)
                    logger.info(
                        "[hook-render] treatment=emotional_push_in intent=%s style=%s generic_fallback=false rendered=true method=fallback_static_push_in",
                        _hook_plan_data.get("hook_intent") or "emotional_closure",
                        _hook_plan_data.get("hook_style") or "soft_cinematic_push",
                    )
                else:
                    _hook_plan_data["hook_motion_rendered"] = False
                    _hook_plan_data["hook_motion_method"] = "none"
                    _hook_plan_data.setdefault("warnings", []).append("emotional_hook_visual_weak")
            if _hook_plan_data and _hook_plan_data.get("hook_headline_overlay"):
                _overlay_out = output_path.with_name(f"hook_overlay_{output_path.name}")
                _overlay_result = _apply_hook_headline_overlay(
                    output_path,
                    _overlay_out,
                    _hook_plan_data.get("hook_headline_overlay") or {},
                )
                _hook_plan_data["overlay_rendered"] = bool(_overlay_result.get("rendered"))
                _hook_plan_data["overlay_text"] = _overlay_result.get("text") or _hook_plan_data.get("overlay_text")
                _hook_plan_data["overlay_start_s"] = _overlay_result.get("start_s") or _hook_plan_data.get("overlay_start_s")
                _hook_plan_data["overlay_duration_s"] = _overlay_result.get("duration_s") or _hook_plan_data.get("overlay_duration_s")
                _hook_plan_data["overlay_warnings"] = list(_overlay_result.get("warnings") or [])
                if _overlay_result.get("rendered") and Path(_overlay_result.get("output_path", "")).exists():
                    output_path = Path(_overlay_result["output_path"])
                elif _hook_plan_data.get("enabled"):
                    _hook_plan_data.setdefault("warnings", []).append("hook_overlay_skipped")
            if _hook_plan_data and _hook_plan_data.get("kickframe_event"):
                _hook_zoom_rendered = bool(
                    _smart_reframe_metadata.get("rendered")
                    and any((event or {}).get("hook") for event in (_smart_reframe_metadata.get("events") or []))
                )
                if _hook_zoom_rendered and (_hook_plan_data.get("kickframe_event") or {}).get("integrated_with_zoom"):
                    _hook_plan_data["kickframe_applied"] = True
                    logger.info("[hook-kickframe] applied=true start=%.2f dur=%.2f scale=%.3f",
                                float((_hook_plan_data["kickframe_event"] or {}).get("start_s", 0.0)),
                                float((_hook_plan_data["kickframe_event"] or {}).get("duration_s", 0.0)),
                                float((_hook_plan_data["kickframe_event"] or {}).get("scale", 1.0)))
                else:
                    _kick_out = output_path.with_name(f"hook_kick_{output_path.name}")
                    _kick_result = _apply_hook_kickframe(output_path, _kick_out, _hook_plan_data.get("kickframe_event") or {})
                    _hook_plan_data["kickframe_applied"] = bool(_kick_result.get("rendered"))
                    if _kick_result.get("event"):
                        _hook_plan_data["kickframe_event"] = _kick_result.get("event")
                    if _kick_result.get("rendered") and Path(_kick_result.get("output_path", "")).exists():
                        output_path = Path(_kick_result["output_path"])
                    else:
                        _hook_plan_data.setdefault("warnings", []).append("hook_kickframe_skipped")
            if _hook_plan_data:
                _hook_signal_types = []
                if _hook_plan_data.get("rendered"):
                    _hook_signal_types.append(str(_hook_plan_data.get("visual_treatment") or "hook_zoom"))
                    if _hook_plan_data.get("hook_type") == "emotional_hook":
                        _hook_plan_data["hook_motion_rendered"] = True
                        if _hook_plan_data.get("hook_motion_method") in {None, "", "none", "planned"}:
                            _hook_plan_data["hook_motion_method"] = _smart_reframe_metadata.get("method") or "smart_reframe"
                        if _hook_plan_data.get("hook_motion_strength") in {None, "", "none"}:
                            _hook_plan_data["hook_motion_strength"] = "subtle"
                        _hook_plan_data["hook_motion_start_s"] = float(((_hook_plan_data.get("zoom_event") or {}).get("start_s")) or 0.0)
                        _hook_plan_data["hook_motion_duration_s"] = float(((_hook_plan_data.get("zoom_event") or {}).get("duration_s")) or 0.0)
                if _hook_plan_data.get("overlay_rendered"):
                    _hook_signal_types.append("headline_overlay")
                if _hook_plan_data.get("kickframe_applied"):
                    _hook_signal_types.append("kickframe")
                if _hook_plan_data.get("emphasis_words"):
                    _hook_signal_types.append("subtitle_highlight")
                _hook_plan_data["rendered"] = bool(
                    _hook_plan_data.get("rendered")
                    or _hook_plan_data.get("overlay_rendered")
                    or _hook_plan_data.get("kickframe_applied")
                    or _hook_plan_data.get("emphasis_words")
                )
                _hook_plan_data["hook_visual_signal_types"] = list(dict.fromkeys(_hook_signal_types))
                _hook_plan_data["hook_visual_signal_count"] = len(_hook_plan_data["hook_visual_signal_types"])
                _first4_signals = list(_hook_plan_data.get("hook_first_4s_signals") or [])
                for _signal in _hook_plan_data["hook_visual_signal_types"]:
                    if _signal not in _first4_signals:
                        _first4_signals.append(_signal)
                if _hook_plan_data.get("enabled") and not _first4_signals:
                    _first4_signals.append("safe_speaker_focus")
                _hook_plan_data["hook_first_4s_signals"] = _first4_signals
                _hook_plan_data["hook_first_4s_score"] = len(_first4_signals)
                _hook_plan_data["hook_contract_satisfied"] = (
                    _hook_plan_data.get("hook_type") == "weak_intro"
                    or _hook_plan_data["hook_visual_signal_count"] > 0
                )
                if _hook_plan_data.get("hook_type") == "emotional_hook" and duration > 10.0:
                    _speaker_focus_strong = bool((_silence_edit_plan_data or {}).get("total_removed_s")) and any(
                        float((cut or {}).get("start_s", (cut or {}).get("start", 99.0)) or 99.0) < 2.0
                        for cut in ((_silence_edit_plan_data or {}).get("cuts") or [])
                    )
                    _motion_ok = bool(_hook_plan_data.get("hook_motion_rendered"))
                    if not (_motion_ok or _speaker_focus_strong):
                        _hook_plan_data["hook_contract_satisfied"] = False
                        _hook_plan_data["hook_disabled_reason"] = "emotional_hook_visual_weak"
                        _hook_plan_data.setdefault("warnings", []).append("emotional_hook_visual_weak")
                    elif _speaker_focus_strong and not _motion_ok:
                        _hook_plan_data["hook_motion_strength"] = "none"
                        _hook_plan_data["hook_motion_method"] = "speaker_focus_strong"
                if (
                    _hook_plan_data.get("enabled")
                    and _hook_plan_data.get("hook_type") != "weak_intro"
                    and int(_hook_plan_data.get("hook_first_4s_score") or 0) < 2
                ):
                    _hook_plan_data.setdefault("warnings", []).append("weak_first_4_seconds")
                if _hook_plan_data.get("enabled") and not _hook_plan_data["hook_contract_satisfied"]:
                    _hook_plan_data["hook_disabled_reason"] = "hook_visual_missing"
                    _hook_plan_data.setdefault("warnings", []).append("hook_visual_missing")
                logger.info(
                    "[hook-contract] type=%s satisfied=%s signals=%s",
                    _hook_plan_data.get("hook_type"),
                    str(bool(_hook_plan_data.get("hook_contract_satisfied"))).lower(),
                    "|".join(_hook_plan_data.get("hook_visual_signal_types") or []) or "none",
                )
                logger.info(
                    "[hook-first4] satisfied=%s signals=%s",
                    str(
                        _hook_plan_data.get("hook_type") == "weak_intro"
                        or int(_hook_plan_data.get("hook_first_4s_score") or 0) >= 2
                    ).lower(),
                    "|".join(_hook_plan_data.get("hook_first_4s_signals") or []) or "none",
                )
                _editing_plan_data["hook_plan"] = _hook_plan_data
        except Exception as _plan_e:
            logger.warning("[editing-plan] failed metadata_only=true error=%s", _plan_e)
            _editing_plan_data = {"error": str(_plan_e), "metadata_only": True}
            _hook_plan_data = {"error": str(_plan_e), "metadata_only": True}
            _silence_edit_plan_data = {"error": str(_plan_e), "metadata_only": True, "warnings": ["silence_metadata_only"]}

        # Step 4.3: B-Roll overlay — after EP so vignette/LUT don't darken B-roll.
        # [beta-clean] Skipped when VIRACLIP_BETA_CLEAN=true (unless editorial B-roll is enabled).
        _broll_editorial_decision: Dict[str, Any] = {}
        _broll_asset_match: Dict[str, Any] = {}
        _broll_editorial_opportunity = False
        _broll_editorial_fallback = "none"
        _broll_composition_allowed = True
        _editorial_broll_mode = _cfg.beta_clean and _cfg.enable_editorial_broll and include_broll
        if _editorial_broll_mode:
            try:
                from .vpi_broll_intent import build_broll_editorial_decision as _build_broll_editorial_decision
                from .vpi_broll_intent import match_broll_asset as _match_broll_asset
                from .vpi_visual_effects_service import resolve_visual_layer_conflicts as _resolve_visual_layer_conflicts

                _broll_editorial_decision = _build_broll_editorial_decision(
                    segment_text=str(segment.get("text") or ""),
                    hook_intent=str((_hook_plan_data or {}).get("hook_intent") or segment.get("editorial_type") or ""),
                    topic=str(segment.get("editorial_type") or ""),
                    private_premium_status=str(_publishable_metadata.get("private_premium_status") or ""),
                    composition_decision=_composition_decision,
                    first3_visual_contract={},
                    visual_profile=str((_hook_plan_data or {}).get("visual_profile") or ""),
                )
                _broll_editorial_opportunity = bool(_broll_editorial_decision.get("should_use_broll"))
                _broll_editorial_fallback = str(_broll_editorial_decision.get("fallback") or "none")
                if _broll_editorial_opportunity:
                    _broll_asset_match = _match_broll_asset(
                        broll_intent=str(_broll_editorial_decision.get("broll_intent") or ""),
                        topic=str(segment.get("editorial_type") or ""),
                        segment_text=str(segment.get("text") or ""),
                    )
                    if not _broll_asset_match.get("matched"):
                        _editorial_broll_mode = False
                        _broll_editorial_decision["should_use_broll"] = False
                        _broll_editorial_decision["skip_reason"] = "no_assets"
                        logger.info("[broll-editorial] skipped reason=no_assets")
                    else:
                        _layers_for_broll = []
                        if bool((_hook_plan_data or {}).get("overlay_rendered")):
                            _layers_for_broll.append({"type": "hook_overlay", "start_s": 0.0, "duration_s": 1.2})
                        _layers_for_broll.append({
                            "type": "broll",
                            "start_s": float(_broll_editorial_decision.get("start_offset") or 1.8),
                            "duration_s": float(_broll_editorial_decision.get("duration") or 1.2),
                            "caption_text": str(segment.get("text") or ""),
                        })
                        _resolved_broll_layers = _resolve_visual_layer_conflicts(_layers_for_broll, _composition_decision or {})
                        _broll_composition_allowed = "broll" in list(_resolved_broll_layers.get("layers_final") or [])
                        logger.info(
                            "[broll-editorial] composition_allowed=%s reason=%s",
                            str(_broll_composition_allowed).lower(),
                            "allowed" if _broll_composition_allowed else "composition_conflict",
                        )
                        if not _broll_composition_allowed:
                            _editorial_broll_mode = False
                            _broll_editorial_decision["should_use_broll"] = False
                            _broll_editorial_decision["skip_reason"] = "composition_conflict"
                            logger.info("[broll-editorial] skipped reason=composition_conflict")
                else:
                    _editorial_broll_mode = False
                    _broll_editorial_decision["skip_reason"] = _broll_editorial_decision.get("skip_reason") or "no_editorial_gain"
            except Exception as _broll_decision_e:
                logger.debug("[broll-editorial] decision skipped reason=%s", _broll_decision_e)
                _broll_editorial_decision = {
                    "should_use_broll": False,
                    "broll_intent": "no_broll_needed",
                    "reason": "decision_failed",
                    "fallback": "none",
                    "skip_reason": "decision_failed",
                }
                _editorial_broll_mode = False
        logger.info(
            "[editorial-broll] gate beta_clean=%s enabled=%s include_broll=%s",
            str(_cfg.beta_clean).lower(),
            str(_cfg.enable_editorial_broll).lower(),
            str(include_broll).lower(),
        )
        if _editorial_broll_mode:
            logger.info("[editorial-broll] enabled in beta-clean safe mode")
            from .broll_service import BrollService
            _broll_svc = BrollService()
            _broll_out = output_path.with_name(f"broll_{output_path.name}")
            try:
                _broll_result = await _broll_svc.process_clip(
                    video_path=str(output_path),
                    output_path=str(_broll_out),
                    segment_text=segment.get("text", ""),
                    clip_duration=duration,
                    max_overlays=3,
                    overlay_duration_s=3.0,
                    words_with_timestamps=words_with_confidence or None,
                    precomputed_keywords=None,
                    broll_fade_s=0.6,
                    task_id=task_id,
                    suggested_broll_cue_type=segment.get("suggested_broll_cue_type"),
                    editorial_type=segment.get("editorial_type"),
                    vpi_score=segment.get("vpi_score"),
                    hook_broll_delay_until_s=float((_hook_plan_data or {}).get("broll_delay_until_s") or 0.0),
                )
                if Path(_broll_result).exists() and _broll_result != str(output_path):
                    _broll_input = output_path
                    output_path = Path(_broll_result)
                    _log_premium_pipeline_step("broll", _broll_input, output_path)
                    logger.info(f"  ✓ Editorial B-roll overlay applied")
                _editorial_broll_metadata = list(getattr(_broll_svc, "last_editorial_broll", []) or [])
                _broll_selection_stats = dict(getattr(_broll_svc, "_last_broll_selection_stats", {}) or {})
                if _editing_plan_data:
                    _editing_plan_data["has_broll"] = bool(_editorial_broll_metadata)
                    _editing_plan_data["broll_selection_stats"] = _broll_selection_stats
                    _editing_plan_data["broll_editorial_decision"] = _broll_editorial_decision
                    _editing_plan_data["broll_asset_match"] = _broll_asset_match
                    _editing_plan_data["broll_editorial_opportunity"] = bool(_broll_editorial_opportunity)
                    _editing_plan_data["broll_editorial_fallback"] = _broll_editorial_fallback
                    _editing_plan_data["broll_composition_allowed"] = bool(_broll_composition_allowed)
                    for _stat_key in (
                        "broll_no_broll_reason",
                        "broll_candidates_total",
                        "broll_candidates_rejected_forbidden",
                        "broll_candidates_rejected_cooldown",
                        "broll_candidates_rejected_relevance",
                        "broll_candidates_usable",
                    ):
                        if _stat_key in _broll_selection_stats:
                            _editing_plan_data[_stat_key] = _broll_selection_stats.get(_stat_key)
            except Exception as _broll_e:
                logger.warning(f"  Editorial B-roll overlay failed: {_broll_e}")
                _editorial_broll_metadata = []
                _broll_selection_stats = {}
                if _editing_plan_data:
                    _editing_plan_data["broll_editorial_decision"] = _broll_editorial_decision
                    _editing_plan_data["broll_asset_match"] = _broll_asset_match
                    _editing_plan_data["broll_editorial_opportunity"] = bool(_broll_editorial_opportunity)
                    _editing_plan_data["broll_editorial_fallback"] = _broll_editorial_fallback
                    _editing_plan_data["broll_composition_allowed"] = bool(_broll_composition_allowed)
        elif not _cfg.beta_clean:
            from ..config import get_config as _get_cfg_broll
            if _get_cfg_broll().broll_enabled:
                try:
                    from .broll_service import BrollService
                    _broll_svc = BrollService()
                    _broll_out = output_path.with_name(f"broll_{output_path.name}")
                    _broll_kw_override = (_clip_profile.ai_keywords
                                          if _clip_profile and _clip_profile.ai_keywords
                                          else None)
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
                        task_id=task_id,
                        hook_broll_delay_until_s=float((_hook_plan_data or {}).get("broll_delay_until_s") or 0.0),
                    )
                    if Path(_broll_result).exists() and _broll_result != str(output_path):
                        output_path = Path(_broll_result)
                        logger.info(f"  ✓ B-roll overlay applied (post-EP)")
                except Exception as _broll_e:
                    logger.warning(f"  B-roll overlay failed: {_broll_e}")
        else:
            logger.info(f"[beta-clean] B-roll overlay skipped (beta_clean mode)")
        if _editing_plan_data and "broll_editorial_decision" not in _editing_plan_data:
            _editing_plan_data["broll_editorial_decision"] = _broll_editorial_decision
            _editing_plan_data["broll_asset_match"] = _broll_asset_match
            _editing_plan_data["broll_editorial_opportunity"] = bool(_broll_editorial_opportunity)
            _editing_plan_data["broll_editorial_fallback"] = _broll_editorial_fallback
            _editing_plan_data["broll_composition_allowed"] = bool(_broll_composition_allowed)
        if _broll_editorial_opportunity:
            _broll_fulfilled = bool(locals().get("_editorial_broll_metadata") or [])
            logger.info(
                "[broll-editorial] opportunity=true fulfilled=%s fallback=%s",
                str(_broll_fulfilled).lower(),
                _broll_editorial_fallback,
            )

        # Step 4.3b: Contextual Overlay Engine — keyword→image/video overlays (viral TikTok feature)
        _ctx_overlays_env = os.environ.get("CONTEXTUAL_OVERLAYS_ENABLED", "true").lower() == "true"
        if _cfg.beta_clean:
            logger.info("[beta-clean] template text overlay skipped")
            logger.info("[beta-clean] top text overlay skipped")
        elif _ctx_overlays_env and segment and words_with_confidence:
            try:
                from .contextual_overlay_engine import ContextualOverlayEngine
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
                from ..video_processing.viral_effects import analyze_content_type_for_effects, get_effects_for_content
                _seg_text = segment.get("text", "") if segment else ""
                _content_type = analyze_content_type_for_effects(_seg_text)
                _fx_list = get_effects_for_content(_content_type)
                if _fx_list:
                    logger.info(f"  ✓ Viral effects profile: {_content_type} ({len(_fx_list)} effects queued)")
            except Exception as _vfx_e:
                logger.debug(f"  Viral effects skipped: {_vfx_e}")

        # Step 4.4: ASS Karaoke captions — after B-roll so text burns on top.
        if add_subtitles and words_with_confidence:
            # ── Timeline validation: clamp words that exceed video duration ──
            # After silence removal / jump cuts the word timestamps may exceed
            # the final video duration, causing desynchronised subtitles.
            _video_dur = VideoService._get_file_duration(output_path)
            if _video_dur is not None and _video_dur > 0:
                _before = len(words_with_confidence)
                _clamped = 0
                _dropped = 0
                for _w in words_with_confidence:
                    _ws = float(_w.get("start", 0))
                    _we = float(_w.get("end", _ws + 0.3))
                    # Clamp negative start times to 0
                    if _ws < 0:
                        _w["start"] = 0.0
                        _clamped += 1
                    # Drop words that start after the video ends
                    if _ws >= _video_dur:
                        _w["_drop"] = True
                        _dropped += 1
                        continue
                    # Clamp end time to video duration
                    if _we > _video_dur:
                        _w["end"] = _video_dur
                        _clamped += 1
                words_with_confidence = [w for w in words_with_confidence if not w.get("_drop")]
                _first_start = words_with_confidence[0].get("start", 0) if words_with_confidence else 0
                _last_end = words_with_confidence[-1].get("end", 0) if words_with_confidence else 0
                logger.info(
                    "[TIMELINE-VALIDATION] video_dur=%.2fs words=%d→%d "
                    "(clamped=%d dropped=%d) "
                    "first_word_start=%.2fs last_word_end=%.2fs",
                    _video_dur, _before, len(words_with_confidence),
                    _clamped, _dropped,
                    _first_start, _last_end,
                )
            else:
                logger.debug(
                    "[TIMELINE-VALIDATION] Could not determine video duration "
                    "for %s — skipping clamp", output_path.name,
                )

            try:
                from .caption_service import CaptionService as _CS, burn_captions as _burn_caps
                logger.info(f"  Burning ASS captions ({len(words_with_confidence)} words)...")
                _cap_style_raw = (_clip_profile.caption_style if _clip_profile else None) or _CS.style_for_template(caption_template, target_platform)
                _cap_style = "highlight" if _cap_style_raw == "minimal" else _cap_style_raw  # Nunca usar minimal - texto invisible
                subtitled_path = output_path.with_name(f"sub_{output_path.name}")
                _caption_decisions = {
                    "highlighted_terms": (_editing_plan_data or {}).get("highlighted_terms", []),
                    "hook_emphasis_words": (_hook_plan_data or {}).get("emphasis_words", []),
                    "hook_headline_text": (_hook_plan_data or {}).get("headline_text"),
                    "hook_subtitle_text": (_hook_plan_data or {}).get("subtitle_hook_text"),
                    "hook_type": (_hook_plan_data or {}).get("hook_type"),
                    "hook_intent": (_hook_plan_data or {}).get("hook_intent"),
                    "hook_first3_status": (_hook_plan_data or {}).get("hook_first3_status"),
                    "hook_first3_score": (_hook_plan_data or {}).get("hook_first3_score"),
                    "editorial_type": segment.get("editorial_type") or (_editing_plan_data or {}).get("editorial_type"),
                    "segment_text": segment.get("text") or "",
                    "composition_decision": _composition_decision,
                }
                _cap_ok = await _burn_caps(
                    output_path, subtitled_path,
                    words_with_confidence,
                    style=_cap_style,
                    platform=target_platform,
                    caption_decisions=_caption_decisions,
                )
                _caption_overlay_pack_metadata = dict(_caption_decisions.get("caption_overlay_pack") or {})
                if _cap_ok and subtitled_path.exists():
                    _caption_input = output_path
                    output_path = subtitled_path
                    _log_premium_pipeline_step("captions", _caption_input, output_path)
                    _caption_ass_debug_path = str(
                        Path(os.environ.get("CAPTION_DEBUG_DIR", "/app/temp/caption_debug"))
                        / f"{subtitled_path.stem}.ass"
                    )
                    logger.info(f"  ✓ ASS captions burned (style={_cap_style}, platform={target_platform})")
                else:
                    raise RuntimeError("caption_service returned False")
            except Exception as burn_e:
                if _cfg.beta_clean:
                    logger.error(
                        "[beta-clean] CaptionService.burn_captions failed (%s); "
                        "legacy subtitle fallback disabled",
                        burn_e,
                    )
                    logger.info("[beta-clean] legacy subtitle fallback disabled")
                    if "subtitled_path" in locals() and subtitled_path is not None:
                        subtitled_path.unlink(missing_ok=True)
                    subtitled_path = None
                else:
                    logger.warning(
                        "[LEGACY-FALLBACK] CaptionService.burn_captions failed (%s) — "
                        "falling back to VideoService._burn_subtitles_word_level (legacy ASS)",
                        burn_e,
                    )
                    try:
                        subtitled_path = output_path.with_name(f"sub_{output_path.name}")
                        await VideoService._burn_subtitles_word_level(
                            str(output_path), words_with_confidence, str(subtitled_path)
                        )
                        if subtitled_path.exists():
                            output_path = subtitled_path
                            logger.info(
                                "[LEGACY-FALLBACK] Legacy _burn_subtitles_word_level succeeded "
                                "for %s", subtitled_path.name,
                            )
                    except Exception as _fb_e:
                        logger.warning(
                            "[LEGACY-FALLBACK] Legacy subtitle fallback also failed: %s", _fb_e,
                        )

        # Step 4.7: ComfyUI GPU Enhancement — Real-ESRGAN upscaling (optional, GPU only)
        if COMFYUI_ENABLED:
            try:
                _cfy = ComfyUIBridge()
                _cfy_out = output_path.with_name(f"cfy_{output_path.name}")
                _cfy_result = await _cfy.enhance_video(output_path, _cfy_out)
                await _cfy.close()
                if _cfy_result and _cfy_out.exists():
                    output_path = _cfy_out
                    logger.info("  ✓ ComfyUI: GPU upscale (RealESRGAN x2)")
            except Exception as _cfy_e:
                logger.debug(f"  ComfyUI enhance skipped: {_cfy_e}")

        # Step 4.8: Sound Design (efectos de sonido virales)
        # [beta-clean] Skipped when VIRACLIP_BETA_CLEAN=true
        if not _cfg.beta_clean:
            try:
                sound_service = SoundDesignService()
                _emphasis_words = [
                    {"start": w["start"]}
                    for w in words_with_confidence
                    if w.get("is_emphasis") and 0 < w.get("start", 0) < duration
                ] if words_with_confidence else []
                virality_segments = [{
                    "start": 0,
                    "end": duration,
                    "hook_type": segment.get("hook_type", "insight_reveal"),
                    "text": segment.get("text", ""),
                    "emphasis_words": _emphasis_words,
                }]
                sound_cues = sound_service.get_sound_cues_from_virality(virality_segments)
                if sound_cues:
                    sound_path = output_path.with_name(f"sound_{output_path.name}")
                    await sound_service.inject_sound_effects(
                        str(output_path),
                        str(sound_path),
                        sound_cues
                    )
                    if Path(sound_path).exists():
                        output_path = sound_path
                        logger.info(f"  ✓ {len(sound_cues)} sound effects added")
            except Exception as sound_e:
                logger.warning(f"  Sound design failed: {sound_e}")
        else:
            logger.info(f"[beta-clean] Sound design skipped (beta_clean mode)")

        # Step 4.10: Platform export — only re-encode when burning hardsubs.
        # When no subtitle file exists use stream copy (near-instant, no quality loss).
        _sub_path = segment.get("colored_subtitle_path")
        if _sub_path and Path(str(_sub_path)).exists():
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
        if target_language and target_language != "eng":
            from .translation_service import TranslationService
            translator = TranslationService()
            dubbed_path = output_path.with_name(f"dubbed_{output_path.name}")
            await translator.dub_clip(output_path, dubbed_path, target_language)
            output_path = dubbed_path

        # Beat-synced BGM: use BeatSyncService (auto BPM match + adaptive ducking).
        # Falls back to niche-based static track when BGM library is empty.
        if not _cfg.beta_clean:
            try:
                from .beat_sync_service import get_beat_sync_service as _get_bs
                _music_out = output_path.with_name(f"music_{output_path.name}")
                _speech_segs = [
                    {"start": w["start"], "end": w.get("end", w["start"] + 0.3)}
                    for w in (words_with_confidence or [])[::3]
                ]
                _bs_result = await _get_bs().mix_bgm_beat_synced(
                    video_path=output_path,
                    output_path=_music_out,
                    speech_segments=_speech_segs,
                    bgm_volume=float(os.environ.get("BGM_VOLUME", "0.40")),  # Aumentado para audibilidad
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
                    from ..video_processing.audio import get_background_music_for_niche, mix_background_music as _mix_bg
                    from ..config import get_config as _get_cfg
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
        else:
            logger.info("  [beta-clean] Beat-synced BGM skipped (beta_clean mode)")

        # Step 4.10b: Audio Ducking — auto-lower BGM when speaker talks (sidechain)
        try:
            from .audio_ducking_service import get_audio_ducking_service
            _duck_svc = get_audio_ducking_service()
            if _duck_svc.enabled and words_with_confidence:
                _duck_out = output_path.with_name(f"duck_{output_path.name}")
                _duck_result = await _duck_svc.apply_ducking(
                    video_path=output_path,
                    output_path=_duck_out,
                    word_timings=words_with_confidence,
                )
                if _duck_result.success and _duck_out.exists():
                    _duck_out.replace(output_path)
                    logger.info(f"  ✓ Audio ducking applied ({_duck_result.ducked_segments} segments)")
        except Exception as _duck_e:
            logger.debug(f"  Audio ducking skipped: {_duck_e}")

        # Step 4.11: Pexels B-Roll overlay (Feature A — await prefetch task started at render launch)
        # Skip if Step 4.3 (BrollService) already applied B-roll — prevents double overlay.
        # [beta-clean] Skipped when VIRACLIP_BETA_CLEAN=true
        if not _cfg.beta_clean:
            _step43_ran = _get_cfg_broll().broll_enabled
            if _broll_prefetch_task is not None and not _step43_ran:
                try:
                    from .pexels_service import overlay_broll_on_clip
                    _broll_path = await asyncio.wait_for(_broll_prefetch_task, timeout=30.0)
                    if _broll_path:
                        _broll_out = output_path.with_name(f"broll_{output_path.name}")
                        ok = overlay_broll_on_clip(
                            output_path, _broll_path, _broll_out,
                            broll_start=0.3, broll_end=0.6,
                        )
                        if ok and _broll_out.exists():
                            _broll_out.replace(output_path)
                            logger.info(f"  ✓ Pexels B-Roll overlaid ({segment.get('theme', 'nature')})")
                    else:
                        logger.debug("  B-Roll prefetch returned no clip — skipping overlay")
                except asyncio.TimeoutError:
                    logger.warning("  WARNING: B-Roll prefetch timeout — skipping")
                    _broll_prefetch_task.cancel()
                except Exception as _br_e:
                    logger.warning(f"  Pexels B-Roll skipped: {_br_e}")
        else:
            logger.info(f"[beta-clean] Pexels B-roll overlay skipped (beta_clean mode)")

        logger.info(f"Created clip {clip_index + 1}: {duration:.1f}s")

        # ClipValidator: post-render A/V sync + quality check
        try:
            from .clip_validator import get_clip_validator
            _cv = get_clip_validator()
            _cv_report = await _cv.validate_output(
                output_path,
                expected_duration=duration,
                words=words_with_confidence,
            )
            if not _cv_report.get("valid", True):
                logger.warning(f"  ⚠ ClipValidator issues: {_cv_report.get('issues', [])}")
            else:
                logger.debug(f"  ✓ ClipValidator passed")
        except Exception as _cv_e:
            logger.debug(f"  ClipValidator skipped: {_cv_e}")

        # Phase 3.5: Hook slow-motion (opt-in via HOOK_SLOWMO_ENABLED=true)
        try:
            from ..video_processing.hook_slowmo import maybe_apply_hook_slowmo
            _sm_applied = maybe_apply_hook_slowmo(
                output_path,
                virality_score=segment.get("virality_score", 0),
                inplace=True,
            )
            if _sm_applied:
                logger.info(f"  ↳ Hook slo-mo applied to clip {clip_index + 1}")
        except Exception as _sm_e:
            logger.debug(f"  Hook slo-mo skipped: {_sm_e}")

        # ── V4 Elite: Visual scoring + Scene rhythm ──────────────────────
        text_virality = segment.get("virality_score", 0)
        final_virality = text_virality
        vision_data: dict = {}
        rhythm_data: dict = {}

        # Scene rhythm analysis (PySceneDetect — always runs, no GPU needed)
        try:
            from ..utils.scene_analysis import analyze_clip_rhythm, detect_loop_potential
            rhythm_data = analyze_clip_rhythm(output_path)
            loop_data = detect_loop_potential(output_path)
            rhythm_data.update(loop_data)
        except Exception as e:
            logger.debug(f"Scene analysis skipped: {e}")

        # ViralityEngine: unified hook+pacing+emotion+phi3 score (replaces manual blend)
        if not _cfg.beta_clean:
            try:
                from .virality_engine import get_virality_engine
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
        else:
            logger.info("[beta-clean] ViralityEngine disabled")

        # Visual scoring via Ollama + Qwen3-VL (GPU optional, graceful fallback)
        if not _cfg.beta_clean:
            try:
                from ..config import get_config
                cfg = get_config()
                if getattr(cfg, "vision_analysis_enabled", True):
                    from .vision_service import analyze_clip_visually, blend_with_text_score
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
        else:
            logger.info("[beta-clean] Vision scoring disabled")

        # Thumbnail: Qwen3-VL quality scoring → pick best among 5 candidate frames
        thumbnail_filename = None
        if not _cfg.beta_clean:
            try:
                from ..config import get_config
                cfg = get_config()
                if getattr(cfg, "vision_analysis_enabled", True):
                    from .vision_service import score_thumbnail_frame
                    from ..utils.scene_analysis import extract_representative_frames
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
        else:
            logger.info("[beta-clean] AI thumbnail generation disabled")
            # Fallback: sharpness-based smart thumbnail (always runs)
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
        if os.environ.get("AI_THUMBNAIL_ENABLED", "true").lower() == "true" and not _cfg.beta_clean:
            try:
                from .ai_thumbnail_service import AIThumbnailService, ThumbnailStyle
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
        elif _cfg.beta_clean:
            logger.info("[beta-clean] AI thumbnail variants disabled")

        # Viral metadata: LLM-generated hashtags + SEO title
        viral_meta: dict = {}
        if not _cfg.beta_clean:
            try:
                viral_meta = await generate_viral_metadata(
                    text=segment.get("text", ""),
                    platform=target_platform,
                )
                logger.info(
                    f"  ✓ Viral metadata: '{viral_meta.get('title', '')}' "
                    f"({len(viral_meta.get('hashtags', []))} hashtags)"
                )
            except Exception as _vm_e:
                logger.debug(f"  Viral metadata skipped: {_vm_e}")
        else:
            logger.info("[beta-clean] Viral metadata LLM disabled")

        # Phase 8.3: LSTM/CNN engagement prediction (drop-off curve)
        engagement_data: dict = {}
        if not _cfg.beta_clean:
            try:
                from .engagement_prediction_service import get_engagement_predictor
                import asyncio as _asyncio
                _predictor = get_engagement_predictor()
                _loop = _asyncio.get_event_loop()
                _eng = await _loop.run_in_executor(
                    None,
                    lambda: _predictor.predict_engagement_curve(
                        words=words_with_confidence,
                        audio_features=audio_features,
                        duration=duration,
                    ),
                )
                engagement_data = {
                    "engagement_curve":   _eng["curve"],
                    "drop_off_points":    _eng["drop_off_points"],
                    "hook_insertion_pts": _eng["hook_points"],
                    "retention_score":    _eng["retention_score"],
                    "engagement_method":  _eng["predicted_by"],
                }
                logger.info(
                    f"  ✓ Engagement curve [{_eng['predicted_by']}]: "
                    f"retention={_eng['retention_score']}% "
                    f"drop-offs={_eng['drop_off_points']}"
                )
            except Exception as _ep_e:
                logger.debug(f"  Engagement prediction skipped: {_ep_e}")
        else:
            logger.info("[beta-clean] Engagement prediction disabled")

        # ── Recommendation Engine — personalized suggestions per user ─────
        _recommendations: list = []
        try:
            from .recommendation_engine import get_recommendation_engine
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
                from .social_publisher import publish_to_all, PublishRequest, Platform as SocialPlatform
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
        # ── Quality Validator — criterios de calidad antes de entregar ──────
        _quality_report: dict = {}
        try:
            from .quality_validator import validate_clip
            _qr = validate_clip(
                clip_path=output_path,
                clip_info={"duration": duration, "virality_score": final_virality},
            )
            _quality_report = {
                "quality_level": _qr.quality_level.value if hasattr(_qr.quality_level, "value") else str(_qr.quality_level),
                "passed": _qr.passed,
                "issues": [c.message for c in _qr.checks if not c.passed],
            }
            if not _qr.passed:
                logger.warning(f"  ⚠ Quality issues: {_quality_report['issues'][:2]}")
            else:
                logger.debug(f"  ✓ Quality: {_quality_report['quality_level']}")
        except Exception as _qval_e:
            logger.debug(f"  QualityValidator skipped: {_qval_e}")

        # ── Audio Recommendation — sugerir música ideal para este clip ────
        _audio_recs: list = []
        try:
            from .audio_recommendation import recommend_music_for_video
            _arecs = await recommend_music_for_video(output_path, count=3)
            _audio_recs = [
                {"title": r.title, "genre": r.genre.value if hasattr(r.genre, "value") else str(r.genre), "mood": r.mood, "bpm": r.bpm}
                for r in _arecs[:3]
            ]
            if _audio_recs:
                logger.debug(f"  ✓ Audio recs: {[r['title'] for r in _audio_recs]}")
        except Exception as _arec_e:
            logger.debug(f"  Audio recommendation skipped: {_arec_e}")

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

        # ── Clip Health Service — reporte accionable de salud del clip ─────
        _clip_health: dict = {}
        try:
            from .clip_health_service import generate_health_report
            _health_report = generate_health_report(
                clip_id=str(clip_index + 1),
                virality_score=final_virality,
                hook_score=segment.get("hook_score") if segment else None,
                hook_type=segment.get("hook_type") if segment else None,
                duration=duration,
                platform=target_platform,
                has_subtitles=bool(segment and segment.get("text")),
                hashtag_count=len(viral_meta.get("hashtags", [])),
                zoom_punch_applied=bool(os.environ.get("CUT_ZOOM_ENABLED", "true") == "true"),
            )
            _clip_health = _health_report.to_dict()
            if _clip_health.get("grade") in ("D", "F"):
                logger.warning(f"  ⚠ Clip health grade={_clip_health['grade']} top_fix={_clip_health.get('top_fix','')}")
            else:
                logger.info(f"  ✓ Clip health grade={_clip_health.get('grade','?')} score={_clip_health.get('overall_score',0):.0f}")
        except Exception as _ch_e:
            logger.debug(f"  Clip health skipped: {_ch_e}")
        # ─────────────────────────────────────────────────────────────────

        # VPI Daily Publishing: safe branding, output QC and publishable status.
        _brand_metadata: dict = {}
        _output_qc: dict = {}
        _publishable_metadata: dict = {}
        _subtitle_intelligence_metadata: dict = {}
        _caption_overlay_pack_metadata: dict = {}
        _music_metadata: dict = {}
        _sfx_metadata: dict = {}
        _visual_effects_metadata: dict = {}
        _cinematic_finish_metadata: dict = {}
        _transition_metadata: dict = {}
        _speaker_focus_metadata: dict = {}
        _editing_richness_metadata: dict = {}
        try:
            from .vpi_branding_service import apply_vpi_branding as _apply_vpi_branding
            from .vpi_branding_service import find_brand_asset as _find_brand_asset
            from .vpi_editing_plan import assess_visual_density as _assess_visual_density
            from .vpi_editing_plan import determine_publishable_status as _determine_publishable_status
            from .vpi_editing_plan import extend_output_qc_visual as _extend_output_qc_visual
            from .vpi_editing_plan import probe_output_qc as _probe_output_qc

            _repo_root = Path(__file__).resolve().parents[3]
            _brand_asset = _find_brand_asset(_repo_root)
            _brand_metadata = {
                "logo_found": bool(_brand_asset),
                "logo_path": str(_brand_asset) if _brand_asset else None,
                "rendered": False,
                "type": "pending_after_transitions",
            }

            _editorial_broll_for_status = locals().get("_editorial_broll_metadata", []) or []
            _broll_selection_stats = locals().get("_broll_selection_stats", {}) or {}
            if not _caption_overlay_pack_metadata and isinstance(_caption_decisions, dict):
                _caption_overlay_pack_metadata = dict(_caption_decisions.get("caption_overlay_pack") or {})
            try:
                from .vpi_visual_effects_service import build_composition_decision as _build_composition_decision
                _composition_decision = _build_composition_decision(
                    hook_intent=str((_hook_plan_data or {}).get("hook_intent") or segment.get("editorial_type") or ""),
                    visual_profile=str((_hook_plan_data or {}).get("visual_profile") or ""),
                    caption_overlay_pack=_caption_overlay_pack_metadata,
                    transition_plan=_transition_metadata,
                    sfx_plan=_sfx_metadata,
                    private_premium_status=str(_publishable_metadata.get("private_premium_status") or ""),
                    segment_text=str(segment.get("text") or ""),
                )
                logger.info("[composition-pack] runtime_connected=true")
            except Exception as _comp_refresh_e:
                logger.debug("[composition-pack] runtime refresh skipped reason=%s", _comp_refresh_e)

            # ── Post-production visual effects v3.6 — CPU-only, speaker-safe ──
            try:
                from .vpi_visual_effects_service import apply_visual_effects as _apply_visual_effects
                _visual_out = output_path.with_name(f"vfx_{output_path.name}")
                _visual_effects_metadata = _apply_visual_effects(
                    output_path,
                    _visual_out,
                    hook_plan=_hook_plan_data,
                    no_broll=not bool(_editorial_broll_for_status),
                    editorial_type=str(segment.get("editorial_type") or ""),
                    duration_s=float(duration or 0.0),
                )
                if _visual_effects_metadata.get("visual_effects_applied") and _visual_out.exists():
                    _vfx_input = output_path
                    output_path = _visual_out
                    _log_premium_pipeline_step("vfx", _vfx_input, output_path)
                    logger.info("[visual-effects] final_output_uses_vfx=true final_path=%s", output_path)
                if _hook_plan_data and (_visual_effects_metadata.get("visual_effects_events") or []):
                    _motion_event = (_visual_effects_metadata.get("visual_effects_events") or [{}])[0] or {}
                    _hook_plan_data["visual_profile"] = _motion_event.get("visual_profile") or _hook_plan_data.get("visual_profile") or ""
                    _hook_plan_data["motion_pack_profile"] = _motion_event.get("motion_pack_profile") or _hook_plan_data.get("motion_pack_profile") or ""
                    _hook_plan_data["motion_pack_applied"] = bool(_visual_effects_metadata.get("motion_pack_applied"))
            except Exception as _vfx_e:
                logger.warning("[visual-effects] failed reason=%s", _vfx_e)
                _visual_effects_metadata = {
                    "visual_effects_applied": False,
                    "visual_effects_count": 0,
                    "visual_effects_events": [],
                    "visual_effects_warning": str(_vfx_e),
                }

            # ── Premium Transition Pack v4.1 — visible, intentional, CPU-only ──
            try:
                from .vpi_transition_engine import (
                    apply_transition_plan as _apply_transition_plan,
                    plan_transition_events as _plan_transition_events,
                )
                _transition_context = {
                    "editorial_type": str(segment.get("editorial_type") or ""),
                    "hook_intent": str((_hook_plan_data or {}).get("hook_intent") or ""),
                    "reason": str(segment.get("text") or "")[:180],
                    "start_time": 0.45 if float(duration or 0.0) <= 8.0 else min(3.2, max(0.45, float(duration or 0.0) * 0.18)),
                    "important_broll": bool(_editorial_broll_for_status),
                    "narrative_event": "hook_to_explanation" if (_hook_plan_data or {}).get("hook_type") != "weak_intro" else "",
                    "semantic_continuity": bool(_editorial_broll_for_status),
                    "target_bbox": (
                        (_editorial_broll_for_status[0] or {}).get("bbox")
                        if _editorial_broll_for_status
                        else None
                    ),
                    "concept_shift": (
                        "risk_to_protection"
                        if str(segment.get("editorial_type") or "") == "risk_warning"
                        else ""
                    ),
                    "shape_morph_viable": True,
                    "frame_rhythm_group": "hook_transition",
                    "composition_decision": _composition_decision,
                    "hook_overlay_active": bool(((_caption_overlay_pack_metadata or {}).get("hook_overlay") or {}).get("applied")),
                }
                _transition_plan = _plan_transition_events(_transition_context)
                _transition_out = output_path.with_name(f"trans_{output_path.name}")
                _transition_metadata = _apply_transition_plan(
                    output_path,
                    _transition_out,
                    _transition_plan,
                )
                _transition_metadata["transition_plan"] = _transition_plan.to_dict()
                if _transition_metadata.get("transitions_applied") and _transition_out.exists():
                    _transition_input = output_path
                    output_path = _transition_out
                    _log_premium_pipeline_step("transitions", _transition_input, output_path)
                    logger.info("[transition-final] final_output_uses_transition=true path=%s", output_path)
                else:
                    logger.info("[transition-final] final_output_uses_transition=false path=%s", output_path)
            except Exception as _trans_e:
                logger.warning("[transition-apply] failed type=unknown fallback=clean_cut reason=%s", _trans_e)
                _transition_metadata = {
                    "transitions_applied": False,
                    "transition_events": [],
                    "transition_types": [],
                    "transition_warnings": [str(_trans_e)],
                    "final_output_uses_transition": False,
                }

            try:
                _brand_out = output_path.with_name(f"brand_{output_path.name}")
                _brand_input = output_path
                _brand_metadata = _apply_vpi_branding(output_path, _brand_out)
                _brand_metadata["logo_found"] = bool(_brand_asset)
                _brand_metadata["logo_path"] = str(_brand_asset) if _brand_asset else None
                if _brand_metadata.get("rendered") and _brand_out.exists():
                    output_path = _brand_out
                    _log_premium_pipeline_step("branding", _brand_input, output_path)
                else:
                    _brand_metadata.setdefault("type", "metadata_only")
                    _brand_metadata["rendered"] = False
            except Exception as _brand_e:
                logger.warning("[branding] skipped reason=%s", _brand_e)
                _brand_metadata = {"type": "metadata_only", "rendered": False, "reason": str(_brand_e)}

            # ── Music/SFX v3.3 — local libraries only, before final mastering ──
            try:
                from .vpi_music_service import apply_music_bed as _apply_music_bed
                _music_out = output_path.with_name(f"music_{output_path.name}")
                _music_metadata = _apply_music_bed(
                    output_path,
                    _music_out,
                    editorial_type=str(segment.get("editorial_type") or ""),
                )
                if _music_metadata.get("music_applied") and _music_out.exists():
                    _music_input = output_path
                    output_path = _music_out
                    _log_premium_pipeline_step("music", _music_input, output_path)
                    logger.info("[music] final_output_uses_music=true final_path=%s", output_path)
            except Exception as _music_e:
                logger.warning("[music] skipped reason=%s", _music_e)
                _music_metadata = {"music_applied": False, "music_status": "failed", "music_warning": str(_music_e)}

            try:
                from .vpi_sfx_service import apply_sfx_bed as _apply_sfx_bed
                from .vpi_visual_effects_service import first3_visual_contract as _build_first3_visual_contract_pre_sfx
                _sfx_out = output_path.with_name(f"sfx_{output_path.name}")
                _first3_visual_contract_pre_sfx: Dict[str, Any] = {}
                try:
                    _first3_visual_contract_pre_sfx = _build_first3_visual_contract_pre_sfx(
                        hook_plan=_hook_plan_data,
                        caption_overlay_pack=_caption_overlay_pack_metadata if isinstance(_caption_overlay_pack_metadata, dict) else {},
                        composition_decision=_composition_decision,
                        visual_effects=(_visual_effects_metadata or {}).get("visual_effects_events") or [],
                        transition_plan=_transition_metadata if isinstance(_transition_metadata, dict) else {},
                    )
                except Exception as _pre_sfx_contract_e:
                    logger.debug("[first3-visual-contract] pre_sfx skipped reason=%s", _pre_sfx_contract_e)
                _sfx_metadata = _apply_sfx_bed(
                    output_path,
                    _sfx_out,
                    hook_plan=_hook_plan_data,
                    broll_events=_editorial_broll_for_status,
                    transition_events=(_transition_metadata or {}).get("transition_events") or [],
                    editorial_type=str(segment.get("editorial_type") or ""),
                    segment_text=str(segment.get("text") or ""),
                    composition_decision=_composition_decision,
                    broll_editorial_decision=_broll_editorial_decision,
                    private_premium_status=str(_publishable_metadata.get("private_premium_status") or ""),
                    first3_visual_contract=_first3_visual_contract_pre_sfx,
                    silence_plan=_silence_edit_plan_data,
                )
                if _sfx_metadata.get("sfx_applied") and _sfx_out.exists():
                    _sfx_input = output_path
                    output_path = _sfx_out
                    _log_premium_pipeline_step("sfx", _sfx_input, output_path)
                    logger.info("[sfx] final_output_uses_sfx=true final_path=%s", output_path)
            except Exception as _sfx_e:
                logger.warning("[sfx] skipped reason=%s", _sfx_e)
                _sfx_metadata = {"sfx_applied": False, "sfx_count": 0, "sfx_warning": str(_sfx_e)}

            # ── Audio Mastering v1.8 — loudness normalization for social reels ──
            # Applied AFTER branding (all audio elements present) and BEFORE
            # output QC (so QC measures mastered loudness).
            _audio_mastering_result: Optional[Any] = None
            try:
                from .vpi_audio_mastering import (
                    audio_mastering_enabled as _am_enabled,
                    master_audio_for_social as _master_audio,
                    build_audio_qc_metadata as _build_audio_qc,
                    build_audio_publish_warnings as _build_audio_pub_warnings,
                )
                if _am_enabled():
                    _am_out = output_path.with_name(f"mastered_{output_path.name}")
                    _audio_mastering_result = _master_audio(
                        input_path=str(output_path),
                        output_path=str(_am_out),
                    )
                    if _audio_mastering_result.applied and _am_out.exists():
                        _audio_master_metadata = _build_audio_qc(_audio_mastering_result)
                        logger.info(
                            "[audio-master] applied method=%s input_lufs=%s output_lufs=%s status=%s",
                            _audio_mastering_result.method,
                            _audio_master_metadata.get("input_lufs"),
                            _audio_master_metadata.get("output_lufs"),
                            _audio_master_metadata.get("audio_voice_status"),
                        )
                        _log_premium_pipeline_step("audio_mastering", Path(_audio_mastering_result.input_path) if hasattr(_audio_mastering_result, "input_path") else output_path, _am_out)
                        output_path = _am_out
                        logger.info(
                            "[music] final_output_uses_music=%s final_path=%s",
                            str(bool(_music_metadata.get("music_applied") and "music_" in output_path.name)).lower(),
                            output_path,
                        )
                        logger.info(
                            "[visual-effects] final_output_uses_vfx=%s final_path=%s",
                            str(bool(_visual_effects_metadata.get("visual_effects_applied") and "vfx_" in output_path.name)).lower(),
                            output_path,
                        )
                        logger.info(
                            "[transition-final] final_output_uses_transition=%s path=%s",
                            str(bool(_transition_metadata.get("transitions_applied") and "trans_" in output_path.name)).lower(),
                            output_path,
                        )
                    elif _audio_mastering_result.method == "skipped":
                        _audio_master_metadata = _build_audio_qc(_audio_mastering_result)
                        logger.info("[audio-master] skipped reason=already_loud_enough")
                    else:
                        _audio_master_metadata = _build_audio_qc(_audio_mastering_result)
                        logger.info("[audio-master] not applied method=%s", _audio_mastering_result.method)
                else:
                    logger.debug("[audio-master] disabled by config")
                    _audio_master_metadata = {"audio_mastering_enabled": False, "audio_mastering_applied": False}
            except Exception as _am_e:
                logger.warning("[audio-master] integration error: %s", _am_e)
                _audio_mastering_result = None
                _audio_master_metadata = {"audio_mastering_applied": False, "audio_warnings": [str(_am_e)]}

            # ── Cinematic Finish Pack v1 — subtle final visual polish ──────────
            try:
                from .vpi_visual_effects_service import (
                    apply_cinematic_finish as _apply_cinematic_finish,
                    build_cinematic_finish_decision as _build_cinematic_finish_decision,
                )

                _finish_first3_contract = locals().get("_first3_visual_contract_pre_sfx") or {}
                _finish_status_hint = str((_publishable_metadata or {}).get("private_premium_status") or "")
                if not _finish_status_hint:
                    _finish_complete_idea = float(segment.get("complete_idea_score") or 1.0)
                    _finish_fluency = float(
                        segment.get("fluency_score_after")
                        or ((_fluency_edit_plan or {}).get("fluency_score_after") if _fluency_edit_plan else 1.0)
                        or 1.0
                    )
                    _finish_content_quality = str(segment.get("content_quality_label") or "")
                    _finish_hook_score = int((_hook_plan_data or {}).get("hook_first3_score") or 0)
                    _finish_hook_fit_ok = bool((_hook_plan_data or {}).get("hook_fit_acceptable"))
                    if _finish_content_quality == "reject" or _finish_complete_idea < 0.75 or _finish_fluency < 0.70:
                        _finish_status_hint = "DO_NOT_UPLOAD"
                    elif _finish_hook_score < 5 and not _finish_hook_fit_ok:
                        _finish_status_hint = "PRIVATE_PREMIUM_REVIEW"
                    else:
                        _finish_status_hint = "PRIVATE_PREMIUM_READY"
                _finish_decision = _build_cinematic_finish_decision(
                    hook_intent=str((_hook_plan_data or {}).get("hook_intent") or ""),
                    composition_mode=str((_composition_decision or {}).get("composition_mode") or ""),
                    private_premium_status=_finish_status_hint,
                    first3_visual_contract=_finish_first3_contract,
                    caption_overlay_pack=_caption_overlay_pack_metadata,
                    motion_pack_applied=bool((_visual_effects_metadata or {}).get("motion_pack_applied")),
                    broll_applied=bool(_editorial_broll_for_status),
                    sfx_retention_pack=bool((_sfx_metadata or {}).get("sfx_retention_pack")),
                    segment_text=str(segment.get("text") or ""),
                )
                _finish_out = output_path.with_name(f"finish_{output_path.name}")
                _cinematic_finish_metadata = _apply_cinematic_finish(
                    output_path,
                    _finish_out,
                    decision=_finish_decision,
                    caption_overlay_pack=_caption_overlay_pack_metadata if isinstance(_caption_overlay_pack_metadata, dict) else {},
                    first3_visual_contract_data=_finish_first3_contract,
                    composition_decision=_composition_decision if isinstance(_composition_decision, dict) else {},
                )
                if _cinematic_finish_metadata.get("visual_finish") and _finish_out.exists():
                    _finish_input = output_path
                    output_path = _finish_out
                    _log_premium_pipeline_step("cinematic_finish", _finish_input, output_path)
                logger.info(
                    "[editing-richness] cinematic_finish_pack=%s reason=%s",
                    str(bool(_cinematic_finish_metadata.get("cinematic_finish_pack"))).lower(),
                    (
                        "filter_plan_applied"
                        if _cinematic_finish_metadata.get("cinematic_finish_pack")
                        else (_cinematic_finish_metadata.get("finish_warning") or "not_applied")
                    ),
                )
                logger.info(
                    "[editing-richness] visual_finish=%s reason=%s",
                    str(bool(_cinematic_finish_metadata.get("visual_finish"))).lower(),
                    "ffmpeg_filter_applied" if _cinematic_finish_metadata.get("visual_finish") else (_cinematic_finish_metadata.get("finish_warning") or "not_applied"),
                )
                logger.info("[editing-richness] finish_profile=%s", str(_cinematic_finish_metadata.get("finish_profile") or "none"))
                logger.info("[editing-richness] finish_safety=%s", str(_cinematic_finish_metadata.get("finish_safety") or "blocked"))
            except Exception as _finish_e:
                logger.warning("[cinematic-finish] skipped reason=%s", _finish_e)
                _cinematic_finish_metadata = {
                    "cinematic_finish_pack": False,
                    "visual_finish": False,
                    "finish_profile": "no_finish_needed",
                    "finish_safety": "blocked",
                    "finish_warning": str(_finish_e),
                    "finish_applied": False,
                }

            _broll_asset_ids = [
                str(item.get("asset_id") or item.get("asset_path") or item.get("asset_url") or "")
                for item in _editorial_broll_for_status
                if item
            ]
            _broll_asset_ids = [item for item in _broll_asset_ids if item]
            _repeated_exact_broll_same_clip = len(_broll_asset_ids) != len(set(_broll_asset_ids))
            _weak_intro_forced_broll = (
                (_editing_plan_data or {}).get("broll_strategy") == "no_broll"
                and bool(_editorial_broll_for_status)
            )
            if _weak_intro_forced_broll:
                logger.warning("[context-no-broll] hard_stop_failed reason=weak_intro_forced_broll")

            _smart_events = list((_editing_plan_data or {}).get("smart_zoom_events") or [])
            if _editorial_broll_for_status and len(_smart_events) > 1:
                _editing_plan_data["smart_zoom_events"] = _smart_events[:1]
                if isinstance(_editing_plan_data.get("smart_reframe"), dict):
                    _editing_plan_data["smart_reframe"]["events"] = _smart_events[:1]
                if isinstance(_smart_reframe_metadata, dict):
                    _smart_reframe_metadata["events"] = _smart_events[:1]

            _subtitle_terms = list((_editing_plan_data or {}).get("highlighted_terms") or [])
            _hook_terms = list((_hook_plan_data or {}).get("emphasis_words") or [])
            _subtitle_intelligence_metadata = {
                "highlighted_terms": _subtitle_terms,
                "hook_highlight_terms": _hook_terms,
                "hook_highlight_applied": bool(_hook_terms),
                "rendered": bool(_subtitle_terms),
                "reason": "emphasis_indices" if _subtitle_terms else "no_terms",
                "caption_overlay_pack": bool((_caption_overlay_pack_metadata or {}).get("caption_overlay_pack")),
                "caption_overlay_actions": list((_caption_overlay_pack_metadata or {}).get("caption_overlay_actions") or []),
                "keyword_emphasis_terms": list((_caption_overlay_pack_metadata or {}).get("keyword_emphasis_terms") or []),
                "hook_overlay": (_caption_overlay_pack_metadata or {}).get("hook_overlay") or {},
                "caption_icon": (_caption_overlay_pack_metadata or {}).get("caption_icon") or {},
                "lower_third": (_caption_overlay_pack_metadata or {}).get("lower_third") or {},
            }
            if _hook_plan_data:
                _first3_signals: List[str] = []
                _first3_score = 0
                _hook_motion_start = float((_hook_plan_data or {}).get("hook_motion_start_s") or ((_hook_plan_data or {}).get("zoom_event") or {}).get("start_s") or 0.0)
                _hook_motion_duration = float((_hook_plan_data or {}).get("hook_motion_duration_s") or ((_hook_plan_data or {}).get("zoom_event") or {}).get("duration_s") or 0.0)
                _vfx_first3 = any(
                    float((event or {}).get("start_s") or 99.0) < 3.0
                    for event in (_visual_effects_metadata or {}).get("visual_effects_events", []) or []
                ) and bool((_visual_effects_metadata or {}).get("visual_effects_applied"))
                _hook_motion_in_first3 = bool(
                    (_hook_plan_data or {}).get("hook_motion_rendered")
                    or (_hook_plan_data or {}).get("rendered")
                    or (_hook_plan_data or {}).get("kickframe_applied")
                ) and _hook_motion_start < 3.0 and _hook_motion_duration > 0.0
                _motion_in_first3 = bool(_hook_motion_in_first3 or _vfx_first3)
                if _motion_in_first3:
                    _first3_score += 2
                    _first3_signals.append("visible_hook_motion")
                if (
                    bool(_hook_terms)
                    or _subtitle_intelligence_metadata.get("hook_highlight_applied")
                    or _subtitle_intelligence_metadata.get("caption_overlay_pack")
                ):
                    _first3_score += 2
                    _first3_signals.append("hook_subtitle_before_1_5s")
                try:
                    _silence_segments = (_silence_edit_plan_data or {}).get("segments") or []
                    _silence_cuts = (_silence_edit_plan_data or {}).get("cuts") or []
                    if any(float((item or {}).get("start_s") or (item or {}).get("original_start") or 99.0) < 3.0 for item in list(_silence_segments) + list(_silence_cuts)):
                        _first3_score += 1
                        _first3_signals.append("silence_cut_before_3s")
                except Exception:
                    pass
                _headline = str((_hook_plan_data or {}).get("headline_text") or (_hook_plan_data or {}).get("subtitle_hook_text") or "")
                _segment_text = str(segment.get("text") or "")
                if _headline and _segment_text and _headline.lower()[:18] in _segment_text.lower()[:180]:
                    _first3_score += 1
                    _first3_signals.append("strong_phrase_before_2s")
                if (
                    (_hook_plan_data or {}).get("overlay_rendered")
                    or (_hook_plan_data or {}).get("lower_third_applied")
                    or ((_subtitle_intelligence_metadata.get("hook_overlay") or {}).get("applied"))
                    or ((_subtitle_intelligence_metadata.get("lower_third") or {}).get("applied"))
                ):
                    _first3_score += 1
                    _first3_signals.append("visual_emphasis")
                if any(str((event or {}).get("event") or "").startswith("hook") for event in (_sfx_metadata or {}).get("sfx_events", []) or []):
                    _first3_score += 1
                    _first3_signals.append("hook_sfx")
                elif _music_metadata.get("music_applied"):
                    _first3_score += 1
                    _first3_signals.append("music_swell")
                _first3_strong = bool(
                    (_hook_plan_data or {}).get("hook_type") != "weak_intro"
                    and _first3_score >= 5
                    and _motion_in_first3
                )
                _first3_perceptible = _first3_strong
                _missing = []
                if not _motion_in_first3:
                    _missing.append("hook_motion")
                if not (
                    bool(_hook_terms)
                    or _subtitle_intelligence_metadata.get("hook_highlight_applied")
                    or _subtitle_intelligence_metadata.get("caption_overlay_pack")
                ):
                    _missing.append("hook_subtitle_before_1_5s")
                if not ((_silence_edit_plan_data or {}).get("rendered")):
                    _missing.append("rhythm")
                if not (_sfx_metadata.get("sfx_applied") or _music_metadata.get("music_applied")):
                    _missing.append("sound_layer")
                _hook_plan_data["hook_first3_score"] = _first3_score
                _hook_plan_data["hook_first3_perceptible_score"] = _first3_score
                _hook_plan_data["hook_first3_perceptible"] = bool(_first3_perceptible)
                _hook_plan_data["hook_first3_signals"] = _first3_signals
                _hook_plan_data["hook_first3_missing"] = _missing
                _hook_plan_data["hook_first3_status"] = "strong" if _first3_strong else "weak"
                _hook_plan_data["hook_first3_final_verified"] = bool(_motion_in_first3)
                if not _first3_perceptible:
                    _hook_plan_data["hook_first3_warning"] = "weak_first_3_seconds"
                    _hook_plan_data.setdefault("warnings", []).append("weak_first_3_seconds")
                logger.info(
                    "[hook-first3] score=%d status=%s rendered_signals=%s final_output_verified=%s",
                    _first3_score,
                    _hook_plan_data["hook_first3_status"],
                    "|".join(_first3_signals) or "none",
                    str(bool(_motion_in_first3)).lower(),
                )
                logger.info("[hook-first3] rendered_signals=%s", "|".join(_first3_signals) or "none")
                if not _first3_perceptible:
                    logger.info("[hook-first3] warning=weak_first_3_seconds")
                logger.info("[hook-first3] missing=%s", "|".join(_missing) or "none")
                logger.info("[hook-first3] final_output_verified=%s", str(bool(_motion_in_first3)).lower())

            _hook_quality = "missing"
            _hook_broll_too_early = False
            if _hook_plan_data:
                _hook_broll_delay = float((_hook_plan_data or {}).get("broll_delay_until_s") or 0.0)
                for _broll_event in _editorial_broll_for_status:
                    try:
                        if float(_broll_event.get("start_s", 0.0) or 0.0) < _hook_broll_delay:
                            _hook_broll_too_early = True
                            break
                    except (TypeError, ValueError):
                        continue
                if (_hook_plan_data or {}).get("hook_type") == "weak_intro":
                    _hook_quality = "weak"
                elif not (_hook_plan_data or {}).get("headline_text"):
                    _hook_quality = "weak"
                elif _hook_broll_too_early or float((_hook_plan_data or {}).get("density_score") or 0.0) > 6.0:
                    _hook_quality = "acceptable"
                elif (
                    (_hook_plan_data or {}).get("rendered")
                    or (_hook_plan_data or {}).get("overlay_rendered")
                    or int((_hook_plan_data or {}).get("hook_visual_signal_count") or 0) > 0
                    or bool(_hook_terms)
                ):
                    _hook_quality = "strong"
                else:
                    _hook_quality = "acceptable"
                if (
                    _hook_quality == "strong"
                    and (_hook_plan_data or {}).get("hook_type") != "weak_intro"
                    and (
                        int((_hook_plan_data or {}).get("hook_first_4s_score") or 0) < 2
                        or int((_hook_plan_data or {}).get("hook_first3_perceptible_score") or 0) < 4
                    )
                ):
                    _hook_quality = "acceptable"
                _hook_plan_data["hook_quality"] = _hook_quality

            _output_qc = _probe_output_qc(output_path)
            if locals().get("_audio_master_metadata"):
                _output_qc["audio_qc"] = dict(_audio_master_metadata)
                _output_qc.update({
                    "audio_mastering_applied": _audio_master_metadata.get("audio_mastering_applied"),
                    "input_lufs": _audio_master_metadata.get("input_lufs"),
                    "output_lufs": _audio_master_metadata.get("output_lufs"),
                    "input_peak": _audio_master_metadata.get("input_peak"),
                    "output_peak": _audio_master_metadata.get("output_peak"),
                    "audio_measurement_method": _audio_master_metadata.get("audio_measurement_method"),
                    "audio_voice_status": _audio_master_metadata.get("audio_voice_status"),
                    "audio_warnings": _audio_master_metadata.get("audio_warnings", []),
                })
            _output_qc["silence_trim_applied"] = bool((_silence_edit_plan_data or {}).get("rendered"))
            _output_qc["total_removed_s"] = float((_silence_edit_plan_data or {}).get("total_removed_s") or 0.0)
            _output_qc["silence_warnings"] = list(
                (_silence_edit_plan_data or {}).get("warnings")
                or (_silence_edit_plan_data or {}).get("apply_warnings")
                or []
            )
            _density_final = _assess_visual_density(
                editing_plan=_editing_plan_data or {},
                broll_events=_editorial_broll_for_status,
                subtitle_highlight_count=len(_subtitle_terms),
                watermark_applied=bool(_brand_metadata.get("rendered")),
            )
            if _editing_plan_data:
                _editing_plan_data["visual_density_score"] = _density_final.get("visual_density_score")
                _editing_plan_data["visual_density_warnings"] = _density_final.get("visual_density_warnings", [])
                _editing_plan_data["visual_density_actions"] = _density_final.get("visual_density_actions", [])
            _hook_signal_count = int((_hook_plan_data or {}).get("hook_visual_signal_count") or 0)
            _editing_activity_score = 0
            if _hook_signal_count:
                _editing_activity_score += 2
            if _smart_reframe_metadata.get("rendered"):
                _editing_activity_score += 2
            if _editorial_broll_for_status:
                _editing_activity_score += 2
            if bool(add_subtitles and (words_with_confidence or segment.get("text"))):
                _editing_activity_score += 1
            if _brand_metadata.get("rendered"):
                _editing_activity_score += 1
            if (_silence_edit_plan_data or {}).get("rendered"):
                _editing_activity_score += 1
            if locals().get("_audio_master_metadata", {}).get("applied") or str(Path(output_path).name).startswith("mastered_"):
                _editing_activity_score += 1
            _editing_activity_warning = (
                bool((_hook_plan_data or {}).get("enabled"))
                and (_hook_plan_data or {}).get("hook_type") != "weak_intro"
                and _editing_activity_score < 5
            )
            if _editing_activity_warning:
                logger.info("[editing-activity] score=%d warning=low_editing_activity", _editing_activity_score)
            else:
                logger.info("[editing-activity] score=%d warning=none", _editing_activity_score)
            if _editing_plan_data is not None:
                _editing_plan_data["editing_activity_score"] = _editing_activity_score
                _editing_plan_data["editing_activity_warning"] = "low_editing_activity" if _editing_activity_warning else None
            _output_qc = _extend_output_qc_visual(
                _output_qc,
                watermark_applied=bool(_brand_metadata.get("rendered")),
                captions_applied=bool(add_subtitles and (words_with_confidence or segment.get("text"))),
                subtitle_highlight_count=len(_subtitle_terms),
                broll_count=len(_editorial_broll_for_status),
                smart_reframe_applied=bool(_smart_reframe_metadata.get("rendered")),
                visual_density_warnings=_density_final.get("visual_density_warnings", []),
                branding_warnings=_brand_metadata.get("warnings", []),
                broll_repetition_warnings=["repeated_exact_broll_same_clip"] if _repeated_exact_broll_same_clip else [],
                hook_applied=bool((_hook_plan_data or {}).get("enabled")),
                hook_type=str((_hook_plan_data or {}).get("hook_type") or ""),
                hook_rendered=bool((_hook_plan_data or {}).get("rendered")),
            )
            _publish_warnings = []
            if not _brand_asset:
                _publish_warnings.append("no_logo_found_text_watermark_used")
            if not _smart_reframe_metadata.get("rendered"):
                _publish_warnings.append("smart_zoom_metadata_only")
            if (_editing_plan_data or {}).get("cta_strategy") in {"metadata_only", "optional_end"}:
                _publish_warnings.append("cta_metadata_only")
            for _hook_warning in ((_hook_plan_data or {}).get("warnings") or []):
                if _hook_warning in {"weak_hook", "hook_metadata_only", "hook_render_failed", "hook_render_failed_or_skipped", "hook_overlay_skipped", "hook_density_high", "emotional_hook_visual_weak"}:
                    _publish_warnings.append(_hook_warning)
            for _silence_warning in ((_silence_edit_plan_data or {}).get("warnings") or []) + ((_silence_edit_plan_data or {}).get("apply_warnings") or []):
                if _silence_warning in {"silence_trim_failed", "silence_remap_failed", "silence_metadata_only", "excessive_dead_air_detected"}:
                    _publish_warnings.append(_silence_warning)
            if _audio_mastering_result is not None:
                try:
                    _publish_warnings.extend(_build_audio_pub_warnings(_audio_mastering_result))
                except Exception:
                    pass
            if _hook_quality in {"weak", "missing"}:
                _publish_warnings.append("weak_hook")
            if (_hook_plan_data or {}).get("hook_headline_overlay") and not (_hook_plan_data or {}).get("overlay_rendered"):
                _publish_warnings.append("hook_overlay_skipped")
            if (
                bool((_hook_plan_data or {}).get("enabled"))
                and (_hook_plan_data or {}).get("hook_type") != "weak_intro"
                and int((_hook_plan_data or {}).get("hook_first_4s_score") or 0) < 2
            ):
                _publish_warnings.append("weak_first_4_seconds")
            if (
                bool((_hook_plan_data or {}).get("enabled"))
                and (_hook_plan_data or {}).get("hook_type") != "weak_intro"
                and not bool((_hook_plan_data or {}).get("hook_first3_perceptible"))
            ):
                _publish_warnings.append("weak_first_3_seconds")
            if float((_hook_plan_data or {}).get("density_score") or 0.0) > 6.0:
                _publish_warnings.append("hook_density_high")
            if _hook_broll_too_early:
                _publish_warnings.append("hook_broll_too_early")
            if bool((_hook_plan_data or {}).get("enabled")) and int((_hook_plan_data or {}).get("hook_visual_signal_count") or 0) == 0:
                _publish_warnings.append("hook_visual_missing")
            if locals().get("_editing_activity_warning"):
                _publish_warnings.append("low_editing_activity")
            if (
                not _editorial_broll_for_status
                and not _visual_effects_metadata.get("visual_effects_applied")
                and not _music_metadata.get("music_applied")
                and not _sfx_metadata.get("sfx_applied")
            ):
                _publish_warnings.append("missing_editing_layers")

            _no_broll = not bool(_editorial_broll_for_status)
            _non_weak_hook = bool((_hook_plan_data or {}).get("enabled")) and (_hook_plan_data or {}).get("hook_type") != "weak_intro"
            _speaker_focus_events = []
            if _no_broll and _non_weak_hook:
                if (_hook_plan_data or {}).get("hook_motion_rendered") or (_hook_plan_data or {}).get("rendered"):
                    _speaker_focus_events.append({
                        "type": "hook_motion",
                        "start_s": (_hook_plan_data or {}).get("hook_motion_start_s"),
                        "duration_s": (_hook_plan_data or {}).get("hook_motion_duration_s"),
                    })
                if (_silence_edit_plan_data or {}).get("rendered"):
                    _speaker_focus_events.append({
                        "type": "silence_rhythm",
                        "removed_s": (_silence_edit_plan_data or {}).get("total_removed_s"),
                    })
                if _subtitle_intelligence_metadata.get("hook_highlight_applied"):
                    _speaker_focus_events.append({"type": "caption_hook_highlight"})
            _speaker_focus_metadata = {
                "speaker_focus_enhanced": bool(_speaker_focus_events),
                "speaker_focus_events": _speaker_focus_events[:2],
                "speaker_focus_real_effects": bool(
                    _no_broll
                    and (_visual_effects_metadata or {}).get("visual_effects_applied")
                ),
            }
            logger.info(
                "[speaker-focus] enhanced=%s events=%s",
                str(_speaker_focus_metadata["speaker_focus_enhanced"]).lower(),
                _speaker_focus_metadata["speaker_focus_events"],
            )
            logger.info(
                "[speaker-focus] applied_real_effects=%s",
                str(bool(_speaker_focus_metadata.get("speaker_focus_real_effects"))).lower(),
            )

            _good_broll_phrase_fit = False
            _broll_without_transition = False
            _static_broll_without_kenburns = False
            for _broll_item in _editorial_broll_for_status:
                try:
                    _fit_score = float((_broll_item or {}).get("broll_phrase_fit_score") or 0.0)
                except (TypeError, ValueError):
                    _fit_score = 0.0
                _fit_label = str((_broll_item or {}).get("broll_phrase_fit_label") or "").lower()
                if _fit_score >= 60.0 or _fit_label in {"exact", "good"}:
                    _good_broll_phrase_fit = True
                if not bool((_broll_item or {}).get("broll_transition_applied")):
                    _broll_without_transition = True
                if bool((_broll_item or {}).get("broll_is_image")) and not bool((_broll_item or {}).get("broll_ken_burns_applied")):
                    _static_broll_without_kenburns = True
            _broll_editorial_decision_final = dict((_editing_plan_data or {}).get("broll_editorial_decision") or {})
            _broll_asset_match_final = dict((_editing_plan_data or {}).get("broll_asset_match") or {})
            _broll_editorial_opportunity_final = bool((_editing_plan_data or {}).get("broll_editorial_opportunity"))
            _broll_composition_allowed_final = bool((_editing_plan_data or {}).get("broll_composition_allowed", True))
            _broll_start = float(_broll_editorial_decision_final.get("start_offset") or 0.0)
            _broll_duration = float(_broll_editorial_decision_final.get("duration") or 0.0)
            _broll_timing_valid = bool(1.2 <= _broll_start <= 5.0 and 0.8 <= _broll_duration <= 2.2)
            _expected_broll_asset = str(_broll_asset_match_final.get("asset") or "")
            _expected_broll_asset_norm = _expected_broll_asset.replace("\\", "/").lower()
            _actual_broll_assets = [
                str((_item or {}).get("asset_path") or (_item or {}).get("path") or (_item or {}).get("asset_url") or "")
                for _item in _editorial_broll_for_status
            ]
            _actual_broll_assets = [item for item in _actual_broll_assets if item]
            _actual_broll_assets_norm = [item.replace("\\", "/").lower() for item in _actual_broll_assets]
            _broll_asset_applied_match = bool(
                _expected_broll_asset_norm
                and any(
                    _expected_broll_asset_norm.endswith(_actual)
                    or _actual.endswith(_expected_broll_asset_norm)
                    for _actual in _actual_broll_assets_norm
                )
            )
            _broll_runtime_blocked_by_status = str((_publishable_metadata or {}).get("private_premium_status") or "") == "DO_NOT_UPLOAD"
            _broll_true = bool(
                _editorial_broll_for_status
                and _broll_composition_allowed_final
                and _broll_timing_valid
                and bool(_broll_asset_match_final.get("matched"))
                and _broll_asset_applied_match
                and not _broll_runtime_blocked_by_status
            )
            _broll_opportunity_unfulfilled = bool(_broll_editorial_opportunity_final and not _broll_true)
            _broll_unfulfilled_reason = str(_broll_editorial_decision_final.get("skip_reason") or "")
            if _broll_editorial_opportunity_final and not _broll_true and not _broll_unfulfilled_reason:
                if _broll_runtime_blocked_by_status:
                    _broll_unfulfilled_reason = "private_premium_do_not_upload"
                elif not _broll_asset_applied_match:
                    _broll_unfulfilled_reason = "applied_asset_mismatch"
                elif not _broll_composition_allowed_final:
                    _broll_unfulfilled_reason = "composition_conflict"
                elif not _broll_timing_valid:
                    _broll_unfulfilled_reason = "invalid_timing"
                else:
                    _broll_unfulfilled_reason = "not_applied"
            _broll_limited_assets = bool(
                _broll_opportunity_unfulfilled
                and _broll_unfulfilled_reason in {"no_assets", "no_local_asset", "composition_conflict", "applied_asset_mismatch"}
            )
            logger.info(
                "[broll-asset] applied_match=%s expected=%s actual=%s",
                str(_broll_asset_applied_match).lower(),
                _expected_broll_asset or "none",
                "|".join(_actual_broll_assets) or "none",
            )
            logger.info(
                "[editing-richness] broll=%s reason=%s",
                str(_broll_true).lower(),
                "editorial_asset_timing_composition" if _broll_true else (_broll_unfulfilled_reason or "not_fulfilled_or_not_needed"),
            )
            logger.info(
                "[editing-richness] broll_editorial_opportunity=%s reason=%s",
                str(_broll_opportunity_unfulfilled).lower(),
                _broll_unfulfilled_reason or "none",
            )
            logger.info(
                "[editing-richness] limited_assets=%s reason=%s",
                str(_broll_limited_assets).lower(),
                _broll_unfulfilled_reason or "none",
            )
            if _broll_true and not _good_broll_phrase_fit:
                _good_broll_phrase_fit = True
            if not _broll_true:
                _good_broll_phrase_fit = False
            _sfx_asset_match = bool((_sfx_metadata or {}).get("sfx_asset_applied_match"))
            _sfx_composition_allowed = bool((_sfx_metadata or {}).get("sfx_composition_allowed", True))
            _sfx_timing_safe = bool((_sfx_metadata or {}).get("sfx_timing_safe", (_sfx_metadata or {}).get("sfx_applied")))
            _sfx_true = bool(
                (_sfx_metadata or {}).get("sfx_applied")
                and _sfx_asset_match
                and _sfx_composition_allowed
                and _sfx_timing_safe
            )
            _sfx_opportunity = bool((_sfx_metadata or {}).get("sfx_editorial_opportunity"))
            _sfx_low_variation = bool((_sfx_metadata or {}).get("sfx_low_variation"))
            _sfx_retention_pack = bool(
                (_sfx_metadata or {}).get("sfx_retention_pack")
                or _sfx_true
                or bool(((_silence_edit_plan_data or {}).get("summary") or {}).get("tension_silences_preserved"))
            )
            _sfx_reason = str((_sfx_metadata or {}).get("sfx_warning") or ((_sfx_metadata or {}).get("sfx_retention_decision") or {}).get("skip_reason") or "")
            if _sfx_true:
                _sfx_reason = "asset_timing_composition_safe"
            elif _sfx_opportunity and not _sfx_reason:
                _sfx_reason = "opportunity_unfulfilled"
            _sfx_metadata["sfx_applied"] = bool(_sfx_true)
            _sfx_metadata["sfx_retention_pack"] = bool(_sfx_retention_pack)
            _sfx_metadata["sfx_editorial_opportunity"] = bool(_sfx_opportunity and not _sfx_true)
            _sfx_metadata["sfx_low_variation"] = bool(_sfx_low_variation)
            logger.info("[editing-richness] sfx=%s reason=%s", str(_sfx_true).lower(), _sfx_reason or "none")
            logger.info(
                "[editing-richness] sfx_retention_pack=%s reason=%s",
                str(_sfx_retention_pack).lower(),
                "contextual_timing_or_silence" if _sfx_retention_pack else "none",
            )
            logger.info(
                "[editing-richness] sfx_editorial_opportunity=%s reason=%s",
                str(bool(_sfx_opportunity and not _sfx_true)).lower(),
                _sfx_reason or "none",
            )
            logger.info("[editing-richness] sfx_low_variation=%s", str(_sfx_low_variation).lower())
            _shot_rhythm_plan = dict(
                (_silence_edit_plan_data or {}).get("shot_rhythm")
                or (_editing_plan_data or {}).get("shot_rhythm")
                or (_shot_rhythm_metadata or {})
                or {}
            )
            _shot_rhythm_microcuts = list(_shot_rhythm_plan.get("microcuts") or [])
            _shot_rhythm_preserved = list(_shot_rhythm_plan.get("preserved_pauses") or [])
            _shot_rhythm_interruptions = [
                item for item in (_shot_rhythm_plan.get("pattern_interruptions") or [])
                if bool((item or {}).get("applied"))
            ]
            _shot_rhythm_applied = bool(
                _shot_rhythm_plan.get("applied")
                or int(_shot_rhythm_plan.get("microcuts_applied_count") or 0) > 0
                or _shot_rhythm_microcuts
                or _shot_rhythm_preserved
                or _shot_rhythm_interruptions
            )
            _pacing_before = float(_shot_rhythm_plan.get("pacing_score_before") or 0.0)
            _pacing_after = float(_shot_rhythm_plan.get("pacing_score_after_estimate") or _pacing_before)
            _shot_rhythm_pack = bool(
                _shot_rhythm_applied
                and (
                    bool(_shot_rhythm_microcuts)
                    or bool(_shot_rhythm_preserved)
                    or bool(_shot_rhythm_interruptions)
                    or (_pacing_after > _pacing_before + 0.01)
                )
            )
            _shot_rhythm_reason = str(_shot_rhythm_plan.get("reason") or "")
            if _shot_rhythm_pack:
                _shot_rhythm_reason = "microcut_pause_pattern_applied"
            elif not _shot_rhythm_reason:
                _shot_rhythm_reason = "metadata_only"
            logger.info("[shot-rhythm] pacing_score_before=%.2f", _pacing_before)
            logger.info("[shot-rhythm] pacing_score_after=%.2f", _pacing_after)
            logger.info("[shot-rhythm] applied=%s reason=%s", str(_shot_rhythm_applied).lower(), _shot_rhythm_reason)
            logger.info(
                "[editing-richness] shot_rhythm_pack=%s reason=%s",
                str(_shot_rhythm_pack).lower(),
                _shot_rhythm_reason,
            )
            _finish_decision_meta = dict((_cinematic_finish_metadata or {}).get("finish_decision") or {})
            _finish_filter_plan_meta = dict((_cinematic_finish_metadata or {}).get("finish_filter_plan") or {})
            _finish_should_apply = bool(_finish_decision_meta.get("should_apply_finish"))
            _finish_filter_applied = bool((_cinematic_finish_metadata or {}).get("finish_applied"))
            _finish_safety_status = str((_cinematic_finish_metadata or {}).get("finish_safety") or "blocked")
            _finish_has_plan = bool(_finish_filter_plan_meta.get("filter_chain"))
            _visual_finish = bool(
                (_cinematic_finish_metadata or {}).get("visual_finish")
                and _finish_filter_applied
                and _finish_has_plan
                and _finish_safety_status in {"pass", "adjusted"}
            )
            _cinematic_finish_pack = bool(
                _finish_should_apply
                and _visual_finish
                and _finish_safety_status in {"pass", "adjusted"}
            )
            _finish_limited_assets = bool(_finish_should_apply and not _visual_finish)
            _finish_reason = str((_cinematic_finish_metadata or {}).get("finish_warning") or "")
            if _visual_finish:
                _finish_reason = "filter_plan_applied"
            elif _finish_should_apply and not _finish_reason:
                _finish_reason = "opportunity_unfulfilled"
            logger.info(
                "[editing-richness] cinematic_finish_pack=%s reason=%s",
                str(_cinematic_finish_pack).lower(),
                _finish_reason or "none",
            )
            logger.info(
                "[editing-richness] visual_finish=%s reason=%s",
                str(_visual_finish).lower(),
                "ffmpeg_filter_applied" if _visual_finish else (_finish_reason or "none"),
            )
            logger.info("[editing-richness] finish_profile=%s", str((_cinematic_finish_metadata or {}).get("finish_profile") or "none"))
            logger.info("[editing-richness] finish_safety=%s", _finish_safety_status)
            _final_name = Path(output_path).name
            _music_in_final = bool(_music_metadata.get("music_applied") and "music_" in _final_name)
            _sfx_in_final = bool(_sfx_metadata.get("sfx_applied") and "sfx_" in _final_name)
            _vfx_in_final = bool(_visual_effects_metadata.get("visual_effects_applied") and "vfx_" in _final_name)
            _transition_in_final = bool(_transition_metadata.get("transitions_applied") and "trans_" in _final_name)
            _music_metadata["music_final_verified"] = bool(_music_in_final)
            _sfx_metadata["sfx_final_verified"] = bool(_sfx_in_final)
            _visual_effects_metadata["visual_effects_final_verified"] = bool(_vfx_in_final)
            _transition_metadata["final_output_uses_transition"] = bool(_transition_in_final)
            _transition_metadata["transition_final_path"] = str(output_path)
            if _transition_metadata.get("frame_rhythm_applied"):
                _visual_effects_metadata["frame_rhythm_applied"] = True
                _visual_effects_metadata["frame_rhythm_events"] = list(_transition_metadata.get("frame_rhythm_events") or [])
            _final_contract_metadata = verify_final_filename_contract(
                output_path,
                music=_music_metadata,
                sfx=_sfx_metadata,
                transitions=_transition_metadata,
                visual_effects=_visual_effects_metadata,
                broll_events=_editorial_broll_for_status,
            )
            logger.info("[premium-pipeline] final_path=%s", output_path)
            _composition_allowed_layers = list((_caption_overlay_pack_metadata or {}).get("composition_allowed_layers") or [])
            _composition_skipped_layers = list((_caption_overlay_pack_metadata or {}).get("composition_skipped_layers") or [])
            _composition_runtime_applied = bool(
                (_caption_overlay_pack_metadata or {}).get("composition_decision_applied")
                or _composition_skipped_layers
                or any(
                    str(_warning).startswith("composition_blocked_")
                    for _warning in ((_transition_metadata or {}).get("transition_warnings") or [])
                )
                or bool((_sfx_metadata or {}).get("composition_decision_applied"))
            )
            _composition_layer_overload = bool(
                (_caption_overlay_pack_metadata or {}).get("layer_overload")
            )
            _composition_pack_active = bool(
                _composition_decision
                and _composition_decision.get("composition_mode")
                and _composition_decision.get("composition_mode") not in ("", "unknown")
                and _composition_runtime_applied
            )
            _composition_quality = "poor"
            if _composition_pack_active and not _composition_layer_overload:
                _composition_quality = "good" if _composition_skipped_layers or _composition_allowed_layers else "ok"
            elif _composition_decision and _composition_runtime_applied:
                _composition_quality = "ok"
            elif _composition_decision:
                _composition_quality = "poor"
            _editing_richness_score = 0
            if (_hook_plan_data or {}).get("hook_first3_perceptible"):
                _editing_richness_score += 2
            if _vfx_in_final:
                _editing_richness_score += 2
            if _transition_in_final:
                _editing_richness_score += 2
            if _good_broll_phrase_fit:
                _editing_richness_score += 2
            if _music_in_final:
                _editing_richness_score += 1
            if _sfx_in_final:
                _editing_richness_score += 1
            if (_silence_edit_plan_data or {}).get("rendered"):
                _editing_richness_score += 1
            if _subtitle_intelligence_metadata.get("hook_highlight_applied"):
                _editing_richness_score += 1
            if _brand_metadata.get("rendered"):
                _editing_richness_score += 1
            if _speaker_focus_metadata.get("speaker_focus_enhanced"):
                _editing_richness_score += 1
            if _composition_pack_active:
                _editing_richness_score += 1
            if _visual_finish:
                _editing_richness_score += 1
            if _shot_rhythm_pack:
                _editing_richness_score += 1
            logger.info(
                "[editing-richness] composition_pack=%s reason=%s",
                str(_composition_pack_active).lower(),
                "runtime_connected_and_applied" if _composition_pack_active else "no_runtime_applied_layers",
            )
            logger.info("[editing-richness] composition_quality=%s", _composition_quality)
            logger.info("[editing-richness] layer_overload=%s", str(_composition_layer_overload).lower())
            _no_music_sfx_good_broll = (
                not _music_metadata.get("music_applied")
                and not _sfx_metadata.get("sfx_applied")
                and not _good_broll_phrase_fit
            )
            if _editing_richness_score <= 3:
                _editing_richness_status = "too_plain"
            elif _editing_richness_score <= 5:
                _editing_richness_status = "acceptable"
            elif _editing_richness_score <= 8:
                _editing_richness_status = "good"
            else:
                _editing_richness_status = "rich"
            _richness_warnings = []
            if _no_music_sfx_good_broll:
                if _editing_richness_status in {"good", "rich"}:
                    _editing_richness_status = "acceptable"
                _richness_warnings.append("visually_too_plain")
            if _no_broll and not _visual_effects_metadata.get("visual_effects_applied"):
                _richness_warnings.append("missing_visual_effects_for_no_broll")
            if _music_metadata.get("music_warning") == "missing_music_library":
                _richness_warnings.append("missing_music_library")
            if _sfx_metadata.get("sfx_warning") in {"missing_sfx_library", "missing_sfx_worker_assets"}:
                _richness_warnings.append(str(_sfx_metadata.get("sfx_warning")))
            if (_sfx_metadata or {}).get("sfx_editorial_opportunity") and not _sfx_in_final:
                _richness_warnings.append("sfx_editorial_opportunity_unfulfilled")
            if (_sfx_metadata or {}).get("sfx_low_variation"):
                _richness_warnings.append("sfx_low_variation")
            if _finish_limited_assets:
                _richness_warnings.append("finish_limited_assets_or_safety")
            if _finish_safety_status == "blocked":
                _richness_warnings.append("finish_safety_blocked")
            if not _shot_rhythm_pack and _pacing_before <= 0.55:
                _richness_warnings.append("shot_rhythm_opportunity_unfulfilled")
            if _music_metadata.get("music_applied") and not _music_in_final:
                _richness_warnings.append("music_planned_not_in_final")
            if _visual_effects_metadata.get("visual_effects_applied") and not _vfx_in_final:
                _richness_warnings.append("vfx_planned_not_in_final")
            if _transition_metadata.get("transition_events") and not _transition_in_final:
                _richness_warnings.append("transition_planned_not_in_final")
            for _transition_warning in _transition_metadata.get("transition_warnings", []) or []:
                if _transition_warning:
                    _richness_warnings.append(str(_transition_warning))
            if _broll_without_transition:
                _richness_warnings.append("broll_without_transition")
            if _static_broll_without_kenburns:
                _richness_warnings.append("static_broll_without_kenburns")
            if _broll_opportunity_unfulfilled:
                _richness_warnings.append("broll_editorial_opportunity_unfulfilled")
            if _broll_limited_assets:
                _richness_warnings.append("broll_asset_missing_or_conflict")
            if _sfx_metadata.get("sfx_warning") == "missing_sfx_worker_assets":
                _richness_warnings.append("sfx_missing_worker_assets")
            _richness_warnings.extend(_final_contract_metadata.get("final_contract_warnings") or [])

            # ── FASE 5: Honest Quality Gate — block false "rich" ──────────────────
            # If hook is weak (< 5) and there is no meaningful editorial action
            # (no fluency edit, no silence cut, no broll, no visual effects),
            # then the clip cannot be "rich" or "good".
            _hook_first3_score_f5 = int((_hook_plan_data or {}).get("hook_first3_score") or 0)
            _hook_fit_acceptable_f5 = bool((_hook_plan_data or {}).get("hook_fit_acceptable"))
            _complete_idea_score_f5 = float(segment.get("complete_idea_score") or 1.0)
            _fluency_score_after_f5 = float(
                segment.get("fluency_score_after")
                or ((_fluency_edit_plan or {}).get("fluency_score_after") if _fluency_edit_plan else 1.0)
                or 1.0
            )
            _has_editorial_action_f5 = bool(
                (_fluency_edit_plan or {}).get("fluency_edit_applied")
                or (_silence_edit_plan_data or {}).get("rendered")
                or _good_broll_phrase_fit
                or _visual_effects_metadata.get("visual_effects_applied")
                or _shot_rhythm_pack
            )
            _honest_gate_reason_f5 = ""
            if _complete_idea_score_f5 < 0.75:
                _honest_gate_reason_f5 = "incomplete_idea"
            elif _fluency_score_after_f5 < 0.70:
                _honest_gate_reason_f5 = "low_fluency"
            elif _hook_first3_score_f5 < 5 and not _hook_fit_acceptable_f5:
                _honest_gate_reason_f5 = "weak_hook"
            elif _hook_first3_score_f5 < 5 and not _has_editorial_action_f5:
                _honest_gate_reason_f5 = "weak_hook_or_no_editorial_action"
            if _honest_gate_reason_f5:
                if _editing_richness_status in {"good", "rich"}:
                    _editing_richness_status = "acceptable"
                _richness_warnings.append(f"rich_blocked_{_honest_gate_reason_f5}")
                logger.info("[quality-gate] rich_blocked reason=%s", _honest_gate_reason_f5)
                logger.info(
                    "[quality-gate] complete_idea=%.2f fluency=%.2f hook_fit=%s editorial_action=%s final_status=%s",
                    _complete_idea_score_f5,
                    _fluency_score_after_f5,
                    str(_hook_fit_acceptable_f5).lower(),
                    str(_has_editorial_action_f5).lower(),
                    _editing_richness_status,
                )
                logger.info("[editing-richness] honest=true status=%s warnings=%s", _editing_richness_status, "|".join(_richness_warnings) or "none")

            try:
                from .vpi_retention_editing_service import build_retention_editing_plan as _build_retention_editing_plan
                from .vpi_retention_editing_service import retention_plan_metadata as _retention_plan_metadata
                _retention_plan_obj = _build_retention_editing_plan(
                    clip_index=clip_index + 1,
                    clip_duration_s=float(duration or 0.0),
                    editorial_type=str(segment.get("editorial_type") or ""),
                    text=str(segment.get("text") or ""),
                    hook_plan=_hook_plan_data,
                    silence_plan=_silence_edit_plan_data,
                    broll_plan={"events": _editorial_broll_for_status},
                    existing_music=_music_metadata,
                    existing_effects=(_visual_effects_metadata or {}).get("visual_effects_events") or [],
                )
                _retention_metadata = _retention_plan_metadata(_retention_plan_obj)
            except Exception as _retention_e:
                logger.warning("[retention-plan] warnings=build_failed:%s", _retention_e)
                _retention_metadata = {"retention_warnings": [str(_retention_e)]}
            _editing_richness_metadata = {
                "editing_richness_score": _editing_richness_score,
                "editing_richness_status": _editing_richness_status,
                "editing_richness_warnings": _richness_warnings,
                "editing_richness_good_broll_phrase_fit": _good_broll_phrase_fit,
                "broll": _broll_true,
                "broll_editorial_opportunity": _broll_opportunity_unfulfilled,
                "broll_limited_assets": _broll_limited_assets,
                "broll_editorial_decision": _broll_editorial_decision_final,
                "broll_asset_match": _broll_asset_match_final,
                "sfx": _sfx_true,
                "sfx_retention_pack": _sfx_retention_pack,
                "sfx_editorial_opportunity": bool(_sfx_opportunity and not _sfx_true),
                "sfx_low_variation": _sfx_low_variation,
                "cinematic_finish_pack": _cinematic_finish_pack,
                "visual_finish": _visual_finish,
                "finish_profile": str((_cinematic_finish_metadata or {}).get("finish_profile") or "none"),
                "finish_safety": _finish_safety_status,
                "finish_limited_assets": _finish_limited_assets,
                "shot_rhythm": _shot_rhythm_plan,
                "shot_rhythm_pack": _shot_rhythm_pack,
                "pacing_score_before": _pacing_before,
                "pacing_score_after": _pacing_after,
                "private_premium_finish_adjustment": "pending",
                "private_premium_status_after_finish": "pending",
                "private_premium_rhythm_adjustment": "pending",
                "private_premium_status_after_rhythm": "pending",
                "editing_richness_final_verified": True,
                **_retention_metadata,
                **_final_contract_metadata,
            }
            logger.info("[editing-richness] final_verified=true score=%d status=%s warnings=%s", _editing_richness_score, _editing_richness_status, "|".join(_richness_warnings) or "none")
            _publish_warnings.extend(_richness_warnings)

            # ── CAMBIO 5: first3_visual_contract — check first 3s visual quality ──
            _first3_visual_contract_result: Dict[str, Any] = {}
            try:
                from .vpi_visual_effects_service import first3_visual_contract as _first3_visual_contract
                _first3_visual_contract_result = _first3_visual_contract(
                    hook_plan=_hook_plan_data,
                    caption_overlay_pack=_caption_overlay_pack_metadata if isinstance(_caption_overlay_pack_metadata, dict) else {},
                    composition_decision=_composition_decision,
                    visual_effects=(_visual_effects_metadata or {}).get("visual_effects_events") or [],
                    transition_plan=_transition_metadata if isinstance(_transition_metadata, dict) else {},
                )
                _first3_passed = _first3_visual_contract_result.get("first3_visual_passed", False)
                _first3_fail_count = _first3_visual_contract_result.get("first3_visual_fail_count", 0)
                logger.info(
                    "[first3-visual-contract] runtime=true passed=%s fail_count=%d",
                    str(_first3_passed).lower(),
                    _first3_fail_count,
                )
            except Exception as _f3_e:
                logger.debug("[first3-visual-contract] runtime skipped reason=%s", _f3_e)
                _first3_visual_contract_result = {}

            _composition_runtime_applied = bool(
                _composition_runtime_applied
                or (_first3_visual_contract_result or {}).get("status") == "pass"
            )
            _composition_pack_active = bool(
                _composition_decision
                and _composition_decision.get("composition_mode")
                and _composition_decision.get("composition_mode") not in ("", "unknown")
                and _composition_runtime_applied
            )
            if (_first3_visual_contract_result or {}).get("status") == "pass" and not _composition_layer_overload:
                _composition_quality = "strong" if (_composition_skipped_layers or _composition_allowed_layers) else "good"
            elif _composition_pack_active and not _composition_layer_overload:
                _composition_quality = "good" if (_composition_skipped_layers or _composition_allowed_layers) else "ok"
            elif _composition_decision and _composition_runtime_applied:
                _composition_quality = "ok"
            else:
                _composition_quality = "poor"
            if isinstance(_composition_decision, dict):
                _composition_decision["composition_pack"] = _composition_pack_active
                _composition_decision["composition_quality"] = _composition_quality
                _composition_decision["layer_overload"] = _composition_layer_overload
                _composition_decision["runtime_connected"] = _composition_runtime_applied

            _publishable_metadata = _determine_publishable_status(
                task_completed=True,
                final_file_exists=Path(output_path).exists(),
                subtitles=bool(add_subtitles and (words_with_confidence or segment.get("text"))),
                output_qc=_output_qc,
                beta_clean=bool(_cfg.beta_clean),
                legacy_runtime=False,
                error_code=None,
                repeated_exact_broll_same_task=_repeated_exact_broll_same_clip,
                weak_intro_forced_broll=_weak_intro_forced_broll,
                warnings=_publish_warnings,
                first3_visual_contract=_first3_visual_contract_result,
            )
            _finish_adjustment = "none"
            _status_after_finish = str(_publishable_metadata.get("private_premium_status") or "")
            if _finish_safety_status == "blocked" and _status_after_finish == "PRIVATE_PREMIUM_READY":
                _publishable_metadata["private_premium_status"] = "PRIVATE_PREMIUM_LIMITED_ASSETS"
                _publishable_metadata["private_premium_reason"] = "finish_limited_assets_or_safety"
                _finish_adjustment = "limited_assets"
                _status_after_finish = "PRIVATE_PREMIUM_LIMITED_ASSETS"
            if _visual_finish and _finish_safety_status == "blocked":
                _publishable_metadata["private_premium_status"] = "PRIVATE_PREMIUM_REVIEW"
                _publishable_metadata["private_premium_reason"] = "finish_safety_degradation"
                _finish_adjustment = "review_due_to_finish_safety"
                _status_after_finish = "PRIVATE_PREMIUM_REVIEW"
            logger.info("[private-premium] finish_adjustment=%s", _finish_adjustment)
            logger.info("[private-premium] status_after_finish=%s", _status_after_finish)
            _publishable_metadata["private_premium_finish_adjustment"] = _finish_adjustment
            _publishable_metadata["private_premium_status_after_finish"] = _status_after_finish
            _rhythm_adjustment = "none"
            _status_after_rhythm = str(_publishable_metadata.get("private_premium_status") or _status_after_finish)
            _fluency_score_rhythm = float(
                segment.get("fluency_score_after")
                or ((_fluency_edit_plan or {}).get("fluency_score_after") if _fluency_edit_plan else 1.0)
                or 1.0
            )
            _hook_fit_ok_rhythm = bool((_hook_plan_data or {}).get("hook_fit_acceptable"))
            if _status_after_rhythm != "DO_NOT_UPLOAD":
                if _pacing_after < 0.58 and (not _hook_fit_ok_rhythm or _fluency_score_rhythm < 0.75):
                    _publishable_metadata["private_premium_status"] = "PRIVATE_PREMIUM_REVIEW"
                    _publishable_metadata["private_premium_reason"] = "low_pacing_rhythm_review"
                    _rhythm_adjustment = "review_low_pacing"
                    _status_after_rhythm = "PRIVATE_PREMIUM_REVIEW"
            logger.info("[private-premium] rhythm_adjustment=%s", _rhythm_adjustment)
            logger.info("[private-premium] status_after_rhythm=%s", _status_after_rhythm)
            _publishable_metadata["private_premium_rhythm_adjustment"] = _rhythm_adjustment
            _publishable_metadata["private_premium_status_after_rhythm"] = _status_after_rhythm
            _composition_downgrade = bool(
                (_first3_visual_contract_result or {}).get("downgrade_required")
                and str(_publishable_metadata.get("private_premium_status") or "") == "PRIVATE_PREMIUM_REVIEW"
            )
            logger.info(
                "[private-premium] status_after_composition=%s",
                str(_publishable_metadata.get("private_premium_status") or ""),
            )
            logger.info(
                "[private-premium] composition_downgrade=%s reason=%s",
                str(_composition_downgrade).lower(),
                (
                    "|".join((_first3_visual_contract_result or {}).get("failed_checks") or [])
                    or "none"
                ),
            )
            _final_qc_report = {}
            try:
                from .vpi_publishable_gate import build_final_qc_report as _build_final_qc_report
                _audio_qc_meta = dict(locals().get("_audio_master_metadata", {}) or {})
                _subtitle_qc_meta = {
                    "captions_rendered": bool(add_subtitles and (words_with_confidence or segment.get("text"))),
                    "hook_first3_score": int((_hook_plan_data or {}).get("hook_first3_score") or 0),
                }
                _final_qc_report = _build_final_qc_report(
                    private_premium_status=str(_publishable_metadata.get("private_premium_status") or ""),
                    editing_richness=_editing_richness_metadata,
                    composition_decision=_composition_decision if isinstance(_composition_decision, dict) else {},
                    first3_visual_contract=_first3_visual_contract_result if isinstance(_first3_visual_contract_result, dict) else {},
                    caption_overlay_pack=_caption_overlay_pack_metadata if isinstance(_caption_overlay_pack_metadata, dict) else {},
                    motion_pack=_visual_effects_metadata if isinstance(_visual_effects_metadata, dict) else {},
                    broll_metadata={
                        "broll_asset_applied_match": _broll_asset_applied_match,
                        "matched": bool(_broll_asset_match_final.get("matched")),
                        "timing_valid": _broll_timing_valid,
                        "composition_allowed": _broll_composition_allowed_final,
                    },
                    sfx_metadata=_sfx_metadata if isinstance(_sfx_metadata, dict) else {},
                    cinematic_finish=_cinematic_finish_metadata if isinstance(_cinematic_finish_metadata, dict) else {},
                    shot_rhythm=_shot_rhythm_plan if isinstance(_shot_rhythm_plan, dict) else {},
                    audio_metadata=_audio_qc_meta,
                    subtitle_metadata=_subtitle_qc_meta,
                    segment_text=str(segment.get("text") or ""),
                )
            except Exception as _final_qc_e:
                logger.warning("[final-qc] build_failed reason=%s", _final_qc_e)
                _final_qc_report = {
                    "final_qc_status": "REVIEW",
                    "upload_recommendation": "REVIEW_MANUALLY",
                    "checks": {},
                    "warnings": [f"final_qc_failed:{_final_qc_e}"],
                    "reasons": ["final_qc_build_failed"],
                    "premium_truth_score": 0.0,
                    "readability_score": 0.0,
                    "audio_score": 0.0,
                    "composition_score": 0.0,
                    "retention_score": 0.0,
                }

            _final_qc_status = str(_final_qc_report.get("final_qc_status") or "REVIEW")
            _final_upload_recommendation = str(_final_qc_report.get("upload_recommendation") or "REVIEW_MANUALLY")
            _status_after_final_qc = str(_publishable_metadata.get("private_premium_status") or "")
            _final_qc_adjustment = "none"
            if _final_qc_status == "FAIL":
                _status_after_final_qc = "DO_NOT_UPLOAD"
                _final_qc_adjustment = "downgrade_do_not_upload"
            elif _final_qc_status == "REVIEW" and _status_after_final_qc != "DO_NOT_UPLOAD":
                _status_after_final_qc = "PRIVATE_PREMIUM_REVIEW"
                _final_qc_adjustment = "downgrade_review"
            _publishable_metadata["private_premium_status"] = _status_after_final_qc
            _publishable_metadata["final_private_premium_status"] = _status_after_final_qc
            _publishable_metadata["final_qc_status"] = _final_qc_status
            _publishable_metadata["final_upload_recommendation"] = _final_upload_recommendation
            _publishable_metadata["final_qc"] = _final_qc_report
            logger.info("[private-premium] final_qc_adjustment=%s", _final_qc_adjustment)
            logger.info("[private-premium] final_status=%s", _status_after_final_qc)
            _editing_richness_metadata.update({
                "composition_decision": _composition_decision,
                "composition_pack": _composition_pack_active,
                "composition_quality": _composition_quality,
                "layer_overload": _composition_layer_overload,
                "first3_visual_contract": _first3_visual_contract_result,
                "composition_runtime_applied": _composition_runtime_applied,
                "cinematic_finish": _cinematic_finish_metadata,
                "private_premium_finish_adjustment": _finish_adjustment,
                "private_premium_status_after_finish": _status_after_finish,
                "shot_rhythm": _shot_rhythm_plan,
                "shot_rhythm_pack": _shot_rhythm_pack,
                "pacing_score_before": _pacing_before,
                "pacing_score_after": _pacing_after,
                "private_premium_rhythm_adjustment": _rhythm_adjustment,
                "private_premium_status_after_rhythm": _status_after_rhythm,
                "final_qc": _final_qc_report,
                "final_qc_status": _final_qc_status,
                "final_upload_recommendation": _final_upload_recommendation,
                "final_private_premium_status": _status_after_final_qc,
            })
            logger.info(
                "[editing-richness] composition_pack=%s reason=%s",
                str(_composition_pack_active).lower(),
                "runtime_connected_and_applied" if _composition_pack_active else "no_runtime_applied_layers",
            )
            logger.info("[editing-richness] composition_quality=%s", _composition_quality)
            logger.info("[editing-richness] layer_overload=%s", str(_composition_layer_overload).lower())
            if _editing_plan_data:
                _editing_plan_data["brand_treatment"] = _brand_metadata
                _editing_plan_data["hook_plan"] = _hook_plan_data
                _editing_plan_data["cta"] = {
                    "strategy": (_editing_plan_data or {}).get("cta_strategy"),
                    "text_options": ["Lo revisamos juntos?", "Valentin Proteccion Integral"],
                    "rendered": False,
                }
                _editing_plan_data["subtitle_intelligence"] = _subtitle_intelligence_metadata
                _editing_plan_data["silence_edit_plan"] = _silence_edit_plan_data
                _editing_plan_data["output_qc"] = _output_qc
                _editing_plan_data["audio_qc"] = locals().get("_audio_master_metadata", {})
                _editing_plan_data["visual_effects"] = _visual_effects_metadata
                _editing_plan_data["transitions"] = _transition_metadata
                _editing_plan_data["music"] = _music_metadata
                _editing_plan_data["sfx"] = _sfx_metadata
                _editing_plan_data["premium_runtime"] = _premium_runtime
                _editing_plan_data["premium_runtime_enabled"] = _premium_runtime["premium_runtime_enabled"]
                _editing_plan_data["premium_layers_requested"] = list(_premium_runtime["premium_layers_requested"])
                _editing_plan_data["speaker_focus"] = _speaker_focus_metadata
                _editing_plan_data["composition_decision"] = _composition_decision
                _editing_plan_data["first3_visual_contract"] = _first3_visual_contract_result
                _editing_plan_data["cinematic_finish"] = _cinematic_finish_metadata
                _editing_plan_data.update(_editing_richness_metadata)
                _editing_plan_data.update(_publishable_metadata)
                _editing_plan_data["hook_quality"] = _hook_quality
            if _hook_plan_data:
                _hook_plan_data["rendered"] = bool(_hook_plan_data.get("rendered"))
                _publishable_metadata["hook_quality"] = _hook_quality
        except Exception as _daily_e:
            logger.warning("[daily-publishing] metadata failed error=%s", _daily_e)
            _brand_metadata = {"type": "metadata_only", "rendered": False, "reason": str(_daily_e)}

        # Phase 5: Final duration guard — ensure clip isn't too short after processing
        try:
            _final_dur = probe_duration(output_path)
            if _final_dur < 10.0:
                logger.warning(
                    "[CLIP-GUARD] Final clip duration %.1fs < 10s minimum — "
                    "silence removal may have cut too aggressively", _final_dur
                )
            elif _final_dur > 90.0:
                logger.warning(
                    "[CLIP-GUARD] Final clip duration %.1fs > 90s maximum — "
                    "consider platform limits", _final_dur
                )
        except Exception as _dur_e:
            logger.debug(f"[CLIP-GUARD] Duration check skipped: {_dur_e}")

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
            "editorial_type": segment.get("editorial_type"),
            "matched_patterns": segment.get("matched_patterns", []),
            "vpi_score": segment.get("vpi_score"),
            "vpi_reason": segment.get("vpi_reason"),
            "suggested_broll_cue_type": segment.get("suggested_broll_cue_type"),
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
            "editorial_broll": locals().get("_editorial_broll_metadata", []),
            "caption_ass_debug_path": locals().get("_caption_ass_debug_path"),
            "editing_plan": _editing_plan_data,
            "hook_plan": _hook_plan_data,
            "silence_edit_plan": _silence_edit_plan_data,
            "smart_reframe": _smart_reframe_metadata,
            "brand_treatment": _brand_metadata,
            "visual_effects": _visual_effects_metadata,
            "transitions": _transition_metadata,
            "music": _music_metadata,
            "sfx": _sfx_metadata,
            "cinematic_finish": _cinematic_finish_metadata,
            "speaker_focus": _speaker_focus_metadata,
            "composition_decision": _composition_decision,
            "premium_runtime": _premium_runtime,
            "premium_runtime_enabled": _premium_runtime["premium_runtime_enabled"],
            "premium_layers_requested": list(_premium_runtime["premium_layers_requested"]),
            **_editing_richness_metadata,
            "subtitle_intelligence": _subtitle_intelligence_metadata,
            "output_qc": _output_qc,
            "audio_qc": locals().get("_audio_master_metadata", {}),
            "audio_mastering_applied": (locals().get("_audio_master_metadata", {}) or {}).get("audio_mastering_applied"),
            "input_lufs": (locals().get("_audio_master_metadata", {}) or {}).get("input_lufs"),
            "output_lufs": (locals().get("_audio_master_metadata", {}) or {}).get("output_lufs"),
            "input_peak": (locals().get("_audio_master_metadata", {}) or {}).get("input_peak"),
            "output_peak": (locals().get("_audio_master_metadata", {}) or {}).get("output_peak"),
            "audio_measurement_method": (locals().get("_audio_master_metadata", {}) or {}).get("audio_measurement_method"),
            "audio_voice_status": (locals().get("_audio_master_metadata", {}) or {}).get("audio_voice_status"),
            "audio_warnings": (locals().get("_audio_master_metadata", {}) or {}).get("audio_warnings", []),
            "publishable_status": _publishable_metadata.get("publishable_status"),
            "publishable_warnings": _publishable_metadata.get("publishable_warnings", []),
            "publishable_score": _publishable_metadata.get("publishable_score"),
            "hook_quality": _publishable_metadata.get("hook_quality"),
            "final_qc": _publishable_metadata.get("final_qc", {}),
            "final_qc_status": _publishable_metadata.get("final_qc_status"),
            "final_upload_recommendation": _publishable_metadata.get("final_upload_recommendation"),
            "final_private_premium_status": _publishable_metadata.get("final_private_premium_status"),
        }
        # Cancel prefetch task if still running
        if _broll_prefetch_task is not None and not _broll_prefetch_task.done():
            _broll_prefetch_task.cancel()

    @staticmethod
    async def apply_single_transition(
        prev_clip_path: Path,
        current_clip_info: Dict[str, Any],
        clip_index: int,
        output_dir: Path,
    ) -> Dict[str, Any]:
        """
        Phase 2.3: apply RAFT optical flow (or FFmpeg xfade) transition between
        the previous clip and the current clip.

        Returns updated clip_info with the transitioned path when successful;
        returns the original clip_info unchanged on any failure.
        """
        current_path = Path(current_clip_info.get("path", ""))
        prev_path = Path(prev_clip_path) if prev_clip_path else None

        if not prev_path or not prev_path.exists() or not current_path.exists():
            logger.debug(
                "[transition] Skipping clip %s — adjacent clip not available",
                clip_index + 1,
            )
            return current_clip_info

        try:
            # OpticalFlowService: priority chain RAFT → xfade → NumPy cross-dissolve
            from .optical_flow_service import OpticalFlowService
            out_name = f"trans_{clip_index:02d}_{current_path.name}"
            out_path = output_dir / out_name
            _ofs = OpticalFlowService()
            _ofs_result = await _ofs.generate_transition(
                clip_a=str(prev_path),
                clip_b=str(current_path),
                duration=0.4,
                output_path=str(out_path),
            )
            if _ofs_result.get("output_path") and Path(_ofs_result["output_path"]).exists():
                logger.info(
                    "[transition] %s transition applied for clip %s → %s",
                    _ofs_result.get("method", "auto").upper(),
                    clip_index + 1,
                    out_name,
                )
                updated = dict(current_clip_info)
                updated["path"] = _ofs_result["output_path"]
                updated["filename"] = Path(_ofs_result["output_path"]).name
                updated["transition_applied"] = _ofs_result.get("method", "auto")
                return updated

        except Exception as e:
            logger.debug("[transition] OpticalFlowService failed for clip %s: %s — trying raw", clip_index + 1, e)
            try:
                from ..video_processing.optical_flow_transitions import (
                    apply_optical_flow_transition,
                    get_transition_capabilities,
                )
                caps = get_transition_capabilities()
                if caps["xfade_available"] or caps["cv2_available"]:
                    out_name = f"trans_{clip_index:02d}_{current_path.name}"
                    out_path = output_dir / out_name
                    loop = asyncio.get_event_loop()
                    success = await loop.run_in_executor(
                        None, apply_optical_flow_transition,
                        prev_path, current_path, out_path, 0.4, "auto",
                    )
                    if success and out_path.exists():
                        updated = dict(current_clip_info)
                        updated["path"] = str(out_path)
                        updated["filename"] = out_name
                        updated["transition_applied"] = caps["best_mode"]
                        return updated
            except Exception as _e2:
                logger.debug("[transition] Fallback also failed: %s", _e2)

        return current_clip_info

    @staticmethod
    def determine_source_type(url: str) -> str:
        """Determine if source is YouTube or uploaded file."""
        video_id = get_youtube_video_id(url)
        return "youtube" if video_id else "video_url"

    @staticmethod
    async def process_video_complete(
        url: str,
        source_type: str,
        task_id: Optional[str] = None,
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        processing_mode: str = "fast",
        output_format: str = "vertical",
        add_subtitles: bool = True,
        include_broll: bool = False,
        split_screen: bool = False,
        target_platform: str = "all",
        url_secondary: Optional[str] = None,
        cached_transcript: Optional[str] = None,
        cached_analysis_json: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str, str], Awaitable[None]]] = None,
        should_cancel: Optional[Callable[[], Awaitable[bool]]] = None,
        num_clips: int = 6,
    ) -> Dict[str, Any]:
        """
        Complete video processing pipeline.
        Returns dict with segments and clips info.

        progress_callback: Optional function to call with progress updates
                          Signature: async def callback(progress: int, message: str, status: str)
        """
        try:
            # Initialize metrics collector for this pipeline
            metrics = get_metrics_collector().start_pipeline(task_id or "unknown")
            
            # Step 1: Get video path (download or use existing)
            if should_cancel and await should_cancel():
                raise Exception("Task cancelled")

            if progress_callback:
                await progress_callback(10, "Downloading video...", "processing")

            if source_type == "youtube":
                video_info = await async_get_youtube_video_info(url, task_id=task_id)
                if video_info:
                    cfg = get_service_config()
                    duration = video_info.get("duration", 0)
                    if duration and duration > cfg.max_video_duration:
                        mins = cfg.max_video_duration // 60
                        raise Exception(
                            f"Video is too long ({duration // 60} min). "
                            f"Maximum allowed duration is {mins} minutes."
                        )

                video_path = await VideoService.download_video(url, task_id=task_id)
                if not video_path:
                    raise Exception("Failed to download video")
            else:
                video_path = VideoService.resolve_local_video_path(url)
                if not video_path.exists():
                    raise Exception("Video file not found")

            # Post-download duration guard (catches cases where preflight info was unavailable)
            file_duration = VideoService._get_file_duration(video_path)
            if file_duration:
                cfg = get_service_config()
                if file_duration > cfg.max_video_duration:
                    mins = cfg.max_video_duration // 60
                    raise Exception(
                        f"Video is too long ({int(file_duration) // 60} min). "
                        f"Maximum allowed duration is {mins} minutes."
                    )

            # Step 2: Generate transcript (with Smart Cache and retries)
            if should_cancel and await should_cancel():
                raise Exception("Task cancelled")

            if progress_callback:
                await progress_callback(30, "Generating transcript...", "processing")

            # Try Smart Cache first (Redis + local + disk fallback)
            cache_manager = get_cache_manager()
            cached_transcript_data = await get_cached_transcript_smart(video_path) if not cached_transcript else None
            
            if cached_transcript:
                transcript = cached_transcript
                logger.info("[CACHE] Using provided cached transcript")
            elif cached_transcript_data:
                transcript = cached_transcript_data.get("text", "")
                logger.info(f"[CACHE] Smart cache HIT for transcript: {len(transcript)} chars")
            else:
                # Generate with retry logic for transient failures
                transcript = await execute_with_recovery(
                    VideoService.generate_transcript,
                    video_path, 
                    processing_mode,
                    max_retries=2,
                    context={"stage": "transcription", "video_path": str(video_path)}
                )
                # Cache in all layers
                await cache_transcript_smart(
                    video_path,
                    {"text": transcript, "timestamp": datetime.now().isoformat()}
                )
                logger.info(f"[CACHE] Saved transcript to smart cache: {len(transcript)} chars")

            # Step 2.5: Analyze content niche for optimization
            if progress_callback:
                await progress_callback(35, "Analyzing content niche and trends...", "processing")
            
            niche_analysis = analyze_content_niche(transcript)
            logger.info(f"Content niche detected: {niche_analysis.primary_niche} (confidence: {niche_analysis.confidence:.2f})")
            logger.info(f"Platform optimization: {niche_analysis.platform_optimization}")
            
            # Get platform-specific optimization
            platform_opt = optimize_for_platform(niche_analysis, target_platform if target_platform != "all" else "tiktok")
            
            # Store niche info for later use
            niche_info = {
                "primary_niche": niche_analysis.primary_niche,
                "confidence": niche_analysis.confidence,
                "trending_keywords": niche_analysis.trending_keywords,
                "optimal_duration": platform_opt["recommended_duration"],
                "content_tips": platform_opt["niche_specific_tips"],
            }

            # Step 3: AI analysis (with Smart Cache)
            if should_cancel and await should_cancel():
                raise Exception("Task cancelled")

            if progress_callback:
                await progress_callback(
                    50, "Analyzing content with AI...", "processing"
                )

            # _SimpleResult wraps any dict-based analysis result (DB cache, disk cache, or fresh)
            class _SimpleResult:
                def __init__(self, payload: Dict[str, Any]):
                    self.summary = payload.get("summary")
                    self.key_topics = payload.get("key_topics")
                    self.most_relevant_segments = payload.get(
                        "most_relevant_segments", []
                    )
                    self.broll_opportunities = payload.get("broll_opportunities")

            relevant_parts = None
            
            # Try cached analysis from parameter first
            if cached_analysis_json:
                try:
                    cached_analysis = json.loads(cached_analysis_json)
                    segments = cached_analysis.get("most_relevant_segments", [])
                    relevant_parts = _SimpleResult(
                        {
                            "summary": cached_analysis.get("summary"),
                            "key_topics": cached_analysis.get("key_topics", []),
                            "most_relevant_segments": segments,
                            "broll_opportunities": cached_analysis.get("broll_opportunities"),
                        }
                    )
                    logger.info("[CACHE] Using provided cached AI analysis")
                except Exception as e:
                    logger.error(f"[CACHE] Failed to parse cached AI analysis: {e}", exc_info=True)
                    relevant_parts = None
            
            # Try Smart Cache for AI analysis
            if relevant_parts is None:
                video_hash = cache_manager._generate_file_hash(video_path)
                cached_ai = await cache_manager.get("ai_analysis", video_hash)
                if cached_ai:
                    relevant_parts = _SimpleResult(cached_ai["data"])
                    logger.info(f"[CACHE] Smart cache HIT for AI analysis: {len(cached_ai['data'].get('most_relevant_segments', []))} segments")

            if relevant_parts is None:
                if get_service_config().beta_clean:
                    logger.info("[beta-clean] local segment selection only")
                    from .vpi_retention_editing_service import build_clean_take_candidates

                    _pool = build_clean_take_candidates(
                        transcript,
                        transcript_duration_s=float(file_duration or 0.0),
                        num_clips=num_clips,
                    )
                    _segments = list(_pool.get("segments") or [])
                    if not _segments:
                        segment_end = min(file_duration or 30.0, 60.0)
                        end_minutes = int(segment_end) // 60
                        end_seconds = int(segment_end) % 60
                        _segments = [
                            {
                                "start_time": "00:00",
                                "end_time": f"{end_minutes:02d}:{end_seconds:02d}",
                                "text": transcript,
                                "relevance_score": 0.5,
                                "virality_score": 40,
                                "reasoning": "beta-clean local segment fallback",
                            }
                        ]
                    relevant_parts = _SimpleResult(
                        {
                            "summary": None,
                            "key_topics": _pool.get("topics", []),
                            "most_relevant_segments": _segments,
                            "broll_opportunities": [],
                        }
                    )
                else:
                    # AI analysis with retry logic
                    relevant_parts = await execute_with_recovery(
                        VideoService.analyze_transcript,
                        transcript,
                        video_duration=file_duration or 0.0,
                        include_broll=include_broll,
                        max_retries=2,
                        context={"stage": "ai_analysis", "task_id": task_id}
                    )
                    # Cache in smart cache
                    cache_payload = {
                        "summary": getattr(relevant_parts, "summary", None),
                        "key_topics": getattr(relevant_parts, "key_topics", []),
                        "most_relevant_segments": [
                            s if isinstance(s, dict) else (s.model_dump() if hasattr(s, "model_dump") else vars(s))
                            for s in (relevant_parts.most_relevant_segments or [])
                        ],
                        "broll_opportunities": [
                            o if isinstance(o, dict) else (o.model_dump() if hasattr(o, "model_dump") else vars(o))
                            for o in (getattr(relevant_parts, "broll_opportunities", None) or [])
                        ],
                    }
                    await cache_manager.set("ai_analysis", video_hash, cache_payload)
                    logger.info(f"[CACHE] Saved AI analysis to smart cache")

            if get_service_config().beta_clean:
                try:
                    from .vpi_retention_editing_service import build_clean_take_candidates

                    _existing_segments = list(getattr(relevant_parts, "most_relevant_segments", []) or [])
                    _pool = build_clean_take_candidates(
                        transcript,
                        transcript_duration_s=float(file_duration or 0.0),
                        num_clips=num_clips,
                    )
                    _pool_segments = list(_pool.get("segments") or [])
                    if len(_pool_segments) > len(_existing_segments):
                        relevant_parts.most_relevant_segments = _pool_segments
                        relevant_parts.key_topics = _pool.get("topics", [])
                        logger.info(
                            "[candidate-pool-source] replacing_initial_segments existing=%d clean_pool=%d",
                            len(_existing_segments),
                            len(_pool_segments),
                        )
                    else:
                        logger.info(
                            "[candidate-pool-source] keeping_initial_segments existing=%d clean_pool=%d",
                            len(_existing_segments),
                            len(_pool_segments),
                        )
                except Exception as _pool_e:
                    logger.warning("[candidate-pool-source] failed reason=%s", _pool_e)

            # Step 3.1: Elite Creative Direction — bypassed (Groq 400/429 always fails)
            if progress_callback:
                await progress_callback(55, "Preparing creative plan...", "processing")
            from .elite_ai_service import EliteCreativePlan as _EliteCreativePlan
            elite_plan = _EliteCreativePlan(
                clips=[], global_vibe="Standard", brand_consistency_plan="Default brand voice",
                custom_hashtags=[]
            )
            logger.info("EliteAI: bypassed — using minimal plan (0 clips)")
            
            # Map Elite plans to the segments for metadata propagation
            elite_map = {
                (p.start_time, p.end_time): p 
                for p in elite_plan.clips
            }

            # Step 3.5: Virality metadata for ranking.
            if progress_callback:
                await progress_callback(60, "Predicting virality with local scoring...", "processing")

            if get_service_config().beta_clean:
                logger.info("[beta-clean] local virality scoring only")
                virality_map = {
                    idx: {
                        "segment_index": idx,
                        "virality_score": (
                            segment.get("virality_score", 40)
                            if isinstance(segment, dict)
                            else getattr(segment, "virality_score", 40)
                        ),
                    }
                    for idx, segment in enumerate(relevant_parts.most_relevant_segments)
                }
            else:
                # Prepare segments for LLM (with improved service)
                segment_texts = [s.get("text") if isinstance(s, dict) else s.text for s in relevant_parts.most_relevant_segments]

                # Use improved LLM service with validation + text-based fallback
                from .llm_service_improved import ImprovedLLMService
                llm_service = ImprovedLLMService()
                virality_data = await llm_service.get_virality_analysis(segment_texts)
                virality_map = {item.get("segment_index"): item for item in virality_data.get("analysis", [])}

                # Log scoring method used
                if virality_map:
                    first_reasoning = list(virality_map.values())[0].get("reasoning", "")
                    if "fallback" in first_reasoning.lower():
                        logger.info("Text-based virality scoring fallback active")
                    else:
                        logger.info("AI virality scoring active")
                    
                # Quality check: warn if scores look suspicious
                avg_score = sum(item.get("virality_score", 0) for item in virality_map.values()) / len(virality_map)
                if avg_score < 20:
                    logger.warning(f"⚠️ Low average virality score ({avg_score:.1f}/100) - segments may not be very viral")

            # Prepare B-roll suggestions if requested
            # NOTE: BrollService doesn't implement get_broll_for_opportunity - using process_clip instead
            all_broll_suggestions = []
            # if include_broll and relevant_parts.broll_opportunities:
            #     for opp in relevant_parts.broll_opportunities:
            #         suggestion = broll_service.get_broll_for_opportunity(opp.model_dump() if hasattr(opp, "model_dump") else opp)
            #         if suggestion:
            #             all_broll_suggestions.append(suggestion)

            # B.4: YOLO-based B-roll detection (opt-in via BROLL_ENABLED=true)
            # NOTE: analyze_video_objects and get_broll_for_detected_objects don't exist in BrollService
            from ..config import get_config as _get_cfg_b4
            _cfg_b4 = _get_cfg_b4()
            if False and getattr(_cfg_b4, "broll_enabled", False) and video_path:
                try:
                    logger.info("🔍 B.4: Running YOLOv8 object detection for B-roll...")
                    broll_service = BrollService()
                    detected_objects = await run_in_thread(
                        broll_service.analyze_video_objects, video_path
                    )
                    if detected_objects:
                        yolo_broll = await run_in_thread(
                            broll_service.get_broll_for_detected_objects, detected_objects
                        )
                        if yolo_broll:
                            all_broll_suggestions.append({
                                "local_path": str(yolo_broll),
                                "timestamp": 0,
                                "duration": 5.0,
                                "context": f"yolo:{','.join(detected_objects[:2])}",
                            })
                            logger.info(f"✅ B.4: YOLO B-roll prepared: {yolo_broll.name}")
                except Exception as _yolo_e:
                    logger.warning(f"B.4 YOLO B-roll skipped: {_yolo_e}")

            # Step 4: Create clips
            if should_cancel and await should_cancel():
                raise Exception("Task cancelled")

            if progress_callback:
                await progress_callback(70, "Creating video clips...", "processing")

            raw_segments = relevant_parts.most_relevant_segments
            segments_json: List[Dict[str, Any]] = []
            _editorial_fields = (
                "moment_type",
                "hook_quote",
                "editorial_score",
                "editorial_type",
                "matched_patterns",
                "vpi_score",
                "vpi_reason",
                "vpi_generic_penalty",
                "suggested_broll_cue_type",
                "standalone_clarity_score",
                "completion_score",
                "insurance_relevance_score",
                "commercial_value_score",
                "specificity_score",
                "emotional_trust_score",
                "filler_penalty",
                "generic_motivation_penalty",
                "incomplete_argument_penalty",
                "long_context_penalty",
                "duplicate_theme_key",
            )

            def _safe_float(value: Any) -> Optional[float]:
                try:
                    if value is None or value == "":
                        return None
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def _clamp01(value: float) -> float:
                return max(0.0, min(1.0, value))

            def _normalized_virality(value: Any) -> Optional[float]:
                score = _safe_float(value)
                if score is None:
                    return None
                if score <= 10.0:
                    return _clamp01(score / 10.0)
                return _clamp01(score / 100.0)

            def _compute_base_rank_score(seg: Dict[str, Any]) -> float:
                editorial = _safe_float(seg.get("editorial_score"))
                virality = _normalized_virality(seg.get("virality_score"))

                if editorial is not None:
                    editorial = _clamp01(editorial if editorial <= 1.0 else editorial / 100.0)
                if editorial is not None and virality is not None:
                    return _clamp01(0.7 * editorial + 0.3 * virality)
                if editorial is not None:
                    return editorial
                if virality is not None:
                    return virality
                return 0.0

            def _compute_final_rank_score(seg: Dict[str, Any]) -> float:
                base = _compute_base_rank_score(seg)
                vpi_score = _safe_float(seg.get("vpi_score"))
                generic_penalty = _safe_float(seg.get("vpi_generic_penalty")) or 0.0
                if vpi_score is None:
                    return base

                vpi_boost = _clamp01(vpi_score / 100.0) * 0.35
                penalty = _clamp01(generic_penalty / 100.0) * 0.15
                return _clamp01(base + vpi_boost - penalty)

            def _extract_editorial_fields(src: Any) -> Dict[str, Any]:
                data: Dict[str, Any] = {}
                virality_obj = None
                if isinstance(src, dict):
                    virality_obj = src.get("virality")
                else:
                    virality_obj = getattr(src, "virality", None)

                for field in _editorial_fields:
                    value = src.get(field) if isinstance(src, dict) else getattr(src, field, None)
                    if value is None and virality_obj is not None:
                        if isinstance(virality_obj, dict):
                            value = virality_obj.get(field)
                        else:
                            value = getattr(virality_obj, field, None)
                    if value is not None:
                        data[field] = value
                return data

            _vpi_scorer = None
            if get_service_config().beta_clean:
                try:
                    from .vpi_editorial_scorer import VPIEditorialScorer
                    _vpi_scorer = VPIEditorialScorer()
                except Exception as _vpi_import_e:
                    logger.warning("[vpi-scorer] unavailable: %s", _vpi_import_e)

            def _apply_vpi_score(seg: Dict[str, Any]) -> Dict[str, Any]:
                if _vpi_scorer is None:
                    return seg

                scored = _vpi_scorer.score(seg.get("text", ""))
                seg["vpi_score"] = scored.vpi_score
                seg["matched_patterns"] = scored.matched_patterns
                seg["editorial_type"] = scored.editorial_type
                seg["vpi_reason"] = scored.reason
                seg["vpi_generic_penalty"] = scored.generic_penalty
                if scored.suggested_broll_cue_type:
                    seg["suggested_broll_cue_type"] = scored.suggested_broll_cue_type

                logger.info(
                    "[vpi-scorer] segment=%s→%s type=%s boost=%.2f patterns=%s",
                    seg.get("start_time", "?"),
                    seg.get("end_time", "?"),
                    scored.editorial_type,
                    scored.vpi_score,
                    ",".join(scored.matched_patterns[:5]) or "-",
                )
                return seg

            def _apply_final_rank(seg: Dict[str, Any]) -> Dict[str, Any]:
                base = _compute_base_rank_score(seg)
                seg["final_rank_score"] = _compute_final_rank_score(seg)
                if seg.get("vpi_score") is not None:
                    logger.info(
                        "[vpi-scorer] final_score=%.3f base=%.3f vpi=%.2f",
                        seg["final_rank_score"],
                        base,
                        _safe_float(seg.get("vpi_score")) or 0.0,
                    )
                return seg

            def _apply_content_quality_filter(items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
                try:
                    from .vpi_retention_editing_service import filter_content_quality_candidates
                    return filter_content_quality_candidates(items, requested=num_clips)
                except Exception as _cq_e:
                    logger.warning("[content-quality] skipped reason=%s", _cq_e)
                    return items, []

            def _dedupe_editorial_segments(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                best_by_key: Dict[str, Dict[str, Any]] = {}
                result: List[Dict[str, Any]] = []
                for item in items:
                    _apply_final_rank(item)
                    key = item.get("duplicate_theme_key")
                    if not key:
                        result.append(item)
                        continue
                    current = best_by_key.get(str(key))
                    if current is None:
                        best_by_key[str(key)] = item
                        continue
                    if item.get("final_rank_score", 0.0) > current.get("final_rank_score", 0.0):
                        logger.info(
                            "[EDITORIAL] dedup duplicate_theme_key=%s kept_later=%.3f dropped=%.3f",
                            key,
                            item.get("final_rank_score", 0.0),
                            current.get("final_rank_score", 0.0),
                        )
                        best_by_key[str(key)] = item
                    else:
                        logger.info(
                            "[EDITORIAL] dedup duplicate_theme_key=%s kept=%.3f dropped=%.3f",
                            key,
                            current.get("final_rank_score", 0.0),
                            item.get("final_rank_score", 0.0),
                        )
                return result + list(best_by_key.values())

            def _enforce_min_duration_dict(seg: Dict[str, Any], min_secs: float = 18.0, max_extension_secs: float = 3.0) -> Dict[str, Any]:
                """Apply conservative boundary handling to cached dict segments."""
                def _ts(ts: str) -> float:
                    try:
                        parts = ts.strip().split(":")
                        return int(parts[0]) * 60 + float(parts[1]) if len(parts) == 2 else float(parts[0])
                    except Exception:
                        return 0.0
                def _fmt(s: float) -> str:
                    return f"{int(s)//60:02d}:{int(s)%60:02d}"
                start = _ts(seg.get("start_time", "00:00"))
                end = _ts(seg.get("end_time", "00:00"))
                duration = max(0.0, end - start)
                if duration >= min_secs:
                    return seg

                new_end = end
                if duration > 0:
                    new_end = end + max_extension_secs
                    if file_duration and file_duration > 0:
                        new_end = min(new_end, file_duration)

                if new_end > end:
                    extension = new_end - end
                    logger.warning(
                        "[EDITORIAL] short cached segment: conservative expansion +%.1fs, not forcing 18s",
                        extension,
                    )
                    seg = dict(seg, end_time=_fmt(new_end))
                else:
                    logger.warning(
                        "[EDITORIAL] short cached segment %.1fs kept unchanged; cannot safely expand",
                        duration,
                    )
                return seg

            for idx, segment in enumerate(raw_segments):
                if isinstance(segment, dict):
                    segment = _enforce_min_duration_dict(segment)
                    # Segments from cache arrive as dicts — still apply virality_map
                    v_info = virality_map.get(idx, {})
                    elite_data = elite_map.get((segment.get("start_time"), segment.get("end_time")))
                    raw_virality = v_info.get("virality_score", segment.get("virality_score", 0))
                    item = {
                        "start_time": segment.get("start_time"),
                        "end_time": segment.get("end_time"),
                        "text": segment.get("text", ""),
                        "relevance_score": segment.get("relevance_score", 0.0),
                        "reasoning": v_info.get("reasoning", segment.get("reasoning", "")),
                        "virality_score": raw_virality,
                        "hook_score": v_info.get("hook_score", raw_virality // 4),
                        "engagement_score": v_info.get("engagement_score", raw_virality // 4),
                        "value_score": v_info.get("value_score", raw_virality // 4),
                        "shareability_score": v_info.get("shareability_score", raw_virality // 4),
                        "hook_strength": v_info.get("hook_strength", "Medium"),
                        "hook_type": v_info.get("hook_type"),
                        "suggested_title": v_info.get("suggested_title", segment.get("suggested_title", "")),
                        "suggested_hashtags": v_info.get("suggested_hashtags", segment.get("suggested_hashtags", [])),
                        "theme": segment.get("theme"),
                        "suggested_edits": segment.get("suggested_edits"),
                        "viral_cues": v_info.get("viral_cues"),
                        "split_screen": split_screen,
                        "elite_metadata": elite_data.model_dump() if elite_data else None,
                    }
                    item.update(_extract_editorial_fields(segment))
                    _apply_vpi_score(item)
                    segments_json.append(_apply_final_rank(item))
                else:
                    v_info = virality_map.get(idx, {})

                    elite_data = elite_map.get((segment.start_time, segment.end_time))
                    raw_virality = v_info.get("virality_score", 0)
                    # Distribute composite virality into 4 component scores if they aren't provided
                    item = {
                        "start_time": segment.start_time,
                        "end_time": segment.end_time,
                        "text": segment.text,
                        "relevance_score": segment.relevance_score,
                        "reasoning": v_info.get("reasoning", segment.reasoning),
                        "virality_score": raw_virality,
                        "hook_score": v_info.get("hook_score", raw_virality // 4),
                        "engagement_score": v_info.get("engagement_score", raw_virality // 4),
                        "value_score": v_info.get("value_score", raw_virality // 4),
                        "shareability_score": v_info.get("shareability_score", raw_virality // 4),
                        "hook_strength": v_info.get("hook_strength", "Medium"),
                        "hook_type": v_info.get("hook_type"),
                        "suggested_title": v_info.get("suggested_title", ""),
                        "suggested_hashtags": v_info.get("suggested_hashtags", []),
                        "theme": segment.theme,
                        "suggested_edits": segment.suggested_edits,
                        "viral_cues": v_info.get("viral_cues"),
                        "broll_suggestions": [s for s in all_broll_suggestions if s["timestamp"] >= parse_timestamp_to_seconds(segment.start_time) and s["timestamp"] <= parse_timestamp_to_seconds(segment.end_time)],
                        "split_screen": split_screen,
                        "elite_metadata": elite_data.model_dump() if elite_data else None,
                    }
                    item.update(_extract_editorial_fields(segment))
                    _apply_vpi_score(item)
                    segments_json.append(_apply_final_rank(item))

            propagated = sorted({field for seg in segments_json for field in _editorial_fields if field in seg})
            if propagated:
                logger.info("[EDITORIAL] propagated_fields=%s", ",".join(propagated))
                logger.info("[EDITORIAL] ranking uses editorial_score/final_rank_score")
            segments_json = _dedupe_editorial_segments(segments_json)
            _candidate_pool_generated = len(segments_json)
            segments_json, _content_quality_rejections = _apply_content_quality_filter(segments_json)
            logger.info(
                "[candidate-pool] generated=%d after_quality_filter=%d",
                _candidate_pool_generated,
                len(segments_json),
            )

            # ── CAUSA 5 guard: pad with synthetic segments if AI returned too few ──
            if len(segments_json) < num_clips and file_duration and file_duration > 0:
                needed = (num_clips + 2) - len(segments_json)
                logger.warning(
                    f"[SEGMENT-PAD] AI returned only {len(segments_json)} segments "
                    f"(need {num_clips}). Generating {needed} synthetic fallback segments."
                )
                _seg_dur = 30.0
                _spacing = file_duration / (needed + 1)
                def _fmt_ts(s: float) -> str:
                    return f"{int(s) // 60:02d}:{int(s) % 60:02d}"
                for _pi in range(needed):
                    _start = max(0.0, _spacing * (_pi + 1) - _seg_dur / 2)
                    _start = min(_start, max(0.0, file_duration - _seg_dur))
                    _end = min(_start + _seg_dur, file_duration)
                    if _end - _start < 10.0:
                        continue
                    segments_json.append({
                        "start_time": _fmt_ts(_start),
                        "end_time": _fmt_ts(_end),
                        "text": "",
                        "relevance_score": 0.5,
                        "reasoning": "Synthetic fallback segment (AI returned too few)",
                        "virality_score": 40 + _pi * 5,
                        "hook_score": 10, "engagement_score": 10,
                        "value_score": 10, "shareability_score": 10,
                        "hook_strength": "Low",
                        "hook_type": "content",
                        "suggested_title": f"Clip {len(segments_json) + 1}",
                        "suggested_hashtags": [],
                        "split_screen": split_screen,
                        "elite_metadata": None,
                    })
                    _apply_vpi_score(segments_json[-1])
                    _apply_final_rank(segments_json[-1])
                logger.info(
                    f"[SEGMENT-PAD] Now have {len(segments_json)} segments after padding"
                )
            segments_json = _dedupe_editorial_segments(segments_json)
            _candidate_pool_after_pad = len(segments_json)
            segments_json, _more_quality_rejections = _apply_content_quality_filter(segments_json)
            _content_quality_rejections.extend(_more_quality_rejections)
            logger.info(
                "[candidate-pool] generated=%d after_quality_filter=%d",
                _candidate_pool_after_pad,
                len(segments_json),
            )
            segments_json.sort(key=lambda x: x.get("final_rank_score", _compute_final_rank_score(x)), reverse=True)
            if get_service_config().beta_clean and num_clips >= 3:
                _topic_priority = ("decesos", "salud", "autonomos")
                _selected_topic_segments: List[Dict[str, Any]] = []
                _selected_ids: set[int] = set()
                for _topic in _topic_priority:
                    _topic_match = next(
                        (
                            seg for seg in segments_json
                            if str(seg.get("clean_take_topic") or "") == _topic
                            and id(seg) not in _selected_ids
                        ),
                        None,
                    )
                    if _topic_match is not None:
                        _selected_topic_segments.append(_topic_match)
                        _selected_ids.add(id(_topic_match))
                        logger.info(
                            "[clip-topic] selected topic=%s start=%s end=%s",
                            _topic,
                            _topic_match.get("start_time"),
                            _topic_match.get("end_time"),
                        )
                if len(_selected_topic_segments) >= min(num_clips, len(_topic_priority)):
                    _rest = [seg for seg in segments_json if id(seg) not in _selected_ids]
                    segments_json = _selected_topic_segments + _rest
            # ── Render a buffer of +2 extra segments so that if 1-2 clips fail to
            # render the save loop can still fill the requested quota.
            # The save loop in task_service.py caps successful saves at num_clips.
            render_buffer = min(max(num_clips + 5, 8), 12)
            segments_json = segments_json[:render_buffer]
            logger.info(
                f"[PIPELINE] Selected {len(segments_json)} segments for render "
                f"(quota={num_clips}, buffer={render_buffer})"
            )
            logger.info("[candidate-pool] after_diversity=%d", len(segments_json))

            # Step 4.5: Apply hook pattern analysis to enhance virality scoring
            if progress_callback:
                await progress_callback(75, "Analyzing viral hooks and patterns...", "processing")
            
            # Enhance segments with hook analysis
            for segment in segments_json:
                segment_text = segment.get("text", "")
                if segment_text:
                    # Analyze hook patterns in the segment text
                    hook_result = analyze_segment_virality(segment_text)
                    
                    # Boost virality score based on detected hooks (up to +20%)
                    hook_bonus = hook_result["virality_score"] * 0.2
                    segment["virality_score"] = min(100, segment.get("virality_score", 0) + hook_bonus)
                    
                    # Add hook analysis metadata
                    segment["hook_analysis"] = {
                        "detected_hooks": [
                            {
                                "type": h.pattern_type,
                                "confidence": h.confidence,
                                "text": h.text
                            }
                            for h in hook_result["hook_analysis"]["detected_hooks"][:3]  # Top 3
                        ],
                        "hook_density": hook_result["hook_analysis"]["hook_density"],
                        "primary_hook_type": hook_result["hook_analysis"]["primary_hook_type"],
                        "retention_mechanisms": hook_result["retention_analysis"]["mechanisms"],
                        "recommendations": hook_result["recommendations"],
                    }
                    
                    # Update hook_type if not already set
                    if not segment.get("hook_type") and hook_result["hook_analysis"]["primary_hook_type"]:
                        segment["hook_type"] = hook_result["hook_analysis"]["primary_hook_type"]
            
            # Re-rank after hook re-score while preserving editorial priority.
            segments_json = _dedupe_editorial_segments(segments_json)
            segments_json.sort(key=lambda x: x.get("final_rank_score", _compute_final_rank_score(x)), reverse=True)

            # ── Weak Intro Gate v2.6 ─────────────────────────────────────
            # Do not spend publishable slots on generic greetings when enough
            # stronger editorial candidates exist.
            _strong_editorial_types = {
                "emotional_protection",
                "family_responsibility",
                "client_objection",
                "myth_debunk",
                "risk_warning",
                "coverage_explanation",
                "actionable_advice",
            }

            def _is_weak_intro_candidate(_segment: Dict[str, Any]) -> bool:
                _editorial = str(_segment.get("editorial_type") or "").lower()
                _matched = " ".join(str(item or "") for item in (_segment.get("matched_patterns") or [])).lower()
                _text_norm = str(_segment.get("text") or "").lower().strip()
                return (
                    _editorial == "weak_intro"
                    or "weak_intro" in _matched
                    or _text_norm.startswith("hola soy")
                    or "en este momento les vengo" in _text_norm
                )

            _weak_intro_excluded_count = 0
            _weak_intro_selected_reason = ""
            _weak_intro_candidates = [seg for seg in segments_json if _is_weak_intro_candidate(seg)]
            _strong_candidates = [
                seg
                for seg in segments_json
                if not _is_weak_intro_candidate(seg)
                and str(seg.get("editorial_type") or "").lower() in _strong_editorial_types
            ]
            if _weak_intro_candidates and len(_strong_candidates) >= num_clips:
                _weak_intro_excluded_count = len(_weak_intro_candidates)
                for _seg in _weak_intro_candidates:
                    _seg["low_publish_priority"] = True
                    _seg["weak_intro_selected_reason"] = "excluded_better_editorial_candidates"
                segments_json = [seg for seg in segments_json if not _is_weak_intro_candidate(seg)]
                _weak_intro_selected_reason = "excluded_better_editorial_candidates"
                logger.info("[clip-selection-gate] weak_intro excluded reason=better_editorial_candidates count=%d", _weak_intro_excluded_count)
            elif _weak_intro_candidates:
                _weak_intro_selected_reason = "not_enough_strong_candidates"
                for _seg in _weak_intro_candidates:
                    _score_before_gate = float(_seg.get("final_rank_score", _compute_final_rank_score(_seg)) or 0.0)
                    _seg["score_before_weak_intro_gate"] = _score_before_gate
                    _seg["weak_intro_penalty"] = 35.0
                    _seg["final_rank_score"] = max(0.0, _score_before_gate - 35.0)
                    _seg["low_publish_priority"] = True
                    _seg["weak_intro_selected_reason"] = "not_enough_strong_candidates"
                segments_json.sort(key=lambda x: x.get("final_rank_score", _compute_final_rank_score(x)), reverse=True)
                logger.info("[clip-selection-gate] weak_intro allowed reason=not_enough_strong_candidates count=%d", len(_weak_intro_candidates))

            # ── Segment Diversity v1.9 — cross-run diversity layer ──────────
            # Applies post-ranking penalties for recently-selected segments.
            _diversity_metadata: Dict[str, Any] = {}
            try:
                from .vpi_segment_memory import (
                    adjust_segments_for_diversity as _adjust_diversity,
                    remember_selected_segments as _remember_segments,
                )
                segments_json, _diversity_metadata = _adjust_diversity(
                    segments_json,
                    source_video_path=str(video_path) if video_path else None,
                    num_clips=num_clips,
                )
            except Exception as _div_e:
                logger.warning("[segment-diversity] integration error: %s", _div_e)
                _diversity_metadata = {"diversity_enabled": False, "error": str(_div_e)}

            if isinstance(_diversity_metadata, dict):
                _diversity_metadata["weak_intro_excluded_count"] = _weak_intro_excluded_count
                _diversity_metadata["weak_intro_selected_reason"] = _weak_intro_selected_reason
                _diversity_metadata["content_quality_rejections"] = _content_quality_rejections
                _diversity_metadata["editorial_mix_selected"] = [
                    str(seg.get("editorial_type") or "") for seg in segments_json[:num_clips]
                ]

            # Add niche info to segments
            for segment in segments_json:
                segment["niche_info"] = niche_info

            # CRITICAL VALIDATION before return
            logger.info(f"[PIPELINE RETURN] Preparing return with {len(segments_json)} segments")
            if len(segments_json) == 0:
                logger.error(
                    f"[PIPELINE RETURN] ❌❌❌ CRITICAL ERROR: segments_json is EMPTY at return! "
                    f"Task will complete with 0 clips. "
                    f"raw_segments count was: {len(raw_segments)}, "
                    f"relevant_parts.most_relevant_segments: {len(relevant_parts.most_relevant_segments) if relevant_parts else 'N/A'}"
                )
            else:
                top_virality = segments_json[0].get("virality_score", 0)
                logger.info(f"[PIPELINE RETURN] Top segment virality: {top_virality}")

            # Step 5: RENDER CLIPS TO DISK
            clips_info = []
            if len(segments_json) > 0 and video_path:
                if should_cancel and await should_cancel():
                    raise Exception("Task cancelled")

                if progress_callback:
                    await progress_callback(80, "Rendering clips to disk...", "processing")

                logger.info(f"[CLIP RENDERING] Starting rendering of {len(segments_json[:num_clips])} clips...")
                try:
                    clips_info = await VideoService.create_video_clips_parallel(
                        video_path=video_path,
                        segments=segments_json[:num_clips],  # Render top N clips
                        task_id=task_id or "full_test",
                        font_family=font_family,
                        font_size=font_size,
                        font_color=font_color,
                        caption_template=caption_template,
                        output_format=output_format,
                        add_subtitles=add_subtitles,
                        include_broll=include_broll,
                    )
                    logger.info(f"[CLIP RENDERING] ✅ Successfully rendered {len([c for c in clips_info if c])} clips")
                except Exception as render_error:
                    logger.error(f"[CLIP RENDERING] ❌ Failed to render clips: {render_error}", exc_info=True)
                    # Don't fail the entire pipeline if rendering fails
                    clips_info = []

                if progress_callback:
                    await progress_callback(90, "Finalizing...", "processing")

            # ── Segment Diversity v1.9: remember selected segments ──────────
            # Only record if clips were successfully rendered.
            if clips_info and len([c for c in clips_info if c]) > 0:
                try:
                    from .vpi_segment_memory import load_segment_memory as _load_segment_memory
                    from .vpi_segment_memory import remember_selected_segments as _remember_segments
                    _remember_ok = _remember_segments(
                        segments=segments_json[:num_clips],
                        task_id=task_id or "unknown",
                        source_video_path=str(video_path) if video_path else None,
                    )
                    if _remember_ok:
                        _memory_after = _load_segment_memory()
                        _diversity_metadata["memory_entries_after"] = len(_memory_after)
                    logger.info(
                        "[segment-memory] remembered count=%d ok=%s",
                        len(segments_json[:num_clips]),
                        str(bool(_remember_ok)).lower(),
                    )
                except Exception as _rem_e:
                    logger.warning("[segment-diversity] remember failed: %s", _rem_e)

            # Record pipeline success metrics
            get_metrics_collector().finish_pipeline(task_id or "unknown", success=True)
            
            # DEFENSIVE: Ensure video_path is valid before returning
            if video_path is None:
                raise Exception("video_path is None at return - download or resolution failed silently")
            
            return {
                "segments": segments_json,
                "segments_to_render": segments_json,
                "video_path": str(video_path),
                "clips": clips_info,
                "clips_info": clips_info,
                "diversity_metadata": _diversity_metadata,
                "summary": relevant_parts.summary if relevant_parts else None,
                "key_topics": relevant_parts.key_topics if relevant_parts else None,
                "transcript": transcript,
                "analysis_json": json.dumps(
                    {
                        "summary": relevant_parts.summary if relevant_parts else None,
                        "key_topics": relevant_parts.key_topics
                        if relevant_parts
                        else [],
                        "most_relevant_segments": segments_json,
                    }
                ),
                "_metrics": get_metrics_collector().get_pipeline_report(task_id or "unknown"),
            }

        except Exception as e:
            logger.error(f"Error in video processing pipeline: {e}")
            # Record pipeline failure metrics
            get_metrics_collector().finish_pipeline(task_id or "unknown", success=False, error=str(e))
            raise
