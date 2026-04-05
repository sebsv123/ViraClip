"""
Video processing coordinator with parallel agent execution.

Replaces sequential pipeline with parallel task execution using asyncio.gather().
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoCoordinator:
    """
    Orchestrates video processing with parallel execution.
    
    Phases:
    1. Parallel: Transcription + Vision Analysis
    2. Sequential: Scoring with combined context
    3. Parallel: Render all clips simultaneously
    """
    
    def __init__(self, task_id: str, video_path: str, config: dict):
        self.task_id = task_id
        self.video_path = video_path
        self.config = config
        self.clips_generated: List[dict] = []
        self.errors: List[Exception] = []
    
    async def run(self) -> List[dict]:
        """
        Execute the complete video processing pipeline.
        
        Returns:
            List of successfully generated clip metadata
        """
        from .progress_emitter import emit_progress, emit_completion, emit_error
        from .cache_checker import get_cache_checker
        
        try:
            # PHASE 0: Check cache BEFORE launching pipeline
            cache_checker = get_cache_checker()
            cached = await cache_checker.check_existing_clips(
                task_id=self.task_id,
                video_path=self.video_path,
                min_clips=1
            )
            
            if cached:
                await emit_progress(
                    self.task_id,
                    "cache_hit",
                    100,
                    f"✅ {len(cached)} clips already exist (cache hit)"
                )
                logger.info(f"Cache hit for task {self.task_id}: {len(cached)} clips")
                return cached
            
            logger.info(f"🎬 Starting coordinator for task {self.task_id}")
            
            # PHASE 1: Parallel transcription + vision analysis
            await emit_progress(self.task_id, "analysis", 10, "Starting analysis...")
            
            transcript, vision_data = await self._parallel_analysis()
            
            await emit_progress(self.task_id, "analysis", 40, "Analysis completed")
            
            # PHASE 2: Scoring with combined context
            await emit_progress(self.task_id, "scoring", 50, "Scoring viral segments...")
            
            segments = await self._score_segments(transcript, vision_data)
            
            await emit_progress(
                self.task_id,
                "scoring",
                60,
                f"{len(segments)} segments identified"
            )
            
            # PHASE 3: Parallel clip rendering
            await emit_progress(self.task_id, "render", 65, "Rendering clips...")
            
            clips = await self._parallel_rendering(segments)
            
            # Filter successful clips
            successful = [c for c in clips if not isinstance(c, Exception)]
            failed = [c for c in clips if isinstance(c, Exception)]
            
            if failed:
                logger.warning(
                    f"⚠️  {len(failed)} clips failed for task {self.task_id}: {failed}"
                )
            
            self.clips_generated = successful
            
            # PHASE 4: Completion
            await emit_completion(self.task_id, len(successful))
            
            logger.info(
                f"✅ Task {self.task_id} complete: "
                f"{len(successful)} successful, {len(failed)} failed"
            )
            
            return successful
            
        except Exception as e:
            logger.error(f"❌ Coordinator error for task {self.task_id}: {e}", exc_info=True)
            await emit_error(self.task_id, str(e))
            raise
    
    async def _parallel_analysis(self) -> tuple[str, Optional[dict]]:
        """
        Run transcription and vision analysis in parallel.
        
        Returns:
            (transcript, vision_data) tuple
        """
        from .video_service import VideoService
        from .vision_service import analyze_video_frames
        from ..config import get_config
        
        config = get_config()
        processing_mode = self.config.get("processing_mode", "fast")

        # Transcription task — calls real faster-whisper via VideoService
        async def get_transcript():
            return await VideoService.generate_transcript(
                Path(self.video_path), processing_mode
            )

        # Vision analysis is optional - run if enabled
        tasks = [get_transcript()]
        
        if config.vision_analysis_enabled:
            tasks.append(analyze_video_frames(self.video_path))
        else:
            tasks.append(asyncio.sleep(0))  # Dummy task that returns None
        
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        transcript = results[0]
        vision_data = results[1] if len(results) > 1 and results[1] else None
        
        logger.info(
            f"Analysis complete: transcript={len(transcript) if transcript else 0} chars, "
            f"vision={'enabled' if vision_data else 'disabled'}"
        )
        
        return transcript, vision_data
    
    async def _score_segments(self, transcript: str, vision_data: Optional[dict]) -> List[dict]:
        """
        Score segments using validated LLM scoring.
        
        Args:
            transcript: Video transcript
            vision_data: Optional vision analysis data
            
        Returns:
            List of scored segments
        """
        from .ai_validator import get_validated_segments
        from .ai_prompts import VIRAL_SCORER_SYSTEM_PROMPT, build_dynamic_user_prompt
        from ..config import get_config
        
        config = get_config()
        language = self.config.get("language", "es")
        num_clips = self.config.get("num_clips", 3)
        
        # Create scoring function that uses static/dynamic prompts
        async def score_with_groq(transcript, language, num_clips, previous_error=None):
            """Wrapper for Groq API call with prompt splitting."""
            import httpx
            
            user_prompt = build_dynamic_user_prompt(
                transcript=transcript,
                language=language,
                num_clips=num_clips,
                previous_error=previous_error
            )
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {config.groq_api_key}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": VIRAL_SCORER_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.3
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        
        # Get validated segments with retry loop
        segments = await get_validated_segments(
            scoring_function=score_with_groq,
            transcript=transcript,
            language=language,
            num_clips=num_clips,
            max_retries=3
        )
        
        # Convert Pydantic models to dicts
        return [seg.model_dump() for seg in segments]
    
    async def _parallel_rendering(self, segments: List[dict]) -> List[dict]:
        """
        Render all clips in parallel.
        
        Args:
            segments: List of segment metadata
            
        Returns:
            List of clip results (mix of dicts and Exceptions)
        """
        from .progress_emitter import emit_clip_generated
        
        async def render_single_clip(segment: dict, index: int) -> dict:
            """Render one clip via VideoService and emit progress."""
            from pathlib import Path as _Path
            from ..services.clip_validator import get_clip_validator
            from ..utils.retry_helper import retry_ffmpeg_operation
            
            try:
                output_dir = _Path(self.config.get("output_dir", "/app/temp/uploads/clips"))
                output_dir.mkdir(parents=True, exist_ok=True)

                # ViralSegment uses 'start'/'end'; VideoService.create_single_clip
                # expects 'start_time'/'end_time' — adapt here
                vs_segment = {
                    **segment,
                    "start_time": segment.get("start_time") or segment.get("start"),
                    "end_time":   segment.get("end_time")   or segment.get("end"),
                }
                
                # Pre-render validation
                validator = get_clip_validator()
                validation = await validator.validate_input(
                    video_path=_Path(self.video_path),
                    start_time=vs_segment["start_time"],
                    end_time=vs_segment["end_time"],
                    words=segment.get("words"),
                )
                
                if not validation.passed:
                    error_msg = f"Pre-render validation failed for clip {index}: {', '.join(validation.issues)}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                if validation.warnings:
                    logger.warning(f"Clip {index} validation warnings: {', '.join(validation.warnings)}")

                clip = await VideoService.create_single_clip(
                    video_path=_Path(self.video_path),
                    segment=vs_segment,
                    clip_index=index,
                    output_dir=output_dir,
                    font_family=self.config.get("font_family", "TikTokSans-Regular"),
                    font_size=int(self.config.get("font_size", 24)),
                    font_color=self.config.get("font_color", "#FFFFFF"),
                    caption_template=self.config.get("caption_template", "default"),
                    output_format=self.config.get("output_format", "vertical"),
                    add_subtitles=self.config.get("add_subtitles", True),
                    task_id=self.task_id,
                    target_platform=self.config.get("target_platform", "tiktok"),
                )

                if clip is None:
                    raise RuntimeError(f"create_single_clip returned None for clip {index}")
                
                # Post-render validation
                clip_path = _Path(clip.get("path", ""))
                if clip_path.exists():
                    expected_duration = vs_segment["end_time"] - vs_segment["start_time"]
                    post_validation = await validator.validate_output(
                        output_path=clip_path,
                        expected_duration=expected_duration,
                        source_path=_Path(self.video_path),
                    )
                    
                    if not post_validation.passed:
                        error_msg = f"Post-render validation failed for clip {index}: {', '.join(post_validation.issues)}"
                        logger.error(error_msg)
                        # Don't fail the clip, but log the issue
                        clip["validation_issues"] = post_validation.issues
                    
                    if post_validation.warnings:
                        logger.warning(f"Clip {index} post-render warnings: {', '.join(post_validation.warnings)}")
                        clip["validation_warnings"] = post_validation.warnings
                    
                    # Add validation metadata
                    clip["validation_passed"] = post_validation.passed
                    clip.update(post_validation.metadata)

                # Phase 9: Creative Engine — enhance clip with timeline-driven effects
                _words_for_editor = list(clip.get("words") or [])
                creative_meta: dict = {}
                try:
                    from .creative_pipeline import get_creative_pipeline
                    creative_meta = await get_creative_pipeline().enhance(
                        clip_path=_Path(clip["path"]),
                        source_video=_Path(self.video_path),
                        segment=vs_segment,
                        words=clip.pop("words", []) or [],
                        audio_features=clip.pop("audio_features", {}) or {},
                        task_id=self.task_id,
                        clip_index=index,
                        platform=self.config.get("target_platform", "tiktok"),
                    )
                    clip.update(creative_meta)
                except Exception as _ce:
                    logger.warning("Creative pipeline skipped for clip %d: %s", index, _ce)
                    clip.pop("words", None)
                    clip.pop("audio_features", None)

                # Smart Auto-Editor — viral keyword analysis + TEXT_POP overlay application
                try:
                    from .smart_auto_editor import SmartAutoEditor
                    _editor = SmartAutoEditor()
                    _transcript = vs_segment.get("transcript", "") or vs_segment.get("text", "")
                    _edit_analysis = await _editor.analyze_and_edit(
                        transcript=_transcript,
                        word_timings=_words_for_editor,
                    )
                    _decisions = _edit_analysis.get("decisions", [])

                    # Apply TEXT_POP overlays to clip (purely additive — safe after creative pipeline)
                    _text_pops_applied = 0
                    _hook_offset = 1.0 if creative_meta.get("hook_reorder_applied") else 0.0
                    _clip_path_obj = _Path(clip["path"])
                    _textpop_out = _clip_path_obj.with_name(f"tp_{_clip_path_obj.name}")
                    _tp_result = await _editor.apply_text_pops(
                        clip_path=_clip_path_obj,
                        output_path=_textpop_out,
                        decisions=_decisions,
                        hook_offset=_hook_offset,
                    )
                    if _tp_result and _textpop_out.exists() and _textpop_out.stat().st_size > 0:
                        _clip_path_obj.unlink(missing_ok=True)
                        _textpop_out.rename(_clip_path_obj)
                        _text_pops_applied = sum(
                            1 for d in _decisions if d.get("type") == "text_pop"
                        )
                        logger.info("  [SmartEditor] %d text-pop overlays applied", _text_pops_applied)
                    else:
                        _textpop_out.unlink(missing_ok=True)

                    # Merge smart-edit fields into creative_meta so they are persisted together
                    creative_meta["smart_edit_decisions"] = _edit_analysis.get("total_decisions", 0)
                    creative_meta["smart_edit_summary"]   = _edit_analysis.get("edit_summary", "")
                    creative_meta["smart_edit_time_saved"] = _edit_analysis.get("estimated_time_saved", 0.0)
                    creative_meta["text_pops_applied"] = _text_pops_applied
                    clip["smart_edit_decisions"] = creative_meta["smart_edit_decisions"]
                    clip["smart_edit_summary"]   = creative_meta["smart_edit_summary"]
                    clip["smart_edit_time_saved"] = creative_meta["smart_edit_time_saved"]
                    clip["text_pops_applied"] = _text_pops_applied
                    logger.info(
                        "  [SmartEditor] clip %d: %d decisions (~%.1fs saved)",
                        index,
                        creative_meta["smart_edit_decisions"],
                        creative_meta["smart_edit_time_saved"],
                    )
                except Exception as _se:
                    logger.debug("SmartAutoEditor skipped for clip %d: %s", index, _se)

                # Videofy Timeline Integration (optional) — build structured timeline for future use
                if self.config.get("enable_timeline", False):
                    try:
                        from ..project_store import ProjectStore
                        from ..services.timeline_builder import build_clip_timeline
                        
                        store = ProjectStore()
                        
                        # Build timeline if not already done
                        if not store.is_step_done(self.task_id, "timeline"):
                            # Get OpenAI client for Vision AI
                            openai_client = None
                            try:
                                import os
                                from openai import OpenAI
                                if os.getenv("OPENAI_API_KEY"):
                                    openai_client = OpenAI()
                            except Exception:
                                pass
                            
                            # Build timeline from segment
                            timeline = await build_clip_timeline(
                                task_id=self.task_id,
                                video_path=_Path(self.video_path),
                                whisper_words=_words_for_editor,
                                ai_segments=[{
                                    "text": vs_segment.get("transcript", "") or vs_segment.get("text", ""),
                                    "start_time": vs_segment.get("start_time", 0.0),
                                    "end_time": vs_segment.get("end_time", 3.0),
                                    "virality_score": vs_segment.get("virality_score", 0.0),
                                    "hook_score": vs_segment.get("hook_score", 0.0),
                                    "hook_type": vs_segment.get("hook_type", "none"),
                                    "mood": creative_meta.get("preset_used", "neutral"),
                                }],
                                store=store,
                                openai_client=openai_client,
                                preset=creative_meta.get("preset_used", "default"),
                                skip_vision=not self.config.get("enable_vision_ai", False),
                            )
                            
                            # Add timeline metadata to clip
                            creative_meta["timeline_built"] = True
                            creative_meta["timeline_id"] = timeline.clip_id
                            clip["timeline_built"] = True
                            logger.info(f"  [Timeline] Built timeline with {len(timeline.segments)} segments")

                            # Optional: render with camera movements (enable_timeline_render=True)
                            if self.config.get("enable_timeline_render", False):
                                try:
                                    from ..services.timeline_renderer import apply_timeline_to_clip
                                    _clip_p = _Path(clip["path"])
                                    _tl_out = _clip_p.parent / f"{_clip_p.stem}_timeline{_clip_p.suffix}"
                                    rendered = await apply_timeline_to_clip(
                                        timeline=timeline,
                                        source_video=_clip_p,
                                        output_path=_tl_out,
                                    )
                                    if rendered.exists():
                                        clip["path"] = str(rendered)
                                        clip["filename"] = rendered.name
                                        creative_meta["timeline_rendered"] = True
                                        logger.info(f"  [Timeline] Rendered with camera movements → {rendered.name}")
                                except Exception as _trf:
                                    logger.debug("Timeline rendering skipped for clip %d: %s", index, _trf)

                    except Exception as _te:
                        logger.debug("Timeline building skipped for clip %d: %s", index, _te)

                # Persist all creative metadata (including smart-edit fields) in one DB write
                try:
                    from ..repositories.clip_repository import ClipRepository
                    from ..database import AsyncSessionLocal
                    _clip_db_id = clip.get("id")
                    if _clip_db_id and creative_meta:
                        async with AsyncSessionLocal() as _db:
                            await ClipRepository.update_creative_meta(
                                _db, str(_clip_db_id), creative_meta
                            )
                except Exception as _dbe:
                    logger.warning("Creative meta DB persist failed for clip %d: %s", index, _dbe)

                await emit_clip_generated(
                    task_id=self.task_id,
                    clip_id=clip.get("id", f"clip_{self.task_id}_{index}"),
                    clip_path=clip.get("path", ""),
                    clip_number=index + 1,
                    total_clips=len(segments),
                )

                logger.info(f"Clip {index} rendered: {clip.get('path')}")
                return clip

            except Exception as e:
                logger.error(f"Clip {index} rendering failed: {e}", exc_info=True)
                return e
        
        # Launch all renders in parallel with return_exceptions=True
        render_tasks = [
            render_single_clip(seg, i)
            for i, seg in enumerate(segments)
        ]
        
        clips = await asyncio.gather(*render_tasks, return_exceptions=True)
        
        return clips
    
    def get_stats(self) -> dict:
        """Get coordinator statistics."""
        return {
            "task_id": self.task_id,
            "clips_generated": len(self.clips_generated),
            "errors": len(self.errors),
            "success_rate": (
                len(self.clips_generated) / (len(self.clips_generated) + len(self.errors))
                if (len(self.clips_generated) + len(self.errors)) > 0
                else 0
            )
        }
