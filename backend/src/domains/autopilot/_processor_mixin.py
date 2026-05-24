"""Task processing mixin — the heavy `process_task` orchestrator."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import redis.asyncio as redis

from ...clip_editor import (
    merge_clip_files,
    overlay_custom_captions,
    split_clip_file,
    trim_clip_file,
)
from ...config import Config, get_config
from ...domains.broll.comfyui_integration import comfyui_integration
from ...domains.notifications.task_completion_email_service import (
    TaskCompletionEmailService,
    TaskCompletionRecipient,
)
from ...domains.validation.source_subtitle_detector import (
    check_source_subtitles_and_adjust,
)
from ...domains.video.video_service import VideoService
from ...repositories.cache_repository import CacheRepository
from ...repositories.clip_repository import ClipRepository
from ...repositories.source_repository import SourceRepository
from ...repositories.task_repository import TaskRepository
from ...utils.gpu_detection import detect_gpu, get_optimal_render_concurrency
from ...utils.resource_manager import (
    cleanup_temp_files,
    detect_hardware_capabilities,
    get_adaptive_settings,
    should_throttle_processing,
)
from ...utils.video_extraction import cleanup_extracted_segments, extract_segments_fast
from ...video_processing.utils import parse_timestamp_to_seconds
from ._helpers import build_hook_title as _build_hook_title

logger = logging.getLogger(__name__)

class _ProcessorMixin:
    """Mixin providing ProcessorMixin methods."""

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
        # ComfyUI AI features (Phase 10)
        use_comfyui_reframe: bool = False,
        use_comfyui_thumbnail: bool = False,
        thumbnail_prompt: str = "cinematic viral thumbnail",
        comfyui_chunk_size: int = 300,
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
            
            # ── Source Subtitle Detector: preflight check ────────────────────────
            # Lightweight heuristic detection of burned-in subtitles in the bottom
            # band of the source video. Adjusts caption strategy accordingly.
            _source_subtitle_result = await check_source_subtitles_and_adjust(
                video_path=video_path,
                add_subtitles=add_subtitles,
                target_platform=target_platform,
            )
            _adjusted_add_subtitles = _source_subtitle_result["add_subtitles"]
            _caption_offset_y = _source_subtitle_result["caption_offset_y"]
            _caption_strategy = _source_subtitle_result["caption_strategy"]
            if _caption_strategy != "normal":
                logger.info(
                    "[preflight] Source subtitle strategy: %s "
                    "(add_subtitles=%s, offset_y=%d)",
                    _caption_strategy, _adjusted_add_subtitles, _caption_offset_y,
                )
            # ─────────────────────────────────────────────────────────────────────
            
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
            
            # Mark render phase start in metrics
            from ...core.metrics_service import get_metrics_collector
            get_metrics_collector().start_render(task_id)
            
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

            # ── BUG 2 FIX: Local helper to remux MP4 in-place, fixing moov atom ──
            async def _remux_fix(path: str) -> bool:
                """Remux MP4 in-place to fix moov atom and sync stream durations."""
                import subprocess as _sp
                _in = Path(path)
                _tmp = _in.with_suffix(".remux.mp4")
                try:
                    r = _sp.run(
                        ["ffmpeg", "-y", "-i", str(_in),
                         "-c", "copy", "-movflags", "+faststart",
                         str(_tmp)],
                        capture_output=True, timeout=60
                    )
                    if r.returncode == 0 and _tmp.exists() and _tmp.stat().st_size > 0:
                        _in.unlink(missing_ok=True)
                        _tmp.rename(_in)
                        return True
                    _tmp.unlink(missing_ok=True)
                    return False
                except Exception:
                    _tmp.unlink(missing_ok=True)
                    return False

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
                # Always cap at video end to prevent FFmpeg silent truncation,
                # regardless of whether the segment is being extended or not.
                _new_end = _e0
                if (_e0 - _s0) < _tdur:
                    _new_end = _s0 + _tdur
                if _video_dur and _new_end > _video_dur - 1.0:
                    _new_end = max(_s0 + 10.0, _video_dur - 1.0)
                    logger.debug(f"  [pre-extract] Capped at video end: {_new_end:.1f}s")
                if _new_end != _e0:
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
                            _adjusted_add_subtitles,  # Use adjusted value from source subtitle detector
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
                            jump_cut=jump_cut,
                            caption_offset_y=_caption_offset_y,  # Pass offset from source subtitle detector
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
                        # Guard: save backup of clip before Creative Pipeline
                        _cp_backup = None
                        _cp_before_dur = 0.0
                        try:
                            import subprocess as _cp_sp, json as _cp_json
                            _cp_probe = _cp_sp.run(
                                ["ffprobe", "-v", "quiet", "-print_format", "json",
                                 "-show_format", info["path"]],
                                capture_output=True, text=True, timeout=10
                            )
                            _cp_before_dur = float(
                                _cp_json.loads(_cp_probe.stdout)
                                .get("format", {}).get("duration", 0)
                            )
                            # Save backup before Creative Pipeline modifies the file
                            _cp_backup = Path(info["path"]).with_name(f"_cp_backup_{Path(info['path']).name}")
                            shutil.copy2(info["path"], str(_cp_backup))
                        except Exception:
                            pass
                        
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
                        
                        # Guard: restore clip from backup if Creative Pipeline truncated it
                        if _cp_backup and _cp_backup.exists() and _cp_before_dur > 0:
                            try:
                                _cp_after_probe = _cp_sp.run(
                                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                                     "-show_format", info["path"]],
                                    capture_output=True, text=True, timeout=10
                                )
                                _cp_after_dur = float(
                                    _cp_json.loads(_cp_after_probe.stdout)
                                    .get("format", {}).get("duration", 0)
                                )
                                if _cp_after_dur < _cp_before_dur * 0.8:
                                    logger.warning(
                                        "[CREATIVE GUARD] Creative Pipeline truncated clip %d: "
                                        "%.1fs → %.1fs — restoring from backup",
                                        i + 1, _cp_before_dur, _cp_after_dur,
                                    )
                                    shutil.copy2(str(_cp_backup), info["path"])
                                    logger.info(
                                        "[CREATIVE GUARD] Restored clip %d from backup (%.1fs)",
                                        i + 1, _cp_before_dur,
                                    )
                                _cp_backup.unlink(missing_ok=True)
                            except Exception:
                                _cp_backup.unlink(missing_ok=True)
                    
                    # ── Viral Editing: Audio Denoise (opt-in) ────────────────────────
                    if info is not None and denoise_audio:
                        try:
                            from ...domains.audio.audio_denoiser import denoise_audio as _denoise
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
                    
                    # Jump cuts are applied inside create_single_clip (Step 4.2-jc),
                    # controlled by the jump_cut parameter passed above.
                    # ─────────────────────────────────────────────────────────────────

                    # ── Phase 10: ComfyUI AI Enhancement (opt-in) ─────────────────────
                    # Applies: 9:16 reframe with AI, AI thumbnail generation, subtitle enhancement
                    if info is not None:
                        try:
                            clip_path = Path(info["path"])
                            
                            # ComfyUI 9:16 Reframe
                            if use_comfyui_reframe and output_format == "vertical":
                                logger.info("  [Clip %d] Phase 10a: ComfyUI 9:16 reframe...", i + 1)
                                reframe_result = await comfyui_integration.process_with_comfyui(
                                    task_id=f"{task_id}_c{i}",
                                    video_path=clip_path,
                                    operation="reframe_9_16",
                                    progress_callback=lambda p, msg: None,
                                    chunk_size=comfyui_chunk_size
                                )
                                if reframe_result:
                                    info["comfyui_reframed"] = True
                                    logger.info("  [Clip %d] Phase 10a ✓", i + 1)
                            
                            # ComfyUI Thumbnail Generation
                            if use_comfyui_thumbnail:
                                logger.info("  [Clip %d] Phase 10b: ComfyUI AI thumbnail...", i + 1)
                                thumb_result = await comfyui_integration.process_with_comfyui(
                                    task_id=f"{task_id}_c{i}_thumb",
                                    video_path=clip_path,
                                    operation="thumbnail",
                                    progress_callback=lambda p, msg: None,
                                    prompt=thumbnail_prompt
                                )
                                if thumb_result:
                                    info["comfyui_thumbnail"] = str(thumb_result)
                                    logger.info("  [Clip %d] Phase 10b ✓", i + 1)
                            
                        except Exception as _cu_e:
                            logger.warning("Phase 10 ComfyUI skipped for clip %d: %s", i, _cu_e)
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

                # ── BUG 2 FIX: Remux MP4 in-place to fix moov atom and sync stream durations ──
                if clip_info is not None:
                    _fixed = await _remux_fix(clip_info["path"])
                    if not _fixed:
                        logger.warning(f"[REMUX] Failed to fix moov atom for clip {i+1}, using original")

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

                # Suggestion Studio: persist render context + seed suggestions.
                # Safe-by-design: failures here never break clip delivery.
                try:
                    from .render_context import build_clip_render_context
                    _ctx = build_clip_render_context(
                        clip_index=i,
                        segment=segment,
                        clip_info=clip_info,
                        source_video_path=str(video_path),
                        task_config={
                            "font_family": font_family,
                            "font_size": font_size,
                            "font_color": font_color,
                            "caption_template": caption_template,
                            "output_format": output_format,
                            "add_subtitles": add_subtitles,
                            "include_broll": include_broll,
                            "split_screen": split_screen,
                            "target_platform": target_platform,
                            "target_language": target_language,
                            "auto_center_face": auto_center_face,
                            "eye_contact_correction": eye_contact_correction,
                            "jump_cut": jump_cut,
                            "denoise_audio": denoise_audio,
                            "contextual_overlays": contextual_overlays,
                            "audio_ducking": audio_ducking,
                            "task_id": task_id,
                        },
                    )
                    await self.clip_repo.set_render_context(self.db, clip_id, _ctx)
                except Exception as _ctx_e:
                    logger.warning(
                        "[render_context] failed for clip %s: %s", clip_id, _ctx_e
                    )

                try:
                    from .suggestion_seeder import seed_suggestions_for_clip
                    await seed_suggestions_for_clip(
                        self.db,
                        clip_id=clip_id,
                        segment=segment,
                        clip_info=clip_info,
                    )
                except Exception as _seed_e:
                    logger.warning(
                        "[suggestion_seeder] skipped for clip %s: %s",
                        clip_id, _seed_e,
                    )

                # P0: REAL Suggestion Application - Render suggestions into video
                try:
                    from .suggestion_applicator import SuggestionApplicator
                    from ...repositories.clip_suggestion_repository import ClipSuggestionRepository
                    from ...domains.autopilot.clip_suggestion_status import ClipSuggestionStatus

                    _suggestions = await ClipSuggestionRepository.list_by_clip(self.db, clip_id)

                    if _suggestions:
                        _auto_apply_kinds = {
                            "caption_template", "caption_style", "caption_animation",
                            "loudnorm", "sfx_cues", "background_music",
                            "zoom_punch", "vignette", "color_grading",
                            "broll_stock", "broll_ai", "contextual_overlay",
                            "emoji_overlay", "cta_overlay",
                        }

                        _suggestions_to_apply = [
                            s for s in _suggestions
                            if s.get("kind") in _auto_apply_kinds and s.get("status") == ClipSuggestionStatus.PENDING.value
                        ]

                        if _suggestions_to_apply:
                            logger.info(
                                "[suggestion_applicator] Applying %d suggestions to clip %s",
                                len(_suggestions_to_apply), clip_id,
                            )

                            _clip_record = await self.clip_repo.get_clip_by_id(self.db, clip_id)
                            _input_path = Path(_clip_record["file_path"])
                            _output_path = _input_path.parent / f"enhanced_{_input_path.name}"

                            applicator = SuggestionApplicator()
                            _result = await applicator.apply_suggestions(
                                input_path=_input_path,
                                output_path=_output_path,
                                suggestions=_suggestions_to_apply,
                                clip_info=clip_info,
                            )

                            if _result.get("success"):
                                # Verify output is valid (not 0 bytes)
                                if _output_path.exists() and _output_path.stat().st_size > 0:
                                    await self.clip_repo.update_clip_path(
                                        self.db, clip_id, str(_output_path)
                                    )
                                    for s in _suggestions_to_apply:
                                        await ClipSuggestionRepository.update_status(
                                            self.db, s["id"], ClipSuggestionStatus.APPLIED.value
                                        )
                                    logger.info(
                                        "[suggestion_applicator] Successfully enhanced clip %s",
                                        clip_id,
                                    )
                                else:
                                    # Clean up 0-byte output
                                    if _output_path.exists():
                                        _output_path.unlink(missing_ok=True)
                                        logger.warning(
                                            "[suggestion_applicator] Removed 0-byte enhanced clip for %s",
                                            clip_id,
                                        )
                                    logger.error(
                                        "[suggestion_applicator] Enhanced clip %s is 0 bytes — keeping original",
                                        clip_id,
                                    )
                            else:
                                # Clean up any 0-byte output on failure
                                if _output_path.exists() and _output_path.stat().st_size == 0:
                                    _output_path.unlink(missing_ok=True)
                                    logger.warning(
                                        "[suggestion_applicator] Removed 0-byte failed output for %s",
                                        clip_id,
                                    )
                                logger.error(
                                    "[suggestion_applicator] Failed to enhance clip %s: %s",
                                    clip_id, _result.get("error"),
                                )

                        _manual_suggestions = [
                            s for s in _suggestions
                            if s.get("kind") not in _auto_apply_kinds and s.get("status") == ClipSuggestionStatus.PENDING.value
                        ]
                        for s in _manual_suggestions:
                            await ClipSuggestionRepository.update_status(
                                self.db, s["id"], ClipSuggestionStatus.READY_FOR_REVIEW.value
                            )

                        await self.db.commit()

                except Exception as _aa_e:
                    logger.exception(
                        "[suggestion_applicator] Error applying suggestions to clip %s: %s",
                        clip_id, _aa_e,
                    )

                # Auto-copy clip to unified exports folder for local sync
                # NOTE: Must run AFTER suggestion_applicator so we copy the enhanced version
                try:
                    _clip_record_for_export = await self.clip_repo.get_clip_by_id(self.db, clip_id)
                    if _clip_record_for_export and _clip_record_for_export.get("file_path"):
                        _exports_dir = Path("/app/exports/clips")
                        _exports_dir.mkdir(parents=True, exist_ok=True)
                        _src = Path(_clip_record_for_export["file_path"])
                        if _src.exists():
                            _dst = _exports_dir / _src.name
                            import shutil as _shutil
                            _shutil.copy2(_src, _dst)
                            logger.info(f"  ✓ Copied clip to exports: {_src.name}")
                except Exception as _cp_e:
                    logger.warning(f"  exports copy failed: {_cp_e}")

                # Notify frontend via SSE after enhance
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
            
            # Mark render phase complete in metrics
            from ...core.metrics_service import get_metrics_collector
            get_metrics_collector().finish_render(task_id)
            
            # Cleanup temporary extracted segments to free disk space
            cleanup_extracted_segments(extracted_segment_paths)

            # IMMEDIATE CLEANUP: Remove ALL files after processing (user request)
            # Don't keep videos for days - delete immediately after task completes
            if len(clip_ids) > 0:
                try:
                    # Collect filenames of clips saved to DB so we never delete them.
                    # render_results is List[Tuple[int, Optional[Dict], float]],
                    # so each element is (index, info_dict, elapsed).
                    _saved_filenames = set()
                    for _idx, _ci, _elapsed in render_results:
                        if _ci and isinstance(_ci, dict):
                            if _ci.get("filename"):
                                _saved_filenames.add(_ci["filename"])
                            if _ci.get("thumbnail_filename"):
                                _saved_filenames.add(_ci["thumbnail_filename"])
                            if _ci.get("path"):
                                _saved_filenames.add(Path(_ci["path"]).name)
                                _saved_filenames.add(f"enhanced_{Path(_ci['path']).name}")

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

            # AGGRESSIVE CLEANUP: Delete source video and ALL temp files immediately
            # User requested: "no quiero que el sistema guarde videos"
            try:
                # Delete source video
                if video_path.exists():
                    video_path.unlink(missing_ok=True)
                    logger.info(f"[CLEANUP] Source video deleted: {video_path}")

                # Delete the entire task temp directory to prevent accumulation
                task_temp_dir = Path(self.config.temp_dir) / "clips" / task_id
                if task_temp_dir.exists() and task_temp_dir != clips_output_dir:
                    shutil.rmtree(task_temp_dir, ignore_errors=True)
                    logger.info(f"[CLEANUP] Deleted task temp dir: {task_temp_dir}")

                # Also clean up exports folder to prevent duplicates appearing
                exports_dir = Path("/app/exports/clips")
                if exports_dir.exists():
                    for f in exports_dir.iterdir():
                        if f.is_file() and f.stat().st_mtime < (time.time() - 3600):  # Older than 1 hour
                            f.unlink(missing_ok=True)
                            logger.debug(f"[CLEANUP] Deleted old export: {f.name}")

            except Exception as _aggressive_cleanup_e:
                logger.warning(f"[CLEANUP] Aggressive cleanup failed: {_aggressive_cleanup_e}")

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
                "segments_to_render": result["segments_to_render"],
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

