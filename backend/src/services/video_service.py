"""
Video service - handles video processing business logic.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Awaitable, cast
from datetime import datetime
import logging
import json
import subprocess
import os

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
        """Quema subtítulos word-level con colores de confidence en el vídeo."""
        import subprocess
        import asyncio
        
        # Generar archivo ASS (mejor que SRT para estilos)
        ass_path = video_path.replace(".mp4", "_subtitles.ass")
        
        # Header ASS
        ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Viral,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,10,10,100,1
Style: HighConf,Arial,48,&H0000FF00,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,10,10,100,1
Style: LowConf,Arial,48,&H000000FF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,10,10,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        # Generar líneas de eventos
        events = []
        for i, word in enumerate(words):
            start = word.get("start", 0)
            end = word.get("end", start + 0.5)
            text = word.get("word", "").strip()
            conf = word.get("confidence", 1.0)
            is_emphasis = word.get("is_emphasis", False)
            
            # Elegir estilo según confidence
            if is_emphasis or conf < 0.7:
                style_name = "LowConf"  # Rojo para énfasis/baja confianza
            elif conf > 0.95:
                style_name = "HighConf"  # Verde para alta confianza
            else:
                style_name = "Viral"  # Blanco normal
            
            start_str = _seconds_to_ass_time(start)
            end_str = _seconds_to_ass_time(end)
            events.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{text}")
        
        # Escribir archivo ASS
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_header)
            f.write("\n".join(events))
        
        # FFmpeg: quemar subtítulos
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.wait()
        
        # Limpiar archivo temporal
        Path(ass_path).unlink(missing_ok=True)
        return output_path

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

        transcript_obj = await run_in_thread(get_video_transcript, video_path, speech_model)
        transcript = cast(str, transcript_obj)
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
        logger.info(f"Starting AI analysis of transcript (duration={video_duration:.1f}s)")
        relevant_parts = await get_most_relevant_parts_by_transcript(
            transcript, 
            include_broll=include_broll,
            video_duration=video_duration
        )
        logger.info(
            f"AI analysis complete: {len(relevant_parts.most_relevant_segments)} segments found"
        )
        return relevant_parts

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
        auto_center_face: bool = False,
        eye_contact_correction: bool = False,
        target_language: Optional[str] = None,
        task_id: str = "unknown",
        elite_metadata: Optional[Dict[str, Any]] = None,
        camera_plan: Optional[Dict[str, Any]] = None,
        sync_offset: float = 0.0,
        secondary_video_path: Optional[Path] = None,
        gpu_encoding_settings: Optional[Dict[str, Any]] = None,
        use_extracted_segment: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Render a single clip in the thread pool and return clip_info dict, or None on failure."""
        try:
            start_seconds = parse_timestamp_to_seconds(segment["start_time"])
            end_seconds = parse_timestamp_to_seconds(segment["end_time"])
            duration = end_seconds - start_seconds

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
                logger.info(f"[Clip {clip_index+1}] Step 4: Word-level confidence subtitles...")
                try:
                    subtitle_gen = ConfidenceSubtitleGenerator(model_size="base", device="cpu")
                    
                    # Re-extraer audio si no existe (fue eliminado en paso 2)
                    audio_temp_path = output_dir / f"audio_temp_{clip_index}.wav"
                    audio_ss2 = 0.0 if use_extracted_segment else start_seconds
                    from ..video_processing.ffmpeg_guard import validate_segment_call
                    validate_segment_call(
                        source_path=str(video_path),
                        ss=audio_ss2,
                        to=audio_ss2 + duration,
                        context=f"clip_{clip_index+1}_audio_step4",
                    )
                    cmd_extract = [
                        "ffmpeg", "-y",
                        "-ss", str(audio_ss2), "-i", str(video_path),
                        "-t", str(duration),
                        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                        str(audio_temp_path)
                    ]
                    subprocess.run(cmd_extract, capture_output=True, timeout=60)
                    
                    # Generar subtítulos con colores
                    if audio_temp_path.exists():
                        colored_segments = subtitle_gen.transcribe_with_confidence(str(audio_temp_path))
                        if colored_segments:
                            logger.info(f"  ✓ {len(colored_segments)} subtitle segments generated")
                            
                            # Guardar SRT coloreado
                            srt_path = output_dir / f"{clip_path.stem}_colored.srt"
                            subtitle_gen.generate_colored_srt(colored_segments, str(srt_path))
                            segment["colored_subtitle_path"] = str(srt_path)
                            
                            # Extraer palabras con confidence para quemar después
                            for seg in colored_segments:
                                for w in seg.words:
                                    words_with_confidence.append({
                                        "word": w.text,
                                        "start": seg.start + (w.start if hasattr(w, 'start') else 0),
                                        "end": seg.start + (w.end if hasattr(w, 'end') else 0.5),
                                        "confidence": w.confidence if hasattr(w, 'confidence') else 0.9,
                                        "is_emphasis": w.is_emphasis if hasattr(w, 'is_emphasis') else False
                                    })
                            
                            # Contar palabras raras resaltadas
                            rare_count = sum(1 for w in words_with_confidence if w.get("is_emphasis"))
                            logger.info(f"  ✓ {rare_count} rare/technical terms highlighted")
                        
                        # Limpiar audio temporal
                        audio_temp_path.unlink(missing_ok=True)
                except Exception as sub_e:
                    logger.warning(f"  Confidence subtitles generation failed: {sub_e}")
            
            # Duración dinámica basada en virality (Capa C)
            dynamic_duration = duration
            if virality_result and virality_result.total_score > 80:
                # Contenido viral fuerte = permitir hasta 55s
                dynamic_duration = min(55, max(25, duration))
                logger.info(f"  Viral content ({virality_result.total_score}): extended to {dynamic_duration:.0f}s")
            elif virality_result and virality_result.total_score < 50:
                # Contenido débil = recortar a 15s
                dynamic_duration = min(15, duration)
                logger.info(f"  Low virality ({virality_result.total_score}): trimmed to {dynamic_duration:.0f}s")
            
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
                task_id,
                elite_metadata=elite_metadata,
                gpu_encoding_settings=gpu_encoding_settings,
            )

            if not success:
                logger.error(f"Failed to create base clip {clip_index + 1}")
                return None

            output_path = clip_path
            
            # Step 4.4: Burn subtitles word-level (quemar subtítulos con confidence colors)
            if add_subtitles and words_with_confidence:
                try:
                    logger.info(f"  Burning word-level subtitles ({len(words_with_confidence)} words)...")
                    subtitled_path = output_path.with_name(f"sub_{output_path.name}")
                    await VideoService._burn_subtitles_word_level(
                        str(output_path),
                        words_with_confidence,
                        str(subtitled_path)
                    )
                    if Path(subtitled_path).exists():
                        output_path = subtitled_path
                        logger.info(f"  ✓ Word-level subtitles burned")
                except Exception as burn_e:
                    logger.warning(f"  Burning subtitles failed: {burn_e}")
            
            # Step 4.5: Advanced Polish (Auto-centering, Eye Contact)
            if auto_center_face or eye_contact_correction:
                from .video_polish_service import VideoPolishService
                polisher = VideoPolishService()
                
                if auto_center_face:
                    polished_path = output_path.with_name(f"centered_{output_path.name}")
                    await polisher.auto_center_face(output_path, polished_path)
                    output_path = polished_path
                
                if eye_contact_correction:
                    polished_path = output_path.with_name(f"gaze_{output_path.name}")
                    await polisher.apply_eye_contact_correction(output_path, polished_path)
                    output_path = polished_path

            # Step 4.7: Hook Visual Overlay (texto grande primeros 2s)
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

            # Step 4.8: Sound Design (efectos de sonido virales)
            try:
                sound_service = SoundDesignService()
                virality_segments = [{
                    "start": 0,
                    "end": duration,
                    "hook_type": segment.get("hook_type", "insight_reveal"),
                    "text": segment.get("text", "")
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

            # Step 4.9: Face Detection Crop 9:16 (si es vertical)
            if output_format == "vertical":
                try:
                    face_service = FaceDetectionService()
                    crop_filter = face_service.generate_ffmpeg_crop_filter(str(output_path))
                    if crop_filter and "crop=" in crop_filter:
                        cropped_path = output_path.with_name(f"crop_{output_path.name}")
                        # Aplicar crop con FFmpeg
                        import subprocess
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", str(output_path),
                            "-vf", f"{crop_filter},scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                            "-c:v", "libx264",
                            "-crf", "23",
                            "-preset", "fast",
                            "-c:a", "copy",
                            str(cropped_path)
                        ]
                        subprocess.run(cmd, capture_output=True, timeout=60)
                        if Path(cropped_path).exists():
                            output_path = cropped_path
                            logger.info(f"  ✓ Face-centered 9:16 crop applied")
                except Exception as crop_e:
                    logger.warning(f"  Face detection crop failed: {crop_e}")
                    # Fallback: crop simple centrado sin face detection
                    try:
                        logger.info(f"  Applying fallback 9:16 crop (centered)...")
                        fallback_path = output_path.with_name(f"vertical_{output_path.name}")
                        await VideoService._crop_to_vertical_9_16(
                            str(output_path),
                            str(fallback_path)
                        )
                        if Path(fallback_path).exists():
                            output_path = fallback_path
                            logger.info(f"  ✓ Fallback 9:16 crop applied")
                    except Exception as fallback_e:
                        logger.warning(f"  Fallback crop also failed: {fallback_e}")

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
                subprocess.run(cmd, capture_output=True, timeout=120)
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

            logger.info(f"Created clip {clip_index + 1}: {duration:.1f}s")

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
                    }
            except Exception as e:
                logger.debug(f"Vision scoring skipped: {e}")

            # Thumbnail generation (always — fast ffmpeg operation)
            thumbnail_filename = None
            try:
                thumbnail_path = output_path.with_suffix(".jpg")
                if generate_clip_thumbnail(output_path, thumbnail_path, seek_seconds=1.0):
                    thumbnail_filename = thumbnail_path.name
            except Exception as e:
                logger.debug(f"Thumbnail generation failed: {e}")
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
                "suggested_hashtags": segment.get("suggested_hashtags", []),
                "face_detected": segment.get("face_detected"),
                "translated_text": segment.get("translated_text"),
                "thumbnail_filename": thumbnail_filename,
                # V4 extras
                "rhythm_score": rhythm_data.get("rhythm_score"),
                "edit_pace": rhythm_data.get("edit_pace"),
                "scene_count": rhythm_data.get("scene_count"),
                "loop_potential": rhythm_data.get("can_loop", False),
                **vision_data,
            }
        except Exception as e:
            logger.error(f"Error creating clip {clip_index + 1}: {e}")
            return None

    @staticmethod
    async def apply_single_transition(
        prev_clip_path: Path,
        current_clip_info: Dict[str, Any],
        clip_index: int,
        output_dir: Path,
    ) -> Dict[str, Any]:
        """Return the original clip info.

        Standalone exports intentionally do not depend on adjacent clips.
        """
        logger.info(
            "Skipping inter-clip transition for clip %s to preserve standalone exports",
            clip_index + 1,
        )
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

            # Step 3.1: Elite Creative Direction (V4)
            if progress_callback:
                await progress_callback(55, "Generating Elite creative plan...", "processing")
            
            elite_service = EliteAIService()
            elite_plan = await elite_service.generate_creative_plan(
                video_path=video_path,
                transcript=transcript,
                duration=file_duration or 0.0
            )
            
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
            broll_service = BrollService()
            all_broll_suggestions = []
            if include_broll and relevant_parts.broll_opportunities:
                for opp in relevant_parts.broll_opportunities:
                    suggestion = broll_service.get_broll_for_opportunity(opp.model_dump() if hasattr(opp, "model_dump") else opp)
                    if suggestion:
                        all_broll_suggestions.append(suggestion)

            # Step 4: Create clips
            if should_cancel and await should_cancel():
                raise Exception("Task cancelled")

            if progress_callback:
                await progress_callback(70, "Creating video clips...", "processing")

            raw_segments = relevant_parts.most_relevant_segments
            segments_json: List[Dict[str, Any]] = []
            for idx, segment in enumerate(raw_segments):
                if isinstance(segment, dict):
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

            if processing_mode == "fast":
                cfg = get_service_config()
                segments_json = segments_json[: cfg.fast_mode_max_clips]

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
