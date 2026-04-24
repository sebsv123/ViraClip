"""Inter-clip transitions — cross-fades, wipes, glitches, etc."""

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
from ._helpers import get_ffmpeg_exe, get_service_config
from .vfx_service import VFXService

logger = logging.getLogger(__name__)

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
            from ...video_processing.optical_flow_transitions import (
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

