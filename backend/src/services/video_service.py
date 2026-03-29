"""
Video service - handles video processing business logic.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Awaitable
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
from ..video_utils import (
    get_video_transcript,
    create_clips_with_transitions,
    create_optimized_clip,
    parse_timestamp_to_seconds,
)
from ..ai import get_most_relevant_parts_by_transcript
from ..config import Config
from .llm_service import LLMService
from .broll_service import BrollService
from .elite_ai_service import EliteAIService
from .vfx_service import VFXService
from .social_distribution_service import SocialDistributionService
from typing import List, Dict, Any, Optional, cast

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
        except Exception:
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
    async def analyze_transcript(transcript: str) -> Any:
        """
        Analyze transcript with AI to find relevant segments.
        This is already async, no need to wrap.
        """
        logger.info("Starting AI analysis of transcript")
        relevant_parts = await get_most_relevant_parts_by_transcript(transcript)
        logger.info(
            f"AI analysis complete: {len(relevant_parts.most_relevant_segments)} segments found"
        )
        return relevant_parts

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

            clip_filename = (
                f"clip_{clip_index + 1}_"
                f"{segment['start_time'].replace(':', '')}-"
                f"{segment['end_time'].replace(':', '')}.mp4"
            )
            clip_path = output_dir / clip_filename

            success = await run_in_thread(
                create_optimized_clip,
                video_path,
                start_seconds,
                end_seconds,
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
            )

            if not success:
                logger.error(f"Failed to create base clip {clip_index + 1}")
                return None

            output_path = clip_path
            
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
                from ..video_utils import generate_clip_thumbnail
                thumb_path = output_path.with_suffix(".jpg")
                if generate_clip_thumbnail(output_path, thumb_path, seek_seconds=1.0):
                    thumbnail_filename = thumb_path.name
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

            # Step 2: Generate transcript
            if should_cancel and await should_cancel():
                raise Exception("Task cancelled")

            if progress_callback:
                await progress_callback(30, "Generating transcript...", "processing")

            # Check disk-level transcript cache first (survives worker restarts within same run)
            # Uses the shared uploads volume (/app/temp/uploads) so ALL workers can hit the cache,
            # not just the worker that originally processed the task.
            _transcript_cache_path = None
            if task_id:
                _transcript_cache_dir = Path(get_service_config().temp_dir) / "cache" / "transcripts"
                _transcript_cache_dir.mkdir(parents=True, exist_ok=True)
                _transcript_cache_path = _transcript_cache_dir / f"{task_id}.json"

            transcript = cached_transcript
            if not transcript and _transcript_cache_path and _transcript_cache_path.exists():
                try:
                    transcript = _transcript_cache_path.read_text(encoding="utf-8")
                    logger.info(f"[CACHE] Loaded transcript from disk: {_transcript_cache_path}")
                except Exception as cache_err:
                    logger.warning(f"[CACHE] Failed to read disk transcript: {cache_err}")
                    transcript = None

            if not transcript:
                transcript = await VideoService.generate_transcript(
                    video_path, processing_mode=processing_mode
                )
                # Persist to disk immediately so retries can skip AssemblyAI
                if transcript and _transcript_cache_path:
                    try:
                        _transcript_cache_path.write_text(transcript, encoding="utf-8")
                        logger.info(f"[CACHE] Saved transcript to disk: {_transcript_cache_path}")
                    except Exception as save_err:
                        logger.warning(f"[CACHE] Failed to save transcript to disk: {save_err}")

            # Step 3: AI analysis
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
                except Exception:
                    relevant_parts = None

            # Disk-level analysis cache — also on the shared uploads volume so any worker can read it
            _analysis_cache_path = None
            if task_id:
                _analysis_cache_dir = Path(get_service_config().temp_dir) / "cache" / "analysis"
                _analysis_cache_dir.mkdir(parents=True, exist_ok=True)
                _analysis_cache_path = _analysis_cache_dir / f"{task_id}.json"

            if relevant_parts is None and _analysis_cache_path and _analysis_cache_path.exists():
                try:
                    cached_json = _analysis_cache_path.read_text(encoding="utf-8")
                    cached_data = json.loads(cached_json)
                    logger.info(f"[CACHE] Loaded AI analysis from disk: {_analysis_cache_path}")
                    relevant_parts = _SimpleResult(cached_data)
                except Exception as disk_err:
                    logger.warning(f"[CACHE] Failed to read disk analysis: {disk_err}")
                    relevant_parts = None

            if relevant_parts is None:
                relevant_parts = await VideoService.analyze_transcript(transcript)
                # Persist to disk immediately so retries can skip Gemini re-call
                if relevant_parts and _analysis_cache_path:
                    try:
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
                        _analysis_cache_path.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")
                        logger.info(f"[CACHE] Saved AI analysis to disk: {_analysis_cache_path}")
                    except Exception as save_err:
                        logger.warning(f"[CACHE] Failed to save analysis to disk: {save_err}")

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
            
            # Prepare segments for LLM
            segment_texts = [s.get("text") if isinstance(s, dict) else s.text for s in relevant_parts.most_relevant_segments]
            llm_service = LLMService()
            virality_data = await llm_service.get_virality_analysis(segment_texts)
            virality_map = {item.get("segment_index"): item for item in virality_data.get("analysis", [])}

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
            }

        except Exception as e:
            logger.error(f"Error in video processing pipeline: {e}")
            raise
