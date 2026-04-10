"""
Video service - handles video processing business logic.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Awaitable, cast, Tuple
from datetime import datetime
import asyncio
import logging
import json
import subprocess
import os
import tempfile

from ..utils.async_helpers import run_in_thread
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
from .concurrency_optimizer import parallel_map, run_with_timeout
from .llm_service import LLMService
from .broll_service import BrollService
from .elite_ai_service import EliteAIService
from .vfx_service import VFXService
from .social_distribution_service import SocialDistributionService
from .phi3_virality_service import Phi3ViralityService, get_phi3_service
from .confidence_subtitle_service import ConfidenceSubtitleGenerator
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
from ..video_processing.editing_pipeline import EditingPipeline
from ..video_processing.thumbnail_selector import select_best_thumbnail
from .viral_metadata_service import generate_viral_metadata
from ..comfyui_bridge import ComfyUIBridge, COMFYUI_ENABLED

logger = logging.getLogger(__name__)
# Global config instance for static methods
_config = None

def get_service_config():
    global _config
    if _config is None:
        from ..config import get_config
        _config = get_config()
    return _config

UPLOAD_URL_PREFIX = "upload://"


class VideoService:
    """Service for video processing operations."""

    @staticmethod
    def _get_file_duration(path: Path) -> Optional[float]:
        """Return video duration in seconds via ffprobe, or None on failure."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    str(path),
                ],
                capture_output=True, text=True, check=True,
            )
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"[VIDEO_DURATION] Failed to get duration for {path}: {e}", exc_info=True)
            return None

    @staticmethod
    def resolve_local_video_path(url: str) -> Path:
        """Resolve uploaded-video references without exposing server filesystem paths."""
        cfg = get_service_config()
        if url.startswith(UPLOAD_URL_PREFIX):
            filename = Path(url.removeprefix(UPLOAD_URL_PREFIX)).name
            return Path(cfg.temp_dir) / "uploads" / filename
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

        WORDS_PER_LINE = 3   # max words per group
        MAX_GAP_S      = 0.6  # break group if gap between consecutive words exceeds this
        MAX_SPAN_S     = 2.2  # break group if total span exceeds this
        events: List[str] = []

        # Build groups by TIME PROXIMITY, not word count.
        # This prevents a group from spanning a long pause, which causes perceived desync.
        all_valid = [w for w in words if (w.get("word") or "").strip()]
        groups: List[List[Dict]] = []
        current: List[Dict] = []
        for w in all_valid:
            if not current:
                current.append(w)
                continue
            gap  = float(w.get("start", 0)) - float(current[-1].get("end", 0))
            span = float(w.get("end", 0))   - float(current[0].get("start", 0))
            if len(current) >= WORDS_PER_LINE or gap > MAX_GAP_S or span > MAX_SPAN_S:
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
            "ffmpeg", "-y", "-i", video_path,
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
            "ffmpeg", "-y", "-i", video_path,
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

        try:
            start_seconds = parse_timestamp_to_seconds(segment["start_time"])
            end_seconds = parse_timestamp_to_seconds(segment["end_time"])
            duration = end_seconds - start_seconds

            # Virality-based dynamic duration then platform cap
            _vscore_pre = segment.get("virality_score", 50)
            if _vscore_pre >= 70:
                _target_dur = 90.0
            elif _vscore_pre >= 50:
                _target_dur = 60.0
            else:
                _target_dur = 45.0
            _target_dur = max(45.0, min(120.0, _target_dur))
            if duration < _target_dur:
                end_seconds = start_seconds + _target_dur
                duration = _target_dur
                logger.info(f"  Dynamic duration: {duration:.0f}s (virality_pre={_vscore_pre})")

            # Platform duration cap (TikTok=60s, Reels=90s, Shorts=60s)
            _platform_enum = Platform.TIKTOK if target_platform in ["all", "tiktok"] else \
                             Platform.REELS if target_platform == "reels" else \
                             Platform.SHORTS if target_platform == "shorts" else \
                             Platform.UNIVERSAL
            _export_svc_dur = ExportService()
            _capped = _export_svc_dur.enforce_clip_duration(duration, _platform_enum)
            if _capped != duration:
                end_seconds = start_seconds + _capped
                duration = _capped

            if duration <= 0:
                logger.warning(
                    f"Skipping clip {clip_index + 1}: invalid duration {duration:.1f}s"
                )
                return None

            # PASO 1: Phi-3-mini Scroll Stop Test (Fase 2 del plan)
            logger.info(f"[Clip {clip_index+1}] Step 1: Phi-3-mini virality scoring...")
            try:
                phi3_service = get_phi3_service()
                virality_result = await phi3_service.score_segment(
                    segment_text=segment.get("text", ""),
                    duration=duration,
                    audio_features=None  # Se llenará después
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
            
            # PASO 2: Audio spectral analysis (Fase 1 del plan)
            logger.info(f"[Clip {clip_index+1}] Step 2: Audio spectral analysis...")
            audio_features = {}
            try:
                # Extraer audio del segmento
                from tempfile import NamedTemporaryFile
                import subprocess
                
                audio_temp = NamedTemporaryFile(suffix='.wav', delete=False)
                audio_temp.close()
                
                # Extraer audio con ffmpeg
                # Bug fix: si el input ya es un segmento pre-extraído, buscar desde 0
                audio_ss = 0.0 if use_extracted_segment else start_seconds
                from ..video_processing.ffmpeg_guard import validate_segment_call
                validate_segment_call(
                    source_path=str(video_path),
                    ss=audio_ss,
                    to=audio_ss + duration,
                    context=f"clip_{clip_index+1}_audio_step2",
                )
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(audio_ss), "-i", str(video_path),
                    "-t", str(duration),
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1",
                    audio_temp.name
                ]
                subprocess.run(cmd, capture_output=True, timeout=60)
                
                # Analizar
                if Path(audio_temp.name).exists():
                    audio_features = analyze_audio_virality(audio_temp.name)
                    Path(audio_temp.name).unlink()
                    
                    logger.info(f"  ✓ Tempo: {audio_features.get('tempo_bpm', 0):.1f} BPM, "
                               f"{audio_features.get('dramatic_pauses', 0)} pauses")
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

                # ── Priority 2: faster-whisper re-transcription (fallback) ──
                if not words_with_confidence:
                    try:
                        subtitle_gen = ConfidenceSubtitleGenerator(model_size="base", device="cpu")
                        audio_temp_path = output_dir / f"audio_temp_{clip_index}.wav"
                        audio_ss2 = 0.0 if use_extracted_segment else start_seconds
                        cmd_extract = [
                            "ffmpeg", "-y",
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
                logger.warning("[SUBTITLE-FALLBACK] No cache / Whisper — building from segment.text")
                _words_list = [w for w in segment["text"].split() if w.strip()]
                if _words_list:
                    _spw = duration / max(1, len(_words_list))  # seconds per word
                    for _j, _w in enumerate(_words_list):
                        words_with_confidence.append({
                            "word":       _w,
                            "start":      _j * _spw,
                            "end":        (_j + 1) * _spw,
                            "confidence": 0.9,
                            "is_emphasis": False,
                        })
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
                except Exception as _esr_e:
                    logger.debug(f"  ESRGAN skipped: {_esr_e}")

            # Step 4.2: Audio denoising (afftdn — built-in FFmpeg, no model needed)
            try:
                _denoise_out = output_path.with_name(f"dn_{output_path.name}")
                _denoise_ok = await denoise_audio(
                    str(output_path), str(_denoise_out),
                    noise_floor_db=float(os.environ.get("DENOISE_NOISE_FLOOR_DB", "-25")),
                )
                if _denoise_ok and _denoise_out.exists():
                    output_path = _denoise_out
                    logger.info("  ✓ Audio denoised")
            except Exception as _dn_e:
                logger.debug(f"  Denoising skipped: {_dn_e}")

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

            # Step 4.2c: TTS Narration — inject AI narrator when audio SNR is low (Phase 3.4)
            _tts_enabled = os.environ.get("TTS_NARRATION_ENABLED", "false").lower() == "true"
            if _tts_enabled:
                try:
                    from .tts_service import maybe_add_narration
                    _tts_out = output_path.with_name(f"tts_{output_path.name}")
                    _tts_ok = await maybe_add_narration(
                        video_path=output_path,
                        segment_text=segment.get("text", "") if segment else "",
                        output_path=_tts_out,
                        language=os.environ.get("TTS_LANGUAGE", "en"),
                    )
                    if _tts_ok and _tts_out.exists():
                        output_path = _tts_out
                        logger.info("  ✓ TTS narration injected (low SNR audio)")
                except Exception as _tts_e:
                    logger.debug(f"  TTS narration skipped: {_tts_e}")

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

            # Step 4.3: B-Roll overlay (opt-in via BROLL_ENABLED=true)
            from ..config import get_config as _get_cfg_broll
            if _get_cfg_broll().broll_enabled:
                try:
                    from .broll_service import BrollService
                    _broll_svc = BrollService()
                    _broll_out = output_path.with_name(f"broll_{output_path.name}")
                    _broll_result = await _broll_svc.process_clip(
                        video_path=str(output_path),
                        output_path=str(_broll_out),
                        segment_text=segment.get("text", ""),
                        clip_duration=duration,
                    )
                    if Path(_broll_result).exists() and _broll_result != str(output_path):
                        output_path = Path(_broll_result)
                        logger.info(f"  ✓ B-roll overlay applied")
                except Exception as _broll_e:
                    logger.warning(f"  B-roll overlay failed: {_broll_e}")

            # Step 4.9: Crop already handled — create_optimized_clip applies
            # crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920 via _PLATFORM_VF
            # during FFmpeg pre-extraction. The output is already 1080×1920.
            # Re-running face-detection crop on 1080×1920 generates wrong
            # dimensions and adds black bars — do NOT apply a second crop here.

            # Step 4.4: ASS Karaoke captions via CaptionService
            # Auto-selects style based on caption_template + platform safe zones.
            # Falls back to legacy _burn_subtitles_word_level on any error.
            if add_subtitles and words_with_confidence:
                try:
                    from .caption_service import CaptionService as _CS, burn_captions as _burn_caps
                    logger.info(f"  Burning ASS captions ({len(words_with_confidence)} words)...")
                    _cap_style  = _CS.style_for_template(caption_template, target_platform)
                    subtitled_path = output_path.with_name(f"sub_{output_path.name}")
                    _cap_ok = await _burn_caps(
                        output_path, subtitled_path,
                        words_with_confidence,
                        style=_cap_style,
                        platform=target_platform,
                    )
                    if _cap_ok and subtitled_path.exists():
                        output_path = subtitled_path
                        logger.info(f"  ✓ ASS captions burned (style={_cap_style}, platform={target_platform})")
                    else:
                        raise RuntimeError("caption_service returned False")
                except Exception as burn_e:
                    logger.warning(f"  CaptionService failed ({burn_e}), falling back to legacy subtitles")
                    try:
                        subtitled_path = output_path.with_name(f"sub_{output_path.name}")
                        await VideoService._burn_subtitles_word_level(
                            str(output_path), words_with_confidence, str(subtitled_path)
                        )
                        if subtitled_path.exists():
                            output_path = subtitled_path
                    except Exception as _fb_e:
                        logger.warning(f"  Legacy subtitle fallback also failed: {_fb_e}")

            # Step 4.5: Advanced Polish (Auto-centering, Eye Contact, Background Blur)
            if auto_center_face or eye_contact_correction:
                from .video_polish_service import VideoPolishService
                polisher = VideoPolishService()
                _face_centered = False
                if auto_center_face:
                    polished_path = output_path.with_name(f"centered_{output_path.name}")
                    _face_centered = await polisher.auto_center_face(output_path, polished_path)
                    if _face_centered and polished_path.exists():
                        output_path = polished_path

                # Talking-head auto-detection: if face was found AND audio has words
                # → we're looking at a speaker clip → auto-apply eye contact correction.
                # Override via EYE_CONTACT_AUTO=false to disable.
                _eye_contact_auto = os.environ.get("EYE_CONTACT_AUTO", "true").lower() != "false"
                _is_talking_head = _face_centered and bool(words_with_confidence)
                if eye_contact_correction or (_is_talking_head and _eye_contact_auto):
                    try:
                        polished_path = output_path.with_name(f"gaze_{output_path.name}")
                        await polisher.apply_eye_contact_correction(output_path, polished_path)
                        if polished_path.exists():
                            output_path = polished_path
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

            # Step 4.7: Hook Visual Overlay — ONLY when ASS subtitles are NOT burned.
            # When subtitles are active both layers appear simultaneously (0-2s) causing
            # a double-text overlap. The karaoke subtitle already serves as the visual hook.
            if not words_with_confidence:
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
            try:
                from .beat_sync_service import analyse_bpm as _analyse_bpm
                _bpm_result = await _analyse_bpm(audio_path=output_path)
                _beat_bpm   = _bpm_result.get("bpm", 0.0)
                _beat_times = _bpm_result.get("beat_times", [])
                if _beat_times:
                    logger.info(f"  ✓ BPM detected: {_beat_bpm:.1f} ({len(_beat_times)} beats)")
            except Exception as _bpm_e:
                logger.debug(f"  BPM detection skipped: {_bpm_e}")

            # Merge beat timestamps into flash_timestamps so zoom punches land on beats.
            if _beat_times:
                _flash_ts = sorted(set(_flash_ts) | {
                    t for t in _beat_times
                    if 0.5 < t < (duration - 0.5)
                })

            # Step 4.6: Editing Pipeline — color grading, cinematic look, vignette,
            # zoom punch-in / Ken Burns / pattern interrupts, lower thirds,
            # progress bar, loudness normalization (single FFmpeg pass).
            try:
                _ep = EditingPipeline()
                _ep_out = output_path.with_name(f"ep_{output_path.name}")
                _ep_segment_text = segment.get("text", "")[:60] if segment else ""
                _ep_result = await _ep.apply(
                    video_path=output_path,
                    words=words_with_confidence,
                    output_path=_ep_out,
                    segment_text=_ep_segment_text,
                    flash_timestamps=_flash_ts if _flash_ts else None,
                    gpu_settings=gpu_encoding_settings if gpu_encoding_settings else None,
                )
                if _ep_result == _ep_out and _ep_out.exists():
                    output_path = _ep_out
                    logger.info("  ✓ EditingPipeline: color+cine+vignette+zoom+PI+lower-third+progress+loudnorm")
            except Exception as _ep_e:
                logger.warning(f"  EditingPipeline failed: {_ep_e}")

            # Step 4.6b: Cinematic LUT color grade (after EditingPipeline basic grade).
            # Controlled via env LUT_PRESET (default: teal_orange). Set to 'none' to skip.
            _lut_preset = os.environ.get("LUT_PRESET", "teal_orange")
            if _lut_preset and _lut_preset.lower() not in ("none", "off", "false", ""):
                try:
                    from .lut_service import get_lut_service as _get_lut
                    _lut_out = output_path.with_name(f"lut_{output_path.name}")
                    if await _get_lut().apply_lut(output_path, _lut_out, lut_id=_lut_preset):
                        output_path = _lut_out
                        logger.info(f"  ✓ Cinematic LUT applied: {_lut_preset}")
                except Exception as _lut_e:
                    logger.debug(f"  LUT skipped: {_lut_e}")

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

            # Step 4.10: Export with Platform Profile
            try:
                platform_enum = Platform.TIKTOK if target_platform in ["all", "tiktok"] else \
                                Platform.REELS if target_platform == "reels" else \
                                Platform.SHORTS if target_platform == "shorts" else \
                                Platform.UNIVERSAL

                export_service = ExportService()
                profile = export_service.get_profile(platform_enum)
                
                final_path = output_path.with_name(f"final_{output_path.name}")
                cmd = export_service.build_ffmpeg_command(
                    str(output_path),
                    str(final_path),
                    platform_enum,
                    burn_subtitles=segment.get("colored_subtitle_path")
                )
                import subprocess
                subprocess.run(cmd, capture_output=True, timeout=300)
                if Path(final_path).exists():
                    output_path = final_path
                    logger.info(f"  ✓ Exported with {profile.name} profile")
            except Exception as export_e:
                logger.warning(f"  Platform export failed: {export_e}")

            # Step 4.6: Translation & Dubbing
            if target_language and target_language != "eng":
                from .translation_service import TranslationService
                translator = TranslationService()
                dubbed_path = output_path.with_name(f"dubbed_{output_path.name}")
                await translator.dub_clip(output_path, dubbed_path, target_language)
                output_path = dubbed_path

            # Beat-synced BGM: use BeatSyncService (auto BPM match + adaptive ducking).
            # Falls back to niche-based static track when BGM library is empty.
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
                    bgm_volume=float(os.environ.get("BGM_VOLUME", "0.22")),
                    preferred_category=preferred_music_category or None,
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
                        if _mix_bg(output_path, _music_tmp, music_volume=0.22, music_path=_music_path):
                            if _music_tmp.exists():
                                _music_tmp.replace(output_path)
                                logger.info(f"  ✓ Background music (niche fallback): {_music_path.name}")
                except Exception as _fb_music_e:
                    logger.warning(f"  All music paths skipped: {_fb_music_e}")

            # Step 4.11: Pexels B-Roll overlay (Feature A — await prefetch task started at render launch)
            if _broll_prefetch_task is not None:
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

            logger.info(f"Created clip {clip_index + 1}: {duration:.1f}s")

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

            # Visual scoring via Ollama + Qwen3-VL (GPU optional, graceful fallback)
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

            # Thumbnail: Qwen3-VL quality scoring → pick best among 5 candidate frames
            thumbnail_filename = None
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

            # Viral metadata: LLM-generated hashtags + SEO title
            viral_meta: dict = {}
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

            # Phase 8.3: LSTM/CNN engagement prediction (drop-off curve)
            engagement_data: dict = {}
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
            # ─────────────────────────────────────────────────────────────────

            return {
                "clip_id": clip_index + 1,
                "filename": clip_filename,
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
            }
        except Exception as e:
            logger.error(f"Error creating clip {clip_index + 1}: {e}")
            return None
        finally:
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
            from ..video_processing.optical_flow_transitions import (
                apply_optical_flow_transition,
                get_transition_capabilities,
            )

            caps = get_transition_capabilities()
            if not caps["xfade_available"] and not caps["cv2_available"]:
                logger.debug("[transition] No transition backend available — skipping")
                return current_clip_info

            out_name = f"trans_{clip_index:02d}_{current_path.name}"
            out_path = output_dir / out_name

            import asyncio
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                apply_optical_flow_transition,
                prev_path,
                current_path,
                out_path,
                0.4,   # transition_duration seconds
                "auto",
            )

            if success and out_path.exists():
                logger.info(
                    "[transition] %s transition applied for clip %s → %s",
                    caps["best_mode"].upper(),
                    clip_index + 1,
                    out_name,
                )
                updated = dict(current_clip_info)
                updated["path"] = str(out_path)
                updated["filename"] = out_name
                updated["transition_applied"] = caps["best_mode"]
                return updated

        except Exception as e:
            logger.debug("[transition] Transition failed for clip %s: %s", clip_index + 1, e)

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

            # Step 3.5: Local LLM Virality Analysis
            if progress_callback:
                await progress_callback(60, "Predicting virality with local AI...", "processing")
            
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
                    logger.info("📊 Using text-based virality scoring (Ollama unavailable)")
                else:
                    logger.info("✨ Using AI virality scoring (Ollama active)")
                    
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

            def _enforce_min_duration_dict(seg: Dict[str, Any], min_secs: float = 45.0) -> Dict[str, Any]:
                """Apply 45s minimum duration to cached dict segments (Pydantic validator skipped for dicts)."""
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
                if end - start < min_secs:
                    new_end = start + min_secs
                    logger.warning(
                        f"[CACHE-VALIDATOR] Segment too short ({end-start:.1f}s): "
                        f"{seg.get('start_time')}→{seg.get('end_time')} — extending to {_fmt(new_end)}"
                    )
                    seg = dict(seg, end_time=_fmt(new_end))
                return seg

            for idx, segment in enumerate(raw_segments):
                if isinstance(segment, dict):
                    segment = _enforce_min_duration_dict(segment)
                    # Segments from cache arrive as dicts — still apply virality_map
                    v_info = virality_map.get(idx, {})
                    elite_data = elite_map.get((segment.get("start_time"), segment.get("end_time")))
                    raw_virality = v_info.get("virality_score", segment.get("virality_score", 0))
                    segments_json.append(
                        {
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
                    )
                else:
                    v_info = virality_map.get(idx, {})

                    elite_data = elite_map.get((segment.start_time, segment.end_time))
                    raw_virality = v_info.get("virality_score", 0)
                    # Distribute composite virality into 4 component scores if they aren't provided
                    segments_json.append(
                        {
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
                    )

            # ── CAUSA 5 guard: pad with synthetic segments if AI returned too few ──
            if len(segments_json) < num_clips and file_duration and file_duration > 0:
                needed = (num_clips + 2) - len(segments_json)
                logger.warning(
                    f"[SEGMENT-PAD] AI returned only {len(segments_json)} segments "
                    f"(need {num_clips}). Generating {needed} synthetic fallback segments."
                )
                _seg_dur = 45.0
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
                logger.info(
                    f"[SEGMENT-PAD] Now have {len(segments_json)} segments after padding"
                )
            # ── Render a buffer of +2 extra segments so that if 1-2 clips fail to
            # render the save loop can still fill the requested quota.
            # The save loop in task_service.py caps successful saves at num_clips.
            render_buffer = num_clips + 2
            segments_json = segments_json[:render_buffer]
            logger.info(
                f"[PIPELINE] Selected {len(segments_json)} segments for render "
                f"(quota={num_clips}, buffer={render_buffer})"
            )

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
            
            # Re-sort segments by enhanced virality score
            segments_json.sort(key=lambda x: x.get("virality_score", 0), reverse=True)
            
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

            # Record pipeline success metrics
            get_metrics_collector().finish_pipeline(task_id or "unknown", success=True)
            
            # DEFENSIVE: Ensure video_path is valid before returning
            if video_path is None:
                raise Exception("video_path is None at return - download or resolution failed silently")
            
            return {
                "segments": segments_json,
                "segments_to_render": segments_json,
                "video_path": str(video_path),
                "clips": [],
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
