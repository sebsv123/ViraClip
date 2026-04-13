"""
Video processing coordinator with parallel agent execution.

Replaces sequential pipeline with parallel task execution using asyncio.gather().
"""

import asyncio
import logging
import os
import re
import tempfile
from typing import List, Dict, Any, Optional
from pathlib import Path
_Path = Path

logger = logging.getLogger(__name__)

# ── Emoji keyword map ──────────────────────────────────────────────────────────
_EMOJI_MAP: Dict[str, str] = {
    # energy / hype
    "insane": "🤯", "crazy": "🤯", "mind-blowing": "🤯", "shocking": "😱",
    "incredible": "🔥", "amazing": "🔥", "unbelievable": "😱", "wow": "😲",
    "fire": "🔥", "hot": "🔥", "viral": "🚀", "growth": "📈",
    "secret": "🤫", "hidden": "🤫", "truth": "💡", "fact": "💡",
    "money": "💰", "rich": "💰", "profit": "💰", "earn": "💰",
    "best": "🏆", "winner": "🏆", "number one": "🥇", "#1": "🥇",
    "love": "❤️", "heart": "❤️", "life": "✨", "dream": "✨",
    "stop": "🛑", "wait": "⏸️", "listen": "👂", "watch": "👀",
    "go": "🚀", "now": "⚡", "today": "📅", "free": "🎁",
    "dead": "💀", "kill": "💀", "die": "💀", "wrong": "❌",
    "right": "✅", "yes": "✅", "no": "❌", "perfect": "💯",
    "100": "💯", "real": "💯", "true": "💯",
}

# ── Creator profile caption_style → caption template mapping ─────────────────
_CAPTION_STYLE_TEMPLATE: Dict[str, str] = {
    "minimal":  "minimal",
    "bold":      "bold",
    "karaoke":   "tiktok_word",
    "none":      "default",
}

# ── CTA options per platform ───────────────────────────────────────────────────
_CTA_TEXTS: Dict[str, List[str]] = {
    "tiktok":    ["Follow for more 🔥", "Like if this helped 👍", "Comment your thoughts 💬"],
    "reels":     ["Follow for more 🔥", "Save this 🔖", "Share with a friend 👇"],
    "shorts":    ["Subscribe for more ▶️", "Like & Subscribe 🔔", "Comment below 💬"],
    "universal": ["Follow for more 🔥", "Share this 🚀", "Save for later 🔖"],
}

# Platform-aware Y position for CTA (above platform UI safe zone, in pixels on 1920-tall video)
_CTA_Y: Dict[str, int] = {
    "tiktok": 1580, "reels": 1600, "shorts": 1560, "universal": 1700,
}


async def _apply_cta_overlay(
    input_path: _Path,
    output_path: _Path,
    platform: str = "tiktok",
    custom_cta_text: Optional[str] = None,
) -> bool:
    """
    Burn a call-to-action drawtext overlay onto the last 2 seconds of a clip.
    Text is platform-aware and positioned above the platform's UI safe zone.
    Returns True on success.
    """
    import asyncio as _asyncio
    import subprocess as _sp

    try:
        # Probe clip duration
        probe = _sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(input_path)],
            capture_output=True, text=True, timeout=15,
        )
        import json as _json
        dur = float(_json.loads(probe.stdout).get("format", {}).get("duration", 0) or 0)
    except Exception:
        dur = 0.0

    if dur < 3.0:
        return False

    import random
    _plat = platform.lower() if platform.lower() in _CTA_TEXTS else "universal"
    cta_text = custom_cta_text if custom_cta_text else random.choice(_CTA_TEXTS[_plat])
    cta_y    = _CTA_Y.get(_plat, 1700)
    show_from = max(0.5, dur - 2.2)
    show_to   = dur - 0.1

    # Escape special chars for FFmpeg drawtext
    safe_text = cta_text.replace("'", "\\'").replace(":", "\\:")
    font_path = "/app/fonts/TikTokSans-Bold.ttf"
    font_arg  = f":fontfile={font_path}" if _Path(font_path).exists() else ""

    ft = (
        f"drawtext=text='{safe_text}'{font_arg}"
        f":fontsize=52:fontcolor=white:bordercolor=black:borderw=3"
        f":x=(w-text_w)/2:y={cta_y}"
        f":enable='between(t,{show_from:.2f},{show_to:.2f})'"
    )

    proc = await _asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path),
        "-vf", ft,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        str(output_path),
        stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
    return proc.returncode == 0


