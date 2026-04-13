"""
Task service - orchestrates task creation and processing workflow.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional, Callable, List, Tuple
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
from time import perf_counter

import redis.asyncio as redis

from ..repositories.task_repository import TaskRepository
from ..repositories.source_repository import SourceRepository
from ..repositories.clip_repository import ClipRepository
from ..repositories.cache_repository import CacheRepository
from .video_service import VideoService
from .task_completion_email_service import (
    TaskCompletionEmailService,
    TaskCompletionRecipient,
)
from ..config import Config, get_config
from ..clip_editor import (
    trim_clip_file,
    split_clip_file,
    merge_clip_files,
    overlay_custom_captions,
)
from ..video_processing.utils import parse_timestamp_to_seconds
from ..utils.video_extraction import extract_segments_fast, cleanup_extracted_segments
from ..utils.gpu_detection import detect_gpu, get_optimal_render_concurrency
from ..utils.resource_manager import (
    detect_hardware_capabilities,
    get_adaptive_settings,
    cleanup_temp_files,
    should_throttle_processing,
)

logger = logging.getLogger(__name__)


def _build_hook_title(segment: Dict[str, Any]) -> Optional[str]:
    """
    Generate a concise hook title overlay for a clip.

    Priority order:
    1. AI-generated suggested_title (if present)
    2. First 4-6 words of the segment text (short enough to read in 3s)
    3. None (no overlay) — avoids showing raw hook_type strings like "QUESTION"
    """
    # 1. Explicit suggested title from AI (rare but highest quality)
    if segment.get("suggested_title"):
        raw = segment["suggested_title"].strip()
        return raw[:60] if raw else None

    # 2. Derive from segment text — take first punchy phrase
    text = (segment.get("text") or "").strip()
    if not text:
        return None

    # Remove filler words from start
    filler_starts = {"uh", "um", "like", "so", "and", "but", "well", "okay", "ok", "right", "you know"}
    words = text.split()
    while words and words[0].lower().strip(".,!?") in filler_starts:
        words = words[1:]

    if not words:
        return None

    # Take first 5 words max, stop at natural punctuation
    result_words = []
    for w in words[:6]:
        result_words.append(w)
        if any(w.endswith(p) for p in [".", "!", "?", ","]):
            break

    title = " ".join(result_words).strip(".,")
    # Only show if it's meaningful (at least 2 words, not too long)
    if len(result_words) >= 2 and len(title) <= 50:
        return title

    return None


class TaskService:
    """Service for task workflow orchestration."""

    def __init__(self, db: AsyncSession, config: Config | None = None):
        self.db = db
        self.task_repo = TaskRepository()
        self.source_repo = SourceRepository()
        self.clip_repo = ClipRepository()
        self.cache_repo = CacheRepository()
        self.video_service = VideoService()
        self.config = config or get_config()

    @staticmethod
    def _build_cache_key(url: str, source_type: str, processing_mode: str, config: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate cache key with config hash to auto-invalidate when settings change.
        
        When min_duration, prompt, or model changes, the hash changes → cache miss → fresh analysis.
        This prevents stale cached results from being reused with different configurations.
        """
        from ..config import get_config
        
        cfg = config or get_config()
        
        # Parameters that affect AI analysis - changing any of these invalidates cache
        config_params = {
            "min_duration": getattr(cfg, 'min_clip_duration', 5),
            "max_duration": getattr(cfg, 'max_clip_duration', 45),
            "prompt_version": "v3",  # Increment this when you change LLM prompts in ai.py
            "llm_model": getattr(cfg, 'llm', 'ollama:qwen2.5:7b'),
        }
        
        # Generate 8-char hash of config for cache key
        config_hash = hashlib.md5(
            json.dumps(config_params, sort_keys=True).encode()
        ).hexdigest()[:8]
        
        # Final key: source|mode|url:config_hash
        payload = f"{source_type}|{processing_mode}|{url.strip()}"
        url_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        
        return f"{url_hash}:{config_hash}"

    def _is_stale_queued_task(self, task: Dict[str, Any]) -> bool:
        """Detect queued tasks that have likely stalled due to worker issues."""
        if task.get("status") != "queued":
            return False

        created_at = task.get("created_at")
        updated_at = task.get("updated_at") or created_at

        if not created_at or not updated_at:
            return False

        # Always compare in UTC to avoid timezone-naive vs timezone-aware issues.
        # Note: datetime.utcnow() is deprecated in Python 3.12+; use datetime.now(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        if getattr(updated_at, "tzinfo", None) is not None:
            updated_utc = updated_at.astimezone(timezone.utc)
        else:
            # Assume naive datetimes are UTC (DB convention)
            updated_utc = updated_at.replace(tzinfo=timezone.utc)

        age_seconds = (now_utc - updated_utc).total_seconds()
        return age_seconds >= self.config.queued_task_timeout_seconds

    async def create_task_with_source(
        self,
        user_id: str,
        url: str,
        title: Optional[str] = None,
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        include_broll: bool = False,
        processing_mode: str = "fast",
        target_language: str = "eng",
        auto_center_face: bool = False,
        eye_contact_correction: bool = False,
        split_screen: bool = False,
        url_secondary: Optional[str] = None,
        batch_id: Optional[str] = None,          # P3.4: batch group identifier
        force_fresh: bool = False,              # Force reprocessing for testing
    ) -> str:
        """
        Create a new task with associated source.
        Returns the task ID.
        """
        # Validate user exists
        if not await self.task_repo.user_exists(self.db, user_id):
            raise ValueError(f"User {user_id} not found")

        # Determine source type
        source_type = self.video_service.determine_source_type(url)

        # Get or generate title
        if not title:
            if source_type == "youtube":
                title = await self.video_service.get_video_title(url)
            else:
                title = "Uploaded Video"

        # Create source
        source_id = await self.source_repo.create_source(
            self.db, source_type=source_type, title=title, url=url
        )

        # Create task
        task_id = await self.task_repo.create_task(
            self.db,
            user_id=user_id,
            source_id=source_id,
            status="queued",  # Changed from "processing" to "queued"
            font_family=font_family,
            font_size=font_size,
            font_color=font_color,
            caption_template=caption_template,
            include_broll=include_broll,
            processing_mode=processing_mode,
            target_language=target_language,
            auto_center_face=auto_center_face,
            eye_contact_correction=eye_contact_correction,
            split_screen=split_screen,
            batch_id=batch_id,                  # P3.4: batch group
        )

        logger.info(f"Created task {task_id} for user {user_id}")
        return task_id

    async def create_task(
        self,
        user_id: str,
        source: str,
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        include_broll: bool = False,
        processing_mode: str = "fast",
        output_format: str = "vertical",
        add_subtitles: bool = True,
        target_language: str = "eng",
        auto_center_face: bool = False,
        eye_contact_correction: bool = False,
        split_screen: bool = False,
        target_platform: str = "all",
        batch_id: Optional[str] = None,
    ) -> str:
        """
        P3.4: Thin wrapper around create_task_with_source for batch usage.
        """
        return await self.create_task_with_source(
            user_id=user_id,
            url=source,
            font_family=font_family,
            font_size=font_size,
            font_color=font_color,
            caption_template=caption_template,
            include_broll=include_broll,
            processing_mode=processing_mode,
            target_language=target_language,
            auto_center_face=auto_center_face,
            eye_contact_correction=eye_contact_correction,
            split_screen=split_screen,
            batch_id=batch_id,
        )

    async def process_task(
        self,
        task_id: str,
        url: str,
        source_type: str,
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        processing_mode: str = "fast",
        output_format: str = "vertical",
        add_subtitles: bool = True,
        auto_center_face: bool = False,
        eye_contact_correction: bool = False,
        include_broll: bool = False,
        split_screen: bool = False,
        target_platform: str = "all",
        url_secondary: Optional[str] = None,
        target_language: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        should_cancel: Optional[Callable] = None,
        clip_ready_callback: Optional[Callable] = None,
        generate_ab_variants: bool = False,    # P3.5: also render a B variant per clip
        num_clips: int = 6,
        # Viral editing features
        jump_cut: bool = False,
        jump_cut_min_silence: float = 0.3,
        zoom_on_cuts: bool = True,
        cut_zoom_factor: float = 1.08,
        denoise_audio: bool = False,
        contextual_overlays: bool = True,
        overlay_frequency: str = "adaptive",
        audio_ducking: bool = True,
        playback_speed: float = 1.0,
        dramatic_slowmo: bool = False,
        speed_ramp_enabled: bool = True,
        use_scene_detection: bool = True,
        force_fresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Process a task: download video, analyze, create clips.
        Returns processing results.
        """
        try:
            logger.info(f"Starting processing for task {task_id} (force_fresh={force_fresh})")
            started_at = datetime.now(timezone.utc)
            stage_timings: Dict[str, float] = {}
            cache_key = self._build_cache_key(url, source_type, processing_mode)

            # FORCE FRESH: Delete cache entry if forcing reprocessing
            if force_fresh:
                await self.cache_repo.delete_cache(self.db, cache_key)
                logger.info(f"🔄 Force fresh: cache invalidated for {cache_key}")
                cache_entry = None
            else:
                cache_entry = await self.cache_repo.get_cache(self.db, cache_key)
            
            # CACHE GUARD: Verify source video exists before using cache
            # Prevents desync when video was cleaned but cache still valid
            if cache_entry:
                video_path_str = cache_entry.get("video_path")
                if video_path_str:
                    cached_video_path = Path(video_path_str)
                    if not cached_video_path.exists():
                        logger.warning(
                            f"[CACHE GUARD] Cache hit but source video missing: {cached_video_path}. "
                            f"Invalidating cache and re-processing."
                        )
                        await self.cache_repo.delete_cache(self.db, cache_key)
                        cache_entry = None
                # else: video_path is None/empty — cache incomplete, proceed with fresh download
            
            cached_transcript = (
                cache_entry.get("transcript_text") if cache_entry else None
            )
            cached_analysis_json = (
                cache_entry.get("analysis_json") if cache_entry else None
            )
            cache_hit = bool(cached_transcript and cached_analysis_json)

            await self.task_repo.update_task_runtime_metadata(
                self.db,
                task_id,
                started_at=started_at,
                cache_hit=cache_hit,
            )

            # Clear any clips from previous failed/retried runs to avoid duplicates
            await self.clip_repo.delete_clips_by_task(self.db, task_id)

            # Update status to processing
            await self.task_repo.update_task_status(
                self.db,
                task_id,
                "processing",
                progress=0,
                progress_message="Starting...",
            )

            # Progress callback wrapper
            async def update_progress(
                progress: int, message: str, status: str = "processing"
            ):
                await self.task_repo.update_task_status(
                    self.db,
                    task_id,
                    status,
                    progress=progress,
                    progress_message=message,
                )
                if progress_callback:
                    await progress_callback(progress, message, status)

            # Process video with progress updates
            pipeline_start = perf_counter()
            try:
                result = await self.video_service.process_video_complete(
                    url=url,
                    source_type=source_type,
                    task_id=task_id,
                    font_family=font_family,
                    font_size=font_size,
                    font_color=font_color,
                    caption_template=caption_template,
                    processing_mode=processing_mode,
                    output_format=output_format,
                    add_subtitles=add_subtitles,
                    include_broll=include_broll,
                    split_screen=split_screen,
                    target_platform=target_platform,
                    url_secondary=url_secondary,
                    cached_transcript=cached_transcript,
                    cached_analysis_json=cached_analysis_json,
                    progress_callback=update_progress,
                    should_cancel=should_cancel,
                    num_clips=num_clips,
                )
            except Exception as pipeline_error:
                logger.error(f"[PIPELINE FAILED] Task {task_id}: {type(pipeline_error).__name__}: {pipeline_error}")
                raise RuntimeError(f"Video processing pipeline failed: {pipeline_error}") from pipeline_error
            stage_timings["pipeline_seconds"] = round(
                perf_counter() - pipeline_start, 3
            )

            await self.cache_repo.upsert_cache(
                self.db,
                cache_key=cache_key,
                source_url=url,
                source_type=source_type,
                transcript_text=result.get("transcript"),
                analysis_json=result.get("analysis_json"),
            )

            # DEFENSIVE: Validate video_path before using it
            raw_video_path = result.get("video_path")
            if not raw_video_path:
                raise RuntimeError(
                    f"[DOWNLOAD FAILED] video_path is None or empty — "
                    f"download likely failed. Check yt-dlp logs for URL: {url}"
                )
            video_path = Path(raw_video_path)
            if not video_path.exists():
                raise FileNotFoundError(
                    f"[DOWNLOAD FAILED] Video file missing after download: {video_path}"
                )
            
            # Get segments to render
            segments_to_render = result.get("segments_to_render", [])
            total_clips = len(segments_to_render)
            
            # CRITICAL VALIDATION: Check if we have segments
            if total_clips == 0:
                logger.error(
                    f"[TASK {task_id}] ❌❌❌ CRITICAL: segments_to_render is EMPTY! "
                    f"This will cause 'No Clips Generated' error."
                )
                logger.error(f"[TASK {task_id}] Pipeline result keys: {list(result.keys())}")
                logger.error(f"[TASK {task_id}] LLM configured: {self.config.llm}")
                
                # Check API key configuration
                if self.config.llm.startswith("google"):
                    has_key = bool(self.config.google_api_key)
                    logger.error(f"[TASK {task_id}] Google API key configured: {has_key}")
                    if has_key:
                        key_preview = self.config.google_api_key[:10] + "..." if len(self.config.google_api_key) > 10 else "[too short]"
                        logger.error(f"[TASK {task_id}] API key preview: {key_preview}")
                elif self.config.llm.startswith("ollama"):
                    logger.error(f"[TASK {task_id}] Ollama base URL: {self.config.ollama_base_url}")
                
                # Log transcript info if available
                if result.get("transcript"):
                    transcript_preview = result["transcript"][:300]
                    logger.error(f"[TASK {task_id}] Transcript exists ({len(result['transcript'])} chars), preview: {transcript_preview}")
                else:
                    logger.error(f"[TASK {task_id}] No transcript in result!")
            else:
                logger.info(f"[TASK {task_id}] ✅ {total_clips} segments ready to render")
            
            clips_output_dir = Path(self.config.temp_dir) / "clips" / task_id
            clips_output_dir.mkdir(parents=True, exist_ok=True)

            clip_ids: List[str] = []
            render_start = perf_counter()
            clip_render_times: Dict[int, float] = {}  # per-clip timing
            failed_clips: List[Dict[str, Any]] = []   # track failed clips with reason

            # ── P2.1 OPTIMIZED PARALLEL RENDER ──────────────────────────────────
            # Dynamic concurrency based on GPU availability:
            # - NVIDIA GPU: 4 concurrent (NVENC handles multiple streams)
            # - AMD/Intel: 3 concurrent
            # - CPU only: 2 concurrent (avoid overload)
            # Can override with RENDER_CONCURRENCY env var
            if self.config.render_concurrency == "auto":
                optimal_concurrency = get_optimal_render_concurrency()
            else:
                try:
                    optimal_concurrency = int(self.config.render_concurrency)
                except ValueError:
                    logger.warning(f"Invalid RENDER_CONCURRENCY={self.config.render_concurrency}, using auto")
                    optimal_concurrency = get_optimal_render_concurrency()
            
            _render_sem = asyncio.Semaphore(optimal_concurrency)
            logger.info(f"Render concurrency: {optimal_concurrency} clips in parallel")
            
            # Detect GPU for encoding settings
            gpu_type, gpu_settings = detect_gpu()

            def _pick_caption_template(segment: Dict[str, Any]) -> str:
                """
                P2.6: Platform-aware caption style auto-selection.

                When the user picks "default", we choose the best template for
                the target platform + virality score combination:

                  TikTok  → big, punchy, fast — viral_pro / hormozi / tiktok
                  Reels   → polished, readable — viral_pro / tiktok / subtitles
                  Shorts  → minimal, text-first — subtitles / tiktok
                  all     → same as before (virality-based)

                If the user explicitly chose a template, honour it.
                """
                if caption_template != "default":
                    return caption_template

                v_score = segment.get("virality_score", 0)
                intensity = segment.get("intensity", "medium")

                # Platform-specific logic
                if target_platform == "tiktok":
                    # TikTok rewards attention-grabbing, high-energy text
                    if v_score >= 65 or intensity == "high":
                        return "viral_pro"
                    if v_score >= 40:
                        return "hormozi"
                    return "tiktok"

                elif target_platform == "reels":
                    # Instagram Reels prefers cleaner, more aesthetic captions
                    if v_score >= 65:
                        return "viral_pro"
                    if v_score >= 40:
                        return "tiktok"
                    return "subtitles"

                elif target_platform == "shorts":
                    # YouTube Shorts audience skews toward educational content —
                    # cleaner captions work better
                    if v_score >= 70:
                        return "tiktok"
                    return "subtitles"

                else:
                    # "all" / fallback — original virality-based logic
                    if v_score >= 70:
                        return "viral_pro"
                    if v_score >= 45:
                        return "hormozi"
                    return "tiktok"

            completed_renders = 0
            render_lock = asyncio.Lock()

            async def _render_one(i: int, segment: Dict[str, Any]) -> Tuple[int, Optional[Dict[str, Any]], float]:
                """Render one clip under the semaphore and return (index, clip_info, elapsed_s)."""
                nonlocal completed_renders
                async with _render_sem:
                    t0 = perf_counter()
                    info = None
                    try:
                        # Use pre-extracted segment if available, else fall back to full video
                        segment_source = extracted_segment_paths[i] if extracted_segment_paths[i] else video_path
                        
                        info = await self.video_service.create_single_clip(
                            segment_source,  # Pre-extracted segment (MUCH faster)
                            segment,
                            i,
                            clips_output_dir,
                            font_family,
                            font_size,
                            font_color,
                            _pick_caption_template(segment),
                            output_format,
                            add_subtitles,
                            broll_suggestions=segment.get("broll_suggestions"),
                            split_screen=split_screen,
                            hook_title=_build_hook_title(segment),
                            auto_center_face=auto_center_face,
                            eye_contact_correction=eye_contact_correction,
                            target_language=target_language,
                            task_id=task_id,
                            camera_plan=result.get("camera_plan"),
                            sync_offset=result.get("sync_offset", 0.0),
                            secondary_video_path=(
                                Path(result["secondary_video_path"])
                                if result.get("secondary_video_path")
                                else None
                            ),
                            gpu_encoding_settings=gpu_settings,  # Pass GPU settings for fast encoding
                            use_extracted_segment=(extracted_segment_paths[i] is not None),
                            target_platform=target_platform,
                        )
                    except Exception as clip_error:
                        logger.error(
                            f"Exception rendering clip {i+1}/{total_clips} "
                            f"({segment.get('start_time')} → {segment.get('end_time')}): {clip_error}",
                            exc_info=True
                        )
                        info = None

                    # ── Phase 9: Creative Engine post-render enhancement ──────────────
                    # Applies: hook-flash reorder, zoom punch, B-roll overlay,
                    # audio mastering (EBU R128), QA check, learning-loop manifest.
                    # All steps are independently guarded — never breaks clip delivery.
                    if info is not None:
                        try:
                            from .creative_pipeline import get_creative_pipeline
                            _cp = get_creative_pipeline()
                            creative_meta = await _cp.enhance(
                                clip_path=Path(info["path"]),
                                source_video=video_path,
                                segment=segment,
                                words=info.pop("words", []) or [],
                                audio_features=info.pop("audio_features", {}) or {},
                                task_id=task_id,
                                clip_index=i,
                                platform=target_platform or "tiktok",
                            )
                            info.update(creative_meta)
                            logger.info(
                                "[Clip %d] Phase 9 ✓ — preset=%s qa=%s zoom=%s "
                                "hook_reorder=%s loudnorm=%s",
                                i + 1,
                                creative_meta.get("preset_used"),
                                creative_meta.get("qa_passed"),
                                creative_meta.get("zoom_punch_applied"),
                                creative_meta.get("hook_reorder_applied"),
                                creative_meta.get("loudnorm_applied"),
                            )
                        except Exception as _ce:
                            logger.warning(
                                "Phase 9 creative pipeline skipped for clip %d: %s",
                                i, _ce,
                            )
                            info.pop("words", None)
                            info.pop("audio_features", None)
                    
                    # ── Viral Editing: Audio Denoise (opt-in) ────────────────────────
                    if info is not None and denoise_audio:
                        try:
                            from .audio_denoiser import denoise_audio as _denoise
                            from pathlib import Path as _Path
                            _dn_in = _Path(info["path"])
                            _dn_out = _dn_in.with_name(f"dn_{_dn_in.name}")
                            _dn_result = await _denoise(
                                str(_dn_in), str(_dn_out),
                                noise_reduction=True,
                                voice_isolation=True,
                                apply_loudnorm=True,
                            )
                            if not _dn_result.error and _dn_out.exists() and _dn_out.stat().st_size > 0:
                                _dn_in.unlink(missing_ok=True)
                                _dn_out.rename(_dn_in)
                                info["audio_denoised"] = True
                                info["audio_lufs_before"] = _dn_result.original_lufs
                                info["audio_lufs_after"] = _dn_result.output_lufs
                                logger.info(
                                    "  [Clip %d] Audio denoised: %.1f→%.1f LUFS",
                                    i + 1,
                                    _dn_result.original_lufs or -99,
                                    _dn_result.output_lufs or -99
                                )
                            else:
                                _dn_out.unlink(missing_ok=True)
                        except Exception as _dn_e:
                            logger.debug("Audio denoiser skipped for clip %d: %s", i, _dn_e)
                    
                    # ── Viral Editing: Jump Cuts + Zoom Transitions (opt-in) ─────────
                    if info is not None and jump_cut:
                        try:
                            from .cut_zoom_service import apply_jump_cuts_with_zoom
                            from pathlib import Path as _Path
                            _jc_in = _Path(info["path"])
                            _jc_out = _jc_in.with_name(f"jc_{_jc_in.name}")
                            _jc_words = info.get("words", []) or segment.get("words", [])
                            
                            _jc_result = await apply_jump_cuts_with_zoom(
                                video_path=str(_jc_in),
                                output_path=str(_jc_out),
                                words=_jc_words,
                                min_silence_sec=jump_cut_min_silence,
                                zoom_on_cuts=zoom_on_cuts,
                                zoom_factor=cut_zoom_factor,
                            )
                            
                            if _jc_result.get("success") and _jc_out.exists() and _jc_out.stat().st_size > 0:
                                _jc_in.unlink(missing_ok=True)
                                _jc_out.rename(_jc_in)
                                info["jump_cut_applied"] = True
                                info["jump_cut_time_saved"] = _jc_result.get("time_saved", 0)
                                info["jump_cut_fillers_removed"] = _jc_result.get("filler_words_removed", 0)
                                info["jump_cut_silences_removed"] = _jc_result.get("silence_gaps_removed", 0)
                                info["zoom_transitions_applied"] = _jc_result.get("zoom_count", 0)
                                info["cut_zoom_enabled"] = _jc_result.get("zoom_applied", False)
                                logger.info(
                                    "  [Clip %d] JumpCut+Zoom: %.1fs saved, %d cuts, %d zooms",
                                    i + 1,
                                    _jc_result.get("time_saved", 0),
                                    _jc_result.get("cut_count", 0),
                                    _jc_result.get("zoom_count", 0),
                                )
                            else:
                                _jc_out.unlink(missing_ok=True)
                                logger.warning("  [Clip %d] JumpCut+Zoom failed: %s", i + 1, _jc_result.get("error"))
                        except Exception as _jc_e:
                            logger.error("Jump-cut+zoom failed for clip %d: %s", i, _jc_e, exc_info=True)
                    # ─────────────────────────────────────────────────────────────────

                    elapsed = round(perf_counter() - t0, 3)
                    
                    # Update progress as each clip completes (success or failure)
                    async with render_lock:
                        completed_renders += 1
                        render_progress = 71 + int((completed_renders / total_clips) * 20)
                        status_msg = f"Rendered {completed_renders}/{total_clips} clips..."
                        if info is None:
                            status_msg = f"Rendered {completed_renders}/{total_clips} clips (1 failed)..."
                        await update_progress(
                            render_progress,
                            status_msg,
                            "processing"
                        )
                    
                    return i, info, elapsed

            # Check cancellation before launching parallel renders
            if should_cancel and await should_cancel():
                raise Exception("Task cancelled")

            # ── P2.1 PRE-EXTRACTION: Extract all segments at once (CRITICAL OPTIMIZATION) ──
            # This is 50-100x faster than re-decoding video for each clip
            # Uses ffmpeg -c copy (stream copy, no re-encoding)
            # Typical time: 0.5-2s per segment vs 30-180s with MoviePy
            await update_progress(68, f"Pre-extracting {total_clips} segments (fast)...", "processing")
            
            segments_temp_dir = Path(self.config.temp_dir) / "segments" / task_id
            segments_temp_dir.mkdir(parents=True, exist_ok=True)

            # Bug B fix: update each segment's end_time to match virality-based
            # dynamic duration BEFORE extraction so the pre-extracted file has
            # the correct length (45-120s, not the original LLM 30s).
            # Also inject _source_video_path so subtitle generation can look up
            # the AssemblyAI transcript cache keyed on the original video.

            # Fix 3: probe actual video duration so Bug B never overshoots the file end
            import subprocess as _sp_dur, json as _json_dur
            _video_dur: Optional[float] = None
            try:
                _probe = _sp_dur.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", str(video_path)],
                    capture_output=True, timeout=10
                )
                _video_dur = float(
                    _json_dur.loads(_probe.stdout).get("format", {}).get("duration", 0) or 0
                )
                logger.debug(f"[pre-extract] Video duration: {_video_dur:.1f}s")
            except Exception as _probe_e:
                logger.warning(f"[pre-extract] Could not probe video duration: {_probe_e}")

            for _seg in segments_to_render:
                _seg["_source_video_path"] = str(video_path)
                _vscore = _seg.get("virality_score", 50)
                if _vscore >= 70:
                    _tdur = 90.0
                elif _vscore >= 50:
                    _tdur = 60.0
                else:
                    _tdur = 45.0
                _tdur = max(45.0, min(120.0, _tdur))
                _s0 = parse_timestamp_to_seconds(_seg["start_time"])
                _e0 = parse_timestamp_to_seconds(_seg["end_time"])
                if (_e0 - _s0) < _tdur:
                    _new_end = _s0 + _tdur
                    # Cap at video end to prevent FFmpeg silent truncation
                    if _video_dur and _new_end > _video_dur - 1.0:
                        _new_end = max(_s0 + 10.0, _video_dur - 1.0)
                        logger.debug(f"  [pre-extract] Capped at video end: {_new_end:.1f}s")
                    _seg["end_time"] = f"{int(_new_end) // 60:02d}:{int(_new_end) % 60:02d}"
                    logger.debug(
                        f"  [pre-extract] Segment updated to {_tdur:.0f}s "
                        f"({_seg['start_time']} → {_seg['end_time']})"
                    )

            extracted_segment_paths = await extract_segments_fast(
                video_path=video_path,
                segments=segments_to_render,
                output_dir=segments_temp_dir,
                task_id=task_id
            )
            
            # Log extraction success rate
            successful_extractions = sum(1 for p in extracted_segment_paths if p is not None)
            logger.info(
                f"Pre-extraction complete: {successful_extractions}/{total_clips} segments "
                f"extracted in {segments_temp_dir}"
            )
            
            await update_progress(71, f"Rendering {total_clips} clips in parallel...", "processing")

            # Launch all renders concurrently (they run in thread pool workers)
            render_tasks = [_render_one(i, seg) for i, seg in enumerate(segments_to_render)]
            _raw_results = await asyncio.gather(*render_tasks, return_exceptions=True)
            render_results: List[Tuple[int, Optional[Dict[str, Any]], float]] = []
            for _ri, _raw in enumerate(_raw_results):
                if isinstance(_raw, Exception):
                    logger.error(
                        f"[Clip {_ri+1}] RENDER FAILED (unhandled): "
                        f"{type(_raw).__name__}: {_raw}",
                        exc_info=_raw
                    )
                    render_results.append((_ri, None, 0.0))
                else:
                    render_results.append(_raw)

            # Sort by original index so clip_order is preserved
            render_results.sort(key=lambda r: r[0])

            # ── Explicit per-clip diagnostics ─────────────────────────────────
            logger.info(f"[RENDER SUMMARY] {total_clips} clips attempted:")
            for _ri, _rinfo, _relapsed in render_results:
                _seg = segments_to_render[_ri]
                _status = "✅ OK" if _rinfo is not None else "❌ FAILED"
                logger.info(
                    f"  [Clip {_ri+1}] {_status} in {_relapsed:.1f}s "
                    f"({_seg.get('start_time')} → {_seg.get('end_time')}, "
                    f"virality={_seg.get('virality_score', '?')})"
                )
            successful_renders = sum(1 for _, info, _ in render_results if info is not None)
            logger.info(
                f"[RENDER SUMMARY] {successful_renders}/{total_clips} OK — "
                f"saving up to {num_clips} clips to DB"
            )
            # ──────────────────────────────────────────────────────────────────

            # Persist results sequentially (DB ops must be on the event loop thread)
            saved_clips = 0
            for i, clip_info, elapsed in render_results:
                # Stop once we've saved the requested number of clips.
                # Extra buffer segments are only used when earlier clips fail.
                if saved_clips >= num_clips:
                    logger.debug(f"  Quota reached ({num_clips}), skipping buffer clip {i+1}")
                    break

                segment = segments_to_render[i]
                clip_render_times[i + 1] = elapsed

                if clip_info is None:
                    failed_clips.append({
                        "clip_index": i + 1,
                        "start_time": segment.get("start_time"),
                        "end_time": segment.get("end_time"),
                        "render_time_s": elapsed,
                    })
                    logger.warning(
                        f"Clip {i+1}/{total_clips} failed to render in {elapsed:.1f}s "
                        f"({segment.get('start_time')} → {segment.get('end_time')})"
                    )
                    continue

                translated_text = clip_info.get("translated_text")
                saved_clips += 1

                # Update progress for saving phase (91-95%)
                save_progress = 91 + int((saved_clips / max(1, total_clips - len(failed_clips))) * 4)
                await update_progress(save_progress, f"Saving clip {saved_clips}/{total_clips - len(failed_clips)}...")

                # Save to DB immediately so SSE can deliver it
                clip_id = await self.clip_repo.create_clip(
                    self.db,
                    task_id=task_id,
                    filename=clip_info["filename"],
                    file_path=clip_info["path"],
                    start_time=clip_info["start_time"],
                    end_time=clip_info["end_time"],
                    duration=clip_info["duration"],
                    text=clip_info.get("text", ""),
                    relevance_score=clip_info.get("relevance_score", 0.0),
                    reasoning=clip_info.get("reasoning", ""),
                    clip_order=i + 1,
                    virality_score=clip_info.get("virality_score", 0),
                    hook_score=clip_info.get("hook_score", 0),
                    engagement_score=clip_info.get("engagement_score", 0),
                    value_score=clip_info.get("value_score", 0),
                    shareability_score=clip_info.get("shareability_score", 0),
                    hook_type=clip_info.get("hook_type"),
                    translated_text=translated_text,
                    # P3: social copy
                    social_title=clip_info.get("social_title"),
                    social_description=clip_info.get("social_description"),
                    suggested_hashtags=clip_info.get("suggested_hashtags"),
                    # P4: thumbnail
                    thumbnail_filename=clip_info.get("thumbnail_filename"),
                    # B-3: face detection flag
                    face_detected=clip_info.get("face_detected"),
                    # P2.4: hook preview score
                    hook_preview_score=clip_info.get("hook_preview_score", 0),
                    # Phase 10: viral polish
                    cta_overlay_applied=clip_info.get("cta_overlay_applied", False),
                    emoji_overlays_applied=clip_info.get("emoji_overlays_applied", False),
                    variants_json=(
                        __import__("json").dumps(clip_info["variants"])
                        if clip_info.get("variants") else None
                    ),
                )
                await self.db.commit()
                clip_ids.append(clip_id)

                # Auto-copy clip to unified exports folder for local sync
                try:
                    import shutil as _shutil
                    _exports_dir = Path("/app/exports/clips")
                    _exports_dir.mkdir(parents=True, exist_ok=True)
                    _src = Path(clip_info["path"])
                    if _src.exists():
                        _dst = _exports_dir / _src.name
                        _shutil.copy2(_src, _dst)
                        logger.info(f"  ✓ Copied clip to exports: {_src.name}")
                except Exception as _cp_e:
                    logger.warning(f"  exports copy failed: {_cp_e}")

                # Notify frontend via SSE immediately
                if clip_ready_callback:
                    clip_record = await self.clip_repo.get_clip_by_id(self.db, clip_id)
                    if clip_record:
                        await clip_ready_callback(i, total_clips, clip_record)

                # P3.5: A/B variant — render a second version with different template/hook
                if generate_ab_variants:
                    try:
                        b_info = await self.video_service.create_ab_variant(
                            original_clip_info=clip_info,
                            video_path=video_path,
                            clips_output_dir=clips_output_dir,
                            base_segment=segment,
                            original_template=_pick_caption_template(segment),
                            clip_index=i,
                        )
                        if b_info:
                            b_clip_id = await self.clip_repo.create_clip(
                                self.db,
                                task_id=task_id,
                                filename=b_info["filename"],
                                file_path=b_info["path"],
                                start_time=b_info["start_time"],
                                end_time=b_info["end_time"],
                                duration=b_info["duration"],
                                text=b_info.get("text", ""),
                                relevance_score=b_info.get("relevance_score", 0.0),
                                reasoning=b_info.get("reasoning", "") + " [Variant B]",
                                clip_order=i + 1,
                                virality_score=b_info.get("virality_score", 0),
                                hook_score=b_info.get("hook_score", 0),
                                engagement_score=b_info.get("engagement_score", 0),
                                value_score=b_info.get("value_score", 0),
                                shareability_score=b_info.get("shareability_score", 0),
                                hook_type=b_info.get("hook_type"),
                                thumbnail_filename=b_info.get("thumbnail_filename"),
                                hook_preview_score=b_info.get("hook_preview_score", 0),
                            )
                            await self.db.commit()
                            clip_ids.append(b_clip_id)
                            logger.info(f"✅ A/B variant B saved: clip {b_clip_id}")
                    except Exception as _ab_e:
                        logger.warning(f"A/B variant B failed for clip {i+1}: {_ab_e}")

            # ── Single bulk update of task.clip_ids after all clips complete ──
            if clip_ids:
                await self.task_repo.update_task_clips(self.db, task_id, clip_ids)

            render_elapsed = round(perf_counter() - render_start, 3)
            stage_timings["render_seconds"] = render_elapsed
            stage_timings["clip_render_times"] = clip_render_times
            if failed_clips:
                stage_timings["failed_clips"] = failed_clips
                logger.warning(
                    f"Task {task_id}: {len(failed_clips)}/{total_clips} clips failed — "
                    f"{[fc['clip_index'] for fc in failed_clips]}"
                )

            avg_clip_time = (
                render_elapsed / len(clip_render_times) if clip_render_times else 0
            )
            logger.info(
                f"Task {task_id} render complete: {len(clip_ids)} clips in "
                f"{render_elapsed:.1f}s (avg {avg_clip_time:.1f}s/clip)"
            )
            
            # Cleanup temporary extracted segments to free disk space
            cleanup_extracted_segments(extracted_segment_paths)

            # INTERMEDIATE FILE CLEANUP: Remove temp files but preserve final delivered clips
            if len(clip_ids) > 0:
                try:
                    # Collect filenames of clips saved to DB so we never delete them
                    # NOTE: use 'path' (final file) not 'filename' (original name before
                    # pipeline prefixes like sub_, broll_, ep_, jc_ are added)
                    _saved_filenames = set()
                    for _, _ci, _ in render_results:
                        if _ci is not None and _ci.get("path"):
                            _saved_filenames.add(Path(_ci["path"]).name)
                        if _ci is not None and _ci.get("thumbnail_filename"):
                            _saved_filenames.add(_ci["thumbnail_filename"])

                    kept, removed = 0, 0
                    for f in clips_output_dir.iterdir():
                        if f.is_file() and f.name not in _saved_filenames:
                            f.unlink(missing_ok=True)
                            removed += 1
                        else:
                            kept += 1
                    logger.info(f"[CLEANUP] Intermediate files removed: {removed}, kept: {kept}")
                except Exception as _ic_e:
                    logger.warning(f"[CLEANUP] Intermediate file cleanup failed: {_ic_e}")

            # SAFE CLEANUP: Only delete source video when clips were successfully generated
            clips_generated = len(clip_ids)
            if clips_generated > 0 and video_path.exists():
                try:
                    video_path.unlink(missing_ok=True)
                    logger.info(f"[CLEANUP] Source video deleted after generating {clips_generated} clips: {video_path}")
                except Exception as cleanup_e:
                    logger.warning(f"[CLEANUP] Failed to delete source video: {cleanup_e}")
            elif clips_generated == 0:
                logger.warning(
                    f"[CLEANUP] Source video PRESERVED — 0 clips generated. "
                    f"Video remains at: {video_path} for retry."
                )

            # Mark as completed
            await self.task_repo.update_task_status(
                self.db,
                task_id,
                "completed",
                progress=100,
                progress_message="Complete!",
            )

            if progress_callback:
                await progress_callback(100, "Complete!", "completed")

            await self.task_repo.update_task_runtime_metadata(
                self.db,
                task_id,
                completed_at=datetime.now(timezone.utc),
                stage_timings_json=json.dumps(stage_timings),
                error_code="",
            )
            await self._send_completion_notification_if_needed(
                task_id=task_id,
                clips_count=len(clip_ids),
            )

            logger.info(
                f"Task {task_id} completed successfully with {len(clip_ids)} clips"
            )

            return {
                "task_id": task_id,
                "clips_count": len(clip_ids),
                "segments": result["segments"],
                "summary": result.get("summary"),
                "key_topics": result.get("key_topics"),
            }

        except Exception as e:
            logger.error(f"Error processing task {task_id}: {e}")
            if str(e) == "Task cancelled":
                await self.task_repo.update_task_status(
                    self.db,
                    task_id,
                    "cancelled",
                    progress=0,
                    progress_message="Cancelled by user",
                )
                raise
            await self.task_repo.update_task_status(
                self.db, task_id, "error", progress_message=str(e)
            )
            error_code = "task_error"
            message = str(e).lower()
            if "download" in message or "youtube" in message:
                error_code = "download_error"
            elif "transcript" in message:
                error_code = "transcription_error"
            elif "analysis" in message:
                error_code = "analysis_error"
            elif "cancelled" in message:
                error_code = "cancelled"

            await self.task_repo.update_task_runtime_metadata(
                self.db,
                task_id,
                completed_at=datetime.now(timezone.utc),
                error_code=error_code,
            )
            raise

    async def _send_completion_notification_if_needed(
        self, *, task_id: str, clips_count: int
    ) -> None:
        context = await self.task_repo.get_task_notification_context(self.db, task_id)
        if not context:
            logger.warning("Task %s missing notification context; skipping email", task_id)
            return

        if not context.get("notify_on_completion"):
            return

        if context.get("completion_notification_sent_at"):
            logger.info(
                "Completion notification already sent for task %s; skipping", task_id
            )
            return

        user_email = context.get("user_email")
        if not user_email:
            logger.warning(
                "Task %s has notify_on_completion enabled but user email is missing",
                task_id,
            )
            return

        email_service = TaskCompletionEmailService(self.config)
        if not email_service.is_configured:
            logger.warning(
                "Skipping completion notification for task %s because Resend is not configured",
                task_id,
            )
            return

        try:
            await email_service.send_task_completed_email(
                recipient=TaskCompletionRecipient(
                    email=user_email,
                    name=context.get("user_name"),
                    first_name=context.get("user_first_name"),
                ),
                task_id=task_id,
                source_title=context.get("source_title"),
                clips_count=clips_count,
            )
            stamped = await self.task_repo.mark_completion_notification_sent(
                self.db, task_id
            )
            if not stamped:
                logger.info(
                    "Completion notification stamp already existed for task %s",
                    task_id,
                )
        except Exception:
            logger.exception(
                "Failed to send completion notification for task %s",
                task_id,
            )

    async def get_task_with_clips(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task details with all clips and analysis data."""
        task = await self.task_repo.get_task_by_id(self.db, task_id)

        if not task:
            return None

        if self._is_stale_queued_task(task):
            timeout_seconds = self.config.queued_task_timeout_seconds
            logger.warning(
                f"Task {task_id} stuck in queued status for over {timeout_seconds}s; marking as error"
            )
            await self.task_repo.update_task_status(
                self.db,
                task_id,
                "error",
                progress=0,
                progress_message=(
                    "Task timed out while waiting in queue. "
                    "Ensure the worker service is running and healthy (docker-compose logs -f worker)."
                ),
            )
            task = await self.task_repo.get_task_by_id(self.db, task_id)
            if not task:
                return None

        # Get clips
        clips = await self.clip_repo.get_clips_by_task(self.db, task_id)
        task["clips"] = clips
        task["clips_count"] = len(clips)

        # Fetch analysis_json from cache if available
        source_url = task.get("source_url")
        source_type = task.get("source_type")
        processing_mode = task.get("processing_mode", "fast")
        if source_url and source_type:
            try:
                cache_key = self._build_cache_key(source_url, source_type, processing_mode)
                cache_entry = await self.cache_repo.get_cache(self.db, cache_key)
                if cache_entry and cache_entry.get("analysis_json"):
                    analysis_json_str = cache_entry.get("analysis_json")
                    analysis_data = json.loads(analysis_json_str)
                    task["analysis"] = analysis_data
            except Exception as e:
                logger.debug(f"Could not load analysis data for task {task_id}: {e}")

        return task

    async def get_user_tasks(
        self, user_id: str, limit: int = 50
    ) -> list[Dict[str, Any]]:
        """Get all tasks for a user."""
        return await self.task_repo.get_user_tasks(self.db, user_id, limit)

    async def delete_task(self, task_id: str) -> None:
        """Delete a task and all its associated clips."""
        # Delete all clips for this task
        await self.clip_repo.delete_clips_by_task(self.db, task_id)

        # Delete the task
        await self.task_repo.delete_task(self.db, task_id)

        logger.info(f"Deleted task {task_id} and all associated clips")

    async def update_task_settings(
        self,
        task_id: str,
        font_family: str,
        font_size: int,
        font_color: str,
        caption_template: str,
        include_broll: bool,
        apply_to_existing: bool,
    ) -> Dict[str, Any]:
        """Update task-level settings and optionally regenerate all clips."""
        await self.task_repo.update_task_settings(
            self.db,
            task_id,
            font_family,
            font_size,
            font_color,
            caption_template,
            include_broll,
        )

        if apply_to_existing:
            await self.regenerate_all_clips_for_task(
                task_id,
                font_family,
                font_size,
                font_color,
                caption_template,
            )

        return await self.get_task_with_clips(task_id) or {}

    async def regenerate_all_clips_for_task(
        self,
        task_id: str,
        font_family: str,
        font_size: int,
        font_color: str,
        caption_template: str,
    ) -> None:
        """Regenerate all clips in a task using existing segment boundaries."""
        task = await self.task_repo.get_task_by_id(self.db, task_id)
        if not task:
            raise ValueError("Task not found")

        source_url = task.get("source_url")
        source_type = task.get("source_type")
        output_format = "vertical"
        add_subtitles = True

        # Preserve original output_format and add_subtitles from task creation (stored in Redis)
        redis_client = redis.Redis(
            host=self.config.redis_host,
            port=self.config.redis_port,
            password=self.config.redis_password,
            decode_responses=True,
        )
        try:
            source_payload = await redis_client.get(f"task_source:{task_id}")
            if source_payload:
                parsed = json.loads(source_payload)
                of = parsed.get("output_format", output_format)
                if of in ("vertical", "original"):
                    output_format = of
                asub = parsed.get("add_subtitles", add_subtitles)
                if isinstance(asub, bool):
                    add_subtitles = asub
        finally:
            await redis_client.aclose()

        if not source_url or not source_type:
            raise ValueError("Task source URL is missing; cannot regenerate clips")

        clips = await self.clip_repo.get_clips_by_task(self.db, task_id)
        if not clips:
            return

        video_path: Path
        if source_type == "youtube":
            downloaded = await self.video_service.download_video(source_url)
            if not downloaded:
                raise ValueError("Failed to download source video for regeneration")
            video_path = Path(downloaded)
        else:
            video_path = self.video_service.resolve_local_video_path(source_url)
            if not video_path.exists():
                raise ValueError("Source video file no longer exists")

        segments = [
            {
                "start_time": clip["start_time"],
                "end_time": clip["end_time"],
                "text": clip.get("text") or "",
                "relevance_score": clip.get("relevance_score", 0.5),
                "reasoning": clip.get("reasoning")
                or "Regenerated with updated settings",
                "virality_score": clip.get("virality_score", 0),
                "hook_score": clip.get("hook_score", 0),
                "engagement_score": clip.get("engagement_score", 0),
                "value_score": clip.get("value_score", 0),
                "shareability_score": clip.get("shareability_score", 0),
                "hook_type": clip.get("hook_type"),
            }
            for clip in clips
        ]

        clips_info = await self.video_service.create_video_clips(
            video_path,
            segments,
            font_family,
            font_size,
            font_color,
            caption_template,
            output_format,
            add_subtitles,
        )

        await self.clip_repo.delete_clips_by_task(self.db, task_id)

        clip_ids = []
        for i, clip_info in enumerate(clips_info):
            clip_id = await self.clip_repo.create_clip(
                self.db,
                task_id=task_id,
                filename=clip_info["filename"],
                file_path=clip_info["path"],
                start_time=clip_info["start_time"],
                end_time=clip_info["end_time"],
                duration=clip_info["duration"],
                text=clip_info.get("text") or "",
                relevance_score=clip_info.get("relevance_score", 0.5),
                reasoning=clip_info.get("reasoning")
                or "Regenerated with updated settings",
                clip_order=i + 1,
                virality_score=clip_info.get("virality_score", 0),
                hook_score=clip_info.get("hook_score", 0),
                engagement_score=clip_info.get("engagement_score", 0),
                value_score=clip_info.get("value_score", 0),
                shareability_score=clip_info.get("shareability_score", 0),
                hook_type=clip_info.get("hook_type"),
            )
            clip_ids.append(clip_id)

        await self.task_repo.update_task_clips(self.db, task_id, clip_ids)

    async def trim_clip(
        self,
        task_id: str,
        clip_id: str,
        start_offset: float,
        end_offset: float,
    ) -> Dict[str, Any]:
        clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
        if not clip or clip["task_id"] != task_id:
            raise ValueError("Clip not found")

        input_path = Path(clip["file_path"])
        if not input_path.exists():
            raise ValueError("Clip file not found")

        output_path = trim_clip_file(
            input_path, Path(self.config.temp_dir) / "clips", start_offset, end_offset
        )
        clip_duration = max(0.1, clip["duration"] - start_offset - end_offset)

        start_seconds = parse_timestamp_to_seconds(clip["start_time"]) + start_offset
        end_seconds = start_seconds + clip_duration

        new_start = self._seconds_to_mmss(start_seconds)
        new_end = self._seconds_to_mmss(end_seconds)

        await self.clip_repo.update_clip(
            self.db,
            clip_id,
            output_path.name,
            str(output_path),
            new_start,
            new_end,
            clip_duration,
            clip.get("text") or "",
        )
        return (await self.clip_repo.get_clip_by_id(self.db, clip_id)) or {}

    async def split_clip(
        self, task_id: str, clip_id: str, split_time: float
    ) -> Dict[str, Any]:
        clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
        if not clip or clip["task_id"] != task_id:
            raise ValueError("Clip not found")

        input_path = Path(clip["file_path"])
        if not input_path.exists():
            raise ValueError("Clip file not found")

        first_path, second_path = split_clip_file(
            input_path, Path(self.config.temp_dir) / "clips", split_time
        )

        start_seconds = parse_timestamp_to_seconds(clip["start_time"])
        clamped_split = max(0.2, min(split_time, float(clip["duration"]) - 0.2))
        split_abs = start_seconds + clamped_split
        end_seconds = parse_timestamp_to_seconds(clip["end_time"])

        await self.clip_repo.update_clip(
            self.db,
            clip_id,
            first_path.name,
            str(first_path),
            clip["start_time"],
            self._seconds_to_mmss(split_abs),
            clamped_split,
            clip.get("text") or "",
        )

        await self.clip_repo.create_clip(
            self.db,
            task_id=task_id,
            filename=second_path.name,
            file_path=str(second_path),
            start_time=self._seconds_to_mmss(split_abs),
            end_time=self._seconds_to_mmss(end_seconds),
            duration=max(0.1, end_seconds - split_abs),
            text=clip.get("text") or "",
            relevance_score=clip.get("relevance_score", 0.5),
            reasoning=clip.get("reasoning") or "Split from original clip",
            clip_order=clip.get("clip_order", 1) + 1,
            virality_score=clip.get("virality_score", 0),
            hook_score=clip.get("hook_score", 0),
            engagement_score=clip.get("engagement_score", 0),
            value_score=clip.get("value_score", 0),
            shareability_score=clip.get("shareability_score", 0),
            hook_type=clip.get("hook_type"),
        )

        await self.clip_repo.reorder_task_clips(self.db, task_id)
        return {"message": "Clip split successfully"}

    async def merge_clips(self, task_id: str, clip_ids: list[str]) -> Dict[str, Any]:
        if len(clip_ids) < 2:
            raise ValueError("At least two clips are required to merge")

        clips = []
        for clip_id in clip_ids:
            clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
            if not clip or clip["task_id"] != task_id:
                raise ValueError("One or more clips not found")
            clips.append(clip)

        ordered = sorted(clips, key=lambda c: c.get("clip_order", 0))
        merged_path = merge_clip_files(
            [Path(c["file_path"]) for c in ordered],
            Path(self.config.temp_dir) / "clips",
        )

        start_time = ordered[0]["start_time"]
        end_time = ordered[-1]["end_time"]
        duration = sum(float(c.get("duration", 0.0)) for c in ordered)
        text = " ".join((c.get("text") or "").strip() for c in ordered if c.get("text"))

        first = ordered[0]
        await self.clip_repo.update_clip(
            self.db,
            first["id"],
            merged_path.name,
            str(merged_path),
            start_time,
            end_time,
            duration,
            text,
        )

        for clip in ordered[1:]:
            await self.clip_repo.delete_clip(self.db, clip["id"])

        await self.clip_repo.reorder_task_clips(self.db, task_id)
        return {"message": "Clips merged successfully", "clip_id": first["id"]}

    async def update_clip_captions(
        self,
        task_id: str,
        clip_id: str,
        caption_text: str,
        position: str,
        highlight_words: list[str],
    ) -> Dict[str, Any]:
        clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
        if not clip or clip["task_id"] != task_id:
            raise ValueError("Clip not found")

        input_path = Path(clip["file_path"])
        if not input_path.exists():
            raise ValueError("Clip file not found")

        output_path = overlay_custom_captions(
            input_path,
            Path(self.config.temp_dir) / "clips",
            caption_text,
            position,
            highlight_words,
        )

        await self.clip_repo.update_clip(
            self.db,
            clip_id,
            output_path.name,
            str(output_path),
            clip["start_time"],
            clip["end_time"],
            clip["duration"],
            caption_text,
        )
        return (await self.clip_repo.get_clip_by_id(self.db, clip_id)) or {}

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Return aggregate processing performance metrics."""
        return await self.task_repo.get_performance_metrics(self.db)

    @staticmethod
    def _seconds_to_mmss(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        minutes = total // 60
        secs = total % 60
        return f"{minutes:02d}:{secs:02d}"
