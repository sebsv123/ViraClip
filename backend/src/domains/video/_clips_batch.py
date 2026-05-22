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

from ...core.job_context import JobContext
from . import _helpers, _subtitles, _transcript
from ._clip_renderer import create_single_clip
from ._helpers import get_ffmpeg_exe, get_service_config
from .vfx_service import VFXService


logger = logging.getLogger(__name__)


# ── Post-render validation ────────────────────────────────────────────────────

async def validate_clip_output(
    clip_path: Path,
    clip_index: int,
    intended_duration: float,
) -> Dict[str, Any]:
    """
    Run 4 post-render validation checks on a clip.

    1. DURATION: within 2s of intended duration (warning only).
    2. AUDIO: at least one audio stream present (error → skip).
    3. VIDEO DIMENSIONS: must be 1080x1920 (error → skip).
    4. FILE SIZE: must be >= 500KB (error → skip).

    Returns a dict with check results and a "pass" boolean.
    """
    result: Dict[str, Any] = {
        "clip_index": clip_index,
        "path": str(clip_path),
        "duration_check": {"pass": True, "actual": 0.0, "intended": intended_duration},
        "audio_check": {"pass": True},
        "dimensions_check": {"pass": True, "actual": ""},
        "file_size_check": {"pass": True, "size_kb": 0},
        "pass": True,
    }

    if not clip_path.exists():
        result["pass"] = False
        result["file_size_check"]["pass"] = False
        result["file_size_check"]["error"] = "File does not exist"
        logger.error("[Validate] Clip %d: file not found — %s", clip_index, clip_path)
        return result

    # 1. DURATION check
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(clip_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        actual_dur = float(stdout.decode().strip())
        result["duration_check"]["actual"] = actual_dur
        diff = abs(actual_dur - intended_duration)
        if diff > 2.0:
            result["duration_check"]["pass"] = False
            logger.warning(
                "[Validate] Clip %d duration mismatch: intended=%.1fs, actual=%.1fs (diff=%.1fs)",
                clip_index, intended_duration, actual_dur, diff,
            )
    except Exception as e:
        result["duration_check"]["pass"] = False
        result["duration_check"]["error"] = str(e)
        logger.warning("[Validate] Clip %d duration probe failed: %s", clip_index, e)

    # 2. AUDIO check
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type", str(clip_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        audio_streams = stdout.decode().strip()
        if "codec_type" not in audio_streams:
            result["audio_check"]["pass"] = False
            result["pass"] = False
            logger.error("[Validate] Clip %d has no audio stream", clip_index)
    except Exception as e:
        result["audio_check"]["pass"] = False
        result["audio_check"]["error"] = str(e)
        logger.warning("[Validate] Clip %d audio probe failed: %s", clip_index, e)

    # 3. VIDEO DIMENSIONS check
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", str(clip_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        dims = stdout.decode().strip()
        result["dimensions_check"]["actual"] = dims
        if dims != "1080,1920":
            result["dimensions_check"]["pass"] = False
            result["pass"] = False
            logger.error(
                "[Validate] Clip %d wrong dimensions: expected 1080x1920, got %s",
                clip_index, dims,
            )
    except Exception as e:
        result["dimensions_check"]["pass"] = False
        result["dimensions_check"]["error"] = str(e)
        logger.warning("[Validate] Clip %d dimensions probe failed: %s", clip_index, e)

    # 4. FILE SIZE check
    try:
        size_kb = clip_path.stat().st_size / 1024
        result["file_size_check"]["size_kb"] = round(size_kb, 1)
        if size_kb < 500:
            result["file_size_check"]["pass"] = False
            result["pass"] = False
            logger.error(
                "[Validate] Clip %d too small: %.1f KB < 500 KB — corrupt render",
                clip_index, size_kb,
            )
    except Exception as e:
        result["file_size_check"]["pass"] = False
        result["file_size_check"]["error"] = str(e)
        logger.warning("[Validate] Clip %d file size check failed: %s", clip_index, e)

    return result


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

    # Instantiate one JobContext for the entire job so services can coordinate
    # asset selection, LUT rotation, etc. across all clips.
    job_ctx = JobContext(job_id=task_id)

    # Use Concurrency Optimizer for parallel clip creation
    processor = ParallelBatchProcessor(max_concurrent=max_concurrent)
    
    # Per-job validation summary
    validation_summary: Dict[str, Any] = {
        "total_clips": len(segments),
        "passed": 0,
        "skipped": 0,
        "warnings": [],
        "results": [],
    }

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
                job_ctx=job_ctx,
            )
            if clip_info is None:
                return None

            # Post-render validation
            clip_path = Path(clip_info["path"])
            intended_dur = clip_info.get("duration", 0.0)
            val_result = await validate_clip_output(clip_path, idx, intended_dur)

            # Collect validation result
            validation_summary["results"].append(val_result)

            if not val_result["pass"]:
                validation_summary["skipped"] += 1
                logger.error(
                    "[Validate] Clip %d failed validation — skipping export",
                    idx,
                )
                return None

            validation_summary["passed"] += 1
            if not val_result["duration_check"]["pass"]:
                validation_summary["warnings"].append(
                    f"Clip {idx}: duration mismatch "
                    f"(intended={val_result['duration_check']['intended']:.1f}s, "
                    f"actual={val_result['duration_check']['actual']:.1f}s)"
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
    
    # Attach validation summary to each clip info
    for clip_info in clips_info:
        clip_info["validation_summary"] = validation_summary

    logger.info(
        "[Validate] %d/%d clips passed, %d skipped, %d warnings",
        validation_summary["passed"],
        validation_summary["total_clips"],
        validation_summary["skipped"],
        len(validation_summary["warnings"]),
    )

    # ── Write per-job debug log ───────────────────────────────────────────────
    try:
        _logs_dir = Path(__file__).resolve().parent.parent.parent / "logs" / "jobs"
        _logs_dir.mkdir(parents=True, exist_ok=True)
        _job_log: Dict[str, Any] = {
            "job_id": task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "clips_attempted": len(segments),
            "clips_exported": len(clips_info),
            "clips_skipped": [],
            "per_clip": [],
        }
        # Collect skipped clip info from validation results
        for _vr in validation_summary.get("results", []):
            if not _vr.get("pass"):
                _reason_parts = []
                if not _vr.get("audio_check", {}).get("pass"):
                    _reason_parts.append("no audio stream")
                if not _vr.get("dimensions_check", {}).get("pass"):
                    _reason_parts.append(f"wrong dimensions: {_vr.get('dimensions_check', {}).get('actual', '?')}")
                if not _vr.get("file_size_check", {}).get("pass"):
                    _reason_parts.append(f"file too small: {_vr.get('file_size_check', {}).get('size_kb', 0)}KB")
                _job_log["clips_skipped"].append({
                    "clip_index": _vr.get("clip_index"),
                    "reason": "; ".join(_reason_parts) if _reason_parts else "validation failed",
                })
        # Collect per-clip info from clip_info dicts
        for _ci in clips_info:
            _seg = _ci.get("segment", {})
            _job_log["per_clip"].append({
                "clip_index": _ci.get("clip_id", 0) - 1,
                "segment": {
                    "start": _seg.get("start_time", "?"),
                    "end": _seg.get("end_time", "?"),
                },
                "lut_applied": _ci.get("lut_preset", ""),
                "broll_count": _ci.get("broll_overlays", 0),
                "broll_assets": _ci.get("broll_asset_ids", []),
                "hook_style": _ci.get("hook_style", ""),
                "music_track": _ci.get("bgm_used", ""),
                "services_failed": _ci.get("services_failed", []),
                "output_duration": _ci.get("duration", 0),
                "output_filesize_kb": _ci.get("output_filesize_kb", 0),
                "validation_passed": _ci.get("validation_passed", True),
            })
        _log_path = _logs_dir / f"{task_id}.json"
        _log_path.write_text(json.dumps(_job_log, indent=2, default=str))
        logger.info("[JobLog] Written to %s", _log_path)
    except Exception as _jl_e:
        logger.debug("[JobLog] Failed to write job log: %s", _jl_e)

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



