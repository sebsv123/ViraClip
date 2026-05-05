"""Suggestion applicator — re-render a clip applying only approved suggestions.

This module provides the core re-rendering logic for the Suggestion Studio:
- Reads the persisted ``render_context`` JSON
- Queries ``clip_suggestions`` for approved rows
- Maps suggestion kinds to ``skip_stages`` for ``creative_pipeline.enhance()``
- Produces a low-res preview (480p) or final quality render (1080p)
- Never mutates the original clip until ``finalize`` is explicitly called

Architecture:
- ``apply_suggestions()`` is the public entry point (called by worker or endpoint)
- Stage mapping is explicit and versioned so the UI/UX can evolve independently
- All I/O is async; CPU-heavy FFmpeg work runs in thread pool via ``run_in_thread``
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories.clip_repository import ClipRepository
from ...repositories.clip_suggestion_repository import ClipSuggestionRepository
from ...utils.async_helpers import run_in_thread

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Stage mapping: which creative_pipeline stages to skip when a suggestion
# is NOT approved (or is rejected). The default is to run all stages.
# --------------------------------------------------------------------------
_STAGE_BY_KIND: Dict[str, str] = {
    # timing
    "hook_reorder": "hook_reorder",
    # media
    "broll_overlays": "broll",
    "contextual_overlay": "contextual_overlay",
    "music_track": "audio_master",  # music is part of audio master
    "sfx_cues": "audio_master",  # sfx is part of audio master
    # polish
    "zoom_punch": "vfx",
    "color_grade": "vfx",
    "speed_control": "speed_control",
    "loudnorm": "audio_master",
    "audio_ducking": "audio_master",
    "denoise": "audio_master",
    "background_composite": "broll",  # composite is an alternative to broll
}

_PREVIEW_SCALE = "480:-2"  # 480p width, keep aspect
_FINAL_SCALE = "1080:-2"  # 1080p width, keep aspect


class ApplicatorError(Exception):
    pass


class RenderContextMissing(ApplicatorError):
    pass


class SourceVideoMissing(ApplicatorError):
    pass


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
async def apply_suggestions(
    db: AsyncSession,
    *,
    clip_id: str,
    preview: bool = False,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Re-render ``clip_id`` honoring approved suggestions only.

    Args:
        db: Database session (async)
        clip_id: UUID of the clip to re-render
        preview: If True, render 480p low-res fast; if False, render 1080p final
        output_dir: Where to write the new clip; defaults to same dir as original

    Returns:
        Dict with keys:
        - ``success``: bool
        - ``new_path``: Path | None
        - ``skipped_stages``: list[str] (which stages were disabled)
        - ``error``: str | None
    """
    # 1. Load render context
    ctx = await ClipRepository.get_render_context(db, clip_id)
    if not ctx:
        raise RenderContextMissing(f"Clip {clip_id} has no render_context")

    source_video = Path(ctx.get("source_video_path", ""))
    if not source_video.exists():
        raise SourceVideoMissing(f"Source video missing: {source_video}")

    segment = ctx.get("segment") or {}
    clip_info = ctx.get("clip_info") or {}
    task_config = ctx.get("task_config") or {}

    # 2. Load approved suggestions
    approved = await ClipSuggestionRepository.list_approved(db, clip_id)

    # 3. Determine skip set based on missing approved suggestions
    # Logic: if user rejected a suggestion, we skip that stage.
    # If a suggestion kind is not present at all in approved, we also skip it
    # (user didn't want it in the first place).
    skip_stages: Set[str] = set()

    # Start with all stages that CAN be skipped
    all_stages = set(_STAGE_BY_KIND.values())

    # Approved kinds
    approved_kinds = {s["kind"] for s in approved}

    # For each stage, if NO suggestion of that kind is approved, skip it
    for kind, stage in _STAGE_BY_KIND.items():
        if kind not in approved_kinds:
            skip_stages.add(stage)

    # 3b. SUGGESTION STUDIO: Extract editable items from approved suggestions
    # Build enriched task_config with user-edited items for granular control
    broll_suggestion = next((s for s in approved if s["kind"] == "broll_overlays"), None)
    if broll_suggestion and broll_suggestion.get("payload", {}).get("items"):
        items = broll_suggestion["payload"]["items"]
        if items and isinstance(items, list) and len(items) > 0:
            # Ensure items have full paths (resolve relative URLs)
            enriched_items = []
            for item in items:
                enriched = dict(item)
                # Resolve video_url if relative
                url = item.get("video_url") or item.get("path")
                if url and not url.startswith(("http", "/")):
                    # Assume it's a relative path, construct full path
                    enriched["video_url"] = str(Path(clip_info.get("path", "")).parent / url)
                enriched_items.append(enriched)
            task_config["broll_items"] = enriched_items
            logger.info("[suggestion_applicator] Passing %d editable B-roll items to pipeline", len(enriched_items))

    overlay_suggestion = next((s for s in approved if s["kind"] == "contextual_overlay"), None)
    if overlay_suggestion and overlay_suggestion.get("payload", {}).get("items"):
        task_config["overlay_items"] = overlay_suggestion["payload"]["items"]
        logger.info("[suggestion_applicator] Passing %d editable overlay items to pipeline", len(task_config["overlay_items"]))

    sfx_suggestion = next((s for s in approved if s["kind"] == "sfx_cues"), None)
    if sfx_suggestion and sfx_suggestion.get("payload", {}).get("items"):
        task_config["sfx_items"] = sfx_suggestion["payload"]["items"]
        logger.info("[suggestion_applicator] Passing %d editable SFX items to pipeline", len(task_config["sfx_items"]))

    # Special case: if user approved "trim_offsets", we need to handle it
    # (trim is applied BEFORE the creative pipeline, in the base render)
    trim_offsets = next(
        (s for s in approved if s["kind"] == "trim_offsets"), None
    )

    # 4. Prepare output path
    original_path = Path(clip_info.get("path", ""))
    if output_dir is None:
        output_dir = original_path.parent if original_path.exists() else Path("/tmp")

    suffix = "_preview" if preview else "_final"
    new_filename = f"{original_path.stem}{suffix}{original_path.suffix}"
    new_path = output_dir / new_filename

    # 5. Re-render
    try:
        result = await _do_render(
            source_video=source_video,
            segment=segment,
            clip_info=clip_info,
            task_config=task_config,
            skip_stages=skip_stages,
            trim_offsets=trim_offsets["payload"] if trim_offsets else None,
            preview=preview,
            output_path=new_path,
        )
        return {
            "success": True,
            "new_path": str(result),
            "skipped_stages": sorted(skip_stages),
            "error": None,
        }
    except Exception as exc:
        logger.exception("[suggestion_applicator] render failed for %s", clip_id)
        return {
            "success": False,
            "new_path": None,
            "skipped_stages": sorted(skip_stages),
            "error": str(exc),
        }


