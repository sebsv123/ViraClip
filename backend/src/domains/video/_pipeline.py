"""End-to-end video processing pipeline.

`process_video_complete` is the master orchestrator that takes a video URL
through download → transcript → AI analysis → clip rendering → polish.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ...core.cache_manager import (
    cache_transcript_smart,
    get_cache_manager,
    get_cached_transcript_smart,
)
from ...core.error_handler import execute_with_recovery
from ...core.metrics_service import get_metrics_collector
from ...domains.broll.broll_service import BrollService
from ...utils.async_helpers import run_in_thread
from ...video_processing.hook_analysis import analyze_segment_virality
from ...video_processing.niche_analysis import analyze_content_niche, optimize_for_platform
from ...video_processing.utils import parse_timestamp_to_seconds
from ...youtube_utils import async_get_youtube_video_info, get_youtube_video_id

from . import _clips, _helpers, _transcript
from ._helpers import get_service_config

logger = logging.getLogger(__name__)

def determine_source_type(url: str) -> str:
    """Determine if source is YouTube or uploaded file."""
    video_id = get_youtube_video_id(url)
    return "youtube" if video_id else "video_url"



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

            video_path = await _transcript.download_video(url, task_id=task_id)
            if not video_path:
                raise Exception("Failed to download video")
        else:
            video_path = _helpers.resolve_local_video_path(url)
            if not video_path.exists():
                raise Exception("Video file not found")

        # Post-download duration guard (catches cases where preflight info was unavailable)
        file_duration = _helpers.get_file_duration(video_path)
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
                _transcript.generate_transcript,
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

        # Elite mode bypasses all analysis caches to force fresh high-quality analysis
        _bypass_analysis_cache = (processing_mode == "elite")
        if _bypass_analysis_cache:
            logger.info("[CACHE] Bypassing AI analysis cache for elite mode — forcing fresh analysis")

        # Try cached analysis from parameter first (skip if bypassing)
        if cached_analysis_json and not _bypass_analysis_cache:
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

        # Try Smart Cache for AI analysis (keyed by video hash + processing_mode)
        if relevant_parts is None and not _bypass_analysis_cache:
            video_hash = cache_manager._generate_file_hash(video_path)
            cache_key_mode = f"{video_hash}:{processing_mode}"
            cached_ai = await cache_manager.get("ai_analysis", cache_key_mode)
            if cached_ai:
                relevant_parts = _SimpleResult(cached_ai["data"])
                logger.info(f"[CACHE] Smart cache HIT for AI analysis ({processing_mode}): {len(cached_ai['data'].get('most_relevant_segments', []))} segments")

        if relevant_parts is None:
            # AI analysis with retry logic
            relevant_parts = await execute_with_recovery(
                _transcript.analyze_transcript,
                transcript,
                video_duration=file_duration or 0.0,
                include_broll=include_broll,
                max_retries=2,
                context={"stage": "ai_analysis", "task_id": task_id}
            )
            # Cache in smart cache (only for non-elite modes to avoid polluting cache)
            if not _bypass_analysis_cache:
                video_hash = cache_manager._generate_file_hash(video_path)
                cache_key_mode = f"{video_hash}:{processing_mode}"
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
                await cache_manager.set("ai_analysis", cache_key_mode, cache_payload)
                logger.info(f"[CACHE] Saved AI analysis to smart cache ({processing_mode})")

        # Step 3.1: Elite Creative Direction — bypassed (Groq 400/429 always fails)
        if progress_callback:
            await progress_callback(55, "Preparing creative plan...", "processing")
        from ...domains.ai.elite_ai_service import EliteCreativePlan as _EliteCreativePlan
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
        
        # Use LLMRouter (Groq) for virality scoring instead of Ollama
        from ...domains.ai.llm_router import LLMRouter
        llm_router = LLMRouter()
        try:
            virality_data = await llm_router.score_segments(
                "\n\n".join(t for t in segment_texts if t), language="es", num_clips=num_clips
            )
        except Exception as _llm_err:
            # Degrade gracefully on 429/5xx/network: continue with rule-based fallback so pipeline isn't blocked
            logger.warning(
                f"[VIRALITY] LLMRouter.score_segments failed ({type(_llm_err).__name__}: {_llm_err}) — falling back to rule-based scoring"
            )
            virality_data = llm_router._rule_based_fallback(
                "\n".join(segment_texts or []), "es", num_clips
            )
        # Defensive JSON parsing: LLM may return string instead of dict
        if isinstance(virality_data, str):
            try:
                virality_data = json.loads(virality_data)
            except (json.JSONDecodeError, ValueError):
                virality_data = {}
        # Ensure virality_data is a dict
        if not isinstance(virality_data, dict):
            virality_data = {}
        # VIRAL_SCORER_SYSTEM_PROMPT returns {"segments": [...]} with fields:
        #   viral_score (0-10), hook_strength (0-10), emotional_peak (0-10),
        #   shareability (0-10), retention (0-10), reason, start, end
        # Legacy code used "analysis" with "segment_index" — both are now handled.
        analysis = virality_data.get("segments", virality_data.get("analysis", []))
        if not isinstance(analysis, list):
            analysis = []
        # Map by position: input segment i → LLM output segment i
        # Translate field names and scale (0-10 → 0-100) to match pipeline internals.
        virality_map = {}
        for _llm_idx, _item in enumerate(analysis):
            if not isinstance(_item, dict):
                continue
            _raw_v = float(_item.get("viral_score", _item.get("virality_score", 0)) or 0)
            # viral_score is avg of 4 sub-scores each 0-10 → multiply by 10 for 0-100 scale
            _v100 = min(100, round(_raw_v * 10))
            virality_map[_llm_idx] = {
                "virality_score": _v100,
                "hook_score": min(100, round(float(_item.get("hook_strength", _item.get("hook_score", 0)) or 0) * 10)),
                "engagement_score": min(100, round(float(_item.get("emotional_peak", _item.get("engagement_score", 0)) or 0) * 10)),
                "value_score": min(100, round(float(_item.get("retention", _item.get("value_score", 0)) or 0) * 10)),
                "shareability_score": min(100, round(float(_item.get("shareability", _item.get("shareability_score", 0)) or 0) * 10)),
                "reasoning": _item.get("reason", _item.get("reasoning", "")),
                "hook_type": _item.get("hook_type"),
                "suggested_title": _item.get("suggested_title", ""),
                "suggested_hashtags": _item.get("suggested_hashtags", []),
                "hook_strength": _item.get("hook_strength_label", _item.get("hook_strength_text", "Medium")),
            }
        
        # Log scoring method used
        if virality_map:
            first_reasoning = list(virality_map.values())[0].get("reasoning", "")
            if "heuristic" in first_reasoning.lower() or "fallback" in first_reasoning.lower():
                logger.info("📊 Using heuristic virality scoring (Groq/Ollama unavailable)")
            else:
                logger.info("✨ Using AI virality scoring (Groq active)")
                
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
        from ...config import get_config as _get_cfg_b4
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

        def _enforce_min_duration_dict(seg: Dict[str, Any], min_secs: float = 30.0) -> Dict[str, Any]:
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

        # Step 5: RENDER CLIPS TO DISK
        # NOTE: Rendering is intentionally skipped here. The _processor_mixin.py
        # render loop handles all clip rendering with the correct task parameters
        # (auto_center_face, jump_cut, GPU settings, etc.). Running it here too
        # would cause every clip to be rendered TWICE, wasting ~50% of processing
        # time and producing clips with wrong parameters that get silently discarded.
        clips_info = []
        if should_cancel and await should_cancel():
            raise Exception("Task cancelled")
        if progress_callback:
            await progress_callback(80, "Preparing clip render...", "processing")

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