async def _apply_emoji_overlays(
    input_path: _Path,
    output_path: _Path,
    words: List[Dict[str, Any]],
    transcript: str = "",
) -> bool:
    """
    Scan word-level timestamps for high-energy keywords and overlay matching
    emoji for 1 second at the word's start time using FFmpeg drawtext.
    Returns True if at least one emoji was placed.
    """
    import asyncio as _asyncio

    # Build list of (timestamp, emoji) pairs from word list
    cues: List[tuple] = []
    seen_times: set = set()
    for w in (words or []):
        word_clean = re.sub(r"[^a-z0-9 \-#]", "", (w.get("word") or "").lower().strip())
        emoji_char  = _EMOJI_MAP.get(word_clean)
        if emoji_char and w.get("start") is not None:
            t = round(float(w["start"]), 2)
            if t not in seen_times:
                cues.append((t, emoji_char))
                seen_times.add(t)
        if len(cues) >= 6:
            break

    # Also scan full transcript for keywords missing from word list
    if not cues:
        for kw, emoji_char in _EMOJI_MAP.items():
            if kw in transcript.lower():
                cues.append((1.5, emoji_char))
                break

    if not cues:
        return False

    # Build one drawtext filter per cue, chained
    vf_parts = []
    for ts, emoji_char in cues[:5]:
        safe_emoji = emoji_char.encode("utf-8").decode("utf-8")
        # Use text substitution with safe ASCII fallback
        safe_text = safe_emoji.replace("'", "\\'")
        vf_parts.append(
            f"drawtext=text='{safe_text}'"
            f":fontsize=90:x=(w-text_w)/2-300:y=h/2-200"
            f":enable='between(t,{ts:.2f},{ts+0.9:.2f})'"
            f":alpha='if(lt(t-{ts:.2f},0.15),(t-{ts:.2f})/0.15,if(gt(t-{ts:.2f},0.75),1-(t-{ts:.2f}-0.75)/0.15,1))'"
        )

    vf = ",".join(vf_parts)

    proc = await _asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        str(output_path),
        stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
    return proc.returncode == 0