# --------------------------------------------------------------------------
# Internal render logic
# --------------------------------------------------------------------------
async def _do_render(
    *,
    source_video: Path,
    segment: Dict[str, Any],
    clip_info: Dict[str, Any],
    task_config: Dict[str, Any],
    skip_stages: Set[str],
    trim_offsets: Optional[Dict[str, Any]],
    preview: bool,
    output_path: Path,
) -> Path:
    """Execute the actual re-render.

    Steps:
    1. Extract base segment from source (respecting trim_offsets if any)
    2. Run creative_pipeline.enhance() with skip_stages
    3. Return new clip path
    """
    # Import here to avoid circular imports at module load time
    from ...domains.video.clip_creation import ClipCreationService
    from .creative_pipeline import CreativePipeline

    # 1. Determine actual start/end with trim offsets
    start_sec = _to_seconds(segment.get("start_time", 0))
    end_sec = _to_seconds(segment.get("end_time", start_sec + 60))

    if trim_offsets:
        start_sec += float(trim_offsets.get("start_offset", 0))
        end_sec -= float(trim_offsets.get("end_offset", 0))
        # Sanity bounds
        if end_sec <= start_sec:
            end_sec = start_sec + 1.0

    # 2. Extract base clip (low-res for preview)
    scale = _PREVIEW_SCALE if preview else _FINAL_SCALE

    # Use ClipCreationService to extract the segment
    service = ClipCreationService()

    # Build a temp path for base extraction
    base_temp = output_path.with_name(f"_base_{output_path.name}")

    # Extract segment using FFmpeg (fast, no analysis)
    await _extract_segment(
        source=source_video,
        start=start_sec,
        end=end_sec,
        output=base_temp,
        scale=scale,
    )

    # 3. Run creative pipeline with skip_stages
    pipeline = CreativePipeline()

    # Get transcript words for the segment (needed by pipeline)
    words = segment.get("words", [])
    audio_features = {}  # We could re-analyze but skip for speed

    meta = await pipeline.enhance(
        clip_path=base_temp,
        source_video=source_video,
        segment=segment,
        words=words,
        audio_features=audio_features,
        task_id=task_config.get("task_id", "unknown"),
        clip_index=clip_info.get("clip_order", 0),
        platform=task_config.get("target_platform", "tiktok"),
        skip_stages=skip_stages,
    )

    logger.info(
        "[suggestion_applicator] enhance complete; stages skipped: %s",
        skip_stages,
    )

    # The pipeline modifies base_temp in place; rename to final output
    if base_temp.exists():
        shutil.move(str(base_temp), str(output_path))

    return output_path


async def _extract_segment(
    *,
    source: Path,
    start: float,
    end: float,
    output: Path,
    scale: str,
) -> None:
    """Fast FFmpeg extract + scale (no re-encode if possible)."""
    import subprocess

    duration = end - start

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(source),
        "-t", str(duration),
        "-vf", f"scale={scale}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23" if "1080" in scale else "28",  # higher CRF for preview
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output),
    ]

    def _run():
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg extract failed: {result.stderr}")
        return output

    await run_in_thread(_run)


def _to_seconds(val: Any) -> float:
    """Convert timestamp string or float to seconds."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        # Handle "HH:MM:SS" or "MM:SS"
        parts = str(val).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return 0.0
