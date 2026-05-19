"""Batch clip rendering — orchestrates many `create_single_clip` calls.

`create_video_clips_parallel` is the modern entry point used by the pipeline;
`create_video_clips` is the legacy sequential fallback.
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
from ...domains.ai.phi3_virality_service import Phi3ViralityService, get_phi3_service
from ...domains.audio.sound_design_service import SoundDesignService, add_viral_sound_effects
from ...domains.broll.broll_service import BrollService
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

from . import _helpers, _subtitles, _transcript
from ._clip_renderer import create_single_clip
from ._helpers import get_ffmpeg_exe, get_service_config
from .vfx_service import VFXService

logger = logging.getLogger(__name__)

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
            # Inject total clip count so create_single_clip can rotate LUTs etc.
            segment = {**segment, "_total_clips": len(segments)}
            clip_info = await create_single_clip(
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