class VideoCoordinator:
    """
    Orchestrates video processing with parallel execution.
    
    Phases:
    1. Parallel: Transcription + Vision Analysis
    2. Sequential: Scoring with combined context
    3. Parallel: Render all clips simultaneously
    """
    
    def __init__(self, task_id: str, video_path: str, config: dict, force_fresh: bool = False):
        self.task_id = task_id
        self.video_path = video_path
        self.config = config
        self.force_fresh = force_fresh
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
            # PHASE 0: Check cache BEFORE launching pipeline (skip if force_fresh)
            cache_checker = get_cache_checker()
            cached = await cache_checker.check_existing_clips(
                task_id=self.task_id,
                video_path=self.video_path,
                min_clips=1,
                force_fresh=self.force_fresh
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
            
            # PHASE 2.5: Scene-aware segment refinement
            if self.config.get("use_scene_detection", True):
                try:
                    from pathlib import Path as _Path
                    from .scene_aware_segmenter import get_scene_aware_segmenter
                    
                    await emit_progress(self.task_id, "scoring", 62, "Refining segments with scene detection...")
                    
                    segmenter = get_scene_aware_segmenter()
                    segments = await segmenter.refine_segments_with_scenes(
                        video_path=_Path(self.video_path),
                        ai_segments=segments,
                        use_scene_detection=True
                    )
                    
                    logger.info(f"Scene-aware refinement complete: {len(segments)} segments aligned to scene boundaries")
                except Exception as scene_err:
                    logger.warning(f"Scene detection skipped: {scene_err}")
            
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
        from .vision_service import analyze_clip_visually as analyze_video_frames
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
            tasks.append(analyze_video_frames(Path(self.video_path), transcript=""))
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
            from .video_service import VideoService
            from ..services.clip_validator import get_clip_validator
            from ..utils.retry_helper import retry_ffmpeg_operation
            
            try:
                output_dir = _Path(self.config.get("output_dir", "/app/temp/uploads/clips"))
                output_dir.mkdir(parents=True, exist_ok=True)

                # ViralSegment uses 'start'/'end'; VideoService.create_single_clip
                # expects 'start_time'/'end_time' as "MM:SS" strings — preserve original format
                _raw_st = segment.get("start_time") if segment.get("start_time") is not None else segment.get("start")
                _raw_et = segment.get("end_time")   if segment.get("end_time")   is not None else segment.get("end")

                def _to_mmss(v) -> str:
                    """Convert float seconds or MM:SS string to MM:SS string."""
                    if v is None:
                        return "00:00"
                    if isinstance(v, (int, float)):
                        total = int(v)
                        return f"{total // 60:02d}:{total % 60:02d}"
                    return str(v)

                vs_segment = {
                    **segment,
                    "start_time": _to_mmss(_raw_st),
                    "end_time":   _to_mmss(_raw_et),
                    # Pass speed control params to creative pipeline
                    "playback_speed": self.config.get("playback_speed", 1.0),
                    "dramatic_slowmo": self.config.get("dramatic_slowmo", False),
                    "speed_ramp_enabled": self.config.get("speed_ramp_enabled", True),
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

                # Load creator profile for personalisation (non-blocking; defaults if missing)
                _creator_profile = None
                _user_id = self.config.get("user_id", "")
                if _user_id:
                    try:
                        from .creator_profile_service import get_profile as _get_cp
                        _creator_profile = _get_cp(_user_id)
                    except Exception as _cp_e:
                        logger.debug("Creator profile load skipped: %s", _cp_e)

                # Resolve caption template: profile.caption_style > config > default
                _caption_tmpl = self.config.get("caption_template", "default")
                if _creator_profile:
                    _style = _creator_profile.caption_style
                    _caption_tmpl = _CAPTION_STYLE_TEMPLATE.get(_style, _caption_tmpl)

                # Resolve preferred music category from profile or config
                _preferred_music = None
                if _creator_profile:
                    _genres = _creator_profile.music_genres()
                    if _genres and _genres[0] != "auto":
                        _preferred_music = _genres[0]

                clip = await VideoService.create_single_clip(
                    video_path=_Path(self.video_path),
                    segment=vs_segment,
                    clip_index=index,
                    output_dir=output_dir,
                    font_family=self.config.get("font_family", "TikTokSans-Regular"),
                    font_size=int(self.config.get("font_size", 24)),
                    font_color=self.config.get("font_color", "#FFFFFF"),
                    caption_template=_caption_tmpl,
                    output_format=self.config.get("output_format", "vertical"),
                    add_subtitles=self.config.get("add_subtitles", True),
                    task_id=self.task_id,
                    target_platform=self.config.get("target_platform", "tiktok"),
                    preferred_music_category=_preferred_music,
                )

                if clip is None:
                    raise RuntimeError(f"create_single_clip returned None for clip {index}")
                
                # Post-render validation
                clip_path = _Path(clip.get("path", ""))
                if clip_path.exists():
                    def _ts_to_s(v) -> float:
                        if isinstance(v, (int, float)):
                            return float(v)
                        try:
                            parts = str(v).strip().split(":")
                            if len(parts) == 2:
                                return int(parts[0]) * 60 + float(parts[1])
                            elif len(parts) == 3:
                                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                            return float(v)
                        except (ValueError, TypeError):
                            return float(v)
                    expected_duration = _ts_to_s(vs_segment["end_time"]) - _ts_to_s(vs_segment["start_time"])
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
                    logger.info(f"[Coordinator] Calling creative pipeline for clip {index}...")
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
                    logger.info(f"[Coordinator] Creative pipeline completed for clip {index}: enhanced={creative_meta.get('creative_enhanced', False)}")
                except ImportError as _ie:
                    logger.error(f"[Coordinator] CRITICAL: Creative pipeline import failed for clip {index}: {_ie}", exc_info=True)
                    clip.pop("words", None)
                    clip.pop("audio_features", None)
                except Exception as _ce:
                    logger.error(f"[Coordinator] Creative pipeline FAILED for clip {index}: {type(_ce).__name__}: {_ce}", exc_info=True)
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

                # ── Emoji keyword overlays ─────────────────────────────────────
                # Scan transcript for high-energy keywords → burn FFmpeg drawtext
                # emoji at the matching word timestamp.  Purely additive / safe.
                try:
                    _clip_path_obj = _Path(clip["path"])
                    _transcript_text = vs_segment.get("text", "") or vs_segment.get("transcript", "")
                    _emo_out = _clip_path_obj.with_name(f"emo_{_clip_path_obj.name}")
                    _emo_applied = await _apply_emoji_overlays(
                        _clip_path_obj, _emo_out,
                        words=_words_for_editor,
                        transcript=_transcript_text,
                    )
                    if _emo_applied and _emo_out.exists() and _emo_out.stat().st_size > 0:
                        _clip_path_obj.unlink(missing_ok=True)
                        _emo_out.rename(_clip_path_obj)
                        clip["path"] = str(_clip_path_obj)
                        clip["emoji_overlays_applied"] = True
                        logger.info("  [Emoji] Keyword emoji overlays applied")
                    else:
                        _emo_out.unlink(missing_ok=True)
                except Exception as _eo_e:
                    logger.debug("Emoji overlays skipped for clip %d: %s", index, _eo_e)

                # ── A/B variant generation ────────────────────────────────────
                # Generate 2 quick variants (caption style swap + BGM swap) so
                # the user can A/B test without waiting for a full re-render.
                # Runs fire-and-forget; failures are non-fatal.
                try:
                    from .variant_generator import generate_clip_variants
                    _clip_path_obj = _Path(clip["path"])
                    _primary_style = creative_meta.get("caption_style") or "tiktok"
                    _primary_bgm_cat = creative_meta.get("bgm_category") or "hype"
                    _variants = await generate_clip_variants(
                        clip_path=_clip_path_obj,
                        words=_words_for_editor,
                        platform=self.config.get("target_platform", "tiktok"),
                        primary_caption_style=_primary_style,
                        primary_bgm_category=_primary_bgm_cat,
                    )
                    if _variants:
                        clip["variants"] = _variants
                        logger.info(
                            "  [Variants] %d A/B variant(s) generated for clip %d",
                            len(_variants), index,
                        )
                except Exception as _ve:
                    logger.debug("Variant generation skipped for clip %d: %s", index, _ve)

                # ── Transition auto-selection ──────────────────────────────────
                # Select appropriate transition for this clip based on template and energy
                try:
                    from .transition_selector import get_transition_selector
                    
                    selector = get_transition_selector()
                    viral_score = vs_segment.get("virality_score", 50.0)
                    
                    # Determine if transition should be used
                    should_transition = selector.should_use_transition(
                        clip_index=index,
                        total_clips=len(segments),
                        viral_score=viral_score
                    )
                    
                    if should_transition:
                        # Get audio energy for transition selection
                        _audio_features = clip.get("audio_features", {})
                        _energy = _audio_features.get("energy", 0.5)
                        
                        # Select transition type
                        transition_type = selector.select_transition(
                            template_style=self.config.get("viral_template", "viral"),
                            energy_level=_energy,
                            use_morph=self.config.get("use_morph_transition", False)
                        )
                        
                        clip["transition_type"] = transition_type.value
                        clip["transition_enabled"] = True
                        logger.info(
                            "  [Transition] Clip %d: %s transition selected (viral_score=%.1f, energy=%.2f)",
                            index, transition_type.value, viral_score, _energy
                        )
                    else:
                        clip["transition_enabled"] = False
                        logger.debug("  [Transition] Clip %d: No transition (index=%d, viral_score=%.1f)", index, index, viral_score)
                
                except Exception as _tr_e:
                    logger.debug("Transition selection skipped for clip %d: %s", index, _tr_e)
                    clip["transition_enabled"] = False

                # ── CTA overlay (last 2 s) ─────────────────────────────────────
                # "Follow for more 🔥" / "Comment below 👇" injected as drawtext
                # on the final clip, respecting the platform safe zone.
                try:
                    _clip_path_obj = _Path(clip["path"])
                    _platform = self.config.get("target_platform", "tiktok")
                    _cta_out = _clip_path_obj.with_name(f"cta_{_clip_path_obj.name}")
                    _profile_cta = (
                        _creator_profile.cta_for_platform(_platform)
                        if _creator_profile else None
                    )
                    _cta_applied = await _apply_cta_overlay(
                        _clip_path_obj, _cta_out,
                        platform=_platform,
                        custom_cta_text=_profile_cta,
                    )
                    if _cta_applied and _cta_out.exists() and _cta_out.stat().st_size > 0:
                        _clip_path_obj.unlink(missing_ok=True)
                        _cta_out.rename(_clip_path_obj)
                        clip["path"] = str(_clip_path_obj)
                        clip["cta_overlay_applied"] = True
                        logger.info("  [CTA] Call-to-action overlay applied (%s)", _platform)
                    else:
                        _cta_out.unlink(missing_ok=True)
                except Exception as _cta_e:
                    logger.debug("CTA overlay skipped for clip %d: %s", index, _cta_e)

                # ── Brand overlay from creator profile ────────────────────────
                if _creator_profile and (
                    _creator_profile.watermark_text or _creator_profile.watermark_image_path
                ):
                    try:
                        from .brand_overlay_service import (
                            BrandConfig as _BrandCfg,
                            apply_text_watermark as _apply_text_wm,
                            apply_image_watermark as _apply_img_wm,
                        )
                        _brand_in = _Path(clip["path"])
                        _brand_out = _brand_in.with_name(f"brand_{_brand_in.name}")
                        _bcfg = _BrandCfg(
                            text=_creator_profile.watermark_text or "",
                            image_path=_creator_profile.watermark_image_path or "",
                            position=_creator_profile.watermark_position,
                        )
                        if _creator_profile.watermark_image_path:
                            _brand_ok = await _apply_img_wm(str(_brand_in), str(_brand_out), _bcfg)
                        else:
                            _brand_ok = await _apply_text_wm(str(_brand_in), str(_brand_out), _bcfg)
                        if _brand_ok and _brand_out.exists() and _brand_out.stat().st_size > 0:
                            _brand_in.unlink(missing_ok=True)
                            _brand_out.rename(_brand_in)
                            clip["path"] = str(_brand_in)
                            clip["brand_overlay_applied"] = True
                            logger.info(
                                "  [Brand] Watermark applied (%s / %s)",
                                _creator_profile.watermark_position,
                                "image" if _creator_profile.watermark_image_path else "text",
                            )
                        else:
                            _brand_out.unlink(missing_ok=True)
                    except Exception as _brand_e:
                        logger.debug("Brand overlay skipped for clip %d: %s", index, _brand_e)

                # ── Audio denoiser (opt-in: config.denoise_audio=True) ───────
                if self.config.get("denoise_audio", False):
                    try:
                        from .audio_denoiser import denoise_audio as _denoise
                        _dn_in = _Path(clip["path"])
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
                            clip["audio_denoised"] = True
                            clip["audio_lufs_before"] = _dn_result.original_lufs
                            clip["audio_lufs_after"] = _dn_result.output_lufs
                            logger.info("  [Denoiser] Audio cleaned (%.1f→%.1f LUFS)",
                                        _dn_result.original_lufs or -99, _dn_result.output_lufs or -99)
                        else:
                            _dn_out.unlink(missing_ok=True)
                    except Exception as _dn_e:
                        logger.debug("Audio denoiser skipped for clip %d: %s", index, _dn_e)

                # ── Jump-cut engine with zoom transitions (opt-in: config.jump_cut=True) ───────────
                if self.config.get("jump_cut", False):
                    try:
                        from .cut_zoom_service import apply_jump_cuts_with_zoom
                        _jc_in = _Path(clip["path"])
                        _jc_out = _jc_in.with_name(f"jc_{_jc_in.name}")
                        _jc_words = list(clip.get("words") or vs_segment.get("words") or [])
                        
                        # Viral-style editing: aggressive 0.3s cuts + zoom transitions
                        _jc_result = await apply_jump_cuts_with_zoom(
                            video_path=str(_jc_in),
                            output_path=str(_jc_out),
                            words=_jc_words,
                            min_silence_sec=self.config.get("jump_cut_min_silence", 0.3),  # Aggressive by default
                            zoom_on_cuts=self.config.get("zoom_on_cuts", True),
                            zoom_factor=self.config.get("cut_zoom_factor", 1.08),
                        )
                        
                        if _jc_result.get("success") and _jc_out.exists() and _jc_out.stat().st_size > 0:
                            _jc_in.unlink(missing_ok=True)
                            _jc_out.rename(_jc_in)
                            clip["jump_cut_applied"] = True
                            clip["jump_cut_time_saved"] = _jc_result.get("time_saved", 0)
                            clip["jump_cut_fillers_removed"] = _jc_result.get("filler_words_removed", 0)
                            clip["jump_cut_silences_removed"] = _jc_result.get("silence_gaps_removed", 0)
                            clip["zoom_transitions_applied"] = _jc_result.get("zoom_count", 0)
                            clip["cut_zoom_enabled"] = _jc_result.get("zoom_applied", False)
                            logger.info(
                                "  [JumpCut+Zoom] %.1fs saved, %d cuts, %d zooms, %d fillers, %d silences",
                                _jc_result.get("time_saved", 0),
                                _jc_result.get("cut_count", 0),
                                _jc_result.get("zoom_count", 0),
                                _jc_result.get("filler_words_removed", 0),
                                _jc_result.get("silence_gaps_removed", 0),
                            )
                        else:
                            _jc_out.unlink(missing_ok=True)
                            logger.warning("  [JumpCut+Zoom] Failed: %s", _jc_result.get("error", "unknown"))
                    except Exception as _jc_e:
                        logger.error("Jump-cut+zoom service failed for clip %d: %s", index, _jc_e, exc_info=True)

                # ── Language detection + locale info ──────────────────────────
                _transcript_for_lang = vs_segment.get("text", "") or vs_segment.get("transcript", "")
                if _transcript_for_lang:
                    try:
                        from .language_detector import detect_language as _detect_lang
                        _lang_result = _detect_lang(_transcript_for_lang)
                        clip["detected_language"] = _lang_result.language
                        clip["language_confidence"] = _lang_result.confidence
                        clip["locale_territory"] = _lang_result.locale.get("territory", "global")
                    except Exception as _ld_e:
                        logger.debug("Language detection skipped: %s", _ld_e)

                # ── Actionable clip health report ─────────────────────────────
                try:
                    from .clip_health_service import generate_health_report as _health_report
                    _health = _health_report(
                        clip_id=clip.get("id", f"clip_{index}"),
                        virality_score=float(creative_meta.get("viral_score") or vs_segment.get("virality_score") or 0),
                        hook_score=float(creative_meta.get("hook_score") or vs_segment.get("hook_score") or 0),
                        hook_start=creative_meta.get("hook_start"),
                        hook_type=vs_segment.get("hook_type"),
                        duration=float(vs_segment.get("end_time", 30) - vs_segment.get("start_time", 0)),
                        platform=self.config.get("target_platform", "tiktok"),
                        loudnorm_applied=bool(creative_meta.get("loudnorm_applied")),
                        sfx_injected=bool(creative_meta.get("sfx_injected")),
                        broll_count=len(creative_meta.get("broll_overlays") or []),
                        has_subtitles=self.config.get("add_subtitles", True),
                        hashtag_count=len(vs_segment.get("hashtags") or vs_segment.get("suggested_hashtags") or []),
                        zoom_punch_applied=bool(creative_meta.get("zoom_punch_applied")),
                    )
                    clip["health_report"] = _health.to_dict()
                    clip["health_grade"] = _health.grade
                    clip["health_score"] = _health.overall_score
                    logger.info(
                        "  [Health] Clip %d: Grade %s (%s/100) — %s",
                        index, _health.grade, _health.overall_score,
                        _health.top_fix or "No critical issues",
                    )
                except Exception as _he:
                    logger.debug("Health report skipped for clip %d: %s", index, _he)

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

                # ── Cleanup intermediate files, keep only the final clip ──────
                try:
                    _final_path = _Path(clip["path"])
                    _final_dir = _final_path.parent
                    # Rename final to a clean name: final_clip_N_<stem>.mp4
                    # Strip all known prefixes from the name so it's human-readable
                    _PREFIXES = ("sub_", "broll_", "ep_", "jc_", "centered_",
                                 "music_fb_", "music_", "duck_", "tp_", "emo_",
                                 "cta_", "brand_", "dn_", "gaze_", "efx_")
                    _clean = _final_path.name
                    for _p in _PREFIXES:
                        _clean = _clean.replace(_p, "")
                    _clean_name = f"final_clip_{index + 1}_{_clean}"
                    _clean_path = _final_dir / _clean_name
                    if not _clean_path.exists():
                        _final_path.rename(_clean_path)
                        clip["path"] = str(_clean_path)
                        clip["filename"] = _clean_name

                    # ── Copy to unified exports folder ────────────────────────────
                    import shutil as _shutil
                    _exports_dir = _Path("/app/exports/clips")
                    _exports_dir.mkdir(parents=True, exist_ok=True)
                    _exports_path = _exports_dir / _clean_name
                    if _clean_path.exists():
                        _shutil.copy2(_clean_path, _exports_path)
                        logger.info("  [Export] Copied to unified folder: %s", _exports_path)

                    # Delete all intermediate files for this clip index
                    # Match by clip_X_viral pattern (timestamps vary per intermediate)
                    import re as _re
                    _clip_match = _re.search(r'clip_(\d+)_viral_\d+_\d{4}-\d{4}', _clean)
                    _removed_intermediates = 0
                    if _clip_match:
                        _clip_pattern = f"clip_{_clip_match.group(1)}_viral_"  # e.g. "clip_1_viral_"
                        for _f in _final_dir.iterdir():
                            if _f.is_file() and _f.name != _clean_name:
                                # Delete files with same clip_X_viral pattern but different prefix or timestamp
                                if _clip_pattern in _f.name and _f.suffix in (".mp4", ".mov", ".jpg", ".wav", ".png"):
                                    _f.unlink(missing_ok=True)
                                    _removed_intermediates += 1
                    if _removed_intermediates:
                        logger.info("  [Cleanup] %d intermediate files deleted for clip %d", _removed_intermediates, index)
                except Exception as _cl_e:
                    logger.debug("Intermediate cleanup skipped for clip %d: %s", index, _cl_e)

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
