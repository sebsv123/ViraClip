"""
Task service - orchestrates task creation and processing workflow.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional, Callable, List, Tuple
import logging
import asyncio
import os
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
import inspect
from time import perf_counter
import re
import unicodedata

import redis.asyncio as redis

from ..repositories.task_repository import TaskRepository
from ..repositories.source_repository import SourceRepository
from ..repositories.clip_repository import ClipRepository
from ..repositories.cache_repository import CacheRepository
from .video_service import (
    VideoService,
    ClipEditorialRejection,
    _normalize_ass_words as _output_basic_normalize_ass_words,
    _burn_ass_subtitles_file as _output_basic_burn_ass_subtitles_file,
    _resolve_caption_artifacts_dir as _output_basic_resolve_caption_artifacts_dir,
)
from .vpi_editorial_scorer import _text_overlap_metrics as _h1413_text_overlap_metrics
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
from .comfyui_integration import comfyui_integration
from .vpi_publishable_gate import (
    UploadRecommendation,
    evaluate_clip_publishability,
    rank_clips,
)
from .vpi_fast_fail_rescue import (
    _apply_fast_fail_rescue_to_render_input,
)
from .vpi_metadata_normalization import _normalize_sfx_meta
from .vpi_editorial_contract import (
    build_vpi_local_review_bundle as _build_vpi_local_review_bundle,
    build_vpi_output_manifest as _build_vpi_output_manifest,
)
from .vpi_task_source_contract import resolve_task_source_contract
from .vpi_retention_editing_service import build_delivery_contract

logger = logging.getLogger(__name__)


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                loaded = json.loads(text)
                return loaded if isinstance(loaded, dict) else {}
            except Exception:
                return {}
    return {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _merge_truth_value(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        if isinstance(value, (list, tuple, set, dict)):
            if value:
                return value
            continue
        return value
    return None


def _hash_file_sha256(path: Path, *, chunk_size: int = 1_048_576) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return ""


def _normalize_output_path_truth(path_value: Any) -> Dict[str, Any]:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return {
            "container_path": "",
            "host_or_relative_path": "",
            "relative_path": "",
            "resolved_path": "",
            "exists": False,
            "size_bytes": 0,
            "mtime": 0.0,
        }
    candidate = Path(raw_path)
    resolved = candidate
    if raw_path.startswith("/app/"):
        relative = raw_path.removeprefix("/app/").lstrip("/")
        workspace_candidate = Path.cwd() / relative
        resolved = workspace_candidate
    elif not candidate.is_absolute():
        workspace_candidate = Path.cwd() / raw_path
        resolved = workspace_candidate if workspace_candidate.exists() else candidate
    exists = bool(resolved.exists() or candidate.exists())
    stat_path = resolved if resolved.exists() else candidate if candidate.exists() else resolved
    try:
        stat = stat_path.stat() if stat_path.exists() else None
    except Exception:
        stat = None
    if resolved.exists():
        host_or_relative_path = str(resolved)
    elif raw_path.startswith("/app/"):
        host_or_relative_path = str(Path.cwd() / raw_path.removeprefix("/app/").lstrip("/"))
    else:
        host_or_relative_path = str(candidate)
    if candidate.is_absolute() and candidate.exists():
        try:
            relative_path = str(candidate.relative_to(Path.cwd()))
        except Exception:
            relative_path = str(candidate)
    elif raw_path.startswith("/app/"):
        relative_path = raw_path.removeprefix("/app/").lstrip("/")
    else:
        relative_path = raw_path
    return {
        "container_path": raw_path,
        "host_or_relative_path": host_or_relative_path,
        "relative_path": relative_path,
        "resolved_path": str(stat_path if stat_path else resolved),
        "exists": exists,
        "size_bytes": int(stat.st_size or 0) if stat else 0,
        "mtime": float(stat.st_mtime or 0.0) if stat else 0.0,
    }


def _build_final_output_truth(
    *,
    task_id: str,
    task_scoped_output_path: Any,
    durable_output_path: Any,
    final_mp4_contract: Optional[Dict[str, Any]] = None,
    selected_final_output_path: Any = None,
) -> Dict[str, Any]:
    task_scoped_truth = _normalize_output_path_truth(task_scoped_output_path)
    durable_truth = _normalize_output_path_truth(durable_output_path)
    selected_truth = _normalize_output_path_truth(selected_final_output_path or task_scoped_output_path or durable_output_path)
    final_contract = _as_dict(final_mp4_contract)
    final_path_obj = Path(str(selected_truth.get("resolved_path") or selected_truth.get("container_path") or ""))
    task_scoped_path_obj = Path(str(task_scoped_truth.get("resolved_path") or task_scoped_truth.get("container_path") or ""))
    durable_path_obj = Path(str(durable_truth.get("resolved_path") or durable_truth.get("container_path") or ""))
    entity_relation = "unknown"
    try:
        if task_scoped_path_obj.exists() and durable_path_obj.exists():
            task_sha = _hash_file_sha256(task_scoped_path_obj)
            durable_sha = _hash_file_sha256(durable_path_obj)
            entity_relation = "byte_identical" if task_sha and task_sha == durable_sha else "distinct_valid_artifacts"
        elif task_scoped_path_obj.exists() or durable_path_obj.exists():
            entity_relation = "single_valid_artifact"
    except Exception:
        entity_relation = "unknown"
    final_output_verified = bool(
        _merge_truth_value(
            final_contract.get("final_output_verified"),
            final_contract.get("final_output_verified") is True,
        )
    )
    final_probe_ok = bool(_merge_truth_value(final_contract.get("final_probe_ok"), final_contract.get("probe_ok")))
    final_video_stream_ok = bool(_merge_truth_value(final_contract.get("final_video_stream_ok"), final_contract.get("video_stream_ok")))
    final_audio_stream_ok = bool(_merge_truth_value(final_contract.get("final_audio_stream_ok"), final_contract.get("audio_stream_ok")))
    final_duration = _merge_truth_value(final_contract.get("final_duration"), final_contract.get("duration"))
    final_file_size = _merge_truth_value(final_contract.get("final_file_size"), final_contract.get("file_size"))
    return {
        "task_id": str(task_id or ""),
        "final_output_path": str(final_path_obj if final_path_obj else selected_final_output_path or task_scoped_output_path or durable_output_path or ""),
        "final_output_path_container": str(task_scoped_truth.get("container_path") or durable_truth.get("container_path") or selected_truth.get("container_path") or ""),
        "final_output_path_host_or_relative": str(selected_truth.get("host_or_relative_path") or ""),
        "final_output_path_relative": str(selected_truth.get("relative_path") or ""),
        "final_output_path_task_scoped": str(task_scoped_truth.get("container_path") or ""),
        "final_output_path_durable": str(durable_truth.get("container_path") or ""),
        "final_output_exists": bool(selected_truth.get("exists")),
        "final_file_size": int(selected_truth.get("size_bytes") or 0),
        "final_mtime": float(selected_truth.get("mtime") or 0.0),
        "final_duration": float(final_duration or 0.0),
        "final_probe_ok": bool(final_probe_ok),
        "final_video_stream_ok": bool(final_video_stream_ok),
        "final_audio_stream_ok": bool(final_audio_stream_ok),
        "final_output_verified": bool(final_output_verified),
        "final_output_entity_relation": entity_relation,
        "final_mp4_contract": dict(final_contract),
    }


def _lightweight_final_contract_ref(contract: Any) -> Dict[str, Any]:
    """H12.9: bounded scalar-only projection of a final_mp4_contract.

    Used to cut the final_mp4_contract <-> final_output_truth telescoping
    chain (diagnosed in H12.8 as the cause of the manifest/summary
    RecursionError) at its embedding source: instead of re-wrapping the
    entire prior contract/truth structure on every render->finalize->rebuild
    pass, we substitute a flat reference carrying only the fields downstream
    consumers (manifest, QC, publishable gate) actually read.
    """
    c = contract if isinstance(contract, dict) else {}
    return {
        "final_output_path": str(c.get("final_output_path") or ""),
        "final_output_exists": bool(c.get("final_output_exists", False)),
        "final_output_verified": bool(c.get("final_output_verified", False)),
        "final_probe_ok": bool(c.get("final_probe_ok", False)),
        "final_video_stream_ok": bool(c.get("final_video_stream_ok", False)),
        "final_audio_stream_ok": bool(c.get("final_audio_stream_ok", False)),
        "final_publishable": bool(c.get("final_publishable", False)),
        "final_needs_review": bool(c.get("final_needs_review", False)),
        "final_duration": float(c.get("final_duration") or 0.0),
        "final_file_size": int(c.get("final_file_size") or 0),
        "boundary_confidence": float(c.get("boundary_confidence") or 0.0),
        "final_truth_source": str(c.get("final_truth_source") or ""),
        "final_blocking_reasons": list(c.get("final_blocking_reasons") or []) if isinstance(c.get("final_blocking_reasons"), list) else [],
        "final_warning_reasons": list(c.get("final_warning_reasons") or []) if isinstance(c.get("final_warning_reasons"), list) else [],
        "_lightweight_ref": True,
    }


def _rehydrate_clip_brief_from_final_contract(
    clip_brief: Any,
    clip_info: Any,
    final_contract: Any,
) -> Dict[str, Any]:
    merged = dict(_as_dict(clip_brief))
    clip = _as_dict(clip_info)
    contract = _as_dict(final_contract)
    fields = (
        "final_output_path",
        "final_output_path_container",
        "final_output_path_host_or_relative",
        "final_output_path_relative",
        "final_output_exists",
        "final_file_size",
        "final_duration",
        "final_probe_ok",
        "final_video_stream_ok",
        "final_audio_stream_ok",
        "final_output_verified",
        "boundary_confidence",
        "complete_idea_score",
        "incomplete_viral_window_detected",
        "setup_context_shift_seconds",
        "trailing_low_value_seconds",
        "forced_shift_back_applied",
        "selected_alternative_for_complete_idea",
        "incomplete_window_uncorrectable",
        "viral_window_shifted_back",
        "viral_window_shift_reason",
        "selected_window_before",
        "selected_window_after",
        "bts_tail_detected",
        "bts_tail_trimmed_seconds",
        "ass_event_count_final",
        "temporal_overlap_count",
        "text_overlap_prevented",
        "captions_overlap_removed",
        "final_mp4_contract",
    )
    for field in fields:
        preferred = _merge_truth_value(contract.get(field), clip.get(field), merged.get(field))
        if preferred is not None:
            merged[field] = preferred
    return merged


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                loaded = json.loads(text)
                if isinstance(loaded, list):
                    return loaded
                if isinstance(loaded, dict):
                    return list(loaded.values())
            except Exception:
                return []
    return []


def _collect_h4_empirical_metadata(*sources: Any) -> Dict[str, Any]:
    h4_keys = (
        "text_overlap_prevented",
        "suppressed_text_layers",
        "text_layer_count_final",
        "caption_priority_enforced",
        "pip_overlay_disabled",
        "thumbnail_overlay_disabled",
        "debug_preview_overlay_disabled",
        "debug_face_box_rendered",
        "debug_overlays_disabled",
        "caption_timebase_corrected",
        "caption_timebase_source",
        "caption_sync_warning",
        "broll_relevance_gate_passed",
        "broll_relevance_score",
        "broll_skipped_unrelated",
        "bgm_volume_empirical_boost_applied",
        "bgm_target_volume_final",
        "bts_tail_detected",
        "bts_tail_trimmed_seconds",
        "viral_window_shifted_back",
        "viral_window_shift_reason",
        "daily_mode_external_route_active",
        "daily_mode_external_route_names",
        "daily_mode_external_source_allowed",
        "non_production_safe_route_used",
        "stage_recorder",
        "hook_lower_third_rendered",
        "ass_hook_overlay_injected",
        "non_text_visual_hook_rendered",
        "ass_event_count_before",
        "ass_event_count_final",
        "ass_event_hard_cap",
        "ass_events_merged_for_daily",
        "ass_karaoke_enabled",
        "ass_approx_simple_mode",
        "ass_hook_overlay_removed",
        "captions_overlap_removed",
        "selected_window_before",
        "selected_window_after",
        "complete_idea_score",
        "incomplete_viral_window_detected",
        "setup_context_shift_seconds",
        "trailing_low_value_seconds",
        "viral_window_shifted_back",
        "viral_window_shift_reason",
        "forced_shift_back_applied",
        "selected_alternative_for_complete_idea",
        "incomplete_window_uncorrectable",
    )
    collected: Dict[str, Any] = {}
    _coerced_non_dict_count = 0
    normalized_sources: List[Dict[str, Any]] = []
    for source in sources:
        if isinstance(source, dict):
            normalized_sources.append(source)
            continue
        if isinstance(source, str):
            normalized_sources.append(_as_dict(source))
            continue
        # Defensive: None or any unexpected type must never raise here —
        # absence of metadata is a warning-level condition, never fatal.
        _coerced_non_dict_count += 1
        normalized_sources.append({})
    if _coerced_non_dict_count:
        logger.info(
            "VPI_H4_EMPIRICAL_METADATA_SAFE_INPUTS sources_total=%d coerced_to_empty=%d",
            len(sources),
            _coerced_non_dict_count,
        )
    for key in h4_keys:
        for source in normalized_sources:
            if key in source and source[key] is not None:
                collected[key] = source[key]
                break
    return collected


def _resolve_publishable_context(source: Any) -> Dict[str, Any]:
    source_dict = _as_dict(source)
    publishable_gate = _as_dict(source_dict.get("publishable_gate"))
    publishable_metadata = _as_dict(source_dict.get("publishable_metadata"))
    raw_status = source_dict.get("publishable_status")
    publishable_status_dict = _as_dict(raw_status)

    if not publishable_metadata:
        publishable_metadata = _as_dict(publishable_gate.get("metadata"))
    if not publishable_metadata:
        publishable_metadata = publishable_status_dict
    if not publishable_metadata:
        publishable_metadata = publishable_gate

    if publishable_status_dict:
        publishable_status = str(
            publishable_status_dict.get("publishable_status")
            or publishable_status_dict.get("status")
            or ""
        )
    else:
        publishable_status = str(raw_status or "")

    publishable_warnings = (
        _as_list(source_dict.get("publishable_warnings"))
        or _as_list(publishable_gate.get("publishable_warnings"))
        or _as_list(publishable_gate.get("final_warning_reasons"))
        or _as_list(publishable_metadata.get("publishable_warnings"))
        or _as_list(publishable_metadata.get("final_warning_reasons"))
    )
    publishable_blocking = (
        _as_list(source_dict.get("publishable_blocking"))
        or _as_list(source_dict.get("final_blocking_reasons"))
        or _as_list(publishable_gate.get("publishable_blocking"))
        or _as_list(publishable_gate.get("final_blocking_reasons"))
        or _as_list(publishable_metadata.get("publishable_blocking"))
        or _as_list(publishable_metadata.get("final_blocking_reasons"))
    )

    return {
        "status": publishable_status,
        "metadata": publishable_metadata,
        "warnings": publishable_warnings,
        "blocking": publishable_blocking,
    }


def _is_truthy_env(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _render_vpi_output_summary_markdown(manifest: Dict[str, Any]) -> str:
    clips = manifest.get("clips") if isinstance(manifest, dict) else []
    clips = clips if isinstance(clips, list) else []
    package_summary = manifest.get("package_summary") if isinstance(manifest, dict) else {}
    package_summary = package_summary if isinstance(package_summary, dict) else {}
    publishable_summary = manifest.get("publishable_summary") if isinstance(manifest, dict) else {}
    publishable_summary = publishable_summary if isinstance(publishable_summary, dict) else {}
    warnings_summary = manifest.get("warnings_summary") if isinstance(manifest, dict) else {}
    warnings_summary = warnings_summary if isinstance(warnings_summary, dict) else {}
    lines: List[str] = [
        "# VPI Clip Summary",
        "",
        f"**Task:** `{manifest.get('task_id', '')}`",
        f"**Created:** {manifest.get('created_at', '')}",
        f"**Output root:** `{manifest.get('output_root', '')}`",
        f"**Manifest:** `{manifest.get('manifest_output_path', '')}`",
        f"**Summary:** `{manifest.get('summary_output_path', '')}`",
        "",
        "## Package",
        "",
        f"- **Campaign intent:** `{package_summary.get('campaign_intent', '')}`",
        f"- **Package diversity score:** `{package_summary.get('package_diversity_score', 0.0)}`",
        f"- **Publishable clips:** `{publishable_summary.get('publishable_clip_count', 0)}`",
        f"- **Review clips:** `{publishable_summary.get('review_clip_count', 0)}`",
        f"- **Warnings:** `{warnings_summary.get('warning_count', 0)}`",
        "",
        "## Clips",
        "",
        "| Clip | Filename | Campaign | Angle | Confidence | CTA | Review Flags | Final File |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        review_flags = clip.get("clip_review_flags") or clip.get("main_warnings") or []
        if isinstance(review_flags, list):
            review_flags_text = ", ".join(str(flag) for flag in review_flags if str(flag)) or "none"
        else:
            review_flags_text = str(review_flags or "none")
        lines.append(
            "| {clip_id} | `{filename}` | `{campaign}` | `{angle}` | `{confidence}` | `{cta}` | `{flags}` | `{path}` |".format(
                clip_id=clip.get("clip_id") or "",
                filename=clip.get("filename") or "",
                campaign=clip.get("campaign_intent") or "",
                angle=clip.get("clip_angle") or "",
                confidence=clip.get("clip_confidence_label") or "",
                cta=clip.get("clip_recommended_cta") or "",
                flags=review_flags_text,
                path=clip.get("file_path") or "",
            )
        )
    lines.extend([
        "",
        "## Recommendations",
        "",
    ])
    for action in manifest.get("recommended_next_actions") or []:
        lines.append(f"- {action}")
    return "\n".join(lines)


def _probe_media_info(path: Path) -> Dict[str, Any]:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return {}
        return json.loads(result.stdout or "{}")
    except Exception:
        return {}


def _deadline_safe_technical_gate(path: Path) -> Tuple[bool, str, Dict[str, Any]]:
    if not path.exists():
        return False, "file_missing", {}
    file_size = int(path.stat().st_size or 0)
    if file_size <= 500 * 1024:
        return False, "file_too_small", {"file_size": file_size}

    probe = _probe_media_info(path)
    streams = probe.get("streams") if isinstance(probe, dict) else []
    streams = streams if isinstance(streams, list) else []
    video_stream = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"), None)
    if not video_stream:
        return False, "missing_video_stream", {"file_size": file_size}
    if not audio_stream:
        return False, "missing_audio_stream", {"file_size": file_size}

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        return False, "invalid_dimensions", {"width": width, "height": height}
    if height <= width:
        return False, "not_vertical_output", {"width": width, "height": height}

    format_info = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    try:
        duration = float(format_info.get("duration") or video_stream.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    if duration < 8.0:
        return False, "duration_lt_8s", {"duration": duration}

    return True, "ok", {
        "file_size": file_size,
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": str(video_stream.get("codec_name") or ""),
        "audio_codec": str(audio_stream.get("codec_name") or ""),
    }


def _parse_ffmpeg_mean_volume(stderr: str) -> Optional[float]:
    for line in (stderr or "").splitlines():
        if "mean_volume:" not in line:
            continue
        try:
            raw = line.split("mean_volume:", 1)[1].replace("dB", "").strip()
            return float(raw)
        except Exception as exc:
            logger.warning("Failed to parse ffmpeg mean_volume value: %s", exc)
            return None
    return None


def _measure_audio_mean_volume_db(path: Path) -> Optional[float]:
    try:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-v",
            "error",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
        return _parse_ffmpeg_mean_volume((proc.stderr or "") + "\n" + (proc.stdout or ""))
    except Exception as exc:
        logger.warning("Failed to measure audio mean volume for %s: %s", path, exc)
        return None


def _probe_clip_file_metadata(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        payload: Dict[str, Any] = {
            "exists": True,
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries",
                    "stream=pix_fmt,color_range,color_space,color_transfer,color_primaries,width,height,duration",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                streams = data.get("streams") or []
                if streams:
                    payload.update({k: streams[0].get(k) for k in ("pix_fmt", "color_range", "color_space", "color_transfer", "color_primaries", "width", "height", "duration")})
        except Exception as exc:
            payload["probe_error"] = str(exc)
        return payload
    except Exception as exc:
        return {"exists": False, "error": str(exc)}


def _probe_clip_first_frame_red_ratio(path: Path, sample_second: float = 2.0) -> Optional[float]:
    try:
        if not path.exists():
            return None
        probe = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            return None
        meta = json.loads(probe.stdout)
        streams = meta.get("streams") or []
        if not streams:
            return None
        width = int(streams[0].get("width") or 0)
        height = int(streams[0].get("height") or 0)
        if width <= 0 or height <= 0:
            return None
        frame = subprocess.run(
            [
                "ffmpeg",
                "-v", "error",
                "-ss", str(sample_second),
                "-i", str(path),
                "-frames:v", "1",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if frame.returncode != 0 or not frame.stdout:
            frame = subprocess.run(
                [
                    "ffmpeg",
                    "-v", "error",
                    "-i", str(path),
                    "-frames:v", "1",
                    "-f", "rawvideo",
                    "-pix_fmt", "rgb24",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
        if frame.returncode != 0 or not frame.stdout:
            return None
        try:
            import numpy as _np
            arr = _np.frombuffer(frame.stdout, dtype=_np.uint8)
            if arr.size < width * height * 3:
                return None
            arr = arr[: width * height * 3].reshape((-1, 3))
            r = float(arr[:, 0].mean())
            g = float(arr[:, 1].mean())
            if g <= 0:
                return None
            return r / g
        except Exception:
            return None
    except Exception:
        return None


def _copy_to_durable_output(task_id: str, clip_order: int, source_path: Path) -> Path:
    durable_dir = Path("/app/outputs/generated") / task_id
    durable_dir.mkdir(parents=True, exist_ok=True)
    durable_path = durable_dir / f"clip_{clip_order:02d}{source_path.suffix or '.mp4'}"
    caller = inspect.stack()[1].function if len(inspect.stack()) > 1 else "unknown"
    source_meta = _probe_clip_file_metadata(source_path)
    source_red_ratio = _probe_clip_first_frame_red_ratio(source_path)
    dest_meta_before = _probe_clip_file_metadata(durable_path)
    logger.info(
        "VPI_CLIP01_WRITE_TRACE task_id=%s clip_order=%d caller=%s source_path=%s dest_path=%s source_exists=%s source_size=%s source_mtime=%s dest_exists=%s dest_size=%s dest_mtime=%s",
        task_id,
        clip_order,
        caller,
        str(source_path),
        str(durable_path),
        str(bool(source_meta.get("exists"))).lower(),
        source_meta.get("size_bytes"),
        source_meta.get("mtime"),
        str(bool(dest_meta_before.get("exists"))).lower(),
        dest_meta_before.get("size_bytes"),
        dest_meta_before.get("mtime"),
    )
    logger.info(
        "VPI_CLIP01_SOURCE_PROBE task_id=%s clip_order=%d caller=%s path=%s metadata=%s",
        task_id,
        clip_order,
        caller,
        str(source_path),
        source_meta,
    )
    if source_red_ratio is not None:
        logger.info(
            "VPI_CLIP01_SOURCE_RED_RATIO task_id=%s clip_order=%d caller=%s path=%s red_ratio=%.4f",
            task_id,
            clip_order,
            caller,
            str(source_path),
            source_red_ratio,
        )
    if source_path.resolve() != durable_path.resolve():
        if durable_path.exists():
            logger.info(
                "VPI_CLIP01_CACHE_HIT task_id=%s clip_order=%d caller=%s path=%s",
                task_id,
                clip_order,
                caller,
                str(durable_path),
            )
        shutil.copy2(source_path, durable_path)
    dest_meta_after = _probe_clip_file_metadata(durable_path)
    dest_red_ratio = _probe_clip_first_frame_red_ratio(durable_path)
    logger.info(
        "VPI_CLIP01_COPY_SOURCE task_id=%s clip_order=%d caller=%s source_path=%s source_metadata=%s",
        task_id,
        clip_order,
        caller,
        str(source_path),
        source_meta,
    )
    logger.info(
        "VPI_CLIP01_COPY_DEST task_id=%s clip_order=%d caller=%s dest_path=%s dest_metadata=%s",
        task_id,
        clip_order,
        caller,
        str(durable_path),
        dest_meta_after,
    )
    logger.info(
        "VPI_CLIP01_DEST_PROBE task_id=%s clip_order=%d caller=%s path=%s metadata=%s",
        task_id,
        clip_order,
        caller,
        str(durable_path),
        dest_meta_after,
    )
    if dest_red_ratio is not None:
        logger.info(
            "VPI_CLIP01_DEST_RED_RATIO task_id=%s clip_order=%d caller=%s path=%s red_ratio=%.4f",
            task_id,
            clip_order,
            caller,
            str(durable_path),
            dest_red_ratio,
        )
    return durable_path


def _normalize_rendered_clip_result(value: Any) -> Optional[Dict[str, Any]]:
    result: Dict[str, Any] = {}
    if isinstance(value, dict):
        result = dict(value)
    elif isinstance(value, Path):
        result = {"path": str(value)}
    elif isinstance(value, str):
        result = {"path": value}
    elif value is not None:
        for attr in (
            "path",
            "final_path",
            "output_path",
            "video_path",
            "durable_output_path",
            "filename",
            "duration",
        ):
            if hasattr(value, attr):
                result[attr] = getattr(value, attr)
    if not result:
        return None
    normalized_path = (
        str(result.get("path") or "")
        or str(result.get("final_path") or "")
        or str(result.get("output_path") or "")
        or str(result.get("video_path") or "")
        or str(result.get("durable_output_path") or "")
    ).strip()
    if normalized_path:
        result["path"] = normalized_path
        result.setdefault("filename", Path(normalized_path).name)
    return result or None


def _find_valid_temp_finish_mp4(task_id: str, clip_order: int) -> Optional[Path]:
    """Search for a valid temp MP4 in fallback stage order.
    
    Fallback stage order (most preferred first):
      1. finish_*.mp4
      2. mastered_*.mp4
      3. music_*.mp4
      4. trans_*.mp4
      5. vfx_*.mp4
      6. ass_*.mp4
      7. emotional_hook_*.mp4
      8. ep_*.mp4
      9. vpi_*.mp4 (base valid)
    """
    temp_dir = Path("/app/temp/uploads/clips") / str(task_id)
    if not temp_dir.exists():
        return None
    stage_prefixes = [
        "finish_",
        "mastered_",
        "music_",
        "trans_",
        "vfx_",
        "ass_",
        "emotional_hook_",
        "ep_",
        "vpi_",
    ]
    order_token = f"_{clip_order}_"
    for prefix in stage_prefixes:
        candidates = sorted(
            temp_dir.glob(f"{prefix}*.mp4"),
            key=lambda p: (p.stat().st_mtime if p.exists() else 0.0, p.name),
            reverse=True,
        )
        ordered_candidates = [p for p in candidates if order_token in p.name] + [p for p in candidates if order_token not in p.name]
        for candidate in ordered_candidates:
            if not candidate.exists():
                continue
            ok, _, _ = _deadline_safe_technical_gate(candidate)
            if ok:
                return candidate
    return None


def _output_basic_build_fallback_caption_words(
    segment: Dict[str, Any],
    duration: float,
) -> List[Dict[str, Any]]:
    """Build approximate word-timed captions from segment text alone.

    Mirrors the [SUBTITLE-FALLBACK] text-split approximation used during
    normal rendering, for use as a last-resort safety net when the regular
    caption pipeline did not run (e.g. render timeout recovery).
    """
    text = str(segment.get("text") or "")
    words_list = [w for w in text.split() if w.strip()]
    if not words_list or duration <= 0.0:
        return []
    try:
        orig_speech_dur = max(
            0.0,
            parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
            - parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00")),
        )
    except Exception:
        orig_speech_dur = duration
    words_count = len(words_list)
    estimated_speech = words_count * 0.38 + 1.5
    effective_dur = min(duration, orig_speech_dur or duration, max(6.0, estimated_speech))
    word_step = effective_dur / max(words_count, 1)
    word_step = max(0.28, min(0.50, word_step))
    out: List[Dict[str, Any]] = []
    cursor = 0.0
    for w in words_list:
        start = cursor
        end = min(cursor + word_step, duration)
        if end <= start:
            break
        out.append({"word": w, "start": round(start, 3), "end": round(end, 3), "confidence": 0.9})
        cursor += word_step
    return out


def _apply_output_basic_caption_safety_net(
    *,
    video_path: Path,
    segment: Dict[str, Any],
    clip_order: int,
    task_id: str,
    duration: float,
) -> Dict[str, Any]:
    """OUTPUT-BASIC-1 Fix A: guarantee visible subtitles on the final MP4.

    Called when the normal caption pipeline did not produce
    ass_event_count_final > 0 (e.g. the per-clip render hit
    VPI_RENDER_CLIP_TIMEOUT_S before reaching the Step 4.4 ASS Karaoke stage).
    Builds a simple fallback ASS from the segment transcript text and burns
    it onto the recovered MP4.
    """
    logger.info(
        "VPI_OUTPUT_BASIC_CAPTIONS_FORCED task_id=%s clip_order=%s video_path=%s",
        task_id, clip_order, video_path,
    )
    fallback_words = _output_basic_build_fallback_caption_words(segment, duration)
    if not fallback_words:
        logger.warning(
            "VPI_OUTPUT_BASIC_CAPTIONS_FAILED task_id=%s clip_order=%s reason=no_transcript_text",
            task_id, clip_order,
        )
        return {"applied": False}
    try:
        from .vpi_ass_caption_service import build_ass_caption_plan as _output_basic_build_ass_caption_plan
        ass_words = _output_basic_normalize_ass_words(fallback_words)
        ass_plan = _output_basic_build_ass_caption_plan(
            clip_id=f"{task_id}_{clip_order}_output_basic_fallback",
            words=ass_words,
            clip_duration=float(duration or 0.0),
            platform="all",
            visual_style="vpi_clean",
            caption_style="vpi_clean",
            editorial_type=str(segment.get("editorial_type") or ""),
            caption_density=float(len(ass_words) / max(1.0, float(duration or 0.0) or 1.0)),
            approx_simple_mode=True,
        )
        ass_plan.validate()
        ass_event_count = len(getattr(ass_plan, "events", []) or [])
        if ass_event_count <= 0:
            logger.warning(
                "VPI_OUTPUT_BASIC_CAPTIONS_FAILED task_id=%s clip_order=%s reason=empty_ass_plan",
                task_id, clip_order,
            )
            return {"applied": False}
        captions_dir = _output_basic_resolve_caption_artifacts_dir(task_id)
        ass_file = captions_dir / f"clip_{clip_order}.ass"
        ass_file.write_text(ass_plan.to_ass_script(), encoding="utf-8")
        logger.info(
            "VPI_OUTPUT_BASIC_FALLBACK_ASS_CREATED task_id=%s clip_order=%s path=%s events=%d",
            task_id, clip_order, ass_file, ass_event_count,
        )
    except Exception as exc:
        logger.warning(
            "VPI_OUTPUT_BASIC_CAPTIONS_FAILED task_id=%s clip_order=%s reason=ass_plan_exception:%s",
            task_id, clip_order, exc,
        )
        return {"applied": False}

    burned_path = video_path.with_name(f"output_basic_ass_{video_path.name}")
    ok, burn_err = _output_basic_burn_ass_subtitles_file(video_path, ass_file, burned_path)
    if not ok or not burned_path.exists():
        logger.warning(
            "VPI_OUTPUT_BASIC_CAPTIONS_FAILED task_id=%s clip_order=%s reason=burn_failed:%s",
            task_id, clip_order, burn_err,
        )
        return {"applied": False}
    logger.info(
        "VPI_OUTPUT_BASIC_ASS_BURNED task_id=%s clip_order=%s path=%s",
        task_id, clip_order, burned_path,
    )
    logger.info(
        "VPI_OUTPUT_BASIC_CAPTIONS_VERIFIED task_id=%s clip_order=%s ass_events=%d path=%s",
        task_id, clip_order, ass_event_count, burned_path,
    )
    return {
        "applied": True,
        "path": burned_path,
        "ass_caption_file_path": str(ass_file),
        "ass_event_count_final": ass_event_count,
    }


def _build_recovered_clip_info_from_path(
    *,
    recovered_path: Path,
    segment: Dict[str, Any],
    clip_order: int,
    stage_recorder: Optional[Dict[str, Any]] = None,
    add_subtitles: bool = False,
    task_id: str = "",
) -> Dict[str, Any]:
    probe = _probe_media_info(recovered_path)
    format_info = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    try:
        duration = float(format_info.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    if duration <= 0.0:
        try:
            duration = max(
                0.0,
                parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
                - parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
            )
        except Exception:
            duration = 0.0
    result = {
        "path": str(recovered_path),
        "filename": recovered_path.name,
        "start_time": segment.get("refined_start_time") or segment.get("start_time") or "00:00",
        "end_time": segment.get("refined_end_time") or segment.get("end_time") or "00:00",
        "duration": duration,
        "text": str(segment.get("text") or ""),
        "reasoning": "recovered_from_temp_final_mp4",
        "relevance_score": float(segment.get("final_rank_score") or segment.get("editorial_score") or 0.0),
        "virality_score": float(segment.get("virality_score") or 0.0),
        "hook_score": float(segment.get("hookability_score") or 0.0),
        "engagement_score": float(segment.get("hookability_score") or 0.0),
        "value_score": float(segment.get("commercial_usefulness_score") or 0.0),
        "shareability_score": float(segment.get("standalone_score") or 0.0),
        "hook_type": str(segment.get("hook_type") or ""),
        "editorial_type": str(segment.get("editorial_type") or ""),
        "recovered_from_temp_final": True,
    }
    # H7.7: Preserve StageRecorder diagnostic data through fallback recovery
    if stage_recorder is not None:
        result["stage_recorder"] = stage_recorder
    # OUTPUT-BASIC-1 Fix A: a recovered (timed-out) clip never reached the
    # normal Step 4.4 ASS Karaoke stage, so it has no burned captions.
    # Force a fallback ASS burn so the final MP4 always shows subtitles.
    if add_subtitles and task_id and duration > 0.0:
        _cap = _apply_output_basic_caption_safety_net(
            video_path=recovered_path,
            segment=segment,
            clip_order=clip_order,
            task_id=task_id,
            duration=duration,
        )
        if _cap.get("applied"):
            _new_path = _cap["path"]
            result["path"] = str(_new_path)
            result["filename"] = Path(_new_path).name
            result["ass_caption_file_path"] = _cap.get("ass_caption_file_path")
            result["ass_event_count_final"] = _cap.get("ass_event_count_final")
            result["ass_caption_events_count"] = _cap.get("ass_event_count_final")
            result["has_ass_captions"] = True
            result["caption_backend"] = "ass_premium_captions"
            result["caption_fallback_reason"] = "output_basic_fallback_ass_burn"
    return result


def _resolve_public_clip_url(task_id: str, file_path: Path) -> str:
    try:
        rel = file_path.relative_to(Path("/app/outputs/generated"))
        return f"/generated/{rel.as_posix()}"
    except Exception as exc:
        logger.warning("Falling back to clips URL for task %s path %s: %s", task_id, file_path, exc)
        return f"/clips/{task_id}/{file_path.name}"


def _build_clip_technical_qc(
    *,
    path: Path,
    clip_info: Dict[str, Any],
    min_duration_s: float = 8.0,
) -> Dict[str, Any]:
    ok, reason, base_meta = _deadline_safe_technical_gate(path)
    reasons: List[str] = []
    if not ok:
        reasons.append(reason)
    meta = dict(base_meta)
    meta["path"] = str(path)

    audio_qc = _as_dict(_as_dict(clip_info.get("output_qc")).get("audio_qc"))
    output_lufs = audio_qc.get("output_lufs")
    input_lufs = audio_qc.get("input_lufs")
    audio_mastering_applied = bool(audio_qc.get("audio_mastering_applied"))
    try:
        output_lufs_val = float(output_lufs) if output_lufs is not None else None
    except Exception:
        output_lufs_val = None
    try:
        input_lufs_val = float(input_lufs) if input_lufs is not None else None
    except Exception:
        input_lufs_val = None

    mean_volume_db = _measure_audio_mean_volume_db(path) if path.exists() else None
    meta["mean_volume_db"] = mean_volume_db
    meta["output_lufs"] = output_lufs_val
    meta["input_lufs"] = input_lufs_val
    meta["audio_mastering_applied"] = audio_mastering_applied

    if output_lufs_val is not None and output_lufs_val <= -95.0:
        reasons.append("audio_lufs_near_silence")
    elif mean_volume_db is not None and mean_volume_db <= -55.0:
        reasons.append("audio_mean_volume_near_silence")

    duration = float(meta.get("duration") or clip_info.get("duration") or 0.0)
    if duration < min_duration_s:
        reasons.append("duration_lt_minimum")

    return {
        "passed": len(reasons) == 0,
        "reasons": list(dict.fromkeys(reasons)),
        "meta": meta,
    }


def _derive_editorial_qc(publishable_qc: Dict[str, Any]) -> Dict[str, Any]:
    strict_reasons = [str(x) for x in (_safe_list(publishable_qc.get("strict_publishable_reasons"))) if str(x)]
    strict_ok = bool(publishable_qc.get("strict_publishable"))
    warnings = strict_reasons if strict_reasons else []
    return {
        "passed": strict_ok,
        "warnings": warnings,
        "reasons": strict_reasons,
    }


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _normalize_confidence_0_1(value: Any) -> Optional[float]:
    raw = _as_float(value)
    if raw is None:
        return None
    if raw > 1.0:
        return max(0.0, min(1.0, raw / 100.0))
    return max(0.0, min(1.0, raw))


def _has_strong_hook_evidence(
    final_contract: Dict[str, Any],
    clip_info: Dict[str, Any],
    publishable_qc: Dict[str, Any],
) -> bool:
    contract = _as_dict(final_contract)
    clip = _as_dict(clip_info)
    pub = _as_dict(publishable_qc)
    hook_plan = _as_dict(clip.get("hook_plan"))
    retention_plan = _as_dict(clip.get("retention_plan"))
    text = str(clip.get("text") or clip.get("transcript") or "").lower()

    weak_openers = ("hola soy", "hoy quiero hablar", "vengo a hablar", "en este momento")
    if any(token in text[:120] for token in weak_openers):
        return False

    hook_first3_pass = str(pub.get("hook_first_3s") or "").lower() == "pass"
    hook_score = int(
        hook_plan.get("hook_first3_score")
        or hook_plan.get("hook_first3_retention_score")
        or pub.get("hook_strength_score")
        or 0
    )
    hook_type = str(hook_plan.get("hook_type") or "").lower()
    strong_types = ("revelation", "warning", "myth", "objection", "actionable_advice", "risk_warning")
    has_strong_type = any(token in hook_type for token in strong_types)
    verbal_phrases = (
        "esto mucha gente no lo sabe",
        "no es vender miedo",
        "la realidad es que",
        "el problema viene cuando",
    )
    has_strong_phrase = any(phrase in text for phrase in verbal_phrases)
    retention_first3 = bool(
        retention_plan.get("first_3s_retention")
        or _as_dict(pub.get("first3_visual_contract")).get("first3_retention")
    )
    editorial_score = _as_float(clip.get("editorial_score")) or 0.0
    score_support = editorial_score >= 75.0
    overlay_only = bool(hook_plan.get("overlay_rendered") or hook_plan.get("kickframe_applied")) and hook_score < 5 and not has_strong_phrase
    if overlay_only:
        return False
    return bool((hook_first3_pass and hook_score >= 5) or has_strong_type or has_strong_phrase or retention_first3 or score_support)


def _has_complete_idea_evidence(
    final_contract: Dict[str, Any],
    clip_info: Dict[str, Any],
    publishable_qc: Dict[str, Any],
) -> bool:
    contract = _as_dict(final_contract)
    clip = _as_dict(clip_info)
    pub = _as_dict(publishable_qc)
    text = str(clip.get("text") or clip.get("transcript") or "").strip()
    words = [w for w in text.split() if w]
    duration = _as_float(clip.get("duration")) or 0.0
    complete_pass = str(pub.get("complete_idea") or "").lower() == "pass"
    boundary_pass = str(pub.get("no_mid_sentence_cut") or "").lower() == "pass"
    complete_score = _as_float(pub.get("complete_idea_score"))
    if complete_score is None:
        complete_score = _as_float(_as_dict(clip.get("publishable_qc")).get("complete_idea_score"))
    if complete_score is None:
        complete_score = _as_float(contract.get("complete_idea_score"))
    ends_clean = text.endswith((".", "!", "?", "…"))
    abrupt_tail = text.lower().endswith(("que", "de", "y", "o", "pero", "porque", "cuando"))
    too_short = len(words) < 12 or duration < 8.0
    generic_only = "hola soy" in text.lower() and len(words) < 20
    semantic_shape_ok = len(words) >= 18 and ends_clean and not abrupt_tail and not generic_only
    return bool((complete_pass and boundary_pass) or (complete_score is not None and complete_score >= 0.75) or semantic_shape_ok) and not too_short


def classify_premium_output_quality(
    final_contract: Dict[str, Any],
    *,
    technical_qc: Optional[Dict[str, Any]] = None,
    clip_info: Optional[Dict[str, Any]] = None,
    publishable_qc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Final premium quality classifier.

    Status:
      - rejected_technical: technical blocking failure
      - needs_review: technical pass with editorial/quality warnings
      - ready: technical pass with no quality warnings
    """
    contract = _as_dict(final_contract)
    tech = _as_dict(technical_qc)
    clip = _as_dict(clip_info)
    pub = _as_dict(publishable_qc)
    final_mp4_contract = _as_dict(clip.get("final_mp4_contract")) or _as_dict(clip.get("final_rendered_contract"))
    if final_mp4_contract:
        contract = final_mp4_contract

    technical_reasons: List[str] = []
    if tech:
        technical_reasons.extend([str(x) for x in (_safe_list(tech.get("reasons"))) if str(x)])
        if not bool(tech.get("passed")) and not technical_reasons:
            technical_reasons.append("technical_qc_failed")
    else:
        if not bool(contract.get("technical_valid", False)):
            technical_reasons.append("technical_invalid_render_output")
        if not bool(contract.get("has_audio", False)):
            technical_reasons.append("missing_audio_stream")
        if not bool(contract.get("has_video", False)):
            technical_reasons.append("missing_video_stream")
        if not bool(contract.get("render_success", False)):
            technical_reasons.append("render_output_missing_or_empty")
    if final_mp4_contract and not bool(final_mp4_contract.get("final_publishable", True)):
        technical_reasons.extend([
            str(x) for x in (_safe_list(final_mp4_contract.get("final_blocking_reasons"))) if str(x)
        ] or ["final_mp4_contract_blocked_publishable"])

    if technical_reasons:
        return {
            "status": "rejected_technical",
            "warnings": [],
            "reasons": list(dict.fromkeys(technical_reasons)),
            "hook_evidence": False,
            "complete_idea_evidence": False,
        }

    warnings: List[str] = []
    positive_evidence: List[str] = []
    evidence = _as_dict(contract.get("evidence_sources"))
    premium_layers = [str(x).lower() for x in _safe_list(evidence.get("premium_layers_applied"))]
    broll_items = [x for x in _safe_list(clip.get("editorial_broll")) if isinstance(x, dict)]
    sfx_meta = _as_dict(clip.get("sfx"))
    music_meta = _as_dict(clip.get("music"))
    subtitle_meta = _as_dict(clip.get("subtitle_intelligence"))
    output_qc = _as_dict(clip.get("output_qc"))
    quality_assurance = _as_dict(clip.get("quality_assurance"))
    cache_policy = _as_dict(clip.get("cache_policy"))
    visual_fx_meta = _as_dict(clip.get("visual_effects"))
    motion_meta = _as_dict(clip.get("motion_overlay"))
    silence_meta = _as_dict(clip.get("silence_edit_plan"))
    transition_meta = _as_dict(clip.get("transitions"))
    caption_visual_support = _as_dict(clip.get("caption_visual_support")) or _as_dict(clip.get("caption_visual_support_plan"))
    final_contract_checks = _as_dict(evidence.get("final_contract_checks"))
    strict_reasons = [str(x).lower() for x in _safe_list(pub.get("strict_publishable_reasons"))]
    caption_backend = str(contract.get("caption_backend") or clip.get("caption_backend") or "").strip().lower()
    caption_fallback_reason = str(contract.get("caption_fallback_reason") or clip.get("caption_fallback_reason") or "").strip()
    has_ass_captions = bool(
        contract.get("has_ass_captions")
        or clip.get("has_ass_captions")
        or contract.get("ass_caption_file_path")
        or clip.get("ass_caption_file_path")
    )

    # 1) B-roll applied but category confidence < 0.65.
    if bool(contract.get("has_broll")) and broll_items:
        low_conf_found = False
        for item in broll_items:
            conf = (
                _normalize_confidence_0_1(item.get("category_confidence"))
                or _normalize_confidence_0_1(item.get("confidence"))
                or _normalize_confidence_0_1(item.get("broll_relevance_score"))
                or _normalize_confidence_0_1(item.get("asset_score"))
            )
            if conf is not None and conf < 0.65:
                low_conf_found = True
                break
        if low_conf_found:
            warnings.append("broll_low_category_confidence")

    # 2) B-roll asset taxonomy mismatch.
    broll_blob = " ".join(
        json.dumps(item, ensure_ascii=False)
        for item in broll_items
    ).lower()
    if "taxonomy_mismatch" in broll_blob or "asset_taxonomy_mismatch" in broll_blob:
        warnings.append("broll_asset_taxonomy_mismatch")

    # 3) B-roll from generic/abstract fallback.
    generic_markers = ("generic", "abstract", "local_fallback", "neutral_background")
    for item in broll_items:
        selected_category = str(item.get("selected_category") or "").lower()
        asset_source = str(item.get("asset_source") or "").lower()
        cue_type = str(item.get("cue_type") or "").lower()
        reason = str(item.get("reason") or "").lower()
        if (
            any(marker in selected_category for marker in generic_markers)
            or any(marker in cue_type for marker in generic_markers)
            or "fallback" in asset_source
            or any(marker in reason for marker in generic_markers)
        ):
            warnings.append("broll_generic_or_abstract_fallback")
            break

    # 4) SFX events > budget.
    sfx_count = int(sfx_meta.get("sfx_count") or len(_safe_list(sfx_meta.get("sfx_events"))))
    if sfx_count > 6:
        warnings.append("sfx_events_over_budget")

    # 5) BGM missing but expected.
    bgm_expected = (
        ("bgm" in premium_layers)
        or bool(final_contract_checks.get("music"))
        or bool(clip.get("final_output_uses_music"))
        or bool(music_meta.get("music_applied"))
        or ("no_perceptible_bgm_or_no_bgm_evidence" in strict_reasons)
    )
    if bgm_expected and not bool(contract.get("has_bgm")):
        warnings.append("bgm_missing_but_expected")

    # 6) audio mastering fallback used.
    mastering_fallback = (
        str(music_meta.get("audio_mastering_fallback") or "").strip()
        or str(_as_dict(output_qc.get("audio_qc")).get("audio_mastering_fallback") or "").strip()
    )
    if mastering_fallback:
        warnings.append("audio_mastering_fallback_used")

    # 7) captions low confidence or weird transcript markers.
    words = _safe_list(clip.get("words"))
    confidences: List[float] = []
    for word in words:
        if isinstance(word, dict):
            conf = _as_float(word.get("confidence"))
            if conf is not None:
                confidences.append(conf if conf <= 1.0 else conf / 100.0)
    avg_conf = (sum(confidences) / len(confidences)) if confidences else None
    text_blob = " ".join(
        [
            str(clip.get("text") or ""),
            str(clip.get("transcript") or ""),
            str(subtitle_meta.get("reason") or ""),
        ]
    ).lower()
    weird_markers = ("[music]", "[inaudible]", "<unk>", "???")
    if (avg_conf is not None and avg_conf < 0.60) or any(marker in text_blob for marker in weird_markers):
        warnings.append("captions_low_confidence_or_weird_markers")

    # 8) transcript cache mismatch.
    cache_blob = " ".join(
        [
            str(cache_policy.get("transcript_cache_source") or ""),
            str(cache_policy.get("cache_guard_reason") or ""),
            str(clip.get("transcript_cache_source") or ""),
            str(clip.get("transcript_cache_guard_reason") or ""),
        ]
    ).lower()
    if any(token in cache_blob for token in ("hash_mismatch", "language_mismatch", "source_hash_mismatch")):
        warnings.append("transcript_cache_mismatch")

    # 9) too many visual elements.
    visual_elements = (
        len(broll_items)
        + len(_safe_list(_as_dict(clip.get("caption_overlay_pack")).get("caption_overlay_actions")))
        + len(_safe_list(_as_dict(visual_fx_meta.get("effects")).get("events")))
        + (1 if bool(motion_meta.get("motion_overlay_applied")) else 0)
        + (1 if bool(transition_meta.get("transitions_applied")) else 0)
    )
    if visual_elements > 8:
        warnings.append("too_many_visual_elements")

    # 10) no motion/rhythm/visual support.
    has_visual_support = bool(
        contract.get("has_broll")
        or contract.get("has_motion_or_vfx")
        or contract.get("has_rhythm_cleanup")
        or bool(motion_meta.get("motion_overlay_applied"))
        or bool(transition_meta.get("shot_rhythm_applied"))
        or bool(silence_meta.get("rendered"))
    )
    if not has_visual_support:
        warnings.append("no_motion_rhythm_visual_support")

    # 11) final output contains known bad asset cue.
    bad_assets = {"de.mp4", "les.mp4", "sea.mp4"}
    for item in broll_items:
        asset_name = Path(str(item.get("asset_path") or "")).name.lower()
        cue = str(item.get("trigger_text") or item.get("visual_query") or "").strip().lower()
        if asset_name in bad_assets or cue in {"de", "les", "sea"}:
            warnings.append("known_bad_asset_cue")
            break

    # 12) QA score below threshold.
    qa_score = (
        _as_float(output_qc.get("qa_score"))
        or _as_float(quality_assurance.get("score"))
        or _as_float(clip.get("qa_score"))
    )
    if qa_score is not None:
        qa_score_norm = qa_score if qa_score <= 1.0 else qa_score / 100.0
        if qa_score_norm < 0.65:
            warnings.append("qa_score_below_threshold")

    # 13) visual editing layer quality checks.
    visual_clutter_score = _as_float(contract.get("visual_clutter_score"))
    if visual_clutter_score is None:
        visual_clutter_score = _as_float(visual_fx_meta.get("visual_clutter_score"))
    if visual_clutter_score is not None and visual_clutter_score > 0.9:
        warnings.append("visual_clutter_too_high")

    has_semantic_object = bool(contract.get("has_semantic_object") or caption_visual_support.get("has_semantic_object"))
    semantic_objects = _safe_list(caption_visual_support.get("semantic_objects"))
    if has_semantic_object and semantic_objects:
        irrelevant = False
        for obj in semantic_objects:
            if not isinstance(obj, dict):
                continue
            if not str(obj.get("phrase") or "").strip():
                irrelevant = True
                break
            if str(obj.get("category") or "").strip().lower() in {"generic", "abstract"}:
                irrelevant = True
                break
        if irrelevant:
            warnings.append("semantic_object_irrelevant")

    expected_premium_visual = bool(
        contract.get("has_broll")
        or contract.get("has_motion_or_vfx")
        or bool(_safe_list(transition_meta.get("transitions")))
    )
    has_transition = bool(contract.get("has_transition") or transition_meta.get("has_transition"))
    has_motion_reveal = bool(contract.get("has_motion_reveal") or _as_dict(visual_fx_meta.get("motion_reveal_plan")).get("enabled"))
    has_existing_visual_motion = bool(
        contract.get("has_motion_or_vfx")
        or _as_dict(clip.get("motion_overlay")).get("motion_overlay_applied")
        or transition_meta.get("shot_rhythm_applied")
    )
    if expected_premium_visual and not (has_transition or has_motion_reveal or has_semantic_object or has_existing_visual_motion):
        warnings.append("no_visual_retention_device")

    # 14) disfluency cleanup quality + runtime timeline bridge evidence.
    runtime_disfluency_plan = _as_dict(clip.get("disfluency_plan"))
    disfluency_quality = str(
        contract.get("disfluency_edit_quality")
        or runtime_disfluency_plan.get("disfluency_edit_quality")
        or _as_dict(visual_fx_meta.get("disfluency_plan")).get("disfluency_edit_quality")
        or ""
    ).lower()
    disfluency_cleanup_count = int(
        contract.get("disfluency_cleanup_count")
        or runtime_disfluency_plan.get("disfluency_cleanup_count")
        or _as_dict(visual_fx_meta.get("disfluency_plan")).get("disfluency_cleanup_count")
        or 0
    )
    high_unhandled_count = int(
        contract.get("disfluency_high_severity_unhandled_count")
        or runtime_disfluency_plan.get("high_severity_unhandled_count")
        or _as_dict(visual_fx_meta.get("disfluency_plan")).get("high_severity_unhandled_count")
        or clip.get("high_severity_unhandled_count")
        or 0
    )
    disfluency_actions_count = int(
        contract.get("disfluency_actions_count")
        or runtime_disfluency_plan.get("actions_count")
        or clip.get("disfluency_actions_count")
        or 0
    )
    if high_unhandled_count > 0 and disfluency_actions_count <= 0:
        warnings.append("unhandled_high_severity_disfluency")
    elif disfluency_actions_count > 0:
        positive_evidence.append("has_disfluency_cleanup")
    if disfluency_quality in {"needs_review", "poor"}:
        warnings.append("unhandled_high_severity_disfluency")
    if disfluency_cleanup_count >= 5:
        warnings.append("robotic_pacing_disfluency_overcut")

    timeline_plan_path = str(contract.get("timeline_plan_path") or clip.get("timeline_plan_path") or "").strip()
    timeline_plan_failed = bool(
        "timeline_plan_failed" in " ".join(str(x) for x in _safe_list(clip.get("timeline_warnings"))).lower()
    )
    if timeline_plan_path:
        positive_evidence.append("timeline_plan_present")
    elif timeline_plan_failed:
        warnings.append("timeline_plan_failed")

    remotion_scene_plan_path = str(contract.get("remotion_scene_plan_path") or clip.get("remotion_scene_plan_path") or "").strip()
    remotion_overlay_status = str(contract.get("remotion_overlay_status") or clip.get("remotion_overlay_status") or "").strip().lower()
    remotion_overlay_file_path = str(contract.get("remotion_overlay_file_path") or clip.get("remotion_overlay_file_path") or "").strip()
    remotion_overlay_composed = bool(contract.get("remotion_overlay_composed") or clip.get("remotion_overlay_composed"))
    remotion_overlay_composed_path = str(contract.get("remotion_overlay_composed_path") or clip.get("remotion_overlay_composed_path") or "").strip()
    remotion_overlay_composition_fallback_reason = str(
        contract.get("remotion_overlay_composition_fallback_reason")
        or clip.get("remotion_overlay_composition_fallback_reason")
        or ""
    ).strip()
    remotion_requested = _is_truthy_env(os.environ.get("VIRACLIP_REMOTION_OVERLAYS"))
    if remotion_scene_plan_path:
        positive_evidence.append("remotion_scene_plan_present")
    if remotion_overlay_status == "failed_plan_generation":
        warnings.append("remotion_scene_plan_failed")
    if remotion_overlay_status == "rendered" and remotion_overlay_file_path:
        positive_evidence.append("remotion_overlay_rendered")
    if remotion_overlay_status == "failed":
        warnings.append("remotion_overlay_failed_fallback")
    if remotion_overlay_composition_fallback_reason:
        warnings.append("remotion_overlay_composition_failed_fallback")
    if remotion_overlay_composed and remotion_overlay_composed_path:
        positive_evidence.append("remotion_overlay_composed")
    if remotion_requested and remotion_overlay_status == "skipped_remotion_unavailable":
        warnings.append("remotion_overlay_requested_but_unavailable")
    overlay_backend_for_check = str(contract.get("overlay_backend") or clip.get("overlay_backend") or "").lower()
    if ("remotion" in overlay_backend_for_check) and not remotion_overlay_file_path:
        warnings.append("remotion_overlay_claim_without_file")

    # 15) visual style coherence conflict.
    visual_style = str(contract.get("visual_style") or _as_dict(visual_fx_meta.get("visual_coherence_plan")).get("visual_style") or "")
    trans_blob = " ".join(json.dumps(x, ensure_ascii=False) for x in _safe_list(transition_meta.get("transitions"))).lower()
    sem_blob = " ".join(json.dumps(x, ensure_ascii=False) for x in semantic_objects).lower()
    style_conflict = False
    if visual_style == "calm_trust" and any(token in (trans_blob + sem_blob) for token in ("dark_push", "quick_impact_cut")):
        style_conflict = True
    if visual_style == "serious_warning" and any(token in sem_blob for token in ("family", "heart", "warm")):
        style_conflict = True
    if style_conflict:
        warnings.append("visual_style_conflict")

    # 16) caption/overlay coherence quality checks.
    caption_cleanup = _as_dict(contract.get("caption_disfluency_cleanup")) or _as_dict(caption_visual_support.get("caption_disfluency_cleanup"))
    caption_clean_text = str(caption_visual_support.get("caption_clean_text") or clip.get("text") or clip.get("transcript") or "").lower()
    filler_tokens = {"eee", "eh", "aaa", "mmm", "um", "uh", "pues", "bueno", "vale", "sabes", "o sea", "entonces"}
    if caption_cleanup and any(token in caption_clean_text for token in filler_tokens):
        warnings.append("captions_include_filler_after_cleanup")
    if bool(caption_visual_support.get("caption_timing_conflict")):
        warnings.append("caption_timing_conflict_with_disfluency_cleanup")
    if bool(contract.get("overlay_duplication_warning") or caption_visual_support.get("overlay_duplication_warning")):
        warnings.append("overlay_duplicates_caption_or_object")
    safe_area_conflicts = _safe_list(contract.get("safe_area_conflicts")) or _safe_list(caption_visual_support.get("safe_area_conflicts"))
    if safe_area_conflicts:
        warnings.append("safe_area_conflicts_unresolved")
    readability = _as_float(contract.get("caption_readability_score"))
    if readability is None:
        readability = _as_float(caption_visual_support.get("caption_readability_score"))
    if readability is not None and readability < 0.75:
        warnings.append("caption_readability_low")
    if has_ass_captions and (readability is None or readability >= 0.75):
        positive_evidence.append("ass_captions_applied")
    if caption_fallback_reason and (
        caption_backend == "legacy_with_ass_artifact"
        or "ass_" in caption_fallback_reason.lower()
    ):
        warnings.append("ass_caption_fallback")
    has_any_caption_backend = bool(caption_backend)
    has_any_caption_output = bool(
        contract.get("has_captions")
        or clip.get("has_captions")
        or subtitle_meta.get("rendered")
        or clip.get("caption_ass_debug_path")
        or clip.get("words")
    )
    if not has_any_caption_backend and not has_any_caption_output:
        warnings.append("captions_missing")

    # Keep reasons aligned with strong editorial publishability signals.
    reasons: List[str] = []
    if strict_reasons:
        reasons.extend(strict_reasons)

    hook_evidence = _has_strong_hook_evidence(contract, clip, pub)
    complete_idea_evidence = _has_complete_idea_evidence(contract, clip, pub)
    if not hook_evidence:
        warnings.append("weak_hook_first_3s")
    if not complete_idea_evidence:
        warnings.append("incomplete_idea")

    status = "needs_review" if warnings else "ready"
    logger.info(
        "DISFLUENCY_QUALITY status=%s warnings=%s",
        status,
        "|".join([w for w in warnings if "disfluency" in w or "robotic_pacing" in w]) or "none",
    )
    logger.info(
        "VISUAL_COHERENCE_SCORE score=%s warnings=%s",
        str(contract.get("visual_coherence_score") or _as_dict(visual_fx_meta).get("visual_coherence_score") or "0"),
        "|".join([w for w in warnings if "visual_style" in w or "visual_clutter" in w]) or "none",
    )
    logger.info(
        "PREMIUM_OUTPUT_QUALITY status=%s warnings=%s hook_evidence=%s complete_idea=%s",
        status,
        "|".join(list(dict.fromkeys(warnings))) or "none",
        str(bool(hook_evidence)).lower(),
        str(bool(complete_idea_evidence)).lower(),
    )
    return {
        "status": status,
        "warnings": list(dict.fromkeys(warnings)),
        "reasons": list(dict.fromkeys(reasons)),
        "hook_evidence": bool(hook_evidence),
        "complete_idea_evidence": bool(complete_idea_evidence),
        "positive_evidence": list(dict.fromkeys(positive_evidence)),
    }


TASK_DIAGNOSTIC_CHOKEPOINTS = {
    "source_download",
    "transcription",
    "segment_selection",
    "extraction",
    "render",
    "technical_qc",
    "editorial_qc",
    "publishable_gate",
    "db_insert",
    "frontend_visibility",
    "delivered",
    "unknown",
}


def _resolve_task_diagnostics_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    primary = repo_root / "reports" / "task_diagnostics"
    fallback = Path("/app/reports/task_diagnostics")
    for candidate in (primary, fallback):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    return primary


def _derive_task_diagnostic_chokepoint(report: Dict[str, Any]) -> str:
    progress = str(report.get("progress_message") or "").lower()
    reasons = " ".join(str(x) for x in (_safe_list(report.get("failed_clip_reasons")) + _safe_list(report.get("qc_reasons")))).lower()
    selected = int(report.get("selected_segments_count") or 0)
    extracted = int(report.get("extraction_success_count") or 0)
    attempted = int(report.get("render_attempted_count") or 0)
    rendered = int(report.get("rendered_outputs_count") or 0)
    technical_valid = int(report.get("technical_valid_count") or 0)
    inserted = int(report.get("inserted_clips_count") or 0)
    publishable_errors = int(report.get("publishable_gate_error_count") or 0)
    strict_rejected = int(report.get("strict_qc_rejected_count") or 0)
    frontend_visible = report.get("frontend_visible_clips_count")

    if inserted > 0:
        if isinstance(frontend_visible, int) and frontend_visible < inserted:
            return "frontend_visibility"
        return "delivered"

    if "download" in progress or "download" in reasons or "youtube" in reasons:
        return "source_download"
    if "transcript" in progress or "transcript" in reasons or "transcription" in reasons:
        return "transcription"
    if selected <= 0:
        return "segment_selection"
    if extracted <= 0 and selected > 0:
        return "extraction"
    if attempted > 0 and rendered <= 0:
        return "render"
    if rendered > 0 and technical_valid <= 0:
        return "technical_qc"
    if publishable_errors > 0 and inserted <= 0:
        return "publishable_gate"
    if strict_rejected > 0 and inserted <= 0:
        return "editorial_qc"
    if rendered > 0 and inserted <= 0:
        if "insert" in progress or "persist" in reasons:
            return "db_insert"
        return "db_insert"
    return "unknown"


def _build_task_diagnostic_markdown(report: Dict[str, Any]) -> str:
    lines = [
        f"# Task Diagnostics — {report.get('task_id')}",
        "",
        f"- status: `{report.get('status')}`",
        f"- progress_message: `{report.get('progress_message')}`",
        f"- chokepoint: `{report.get('chokepoint')}`",
        "",
        "## Metrics",
        f"- requested_clips: {report.get('requested_clips')}",
        f"- candidate_pool_size: {report.get('candidate_pool_size')}",
        f"- selected_segments_count: {report.get('selected_segments_count')}",
        f"- extraction_success_count: {report.get('extraction_success_count')}",
        f"- render_attempted_count: {report.get('render_attempted_count')}",
        f"- render_success_count: {report.get('render_success_count')}",
        f"- rendered_outputs_count: {report.get('rendered_outputs_count')}",
        f"- durable_outputs_count: {report.get('durable_outputs_count')}",
        f"- technical_valid_count: {report.get('technical_valid_count')}",
        f"- editorial_warning_count: {report.get('editorial_warning_count')}",
        f"- publishable_gate_error_count: {report.get('publishable_gate_error_count')}",
        f"- strict_qc_rejected_count: {report.get('strict_qc_rejected_count')}",
        f"- inserted_clips_count: {report.get('inserted_clips_count')}",
        f"- frontend_visible_clips_count: {report.get('frontend_visible_clips_count')}",
        f"- output_files_count: {report.get('output_files_count')}",
        "",
        "## Reasons",
        f"- failed_clip_reasons: {json.dumps(report.get('failed_clip_reasons') or [], ensure_ascii=False)}",
        f"- qc_reasons: {json.dumps(report.get('qc_reasons') or [], ensure_ascii=False)}",
    ]
    return "\n".join(lines) + "\n"


def _maybe_write_task_diagnostic_report(report: Dict[str, Any]) -> None:
    inserted = int(report.get("inserted_clips_count") or 0)
    render_failed_count = int(report.get("render_attempted_count") or 0) - int(report.get("render_success_count") or 0)
    technical_failed = int(report.get("rendered_outputs_count") or 0) - int(report.get("technical_valid_count") or 0)
    editorial_warning_count = int(report.get("editorial_warning_count") or 0)
    publishable_gate_error_count = int(report.get("publishable_gate_error_count") or 0)
    frontend_visible = report.get("frontend_visible_clips_count")
    frontend_mismatch = isinstance(frontend_visible, int) and frontend_visible < inserted
    progress_message = str(report.get("progress_message") or "")

    requested = int(report.get("requested_clips") or 0)
    should_write = any(
        [
            inserted == 0,
            requested > 0 and inserted < requested,
            "post_render_delivery_failed" in progress_message,
            render_failed_count > 0,
            technical_failed > 0,
            publishable_gate_error_count > 0,
            frontend_mismatch,
            editorial_warning_count > 0,
        ]
    )
    if not should_write:
        return

    report = dict(report)
    report["failed_clip_reasons"] = _safe_list(report.get("failed_clip_reasons"))
    report["qc_reasons"] = _safe_list(report.get("qc_reasons"))
    report["chokepoint"] = _derive_task_diagnostic_chokepoint(report)
    if report["chokepoint"] not in TASK_DIAGNOSTIC_CHOKEPOINTS:
        report["chokepoint"] = "unknown"

    out_dir = _resolve_task_diagnostics_dir()
    task_id = str(report.get("task_id") or "unknown_task")
    json_path = out_dir / f"{task_id}.json"
    md_path = out_dir / f"{task_id}.md"
    try:
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_build_task_diagnostic_markdown(report), encoding="utf-8")
        logger.info(
            "TASK_DIAGNOSTIC_REPORT_WRITTEN task_id=%s chokepoint=%s json=%s md=%s",
            task_id,
            report.get("chokepoint"),
            str(json_path),
            str(md_path),
        )
    except Exception as exc:
        logger.warning("TASK_DIAGNOSTIC_REPORT_WRITE_FAILED task_id=%s error=%s", task_id, exc)


def _filename_layer_markers(path: Path) -> Dict[str, bool]:
    name = path.name.lower()
    return {
        "bgm": "music_" in name or "mastered_music_" in name,
        "sfx": "sfx_" in name,
        "broll": "broll_" in name,
        "captions": "sub_" in name,
        "branding": "brand_" in name,
        "rhythm": ("silence_" in name) or ("rhythm_" in name),
        "motion_or_vfx": ("vfx_" in name) or ("motion_" in name),
        "audio_mastering": "mastered_" in name,
    }


def _build_final_rendered_clip_contract(
    *,
    task_id: str,
    clip_order: int,
    segment: Dict[str, Any],
    clip_info: Dict[str, Any],
) -> Dict[str, Any]:
    final_path = Path(str(clip_info.get("path") or ""))
    exists = final_path.exists()
    probe = _probe_media_info(final_path) if exists else {}
    streams = _safe_list(probe.get("streams"))
    format_info = _as_dict(probe.get("format"))
    video_stream = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"), {})

    width = int(_as_dict(video_stream).get("width") or 0)
    height = int(_as_dict(video_stream).get("height") or 0)
    has_video = bool(video_stream)
    has_audio = bool(audio_stream)
    file_size = int(final_path.stat().st_size or 0) if exists else 0

    try:
        duration = float(
            format_info.get("duration")
            or _as_dict(video_stream).get("duration")
            or clip_info.get("duration")
            or 0.0
        )
    except Exception:
        duration = float(clip_info.get("duration") or 0.0)

    premium_layers_field_present = "premium_layers_applied" in clip_info
    premium_layers_applied_raw = clip_info.get("premium_layers_applied")
    premium_layers_applied = _safe_list(premium_layers_applied_raw)

    music_meta = _as_dict(clip_info.get("music"))
    sfx_meta = _as_dict(clip_info.get("sfx"))
    visual_fx_meta = _as_dict(clip_info.get("visual_effects"))
    transition_meta = _as_dict(clip_info.get("transitions"))
    silence_meta = _as_dict(clip_info.get("silence_edit_plan"))
    subtitle_meta = _as_dict(clip_info.get("subtitle_intelligence"))
    brand_meta = _as_dict(clip_info.get("brand_treatment"))
    output_qc = _as_dict(clip_info.get("output_qc"))
    final_contract_meta = _as_dict(clip_info.get("final_contract"))
    final_contract_checks = _as_dict(final_contract_meta.get("final_contract"))
    markers = _filename_layer_markers(final_path)

    independent_bgm = bool(
        clip_info.get("final_output_uses_music")
        or music_meta.get("final_output_uses_bgm")
        or music_meta.get("music_final_verified")
        or final_contract_checks.get("music")
    )
    independent_sfx = bool(
        clip_info.get("final_output_uses_sfx")
        or sfx_meta.get("sfx_final_verified")
        or final_contract_checks.get("sfx")
    )
    independent_vfx = bool(
        clip_info.get("final_output_uses_vfx")
        or visual_fx_meta.get("final_output_uses_vfx")
        or visual_fx_meta.get("visual_effects_final_verified")
        or final_contract_checks.get("vfx")
    )
    independent_rhythm = bool(
        silence_meta.get("rendered")
        or float(silence_meta.get("total_removed_s") or 0.0) > 0.0
        or transition_meta.get("shot_rhythm_applied")
        or ("rhythm" in premium_layers_applied)
    )
    independent_broll = bool(clip_info.get("editorial_broll"))
    independent_captions = bool(
        clip_info.get("caption_ass_debug_path")
        or clip_info.get("ass_caption_file_path")
        or clip_info.get("has_ass_captions")
        or clip_info.get("caption_backend")
        or clip_info.get("words")
        or subtitle_meta.get("rendered")
    )
    independent_branding = bool(
        brand_meta.get("rendered")
        or brand_meta.get("applied")
        or output_qc.get("watermark")
    )
    independent_audio_mastering = bool(
        music_meta.get("audio_mastering_applied")
        or music_meta.get("mastering_applied")
    )
    has_transition = bool(
        transition_meta.get("has_transition")
        or transition_meta.get("transitions_applied")
        or transition_meta.get("final_output_uses_transition")
        or transition_meta.get("total_transitions")
    )
    has_semantic_object = bool(
        _as_dict(clip_info.get("caption_visual_support")).get("has_semantic_object")
        or _as_dict(clip_info.get("caption_visual_support")).get("semantic_objects_enabled")
        or _as_dict(clip_info.get("caption_visual_support_plan")).get("has_semantic_object")
        or _as_dict(clip_info.get("caption_visual_support_plan")).get("semantic_objects_enabled")
    )
    has_motion_reveal = bool(
        visual_fx_meta.get("has_motion_reveal")
        or _as_dict(visual_fx_meta.get("motion_reveal_plan")).get("enabled")
        or _as_dict(clip_info.get("motion_overlay")).get("motion_reveal_applied")
    )
    visual_clutter_score = (
        _as_float(visual_fx_meta.get("visual_clutter_score"))
        or _as_float(_as_dict(clip_info.get("motion_overlay")).get("visual_clutter_score"))
        or 0.0
    )
    visual_coherence_score = (
        _as_float(visual_fx_meta.get("visual_coherence_score"))
        or _as_float(_as_dict(clip_info.get("motion_overlay")).get("visual_coherence_score"))
        or 0.0
    )
    visual_style = str(
        visual_fx_meta.get("visual_style")
        or _as_dict(visual_fx_meta.get("visual_coherence_plan")).get("visual_style")
        or "clear_explanation"
    )
    disfluency_plan = _as_dict(visual_fx_meta.get("disfluency_plan")) or _as_dict(clip_info.get("disfluency_plan"))
    has_disfluency_cleanup = bool(
        visual_fx_meta.get("has_disfluency_cleanup")
        or disfluency_plan.get("has_disfluency_cleanup")
    )
    disfluency_cleanup_count = int(
        visual_fx_meta.get("disfluency_cleanup_count")
        or disfluency_plan.get("disfluency_cleanup_count")
        or 0
    )
    preserved_emphasis_pause_count = int(
        visual_fx_meta.get("preserved_emphasis_pause_count")
        or disfluency_plan.get("preserved_emphasis_pause_count")
        or 0
    )
    covered_disfluency_count = int(
        visual_fx_meta.get("covered_disfluency_count")
        or disfluency_plan.get("covered_disfluency_count")
        or 0
    )
    disfluency_edit_quality = str(
        visual_fx_meta.get("disfluency_edit_quality")
        or disfluency_plan.get("disfluency_edit_quality")
        or "unknown"
    )
    visual_editing_quality = str(
        visual_fx_meta.get("visual_editing_quality")
        or _as_dict(clip_info.get("motion_overlay")).get("visual_editing_quality")
        or ("needs_review" if visual_clutter_score > 0.9 else "premium_visual")
    )
    caption_support_meta = _as_dict(clip_info.get("caption_visual_support")) or _as_dict(clip_info.get("caption_visual_support_plan"))
    has_clean_captions = bool(caption_support_meta.get("has_clean_captions"))
    caption_disfluency_cleanup = _as_dict(caption_support_meta.get("caption_disfluency_cleanup"))
    caption_readability_score = _as_float(caption_support_meta.get("caption_readability_score")) or 0.0
    caption_style = str(caption_support_meta.get("caption_style") or "clean_readable")
    highlight_count = int(caption_support_meta.get("highlight_count") or 0)
    overlay_coherence_score = _as_float(caption_support_meta.get("overlay_coherence_score")) or 0.0
    overlay_duplication_warning = bool(caption_support_meta.get("overlay_duplication_warning"))
    safe_area_conflicts = _safe_list(caption_support_meta.get("safe_area_conflicts"))
    timeline_plan_path = str(clip_info.get("timeline_plan_path") or "").strip() or None
    disfluency_plan_path = str(clip_info.get("disfluency_plan_path") or "").strip() or None
    selection_contract_path = str(clip_info.get("selection_contract_path") or "").strip() or None
    remotion_scene_plan_path = str(clip_info.get("remotion_scene_plan_path") or "").strip() or None
    remotion_scene_events_count = int(clip_info.get("remotion_scene_events_count") or 0)
    remotion_overlay_status = str(clip_info.get("remotion_overlay_status") or "").strip().lower() or "disabled"
    remotion_installed = bool(clip_info.get("remotion_installed"))
    remotion_scaffold_present = bool(clip_info.get("remotion_scaffold_present"))
    remotion_dependencies_declared = bool(clip_info.get("remotion_dependencies_declared"))
    remotion_dependencies_installed = bool(clip_info.get("remotion_dependencies_installed"))
    remotion_render_enabled = bool(clip_info.get("remotion_render_enabled"))
    remotion_overlay_file_path = str(clip_info.get("remotion_overlay_file_path") or "").strip() or None
    remotion_render_command_used = str(clip_info.get("remotion_render_command_used") or "").strip() or None
    remotion_overlay_composed = bool(clip_info.get("remotion_overlay_composed"))
    remotion_overlay_composed_path = str(clip_info.get("remotion_overlay_composed_path") or "").strip() or None
    remotion_overlay_composition_fallback_reason = str(
        clip_info.get("remotion_overlay_composition_fallback_reason") or ""
    ).strip() or None
    has_3d_object_plan = bool(clip_info.get("has_3d_object_plan"))
    object_3d_count = int(clip_info.get("object_3d_count") or 0)
    ass_caption_plan_path = str(clip_info.get("ass_caption_plan_path") or "").strip() or None
    ass_caption_file_path = str(clip_info.get("ass_caption_file_path") or "").strip() or None
    caption_backend = str(clip_info.get("caption_backend") or "").strip().lower() or None
    has_ass_captions = bool(clip_info.get("has_ass_captions") or ass_caption_file_path)
    ass_caption_events_count = int(clip_info.get("ass_caption_events_count") or 0)
    ass_caption_highlights_count = int(clip_info.get("ass_caption_highlights_count") or 0)
    caption_fallback_reason = str(clip_info.get("caption_fallback_reason") or "").strip() or None
    overlay_backend = str(clip_info.get("overlay_backend") or "").strip().lower()
    if not overlay_backend:
        if remotion_overlay_status == "rendered" and remotion_overlay_file_path:
            overlay_backend = "remotion"
        elif has_ass_captions:
            overlay_backend = "ffmpeg_ass"
        elif ass_caption_plan_path or ass_caption_file_path:
            overlay_backend = "legacy_with_ass_artifact"
        else:
            overlay_backend = "none"
    visual_overlay_backend_applied = str(
        clip_info.get("visual_overlay_backend_applied")
        or overlay_backend
        or "none"
    ).strip().lower()
    segment_value_type = (
        str(clip_info.get("segment_value_type") or segment.get("segment_value_type") or segment.get("value_type") or "")
        or None
    )
    predicted_first3_strength = _as_float(clip_info.get("predicted_first3_strength"))
    if predicted_first3_strength is None:
        predicted_first3_strength = _as_float(_as_dict(clip_info.get("hook_plan")).get("hook_first3_score"))
    trim_to_hook_candidate = bool(
        clip_info.get("trim_to_hook_candidate")
        or segment.get("hook_start_adjusted")
        or _as_dict(clip_info.get("hook_plan")).get("hook_start_adjusted")
    )
    hook_start_offset = _as_float(clip_info.get("hook_start_offset"))
    if hook_start_offset is None:
        hook_start_offset = _as_float(_as_dict(clip_info.get("hook_plan")).get("hook_motion_start_s"))
    sfx_intent = str(
        clip_info.get("sfx_intent")
        or sfx_meta.get("sfx_intent")
        or sfx_meta.get("intent")
        or sfx_meta.get("editorial_intent")
        or ""
    ).strip() or None
    sfx_skip_reason = str(
        clip_info.get("sfx_skip_reason")
        or sfx_meta.get("skip_reason")
        or sfx_meta.get("sfx_warning")
        or sfx_meta.get("sfx_status")
        or ""
    ).strip() or None
    bgm_evidence = bool(
        clip_info.get("bgm_evidence")
        or music_meta.get("music_applied")
        or music_meta.get("music_track")
        or music_meta.get("bgm_asset_path")
        or music_meta.get("final_output_uses_bgm")
    )
    broll_confidence = _as_float(clip_info.get("broll_confidence"))
    if broll_confidence is None:
        broll_items_for_conf = _safe_list(clip_info.get("editorial_broll"))
        _cand_conf: List[float] = []
        for item in broll_items_for_conf:
            if not isinstance(item, dict):
                continue
            for key in ("category_confidence", "confidence", "broll_relevance_score", "asset_score"):
                conf = _normalize_confidence_0_1(item.get(key))
                if conf is not None:
                    _cand_conf.append(conf)
                    break
        if _cand_conf:
            broll_confidence = max(_cand_conf)
    one_strong_thing_conflicts = _safe_list(
        clip_info.get("one_strong_thing_conflicts")
        or _as_dict(clip_info.get("timeline_plan")).get("one_strong_thing_conflicts")
        or _as_dict(visual_fx_meta.get("visual_priority_guard")).get("conflicts")
    )
    disfluency_actions_count = int(
        clip_info.get("disfluency_actions_count")
        or _as_dict(clip_info.get("disfluency_plan")).get("actions_count")
        or 0
    )
    disfluency_high_severity_unhandled_count = int(
        clip_info.get("high_severity_unhandled_count")
        or _as_dict(clip_info.get("disfluency_plan")).get("high_severity_unhandled_count")
        or 0
    )

    if premium_layers_field_present and premium_layers_applied_raw is not None:
        has_bgm = ("bgm" in premium_layers_applied) or independent_bgm
        has_sfx = ("sfx" in premium_layers_applied) or independent_sfx
        has_broll = ("broll" in premium_layers_applied) or independent_broll
        has_motion_or_vfx = (
            ("vfx" in premium_layers_applied)
            or ("motion_pack" in premium_layers_applied)
            or independent_vfx
        )
        has_rhythm_cleanup = ("rhythm" in premium_layers_applied) or independent_rhythm
        has_captions = ("captions" in premium_layers_applied) or independent_captions
        has_branding = ("branding" in premium_layers_applied) or independent_branding
        has_audio_mastering = ("audio_mastering" in premium_layers_applied) or independent_audio_mastering
    else:
        has_bgm = independent_bgm or bool(music_meta.get("music_applied")) or markers["bgm"]
        has_sfx = independent_sfx or bool(sfx_meta.get("sfx_applied")) or markers["sfx"]
        has_broll = independent_broll or markers["broll"]
        has_motion_or_vfx = independent_vfx or bool(visual_fx_meta.get("visual_effects_applied")) or markers["motion_or_vfx"]
        has_rhythm_cleanup = independent_rhythm or markers["rhythm"]
        has_captions = independent_captions or markers["captions"]
        has_branding = independent_branding or markers["branding"]
        has_audio_mastering = independent_audio_mastering or markers["audio_mastering"]

    technical_valid = bool(
        exists
        and file_size > 0
        and has_video
        and has_audio
        and width > 0
        and height > 0
        and duration > 0.0
    )
    qa_passed = bool(
        clip_info.get("qa_passed")
        or _as_dict(clip_info.get("quality_assurance")).get("passed")
        or _as_dict(clip_info.get("quality_gate")).get("passed")
    )

    contract = {
        "task_id": task_id,
        "clip_order": int(clip_order),
        "start_time": segment.get("start_time"),
        "end_time": segment.get("end_time"),
        "final_path": str(final_path),
        "public_url": str(clip_info.get("video_url") or ""),
        "duration": duration,
        "width": width,
        "height": height,
        "has_video": has_video,
        "has_audio": has_audio,
        "file_size": file_size,
        "render_success": exists and file_size > 0,
        "technical_valid": technical_valid,
        "has_captions": has_captions,
        "has_branding": has_branding,
        "has_bgm": has_bgm,
        "has_sfx": has_sfx,
        "has_broll": has_broll,
        "has_motion_or_vfx": has_motion_or_vfx,
        "has_transition": has_transition,
        "has_semantic_object": has_semantic_object,
        "has_motion_reveal": has_motion_reveal,
        "visual_clutter_score": visual_clutter_score,
        "visual_coherence_score": visual_coherence_score,
        "visual_style": visual_style,
        "has_disfluency_cleanup": has_disfluency_cleanup,
        "disfluency_cleanup_count": disfluency_cleanup_count,
        "preserved_emphasis_pause_count": preserved_emphasis_pause_count,
        "covered_disfluency_count": covered_disfluency_count,
        "disfluency_edit_quality": disfluency_edit_quality,
        "visual_editing_quality": visual_editing_quality,
        "has_clean_captions": has_clean_captions,
        "caption_disfluency_cleanup": caption_disfluency_cleanup,
        "caption_readability_score": caption_readability_score,
        "caption_style": caption_style,
        "highlight_count": highlight_count,
        "overlay_coherence_score": overlay_coherence_score,
        "overlay_duplication_warning": overlay_duplication_warning,
        "safe_area_conflicts": safe_area_conflicts,
        "timeline_plan_path": timeline_plan_path,
        "disfluency_plan_path": disfluency_plan_path,
        "selection_contract_path": selection_contract_path,
        "overlay_backend": overlay_backend,
        "remotion_scene_plan_path": remotion_scene_plan_path,
        "remotion_scene_events_count": remotion_scene_events_count,
        "remotion_overlay_status": remotion_overlay_status,
        "remotion_installed": remotion_installed,
        "remotion_scaffold_present": remotion_scaffold_present,
        "remotion_dependencies_declared": remotion_dependencies_declared,
        "remotion_dependencies_installed": remotion_dependencies_installed,
        "remotion_render_enabled": remotion_render_enabled,
        "remotion_overlay_file_path": remotion_overlay_file_path,
        "remotion_render_command_used": remotion_render_command_used,
        "remotion_overlay_composed": remotion_overlay_composed,
        "remotion_overlay_composed_path": remotion_overlay_composed_path,
        "remotion_overlay_composition_fallback_reason": remotion_overlay_composition_fallback_reason,
        "has_3d_object_plan": has_3d_object_plan,
        "object_3d_count": object_3d_count,
        "visual_overlay_backend_applied": visual_overlay_backend_applied,
        "ass_caption_plan_path": ass_caption_plan_path,
        "ass_caption_file_path": ass_caption_file_path,
        "caption_backend": caption_backend,
        "has_ass_captions": has_ass_captions,
        "ass_caption_events_count": ass_caption_events_count,
        "ass_caption_highlights_count": ass_caption_highlights_count,
        "caption_fallback_reason": caption_fallback_reason,
        "segment_value_type": segment_value_type,
        "predicted_first3_strength": predicted_first3_strength,
        "trim_to_hook_candidate": trim_to_hook_candidate,
        "hook_start_offset": hook_start_offset,
        "sfx_intent": sfx_intent,
        "sfx_skip_reason": sfx_skip_reason,
        "bgm_evidence": bgm_evidence,
        "broll_confidence": broll_confidence,
        "one_strong_thing_conflicts": one_strong_thing_conflicts,
        "disfluency_actions_count": disfluency_actions_count,
        "disfluency_high_severity_unhandled_count": disfluency_high_severity_unhandled_count,
        "has_rhythm_cleanup": has_rhythm_cleanup,
        "has_audio_mastering": has_audio_mastering,
        "qa_passed": qa_passed,
        "evidence_sources": {
            "premium_layers_field_present": premium_layers_field_present,
            "premium_layers_applied": premium_layers_applied,
            "final_contract_checks": final_contract_checks,
            "final_output_flags": {
                "music": bool(clip_info.get("final_output_uses_music")),
                "sfx": bool(clip_info.get("final_output_uses_sfx")),
                "vfx": bool(clip_info.get("final_output_uses_vfx")),
            },
            "filename_markers": markers,
        },
        "rejection_reasons": [],
    }
    logger.info(
        "FINAL_CONTRACT_PLAN_ARTIFACTS timeline=%s disfluency=%s overlay_backend=%s",
        str(contract.get("timeline_plan_path") or ""),
        str(contract.get("disfluency_plan_path") or ""),
        str(contract.get("overlay_backend") or ""),
    )
    logger.info(
        "FINAL_CONTRACT_ASS_CAPTIONS backend=%s ass_file=%s fallback_reason=%s",
        str(contract.get("caption_backend") or ""),
        str(contract.get("ass_caption_file_path") or ""),
        str(contract.get("caption_fallback_reason") or ""),
    )
    logger.info(
        "FINAL_CONTRACT_REMOTION_SCENE_PLAN path=%s status=%s events=%s",
        str(contract.get("remotion_scene_plan_path") or ""),
        str(contract.get("remotion_overlay_status") or ""),
        str(contract.get("remotion_scene_events_count") or 0),
    )

    if not technical_valid:
        contract["rejection_reasons"].append("technical_invalid_render_output")

    _broll_metadata_ref = (
        _as_dict(clip_info.get("broll_metadata"))
        or _as_dict(final_contract_meta.get("broll_metadata"))
    )
    broll_items = [
        item
        for item in _as_list(
            _broll_metadata_ref.get("items")
            or clip_info.get("broll_items")
            or segment.get("broll_items")
            or clip_info.get("editorial_broll")
            or _as_dict(clip_info.get("broll_editorial_decision")).get("items")
            or final_contract_meta.get("broll_items")
        )
        if isinstance(item, dict)
    ]
    if broll_items:
        logger.info(
            "VPI_FINAL_CONTRACT_BROLL_ITEMS_REHYDRATED task_id=%s clip_order=%d count=%d",
            task_id,
            clip_order,
            len(broll_items),
        )
    else:
        logger.info(
            "VPI_FINAL_CONTRACT_BROLL_ITEMS_SAFE_DEFAULTED task_id=%s clip_order=%d reason=no_broll_items_available",
            task_id,
            clip_order,
        )

    audio_qc = _as_dict(output_qc.get("audio_qc"))

    try:
        _build_final_mp4_contract = None
        from .vpi_publishable_gate import build_final_mp4_contract as _build_final_mp4_contract

        _mp4_contract_input = dict(clip_info)
        _mp4_contract_input.update({
            "path": str(final_path),
            "duration": duration,
            "final_rendered_contract": contract,
            "final_contract": contract,
        })
        hook_plan = _as_dict(clip_info.get("hook_plan")) or _as_dict(_as_dict(clip_info.get("editing_plan")).get("hook_plan"))
        _final_mp4_contract = _build_final_mp4_contract(
            final_output_path=final_path,
            expected_duration_s=duration,
            clip_info=_mp4_contract_input,
            final_qc_report=_as_dict(clip_info.get("final_qc")),
            production_safe=bool(os.environ.get("VPI_PRODUCTION_SAFE_EDIT", "").strip().lower() in {"1", "true", "yes", "on"}),
            captions_metadata=_as_dict(clip_info.get("caption_visual_support")) or _as_dict(clip_info.get("caption_visual_support_plan")),
            bgm_metadata=music_meta,
            sfx_metadata=sfx_meta,
            hook_metadata=hook_plan,
            rhythm_metadata=silence_meta,
            visual_layer_budget_metadata=_as_dict(_as_dict(clip_info.get("editing_plan")).get("visual_layer_budget")),
            visual_reinforcement_metadata=_as_dict(clip_info.get("visual_reinforcement")),
            broll_metadata={
                "items": broll_items,
                "broll_editorial_decision": clip_info.get("broll_editorial_decision") or {},
                "broll_applied": bool(clip_info.get("broll_applied")),
                "broll_rendered": bool(clip_info.get("broll_rendered")),
                "broll_verified": bool(clip_info.get("broll_verified")),
                "broll_skip_reason": str(clip_info.get("broll_skip_reason") or ""),
                "broll_budget_allowed": bool(clip_info.get("broll_budget_allowed", True)),
                "broll_asset_id": str(clip_info.get("broll_asset_id") or ""),
                "broll_asset_source": str(clip_info.get("broll_asset_source") or ""),
            },
            transitions_metadata=transition_meta,
            audio_mastering_metadata=audio_qc,
            task_id=task_id,
            clip_order=clip_order,
        )
        contract["final_mp4_contract"] = _final_mp4_contract
        contract["final_truth_source"] = str(_final_mp4_contract.get("final_truth_source") or "final_mp4_contract")
        contract["final_output_verified"] = bool(_final_mp4_contract.get("final_output_verified"))
        contract["final_publishable"] = bool(_final_mp4_contract.get("final_publishable"))
        contract["final_needs_review"] = bool(_final_mp4_contract.get("final_needs_review"))
        contract["final_contract_ok"] = bool(_final_mp4_contract.get("final_publishable"))
        contract["final_blocking_reasons"] = list(_final_mp4_contract.get("final_blocking_reasons") or [])
        contract["final_warning_reasons"] = list(_final_mp4_contract.get("final_warning_reasons") or [])
        contract["metadata_consistency_ok"] = bool(_final_mp4_contract.get("metadata_consistency_ok"))
        contract["metadata_consistency_errors"] = list(_final_mp4_contract.get("metadata_consistency_errors") or [])
        contract["metadata_consistency_warnings"] = list(_final_mp4_contract.get("metadata_consistency_warnings") or [])
        contract["phase_consistency"] = dict(_final_mp4_contract.get("phase_consistency") or {})
        contract["production_safe_policy"] = dict(_final_mp4_contract.get("production_safe_policy") or {})
        contract["production_safe_policy_version"] = str(_final_mp4_contract.get("production_safe_policy_version") or "a4")
        contract["production_safe_mode_active"] = bool(_final_mp4_contract.get("production_safe_mode_active"))
        contract["production_safe_external_disabled"] = bool(_final_mp4_contract.get("production_safe_external_disabled"))
        contract["production_safe_legacy_disabled"] = bool(_final_mp4_contract.get("production_safe_legacy_disabled"))
        contract["production_safe_routes_allowed"] = list(_final_mp4_contract.get("production_safe_routes_allowed") or [])
        contract["production_safe_routes_blocked"] = list(_final_mp4_contract.get("production_safe_routes_blocked") or [])
        contract["vpi_daily_mode_enabled"] = bool(_final_mp4_contract.get("vpi_daily_mode_enabled"))
        contract["daily_mode_version"] = str(_final_mp4_contract.get("daily_mode_version") or "a1")
        contract["daily_mode_policy"] = dict(_final_mp4_contract.get("daily_mode_policy") or {})
        contract["daily_mode_outputs_enabled"] = bool(_final_mp4_contract.get("daily_mode_outputs_enabled"))
        contract["daily_mode_conflicts_resolved"] = list(_final_mp4_contract.get("daily_mode_conflicts_resolved") or [])
        contract["daily_mode_unsafe_override_used"] = bool(_final_mp4_contract.get("daily_mode_unsafe_override_used"))
        contract["filename_contract_warning"] = str(clip_info.get("filename_contract_warning") or "")
        contract["route_registry"] = _as_dict(_final_mp4_contract.get("route_registry")) or _as_dict(clip_info.get("route_registry"))
        contract["route_registry_version"] = str(_as_dict(contract.get("route_registry")).get("route_registry_version") or "a2")
        contract["production_safe_compliant"] = bool(_as_dict(contract.get("route_registry")).get("production_safe_compliant", True))
        contract["production_safe_routes_blocked"] = list(_safe_list(_as_dict(contract.get("route_registry")).get("production_safe_routes_blocked")))
        contract["legacy_routes_blocked"] = list(_safe_list(_as_dict(contract.get("route_registry")).get("legacy_routes_blocked")))
        contract["external_routes_blocked"] = list(_safe_list(_as_dict(contract.get("route_registry")).get("external_routes_blocked")))
        contract["fallback_routes_used"] = list(_safe_list(_as_dict(contract.get("route_registry")).get("fallback_routes_used")))
        contract["primary_routes_used"] = list(_safe_list(_as_dict(contract.get("route_registry")).get("primary_routes_used")))
    except Exception as exc:
        logger.warning(
            "FINAL_MP4_CONTRACT_BUILD_FAILED task_id=%s clip_order=%d error=%s",
            task_id,
            clip_order,
            exc,
        )
    return contract


def _normalize_json_compatible(value: Any, converted_types: Dict[str, int]) -> Any:
    """
    Recursively normalize values to JSON-compatible primitives.

    Preserves metadata structure while converting known non-JSON types
    (notably pathlib paths) to stable string representations.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        type_name = type(value).__name__
        converted_types[type_name] = converted_types.get(type_name, 0) + 1
        return str(value)

    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, raw_val in value.items():
            normalized_key = key if isinstance(key, str) else str(key)
            if normalized_key != key:
                key_type_name = f"dict_key:{type(key).__name__}"
                converted_types[key_type_name] = converted_types.get(key_type_name, 0) + 1
            normalized[normalized_key] = _normalize_json_compatible(raw_val, converted_types)
        return normalized

    if isinstance(value, (list, tuple, set)):
        if not isinstance(value, list):
            type_name = type(value).__name__
            converted_types[type_name] = converted_types.get(type_name, 0) + 1
        return [_normalize_json_compatible(item, converted_types) for item in value]

    try:
        json.dumps(value)
        return value
    except TypeError:
        type_name = type(value).__name__
        converted_types[type_name] = converted_types.get(type_name, 0) + 1
        return str(value)


def _normalize_json_for_context(task_id: str, context: str, payload: Any) -> Any:
    converted_types: Dict[str, int] = {}
    normalized = _normalize_json_compatible(payload, converted_types)
    if converted_types:
        logger.info(
            "JSON_SAFE_NORMALIZED_CONTEXT task_id=%s context=%s converted_types=%s",
            task_id,
            context,
            converted_types,
        )
    return normalized


def _hash_text_sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8", errors="ignore")).hexdigest()


def _hash_file_head_sha256(path: Path, max_bytes: int = 1_048_576) -> str:
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read(max_bytes)).hexdigest()
    except Exception:
        return ""


def _parse_json_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _is_task_scoped_output(path: Path, task_id: str) -> bool:
    if not path:
        return False
    path_str = str(path)
    task_id_clean = (task_id or "").strip()
    if not task_id_clean:
        return False
    if f"/{task_id_clean}/" in path_str:
        return True
    if task_id_clean in path.name:
        return True
    return False


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


_SETUP_PREFIXES = (
    "hola", "vale", "ok", "okay", "papa", "papá", "ya estamos", "empezamos",
    "a ver", "bueno", "claro", "mira",
)
_CONTENT_TERMS = (
    "seguro", "decesos", "salud", "cobertura", "familia", "proteccion", "protección",
    "poliza", "póliza", "riesgo", "prima", "precio", "descuento", "autonomo", "autónomo",
)
_CONNECTOR_ENDINGS = (
    "que", "y", "pero", "porque", "si", "cuando", "donde", "aunque", "para", "con",
)
_PRE_RENDER_HOOK_TERMS = (
    "ojo",
    "cuidado",
    "importante",
    "revisa",
    "evita",
    "descubre",
    "protege",
    "protegido",
    "familia",
    "seguro",
    "riesgo",
    "tranquilidad",
    "whatsapp",
    "escríbenos",
    "escribenos",
)
_PRE_RENDER_FILLER_PREFIXES = (
    "hola",
    "vale",
    "ok",
    "okay",
    "papá",
    "papa",
    "ya estamos",
    "a ver",
    "bueno",
    "mira",
)
_EDITING_PLAN_REQUIRED_FEATURES = [
    "complete_idea",
    "no_mid_sentence_cut",
    "hook_or_overlay_plan",
    "visual_support_plan",
    "bgm_plan_or_track",
    "rhythm_plan_or_explicit_reason",
    "retention_edit_plan",
]


def _normalize_text_loose(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_sentence_end(text: str) -> bool:
    stripped = (text or "").strip()
    return stripped.endswith((".", "!", "?", "…"))


def _is_setup_text(text: str) -> bool:
    normalized = _normalize_text_loose(text)
    return any(normalized.startswith(prefix) for prefix in _SETUP_PREFIXES)


def _has_content_terms(text: str) -> bool:
    normalized = _normalize_text_loose(text)
    return any(term in normalized for term in _CONTENT_TERMS)


def _parse_timestamped_transcript_lines(transcript: str) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    pattern = re.compile(r"\[(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(\d{2}:\d{2}(?::\d{2})?)\]\s*([^\[]+)")

    for match in pattern.finditer(transcript or ""):
        text = (match.group(3) or "").strip()
        if not text:
            continue
        start = parse_timestamp_to_seconds(match.group(1))
        end = parse_timestamp_to_seconds(match.group(2))
        if end <= start:
            continue
        lines.append({"start": start, "end": end, "text": text})
    return lines


def _format_mmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def _format_mmss_precise(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    whole = int(seconds)
    frac = seconds - whole
    if frac < 0.005:
        return _format_mmss(seconds)
    return f"{whole // 60:02d}:{(whole % 60) + frac:05.2f}"


def _segment_duration_seconds(segment: Dict[str, Any]) -> float:
    start_s = parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
    end_s = parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
    return max(0.0, end_s - start_s)


def _detect_verbal_hook(text: str) -> Tuple[bool, List[str]]:
    normalized = _normalize_text_loose(text)
    if not normalized:
        return False, []
    words = [w for w in normalized.split(" ") if w]
    first_window = " ".join(words[:16])
    hits = [term for term in _PRE_RENDER_HOOK_TERMS if term in first_window]
    question_or_tension = ("?" in text) or any(term in first_window for term in ("si pasa", "y si", "nadie te cuenta"))
    strong = bool(hits) or question_or_tension
    return strong, hits


def _derive_semantic_card_concept(text: str, segment: Dict[str, Any]) -> str:
    blob = _normalize_text_loose(
        " ".join(
            [
                text or "",
                str(segment.get("editorial_type") or ""),
                " ".join(str(x or "") for x in (segment.get("matched_patterns") or [])),
                str(segment.get("clean_take_topic") or ""),
            ]
        )
    )
    concept_keywords = [
        ("salud", ("salud", "medic", "hospital", "consulta")),
        ("proteccion", ("proteccion", "proteg", "cobertura", "familia")),
        ("decesos", ("decesos", "fallecimiento", "duelo")),
        ("revision", ("revisa", "revisión", "condiciones", "antes de contratar")),
        ("cobertura", ("cobertura", "poliza", "póliza", "cubre")),
        ("riesgo", ("riesgo", "ojo", "cuidado", "problema", "sorpresa")),
        ("ahorro", ("ahorro", "precio", "prima", "descuento", "coste")),
    ]
    for concept, needles in concept_keywords:
        if any(needle in blob for needle in needles):
            return concept
    return "proteccion"


def _build_pre_render_hook_plan(segment: Dict[str, Any], verbal_hook: bool) -> Dict[str, Any]:
    hook_analysis = segment.get("hook_analysis") or {}
    first3_score = int(
        hook_analysis.get("hook_density", 0) * 10
        if isinstance(hook_analysis.get("hook_density"), (int, float))
        else 0
    )
    if verbal_hook:
        first3_score = max(first3_score, 7)
    hook_type = str(segment.get("hook_type") or hook_analysis.get("primary_hook_type") or "explanation_hook")
    return {
        "enabled": bool(verbal_hook or first3_score >= 5),
        "hook_type": hook_type,
        "hook_first3_score": max(0, min(10, first3_score)),
        "hook_first3_perceptible": bool(verbal_hook),
        "hook_fit_acceptable": bool(verbal_hook or first3_score >= 5),
    }


def _derive_hook_card_text(segment: Dict[str, Any]) -> str:
    text = _normalize_text_loose(str(segment.get("text") or ""))
    editorial = _normalize_text_loose(str(segment.get("editorial_type") or ""))
    matched = _normalize_text_loose(" ".join(str(x or "") for x in (segment.get("matched_patterns") or [])))
    blob = f"{text} {editorial} {matched}".strip()
    if any(token in blob for token in ("cubre", "cobertura", "poliza", "póliza", "seguro")):
        return "No todos los seguros cubren igual"
    if any(token in blob for token in ("contratar", "firmar", "condiciones", "revisa")):
        return "Revisa esto antes de contratar"
    if any(token in blob for token in ("familia", "tranquilidad", "proteccion", "protección")):
        return "La tranquilidad también se planifica"
    return "Esto conviene revisarlo antes"


def _attach_contract_result_to_segment(segment: Dict[str, Any], contract_result: Dict[str, Any]) -> None:
    """Persist the FULL normalized contract result directly on the segment object.

    This ensures the render handoff (Fix 1) can read back the authoritative
    contract metadata instead of relying on the truncated contract_result
    in candidate_reports (which only has scores + would_runtime_reject).
    """
    from .vpi_editorial_contract import normalize_contract_result as _normalize_contract
    normalized = _normalize_contract(contract_result)
    segment["contract_result"] = normalized
    segment["pre_render_contract_result"] = normalized
    segment["pre_render_approved"] = bool(normalized.get("approved", False))
    segment["contract_approved"] = bool(normalized.get("approved", False))
    segment["contract_would_runtime_reject"] = bool(normalized.get("would_runtime_reject", True))
    segment["hook_support"] = dict(normalized.get("hook_support") or {})
    segment["visual_support"] = dict(normalized.get("visual_support") or {})
    segment["complete_idea_pass"] = bool(normalized.get("complete_idea_pass", False))


def _get_segment_contract_result(segment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Retrieve the persisted contract result from a segment, checking multiple locations.

    Checks in order:
    1. segment["contract_result"]
    2. segment["pre_render_contract_result"]
    3. segment["metadata"]["contract_result"]
    4. segment["metadata"]["pre_render_contract_result"]

    Returns None if no valid contract result is found.
    """
    for key in ("contract_result", "pre_render_contract_result"):
        val = segment.get(key)
        if isinstance(val, dict) and val.get("approved") is not None:
            return val
    metadata = segment.get("metadata") or {}
    for key in ("contract_result", "pre_render_contract_result"):
        val = metadata.get(key)
        if isinstance(val, dict) and val.get("approved") is not None:
            return val
    return None


def run_pre_render_editorial_gate(
    *,
    task_id: str,
    segments: List[Dict[str, Any]],
    requested_clips: int,
    include_broll: bool,
    bgm_tracks_available: int,
) -> Dict[str, Any]:
    """
    Pre-render editorial gate that delegates to the shared evaluate_editorial_contract_batch().
    
    This replaces the old inline logic with the centralised contract evaluator from
    vpi_editorial_contract.py, which provides:
      - Repair-or-reject ladder (extend_boundary, hook_card, semantic_card)
      - Renderability score
      - Editorial policy profiles
      - Penalty/threshold logic
      - Decision snapshots
    """
    from .vpi_editorial_contract import (
        evaluate_editorial_contract_batch,
        build_editorial_snapshots,
        DEFAULT_PROFILE,
    )
    from .vpi_asset_library_service import build_asset_index
    from .vpi_music_service import discover_music_tracks

    approved_segments: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    candidate_reports: List[Dict[str, Any]] = []
    asset_index = build_asset_index()
    music_tracks = discover_music_tracks()
    _resolved_bgm_tracks_available = int(len(music_tracks))

    # Delegate all editorial evaluation to the shared contract evaluator
    contract_results = evaluate_editorial_contract_batch(
        segments,
        task_id=task_id,
        profile=DEFAULT_PROFILE,
        include_broll=include_broll,
        bgm_tracks_available=_resolved_bgm_tracks_available,
        asset_index=asset_index,
        music_tracks=music_tracks,
    )

    for idx, segment in enumerate(segments):
        try:
            contract = contract_results[idx] if idx < len(contract_results) else {}
            approved = bool(contract.get("approved", False))
            reject_reasons = list(contract.get("reject_reasons") or [])
            repair_actions = list(contract.get("repair_actions") or [])
            metadata_to_apply = dict(contract.get("metadata_to_apply") or {})
            pre_render_edit_plan = dict(contract.get("pre_render_edit_plan") or {})
            pre_qc = dict(contract.get("pre_qc") or {})
            would_runtime_reject = bool(contract.get("would_runtime_reject", False))

            # Build pre_qc dict matching the expected format
            severity = dict(contract.get("severity") or {})
            pre_qc = {
                "result": "pass" if approved else "fail",
                "candidate_index": idx + 1,
                "complete_idea": bool(contract.get("complete_idea_pass", False)),
                "no_mid_sentence_cut": bool(pre_render_edit_plan.get("semantic_boundary", {}).get("no_mid_sentence_cut", False)),
                "verbal_hook_detected": bool(contract.get("hook_support", {}).get("verbal_hook_detected", False)),
                "verbal_hook_hits": list(contract.get("hook_support", {}).get("hook_hits", [])),
                "hook_overlay_planned": bool(contract.get("hook_support", {}).get("hook_overlay_planned", False)),
                "visual_support_planned": bool(contract.get("visual_support", {}).get("planned", False)),
                "visual_support_executable": bool(contract.get("visual_support", {}).get("executable", False)),
                "broll_planned": bool(contract.get("visual_support", {}).get("type", "") == "broll"),
                "motion_overlay_planned": bool(contract.get("visual_support", {}).get("type", "") == "motion_overlay"),
                "runtime_complete_idea_score_eval": float(contract.get("complete_idea_score", 0.0)),
                "bgm_tracks_available": int(_resolved_bgm_tracks_available),
                "bgm_planned": bool(contract.get("bgm_support", {}).get("planned", False)),
                "bgm_selected_track": str(contract.get("bgm_support", {}).get("track", "")),
                "rhythm_cleanup_planned": bool(contract.get("rhythm_cleanup", {}).get("planned", False)),
                "rhythm_no_cleanup_reason": str(contract.get("rhythm_cleanup", {}).get("skip_reason", "")),
                "retention_plan_required_features": list(contract.get("retention_plan", {}).get("required_features", [])),
                "retention_plan_score": int(contract.get("retention_plan", {}).get("score", 0)),
                "retention_plan_missing_layers": list(contract.get("retention_plan", {}).get("missing_layers", [])),
                "retention_plan_warnings": list(contract.get("retention_plan", {}).get("warnings", [])),
                "pre_render_edit_plan": pre_render_edit_plan,
                "bts_contamination_ratio": float(contract.get("bts_penalty", 0.0)),
                "failure_reasons": reject_reasons,
                "would_runtime_reject": would_runtime_reject,
                "would_runtime_reject_reason": str(contract.get("would_runtime_reject_reason", "none")),
                "visual_support_type": str(contract.get("visual_support", {}).get("type", "none")),
                "overlay_candidate": dict(contract.get("overlay_candidate", {})),
                # Flexibility Engine fields
                "publishing_intent": str(contract.get("publishing_intent", "unknown")),
                "commercial_usefulness_score": float(contract.get("commercial_usefulness_score", 0.0)),
                "cta_suggestion": str(contract.get("cta_suggestion", "")),
                "brand_voice_applied": bool(contract.get("brand_voice_applied", False)),
                "severity_max": str(severity.get("max_severity", "INFO")),
                "severity_blockers": list(severity.get("blockers", [])),
                "severity_repairable": list(severity.get("repairable", [])),
                "severity_penalties": list(severity.get("penalties", [])),
                "diversity_key": str(contract.get("diversity_key", "")),
                "contract_result": {
                    "complete_idea_score": float(contract.get("complete_idea_score", 0.0)),
                    "renderability_score": float(contract.get("renderability_score", 0.0)),
                    "editorial_value_score": float(contract.get("editorial_value_score", 0.0)),
                    "brand_fit_score": float(contract.get("brand_fit_score", 0.0)),
                    "final_contract_score": float(contract.get("final_contract_score", 0.0)),
                    "would_runtime_reject": would_runtime_reject,
                    "repair_actions": repair_actions,
                    "metadata_to_apply": metadata_to_apply,
                    # Flexibility Engine fields
                    "publishing_intent": str(contract.get("publishing_intent", "unknown")),
                    "commercial_usefulness_score": float(contract.get("commercial_usefulness_score", 0.0)),
                    "cta_suggestion": str(contract.get("cta_suggestion", "")),
                    "brand_voice_applied": bool(contract.get("brand_voice_applied", False)),
                    "severity_max": str(severity.get("max_severity", "INFO")),
                    "severity_blockers": list(severity.get("blockers", [])),
                    "severity_repairable": list(severity.get("repairable", [])),
                    "severity_penalties": list(severity.get("penalties", [])),
                    "diversity_key": str(contract.get("diversity_key", "")),
                },
            }
            segment["pre_render_qc"] = pre_qc
            segment["pre_render_approved"] = bool(approved)
            segment["pre_render_failure_reasons"] = list(reject_reasons)
            segment["editing_plan_required_features"] = list(contract.get("retention_plan", {}).get("required_features", []))
            segment["pre_render_edit_plan"] = pre_render_edit_plan
            # Persist metadata_to_apply on the segment for downstream rendering
            if metadata_to_apply:
                segment["metadata_to_apply"] = metadata_to_apply

            # ── Persist FULL normalized contract result on segment ──────────────
            # The contract dict has approved, hook_support, visual_support,
            # complete_idea_pass, would_runtime_reject, etc. at the top level.
            # We persist the FULL normalized result directly on the segment so
            # that the render handoff (Fix 1) can read it back authoritatively
            # instead of relying on the truncated contract_result in candidate_reports.
            _attach_contract_result_to_segment(segment, contract)

            logger.info(
                "PRE_RENDER_QC task_id=%s result=%s candidate_index=%d reasons=%s",
                task_id,
                pre_qc["result"],
                idx + 1,
                reject_reasons if reject_reasons else [],
            )
            if approved:
                logger.info(
                    "PRE_RENDER_QC task_id=%s result=pass candidate_index=%d hook_exec=%s visual_exec=%s complete_idea_pass=%s",
                    task_id,
                    idx + 1,
                    str(bool(contract.get("hook_support", {}).get("executable", False))).lower(),
                    str(bool(contract.get("visual_support", {}).get("executable", False))).lower(),
                    str(bool(contract.get("complete_idea_pass", False))).lower(),
                )

            if not approved:
                rejected.append(
                    {
                        "clip_index": idx + 1,
                        "start_time": segment.get("start_time"),
                        "end_time": segment.get("end_time"),
                        "reason": "fast_fail_editing_zero:" + ",".join(reject_reasons),
                        "stage": "pre_render_qc_failed",
                    }
                )
            else:
                approved_segments.append(segment)
            candidate_reports.append(
                {
                    "candidate_index": idx + 1,
                    "start_time": segment.get("start_time"),
                    "end_time": segment.get("end_time"),
                    "approved": bool(approved),
                    "reject_reasons": list(reject_reasons),
                    "edit_plan_summary": pre_render_edit_plan,
                    "contract_result": {
                        "complete_idea_score": float(contract.get("complete_idea_score", 0.0)),
                        "renderability_score": float(contract.get("renderability_score", 0.0)),
                        "editorial_value_score": float(contract.get("editorial_value_score", 0.0)),
                        "brand_fit_score": float(contract.get("brand_fit_score", 0.0)),
                        "final_contract_score": float(contract.get("final_contract_score", 0.0)),
                        "would_runtime_reject": would_runtime_reject,
                        "repair_actions": repair_actions,
                        "metadata_to_apply": metadata_to_apply,
                        # Flexibility Engine fields
                        "publishing_intent": str(contract.get("publishing_intent", "unknown")),
                        "commercial_usefulness_score": float(contract.get("commercial_usefulness_score", 0.0)),
                        "cta_suggestion": str(contract.get("cta_suggestion", "")),
                        "brand_voice_applied": bool(contract.get("brand_voice_applied", False)),
                        "severity_max": str(severity.get("max_severity", "INFO")),
                        "severity_blockers": list(severity.get("blockers", [])),
                        "severity_repairable": list(severity.get("repairable", [])),
                        "severity_penalties": list(severity.get("penalties", [])),
                        "diversity_key": str(contract.get("diversity_key", "")),
                    },
                }
            )

        except Exception as seg_exc:
            logger.exception(
                "PRE_RENDER_QC_ERROR task_id=%s candidate_index=%d reason=%s",
                task_id,
                idx + 1,
                f"{type(seg_exc).__name__}:{seg_exc}",
            )
            rejected.append(
                {
                    "clip_index": idx + 1,
                    "start_time": segment.get("start_time"),
                    "end_time": segment.get("end_time"),
                    "reason": f"pre_render_qc_error:{type(seg_exc).__name__}:{seg_exc}",
                    "stage": "pre_render_qc_error",
                }
            )
            candidate_reports.append(
                {
                    "candidate_index": idx + 1,
                    "start_time": segment.get("start_time"),
                    "end_time": segment.get("end_time"),
                    "approved": False,
                    "reject_reasons": [f"pre_render_qc_error:{type(seg_exc).__name__}:{seg_exc}"],
                    "edit_plan_summary": {},
                    "contract_result": {},
                }
            )
            continue

    # -----------------------------------------------------------------------
    # Editorial Diversity Selection
    # -----------------------------------------------------------------------
    # If we have more approved segments than requested_clips, apply diversity
    # selection to prefer variety across editorial_type, publishing_intent,
    # and topic/concept.  This avoids publishing multiple near-identical clips.
    if len(approved_segments) > requested_clips > 0:
        from .vpi_editorial_contract import _compute_diversity_key

        # Build a list of (segment, diversity_key, final_contract_score) tuples
        scored: List[Tuple[Dict[str, Any], str, float]] = []
        for seg in approved_segments:
            pre_qc = seg.get("pre_render_qc") or {}
            publishing_intent = str(pre_qc.get("publishing_intent", "unknown"))
            dkey = _compute_diversity_key(seg, publishing_intent)
            contract_result = dict(pre_qc.get("contract_result") or {})
            score = float(contract_result.get("final_contract_score", 0.0))
            scored.append((seg, dkey, score))

        # Sort by score descending so we keep highest-scoring segments first
        scored.sort(key=lambda x: -x[2])

        selected: List[Dict[str, Any]] = []
        seen_keys: Dict[str, int] = {}  # diversity_key -> count of selections

        for seg, dkey, score in scored:
            if len(selected) >= requested_clips:
                break
            # Apply diversity penalty: if this key is already selected, penalise
            # by reducing effective score.  We still allow duplicates if there
            # aren't enough diverse options.
            diversity_penalty = seen_keys.get(dkey, 0) * 0.15
            effective_score = score * (1.0 - diversity_penalty)
            # If we still have room and the effective score is reasonable, select
            if effective_score > 0.0 or len(selected) < requested_clips:
                selected.append(seg)
                seen_keys[dkey] = seen_keys.get(dkey, 0) + 1
                logger.info(
                    "DIVERSITY_SELECT task_id=%s dkey=%s score=%.3f penalty=%.3f effective=%.3f selected=%d/%d",
                    task_id,
                    dkey,
                    score,
                    diversity_penalty,
                    effective_score,
                    len(selected),
                    requested_clips,
                )

        # If we still haven't filled the quota, add remaining segments by score
        if len(selected) < requested_clips:
            already_selected_ids = {id(s) for s in selected}
            for seg, dkey, score in scored:
                if len(selected) >= requested_clips:
                    break
                if id(seg) not in already_selected_ids:
                    selected.append(seg)
                    already_selected_ids.add(id(seg))
                    logger.info(
                        "DIVERSITY_SELECT_FILL task_id=%s dkey=%s score=%.3f selected=%d/%d",
                        task_id,
                        dkey,
                        score,
                        len(selected),
                        requested_clips,
                    )

        # Update the rejected list with segments that were dropped by diversity
        selected_ids = {id(s) for s in selected}
        for seg in approved_segments:
            if id(seg) not in selected_ids:
                rejected.append(
                    {
                        "clip_index": seg.get("pre_render_qc", {}).get("candidate_index", 0),
                        "start_time": seg.get("start_time"),
                        "end_time": seg.get("end_time"),
                        "reason": "diversity_selection:duplicate_key",
                        "stage": "diversity_filtered",
                    }
                )

        approved_segments = selected
        logger.info(
            "DIVERSITY_SELECT_DONE task_id=%s approved_before=%d approved_after=%d requested=%d",
            task_id,
            len(scored),
            len(approved_segments),
            requested_clips,
        )

    # Build editorial snapshots for persistence
    # NOTE: build_editorial_snapshots() takes only one positional arg (candidates).
    # It internally calls evaluate_editorial_contract_batch() to re-evaluate,
    # so we pass segments as the candidates.
    snapshots = build_editorial_snapshots(
        segments,
        task_id=task_id,
        profile=DEFAULT_PROFILE,
    )

    return {
        "approved_segments": approved_segments,
        "rejected_segments": rejected,
        "requested_clips": requested_clips,
        "candidate_count": len(segments),
        "approved_count": len(approved_segments),
        "failed_count": len(rejected),
        "bgm_tracks_available": _resolved_bgm_tracks_available,
        "task_id": task_id,
        "candidate_reports": candidate_reports,
        "approved_ratio": len(approved_segments) / max(len(segments), 1),
        "approved_full_plans": approved_segments,
        "editorial_snapshots": snapshots,
    }


def _adjust_segment_semantic_boundaries(
    *,
    task_id: str,
    segment: Dict[str, Any],
    transcript_lines: List[Dict[str, Any]],
    video_duration_s: Optional[float],
) -> None:
    old_start_ts = str(segment.get("start_time") or "00:00")
    old_end_ts = str(segment.get("end_time") or "00:00")
    start_s = parse_timestamp_to_seconds(old_start_ts)
    end_s = parse_timestamp_to_seconds(old_end_ts)
    if end_s <= start_s:
        return

    original_start_s = start_s
    original_end_s = end_s
    segment_text = str(segment.get("text") or "")
    setup_removed_s = 0.0
    reasons: List[str] = []

    overlap_lines = [
        line for line in transcript_lines
        if float(line.get("end", 0.0)) >= start_s and float(line.get("start", 0.0)) <= end_s
    ]

    if overlap_lines:
        first_meaningful = next(
            (
                line for line in overlap_lines
                if _has_content_terms(str(line.get("text") or "")) and not _is_setup_text(str(line.get("text") or ""))
            ),
            None,
        )
        if first_meaningful:
            new_start = max(start_s, float(first_meaningful.get("start", start_s)))
            if new_start > start_s:
                setup_removed_s = round(new_start - start_s, 2)
                start_s = new_start
                reasons.append("remove_setup_prefix_from_transcript_lines")

        if not _is_sentence_end(segment_text):
            candidate_end = end_s
            for line in overlap_lines:
                line_end = float(line.get("end", end_s))
                if line_end >= end_s:
                    candidate_end = max(candidate_end, line_end)
            if video_duration_s:
                candidate_end = min(candidate_end, float(video_duration_s))
            max_extension = min(6.0, max(2.0, (end_s - start_s) * 0.25))
            candidate_end = min(candidate_end, end_s + max_extension)
            if candidate_end > end_s:
                end_s = candidate_end
                reasons.append("extend_to_sentence_clause_end")
    else:
        if _is_setup_text(segment_text):
            trim = min(2.0, max(0.7, (end_s - start_s) * 0.12))
            start_s = min(end_s - 4.0, start_s + trim)
            setup_removed_s = round(max(0.0, start_s - original_start_s), 2)
            reasons.append("heuristic_setup_trim")
        if not _is_sentence_end(segment_text):
            extend = min(4.0, max(1.2, (end_s - start_s) * 0.18))
            end_cap = float(video_duration_s) if video_duration_s else end_s + extend
            new_end = min(end_cap, end_s + extend)
            if new_end > end_s:
                end_s = new_end
                reasons.append("heuristic_clause_extension")

    if end_s <= start_s:
        return

    if abs(start_s - original_start_s) > 0.01 or abs(end_s - original_end_s) > 0.01:
        segment["start_time"] = _format_mmss(start_s)
        segment["end_time"] = _format_mmss(end_s)
        logger.info(
            "SEMANTIC_BOUNDARY_ADJUSTMENT task_id=%s old_start=%s old_end=%s new_start=%s new_end=%s reason=%s",
            task_id,
            old_start_ts,
            old_end_ts,
            segment["start_time"],
            segment["end_time"],
            ",".join(reasons) if reasons else "semantic_alignment",
        )
        if setup_removed_s > 0:
            logger.info(
                "HOOK_CLEANUP_REMOVED_SETUP task_id=%s seconds_removed=%.2f",
                task_id,
                setup_removed_s,
            )


# ── OUTPUT-SELECTION-4: anti-backstage / anti-low-value boundary cleaner ────────
# Backstage / production-talk markers (es-ES). Multi-word phrases match directly;
# the risky single words only count when the same line lacks commercial content.
_BACKSTAGE_PHRASES = (
    "no grabes", "esto no sale", "fuera de camara", "detras de camaras",
    "luego lo corto", "vamos de nuevo", "otra vez", "se escucha", "no salio",
    "vale ya esta", "bueno ya esta", "hasta aqui", "ahora si que", "ya estamos",
    "me queda por decir", "no tengo tanto material", "puedes hablar tambien de",
    "esta grabando", "estamos grabando", "lo repito", "repite eso", "quita eso",
    "editalo", "quitalo", "corten", "y ya esta bueno",
    # OUTPUT-SELECTION-10B: meta-reading / camera-aware lines (vídeo 3 stress)
    "estoy leyendo", "no se ve que",
)
_BACKSTAGE_WEAK_WORDS = (
    "camara", "grabando", "toma", "plano", "micro", "microfono", "repite",
    "espera", "esperate", "pausa", "seguimos", "terminamos", "corta",
)


_EXTRA_VALUE_STEMS = (
    "proteg", "asegur", "contrat", "tranquilidad", "ahorr", "client", "asesor",
    "recomiend", "prever", "responsabilidad", "futuro", "claridad", "calma",
)


def _classify_transcript_line_for_publishing(text: str) -> str:
    """Classify a transcript line as backstage / valuable / neutral."""
    # OUTPUT-SELECTION-10B: hard normalizer — veto lists are unaccented and
    # punctuation-free; the loose normalizer silently missed "Perdón."/"cámara".
    normalized = _normalize_text_hard(text)
    if not normalized:
        return "neutral"
    has_value = (
        _has_content_terms(text) or any(stem in normalized for stem in _EXTRA_VALUE_STEMS)
    ) and not _is_setup_text(text)
    if any(phrase in normalized for phrase in _BACKSTAGE_PHRASES):
        return "backstage"
    weak_hits = sum(1 for w in _BACKSTAGE_WEAK_WORDS if re.search(rf"\b{w}\b", normalized))
    if weak_hits and not has_value:
        return "backstage"
    if weak_hits >= 2:
        return "backstage"
    if has_value:
        return "valuable"
    return "neutral"


_REHEARSAL_STRONG_PHRASES = (
    "esta raro", "quedo raro", "otra vez", "vamos de nuevo", "me equivoque",
    "me trabe", "ahora si", "a ver", "no se como", "desde el principio",
    "lo repito", "repite eso", "no me salio", "quedo mal", "en este momento no",
    "no en este momento", "o sea", "esta grabando", "no no no",
)
_REHEARSAL_WEAK_WORDS = (
    "vale", "bueno", "espera", "esperate", "corta", "repite", "grabando",
    "si", "raro", "dejame", "esto", "vamos",
)
_CLEAN_START_VALUE_TERMS = (
    "seguro", "seguros", "cobertura", "poliza", "póliza", "proteccion", "protección",
    "proteger", "familia", "cliente", "prima", "decesos", "salud", "ahorro",
    "contratar", "asesor", "vida", "importante", "explicar", "hablar", "claridad",
)


def _normalize_word_token(text: str) -> str:
    token = unicodedata.normalize("NFKD", str(text or ""))
    token = "".join(ch for ch in token if not unicodedata.combining(ch))
    token = re.sub(r"[^a-zA-Z0-9]+", "", token.lower())
    return token.strip()


def _word_time_seconds(raw: Any, key: str) -> Optional[float]:
    try:
        value = float(_as_dict(raw).get(key) or 0.0)
    except Exception:
        return None
    # Transcript cache words are milliseconds. Accept seconds defensively for
    # older in-memory callers or focused tests.
    return value / 1000.0 if value > 300.0 else value


def _find_clean_start_from_word_timings(
    *,
    words: List[Dict[str, Any]],
    window_start_s: float,
    window_end_s: float,
) -> Dict[str, Any]:
    """Word-level retake/backstage head scan over cached transcript words (ms times).

    Reconstructed lines can merge rehearsal fragments with the start of the clean
    take; this scans the raw words to find the first clean-run start after the
    last rehearsal/logistics signal in the head zone.
    """
    out: Dict[str, Any] = {"applied": False, "reason": "", "confidence": 0.0}
    window_span = window_end_s - window_start_s
    if window_span <= 0 or not words:
        out["reason"] = "no_word_timings"
        return out
    head_end_s = window_start_s + min(20.0, window_span * 0.45)
    in_window: List[Dict[str, Any]] = []
    for w in words:
        try:
            ws = _word_time_seconds(w, "start")
            we = _word_time_seconds(w, "end")
        except Exception:
            continue
        if ws is None or we is None:
            continue
        if we <= window_start_s or ws >= window_end_s:
            continue
        token = _normalize_word_token(w.get("text"))
        if token:
            in_window.append({"s": ws, "e": we, "t": token})
    if len(in_window) < 8:
        out["reason"] = "too_few_words"
        return out

    blob_tokens = [w["t"] for w in in_window]
    joined = " ".join(blob_tokens)

    # Mark dirty word indices in the head zone.
    dirty_end_idx = -1
    head_idx_limit = max(i for i, w in enumerate(in_window) if w["s"] <= head_end_s)
    for phrase in _REHEARSAL_STRONG_PHRASES:
        ph_tokens = phrase.split()
        for i in range(0, min(head_idx_limit + 1, len(in_window)) - len(ph_tokens) + 1):
            if blob_tokens[i:i + len(ph_tokens)] == ph_tokens:
                dirty_end_idx = max(dirty_end_idx, i + len(ph_tokens) - 1)
    # Weak singles: only when clustered (>=2 within a 6-word span).
    weak_hits = [
        i for i, t in enumerate(blob_tokens[: head_idx_limit + 1])
        if t.rstrip("?") in _REHEARSAL_WEAK_WORDS
    ]
    for a in range(len(weak_hits)):
        for b in range(a + 1, len(weak_hits)):
            if weak_hits[b] - weak_hits[a] <= 6:
                dirty_end_idx = max(dirty_end_idx, weak_hits[b])

    if dirty_end_idx < 0:
        # S4 can land on a coarse line boundary that starts inside a clean take
        # (for example the tail of a speaker name) even when no explicit retake
        # marker remains. Snap to the first strong semantic run shortly after a
        # phrase pause; do not invent a new opener or expand backward.
        for i in range(1, min(len(in_window), 12)):
            if in_window[i]["s"] - window_start_s > 3.0:
                break
            pause_before = in_window[i]["s"] - in_window[i - 1]["e"]
            if pause_before < 0.25:
                continue
            prefix_blob = " ".join(blob_tokens[:i])
            run_blob = " ".join(blob_tokens[i:i + 12])
            if any(term in prefix_blob for term in _CLEAN_START_VALUE_TERMS):
                continue
            if not any(term in run_blob for term in _CLEAN_START_VALUE_TERMS):
                continue
            new_start = in_window[i]["s"]
            trimmed = new_start - window_start_s
            if trimmed < 0.6 or window_end_s - new_start < 8.0:
                continue
            removed_words = [w["t"] for w in in_window if w["s"] < new_start][-18:]
            out.update({
                "applied": True,
                "new_start_s": round(new_start, 2),
                "trimmed_seconds": round(trimmed, 2),
                "reason": "wordlevel_partial_phrase_clean_start",
                "confidence": 0.72,
                "removed_head_preview": " ".join(removed_words)[:200],
            })
            return out
        out["reason"] = "head_already_clean"
        return out

    # Find the first clean-run start after the last dirty word.
    candidate_idx = None
    for i in range(dirty_end_idx + 1, min(len(in_window), head_idx_limit + 14)):
        run = blob_tokens[i:i + 12]
        if not run:
            break
        run_blob = " ".join(run)
        if any(phrase in run_blob for phrase in _REHEARSAL_STRONG_PHRASES):
            continue
        if not any(term in run_blob for term in _CLEAN_START_VALUE_TERMS):
            continue
        pause_before = in_window[i]["s"] - in_window[i - 1]["e"] if i > 0 else 1.0
        candidate_idx = i
        out["confidence"] = 0.85 if pause_before >= 0.35 else 0.7
        if pause_before >= 0.35:
            break  # prefer the first clean run after a real phrase boundary
        # otherwise keep looking briefly for a pause-aligned start
        for j in range(i + 1, min(len(in_window), i + 10)):
            pj = in_window[j]["s"] - in_window[j - 1]["e"]
            run_j = " ".join(blob_tokens[j:j + 12])
            if pj >= 0.35 and any(term in run_j for term in _CLEAN_START_VALUE_TERMS) and not any(
                phrase in run_j for phrase in _REHEARSAL_STRONG_PHRASES
            ):
                candidate_idx = j
                out["confidence"] = 0.85
                break
        break

    if candidate_idx is None:
        out["reason"] = "no_clean_run_after_dirty"
        return out

    new_start = in_window[candidate_idx]["s"]
    trimmed = new_start - window_start_s
    if trimmed < 0.6:
        out["reason"] = "trim_below_0_6s"
        return out
    if trimmed > window_span * 0.6:
        out["reason"] = "trim_exceeds_60pct"
        return out
    if window_end_s - new_start < 8.0:
        out["reason"] = "remaining_below_8s"
        return out

    removed_words = [w["t"] for w in in_window if w["s"] < new_start][-18:]
    out.update({
        "applied": True,
        "new_start_s": round(new_start, 2),
        "trimmed_seconds": round(trimmed, 2),
        "reason": "wordlevel_retake_or_logistics_head",
        "removed_head_preview": " ".join(removed_words)[:200],
    })
    return out


def _load_cached_words_for_output_selection(video_path: Path) -> List[Dict[str, Any]]:
    try:
        from ..video_processing.transcription import load_cached_transcript_data

        cached = load_cached_transcript_data(video_path)
    except Exception as exc:
        logger.info(
            "VPI_OUTPUT_SELECTION_WORDLEVEL_START_TRIM_SKIPPED reason=cache_load_failed error=%s",
            str(exc)[:160],
        )
        return []
    words = cached.get("words") if isinstance(cached, dict) else None
    if not isinstance(words, list):
        return []
    valid: List[Dict[str, Any]] = []
    for raw in words:
        item = _as_dict(raw)
        if not str(item.get("text") or item.get("word") or "").strip():
            continue
        if _word_time_seconds(item, "start") is None or _word_time_seconds(item, "end") is None:
            continue
        if "text" not in item and item.get("word"):
            item["text"] = item.get("word")
        valid.append(item)
    return valid


def _trim_unpublishable_tail_from_segment(
    *,
    task_id: str,
    segment: Dict[str, Any],
    transcript_lines: List[Dict[str, Any]],
    video_duration_s: Optional[float],
    clip_order: int = 0,
    cached_words: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Clamp the FINAL render window so it never carries backstage chatter or a
    low-value tail. Runs after every expansion (boundary refinement, semantic
    adjustment, min-duration top-up), immediately before ffmpeg extraction.

    Never pads forward. Prefers backward expansion over keeping a bad tail, and
    accepts a shorter clip over delivering production talk.
    """
    result: Dict[str, Any] = {"applied": False, "tail_trim_reason": "", "tail_trimmed_seconds": 0.0}
    start_s = parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
    end_s = parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
    if end_s <= start_s:
        return result
    original_start_s, original_end_s = start_s, end_s

    lines = sorted(
        (
            dict(line, _class=_classify_transcript_line_for_publishing(str(line.get("text") or "")))
            for line in transcript_lines
            if float(line.get("end", 0.0)) > start_s and float(line.get("start", 0.0)) < end_s
        ),
        key=lambda item: float(item.get("start") or 0.0),
    )
    logger.info(
        "VPI_OUTPUT_SELECTION_TAIL_AUDIT task_id=%s clip_order=%s window=%.2f-%.2f lines=%d backstage=%d valuable=%d",
        task_id, clip_order, start_s, end_s, len(lines),
        sum(1 for l in lines if l["_class"] == "backstage"),
        sum(1 for l in lines if l["_class"] == "valuable"),
    )
    if not lines:
        logger.info(
            "VPI_OUTPUT_SELECTION_TAIL_TRIM_SKIPPED task_id=%s clip_order=%s reason=no_timed_transcript_lines",
            task_id, clip_order,
        )
        return result

    valuable = [l for l in lines if l["_class"] == "valuable"]
    if not valuable:
        logger.info(
            "VPI_OUTPUT_SELECTION_TAIL_TRIM_SKIPPED task_id=%s clip_order=%s reason=no_valuable_lines_low_confidence",
            task_id, clip_order,
        )
        return result

    reasons: List[str] = []
    removed_preview: List[str] = []

    # ── TAIL: walk back over trailing backstage / low-value lines ────────────
    last_valuable_end = max(float(l.get("end") or 0.0) for l in valuable)
    trailing = [l for l in lines if float(l.get("start") or 0.0) >= last_valuable_end - 0.25 and l["_class"] != "valuable"]
    trailing_backstage = [l for l in trailing if l["_class"] == "backstage"]
    trailing_span = max(0.0, end_s - last_valuable_end)
    clean_end = end_s
    if trailing_backstage:
        clean_end = min(end_s, max(start_s + 0.5, min(float(l.get("start") or end_s) for l in trailing_backstage)))
        reasons.append("backstage_tail")
        removed_preview.extend(str(l.get("text") or "")[:80] for l in trailing_backstage[:3])
        logger.info(
            "VPI_OUTPUT_SELECTION_BACKSTAGE_TAIL_DETECTED task_id=%s clip_order=%s at=%.2f preview=%s",
            task_id, clip_order, clean_end, (removed_preview[0] if removed_preview else "")[:90],
        )
    if trailing_span > 3.0:
        # Rule: never keep more than 2.5s after the last valuable line.
        low_value_end = min(clean_end, last_valuable_end + 2.5)
        if low_value_end < clean_end - 0.25:
            reasons.append("low_value_tail")
            removed_preview.extend(
                str(l.get("text") or "")[:80]
                for l in trailing if float(l.get("start") or 0.0) >= low_value_end
            )
            logger.info(
                "VPI_OUTPUT_SELECTION_LOW_VALUE_TAIL_DETECTED task_id=%s clip_order=%s span=%.2f new_end=%.2f",
                task_id, clip_order, trailing_span, low_value_end,
            )
        clean_end = min(clean_end, low_value_end)

    # ── HEAD: drop a leading backstage block (planning talk before the take) ─
    clean_start = start_s
    first_valuable_start = min(float(l.get("start") or 0.0) for l in valuable)
    leading = [l for l in lines if float(l.get("end") or 0.0) <= first_valuable_start + 0.25]
    leading_backstage = [l for l in leading if l["_class"] == "backstage"]
    if leading_backstage:
        candidate_start = max(start_s, max(float(l.get("end") or start_s) for l in leading_backstage))
        # do not remove more than 60% of the window from the head
        if candidate_start - start_s <= (end_s - start_s) * 0.6:
            clean_start = candidate_start
            reasons.append("backstage_head")
            removed_preview.extend(str(l.get("text") or "")[:80] for l in leading_backstage[:3])

    # ── RETAKE HEAD: an early line that near-duplicates a later line means the
    # speaker re-recorded the opener — keep only the final take.
    try:
        window_span = clean_end - clean_start
        head_zone_end = clean_start + window_span * 0.45
        lines_in = [l for l in lines if clean_start - 0.25 <= float(l.get("start") or 0.0) < clean_end]
        retake_start = None
        retake_preview = ""
        for i, early in enumerate(lines_in):
            if float(early.get("start") or 0.0) > head_zone_end:
                break
            early_tokens = set(_normalize_text_loose(str(early.get("text") or "")).split())
            if len(early_tokens) < 3:
                continue
            for late in lines_in[i + 1:]:
                if float(late.get("start") or 0.0) <= float(early.get("end") or 0.0):
                    continue
                late_tokens = set(_normalize_text_loose(str(late.get("text") or "")).split())
                if len(late_tokens) < 3:
                    continue
                # Containment, not Jaccard: the final take usually REPEATS the
                # rehearsed words plus extras ("Hola, soy X, les vengo a hablar…"),
                # so symmetric overlap under-scores the true last take.
                overlap = len(early_tokens & late_tokens) / max(1, len(early_tokens))
                if overlap >= 0.65:
                    candidate = float(late.get("start") or clean_start)
                    if (
                        candidate > clean_start + 0.5
                        and candidate - clean_start <= window_span * 0.65
                        and clean_end - candidate >= 8.0
                        and (retake_start is None or candidate > retake_start)
                    ):
                        retake_start = candidate
                        retake_preview = str(early.get("text") or "")[:90]
        if retake_start is not None and retake_start > clean_start:
            logger.info(
                "VPI_OUTPUT_SELECTION_RETAKE_HEAD_DETECTED task_id=%s clip_order=%s old_start=%.2f new_start=%.2f duplicate_of=%s",
                task_id, clip_order, clean_start, retake_start, retake_preview,
            )
            removed_preview.extend(
                str(l.get("text") or "")[:80]
                for l in lines_in
                if float(l.get("end") or 0.0) <= retake_start + 0.25
            )
            clean_start = retake_start
            reasons.append("retake_head")
    except Exception as _retake_e:
        logger.debug("retake head detection skipped: %s", _retake_e)

    # ── Minimum duration: prefer backward expansion, else accept shorter ─────
    backward_used = 0.0
    if clean_end - clean_start < 12.0:
        prior = sorted(
            (
                dict(line, _class=_classify_transcript_line_for_publishing(str(line.get("text") or "")))
                for line in transcript_lines
                if float(line.get("end", 0.0)) <= clean_start + 0.25
            ),
            key=lambda item: float(item.get("start") or 0.0),
            reverse=True,
        )
        for line in prior:
            if line["_class"] != "valuable" or (clean_end - clean_start) >= 12.0 or backward_used >= 10.0:
                break
            new_start = max(0.0, float(line.get("start") or clean_start))
            backward_used += clean_start - new_start
            clean_start = new_start
        if backward_used > 0.25:
            logger.info(
                "VPI_OUTPUT_SELECTION_BACKWARD_EXPANSION_USED task_id=%s clip_order=%s seconds=%.2f new_start=%.2f",
                task_id, clip_order, backward_used, clean_start,
            )

    # ── S5: word-level retake/backstage head refine (cached words, ms times).
    # Runs LAST so later steps cannot re-expand back into rehearsal.
    wordlevel_meta: Dict[str, Any] = {}
    if cached_words:
        logger.info(
            "VPI_OUTPUT_SELECTION_WORDLEVEL_HEAD_AUDIT task_id=%s clip_order=%s source=cached_words words=%d window=%.2f-%.2f",
            task_id, clip_order, len(cached_words), clean_start, clean_end,
        )
        try:
            _wl = _find_clean_start_from_word_timings(
                words=cached_words,
                window_start_s=clean_start,
                window_end_s=clean_end,
            )
        except Exception as _wl_e:
            _wl = {"applied": False, "reason": f"exception:{_wl_e}"}
        if _wl.get("applied"):
            logger.info(
                "VPI_OUTPUT_SELECTION_WORDLEVEL_RETAKE_HEAD_DETECTED task_id=%s clip_order=%s old_start=%.2f new_start=%.2f preview=%s",
                task_id, clip_order, clean_start, float(_wl["new_start_s"]),
                str(_wl.get("removed_head_preview") or "")[:100],
            )
            removed_preview.append(str(_wl.get("removed_head_preview") or "")[:100])
            clean_start = float(_wl["new_start_s"])
            reasons.append("wordlevel_head")
            wordlevel_meta = {
                "wordlevel_start_trimmed_seconds": float(_wl.get("trimmed_seconds") or 0.0),
                "wordlevel_start_reason": str(_wl.get("reason") or ""),
                "wordlevel_start_confidence": float(_wl.get("confidence") or 0.0),
                "removed_head_preview": str(_wl.get("removed_head_preview") or "")[:200],
                "clean_start_source": "cached_words",
            }
            logger.info(
                "VPI_OUTPUT_SELECTION_WORDLEVEL_START_TRIM_APPLIED task_id=%s clip_order=%s trimmed=%.2f confidence=%.2f",
                task_id, clip_order,
                wordlevel_meta["wordlevel_start_trimmed_seconds"],
                wordlevel_meta["wordlevel_start_confidence"],
            )
        else:
            logger.info(
                "VPI_OUTPUT_SELECTION_WORDLEVEL_START_TRIM_SKIPPED task_id=%s clip_order=%s reason=%s",
                task_id, clip_order, str(_wl.get("reason") or "not_applicable"),
            )

    if clean_end - clean_start < 6.0:
        logger.info(
            "VPI_OUTPUT_SELECTION_TAIL_TRIM_SKIPPED task_id=%s clip_order=%s reason=would_leave_clip_below_6s",
            task_id, clip_order,
        )
        return result

    tail_trimmed = round(max(0.0, original_end_s - clean_end), 2)
    head_trimmed = round(max(0.0, clean_start - original_start_s), 2)
    if tail_trimmed < 0.3 and head_trimmed < 0.3:
        logger.info(
            "VPI_OUTPUT_SELECTION_FINAL_BOUNDARY_CLEAN task_id=%s clip_order=%s window=%.2f-%.2f trim=none",
            task_id, clip_order, clean_start, clean_end,
        )
        return result

    if clean_end - clean_start < 12.0:
        logger.info(
            "VPI_OUTPUT_SELECTION_SHORT_CLIP_ACCEPTED task_id=%s clip_order=%s duration=%.2f reason=clean_over_long",
            task_id, clip_order, clean_end - clean_start,
        )

    kept_lines = [
        line for line in transcript_lines
        if float(line.get("end", 0.0)) > clean_start + 0.05 and float(line.get("start", 0.0)) < clean_end - 0.05
    ]
    kept_text = " ".join(str(l.get("text") or "").strip() for l in kept_lines).strip()
    if wordlevel_meta and cached_words:
        # Word-precise text so captions/QC don't carry the partial leading line.
        _kept_words = [
            str(w.get("text") or "").strip()
            for w in cached_words
            if (_word_time_seconds(w, "start") or 0.0) >= clean_start - 0.05
            and (_word_time_seconds(w, "start") or 0.0) < clean_end - 0.05
        ]
        _word_text = " ".join(t for t in _kept_words if t).strip()
        if _word_text:
            kept_text = _word_text

    segment["original_candidate_start_s"] = original_start_s
    segment["original_candidate_end_s"] = original_end_s
    segment["clean_final_start_s"] = round(clean_start, 2)
    segment["clean_final_end_s"] = round(clean_end, 2)
    segment["tail_trimmed_seconds"] = tail_trimmed
    segment["head_trimmed_seconds"] = head_trimmed
    segment["tail_trim_reason"] = "|".join(dict.fromkeys(reasons)) or "boundary_clamp"
    segment["removed_tail_preview"] = " / ".join(removed_preview[:4])[:240]
    segment["anti_tail_confidence"] = 0.9 if any(r.startswith("backstage") for r in reasons) else 0.7
    if wordlevel_meta:
        segment.update(wordlevel_meta)
        logger.info(
            "VPI_OUTPUT_SELECTION_WORDLEVEL_FINAL_START_CLEAN task_id=%s clip_order=%s start=%.2f",
            task_id, clip_order, clean_start,
        )
    segment["start_time"] = _format_mmss_precise(clean_start) if wordlevel_meta else _format_mmss(clean_start)
    segment["end_time"] = _format_mmss(clean_end)
    segment["refined_start_time"] = segment["start_time"]
    segment["refined_end_time"] = segment["end_time"]
    if kept_text:
        segment["text"] = kept_text
    result.update({
        "applied": True,
        "tail_trimmed_seconds": tail_trimmed,
        "head_trimmed_seconds": head_trimmed,
        "tail_trim_reason": segment["tail_trim_reason"],
    })
    logger.info(
        "VPI_OUTPUT_SELECTION_TAIL_TRIM_APPLIED task_id=%s clip_order=%s old=%.2f-%.2f new=%.2f-%.2f tail_trimmed=%.2f head_trimmed=%.2f reason=%s preview=%s",
        task_id, clip_order, original_start_s, original_end_s, clean_start, clean_end,
        tail_trimmed, head_trimmed, segment["tail_trim_reason"],
        segment["removed_tail_preview"][:100],
    )
    logger.info(
        "VPI_OUTPUT_SELECTION_FINAL_BOUNDARY_CLEAN task_id=%s clip_order=%s window=%.2f-%.2f duration=%.2f",
        task_id, clip_order, clean_start, clean_end, clean_end - clean_start,
    )
    return result


_OPEN_STRUCTURE_ENDINGS = (
    "porque", "para", "cuando", "si", "es", "son", "esta", "estan", "significa",
    "protege", "proteger", "como", "con", "sin", "de", "del", "la", "el", "los",
    "las", "una", "un", "que", "y", "o", "pero", "en", "a", "tu", "su", "mi",
    "concreto", "importante", "idea",
)
_STRONG_CLOSE_PUNCT = (".", "!", "?", "…")


def _apply_speech_closure_guard(
    *,
    task_id: str,
    segment: Dict[str, Any],
    cached_words: Optional[List[Dict[str, Any]]],
    clip_order: int = 0,
    video_duration_s: Optional[float] = None,
) -> None:
    """Never cut the final MP4 mid-phrase: if the clean end falls inside an open
    sentence, extend forward (ideal ≤4s, hard ≤7s) to the next natural closure —
    strong punctuation and/or a real pause — unless the extension zone contains
    backstage/logistics, in which case fall back to the previous clean closure.
    Runs AFTER S4/S5 and BEFORE the post-trim caption contract so the contract is
    rebuilt against the closed boundary (captions can never go stale).
    """
    start_s = parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
    end_s = parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
    if end_s <= start_s:
        return
    words: List[Dict[str, Any]] = []
    for w in cached_words or []:
        ws = _word_time_seconds(w, "start")
        we = _word_time_seconds(w, "end")
        token = str(w.get("text") or "").strip()
        if ws is None or we is None or not token:
            continue
        words.append({"s": ws, "e": we, "t": token})
    if not words:
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_AUDIT task_id=%s clip_order=%s result=skipped reason=no_word_timings",
            task_id, clip_order,
        )
        return
    words.sort(key=lambda x: x["s"])

    in_window = [w for w in words if w["e"] <= end_s + 0.02 and w["s"] >= start_s - 0.02]
    after = [w for w in words if w["s"] >= end_s - 0.6]
    if not in_window:
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_AUDIT task_id=%s clip_order=%s result=skipped reason=no_words_in_window",
            task_id, clip_order,
        )
        return

    last = in_window[-1]
    last_norm = _normalize_text_hard(last["t"])
    last_has_punct = str(last["t"]).rstrip().endswith(_STRONG_CLOSE_PUNCT)
    next_after = next((w for w in words if w["s"] >= last["e"] - 0.01 and w["s"] > last["s"]), None)
    gap_after_last = (next_after["s"] - last["e"]) if next_after else 10.0
    tail_tokens = [_normalize_text_hard(w["t"]) for w in in_window[-3:]]
    open_ending = last_norm in _OPEN_STRUCTURE_ENDINGS or (
        len(tail_tokens) >= 2 and tail_tokens[-2] in ("proteger", "es", "lo", "la") and last_norm in _OPEN_STRUCTURE_ENDINGS
    )
    incomplete = (not last_has_punct and gap_after_last < 0.5) or open_ending or (
        last_has_punct is False and next_after is not None and next_after["s"] - end_s < 0.4
    )
    # Also incomplete if a word is SLICED by the boundary (starts before, ends after).
    sliced = any(w["s"] < end_s - 0.02 < w["e"] for w in words)
    incomplete = incomplete or sliced

    logger.info(
        "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_AUDIT task_id=%s clip_order=%s end=%.2f last_word=%s punct=%s gap_after=%.2f open_ending=%s sliced=%s incomplete=%s",
        task_id, clip_order, end_s, last["t"][:24], str(last_has_punct).lower(),
        min(gap_after_last, 9.9), str(open_ending).lower(), str(sliced).lower(),
        str(incomplete).lower(),
    )
    if not incomplete:
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_FINAL_BOUNDARY task_id=%s clip_order=%s end=%.2f changed=false reason=already_closed",
            task_id, clip_order, end_s,
        )
        return

    next_preview = " ".join(w["t"] for w in after[:14])[:140]
    logger.info(
        "VPI_OUTPUT_SELECTION_INCOMPLETE_FINAL_IDEA_DETECTED task_id=%s clip_order=%s end=%.2f next_words=%s",
        task_id, clip_order, end_s, next_preview,
    )

    hard_max_end = end_s + 7.0
    if video_duration_s:
        hard_max_end = min(hard_max_end, float(video_duration_s) - 0.1)
    forward = [w for w in words if end_s - 0.6 <= w["s"] <= hard_max_end]

    # Backstage screening of the extension zone.
    forward_blob = " ".join(_normalize_text_hard(w["t"]) for w in forward)
    forward_backstage = any(ph in forward_blob for ph in _BACKSTAGE_PHRASES)

    best_end = None
    best_score = 0.0
    best_word = ""
    if not forward_backstage:
        for idx, w in enumerate(forward):
            if w["e"] <= end_s:
                continue
            nxt = forward[idx + 1] if idx + 1 < len(forward) else None
            gap = (nxt["s"] - w["e"]) if nxt else 1.0
            punct = str(w["t"]).rstrip().endswith(_STRONG_CLOSE_PUNCT)
            if punct and gap >= 0.3:
                score = 1.0
            elif punct and gap >= 0.15:
                score = 0.8
            elif punct:
                score = 0.6
            elif gap >= 0.7:
                score = 0.65
            else:
                continue
            # Prefer ideal window (≤4s) lightly.
            if w["e"] - end_s <= 4.0:
                score += 0.05
            if score > best_score + 1e-9:
                best_score = score
                best_end = min(hard_max_end, w["e"] + min(0.25, max(0.1, gap / 2)))
                best_word = w["t"]
    else:
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_BACKSTAGE_BLOCKED task_id=%s clip_order=%s zone=%.2f-%.2f",
            task_id, clip_order, end_s, hard_max_end,
        )

    if best_end is not None and best_score >= 0.6:
        extended = best_end - end_s
        closure_words = [w["t"] for w in words if end_s - 3.5 <= w["s"] < best_end]
        segment["pre_closure_end_s"] = round(end_s, 2)
        segment["closure_final_end_s"] = round(best_end, 2)
        segment["speech_closure_extended_seconds"] = round(extended, 2)
        segment["speech_closure_reason"] = "incomplete_final_idea_extended_to_closure"
        segment["speech_closure_confidence"] = round(min(1.0, best_score), 2)
        segment["closure_text_preview"] = " ".join(closure_words)[:160]
        segment["next_words_after_original_end_preview"] = next_preview
        segment["end_time"] = _format_mmss_precise(best_end)
        segment["refined_end_time"] = segment["end_time"]
        segment["clean_final_end_s"] = round(best_end, 2)
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_EXTENDED task_id=%s clip_order=%s old_end=%.2f new_end=%.2f extended=%.2f closure_word=%s confidence=%.2f",
            task_id, clip_order, end_s, best_end, extended, best_word[:24], best_score,
        )
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_FINAL_BOUNDARY task_id=%s clip_order=%s end=%.2f changed=true preview=%s",
            task_id, clip_order, best_end, segment["closure_text_preview"][:90],
        )
        return

    # No safe forward closure → close at the previous clean point instead of mid-word.
    prev_close = None
    for idx in range(len(in_window) - 2, -1, -1):
        w = in_window[idx]
        nxt = in_window[idx + 1]
        gap = nxt["s"] - w["e"]
        punct = str(w["t"]).rstrip().endswith(_STRONG_CLOSE_PUNCT)
        if (punct and gap >= 0.15) or gap >= 0.7:
            prev_close = w["e"] + min(0.25, max(0.1, gap / 2))
            break
        if end_s - w["e"] > 8.0:
            break
    if prev_close is not None and prev_close - start_s >= 8.0:
        segment["pre_closure_end_s"] = round(end_s, 2)
        segment["closure_final_end_s"] = round(prev_close, 2)
        segment["speech_closure_extended_seconds"] = round(prev_close - end_s, 2)
        segment["speech_closure_reason"] = "trimmed_to_previous_close"
        segment["speech_closure_confidence"] = 0.7
        segment["closure_text_preview"] = " ".join(w["t"] for w in in_window if w["e"] <= prev_close)[-160:]
        segment["next_words_after_original_end_preview"] = next_preview
        segment["end_time"] = _format_mmss_precise(prev_close)
        segment["refined_end_time"] = segment["end_time"]
        segment["clean_final_end_s"] = round(prev_close, 2)
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_TRIMMED_TO_PREVIOUS_CLOSE task_id=%s clip_order=%s old_end=%.2f new_end=%.2f",
            task_id, clip_order, end_s, prev_close,
        )
        logger.info(
            "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_FINAL_BOUNDARY task_id=%s clip_order=%s end=%.2f changed=true reason=previous_close",
            task_id, clip_order, prev_close,
        )
        return
    logger.info(
        "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_FINAL_BOUNDARY task_id=%s clip_order=%s end=%.2f changed=false reason=no_safe_closure",
        task_id, clip_order, end_s,
    )


# ── OUTPUT-NARRATIVE-9: narrative closure planner ─────────────────────────────
_NARRATIVE_META_PHRASES = (
    "la ultima parte", "cuando digas", "se siente como un cierre",
    "estoy leyendo", "el titulo", "lo digo otra vez", "vas a lo nuevo",
    "a menu", "asi de seguido", "lo repito",
)
_NARRATIVE_CONTRAST_SETUPS = (
    "no me gusta", "no se trata de", "no es solo", "no es vender",
    "no quiero", "no consiste en", "no es una cuestion de",
)
_NARRATIVE_PAYOFF_STARTS = (
    "pero", "prefiero", "sino", "desde la", "es la", "al contrario", "en cambio",
)


def _apply_narrative_closure_planner(
    *,
    task_id: str,
    segment: Dict[str, Any],
    cached_words: Optional[List[Dict[str, Any]]],
    clip_order: int = 0,
    video_duration_s: Optional[float] = None,
) -> None:
    """Pick an ending that closes a HUMAN idea, not just a grammatical sentence.

    Runs AFTER S4/S5/S6 (the speech-closure guard fixes sliced/unpunctuated ends)
    and BEFORE the post-trim caption contract.  It handles the case S6 cannot see:
    a sentence that is grammatically closed but rhetorically open — a contrast
    setup ("no me gusta explicarlo desde el susto.") whose payoff ("pero prefiero
    explicarlo desde el cuidado.") starts right after the boundary, or an ending
    on an open connector.  Extends 2-8s to the first natural closure, capping the
    zone at the first backstage/meta phrase; if no good closure exists, marks the
    segment needs_review reason=narrative_closure_weak instead of shipping it.
    """
    start_s = parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
    end_s = parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
    if end_s <= start_s:
        return
    words: List[Dict[str, Any]] = []
    for w in cached_words or []:
        ws = _word_time_seconds(w, "start")
        we = _word_time_seconds(w, "end")
        token = str(w.get("text") or "").strip()
        if ws is None or we is None or not token:
            continue
        words.append({"s": ws, "e": we, "t": token})
    if not words:
        logger.info(
            "VPI_OUTPUT_NARRATIVE_CLOSURE_AUDIT task_id=%s clip_order=%s result=skipped reason=no_word_timings",
            task_id, clip_order,
        )
        return
    words.sort(key=lambda x: x["s"])
    in_window = [w for w in words if w["e"] <= end_s + 0.02 and w["s"] >= start_s - 0.02]
    if not in_window:
        logger.info(
            "VPI_OUTPUT_NARRATIVE_CLOSURE_AUDIT task_id=%s clip_order=%s result=skipped reason=no_words_in_window",
            task_id, clip_order,
        )
        return

    last = in_window[-1]
    last_norm = _normalize_text_hard(last["t"])
    last_has_punct = str(last["t"]).rstrip().endswith(_STRONG_CLOSE_PUNCT)
    tail_norm = " ".join(_normalize_text_hard(w["t"]) for w in in_window[-14:])
    after = [w for w in words if end_s - 0.05 <= w["s"] <= end_s + 9.0]
    next3_norm = " ".join(_normalize_text_hard(w["t"]) for w in after[:3])

    open_connector_end = (last_norm in _OPEN_STRUCTURE_ENDINGS) or not last_has_punct
    contrast_setup = any(ph in tail_norm for ph in _NARRATIVE_CONTRAST_SETUPS)
    payoff_next = bool(after) and any(
        next3_norm.startswith(ph) for ph in _NARRATIVE_PAYOFF_STARTS
    )
    open_end = open_connector_end or (contrast_setup and payoff_next)

    logger.info(
        "VPI_OUTPUT_NARRATIVE_CLOSURE_AUDIT task_id=%s clip_order=%s end=%.2f last_word=%s connector_end=%s contrast_setup=%s payoff_next=%s open_end=%s",
        task_id, clip_order, end_s, last["t"][:24],
        str(open_connector_end).lower(), str(contrast_setup).lower(),
        str(payoff_next).lower(), str(open_end).lower(),
    )
    segment["narrative_pre_end_s"] = round(end_s, 2)
    if not open_end:
        segment["narrative_final_end_s"] = round(end_s, 2)
        segment["narrative_extended_seconds"] = 0.0
        segment["narrative_closure_reason"] = "already_closed"
        segment["narrative_payoff_detected"] = False
        segment["narrative_closure_confidence"] = 0.9
        logger.info(
            "VPI_OUTPUT_NARRATIVE_FINAL_CLOSE_SELECTED task_id=%s clip_order=%s end=%.2f changed=false reason=already_closed",
            task_id, clip_order, end_s,
        )
        return

    logger.info(
        "VPI_OUTPUT_NARRATIVE_OPEN_END_DETECTED task_id=%s clip_order=%s kind=%s next=%s",
        task_id, clip_order,
        "contrast_payoff" if (contrast_setup and payoff_next) else "open_connector",
        " ".join(w["t"] for w in after[:8])[:90],
    )

    hard_max_end = end_s + 8.0
    if video_duration_s:
        hard_max_end = min(hard_max_end, float(video_duration_s) - 0.1)
    zone = [w for w in words if end_s - 0.3 <= w["s"] <= hard_max_end]
    # Cap the zone at the first backstage / meta-production phrase.
    bts_cap = None
    zone_norms = [_normalize_text_hard(w["t"]) for w in zone]
    for i in range(len(zone)):
        window_blob = " ".join(zone_norms[i:i + 5])
        if any(ph in window_blob for ph in _BACKSTAGE_PHRASES) or any(
            ph in window_blob for ph in _NARRATIVE_META_PHRASES
        ):
            bts_cap = zone[i]["s"] - 0.05
            break
    effective_max = min(hard_max_end, bts_cap) if bts_cap is not None else hard_max_end
    if bts_cap is not None:
        logger.info(
            "VPI_OUTPUT_NARRATIVE_CLOSURE_BLOCKED_BY_BTS task_id=%s clip_order=%s bts_at=%.2f zone_capped_to=%.2f",
            task_id, clip_order, bts_cap, effective_max,
        )
    if effective_max <= end_s + 1.0:
        segment["narrative_final_end_s"] = round(end_s, 2)
        segment["narrative_extended_seconds"] = 0.0
        segment["narrative_closure_reason"] = "narrative_closure_weak_bts_adjacent"
        segment["narrative_payoff_detected"] = bool(contrast_setup and payoff_next)
        segment["narrative_closure_confidence"] = 0.3
        segment["needs_review_reason"] = "narrative_closure_weak"
        segment["narrative_closure_weak"] = True
        logger.info(
            "VPI_OUTPUT_NARRATIVE_FINAL_CLOSE_SELECTED task_id=%s clip_order=%s end=%.2f changed=false reason=narrative_closure_weak_bts_adjacent",
            task_id, clip_order, end_s,
        )
        return

    best_end = None
    best_score = 0.0
    best_word = ""
    for idx, w in enumerate(zone):
        if w["e"] <= end_s + 0.4 or w["e"] > effective_max:
            continue
        nxt = zone[idx + 1] if idx + 1 < len(zone) else None
        gap = (nxt["s"] - w["e"]) if nxt else 1.0
        punct = str(w["t"]).rstrip().endswith(_STRONG_CLOSE_PUNCT)
        if punct and gap >= 0.3:
            score = 1.0
        elif punct and gap >= 0.15:
            score = 0.85
        elif punct:
            score = 0.7
        elif gap >= 0.8:
            score = 0.6
        else:
            continue
        # Prefer the EARLIEST solid closure: extend for closure, never for length.
        if best_end is None or score > best_score + 0.1:
            best_score = score
            best_end = min(effective_max, w["e"] + min(0.25, max(0.1, gap / 2)))
            best_word = w["t"]
            if score >= 0.99:
                break

    if best_end is not None and best_score >= 0.6:
        extended = best_end - end_s
        preview = " ".join(w["t"] for w in words if end_s - 0.3 <= w["s"] < best_end)[:160]
        if contrast_setup and payoff_next:
            logger.info(
                "VPI_OUTPUT_NARRATIVE_PAYOFF_EXTENSION_FOUND task_id=%s clip_order=%s payoff=%s",
                task_id, clip_order, preview[:90],
            )
        segment["narrative_final_end_s"] = round(best_end, 2)
        segment["narrative_extended_seconds"] = round(extended, 2)
        segment["narrative_closure_reason"] = (
            "contrast_payoff_completed" if (contrast_setup and payoff_next) else "open_connector_closed"
        )
        segment["narrative_closure_preview"] = preview
        segment["narrative_payoff_detected"] = bool(contrast_setup and payoff_next)
        segment["narrative_closure_confidence"] = round(min(1.0, best_score), 2)
        segment["end_time"] = _format_mmss_precise(best_end)
        segment["refined_end_time"] = segment["end_time"]
        segment["clean_final_end_s"] = round(best_end, 2)
        logger.info(
            "VPI_OUTPUT_NARRATIVE_CLOSURE_EXTENDED task_id=%s clip_order=%s old_end=%.2f new_end=%.2f extended=%.2f closure_word=%s",
            task_id, clip_order, end_s, best_end, extended, best_word[:24],
        )
        logger.info(
            "VPI_OUTPUT_NARRATIVE_FINAL_CLOSE_SELECTED task_id=%s clip_order=%s end=%.2f changed=true reason=%s preview=%s",
            task_id, clip_order, best_end, segment["narrative_closure_reason"], preview[:90],
        )
        return

    segment["narrative_final_end_s"] = round(end_s, 2)
    segment["narrative_extended_seconds"] = 0.0
    segment["narrative_closure_reason"] = "narrative_closure_weak"
    segment["narrative_payoff_detected"] = bool(contrast_setup and payoff_next)
    segment["narrative_closure_confidence"] = 0.3
    segment["needs_review_reason"] = "narrative_closure_weak"
    segment["narrative_closure_weak"] = True
    logger.info(
        "VPI_OUTPUT_NARRATIVE_FINAL_CLOSE_SELECTED task_id=%s clip_order=%s end=%.2f changed=false reason=narrative_closure_weak",
        task_id, clip_order, end_s,
    )


# ── OUTPUT-SELECTION-10: clean opening planner ────────────────────────────────
_NARRATIVE_WEAK_START_CONNECTORS = (
    "y", "pero", "porque", "por eso", "precisamente", "entonces", "ahi",
    "eso", "este tipo", "tambien", "sino", "que", "es decir", "ademas",
)
_NARRATIVE_OPENING_BLOCK_PHRASES = (
    "hola", "hoy vengo a hablarte", "hoy vengo a hablar", "bienvenidos",
    "perdon", "me equivoque", "otra vez", "no no", "vamos de nuevo",
    "lo digo otra vez", "repito",
)


def _normalize_text_hard(text: str) -> str:
    """Accent- and punctuation-stripping normalizer: 'Perdón.' -> 'perdon'.

    _normalize_text_loose keeps accents and punctuation, so phrase screens
    against unaccented phrase lists silently fail on real Whisper tokens.
    """
    import re as _re
    import unicodedata as _ud
    decomposed = _ud.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not _ud.combining(ch))
    ascii_text = _re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return _re.sub(r"\s+", " ", ascii_text).strip()


def _apply_narrative_opening_planner(
    *,
    task_id: str,
    segment: Dict[str, Any],
    cached_words: Optional[List[Dict[str, Any]]],
    clip_order: int = 0,
    video_duration_s: Optional[float] = None,
) -> None:
    """Symmetric counterpart of the narrative closure planner for the OPENING.

    A clip must not start mid-sentence or on an open connector ("Y…", "Por
    eso…", "del pasaje, para que…").  When the start is weak it extends
    backwards 0.3-8.5s to the nearest autonomous sentence start — unless the
    backward zone contains backstage/meta/greeting/retake material — and falls
    back to a forward trim to the next clean sentence start.  If neither works
    the segment is flagged needs_review reason=opening_context_weak.  Runs
    BEFORE the post-trim caption contract so captions stay aligned, and the
    hook is burned relative to the final start so it stays in the first 3s.
    """
    start_s = parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
    end_s = parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
    if end_s <= start_s:
        return
    words: List[Dict[str, Any]] = []
    for w in cached_words or []:
        ws = _word_time_seconds(w, "start")
        we = _word_time_seconds(w, "end")
        token = str(w.get("text") or "").strip()
        if ws is None or we is None or not token:
            continue
        words.append({"s": ws, "e": we, "t": token})
    if not words:
        logger.info(
            "VPI_OUTPUT_NARRATIVE_OPENING_AUDIT task_id=%s clip_order=%s result=skipped reason=no_word_timings",
            task_id, clip_order,
        )
        return
    words.sort(key=lambda x: x["s"])
    in_window = [w for w in words if w["s"] >= start_s - 0.02 and w["s"] < end_s]
    if not in_window:
        logger.info(
            "VPI_OUTPUT_NARRATIVE_OPENING_AUDIT task_id=%s clip_order=%s result=skipped reason=no_words_in_window",
            task_id, clip_order,
        )
        return

    first = in_window[0]
    first_raw = str(first["t"]).strip().lstrip("¿¡\"'(")
    first_norm = _normalize_text_hard(first["t"])
    head_norm = " ".join(_normalize_text_hard(w["t"]) for w in in_window[:3])
    prev = next((w for w in reversed(words) if w["e"] <= first["s"] + 0.01 and w["s"] < first["s"]), None)
    prev_has_punct = bool(prev) and str(prev["t"]).rstrip().endswith(_STRONG_CLOSE_PUNCT)
    gap_before = (first["s"] - prev["e"]) if prev else 10.0

    lowercase_start = bool(first_raw) and first_raw[0].isalpha() and first_raw[0].islower()
    midsentence_before = bool(prev) and not prev_has_punct and gap_before < 0.6
    connector_start = any(
        head_norm.startswith(ph) for ph in _NARRATIVE_WEAK_START_CONNECTORS
    ) and first_norm not in ("yo",)
    weak_start = lowercase_start or midsentence_before or connector_start

    logger.info(
        "VPI_OUTPUT_SELECTION_10B_HARD_NORMALIZER_APPLIED screens=classify_line|s6_tail|s6_forward|closure_tail|closure_zone|opening_zone"
    )
    logger.info(
        "VPI_OUTPUT_NARRATIVE_OPENING_AUDIT task_id=%s clip_order=%s start=%.2f first_word=%s lowercase=%s midsentence_before=%s connector=%s weak=%s",
        task_id, clip_order, start_s, first["t"][:24],
        str(lowercase_start).lower(), str(midsentence_before).lower(),
        str(connector_start).lower(), str(weak_start).lower(),
    )
    segment["narrative_pre_start_s"] = round(start_s, 2)
    if not weak_start:
        segment["narrative_final_start_s"] = round(start_s, 2)
        segment["narrative_opening_shift_seconds"] = 0.0
        segment["narrative_opening_reason"] = "already_clean"
        segment["narrative_opening_confidence"] = 0.9
        segment["opening_context_weak"] = False
        logger.info(
            "VPI_OUTPUT_NARRATIVE_FINAL_OPENING_SELECTED task_id=%s clip_order=%s start=%.2f changed=false reason=already_clean",
            task_id, clip_order, start_s,
        )
        return

    logger.info(
        "VPI_OUTPUT_NARRATIVE_OPEN_START_DETECTED task_id=%s clip_order=%s head=%s",
        task_id, clip_order, " ".join(w["t"] for w in in_window[:6])[:80],
    )

    def _zone_blocked(z_start: float, z_end: float) -> bool:
        zone_norm = " ".join(
            _normalize_text_hard(w["t"])
            for w in words if z_start - 0.05 <= w["s"] < z_end
        )
        padded = f" {zone_norm} "
        return any(f" {ph} " in padded or padded.strip().startswith(ph) for ph in _NARRATIVE_OPENING_BLOCK_PHRASES) or any(
            ph in zone_norm for ph in _BACKSTAGE_PHRASES
        ) or any(ph in zone_norm for ph in _NARRATIVE_META_PHRASES)

    def _is_sentence_start(idx_word: Dict[str, Any]) -> bool:
        w_prev = next((w for w in reversed(words) if w["e"] <= idx_word["s"] + 0.01 and w["s"] < idx_word["s"]), None)
        if w_prev is None:
            return True
        w_gap = idx_word["s"] - w_prev["e"]
        return (str(w_prev["t"]).rstrip().endswith(_STRONG_CLOSE_PUNCT) and w_gap >= 0.05) or w_gap >= 0.7

    def _starts_weak(idx: int, seq: List[Dict[str, Any]]) -> bool:
        head = " ".join(_normalize_text_hard(w["t"]) for w in seq[idx:idx + 3])
        return any(head.startswith(ph) for ph in _NARRATIVE_WEAK_START_CONNECTORS)

    # 1) Backward extension: nearest autonomous sentence start within 0.3-8.5s.
    back_zone = [w for w in words if start_s - 8.5 <= w["s"] < start_s - 0.25]
    new_start = None
    candidate_reason = ""
    confidence = 0.0
    for idx in range(len(back_zone) - 1, -1, -1):
        w = back_zone[idx]
        if not _is_sentence_start(w):
            continue
        if _starts_weak(idx, back_zone):
            continue
        if _zone_blocked(w["s"], start_s):
            logger.info(
                "VPI_OUTPUT_NARRATIVE_OPENING_BLOCKED_BY_BTS task_id=%s clip_order=%s zone=%.2f-%.2f",
                task_id, clip_order, w["s"], start_s,
            )
            break
        new_start = max(0.0, w["s"] - 0.15)
        candidate_reason = "backward_extension_to_sentence_start"
        confidence = 0.85
        logger.info(
            "VPI_OUTPUT_NARRATIVE_OPENING_BACKWARD_EXTENSION_FOUND task_id=%s clip_order=%s new_start=%.2f shift=%.2f first=%s",
            task_id, clip_order, new_start, start_s - new_start, w["t"][:24],
        )
        break

    # 2) Forward trim fallback: drop the orphan fragment up to the next clean start.
    if new_start is None:
        clip_dur = end_s - start_s
        # OUTPUT-SELECTION-10B: cap raised 6s/40% -> 8s/45% (a clean opening a
        # couple of seconds further in beats keeping a mid-sentence fragment);
        # the >=8s remaining-clip guard below still protects short clips.
        fwd_cap = min(8.0, clip_dur * 0.45)
        fwd_limit = start_s + fwd_cap
        segment["opening_forward_trim_cap_s"] = round(fwd_cap, 2)
        logger.info(
            "VPI_OUTPUT_SELECTION_10B_FORWARD_TRIM_CAP task_id=%s clip_order=%s cap=%.2f clip_dur=%.2f",
            task_id, clip_order, fwd_cap, clip_dur,
        )
        fwd_zone = [w for w in in_window if w["s"] > start_s + 0.2 and w["s"] <= fwd_limit]
        for idx, w in enumerate(fwd_zone):
            if not _is_sentence_start(w):
                continue
            if _starts_weak(idx, fwd_zone):
                continue
            if end_s - w["s"] < 8.0:
                break
            new_start = max(start_s, w["s"] - 0.15)
            candidate_reason = "forward_trim_to_sentence_start"
            confidence = 0.75
            segment["opening_forward_trim_applied_s"] = round(new_start - start_s, 2)
            segment["opening_forward_trim_reason"] = "orphan_fragment_dropped_to_sentence_start"
            logger.info(
                "VPI_OUTPUT_NARRATIVE_OPENING_FORWARD_TRIM_EXTENDED task_id=%s clip_order=%s trim=%.2f new_start=%.2f first=%s",
                task_id, clip_order, new_start - start_s, new_start, w["t"][:24],
            )
            break

    if new_start is None:
        segment["narrative_final_start_s"] = round(start_s, 2)
        segment["narrative_opening_shift_seconds"] = 0.0
        segment["narrative_opening_reason"] = "opening_context_weak"
        segment["narrative_opening_confidence"] = 0.3
        segment["opening_context_weak"] = True
        segment["needs_review_reason"] = "opening_context_weak"
        logger.info(
            "VPI_OUTPUT_NARRATIVE_OPENING_CONTEXT_WEAK task_id=%s clip_order=%s start=%.2f",
            task_id, clip_order, start_s,
        )
        logger.info(
            "VPI_OUTPUT_NARRATIVE_FINAL_OPENING_SELECTED task_id=%s clip_order=%s start=%.2f changed=false reason=opening_context_weak",
            task_id, clip_order, start_s,
        )
        return

    shift = new_start - start_s
    preview = " ".join(w["t"] for w in words if new_start - 0.05 <= w["s"] <= new_start + 4.0)[:120]
    segment["narrative_final_start_s"] = round(new_start, 2)
    segment["narrative_opening_shift_seconds"] = round(shift, 2)
    segment["narrative_opening_reason"] = candidate_reason
    segment["narrative_opening_preview"] = preview
    segment["narrative_opening_confidence"] = round(confidence, 2)
    segment["opening_context_weak"] = False
    segment["start_time"] = _format_mmss_precise(new_start)
    segment["refined_start_time"] = segment["start_time"]
    segment["clean_final_start_s"] = round(new_start, 2)
    logger.info(
        "VPI_OUTPUT_NARRATIVE_OPENING_EXTENDED task_id=%s clip_order=%s old_start=%.2f new_start=%.2f shift=%.2f reason=%s",
        task_id, clip_order, start_s, new_start, shift, candidate_reason,
    )
    logger.info(
        "VPI_OUTPUT_NARRATIVE_FINAL_OPENING_SELECTED task_id=%s clip_order=%s start=%.2f changed=true reason=%s preview=%s",
        task_id, clip_order, new_start, candidate_reason, preview[:90],
    )


def _build_post_trim_caption_contract(
    *,
    task_id: str,
    segment: Dict[str, Any],
    cached_words: Optional[List[Dict[str, Any]]],
    transcript_lines: List[Dict[str, Any]],
    clip_order: int = 0,
) -> None:
    """Single post-trim data contract feeding render, captions, ASS and metadata.

    Built for EVERY segment after S4/S5 boundary cleaning and before extraction,
    so downstream caption generation never re-derives words/text from a stale
    (pre-trim) window.
    """
    start_s = parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
    end_s = parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
    if end_s <= start_s:
        return

    post_words: List[Dict[str, Any]] = []
    for w in cached_words or []:
        ws = _word_time_seconds(w, "start")
        we = _word_time_seconds(w, "end")
        if ws is None or we is None:
            continue
        # Hard contract: no words before the clean start or after the clean end.
        if ws < start_s - 0.02 or we > end_s + 0.02:
            continue
        token = str(w.get("text") or "").strip()
        if not token:
            continue
        post_words.append({
            "word": token,
            "absolute_start_s": round(ws, 3),
            "absolute_end_s": round(we, 3),
            "start": round(max(0.0, ws - start_s), 3),
            "end": round(max(0.0, we - start_s), 3),
            "confidence": float(w.get("confidence") or 0.9),
        })

    if post_words:
        text = " ".join(w["word"] for w in post_words).strip()
        source = "post_selection_clean_window"
        logger.info(
            "VPI_OUTPUT_SELECTION_POST_TRIM_CAPTION_WORDS_FILTERED task_id=%s clip_order=%s words=%d window=%.2f-%.2f",
            task_id, clip_order, len(post_words), start_s, end_s,
        )
        logger.info(
            "VPI_OUTPUT_SELECTION_POST_TRIM_CAPTION_TEXT_REBUILT task_id=%s clip_order=%s chars=%d preview=%s",
            task_id, clip_order, len(text), text[:90],
        )
    else:
        # Fallback: post-trim line-level text — NEVER the stale pre-trim text.
        kept_lines = [
            line for line in transcript_lines
            if float(line.get("end", 0.0)) > start_s + 0.05 and float(line.get("start", 0.0)) < end_s - 0.05
        ]
        text = " ".join(str(l.get("text") or "").strip() for l in kept_lines).strip()
        source = "post_trim_line_text" if text else "none"
        logger.info(
            "VPI_OUTPUT_SELECTION_POST_TRIM_CAPTION_CONTRACT_EMPTY task_id=%s clip_order=%s fallback=%s",
            task_id, clip_order, source,
        )

    segment["post_trim_caption_words"] = post_words
    segment["post_trim_caption_text"] = text
    segment["post_trim_start_s"] = round(start_s, 3)
    segment["post_trim_end_s"] = round(end_s, 3)
    segment["post_trim_source"] = source
    segment["post_trim_caption_words_count"] = len(post_words)
    segment["post_trim_caption_first_word"] = post_words[0]["word"] if post_words else ""
    segment["post_trim_caption_last_word"] = post_words[-1]["word"] if post_words else ""
    segment["post_trim_caption_text_preview"] = text[:160]
    segment["post_trim_caption_source"] = source
    segment["caption_words_relative_to"] = "clean_final_start_s"
    if text:
        segment["text"] = text
    logger.info(
        "VPI_OUTPUT_SELECTION_POST_TRIM_CAPTION_CONTRACT_BUILT task_id=%s clip_order=%s words=%d source=%s first=%s last=%s relative_to=clean_final_start_s",
        task_id, clip_order, len(post_words), source,
        segment["post_trim_caption_first_word"][:24],
        segment["post_trim_caption_last_word"][:24],
    )


def _build_publishable_qc(
    segment: Dict[str, Any],
    clip_info: Dict[str, Any],
    *,
    strict_mode: bool = False,
    vpi_productive_minimum: bool = False,
) -> Dict[str, Any]:
    segment = _as_dict(segment)
    clip_info = _as_dict(clip_info)
    text = str(clip_info.get("text") or segment.get("text") or "").strip()
    words = [w for w in re.split(r"\s+", text) if w]
    final_path = Path(str(clip_info.get("path") or ""))
    final_render_contract = _as_dict(clip_info.get("final_rendered_contract"))
    final_mp4_contract = _as_dict(clip_info.get("final_mp4_contract")) or final_render_contract
    if final_mp4_contract:
        final_render_contract = final_mp4_contract
    duration = float(clip_info.get("duration") or final_render_contract.get("duration") or 0.0)
    final_exists = bool(final_render_contract.get("render_success")) if final_render_contract else final_path.exists()
    hook_plan = _as_dict(clip_info.get("hook_plan")) or _as_dict(_as_dict(clip_info.get("editing_plan")).get("hook_plan"))
    _comp_decision = _as_dict(_as_dict(clip_info.get("editing_plan")).get("composition_decision"))
    _comp_layers_final = list(_comp_decision.get("layers_final") or [])
    composition_hook_overlay_applied = bool("hook_overlay" in _comp_layers_final)
    _caption_overlay_pack = _as_dict(clip_info.get("caption_overlay_pack"))
    _ass_hook_injected = bool(
        _caption_overlay_pack.get("ass_hook_overlay_injected")
        or _caption_overlay_pack.get("first3_hook_overlay_forced")
        or bool((_caption_overlay_pack.get("hook_overlay") or {}).get("first3_hook_overlay_forced"))
    )
    _ass_hook_in_first3 = False
    _first_caption_in_first3 = False
    _ass_debug_path = str(clip_info.get("caption_ass_debug_path") or "")
    if _ass_debug_path:
        try:
            _ass_file_path = Path(_ass_debug_path)
            if _ass_file_path.exists():
                for _ass_line in _ass_file_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not _ass_line.startswith("Dialogue:"):
                        continue
                    _ass_parts = _ass_line.split(",", 9)
                    if len(_ass_parts) < 4:
                        continue
                    try:
                        _h, _m, _s = _ass_parts[1].strip().split(":")
                        _start_s = int(_h) * 3600 + int(_m) * 60 + float(_s)
                    except Exception:
                        continue
                    if _start_s > 3.0:
                        continue
                    _ass_style = _ass_parts[3].strip() if len(_ass_parts) > 3 else ""
                    if _ass_style == "HookOverlay":
                        _ass_hook_in_first3 = True
                    elif _ass_style == "Default" and not _first_caption_in_first3:
                        _first_caption_in_first3 = True
        except Exception:
            pass
    final_contract = _as_dict(clip_info.get("final_contract"))
    broll_metadata = _as_dict(clip_info.get("broll_metadata")) or _as_dict(final_render_contract.get("broll_metadata")) or _as_dict(final_contract.get("broll_metadata"))
    broll_items = [
        item
        for item in _as_list(
            broll_metadata.get("items")
            or clip_info.get("broll_items")
            or segment.get("broll_items")
            or clip_info.get("editorial_broll")
            or final_render_contract.get("broll_items")
            or final_contract.get("broll_items")
        )
        if isinstance(item, dict)
    ]
    music_meta = _as_dict(clip_info.get("music"))
    sfx_meta = _as_dict(clip_info.get("sfx"))
    motion_meta = _as_dict(clip_info.get("motion_overlay"))
    transition_meta = _as_dict(clip_info.get("transitions"))
    visual_fx_meta = _as_dict(clip_info.get("visual_effects"))
    silence_meta = _as_dict(clip_info.get("silence_edit_plan"))
    subtitle_meta = _as_dict(clip_info.get("subtitle_intelligence"))
    final_contract_ok = bool(clip_info.get("final_contract_ok", True))
    if final_mp4_contract:
        final_contract_ok = bool(final_mp4_contract.get("final_publishable", final_contract_ok))
    # H13.17: bypass final_contract_ok=False when the ONLY blocking reasons are
    # {final_qc_failed, final_qc_severe} (QC echo from inner temp-path contract)
    # and the technical output is fully verified. These QC signals are independently
    # re-evaluated by this function via hook_first_3s, subtitles_present, etc.
    _inner_qc_only_blocking: set = set(
        str(x) for x in (final_mp4_contract.get("final_blocking_reasons") or []) if str(x)
    ) if (final_mp4_contract and not final_contract_ok) else set()
    _inner_contract_qc_only_fail = bool(
        not final_contract_ok
        and final_mp4_contract
        and bool(final_mp4_contract.get("final_output_verified"))
        and bool(final_mp4_contract.get("final_probe_ok"))
        and (bool(final_mp4_contract.get("final_video_exists")) or bool(final_mp4_contract.get("render_success")))
        and bool(final_mp4_contract.get("final_audio_stream_ok"))
        and bool(final_mp4_contract.get("final_duration_ok"))
        and bool(_inner_qc_only_blocking)
        and _inner_qc_only_blocking.issubset({"final_qc_failed", "final_qc_severe"})
    )
    if _inner_contract_qc_only_fail:
        final_contract_ok = True
        logger.info(
            "VPI_PUBLISHABLE_QC_STRICT_PATH_GAP_DOWNGRADED_VERIFIED_OUTPUT task_id=%s clip_order=%d blocking_was=%s",
            str(clip_info.get("task_id") or segment.get("task_id") or "unknown"),
            int(clip_info.get("clip_index") or clip_info.get("clip_order") or 0),
            "|".join(sorted(_inner_qc_only_blocking)),
        )
    elif not final_contract_ok and final_mp4_contract:
        logger.info(
            "VPI_PUBLISHABLE_QC_STRICT_PATH_GAP_BLOCKING_REAL_ISSUE task_id=%s clip_order=%d blocking=%s verified=%s probe_ok=%s video_ok=%s audio_ok=%s duration_ok=%s",
            str(clip_info.get("task_id") or segment.get("task_id") or "unknown"),
            int(clip_info.get("clip_index") or clip_info.get("clip_order") or 0),
            "|".join(sorted(_inner_qc_only_blocking)) or "unknown",
            str(bool(final_mp4_contract.get("final_output_verified"))).lower(),
            str(bool(final_mp4_contract.get("final_probe_ok"))).lower(),
            str(bool(final_mp4_contract.get("final_video_exists") or final_mp4_contract.get("render_success"))).lower(),
            str(bool(final_mp4_contract.get("final_audio_stream_ok"))).lower(),
            str(bool(final_mp4_contract.get("final_duration_ok"))).lower(),
        )
    final_contract_checks = _as_dict(final_contract.get("final_contract"))
    if final_mp4_contract:
        final_contract_checks = _as_dict(final_mp4_contract.get("final_contract")) or final_contract_checks

    # ── FIX 8: Use premium_layers_applied if available (honest trace) ──────
    premium_applied_raw = clip_info.get("premium_layers_applied")
    premium_applied: Optional[List[str]] = premium_applied_raw if isinstance(premium_applied_raw, list) else None
    premium_skipped: Optional[Dict[str, str]] = clip_info.get("premium_layer_skip_reasons")
    if premium_applied is not None:
        # Override optimistic metadata with honest applied trace
        broll_applied_honest = "broll" in premium_applied
        hook_card_applied_honest = "hook_card" in premium_applied
        semantic_card_applied_honest = "semantic_card" in premium_applied
        motion_pack_applied_honest = "motion_pack" in premium_applied
        bgm_applied_honest = "bgm" in premium_applied
        sfx_applied_honest = "sfx" in premium_applied
        rhythm_applied_honest = "rhythm" in premium_applied
        transition_applied_honest = "transition" in premium_applied
        vfx_applied_honest = "vfx" in premium_applied
        speaker_focus_applied_honest = "speaker_focus" in premium_applied
        branding_applied_honest = "branding" in premium_applied
        captions_applied_honest = "captions" in premium_applied
        audio_mastering_applied_honest = "audio_mastering" in premium_applied
    else:
        broll_applied_honest = None
        hook_card_applied_honest = None
        semantic_card_applied_honest = None
        motion_pack_applied_honest = None
        bgm_applied_honest = None
        sfx_applied_honest = None
        rhythm_applied_honest = None
        transition_applied_honest = None
        vfx_applied_honest = None
        speaker_focus_applied_honest = None
        branding_applied_honest = None
        captions_applied_honest = None
        audio_mastering_applied_honest = None
    # ── End FIX 8 ──────────────────────────────────────────────────────────

    complete_idea = bool(
        len(words) >= 12
        and (_has_content_terms(text) or str(segment.get("editorial_type") or "") not in {"weak_intro", ""})
    )
    no_mid_sentence_cut = _is_sentence_end(text) or (len(words) >= 20 and duration >= 18.0)
    hook_score_first3 = int(hook_plan.get("hook_first3_score") or 0)
    hook_score_first4 = int(hook_plan.get("hook_first_4s_score") or 0)
    hook_score_first3_planned = int(hook_plan.get("hook_first3_score_planned") or 0)
    strong_verbal_hook = bool(
        hook_score_first3 >= 7 or (hook_score_first3 >= 6 and hook_score_first4 >= 2)
    )
    strong_verbal_hook_planned = bool(
        hook_score_first3_planned >= 7 and bool(words)
    )
    hook_overlay_applied = bool(
        hook_plan.get("overlay_rendered")
        or hook_plan.get("kickframe_applied")
        or motion_meta.get("dynamic_overlay_card_composed")
        or composition_hook_overlay_applied
        or _ass_hook_injected
        or _ass_hook_in_first3
    )
    hook_ok = bool(
        strong_verbal_hook
        or strong_verbal_hook_planned
        or hook_overlay_applied
        or motion_meta.get("motion_overlay_applied")
        or _first_caption_in_first3
    )
    _hook_evidence_source = ""
    _tid = str(clip_info.get("task_id") or segment.get("task_id") or "unknown")
    if composition_hook_overlay_applied:
        logger.info(
            "VPI_HOOK_FIRST_3S_COMPOSITION_PACK_SIGNAL_DETECTED task_id=%s layers_final=%s hook_ok=%s",
            _tid,
            "|".join(_comp_layers_final),
            str(hook_ok).lower(),
        )
        if hook_ok:
            _hook_evidence_source = "composition_pack_hook_overlay"
            logger.info(
                "VPI_HOOK_FIRST_3S_SIGNAL_GAP_CLOSED task_id=%s evidence_source=%s",
                _tid,
                _hook_evidence_source,
            )
    if _ass_hook_injected and not _hook_evidence_source:
        _hook_evidence_source = "daily_mode_first3_hook_overlay"
        _first3_forced_text = str(
            (_caption_overlay_pack.get("hook_overlay") or {}).get("first3_hook_overlay_text") or ""
        )
        logger.info(
            "VPI_HOOK_FIRST_3S_SIGNAL_GAP_CLOSED task_id=%s evidence_source=%s text=%s hook_ok=%s",
            _tid,
            _hook_evidence_source,
            _first3_forced_text,
            str(hook_ok).lower(),
        )
    if _ass_hook_in_first3 and not _hook_evidence_source:
        _hook_evidence_source = "ass_hook_overlay_first3"
        logger.info(
            "VPI_HOOK_FIRST_3S_ASS_HOOK_OVERLAY_DETECTED task_id=%s evidence_source=%s hook_ok=%s",
            _tid,
            _hook_evidence_source,
            str(hook_ok).lower(),
        )
    if _first_caption_in_first3 and not _hook_evidence_source:
        _hook_evidence_source = "first_caption_visible_first3"
        logger.info(
            "VPI_HOOK_FIRST_3S_ASS_HOOK_OVERLAY_DETECTED task_id=%s evidence_source=%s hook_ok=%s",
            _tid,
            _hook_evidence_source,
            str(hook_ok).lower(),
        )
    if strong_verbal_hook_planned and not _hook_evidence_source:
        _hook_evidence_source = "propagated_hook_first3_score"
        logger.info(
            "VPI_HOOK_FIRST_3S_SCORE_PROPAGATED_TO_QC task_id=%s planned_score=%d post_render_score=%d hook_ok=%s",
            _tid,
            hook_score_first3_planned,
            hook_score_first3,
            str(hook_ok).lower(),
        )
    if hook_ok and _hook_evidence_source:
        logger.info(
            "VPI_HOOK_FIRST_3S_QC_SCORE_ALIGNED task_id=%s evidence_source=%s",
            _tid,
            _hook_evidence_source,
        )
    if not hook_ok:
        logger.info(
            "VPI_HOOK_FIRST_3S_QC_SCORE_REMAINS_FAIL_NO_VISUAL_EVIDENCE task_id=%s strong_verbal=%s planned_score=%d post_render_score=%d ass_hook=%s caption_first3=%s overlay=%s",
            _tid,
            str(strong_verbal_hook).lower(),
            hook_score_first3_planned,
            hook_score_first3,
            str(_ass_hook_in_first3).lower(),
            str(_first_caption_in_first3).lower(),
            str(bool(
                hook_plan.get("overlay_rendered")
                or hook_plan.get("kickframe_applied")
                or motion_meta.get("dynamic_overlay_card_composed")
            )).lower(),
        )
        logger.info(
            "VPI_HOOK_FIRST_3S_NO_SIGNAL_FOUND task_id=%s strong_verbal=%s overlay=%s composition_hook=%s score=%d",
            _tid,
            str(strong_verbal_hook).lower(),
            str(bool(
                hook_plan.get("overlay_rendered")
                or hook_plan.get("kickframe_applied")
                or motion_meta.get("dynamic_overlay_card_composed")
            )).lower(),
            str(composition_hook_overlay_applied).lower(),
            hook_score_first3,
        )
    subtitles_present = bool(
        clip_info.get("caption_ass_debug_path")
        or clip_info.get("words")
        or subtitle_meta.get("rendered")
    )

    # ── FIX 8: Use premium_layers_applied if available (honest trace) ──────
    # Override optimistic metadata with actual applied status from the trace.
    # This prevents the strict QC from rejecting clips that had layers planned
    # but not actually rendered, and vice versa.
    if broll_applied_honest is not None:
        broll_applied = broll_applied_honest
    else:
        broll_applied = bool(broll_items)

    if motion_pack_applied_honest is not None:
        motion_overlay_applied = motion_pack_applied_honest
    else:
        motion_overlay_applied = bool(motion_meta.get("motion_overlay_applied"))

    if hook_card_applied_honest is not None:
        hook_card_applied = hook_card_applied_honest
    else:
        hook_card_applied = bool(hook_plan.get("overlay_rendered") or hook_plan.get("kickframe_applied"))

    if semantic_card_applied_honest is not None:
        semantic_card_applied = semantic_card_applied_honest
    else:
        semantic_card_applied = bool(motion_meta.get("dynamic_overlay_card_composed"))

    if bgm_applied_honest is not None:
        music_applied = bgm_applied_honest
    else:
        music_applied = bool(music_meta.get("music_applied"))

    if sfx_applied_honest is not None:
        sfx_applied = sfx_applied_honest
    else:
        sfx_applied = bool(sfx_meta.get("sfx_applied")) and int(
            sfx_meta.get("sfx_count") or len(sfx_meta.get("sfx_events") or [])
        ) > 0

    if rhythm_applied_honest is not None:
        rhythm_cleanup_applied = rhythm_applied_honest
    else:
        rhythm_cleanup_applied = bool(silence_meta.get("rendered"))

    if transition_applied_honest is not None:
        transitions_applied = transition_applied_honest
    else:
        transitions_applied = bool(
            transition_meta.get("transitions_applied")
            or transition_meta.get("final_output_uses_transition")
        )

    if vfx_applied_honest is not None:
        motion_or_masking_applied = vfx_applied_honest
    else:
        motion_or_masking_applied = bool(
            visual_fx_meta.get("visual_effects_applied")
            or visual_fx_meta.get("mask_reveal_applied")
            or visual_fx_meta.get("final_output_uses_vfx")
        )

    if captions_applied_honest is not None:
        subtitles_present = captions_applied_honest
    else:
        subtitles_present = bool(
            clip_info.get("caption_ass_debug_path")
            or clip_info.get("words")
            or subtitle_meta.get("rendered")
        )
    if final_render_contract:
        subtitles_present = bool(final_render_contract.get("has_captions", subtitles_present))

    # ── Derived signals (always computed from the (possibly overridden) values above) ──
    # Override final_output_uses_bgm from premium_layers_applied if available
    if bgm_applied_honest is not None:
        final_output_uses_bgm = bgm_applied_honest
    else:
        final_output_uses_bgm = bool(
            music_meta.get("final_output_uses_bgm")
            or clip_info.get("final_output_uses_music")
            or final_contract_checks.get("music")
            or music_meta.get("music_final_verified")
        )
    if final_render_contract:
        final_output_uses_bgm = bool(final_render_contract.get("has_bgm", final_output_uses_bgm))
    music_track_ref = str(
        music_meta.get("music_track")
        or music_meta.get("bgm_asset_path")
        or music_meta.get("selected_track")
        or ""
    ).strip()
    bgm_status = "applied" if music_applied else ("skipped" if music_meta else "missing")
    bgm_skip_reason = str(
        music_meta.get("music_warning")
        or music_meta.get("music_status")
        or music_meta.get("skip_reason")
        or ""
    ).strip()
    bgm_skip_explicit_ok = (
        (not music_applied)
        and bool(bgm_skip_reason)
        and (
            "missing_library" in bgm_skip_reason.lower()
            or "duration_unavailable" in bgm_skip_reason.lower()
            or "intentional_skip" in bgm_skip_reason.lower()
            or "tone_mismatch" in bgm_skip_reason.lower()
            or "voice_intelligibility_risk" in bgm_skip_reason.lower()
        )
    )

    final_output_uses_motion_overlay = bool(
        motion_meta.get("final_output_uses_motion_overlay")
        or clip_info.get("final_output_uses_vfx")
        or final_contract_checks.get("vfx")
    )
    if final_render_contract:
        final_output_uses_motion_overlay = bool(
            final_render_contract.get("has_motion_or_vfx", final_output_uses_motion_overlay)
        )
    overlay_card_applied = bool(
        motion_meta.get("dynamic_overlay_card_composed")
        or hook_plan.get("overlay_rendered")
    )
    semantic_icon_overlay_applied = bool(
        motion_overlay_applied
        and str(motion_meta.get("motion_overlay_asset_id") or "").startswith("generated_icon_")
    )
    # Check output_qc for watermark and reframe/highlights evidence
    output_qc = _as_dict(clip_info.get("output_qc"))
    watermark_applied = bool(output_qc.get("watermark"))
    reframe_applied = bool(output_qc.get("reframe"))
    highlights_count = int(output_qc.get("highlights") or 0)
    # Check speaker_focus evidence
    speaker_focus_meta = _as_dict(clip_info.get("speaker_focus"))
    speaker_focus_applied = bool(speaker_focus_meta.get("speaker_focus_enhanced"))
    # Check branding evidence
    brand_treatment = _as_dict(clip_info.get("brand_treatment"))
    branding_applied = bool(brand_treatment.get("rendered"))
    if final_render_contract:
        branding_applied = bool(final_render_contract.get("has_branding", branding_applied))
    # Check hook_card evidence (already have hook_card_applied from FIX 8)
    # Check semantic_card evidence (already have semantic_card_applied from FIX 8)
    visual_support_real = bool(
        broll_applied
        or (motion_overlay_applied and final_output_uses_motion_overlay)
        or overlay_card_applied
        or semantic_icon_overlay_applied
        or semantic_card_applied
        or hook_card_applied
        or motion_or_masking_applied
        or speaker_focus_applied
        or (branding_applied and watermark_applied)
        or (reframe_applied and highlights_count > 0)
        or bool(final_render_contract.get("has_broll"))
        or bool(final_render_contract.get("has_motion_or_vfx"))
        or bool(final_render_contract.get("has_branding"))
        or bool(final_render_contract.get("has_captions"))
    )

    sfx_skip_reason = str(
        sfx_meta.get("sfx_warning")
        or sfx_meta.get("sfx_status")
        or sfx_meta.get("skip_reason")
        or sfx_meta.get("reason")
        or ""
    ).strip()
    sfx_skip_explicit_ok = (
        not sfx_applied
        and bool(sfx_skip_reason)
        and (
            "no_editorial_event" in sfx_skip_reason.lower()
            or "no_event" in sfx_skip_reason.lower()
            or "no relevant event" in sfx_skip_reason.lower()
            or "no_sfx_moment" in sfx_skip_reason.lower()
            or "no_retention_gain" in sfx_skip_reason.lower()
            or "neutral_clarity" in sfx_skip_reason.lower()
            or "neutral_explanation_no_sfx" in sfx_skip_reason.lower()
            or "no_sfx_editorial_intent" in sfx_skip_reason.lower()
            or "tone_too_sensitive" in sfx_skip_reason.lower()
            or "budget_exhausted" in sfx_skip_reason.lower()
            or "no_motion_sfx_needed" in sfx_skip_reason.lower()
            or "blocked_by_tone" in sfx_skip_reason.lower()
        )
    )
    rhythm_skip_reason = ",".join(
        [str(x) for x in (silence_meta.get("warnings") or silence_meta.get("apply_warnings") or []) if x]
    ).strip()
    fillers_detected_at_start = bool(_is_setup_text(text))
    rhythm_skip_explicit_ok = (
        not rhythm_cleanup_applied
        and bool(rhythm_skip_reason)
        and rhythm_skip_reason.lower() not in {"not_applied", "none"}
        and not fillers_detected_at_start
    )
    retention_edit_applied = bool(
        transitions_applied
        or motion_overlay_applied
        or overlay_card_applied
        or motion_or_masking_applied
        or broll_applied
        or rhythm_cleanup_applied
        or hook_card_applied
        or semantic_card_applied
        or speaker_focus_applied
    )

    sfx_evidence = bool(
        sfx_applied
        or final_contract_checks.get("sfx")
        or clip_info.get("final_output_uses_sfx")
        or bool(final_render_contract.get("has_sfx"))
    )
    rhythm_evidence = bool(
        rhythm_cleanup_applied
        or transition_meta.get("shot_rhythm_applied")
        or ("rhythm" in (premium_applied or []))
        or bool(final_render_contract.get("has_rhythm_cleanup"))
        or bool(final_render_contract.get("has_motion_or_vfx"))
    )
    vfx_evidence = bool(
        motion_or_masking_applied
        or clip_info.get("final_output_uses_vfx")
        or final_contract_checks.get("vfx")
        or bool(final_render_contract.get("has_motion_or_vfx"))
    )

    real_editing_signals = {
        "hook": bool(hook_ok),
        "strong_verbal_hook": bool(strong_verbal_hook),
        "hook_overlay": bool(hook_overlay_applied),
        "visual_support": bool(visual_support_real),
        "broll": bool(broll_applied),
        "motion_overlay": bool(motion_overlay_applied and final_output_uses_motion_overlay),
        "overlay_card": bool(overlay_card_applied),
        "semantic_icon_overlay": bool(semantic_icon_overlay_applied),
        "bgm": bool(
            (music_applied and (final_output_uses_bgm or bool(music_track_ref)))
            or final_contract_checks.get("music")
            or bool(final_render_contract.get("has_bgm"))
        ),
        "sfx": bool(sfx_evidence),
        "sfx_skip_explicit_ok": bool(sfx_skip_explicit_ok),
        "rhythm": bool(rhythm_evidence),
        "rhythm_skip_explicit_ok": bool(rhythm_skip_explicit_ok),
        "motion_or_masking": bool(vfx_evidence),
        "transition": bool(transitions_applied),
        "retention_edit": bool(retention_edit_applied),
    }

    if broll_applied:
        visual_support_status = "broll"
    elif motion_overlay_applied and final_output_uses_motion_overlay:
        visual_support_status = "motion_overlay"
    elif overlay_card_applied:
        visual_support_status = "card"
    elif semantic_card_applied:
        visual_support_status = "semantic_card"
    elif hook_card_applied:
        visual_support_status = "hook_card"
    elif motion_or_masking_applied:
        visual_support_status = "vfx"
    elif speaker_focus_applied:
        visual_support_status = "speaker_focus"
    elif branding_applied and watermark_applied:
        visual_support_status = "branding"
    elif reframe_applied and highlights_count > 0:
        visual_support_status = "reframe_highlights"
    elif subtitles_present:
        visual_support_status = "minimal_overlay_only"
    else:
        visual_support_status = "none"

    qc = {
        "complete_idea": "pass" if complete_idea else "fail",
        "hook_first_3s": "pass" if hook_ok else "fail",
        "subtitles_present": "pass" if subtitles_present else "fail",
        "bgm_status": bgm_status,
        "visual_support_status": visual_support_status,
        "no_mid_sentence_cut": "pass" if no_mid_sentence_cut else "fail",
        "final_output_exists": "pass" if final_exists else "fail",
        "final_output_is_latest_stage": "pass" if (final_contract_ok and final_exists) else "fail",
        "duration_valid": "pass" if (10.0 <= duration <= 90.0) else "fail",
        "render_success": "pass",
        "broll_applied": broll_applied,
        "motion_overlay_applied": motion_overlay_applied,
        "final_output_uses_motion_overlay": final_output_uses_motion_overlay,
        "sfx_status": "applied" if sfx_applied else "skipped",
        "bgm_applied": music_applied,
        "final_output_uses_bgm": final_output_uses_bgm,
        "bgm_track_ref": music_track_ref,
        "bgm_skip_reason": bgm_skip_reason,
        "hook_overlay_applied": hook_overlay_applied,
        "composition_hook_overlay_applied": composition_hook_overlay_applied,
        "first3_hook_overlay_forced": bool(_ass_hook_injected),
        "captions_first3_absent_but_hook_overlay_present": bool(
            _caption_overlay_pack.get("captions_first3_absent_but_hook_overlay_present")
        ),
        "hook_first_3s_evidence_source": _hook_evidence_source,
        "strong_verbal_hook": strong_verbal_hook,
        "transitions_applied": transitions_applied,
        "motion_or_masking_applied": motion_or_masking_applied,
        "rhythm_cleanup_applied": rhythm_cleanup_applied,
        "rhythm_skip_reason": rhythm_skip_reason,
        "sfx_skip_reason": sfx_skip_reason,
        "fillers_detected_at_start": fillers_detected_at_start,
        "final_rendered_contract": final_render_contract,
        "real_editing_signals": real_editing_signals,
    }
    qc["final_output_not_latest_stage_downgraded"] = _inner_contract_qc_only_fail
    if _inner_contract_qc_only_fail:
        qc["strict_path_gap_only"] = True
        qc["final_output_not_latest_stage_downgrade_reason"] = "inner_temp_path_with_verified_final_output"

    strict_reasons: List[str] = []
    if not real_editing_signals["hook"]:
        strict_reasons.append("no_real_hook")
    if not real_editing_signals["visual_support"]:
        strict_reasons.append("no_real_visual_support")
    if qc["complete_idea"] != "pass":
        strict_reasons.append("complete_idea_failed")
    if qc["no_mid_sentence_cut"] != "pass":
        strict_reasons.append("mid_sentence_cut")
    if qc["final_output_is_latest_stage"] != "pass":
        strict_reasons.append("final_output_not_latest_stage")

    # ── VPI Productive Minimum: relaxed strict QC ──────────────────────────
    # When vpi_productive_minimum=True, only require hook + subtitles + basic
    # visual support. BGM, SFX, rhythm cleanup, and retention editing are
    # treated as nice-to-have but NOT hard requirements. This prevents the
    # strict QC from rejecting clips that have a hook, subtitles, and some
    # visual support but lack audio polish layers (which may not be available
    # in all environments, e.g. missing music assets, no SFX library, etc.).
    if not vpi_productive_minimum:
        if not real_editing_signals["bgm"] and not bgm_skip_explicit_ok:
            strict_reasons.append("no_perceptible_bgm_or_no_bgm_evidence")
        if not (real_editing_signals["sfx"] or real_editing_signals["sfx_skip_explicit_ok"]):
            strict_reasons.append("sfx_missing_without_reason")
        if not (
            real_editing_signals["rhythm"]
            or real_editing_signals["rhythm_skip_explicit_ok"]
            or bool(final_render_contract.get("has_motion_or_vfx"))
        ):
            strict_reasons.append("no_rhythm_cleanup_evidence")
        if not real_editing_signals["retention_edit"]:
            strict_reasons.append("no_retention_editing_applied")

    core_signals_count = sum(
        1 for key in ("hook", "visual_support", "bgm", "sfx", "rhythm", "retention_edit")
        if bool(real_editing_signals.get(key))
    )
    editing_zero_detected = bool(
        subtitles_present
        and (
            core_signals_count <= 1
            or (
                not real_editing_signals["visual_support"]
                and not real_editing_signals["bgm"]
                and not real_editing_signals["retention_edit"]
            )
        )
    )
    if editing_zero_detected and "editing_zero_detected" not in strict_reasons:
        strict_reasons.append("editing_zero_detected")

    qc["strict_publishable_reasons"] = strict_reasons
    qc["strict_publishable"] = len(strict_reasons) == 0
    qc["editing_zero_detected"] = editing_zero_detected
    if _inner_contract_qc_only_fail:
        qc.setdefault("strict_publishable_warnings", []).append("final_output_not_latest_stage_downgraded_inner_temp_path")

    hard_fail = (
        qc["final_output_exists"] == "fail"
        or qc["no_mid_sentence_cut"] == "fail"
        or qc["hook_first_3s"] == "fail"
        or qc["subtitles_present"] == "fail"
        or qc["final_output_is_latest_stage"] == "fail"
    )
    if strict_mode:
        qc["publishable"] = (not hard_fail) and bool(qc["strict_publishable"])
    else:
        qc["publishable"] = not hard_fail
    return qc


# ── H14.13 -- render-input replacement candidate source fix ────────────────
# VPI_EXPANSION_CANDIDATE_RENDER_INPUT_REPLACED (the candidate-pool-expansion
# render-input substitution loop below) must never assign a render slot to a
# candidate already tagged as a near-duplicate by H14.7 Fix C / H14.9 Fix A /
# H14.11's backfill skip-check, and must never assign two render slots to
# near-duplicate windows -- even if the pre-render editorial gate (evaluated
# over a stale, pre-dedupe candidate pool) approved both. Replacement
# candidates are sourced from result["segments_to_render"] -- the
# H14.9/H14.11-corrected list returned by video_service.py -- which is never
# mutated by the gate.

_H1413_PROHIBITED_DUPLICATE_REASONS = {
    "duplicate_window_overlap",
    "post_render_input_duplicate_window_overlap",
    "duplicate_theme_key",
}


def _h1413_is_duplicate_tagged(seg: Dict[str, Any]) -> Tuple[bool, str]:
    """Mirror video_service.py's H14.11 _h149_is_duplicate_rejected check.

    Returns (is_duplicate, basis). A candidate for which this returns
    is_duplicate=True must never be picked as a render-input replacement
    candidate, nor left in segments_to_render unreplaced.
    """
    if bool(seg.get("distinct_payoff")) or bool(seg.get("kept_distinct_payoff")):
        return (False, "")
    _reason = str(seg.get("rejected_for_reason") or "")
    if _reason in _H1413_PROHIBITED_DUPLICATE_REASONS:
        return (True, "rejected_for_reason")
    if "duplicate" in _reason and "overlap" in _reason:
        return (True, "rejected_for_reason")
    if seg.get("duplicate_of_candidate_id"):
        return (True, "duplicate_of_candidate_id")
    _stage = str(seg.get("post_render_dedupe_stage") or "")
    if "duplicate" in _stage:
        return (True, "post_render_dedupe_stage")
    _backfill_reason = str(seg.get("backfill_rejected_for_reason") or "")
    if "duplicate" in _backfill_reason:
        return (True, "backfill_rejected_for_reason")
    return (False, "")


def _h1413_window_overlap_ratio(seg_a: Dict[str, Any], seg_b: Dict[str, Any]) -> float:
    a_start = float(parse_timestamp_to_seconds(str(seg_a.get("start_time") or "00:00")) or 0.0)
    a_end = float(parse_timestamp_to_seconds(str(seg_a.get("end_time") or "00:00")) or 0.0)
    b_start = float(parse_timestamp_to_seconds(str(seg_b.get("start_time") or "00:00")) or 0.0)
    b_end = float(parse_timestamp_to_seconds(str(seg_b.get("end_time") or "00:00")) or 0.0)
    union = max(a_end, b_end) - min(a_start, b_start)
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    return (inter / union) if union > 0 else 0.0


def _h1413_text_similarity(seg_a: Dict[str, Any], seg_b: Dict[str, Any]) -> float:
    jaccard, coverage = _h1413_text_overlap_metrics(str(seg_a.get("text") or ""), str(seg_b.get("text") or ""))
    return max(jaccard, coverage)


def _h1413_filter_duplicate_tagged(segments: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Filter duplicate-tagged candidates out of a stale (pre-dedupe) candidate pool."""
    kept: List[Dict[str, Any]] = []
    removed = 0
    for seg in segments:
        is_dup, basis = _h1413_is_duplicate_tagged(seg)
        if is_dup:
            removed += 1
            logger.info(
                "VPI_RENDER_REPLACEMENT_DUPLICATE_CANDIDATE_SKIPPED phase=old_pool_filter start=%s end=%s "
                "candidate_id=%s basis=%s rejected_for_reason=%s duplicate_of_candidate_id=%s",
                seg.get("start_time"), seg.get("end_time"), seg.get("candidate_id"), basis,
                seg.get("rejected_for_reason"), seg.get("duplicate_of_candidate_id"),
            )
            continue
        kept.append(seg)
    return kept, removed


def _h1413_apply_render_replacement_dedupe(
    task_id: str,
    segments_to_render: List[Dict[str, Any]],
    deduped_pool: List[Dict[str, Any]],
    pool_source: str,
    num_clips: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """H14.13 Fix A/B/C.

    Returns (new_segments_to_render, info). `info` carries
    effective_clips_count_after_replacement_filter and (if any slot was
    dropped) render_replacement_skipped_reason="no_valid_non_duplicate_candidate".
    """
    info: Dict[str, Any] = {
        "effective_clips_count_after_replacement_filter": len(segments_to_render),
    }
    if int(num_clips) <= 1 or len(segments_to_render) <= 1:
        return segments_to_render, info

    def _seg_key(seg: Dict[str, Any]) -> Tuple[str, str, str]:
        return (str(seg.get("start_time") or ""), str(seg.get("end_time") or ""), str(seg.get("text") or "")[:80])

    available_replacements = [
        c for c in deduped_pool
        if isinstance(c, dict) and not _h1413_is_duplicate_tagged(c)[0]
    ]

    assigned: List[Dict[str, Any]] = []
    used_keys: set = set()
    any_dropped = False

    for idx, seg in enumerate(segments_to_render):
        is_dup_tagged, dup_basis = _h1413_is_duplicate_tagged(seg)
        dup_against_assigned = None
        if not is_dup_tagged:
            for a_idx, a_seg in enumerate(assigned):
                overlap = _h1413_window_overlap_ratio(seg, a_seg)
                text_sim = _h1413_text_similarity(seg, a_seg)
                if overlap > 0.65 and text_sim >= 0.50:
                    dup_against_assigned = (a_idx, overlap, text_sim)
                    break

        if not is_dup_tagged and dup_against_assigned is None:
            used_keys.add(_seg_key(seg))
            assigned.append(seg)
            logger.info(
                "VPI_RENDER_REPLACEMENT_CANDIDATE_AUDIT idx=%d replacement_candidate_id=%s "
                "replacement_source_pool=%s rejected_for_reason=%s duplicate_of_candidate_id=%s "
                "start=%s end=%s text_preview=%s passed_duplicate_filter=true",
                idx, seg.get("candidate_id"), "segments_to_render",
                seg.get("rejected_for_reason"), seg.get("duplicate_of_candidate_id"),
                seg.get("start_time"), seg.get("end_time"),
                str(seg.get("text") or "")[:60],
            )
            continue

        if is_dup_tagged:
            logger.info(
                "VPI_RENDER_REPLACEMENT_DUPLICATE_CANDIDATE_SKIPPED phase=final_segments idx=%d start=%s end=%s "
                "candidate_id=%s basis=%s rejected_for_reason=%s duplicate_of_candidate_id=%s",
                idx, seg.get("start_time"), seg.get("end_time"), seg.get("candidate_id"), dup_basis,
                seg.get("rejected_for_reason"), seg.get("duplicate_of_candidate_id"),
            )
        else:
            a_idx, overlap, text_sim = dup_against_assigned
            logger.info(
                "VPI_RENDER_REPLACEMENT_DUPLICATE_AGAINST_ASSIGNED_SKIPPED idx=%d start=%s end=%s "
                "assigned_idx=%d overlap=%.4f text_similarity=%.4f",
                idx, seg.get("start_time"), seg.get("end_time"), a_idx, overlap, text_sim,
            )

        replacement = None
        for cand in available_replacements:
            cand_key = _seg_key(cand)
            if cand_key in used_keys:
                continue
            dup_vs_assigned = False
            for a_seg in assigned:
                if _h1413_window_overlap_ratio(cand, a_seg) > 0.65 and _h1413_text_similarity(cand, a_seg) >= 0.50:
                    dup_vs_assigned = True
                    break
            if dup_vs_assigned:
                continue
            replacement = cand
            break

        if replacement is not None:
            logger.info(
                "VPI_RENDER_REPLACEMENT_USING_DEDUPED_CANDIDATE idx=%d old_start=%s old_end=%s "
                "new_start=%s new_end=%s candidate_id=%s source_pool=%s",
                idx, seg.get("start_time"), seg.get("end_time"),
                replacement.get("start_time"), replacement.get("end_time"),
                replacement.get("candidate_id"), pool_source,
            )
            used_keys.add(_seg_key(replacement))
            assigned.append(replacement)
            logger.info(
                "VPI_RENDER_REPLACEMENT_CANDIDATE_AUDIT idx=%d replacement_candidate_id=%s "
                "replacement_source_pool=%s rejected_for_reason=%s duplicate_of_candidate_id=%s "
                "start=%s end=%s text_preview=%s passed_duplicate_filter=true",
                idx, replacement.get("candidate_id"), pool_source,
                replacement.get("rejected_for_reason"), replacement.get("duplicate_of_candidate_id"),
                replacement.get("start_time"), replacement.get("end_time"),
                str(replacement.get("text") or "")[:60],
            )
        else:
            logger.info(
                "VPI_RENDER_REPLACEMENT_SKIPPED_NO_VALID_NON_DUPLICATE idx=%d start=%s end=%s",
                idx, seg.get("start_time"), seg.get("end_time"),
            )
            any_dropped = True

    info["effective_clips_count_after_replacement_filter"] = len(assigned)
    if any_dropped:
        info["render_replacement_skipped_reason"] = "no_valid_non_duplicate_candidate"
    if len(assigned) != len(segments_to_render):
        logger.info(
            "VPI_RENDER_REPLACEMENT_EFFECTIVE_CLIP_COUNT_UPDATED task_id=%s "
            "effective_clips_count_after_replacement_filter=%d max_clips=%d",
            task_id, len(assigned), int(num_clips),
        )

    return assigned, info


_H1415_OVERLAP_THRESHOLD = 0.65
_H1415_TEXT_SIM_THRESHOLD = 0.50


def _h1415_refined_window_seconds(seg: Dict[str, Any]) -> Tuple[float, float]:
    start_str = str(seg.get("refined_start_time") or seg.get("start_time") or "00:00")
    end_str = str(seg.get("refined_end_time") or seg.get("end_time") or "00:00")
    return (
        float(parse_timestamp_to_seconds(start_str) or 0.0),
        float(parse_timestamp_to_seconds(end_str) or 0.0),
    )


def _h1415_window_overlap_ratio(seg_a: Dict[str, Any], seg_b: Dict[str, Any]) -> float:
    a_start, a_end = _h1415_refined_window_seconds(seg_a)
    b_start, b_end = _h1415_refined_window_seconds(seg_b)
    union = max(a_end, b_end) - min(a_start, b_start)
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    return (inter / union) if union > 0 else 0.0


def _h1415_normalize_caption_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def _h1415_extract_ass_dialogue_text(ass_path: Path) -> str:
    try:
        content = Path(ass_path).read_text(encoding="utf-8-sig")
    except Exception:
        return ""
    lines: List[str] = []
    for line in content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = re.sub(r"\{[^}]*\}", "", parts[9])
        text = text.replace("\\N", " ").replace("\\n", " ")
        if text.strip():
            lines.append(text.strip())
    return " ".join(lines)


def _h1415_caption_text_hash(normalized_text: str) -> str:
    if not normalized_text:
        return ""
    return hashlib.md5(normalized_text.encode("utf-8")).hexdigest()


def _h1415_segment_text_for_compare(seg: Dict[str, Any], task_id: str, clip_order: int) -> Tuple[str, bool]:
    """Return (comparison_text, from_ass). Prefers generated ASS dialogue
    text; falls back to caption-plan / transcript / candidate text fields."""
    try:
        from .video_service import _resolve_caption_artifacts_dir as _h1415_caption_dir

        ass_path = _h1415_caption_dir(task_id) / f"clip_{clip_order}.ass"
        if ass_path.exists():
            ass_text = _h1415_extract_ass_dialogue_text(ass_path)
            if ass_text.strip():
                return ass_text, True
    except Exception:
        pass

    fallback = (
        seg.get("caption_plan_text")
        or seg.get("transcript_window_text")
        or seg.get("text")
        or seg.get("text_preview")
        or ""
    )
    return str(fallback), False


def _h1415_text_similarity(text_a: str, text_b: str) -> float:
    jaccard, coverage = _h1413_text_overlap_metrics(text_a, text_b)
    return max(jaccard, coverage)


def _h1415_apply_post_refinement_dedupe(
    task_id: str,
    segments_to_render: List[Dict[str, Any]],
    render_results: List[Tuple[int, Optional[Dict[str, Any]], float]],
    num_clips: int,
) -> Tuple[List[Tuple[int, Optional[Dict[str, Any]], float]], Dict[str, Any]]:
    """H14.15 Fix A/B/C.

    Post-boundary-refinement / post-render, pre-accept duplicate guard.
    Compares the FINAL refined windows (segments_to_render[i]["refined_start_time"
    / "refined_end_time"], mutated in place by create_single_clip) and the
    generated ASS dialogue text (or best-available fallback text) for every
    successfully-rendered clip. Any clip that converges onto an already
    accepted clip (refined_temporal_overlap_ratio > 0.65 AND
    refined_text_similarity >= 0.50, or identical normalized ASS text) is
    dropped from `render_results` BEFORE any contract/gate/manifest code
    processes it. No backfill is performed (no additional render is
    triggered) -- effective_clips_count may drop below num_clips.
    """
    successful = [(i, c, e) for (i, c, e) in render_results if c is not None]
    info: Dict[str, Any] = {"effective_clips_count": len(successful)}
    if int(num_clips) <= 1 or len(successful) <= 1:
        return render_results, info

    logger.info(
        "VPI_POST_REFINEMENT_DEDUPE_STARTED task_id=%s candidates=%d max_clips=%d",
        task_id, len(successful), int(num_clips),
    )

    accepted: List[Tuple[int, str, str]] = []  # (idx, compare_text, normalized_hash)
    rejected_indices: set = set()
    removed_details: List[Dict[str, Any]] = []

    for (idx, _clip_info, _elapsed) in successful:
        seg = segments_to_render[idx]
        text, from_ass = _h1415_segment_text_for_compare(seg, task_id, idx + 1)
        normalized = _h1415_normalize_caption_text(text)
        text_hash = _h1415_caption_text_hash(normalized) if from_ass else ""

        dup = None
        for (a_idx, a_text, a_hash) in accepted:
            a_seg = segments_to_render[a_idx]
            overlap = _h1415_window_overlap_ratio(seg, a_seg)
            if text_hash and a_hash and text_hash == a_hash:
                text_sim = 1.0
                caption_dup = True
            else:
                text_sim = _h1415_text_similarity(normalized, a_text)
                caption_dup = False
            if overlap > _H1415_OVERLAP_THRESHOLD and text_sim >= _H1415_TEXT_SIM_THRESHOLD:
                dup = (a_idx, overlap, text_sim, caption_dup)
                break

        if dup is None:
            accepted.append((idx, normalized, text_hash))
            continue

        a_idx, overlap, text_sim, caption_dup = dup
        rejected_indices.add(idx)
        a_seg = segments_to_render[a_idx]
        seg["rejected_for_reason"] = (
            "post_refinement_caption_text_duplicate" if caption_dup else "post_refinement_duplicate_window"
        )
        seg["post_refinement_duplicate_of_candidate_id"] = a_seg.get("candidate_id")
        seg["post_refinement_temporal_overlap_ratio"] = overlap
        seg["post_refinement_text_similarity"] = text_sim
        seg["post_refinement_dedupe_stage"] = "after_boundary_refinement_before_accept"
        removed_details.append({
            "clip_index": idx + 1,
            "start_time": seg.get("refined_start_time") or seg.get("start_time"),
            "end_time": seg.get("refined_end_time") or seg.get("end_time"),
            "stage": "post_refinement_duplicate",
            "reason": (
                f"duplicate_of_clip_{a_idx + 1} overlap={overlap:.2f} "
                f"text_similarity={text_sim:.2f}"
            ),
        })
        if caption_dup:
            seg["duplicate_caption_text_hash"] = text_hash
            seg["duplicate_caption_of_candidate_id"] = a_seg.get("candidate_id")
            logger.info(
                "VPI_POST_REFINEMENT_CAPTION_TEXT_DUPLICATE_REJECTED task_id=%s idx=%d kept_idx=%d hash=%s",
                task_id, idx, a_idx, text_hash,
            )
        logger.info(
            "VPI_POST_REFINEMENT_DUPLICATE_REJECTED task_id=%s idx=%d kept_idx=%d "
            "refined_start=%s refined_end=%s overlap=%.4f text_similarity=%.4f",
            task_id, idx, a_idx,
            seg.get("refined_start_time") or seg.get("start_time"),
            seg.get("refined_end_time") or seg.get("end_time"),
            overlap, text_sim,
        )
        logger.info(
            "VPI_POST_REFINEMENT_DUPLICATE_KEEPING_EXISTING task_id=%s kept_idx=%d rejected_idx=%d",
            task_id, a_idx, idx,
        )

    if not rejected_indices:
        logger.info(
            "VPI_POST_REFINEMENT_DEDUPE_COMPLETE task_id=%s total=%d removed=0",
            task_id, len(successful),
        )
        return render_results, info

    new_render_results = [(i, c, e) for (i, c, e) in render_results if i not in rejected_indices]
    new_effective_count = sum(1 for _, c, _ in new_render_results if c is not None)
    info["effective_clips_count"] = new_effective_count
    info["removed_details"] = removed_details

    logger.info(
        "VPI_POST_REFINEMENT_BACKFILL_SKIPPED_NO_VALID_NON_DUPLICATE task_id=%s removed=%d",
        task_id, len(rejected_indices),
    )
    logger.info(
        "VPI_POST_REFINEMENT_EFFECTIVE_CLIP_COUNT_UPDATED task_id=%s effective_clips_count=%d max_clips=%d",
        task_id, new_effective_count, int(num_clips),
    )
    logger.info(
        "VPI_POST_REFINEMENT_DEDUPE_COMPLETE task_id=%s total=%d removed=%d",
        task_id, len(successful), len(rejected_indices),
    )
    return new_render_results, info


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
        
        normalized_url = (url or "").strip()
        if source_type == "youtube":
            try:
                from .. import youtube_utils as _youtube_utils

                normalized_url = _youtube_utils.normalize_youtube_url(normalized_url) or normalized_url
            except Exception:
                pass

        # Final key: source|mode|normalized_url:config_hash
        payload = f"{source_type}|{processing_mode}|{normalized_url}"
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
        # ComfyUI AI features
        use_comfyui_reframe: bool = False,
        use_comfyui_subtitles: bool = False,
        use_comfyui_thumbnail: bool = False,
        thumbnail_prompt: str = "cinematic viral thumbnail",
        comfyui_chunk_size: int = 300,
    ) -> Dict[str, Any]:
        """
        Process a task: download video, analyze, create clips.
        Returns processing results.
        """
        try:
            viraclip_mode = str(getattr(self.config, "viraclip_mode", "default") or "default").lower()
            premium_productive_mode = bool(getattr(self.config, "premium_productive_mode", False))
            deadline_safe_mode = bool(getattr(self.config, "deadline_safe_mode", False))
            editorial_qc_blocking = bool(getattr(self.config, "editorial_qc_blocking", True))
            try:
                from .vpi_production_safe_edit import get_vpi_daily_mode_policy
                daily_mode_policy = dict(get_vpi_daily_mode_policy())
            except Exception:
                daily_mode_policy = {}
            vpi_daily_mode_enabled = bool(daily_mode_policy.get("vpi_daily_mode_enabled"))
            if premium_productive_mode:
                deadline_safe_mode = False
                editorial_qc_blocking = False
            if vpi_daily_mode_enabled:
                logger.info(
                    "VPI_DAILY_MODE_OUTPUTS_ENABLED mode=%s outputs_enabled=%s",
                    str(daily_mode_policy.get("daily_mode_version") or "a1"),
                    str(bool(daily_mode_policy.get("daily_mode_outputs_enabled", True))).lower(),
                )
            if deadline_safe_mode:
                include_broll = False
                jump_cut = False
                denoise_audio = False
                contextual_overlays = False
                logger.info("DEADLINE_SAFE_MODE external_planning_disabled=true")
            _broll_mode_enabled = bool(
                getattr(self.config, "broll_enabled", False)
                and getattr(self.config, "enable_editorial_broll", False)
            )
            _sfx_mode_enabled = bool(getattr(self.config, "freesound_sfx_enabled", True))
            _bgm_asset_dirs = [
                Path("/app/assets/sounds"),
                Path("/app/music_legacy"),
                Path("backend/music"),
                Path("assets/sounds"),
            ]
            _bgm_mode_enabled = any(p.exists() for p in _bgm_asset_dirs)
            logger.info(
                "VIRACLIP_MODE_RESOLVED mode=%s deadline_safe=%s broll=%s sfx=%s bgm=%s editorial_qc_blocking=%s",
                viraclip_mode,
                str(deadline_safe_mode).lower(),
                str(_broll_mode_enabled).lower(),
                str(_sfx_mode_enabled).lower(),
                str(_bgm_mode_enabled).lower(),
                str(editorial_qc_blocking).lower(),
            )
            logger.info(
                "VIRACLIP_MODE runtime_mode=%s premium_productive=%s deadline_safe=%s editorial_qc_blocking=%s",
                viraclip_mode,
                str(premium_productive_mode).lower(),
                str(deadline_safe_mode).lower(),
                str(editorial_qc_blocking).lower(),
            )
            logger.info(f"Starting processing for task {task_id} (force_fresh={force_fresh})")
            logger.info("[tasks] process include_broll=%s", str(include_broll).lower())
            started_at = datetime.now(timezone.utc)
            stage_timings: Dict[str, Any] = {}
            task_record = await self.task_repo.get_task_by_id(self.db, task_id)
            normalized_source_url, source_type, _source_contract_diag = resolve_task_source_contract(
                task_record=task_record,
                url=url,
                source_type=source_type,
            )
            if _source_contract_diag.get("mismatch_detected"):
                logger.warning(
                    "SOURCE_CONTRACT_RESOLVED task_id=%s supplied_url=%s supplied_source_type=%s resolved_url=%s resolved_source_type=%s used_task_record=%s",
                    task_id,
                    _source_contract_diag.get("supplied_url") or "none",
                    _source_contract_diag.get("supplied_source_type") or "none",
                    _source_contract_diag.get("resolved_url") or "none",
                    _source_contract_diag.get("resolved_source_type") or "none",
                    str(bool(_source_contract_diag.get("used_task_record"))).lower(),
                )
            if source_type == "youtube":
                try:
                    from .. import youtube_utils as _youtube_utils

                    normalized_source_url = (
                        _youtube_utils.normalize_youtube_url(normalized_source_url) or normalized_source_url
                    )
                except Exception:
                    pass
            cache_key = self._build_cache_key(normalized_source_url, source_type, processing_mode)
            task_run_id = f"{task_id}-{int(started_at.timestamp())}"

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
                    else:
                        _analysis_meta = _parse_json_dict(cache_entry.get("analysis_json"))
                        _cache_guard = _as_dict(_analysis_meta.get("_cache_guard"))
                        _expected_video_hash = str(_cache_guard.get("source_video_hash") or "")
                        _expected_language = str(_cache_guard.get("transcript_language") or "").lower()
                        _actual_video_hash = _hash_file_head_sha256(cached_video_path)
                        _effective_expected_lang = str(os.getenv("VPI_EXPECTED_TRANSCRIPT_LANGUAGE", "es")).strip().lower() or "es"
                        if _expected_video_hash and _actual_video_hash and _expected_video_hash != _actual_video_hash:
                            logger.warning(
                                "TRANSCRIPT_CACHE_REJECTED task_id=%s reason=source_hash_mismatch expected=%s actual=%s",
                                task_id,
                                _expected_video_hash[:12],
                                _actual_video_hash[:12],
                            )
                            await self.cache_repo.delete_cache(self.db, cache_key)
                            cache_entry = None
                        elif _expected_language and _expected_language != _effective_expected_lang:
                            logger.warning(
                                "TRANSCRIPT_CACHE_REJECTED task_id=%s reason=language_mismatch expected=%s requested=%s",
                                task_id,
                                _expected_language,
                                _effective_expected_lang,
                            )
                            await self.cache_repo.delete_cache(self.db, cache_key)
                            cache_entry = None
                # else: video_path is None/empty — cache incomplete, proceed with fresh download
            
            cached_transcript = cache_entry.get("transcript_text") if cache_entry else None
            cached_analysis_json = cache_entry.get("analysis_json") if cache_entry else None
            cache_hit = bool(cached_transcript)
            force_fresh_editorial_decisions = True
            cache_policy: Dict[str, Any] = {
                "task_run_id": task_run_id,
                "source_download_cache_used": False,
                "transcript_cache_used": bool(cached_transcript),
                "final_outputs_reused": False,
                "editorial_decisions_reused": False,
                "source_video_hash": "",
                "transcript_hash": "",
            }
            stage_timings["task_run_id"] = task_run_id
            stage_timings["cache_policy"] = dict(cache_policy)
            logger.info(
                "CACHE_FIREWALL_ACTIVE task_id=%s force_fresh_outputs=true task_run_id=%s",
                task_id,
                task_run_id,
            )
            if cached_transcript:
                logger.info("CACHE_USED task_id=%s context=transcript source=processing_cache", task_id)
            else:
                logger.info("CACHE_BYPASSED task_id=%s context=transcript reason=cache_miss", task_id)
            if cached_analysis_json:
                logger.info(
                    "CACHE_BYPASSED task_id=%s context=editorial_decisions reason=firewall_force_fresh",
                    task_id,
                )
            else:
                logger.info(
                    "CACHE_BYPASSED task_id=%s context=editorial_decisions reason=no_cached_editorial_data",
                    task_id,
                )

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
                    cached_analysis_json=None,
                    force_fresh_editorial_decisions=force_fresh_editorial_decisions,
                    task_metadata=task_record or {},
                    user_options=task_record or {},
                    campaign_prompt=str((task_record or {}).get("source_title") or (task_record or {}).get("source_url") or ""),
                    campaign_config={
                        "processing_mode": processing_mode,
                        "target_platform": target_platform,
                        "include_broll": include_broll,
                    },
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

            _analysis_payload = _parse_json_dict(result.get("analysis_json"))
            _analysis_payload["_cache_guard"] = {
                "source_video_hash": _hash_file_head_sha256(Path(str(result.get("video_path") or ""))),
                "transcript_hash": _hash_text_sha256(str(result.get("transcript") or "")),
                "transcript_language": str(os.getenv("VPI_EXPECTED_TRANSCRIPT_LANGUAGE", "es")).strip().lower() or "es",
                "task_id": task_id,
            }
            await self.cache_repo.upsert_cache(
                self.db,
                cache_key=cache_key,
                source_url=normalized_source_url,
                source_type=source_type,
                transcript_text=result.get("transcript"),
                analysis_json=json.dumps(_analysis_payload),
            )
            _pipeline_cache_usage = result.get("cache_usage") if isinstance(result, dict) else {}
            if isinstance(_pipeline_cache_usage, dict):
                cache_policy["source_download_cache_used"] = bool(_pipeline_cache_usage.get("source_download_cache_used"))
                cache_policy["transcript_cache_used"] = bool(_pipeline_cache_usage.get("transcript_cache_used"))
                if cache_policy["source_download_cache_used"]:
                    logger.info("CACHE_USED task_id=%s context=source_download source=task_scoped_or_shared", task_id)
                else:
                    logger.info("CACHE_BYPASSED task_id=%s context=source_download reason=fresh_download", task_id)
                if cache_policy["transcript_cache_used"]:
                    logger.info(
                        "CACHE_USED task_id=%s context=transcript source=%s",
                        task_id,
                        str(_pipeline_cache_usage.get("transcript_cache_source") or "unknown"),
                    )
                else:
                    logger.info("CACHE_BYPASSED task_id=%s context=transcript reason=fresh_transcription", task_id)
                stage_timings["cache_policy"] = dict(cache_policy)

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
            cache_policy["source_video_hash"] = _hash_file_head_sha256(video_path)
            cache_policy["transcript_hash"] = _hash_text_sha256(str(result.get("transcript") or ""))
            stage_timings["cache_policy"] = dict(cache_policy)
            
            # Get segments to render
            segments_to_render = result.get("segments_to_render", [])
            # H14.13: snapshot the H14.9/H14.11-corrected segments_to_render
            # BEFORE it can be overwritten below by the pre-render editorial
            # gate's approved_segments (which may be derived from a stale,
            # pre-dedupe candidate pool). This snapshot is the trusted source
            # for VPI_EXPANSION_CANDIDATE_RENDER_INPUT_REPLACED replacements.
            _h1413_deduped_segments_to_render: List[Dict[str, Any]] = [
                x for x in (segments_to_render or []) if isinstance(x, dict)
            ]
            package_diversity_summary = dict(result.get("selected_clip_package_summary") or {})
            package_diversity_score = float(result.get("package_diversity_score") or package_diversity_summary.get("package_diversity_score") or 0.0)
            package_diversity_reason = str(result.get("package_diversity_reason") or package_diversity_summary.get("package_diversity_reason") or "")
            package_category_distribution = dict(result.get("package_category_distribution") or package_diversity_summary.get("package_category_distribution") or {})
            package_theme_distribution = dict(result.get("package_theme_distribution") or package_diversity_summary.get("package_theme_distribution") or {})
            package_duration_balance_ok = bool(result.get("package_duration_balance_ok") if result.get("package_duration_balance_ok") is not None else package_diversity_summary.get("package_duration_balance_ok"))
            package_diversity_warnings = list(result.get("package_diversity_warnings") or package_diversity_summary.get("package_diversity_warnings") or [])
            campaign_intent = str(result.get("campaign_intent") or package_diversity_summary.get("campaign_intent") or "general_vpi")
            campaign_intent_confidence = float(result.get("campaign_intent_confidence") or package_diversity_summary.get("campaign_intent_confidence") or 0.0)
            campaign_intent_source = str(result.get("campaign_intent_source") or package_diversity_summary.get("campaign_intent_source") or "default_general")
            campaign_intent_reason = str(result.get("campaign_intent_reason") or package_diversity_summary.get("campaign_intent_reason") or "")
            selected_campaign_mix = dict(result.get("selected_campaign_mix") or package_diversity_summary.get("selected_campaign_mix") or {})
            campaign_alignment_summary = dict(result.get("campaign_alignment_summary") or package_diversity_summary.get("campaign_alignment_summary") or {})
            sensitive_handling_required = bool(result.get("sensitive_handling_required") if result.get("sensitive_handling_required") is not None else package_diversity_summary.get("sensitive_handling_required"))
            campaign_boost_applied = bool(result.get("campaign_boost_applied") if result.get("campaign_boost_applied") is not None else package_diversity_summary.get("campaign_boost_applied"))
            campaign_boost_score = float(result.get("campaign_boost_score") or package_diversity_summary.get("campaign_boost_score") or 0.0)
            campaign_alignment_score = float(result.get("campaign_alignment_score") or package_diversity_summary.get("campaign_alignment_score") or 0.0)
            campaign_alignment_reason = str(result.get("campaign_alignment_reason") or package_diversity_summary.get("campaign_alignment_reason") or "")
            preferred_categories = list(result.get("preferred_categories") or package_diversity_summary.get("preferred_categories") or [])
            suppressed_categories = list(result.get("suppressed_categories") or package_diversity_summary.get("suppressed_categories") or [])
            preferred_keywords = list(result.get("preferred_keywords") or package_diversity_summary.get("preferred_keywords") or [])
            clip_briefs = list(result.get("clip_briefs") or package_diversity_summary.get("clip_briefs") or [])
            clip_brief_summary = dict(result.get("clip_brief_summary") or package_diversity_summary.get("clip_brief_summary") or {})
            high_confidence_clip_count = int(result.get("high_confidence_clip_count") or package_diversity_summary.get("high_confidence_clip_count") or clip_brief_summary.get("high_confidence_clip_count") or 0)
            review_clip_count = int(result.get("review_clip_count") or package_diversity_summary.get("review_clip_count") or clip_brief_summary.get("review_clip_count") or 0)
            campaign_fit_summary = dict(result.get("campaign_fit_summary") or package_diversity_summary.get("campaign_fit_summary") or clip_brief_summary.get("campaign_fit_summary") or {})
            logger.info(
                "VPI_TASK_PACKAGE_DIVERSITY task_id=%s score=%.4f categories=%s warnings=%s",
                task_id,
                package_diversity_score,
                "|".join(f"{k}:{v}" for k, v in package_category_distribution.items()) or "none",
                "|".join(package_diversity_warnings) or "none",
            )
            logger.info(
                "VPI_CAMPAIGN_PACKAGE_SELECTED task_id=%s intent=%s alignment=%.3f boost=%.3f source=%s",
                task_id,
                campaign_intent,
                campaign_alignment_score,
                campaign_boost_score,
                campaign_intent_source,
            )
            logger.info(
                "VPI_CLIP_BRIEF_TASK_SUMMARY task_id=%s briefs=%d high_confidence=%d review=%d campaign_fit=%s",
                task_id,
                len(clip_briefs),
                high_confidence_clip_count,
                review_clip_count,
                "|".join(f"{k}:{v}" for k, v in campaign_fit_summary.items()) or "none",
            )
            # H14.13: prefer the H14.9/H14.11-corrected segments_to_render
            # (deduped, no candidates tagged duplicate_window_overlap /
            # post_render_input_duplicate_window_overlap /
            # duplicate_of_candidate_id) as the source for the pre-render
            # pool. Only fall back to the older, pre-dedupe candidate pools
            # (candidate_pool / pre_render_candidate_pool / ranked_segments /
            # segments_before_final_selection) if the deduped list is empty
            # -- and in that case, filter out any duplicate-tagged entries
            # using the same H14.7/H14.9/H14.11 rules before they can reach
            # the gate or VPI_EXPANSION_CANDIDATE_RENDER_INPUT_REPLACED.
            _candidate_sources: List[Tuple[str, List[Dict[str, Any]]]] = []
            if _h1413_deduped_segments_to_render:
                _candidate_sources.append(("deduped_segments_to_render", list(_h1413_deduped_segments_to_render)))
            for _key in ("candidate_pool", "pre_render_candidate_pool", "ranked_segments", "segments_before_final_selection"):
                _val = result.get(_key)
                if isinstance(_val, list):
                    _raw_items = [x for x in _val if isinstance(x, dict)]
                    _filtered_items, _old_pool_removed = _h1413_filter_duplicate_tagged(_raw_items)
                    if _old_pool_removed:
                        logger.info(
                            "VPI_RENDER_REPLACEMENT_OLD_POOL_FILTERED source=%s removed=%d remaining=%d",
                            _key, _old_pool_removed, len(_filtered_items),
                        )
                    _candidate_sources.append((_key, _filtered_items))
            _candidate_sources.append(("segments_to_render", [x for x in (segments_to_render or []) if isinstance(x, dict)]))
            _pool_source = "segments_to_render"
            pre_render_pool: List[Dict[str, Any]] = []
            for _source_name, _source_items in _candidate_sources:
                if _source_items:
                    pre_render_pool = list(_source_items)
                    _pool_source = _source_name
                    break
            logger.info(
                "VPI_RENDER_REPLACEMENT_SOURCE_SELECTED task_id=%s source=%s count=%d",
                task_id, _pool_source, len(pre_render_pool),
            )
            pre_render_pool_target = max(int(num_clips) * 8, 30)
            _analysis_segments: List[Dict[str, Any]] = []
            _analysis_json_raw = result.get("analysis_json")
            try:
                if isinstance(_analysis_json_raw, str):
                    _analysis_json_raw = json.loads(_analysis_json_raw)
                if isinstance(_analysis_json_raw, dict):
                    _analysis_segments = list(_analysis_json_raw.get("most_relevant_segments") or [])
            except Exception as _analysis_e:
                logger.debug("PRE_RENDER_POOL analysis_json parse skipped reason=%s", _analysis_e)

            def _seg_key(_seg: Dict[str, Any]) -> str:
                return "|".join(
                    [
                        str(_seg.get("start_time") or ""),
                        str(_seg.get("end_time") or ""),
                        str(_seg.get("text") or "")[:140],
                    ]
                )

            _seen_pool: set[str] = set()
            _dedup_pool: List[Dict[str, Any]] = []
            for _seg in (pre_render_pool + _analysis_segments):
                if not isinstance(_seg, dict):
                    continue
                _k = _seg_key(_seg)
                if _k in _seen_pool:
                    continue
                _seen_pool.add(_k)
                _dedup_pool.append(_seg)
            _dedup_pool.sort(
                key=lambda item: float(item.get("final_rank_score") or item.get("editorial_score") or 0.0),
                reverse=True,
            )
            pre_render_pool = _dedup_pool[:pre_render_pool_target]
            logger.info(
                "PRE_RENDER_POOL_SOURCE task_id=%s source=%s count=%d",
                task_id,
                _pool_source,
                len(pre_render_pool),
            )
            if len(pre_render_pool) > int(num_clips):
                logger.info(
                    "PRE_RENDER_POOL_SOURCE source=%s count=%d",
                    _pool_source,
                    len(pre_render_pool),
                )
            for _idx, _seg in enumerate(pre_render_pool):
                _seg["_pre_render_pool_rank"] = _idx + 1
            logger.info(
                "PRE_RENDER_POOL_SIZE task_id=%s pool_size=%d requested=%d",
                task_id,
                len(pre_render_pool),
                num_clips,
            )
            if deadline_safe_mode:
                _base_segments = [x for x in (segments_to_render or pre_render_pool) if isinstance(x, dict)]
                segments_to_render = _base_segments[:num_clips]
                logger.info(
                    "DEADLINE_SAFE_MODE pre_render_gate_disabled=true selected=%d",
                    len(segments_to_render),
                )
                pre_render_pool = []
            pre_render_gate_data: Dict[str, Any] = {
                "candidate_count": len(pre_render_pool),
                "approved_count": 0,
                "failed_count": 0,
                "requested_clips": num_clips,
                "rejected_segments": [],
                "bgm_tracks_available": 0,
            }
            try:
                from .vpi_music_service import discover_music_tracks as _discover_music_tracks
                _bgm_tracks_available = len(_discover_music_tracks())
            except Exception as _bgm_probe_e:
                logger.debug("[pre-render] bgm probe skipped reason=%s", _bgm_probe_e)
                _bgm_tracks_available = 0
            pre_render_gate_data["bgm_tracks_available"] = _bgm_tracks_available
            if deadline_safe_mode:
                pre_render_gate_data["candidate_count"] = len(segments_to_render)
                pre_render_gate_data["approved_count"] = len(segments_to_render)
                pre_render_gate_data["failed_count"] = 0
                pre_render_gate_data["approved_segments"] = list(segments_to_render)
            if pre_render_pool:
                try:
                    pre_render_gate_data = run_pre_render_editorial_gate(
                        task_id=task_id,
                        segments=pre_render_pool,
                        requested_clips=num_clips,
                        include_broll=bool(include_broll),
                        bgm_tracks_available=_bgm_tracks_available,
                    )
                    _approved_pool = list(pre_render_gate_data.get("approved_segments") or [])
                    segments_to_render = _approved_pool[:num_clips]

                    # H14.13 Fix A/B/C: the gate above may have approved
                    # candidates from a stale, pre-dedupe pool (when
                    # _pool_source != "deduped_segments_to_render"). Run a
                    # final pass over segments_to_render that (a) never
                    # leaves a duplicate-tagged candidate (H14.7/H14.9/H14.11)
                    # in place, (b) never assigns two slots to near-duplicate
                    # windows, replacing such slots from
                    # _h1413_deduped_segments_to_render when possible, and
                    # (c) drops the slot (allowing effective_clips_count to
                    # fall below max_clips) when no valid non-duplicate
                    # replacement exists.
                    segments_to_render, _h1413_replacement_info = _h1413_apply_render_replacement_dedupe(
                        task_id=task_id,
                        segments_to_render=segments_to_render,
                        deduped_pool=_h1413_deduped_segments_to_render,
                        pool_source=_pool_source,
                        num_clips=num_clips,
                    )
                    pre_render_gate_data["render_replacement_effective_clips_count"] = (
                        _h1413_replacement_info["effective_clips_count_after_replacement_filter"]
                    )
                    if "render_replacement_skipped_reason" in _h1413_replacement_info:
                        pre_render_gate_data["render_replacement_skipped_reason"] = (
                            _h1413_replacement_info["render_replacement_skipped_reason"]
                        )

                    # Log rendered window vs VPI-selected window for expansion candidates
                    _vpi_first_segment = (result.get("segments_to_render") or [None])[0]
                    _vpi_selected_start = (_vpi_first_segment or {}).get("start_time") if _vpi_first_segment else None
                    _vpi_selected_end = (_vpi_first_segment or {}).get("start_time") if _vpi_first_segment else None
                    for _seg in segments_to_render:
                        _gate_start = _seg.get("start_time")
                        _gate_end = _seg.get("end_time")
                        if _vpi_first_segment and (_gate_start != _vpi_selected_start):
                            logger.warning(
                                "VPI_RENDERED_WINDOW_SELECTION_MISMATCH_PREVENTED task_id=%s "
                                "vpi_selected=%s->%s gate_selected=%s->%s generated_by=%s",
                                task_id,
                                _vpi_first_segment.get("start_time"), _vpi_first_segment.get("end_time"),
                                _gate_start, _gate_end,
                                _seg.get("generated_by", "primary_pipeline"),
                            )
                        else:
                            logger.info(
                                "VPI_RENDERED_WINDOW_MATCHES_SELECTED_CANDIDATE task_id=%s "
                                "start=%s end=%s generated_by=%s",
                                task_id, _gate_start, _gate_end,
                                _seg.get("generated_by", "primary_pipeline"),
                            )

                    # ── FIX 1: Preserve normalized contract_result through render handoff ──
                    # The pre-render editorial gate evaluated each segment and produced a
                    # contract_result dict with approved, hook_support, visual_support,
                    # complete_idea_pass, would_runtime_reject, etc.  We inject these fields
                    # directly into each segment so the render path (create_single_clip) can
                    # use the contract as authoritative — suppressing stale legacy rejections.
                    #
                    # Priority order:
                    #   1. _get_segment_contract_result() — reads from the FULL contract
                    #      persisted by _attach_contract_result_to_segment() during the
                    #      pre_render_qc loop (line 520).  This is the authoritative source.
                    #   2. candidate_reports — legacy fallback for segments that were not
                    #      evaluated by the current pre_render_qc loop (e.g. backup candidates).
                    for _seg in segments_to_render:
                        _seg_idx = int(_seg.get("_pre_render_pool_rank") or 0)
                        _contract_result = _get_segment_contract_result(_seg)
                        if _contract_result is not None:
                            # Authoritative: contract was persisted directly on segment
                            _seg["pre_render_contract_result"] = _contract_result
                            _seg["pre_render_approved"] = bool(_contract_result.get("approved", False))
                            _seg["contract_approved"] = bool(_contract_result.get("approved", False))
                            _seg["contract_would_runtime_reject"] = bool(_contract_result.get("would_runtime_reject", True))
                            _seg["hook_support"] = dict(_contract_result.get("hook_support") or {})
                            _seg["visual_support"] = dict(_contract_result.get("visual_support") or {})
                            _seg["complete_idea_pass"] = bool(_contract_result.get("complete_idea_pass", False))
                            logger.info(
                                "RENDER_HANDOFF_CONTRACT task_id=%s segment_idx=%d "
                                "approved=%s hook_exec=%s visual_exec=%s complete_idea_pass=%s "
                                "would_runtime_reject=%s",
                                task_id,
                                _seg_idx,
                                _seg["contract_approved"],
                                _seg.get("hook_support", {}).get("executable", False),
                                _seg.get("visual_support", {}).get("executable", False),
                                _seg["complete_idea_pass"],
                                _seg["contract_would_runtime_reject"],
                            )
                        else:
                            # Fallback: try candidate_reports (legacy path for backup candidates)
                            _candidate_reports = list(pre_render_gate_data.get("candidate_reports") or [])
                            _report = None
                            for _cr in _candidate_reports:
                                if int(_cr.get("candidate_index", 0)) == _seg_idx:
                                    _report = _cr
                                    break
                            if _report is None:
                                _report_idx = segments_to_render.index(_seg)
                                if _report_idx < len(_candidate_reports):
                                    _report = _candidate_reports[_report_idx]
                            if _report is not None:
                                _contract_result = dict(_report.get("contract_result") or {})
                                try:
                                    from .vpi_editorial_contract import normalize_contract_result as _normalize_contract
                                    _normalized = _normalize_contract(_contract_result)
                                except Exception:
                                    _normalized = _contract_result
                                _seg["pre_render_contract_result"] = _normalized
                                _seg["pre_render_approved"] = bool(_normalized.get("approved", False))
                                _seg["contract_approved"] = bool(_normalized.get("approved", False))
                                _seg["contract_would_runtime_reject"] = bool(_normalized.get("would_runtime_reject", True))
                                _seg["hook_support"] = dict(_normalized.get("hook_support") or {})
                                _seg["visual_support"] = dict(_normalized.get("visual_support") or {})
                                _seg["complete_idea_pass"] = bool(_normalized.get("complete_idea_pass", False))
                                logger.info(
                                    "RENDER_HANDOFF_CONTRACT_FALLBACK task_id=%s segment_idx=%d "
                                    "approved=%s hook_exec=%s visual_exec=%s complete_idea_pass=%s "
                                    "would_runtime_reject=%s",
                                    task_id,
                                    _seg_idx,
                                    _seg["contract_approved"],
                                    _seg.get("hook_support", {}).get("executable", False),
                                    _seg.get("visual_support", {}).get("executable", False),
                                    _seg["complete_idea_pass"],
                                    _seg["contract_would_runtime_reject"],
                                )
                            else:
                                logger.warning(
                                    "RENDER_HANDOFF_CONTRACT_MISSING task_id=%s segment_idx=%d "
                                    "reason=no_contract_result_or_candidate_report_found",
                                    task_id,
                                    _seg_idx,
                                )

                    # ── Hard invariant: RENDER_HANDOFF_CONTRACT_LOST ──────────────────
                    # Before rendering, every segment selected from approved_candidates
                    # MUST have: approved=True, hook_exec=True, visual_exec=True,
                    # complete_idea_pass=True, would_runtime_reject=False.
                    # If any segment fails this invariant, log a diagnostic and skip it.
                    _pre_render_invariant_failed: List[Dict[str, Any]] = []
                    for _seg in segments_to_render:
                        _seg_idx = int(_seg.get("_pre_render_pool_rank") or 0)
                        _contract_result = _get_segment_contract_result(_seg)
                        if _contract_result is None:
                            logger.error(
                                "RENDER_HANDOFF_CONTRACT_LOST task_id=%s segment_idx=%d "
                                "reason=contract_result_not_found_on_segment",
                                task_id,
                                _seg_idx,
                            )
                            _pre_render_invariant_failed.append(_seg)
                            continue
                        _approved = bool(_contract_result.get("approved", False))
                        _hook_exec = bool((_contract_result.get("hook_support") or {}).get("executable", False))
                        _visual_exec = bool((_contract_result.get("visual_support") or {}).get("executable", False))
                        _complete_idea_pass = bool(_contract_result.get("complete_idea_pass", False))
                        _would_runtime_reject = bool(_contract_result.get("would_runtime_reject", True))
                        if not (_approved and _hook_exec and _visual_exec and _complete_idea_pass and not _would_runtime_reject):
                            logger.error(
                                "RENDER_HANDOFF_CONTRACT_LOST task_id=%s segment_idx=%d "
                                "approved=%s hook_exec=%s visual_exec=%s complete_idea_pass=%s "
                                "would_runtime_reject=%s",
                                task_id,
                                _seg_idx,
                                _approved,
                                _hook_exec,
                                _visual_exec,
                                _complete_idea_pass,
                                _would_runtime_reject,
                            )
                            _pre_render_invariant_failed.append(_seg)
                    if _pre_render_invariant_failed:
                        logger.error(
                            "RENDER_HANDOFF_CONTRACT_LOST task_id=%s count=%d "
                            "reason=pre_render_invariant_failed_before_render",
                            task_id,
                            len(_pre_render_invariant_failed),
                        )
                        # Remove failed segments from render list
                        segments_to_render = [
                            _seg for _seg in segments_to_render
                            if _seg not in _pre_render_invariant_failed
                        ]
                        logger.info(
                            "RENDER_HANDOFF_CONTRACT_LOST task_id=%s remaining=%d after_invariant_filter",
                            task_id,
                            len(segments_to_render),
                        )


                    logger.info("RENDER_INPUT_APPROVED_ONLY count=%d", len(segments_to_render))
                    for _sel_idx, _sel in enumerate(segments_to_render, start=1):
                        _rank = int(_sel.get("_pre_render_pool_rank") or 0)
                        if _rank > num_clips:
                            logger.info(
                                "BACKUP_CANDIDATE_USED task_id=%s original_rank=%d backup_rank=%d reason=top_candidate_failed_pre_render",
                                task_id,
                                _sel_idx,
                                _rank,
                            )
                except Exception as pre_render_gate_exc:
                    logger.exception(
                        "PRE_RENDER_QC_ERROR task_id=%s candidate_index=0 reason=%s",
                        task_id,
                        f"{type(pre_render_gate_exc).__name__}:{pre_render_gate_exc}",
                    )
                    pre_render_gate_data = {
                        "approved_segments": [],
                        "rejected_segments": [
                            {
                                "clip_index": 0,
                                "start_time": "",
                                "end_time": "",
                                "reason": f"pre_render_qc_error:{type(pre_render_gate_exc).__name__}:{pre_render_gate_exc}",
                                "stage": "pre_render_qc_error",
                            }
                        ],
                        "requested_clips": num_clips,
                        "candidate_count": len(pre_render_pool),
                        "approved_count": 0,
                        "failed_count": len(pre_render_pool) or 1,
                        "bgm_tracks_available": _bgm_tracks_available,
                        "approved_ratio": 0.0,
                        "candidate_reports": [],
                    }
                    segments_to_render = []
            # INVARIANT: pre_render_qc_stage must always be set before "Rendering clips"
            # progress. It is impossible to see pre_render_qc_stage=missing while
            # progress_message contains "Rendering clips".
            stage_timings["pre_render_qc"] = {
                "candidate_count": int(pre_render_gate_data.get("candidate_count", 0)),
                "approved_count": int(pre_render_gate_data.get("approved_count", 0)),
                "failed_count": int(pre_render_gate_data.get("failed_count", 0)),
                "requested_clips": int(pre_render_gate_data.get("requested_clips", num_clips)),
                "pool_source": _pool_source,
                "pool_size": len(pre_render_pool),
                "pool_target": int(pre_render_pool_target),
                "bgm_tracks_available": int(pre_render_gate_data.get("bgm_tracks_available", 0)),
                "approved_ratio": float(pre_render_gate_data.get("approved_ratio", 0.0) or 0.0),
                "rejected_segments": list(pre_render_gate_data.get("rejected_segments") or []),
                "candidate_reports_top10": list((pre_render_gate_data.get("candidate_reports") or [])[:10]),
            }
            total_clips = len(segments_to_render)
            
            logger.info(
                "[clip-count] requested=%d candidates=%d selected=%d rendered=0 exported=0",
                num_clips,
                int(pre_render_gate_data.get("candidate_count", len(segments_to_render))),
                len(segments_to_render),
            )
            if total_clips < num_clips and total_clips > 0:
                stage_timings["pre_render_shortage"] = f"{total_clips}/{num_clips}"
                await update_progress(
                    67,
                    f"pre_render_shortage:{total_clips}/{num_clips}",
                    "processing",
                )

            # CRITICAL VALIDATION: Check if we have segments
            if total_clips == 0:
                _pre_reasons = list(pre_render_gate_data.get("rejected_segments") or [])
                _render_input_count_before = len(segments_to_render)
                _rejected_types = ",".join(
                    sorted(
                        {
                            str(type(item).__name__)
                            for item in _pre_reasons[:10]
                        }
                    )
                ) or "none"
                _pre_rejected_sample_fields = []
                for _item in _pre_reasons[:3]:
                    if isinstance(_item, dict):
                        _pre_rejected_sample_fields.append(
                            "|".join(
                                [
                                    f"reason={_item.get('reason')!s}",
                                    f"stage={_item.get('stage')!s}",
                                    f"text={str(_item.get('text') or _item.get('transcript_text') or '')[:32]}",
                                    f"start={_item.get('start_time')!s}",
                                    f"end={_item.get('end_time')!s}",
                                    f"segment_key={_item.get('segment_key')!s}",
                                ]
                            )
                        )
                    else:
                        _pre_rejected_sample_fields.append(f"type={type(_item).__name__}|value={str(_item)[:80]}")
                _pre_pool_sample_fields = []
                for _item in pre_render_pool[:3]:
                    if isinstance(_item, dict):
                        _pre_pool_sample_fields.append(
                            "|".join(
                                [
                                    f"text={str(_item.get('text') or _item.get('transcript_text') or '')[:32]}",
                                    f"start={_item.get('start_time')!s}",
                                    f"end={_item.get('end_time')!s}",
                                    f"segment_key={_item.get('segment_key')!s}",
                                    f"source_path={_item.get('source_path')!s}",
                                ]
                            )
                        )
                    else:
                        _pre_pool_sample_fields.append(f"type={type(_item).__name__}")
                logger.info(
                    "FAST_FAIL_RESCUE_INPUT_DIAGNOSTIC task_id=%s approved_count=%d render_input_count_before=%d pre_render_pool_count=%d rejected_count=%d rejected_types=%s rejected_sample_fields=%s pool_sample_fields=%s",
                    task_id,
                    int(pre_render_gate_data.get("approved_count", 0)),
                    _render_input_count_before,
                    len(pre_render_pool),
                    len(_pre_reasons),
                    _rejected_types,
                    "|".join(_pre_rejected_sample_fields) or "none",
                    "|".join(_pre_pool_sample_fields) or "none",
                )
                _recovered_segments, _recovery_meta = _apply_fast_fail_rescue_to_render_input(
                    task_id=task_id,
                    render_input=segments_to_render,
                    rejected_segments=_pre_reasons,
                    pre_render_pool=pre_render_pool,
                    num_clips=num_clips,
                )
                _renderable_candidates = int(_recovery_meta.get("recovered_count", 0) or 0)
                _editorial_only_failures = int(_recovery_meta.get("editorial_only_count", 0) or 0)
                _technical_failures = int(_recovery_meta.get("technical_count", 0) or 0)
                if _renderable_candidates > 0:
                    segments_to_render = _recovered_segments[:num_clips]
                    total_clips = len(segments_to_render)
                    pre_render_gate_data["approved_segments"] = list(segments_to_render)
                    pre_render_gate_data["approved_count"] = total_clips
                    pre_render_gate_data["failed_count"] = max(0, len(_pre_reasons) - total_clips)
                    pre_render_gate_data["approved_ratio"] = float(total_clips / max(1, len(pre_render_pool)))
                    if _recovery_meta.get("pool_fallback_used"):
                        logger.info(
                            "FAST_FAIL_RESCUE_POOL_FALLBACK_USED task_id=%s reason=missing_segment_keys recovered=%d",
                            task_id,
                            total_clips,
                        )
                    logger.info(
                        "FAST_FAIL_RESCUE_HANDOFF_APPLIED task_id=%s render_input_count_after=%d variable=segments_to_render",
                        task_id,
                        total_clips,
                    )
                    logger.info(
                        "FAST_FAIL_EDITING_ZERO_AVOIDED task_id=%s reason=score_contract_candidates_recovered count=%d",
                        task_id,
                        total_clips,
                    )
                    logger.info(
                        "CLIP_SELECTION_REQUESTED_VS_RENDERABLE requested=%d selected=%d renderable=%d editorial_warning=%d editorial_only=%d technical=%d",
                        num_clips,
                        total_clips,
                        _renderable_candidates,
                        _editorial_only_failures,
                        _editorial_only_failures,
                        _technical_failures,
                    )
                    logger.info(
                        "EDITORIAL_CONTRACT_DEGRADED_TO_NEEDS_REVIEW task_id=%s reason=score_contract_threshold count=%d",
                        task_id,
                        total_clips,
                    )
                    _fast_fail_skipped = True
                else:
                    _fast_fail_skipped = False

                if not _fast_fail_skipped and _pre_reasons:
                    _reason_preview = "; ".join(
                        [
                            str(item.get("reason") or "pre_render_qc_failed")
                            for item in _pre_reasons[:6]
                        ]
                    )
                    logger.error(
                        "FAST_FAIL_EDITING_ZERO_DIAGNOSTIC task_id=%s total_clips=%d failed_candidates=%d rejected_count=%d pre_render_pool_count=%d render_input_count=%d selected_count=%d sample_reasons=%s sample_keys=%s",
                        task_id,
                        total_clips,
                        len(_pre_reasons),
                        len(_pre_reasons),
                        len(pre_render_pool),
                        len(segments_to_render),
                        len(segments_to_render),
                        ",".join(str(x) for x in _recovery_meta.get("sample_reasons", [])[:5]) or _reason_preview,
                        ",".join(str(x) for x in _recovery_meta.get("sample_keys", [])[:5]) or "none",
                    )
                    logger.error(
                        "FAST_FAIL_EDITING_ZERO task_id=%s failed_candidates=%d",
                        task_id,
                        len(_pre_reasons),
                    )
                    await self.task_repo.update_task_failure_details(
                        self.db,
                        task_id,
                        error_code="FAST_FAIL_EDITING_ZERO",
                        error_message=f"Pre-render editorial QC rejected all candidates: {_reason_preview[:420]}",
                        progress_message="fast_fail_editing_zero",
                        progress=100,
                    )
                    stage_timings["delivery_status"] = "fast_fail_editing_zero"
                    stage_timings["delivery_shortage_reason"] = "pre_render_qc_all_failed"
                    await self.task_repo.update_task_runtime_metadata(
                        self.db,
                        task_id,
                        completed_at=datetime.now(timezone.utc),
                        stage_timings_json=json.dumps(_normalize_json_for_context(task_id, "delivery_summary", stage_timings)),
                        error_code="FAST_FAIL_EDITING_ZERO",
                    )
                    if progress_callback:
                        await progress_callback(100, "fast_fail_editing_zero", "error")
                    return {
                        "task_id": task_id,
                        "clips_count": 0,
                        "segments": [],
                        "summary": result.get("summary"),
                        "key_topics": result.get("key_topics"),
                        "error": "fast_fail_editing_zero",
                        "reason": "pre_render_qc_all_failed",
                    }
                _pipeline_result_count = len(result.get("segments_to_render") or []) if isinstance(result, dict) else 0
                _actual_render_input_count = len(segments_to_render)
                logger.error(
                    "SEGMENTS_TO_RENDER_DIAGNOSTIC task_id=%s pipeline_result_count=%d actual_render_input_count=%d",
                    task_id,
                    _pipeline_result_count,
                    _actual_render_input_count,
                )
                if _actual_render_input_count <= 0:
                    logger.error(
                        f"[TASK {task_id}] ❌❌❌ CRITICAL: segments_to_render is EMPTY! "
                        f"This will cause 'No Clips Generated' error."
                    )
                else:
                    logger.info(
                        "[TASK %s] render input preserved after rescue count=%d",
                        task_id,
                        _actual_render_input_count,
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
            _stale_clip_outputs_removed = 0
            for _old_file in clips_output_dir.glob("*"):
                if _old_file.is_file():
                    _old_file.unlink(missing_ok=True)
                    _stale_clip_outputs_removed += 1
            if _stale_clip_outputs_removed:
                logger.info(
                    "CACHE_BYPASSED task_id=%s context=final_outputs reason=stale_task_outputs_cleared removed=%d",
                    task_id,
                    _stale_clip_outputs_removed,
                )

            output_root = Path("/app/outputs/tasks") / task_id
            output_clips_dir = output_root / "clips"
            output_manifests_dir = output_root / "manifests"
            output_summaries_dir = output_root / "summaries"
            output_review_dir = output_root / "review"
            for _output_dir in (output_clips_dir, output_manifests_dir, output_summaries_dir, output_review_dir):
                _output_dir.mkdir(parents=True, exist_ok=True)
                for _old_file in _output_dir.glob("*"):
                    if _old_file.is_file():
                        _old_file.unlink(missing_ok=True)
            output_manifest_path = output_manifests_dir / "vpi_output_manifest.json"
            output_summary_path = output_summaries_dir / "vpi_clip_summary.md"
            review_bundle_json_path = output_review_dir / "review_bundle.json"
            review_index_path = output_review_dir / "review_index.html"
            output_management_payload = {
                "output_root": str(output_root),
                "clips_output_dir": str(output_clips_dir),
                "manifest_output_path": str(output_manifest_path),
                "summary_output_path": str(output_summary_path),
                "review_bundle_dir": str(output_review_dir),
                "review_index_path": str(review_index_path),
                "review_json_path": str(review_bundle_json_path),
                "output_filename_strategy": "vpi_{campaign_intent}_{clip_angle}_{confidence}_{start}_{end}_{clip_id_hash}",
                "output_filename_safe": True,
                "output_filename_collision_resolved": False,
                "output_management_ok": False,
                "output_management_warnings": [],
                "output_clip_count": 0,
                "publishable_clip_count": 0,
                "review_clip_count": 0,
                "high_confidence_clip_count": 0,
                "vpi_daily_mode_enabled": bool(daily_mode_policy.get("vpi_daily_mode_enabled")),
                "daily_mode_version": str(daily_mode_policy.get("daily_mode_version") or "a1"),
                "daily_mode_policy": dict(daily_mode_policy),
                "daily_mode_outputs_enabled": bool(daily_mode_policy.get("daily_mode_outputs_enabled", False)),
                "daily_mode_conflicts_resolved": list(daily_mode_policy.get("daily_mode_conflicts_resolved") or []),
                "daily_mode_unsafe_override_used": bool(daily_mode_policy.get("daily_mode_unsafe_override_used")),
            }

            clip_ids: List[str] = []
            render_start = perf_counter()
            clip_render_times: Dict[int, float] = {}  # per-clip timing
            failed_clips: List[Dict[str, Any]] = []   # track failed clips with reason
            strict_runtime_qc_enforced = bool(editorial_qc_blocking and not deadline_safe_mode)
            strict_qc_rejected_count = 0
            strict_qc_rejected_reasons: List[str] = []
            stage_timings["strict_runtime_qc_enforced"] = strict_runtime_qc_enforced
            stage_timings["viraclip_mode"] = viraclip_mode
            stage_timings["premium_productive_mode"] = premium_productive_mode
            stage_timings["editorial_qc_blocking"] = editorial_qc_blocking

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
            clip_failure_details: List[Dict[str, Any]] = []

            def _segment_file_name(_idx: int, _segment: Dict[str, Any]) -> str:
                _start_str = str(_segment.get("start_time") or "0000").replace(":", "")
                _end_str = str(_segment.get("end_time") or "0000").replace(":", "")
                return f"segment_{_idx}_{_start_str}-{_end_str}.mp4"

            def _resolve_segment_source(_idx: int, _segment: Dict[str, Any]) -> Tuple[Path, bool, str]:
                _preferred = extracted_segment_paths[_idx] if _idx < len(extracted_segment_paths) else None
                if _preferred and Path(_preferred).exists():
                    if _segment.get("requires_source_window_extract") or _segment.get("generated_by") == "candidate_pool_expansion":
                        logger.info(
                            "VPI_EXPANSION_CANDIDATE_RENDER_INPUT_REPLACED task_id=%s idx=%d start=%s end=%s path=%s",
                            task_id, _idx, _segment.get("start_time"), _segment.get("end_time"), str(_preferred),
                        )
                    return Path(_preferred), True, "pre_extracted"
                _embedded = _segment.get("_extracted_segment_path")
                if _embedded and Path(str(_embedded)).exists():
                    return Path(str(_embedded)), True, "segment_embedded_path"
                _task_scoped = segments_temp_dir / _segment_file_name(_idx, _segment)
                if _task_scoped.exists():
                    return _task_scoped, True, "task_scoped_fallback"
                if _segment.get("requires_source_window_extract") or _segment.get("generated_by") == "candidate_pool_expansion":
                    logger.warning(
                        "VPI_EXPANSION_CANDIDATE_SOURCE_WINDOW_EXTRACT_REQUESTED task_id=%s idx=%d start=%s end=%s fallback=source_video",
                        task_id, _idx, _segment.get("start_time"), _segment.get("end_time"),
                    )
                return video_path, False, "source_video_fallback"

            async def _render_one(i: int, segment: Dict[str, Any]) -> Tuple[int, Optional[Dict[str, Any]], float]:
                """Render one clip under the semaphore and return (index, clip_info, elapsed_s)."""
                nonlocal completed_renders
                async with _render_sem:
                    t0 = perf_counter()
                    info = None
                    _render_timeout_s = float(
                        os.environ.get(
                            "VPI_RENDER_CLIP_TIMEOUT_S",
                            "420" if vpi_daily_mode_enabled else "900",
                        )
                    )
                    try:
                        # Use pre-extracted segment when available; otherwise fallback to a resolved source.
                        segment_source, use_extracted_segment_flag, source_resolve_reason = _resolve_segment_source(i, segment)
                        if use_extracted_segment_flag and not Path(segment_source).exists():
                            raise FileNotFoundError(f"segment_file_missing:{segment_source}")
                        if not use_extracted_segment_flag and extracted_segment_paths[i] is not None:
                            logger.warning(
                                "segment_file_missing task_id=%s clip_index=%d expected=%s fallback=%s",
                                task_id,
                                i + 1,
                                extracted_segment_paths[i],
                                source_resolve_reason,
                            )
                        
                        if deadline_safe_mode:
                            info = await asyncio.wait_for(
                                self.video_service.create_deadline_safe_clip(
                                    video_path=segment_source,
                                    segment=segment,
                                    clip_index=i,
                                    output_dir=clips_output_dir,
                                    add_subtitles=add_subtitles,
                                    caption_template=_pick_caption_template(segment),
                                    use_extracted_segment=use_extracted_segment_flag,
                                ),
                                timeout=_render_timeout_s,
                            )
                        else:
                            info = await asyncio.wait_for(
                                self.video_service.create_single_clip(
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
                                    use_extracted_segment=use_extracted_segment_flag,
                                    target_platform=target_platform,
                                    include_broll=include_broll,
                                    output_management_context=output_management_payload,
                                ),
                                timeout=_render_timeout_s,
                            )
                        info = _normalize_rendered_clip_result(info)
                        if info is not None:
                            logger.info(
                                "VPI_RENDER_RESULT_NORMALIZED task_id=%s clip_order=%d path=%s",
                                task_id,
                                i + 1,
                                str(info.get("path") or ""),
                            )
                            info["segment_source_path"] = str(segment_source)
                            info["segment_source_mode"] = source_resolve_reason
                        if not info or not Path(str(info.get("path") or "")).exists():
                            _recovered_temp = _find_valid_temp_finish_mp4(task_id, i + 1)
                            if _recovered_temp is not None:
                                logger.warning(
                                    "VPI_RENDER_RESULT_FALLBACK_TEMP_FINISH_USED task_id=%s clip_order=%d path=%s",
                                    task_id,
                                    i + 1,
                                    str(_recovered_temp),
                                )
                                # H7.7: Preserve StageRecorder diagnostic data through fallback recovery
                                _stage_recorder_from_info = info.get("stage_recorder") if info else None
                                info = _build_recovered_clip_info_from_path(
                                    recovered_path=_recovered_temp,
                                    segment=segment,
                                    clip_order=i + 1,
                                    stage_recorder=_stage_recorder_from_info,
                                    add_subtitles=add_subtitles,
                                    task_id=task_id,
                                )
                                info["segment_source_path"] = str(segment_source)
                                info["segment_source_mode"] = source_resolve_reason
                    except ClipEditorialRejection as _cer:
                        logger.info(
                            "CLIP_RENDER_ABORTED_BY_EDITORIAL_QC clip_order=%d stage=%s reason=%s",
                            _cer.clip_order, _cer.stage, _cer.reason,
                        )
                        clip_failure_details.append(
                            {
                                "clip_index": _cer.clip_order,
                                "start_time": segment.get("start_time"),
                                "end_time": segment.get("end_time"),
                                "stage": _cer.stage,
                                "reason": _cer.reason,
                            }
                        )
                        info = None
                    except asyncio.TimeoutError as clip_timeout:
                        _recovered_temp = _find_valid_temp_finish_mp4(task_id, i + 1)
                        if _recovered_temp is not None:
                            logger.warning(
                                "VPI_RENDER_RESULT_FALLBACK_TEMP_FINISH_USED task_id=%s clip_order=%d path=%s reason=timeout",
                                task_id,
                                i + 1,
                                str(_recovered_temp),
                            )
                            # H7.7: Preserve StageRecorder diagnostic data through fallback recovery
                            _stage_recorder_from_timeout = info.get("stage_recorder") if info else None
                            info = _build_recovered_clip_info_from_path(
                                recovered_path=_recovered_temp,
                                segment=segment,
                                clip_order=i + 1,
                                stage_recorder=_stage_recorder_from_timeout,
                                add_subtitles=add_subtitles,
                                task_id=task_id,
                            )
                            info["segment_source_path"] = str(segment_source)
                            info["segment_source_mode"] = source_resolve_reason
                        else:
                            logger.error(
                                "Exception rendering clip %d/%d (%s → %s): %s",
                                i + 1,
                                total_clips,
                                segment.get("start_time"),
                                segment.get("end_time"),
                                clip_timeout,
                                exc_info=True,
                            )
                            clip_failure_details.append(
                                {
                                    "clip_index": i + 1,
                                    "start_time": segment.get("start_time"),
                                    "end_time": segment.get("end_time"),
                                    "stage": "render_timeout",
                                    "reason": f"{clip_timeout}"[:240],
                                }
                            )
                            info = None
                    except Exception as clip_error:
                        logger.error(
                            f"Exception rendering clip {i+1}/{total_clips} "
                            f"({segment.get('start_time')} → {segment.get('end_time')}): {clip_error}",
                            exc_info=True
                        )
                        _recovered_temp = _find_valid_temp_finish_mp4(task_id, i + 1)
                        if _recovered_temp is not None:
                            logger.warning(
                                "VPI_RENDER_RESULT_FALLBACK_TEMP_FINISH_USED task_id=%s clip_order=%d path=%s reason=%s",
                                task_id,
                                i + 1,
                                str(_recovered_temp),
                                clip_error,
                            )
                            # H7.7: Preserve StageRecorder diagnostic data through fallback recovery
                            _stage_recorder_from_exc = info.get("stage_recorder") if info else None
                            info = _build_recovered_clip_info_from_path(
                                recovered_path=_recovered_temp,
                                segment=segment,
                                clip_order=i + 1,
                                stage_recorder=_stage_recorder_from_exc,
                                add_subtitles=add_subtitles,
                                task_id=task_id,
                            )
                            info["segment_source_path"] = str(segment_source)
                            info["segment_source_mode"] = source_resolve_reason
                        else:
                            _reason = str(clip_error)
                            _stage = "segment_file_missing" if ("segment_file_missing" in _reason.lower() or "not found" in _reason.lower()) else "render_failed"
                            clip_failure_details.append(
                                {
                                    "clip_index": i + 1,
                                    "start_time": segment.get("start_time"),
                                    "end_time": segment.get("end_time"),
                                    "stage": _stage,
                                    "reason": _reason[:240],
                                }
                            )
                            info = None

                    # ── Phase 9: Creative Engine post-render enhancement ──────────────
                    # Applies: hook-flash reorder, zoom punch, B-roll overlay,
                    # audio mastering (EBU R128), QA check, learning-loop manifest.
                    # All steps are independently guarded — never breaks clip delivery.
                    # ── Phase 9: Creative Engine post-render enhancement ──────────────
                    if info is not None and not deadline_safe_mode:
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

                    # ── Phase 10: ComfyUI AI Enhancement (opt-in) ─────────────────────
                    # Applies: 9:16 reframe with AI, AI thumbnail generation, subtitle enhancement
                    if info is not None:
                        try:
                            from .vpi_production_safe_edit import (
                                production_safe_edit_enabled as _production_safe_edit_enabled,
                                production_safe_route_allowed as _production_safe_route_allowed,
                            )
                            clip_path = Path(info["path"])
                            if _production_safe_edit_enabled() and not _production_safe_route_allowed("comfyui"):
                                logger.info(
                                    "PRODUCTION_SAFE_ROUTE_BLOCKED route=comfyui reason=premium_local_stability task_id=%s clip_order=%d",
                                    task_id,
                                    i + 1,
                                )
                            else:
                                # ComfyUI 9:16 Reframe
                                if use_comfyui_reframe and output_format == "vertical":
                                    logger.info("  [Clip %d] Phase 10a: ComfyUI 9:16 reframe...", i + 1)
                                    reframe_result = await comfyui_integration.process_with_comfyui(
                                        task_id=f"{task_id}_c{i}",
                                        video_path=clip_path,
                                        operation="reframe_9_16",
                                        progress_callback=lambda p, msg: None,
                                        chunk_size=comfyui_chunk_size,
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
                                        prompt=thumbnail_prompt,
                                    )
                                    if thumb_result:
                                        info["comfyui_thumbnail"] = str(thumb_result)
                                        logger.info("  [Clip %d] Phase 10b ✓", i + 1)

                                # ComfyUI Subtitle Enhancement (if enabled)
                                if use_comfyui_subtitles and add_subtitles:
                                    logger.info("  [Clip %d] Phase 10c: ComfyUI subtitle enhancement...", i + 1)
                                    # Note: Subtitle enhancement would be integrated with existing subtitle flow
                                    info["comfyui_subtitles"] = True
                                
                        except Exception as _cu_e:
                            logger.warning("Phase 10 ComfyUI skipped for clip %d: %s", i, _cu_e)
                    # ─────────────────────────────────────────────────────────────────

                    elapsed = round(perf_counter() - t0, 3)
                    
                    # Update progress as each clip completes (success or failure)
                    async with render_lock:
                        completed_renders += 1
                        render_progress = 71 + int((completed_renders / total_clips) * 20)
                        status_msg = f"Render attempted {completed_renders}/{total_clips} clips..."
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
            _stale_segment_files_removed = 0
            for _old_file in segments_temp_dir.glob("*"):
                if _old_file.is_file():
                    _old_file.unlink(missing_ok=True)
                    _stale_segment_files_removed += 1
            if _stale_segment_files_removed:
                logger.info(
                    "CACHE_BYPASSED task_id=%s context=extracted_segments reason=stale_task_segments_cleared removed=%d",
                    task_id,
                    _stale_segment_files_removed,
                )

            # Preserve editorial clip boundaries from AI selection.  Only apply a
            # small defensive extension for very short clips; do not pad by
            # virality, because that can pull in a second idea.
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

            _transcript_lines_for_bounds = _parse_timestamped_transcript_lines(str(result.get("transcript") or ""))
            for _seg in segments_to_render:
                _seg["_source_video_path"] = str(video_path)
                _adjust_segment_semantic_boundaries(
                    task_id=task_id,
                    segment=_seg,
                    transcript_lines=_transcript_lines_for_bounds,
                    video_duration_s=_video_dur,
                )
                _s0 = parse_timestamp_to_seconds(_seg["start_time"])
                _e0 = parse_timestamp_to_seconds(_seg["end_time"])
                _dur = max(0.0, _e0 - _s0)
                if _dur >= 18.0:
                    logger.info(
                        "[pre-extract] preserving editorial boundaries %s → %s (%.1fs)",
                        _seg.get("start_time"),
                        _seg.get("end_time"),
                        _dur,
                    )
                    continue

                _new_end = _e0
                if _dur > 0:
                    _new_end = min(_s0 + 18.0, _e0 + 3.0)
                    if _video_dur:
                        _new_end = min(_new_end, max(_s0 + _dur, _video_dur - 1.0))

                if _new_end > _e0:
                    # OUTPUT-SELECTION-4: never pad forward into backstage / production talk.
                    _pad_zone = [
                        line for line in _transcript_lines_for_bounds
                        if float(line.get("end", 0.0)) > _e0 and float(line.get("start", 0.0)) < _new_end
                    ]
                    _pad_blocked = any(
                        _classify_transcript_line_for_publishing(str(line.get("text") or "")) == "backstage"
                        for line in _pad_zone
                    )
                    if _pad_blocked:
                        logger.info(
                            "VPI_OUTPUT_SELECTION_FORWARD_PADDING_BLOCKED task_id=%s window_end=%.2f attempted_end=%.2f reason=backstage_in_padding_zone",
                            task_id, _e0, _new_end,
                        )
                    else:
                        _seg["end_time"] = f"{int(_new_end) // 60:02d}:{int(_new_end) % 60:02d}"
                        logger.warning(
                            "[pre-extract] short editorial segment %.1fs extended conservatively to %s",
                            _dur,
                            _seg["end_time"],
                        )
                else:
                    logger.warning(
                        "[pre-extract] short editorial segment %.1fs kept unchanged; cannot safely infer same idea",
                        _dur,
                    )

            # OUTPUT-SELECTION-4: final boundary clamp AFTER every expansion
            # (boundary refinement, semantic adjustment, min-duration top-up) and
            # immediately before extraction — the actual final render range.
            _cached_words_for_output_selection = _load_cached_words_for_output_selection(video_path)
            if not _cached_words_for_output_selection:
                try:
                    from ..video_processing.transcription import get_video_transcript

                    logger.info(
                        "VPI_OUTPUT_SELECTION_WORDLEVEL_HEAD_AUDIT task_id=%s source=transcript_cache_rehydrate",
                        task_id,
                    )
                    _transcript_text_rehydrated, _transcript_data_rehydrated = await get_video_transcript(
                        video_path,
                        use_cache=True,
                    )
                    if isinstance(_transcript_data_rehydrated, dict) and isinstance(
                        _transcript_data_rehydrated.get("words"), list
                    ):
                        _cached_words_for_output_selection = _load_cached_words_for_output_selection(video_path)
                    if not _cached_words_for_output_selection:
                        logger.info(
                            "VPI_OUTPUT_SELECTION_WORDLEVEL_HEAD_AUDIT task_id=%s source=fresh_word_timings",
                            task_id,
                        )
                        _fresh_transcript_text, _fresh_transcript_data = await get_video_transcript(
                            video_path,
                            use_cache=False,
                        )
                        if isinstance(_fresh_transcript_data, dict) and isinstance(
                            _fresh_transcript_data.get("words"), list
                        ):
                            _cached_words_for_output_selection = _load_cached_words_for_output_selection(video_path)
                except Exception as _word_cache_e:
                    logger.info(
                        "VPI_OUTPUT_SELECTION_WORDLEVEL_START_TRIM_SKIPPED task_id=%s reason=word_cache_rehydrate_failed error=%s",
                        task_id,
                        str(_word_cache_e)[:160],
                    )
            if _cached_words_for_output_selection:
                logger.info(
                    "VPI_OUTPUT_SELECTION_WORDLEVEL_HEAD_AUDIT task_id=%s source=cached_words words=%d",
                    task_id, len(_cached_words_for_output_selection),
                )
            else:
                logger.info(
                    "VPI_OUTPUT_SELECTION_WORDLEVEL_START_TRIM_SKIPPED task_id=%s reason=no_cached_words",
                    task_id,
                )
            for _clean_idx, _seg in enumerate(segments_to_render):
                try:
                    _trim_unpublishable_tail_from_segment(
                        task_id=task_id,
                        segment=_seg,
                        transcript_lines=_transcript_lines_for_bounds,
                        video_duration_s=_video_dur,
                        clip_order=_clean_idx + 1,
                        cached_words=_cached_words_for_output_selection,
                    )
                except Exception as _anti_tail_e:
                    logger.warning(
                        "VPI_OUTPUT_SELECTION_TAIL_TRIM_SKIPPED task_id=%s clip_order=%d reason=exception:%s",
                        task_id, _clean_idx + 1, _anti_tail_e,
                    )
                try:
                    _pre_closure_end_marker = str(_seg.get("end_time") or "")
                    _apply_speech_closure_guard(
                        task_id=task_id,
                        segment=_seg,
                        cached_words=_cached_words_for_output_selection,
                        clip_order=_clean_idx + 1,
                        video_duration_s=_video_dur,
                    )
                    _closure_changed_end = str(_seg.get("end_time") or "") != _pre_closure_end_marker
                except Exception as _closure_e:
                    _closure_changed_end = False
                    logger.warning(
                        "VPI_OUTPUT_SELECTION_SPEECH_CLOSURE_FINAL_BOUNDARY task_id=%s clip_order=%d changed=false reason=exception:%s",
                        task_id, _clean_idx + 1, _closure_e,
                    )
                try:
                    _pre_narrative_end_marker = str(_seg.get("end_time") or "")
                    _apply_narrative_closure_planner(
                        task_id=task_id,
                        segment=_seg,
                        cached_words=_cached_words_for_output_selection,
                        clip_order=_clean_idx + 1,
                        video_duration_s=_video_dur,
                    )
                    if str(_seg.get("end_time") or "") != _pre_narrative_end_marker:
                        _closure_changed_end = True
                except Exception as _narrative_e:
                    logger.warning(
                        "VPI_OUTPUT_NARRATIVE_FINAL_CLOSE_SELECTED task_id=%s clip_order=%d changed=false reason=exception:%s",
                        task_id, _clean_idx + 1, _narrative_e,
                    )
                try:
                    _pre_opening_start_marker = str(_seg.get("start_time") or "")
                    _apply_narrative_opening_planner(
                        task_id=task_id,
                        segment=_seg,
                        cached_words=_cached_words_for_output_selection,
                        clip_order=_clean_idx + 1,
                        video_duration_s=_video_dur,
                    )
                    if str(_seg.get("start_time") or "") != _pre_opening_start_marker:
                        _closure_changed_end = True
                except Exception as _opening_e:
                    logger.warning(
                        "VPI_OUTPUT_NARRATIVE_FINAL_OPENING_SELECTED task_id=%s clip_order=%d changed=false reason=exception:%s",
                        task_id, _clean_idx + 1, _opening_e,
                    )
                try:
                    _build_post_trim_caption_contract(
                        task_id=task_id,
                        segment=_seg,
                        cached_words=_cached_words_for_output_selection,
                        transcript_lines=_transcript_lines_for_bounds,
                        clip_order=_clean_idx + 1,
                    )
                    if _closure_changed_end:
                        logger.info(
                            "VPI_OUTPUT_SELECTION_CLOSURE_CONTRACT_REBUILT task_id=%s clip_order=%d end=%s words=%d",
                            task_id, _clean_idx + 1,
                            str(_seg.get("end_time") or ""),
                            int(_seg.get("post_trim_caption_words_count") or 0),
                        )
                        logger.info(
                            "VPI_OUTPUT_SELECTION_CLOSURE_CAPTIONS_ALIGNED task_id=%s clip_order=%d relative_to=clean_final_start_s last_word=%s",
                            task_id, _clean_idx + 1,
                            str(_seg.get("post_trim_caption_last_word") or "")[:24],
                        )
                except Exception as _contract_e:
                    logger.warning(
                        "VPI_OUTPUT_SELECTION_POST_TRIM_CAPTION_CONTRACT_EMPTY task_id=%s clip_order=%d fallback=exception:%s",
                        task_id, _clean_idx + 1, _contract_e,
                    )

            # When subtitles are enabled, use exact seek (re-encode) so the
            # pre-extracted segment starts at the exact frame — critical for
            # word-timestamp sync.  Without subtitles, fast stream copy is fine.
            _exact_seek = bool(add_subtitles)
            if _exact_seek:
                logger.info(
                    "[extract] exact_seek enabled because subtitles are enabled "
                    "— using precise re-encode for %d segments",
                    total_clips,
                )
            extracted_segment_paths = await extract_segments_fast(
                video_path=video_path,
                segments=segments_to_render,
                output_dir=segments_temp_dir,
                task_id=task_id,
                exact_seek=_exact_seek,
            )
            
            # Log extraction success rate
            successful_extractions = sum(1 for p in extracted_segment_paths if p is not None)
            for _seg_idx, _seg_obj in enumerate(segments_to_render):
                _extracted_path = extracted_segment_paths[_seg_idx] if _seg_idx < len(extracted_segment_paths) else None
                _seg_obj["_extracted_segment_path"] = str(_extracted_path) if _extracted_path else None
                _is_expansion = (
                    _seg_obj.get("requires_source_window_extract")
                    or _seg_obj.get("generated_by") == "candidate_pool_expansion"
                    or _seg_obj.get("render_source_mode") == "full_source_window"
                )
                if _is_expansion:
                    if _extracted_path:
                        logger.info(
                            "VPI_EXPANSION_CANDIDATE_SOURCE_WINDOW_EXTRACTED task_id=%s idx=%d start=%s end=%s path=%s",
                            task_id, _seg_idx, _seg_obj.get("start_time"), _seg_obj.get("end_time"), str(_extracted_path),
                        )
                        _seg_obj["source_window_extract_path"] = str(_extracted_path)
                        _seg_obj["source_window_extract_ok"] = True
                        _seg_obj["rendered_from_expansion_candidate"] = True
                        _seg_obj["actual_render_start_time"] = _seg_obj.get("start_time")
                        _seg_obj["actual_render_end_time"] = _seg_obj.get("end_time")
                        _seg_obj["render_source_mode"] = "full_source_window"
                    else:
                        logger.warning(
                            "VPI_EXPANSION_CANDIDATE_SOURCE_WINDOW_EXTRACT_FAILED task_id=%s idx=%d start=%s end=%s",
                            task_id, _seg_idx, _seg_obj.get("start_time"), _seg_obj.get("end_time"),
                        )
                        _seg_obj["source_window_extract_ok"] = False
                        _seg_obj["rendered_from_expansion_candidate"] = False
            mode = "exact" if _exact_seek else "fast"
            logger.info(
                f"Pre-extraction complete ({mode}): {successful_extractions}/{total_clips} segments "
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

            # H14.15: post-boundary-refinement / post-render, pre-accept
            # duplicate guard. Drops any clip whose FINAL refined window +
            # generated ASS text converges with an already-accepted clip,
            # before any contract/gate/manifest code processes it.
            render_results, _h1415_dedupe_info = _h1415_apply_post_refinement_dedupe(
                task_id, segments_to_render, render_results, int(num_clips),
            )
            # OUTPUT RESCUE Fix C: deduped clips must surface as explained failures,
            # not silently shrink the delivered count.
            for _dedupe_detail in (_h1415_dedupe_info.get("removed_details") or []):
                clip_failure_details.append(dict(_dedupe_detail))

            # ── VPI Premium Productive Hardening: First Clip Probe ──────────
            # When render_first_clip_probe is enabled in premium_productive mode,
            # we check whether the first rendered clip can be successfully inserted.
            # If it cannot (render failure, technical QC failure, or publishable gate
            # rejection), we abort the remaining renders to avoid wasting resources.
            if (
                getattr(self.config, "render_first_clip_probe", False)
                and premium_productive_mode
                and render_results
            ):
                _probe_idx, _probe_info, _probe_elapsed = render_results[0]
                _probe_segment = segments_to_render[_probe_idx]
                _probe_failed = False
                _probe_reason = ""

                if _probe_info is None:
                    _probe_failed = True
                    _probe_reason = "render_failed"
                else:
                    # Build final contract for the probe clip
                    try:
                        _probe_info["final_rendered_contract"] = _build_final_rendered_clip_contract(
                            task_id=task_id,
                            clip_order=_probe_idx + 1,
                            segment=_probe_segment,
                            clip_info=_probe_info,
                        )
                    except Exception as _probe_contract_e:
                        logger.warning(
                            "FIRST_CLIP_PROBE_CONTRACT_BUILD_FAILED task_id=%s error=%s",
                            task_id,
                            _probe_contract_e,
                        )

                    # Run technical QC on the probe clip
                    _probe_technical_qc = _build_clip_technical_qc(
                        path=Path(str(_probe_info.get("path") or "")),
                        clip_info=_probe_info,
                        min_duration_s=8.0,
                    )
                    if not bool(_probe_technical_qc.get("passed")):
                        _probe_failed = True
                        _probe_reason = "technical_qc_failed:" + "|".join(
                            str(x) for x in (_probe_technical_qc.get("reasons") or [])
                        )

                if _probe_failed:
                    logger.warning(
                        "FIRST_CLIP_PROBE_FAILED task_id=%s clip_order=%d reason=%s",
                        task_id,
                        _probe_idx + 1,
                        _probe_reason,
                    )
                    # Abort remaining renders — skip the per-clip diagnostics and
                    # the persist loop entirely.
                    render_results = render_results[:0]  # empty the list
                else:
                    logger.info(
                        "FIRST_CLIP_PROBE_PASSED task_id=%s clip_order=%d",
                        task_id,
                        _probe_idx + 1,
                    )
            # ──────────────────────────────────────────────────────────────────

            # ── Explicit per-clip diagnostics ─────────────────────────────────
            logger.info("RENDER_SUMMARY_HEADER attempted=%d", total_clips)
            for _ri, _rinfo, _relapsed in render_results:
                _seg = segments_to_render[_ri]
                logger.info("RENDER_ATTEMPTED clip_order=%d", _ri + 1)
                if _rinfo is not None:
                    logger.info(
                        "RENDER_SUCCESS clip_order=%d elapsed_s=%.1f start=%s end=%s virality=%s",
                        _ri + 1,
                        _relapsed,
                        _seg.get("start_time"),
                        _seg.get("end_time"),
                        str(_seg.get("virality_score", "?")),
                    )
                else:
                    _failed = next((x for x in clip_failure_details if int(x.get("clip_index") or 0) == (_ri + 1)), {})
                    logger.info(
                        "RENDER_FAILED clip_order=%d stage=%s reason=%s",
                        _ri + 1,
                        str(_failed.get("stage") or "render_failed"),
                        str(_failed.get("reason") or "unknown"),
                    )
            successful_renders = sum(1 for _, info, _ in render_results if info is not None)
            failed_renders = max(0, int(total_clips) - int(successful_renders))
            logger.info(
                "RENDER_SUMMARY attempted=%d succeeded=%d failed=%d",
                total_clips,
                successful_renders,
                failed_renders,
            )
            _batch_broll_counts: Dict[str, int] = {}
            for _ri, _rinfo, _relapsed in render_results:
                if not _rinfo:
                    continue
                for _broll_item in (_rinfo.get("editorial_broll") or []):
                    _asset_id = str(
                        _broll_item.get("asset_id")
                        or _broll_item.get("asset_path")
                        or _broll_item.get("asset_url")
                        or ""
                    )
                    if _asset_id:
                        _batch_broll_counts[_asset_id] = _batch_broll_counts.get(_asset_id, 0) + 1
            # ──────────────────────────────────────────────────────────────────

            # Persist results sequentially (DB ops must be on the event loop thread)
            saved_clips = 0
            rejected_candidate_reasons: List[Dict[str, Any]] = []
            for i, clip_info, elapsed in render_results:
                # Stop once we've saved the requested number of clips.
                # Extra buffer segments are only used when earlier clips fail.
                if saved_clips >= num_clips:
                    logger.debug(f"  Quota reached ({num_clips}), skipping buffer clip {i+1}")
                    break

                segment = segments_to_render[i]
                clip_render_times[i + 1] = elapsed

                if clip_info is None:
                    _recovered_temp = _find_valid_temp_finish_mp4(task_id, i + 1)
                    if _recovered_temp is not None:
                        logger.warning(
                            "VPI_POST_RENDER_RECOVERED_WITH_VALID_MP4 task_id=%s clip_order=%d path=%s",
                            task_id,
                            i + 1,
                            str(_recovered_temp),
                        )
                        clip_info = _build_recovered_clip_info_from_path(
                            recovered_path=_recovered_temp,
                            segment=segment,
                            clip_order=i + 1,
                            add_subtitles=add_subtitles,
                            task_id=task_id,
                        )
                    else:
                        failure = {
                            "clip_index": i + 1,
                            "start_time": segment.get("start_time"),
                            "end_time": segment.get("end_time"),
                            "render_time_s": elapsed,
                            "reason": "render_failed",
                        }
                        for _detail in reversed(clip_failure_details):
                            if _detail.get("clip_index") == i + 1:
                                failure["reason"] = str(_detail.get("stage") or "render_failed")
                                failure["detail"] = _detail.get("reason")
                                break
                        failed_clips.append(failure)
                        rejected_candidate_reasons.append(failure)
                        logger.info("[clip-count] rejected index=%d reason=render_failed", i + 1)
                        logger.warning(
                            f"Clip {i+1}/{total_clips} failed to render in {elapsed:.1f}s "
                            f"({segment.get('start_time')} → {segment.get('end_time')})"
                        )
                        continue

                # OUTPUT RESCUE Fix A: a "successful" render can still arrive without any
                # burned captions (the daily-mode base render defers the subtitle burn to a
                # premium ASS stage that may be skipped). If subtitles were requested and
                # transcript text exists but there is no caption-burn evidence, burn a
                # fallback ASS onto the final MP4 before QC / durable copy / DB insert.
                try:
                    _rescue_captions_evident = bool(
                        clip_info.get("has_ass_captions")
                        or int(clip_info.get("ass_event_count_final") or 0) > 0
                        or str(clip_info.get("caption_backend") or "").strip()
                    )
                    _rescue_text = str(clip_info.get("text") or segment.get("text") or "").strip()
                    _rescue_path = Path(str(clip_info.get("path") or ""))
                    if add_subtitles and not _rescue_captions_evident and _rescue_path.exists():
                        if not _rescue_text:
                            clip_info["subtitles_present"] = False
                            clip_info["subtitles_absent_reason"] = "no_transcript_text"
                            logger.warning(
                                "VPI_OUTPUT_RESCUE_CAPTIONS_FAILED task_id=%s clip_order=%d reason=no_transcript_text",
                                task_id, i + 1,
                            )
                        else:
                            logger.info(
                                "VPI_OUTPUT_RESCUE_CAPTIONS_FORCED task_id=%s clip_order=%d path=%s",
                                task_id, i + 1, str(_rescue_path),
                            )
                            _rescue_duration = float(clip_info.get("duration") or 0.0)
                            _rescue_segment = dict(segment)
                            _rescue_segment.setdefault("text", _rescue_text)
                            _rescue_result = _apply_output_basic_caption_safety_net(
                                video_path=_rescue_path,
                                segment=_rescue_segment,
                                clip_order=i + 1,
                                task_id=task_id,
                                duration=_rescue_duration if _rescue_duration > 0 else 30.0,
                            )
                            if _rescue_result.get("applied"):
                                _rescued_path = Path(str(_rescue_result["path"]))
                                _rescue_events = int(_rescue_result.get("ass_event_count_final") or 0)
                                clip_info["path"] = str(_rescued_path)
                                clip_info["filename"] = _rescued_path.name
                                clip_info["has_ass_captions"] = True
                                clip_info["ass_event_count_final"] = _rescue_events
                                clip_info["ass_caption_events_count"] = _rescue_events
                                clip_info["ass_caption_file_path"] = _rescue_result.get("ass_caption_file_path")
                                clip_info["caption_backend"] = "output_rescue_fallback_ass"
                                clip_info["caption_fallback_reason"] = "output_rescue_forced_fallback_ass_burn"
                                clip_info["subtitles_present"] = True
                                clip_info["final_captions_present"] = True
                                logger.info(
                                    "VPI_OUTPUT_RESCUE_FALLBACK_ASS_CREATED task_id=%s clip_order=%d path=%s",
                                    task_id, i + 1, str(_rescue_result.get("ass_caption_file_path") or ""),
                                )
                                logger.info(
                                    "VPI_OUTPUT_RESCUE_ASS_EVENTS task_id=%s clip_order=%d count=%d",
                                    task_id, i + 1, _rescue_events,
                                )
                                logger.info(
                                    "VPI_OUTPUT_RESCUE_ASS_BURNED task_id=%s clip_order=%d path=%s",
                                    task_id, i + 1, str(_rescued_path),
                                )
                                logger.info(
                                    "VPI_OUTPUT_RESCUE_CAPTIONS_VERIFIED task_id=%s clip_order=%d ass_events=%d",
                                    task_id, i + 1, _rescue_events,
                                )
                            else:
                                clip_info["subtitles_present"] = False
                                logger.warning(
                                    "VPI_OUTPUT_RESCUE_CAPTIONS_FAILED task_id=%s clip_order=%d reason=fallback_ass_burn_failed",
                                    task_id, i + 1,
                                )
                    elif add_subtitles and _rescue_captions_evident:
                        clip_info.setdefault("subtitles_present", True)
                except Exception as _rescue_cap_e:
                    logger.warning(
                        "VPI_OUTPUT_RESCUE_CAPTIONS_FAILED task_id=%s clip_order=%d reason=exception:%s",
                        task_id, i + 1, _rescue_cap_e,
                    )

                _rendered_output_path = Path(str(clip_info.get("path") or ""))
                if _rendered_output_path.exists():
                    try:
                        _tech_ok, _tech_reason, _tech_meta = _deadline_safe_technical_gate(_rendered_output_path)
                        if _tech_ok:
                            logger.info(
                                "VPI_POST_RENDER_TEMP_FINAL_DETECTED task_id=%s clip_order=%d path=%s duration=%s",
                                task_id,
                                i + 1,
                                str(_rendered_output_path),
                                str(_tech_meta.get("duration") or clip_info.get("duration") or ""),
                            )
                        _durable_output_path = _copy_to_durable_output(task_id, i + 1, _rendered_output_path)
                        logger.info(
                            "VPI_POST_RENDER_TASK_SCOPED_COPY_DONE task_id=%s clip_order=%d durable=%s",
                            task_id,
                            i + 1,
                            str(_durable_output_path),
                        )

                        # ── Browser MP4 compatibility normalization ──────────────
                        # Ensure the final MP4 has faststart (moov atom at beginning)
                        # and h264+yuv420p for browser playback.
                        _browser_normalization_nonfatal = False
                        _browser_normalized = _durable_output_path.with_name(
                            f"browser_{_durable_output_path.name}"
                        )
                        try:
                            from .video_service import ensure_browser_compatible_mp4
                            _norm_result = ensure_browser_compatible_mp4(
                                _durable_output_path, _browser_normalized
                            )
                            if _norm_result.get("success") and _browser_normalized.exists():
                                # Replace durable output with normalized version
                                _durable_output_path.unlink(missing_ok=True)
                                _browser_normalized.rename(_durable_output_path)
                                logger.info(
                                    "BROWSER_MP4_NORMALIZED task_id=%s clip_order=%d "
                                    "reason=%s",
                                    task_id, i + 1,
                                    _norm_result.get("reason", "unknown"),
                                )
                            elif not _norm_result.get("success"):
                                _browser_normalization_nonfatal = True
                                logger.warning(
                                    "BROWSER_MP4_NORMALIZATION_FAILED task_id=%s "
                                    "clip_order=%d reason=%s",
                                    task_id, i + 1,
                                    _norm_result.get("reason", "unknown"),
                                )
                        except Exception as _norm_e:
                            _browser_normalization_nonfatal = True
                            logger.warning(
                                "BROWSER_MP4_NORMALIZATION_ERROR task_id=%s "
                                "clip_order=%d error=%s",
                                task_id, i + 1, _norm_e,
                            )

                        clip_info["path_rendered_temp"] = str(_rendered_output_path)
                        clip_info["path"] = str(_durable_output_path)
                        clip_info["durable_output_path"] = str(_durable_output_path)
                        _public_url = _resolve_public_clip_url(task_id, _durable_output_path)
                        clip_info["video_url"] = _public_url
                        clip_info["public_url"] = _public_url
                        clip_info["clip_url"] = _public_url
                        logger.info(
                            "DURABLE_OUTPUT_STAGED task_id=%s clip_order=%d source=%s durable=%s",
                            task_id,
                            i + 1,
                            str(_rendered_output_path),
                            str(_durable_output_path),
                        )
                        logger.info(
                            "DURABLE_OUTPUT_PUBLIC_URL task_id=%s clip_order=%d url=%s",
                            task_id,
                            i + 1,
                            _public_url,
                        )
                        logger.info(
                            "CLIP_PLAYBACK_URL_STAGED task_id=%s clip_order=%d url=%s "
                            "file_exists=%s mime=video/mp4",
                            task_id,
                            i + 1,
                            _public_url,
                            str(_durable_output_path.exists()).lower(),
                        )
                    except Exception as _durable_e:
                        logger.warning(
                            "VPI_POST_RENDER_FINALIZATION_EXCEPTION task_id=%s clip_order=%d stage=durable_copy error=%s",
                            task_id,
                            i + 1,
                            _durable_e,
                        )
                        logger.warning(
                            "DURABLE_OUTPUT_STAGE_FAILED task_id=%s clip_order=%d path=%s error=%s",
                            task_id,
                            i + 1,
                            str(_rendered_output_path),
                            _durable_e,
                        )
                elif _rendered_output_path.name:
                    _fallback_public_url = _resolve_public_clip_url(task_id, _rendered_output_path)
                    clip_info["video_url"] = _fallback_public_url
                    clip_info["public_url"] = _fallback_public_url
                    clip_info["clip_url"] = _fallback_public_url

                try:
                    clip_info["final_rendered_contract"] = _build_final_rendered_clip_contract(
                        task_id=task_id,
                        clip_order=i + 1,
                        segment=segment,
                        clip_info=clip_info,
                    )
                    clip_info["final_mp4_contract"] = _as_dict(clip_info["final_rendered_contract"]).get("final_mp4_contract") or clip_info["final_rendered_contract"]
                    clip_info["final_truth_source"] = str(
                        _as_dict(clip_info.get("final_mp4_contract")).get("final_truth_source")
                        or "final_mp4_contract"
                    )
                    clip_info["final_output_verified"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("final_output_verified"))
                    clip_info["final_publishable"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("final_publishable"))
                    clip_info["final_needs_review"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("final_needs_review"))
                    clip_info["final_blocking_reasons"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("final_blocking_reasons") or [])
                    clip_info["final_warning_reasons"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("final_warning_reasons") or [])
                    clip_info["metadata_consistency_ok"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("metadata_consistency_ok"))
                    clip_info["metadata_consistency_errors"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("metadata_consistency_errors") or [])
                    clip_info["metadata_consistency_warnings"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("metadata_consistency_warnings") or [])
                    clip_info["phase_consistency"] = dict(_as_dict(clip_info.get("final_mp4_contract")).get("phase_consistency") or {})
                    clip_info["production_safe_policy"] = dict(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_policy") or {})
                    clip_info["production_safe_policy_version"] = str(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_policy_version") or "a4")
                    clip_info["production_safe_mode_active"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_mode_active"))
                    clip_info["production_safe_external_disabled"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_external_disabled"))
                    clip_info["production_safe_legacy_disabled"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_legacy_disabled"))
                    clip_info["production_safe_routes_allowed"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_routes_allowed") or [])
                    clip_info["production_safe_routes_blocked"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_routes_blocked") or [])
                    clip_info["vpi_daily_mode_enabled"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("vpi_daily_mode_enabled"))
                    clip_info["daily_mode_version"] = str(_as_dict(clip_info.get("final_mp4_contract")).get("daily_mode_version") or "a1")
                    clip_info["daily_mode_policy"] = dict(_as_dict(clip_info.get("final_mp4_contract")).get("daily_mode_policy") or {})
                    clip_info["daily_mode_outputs_enabled"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("daily_mode_outputs_enabled"))
                    clip_info["daily_mode_conflicts_resolved"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("daily_mode_conflicts_resolved") or [])
                    clip_info["daily_mode_unsafe_override_used"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("daily_mode_unsafe_override_used"))
                    clip_info["browser_mp4_normalization_nonfatal"] = bool(locals().get("_browser_normalization_nonfatal"))
                    clip_info["production_safe_compliant"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("production_safe_compliant"))
                    clip_info["filename_contract_mode"] = str(_as_dict(clip_info.get("final_mp4_contract")).get("filename_contract_mode") or "legacy_warning_only")
                    clip_info["legacy_routes_quarantined"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("legacy_routes_quarantined") or [])
                    clip_info["experimental_routes_quarantined"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("experimental_routes_quarantined") or [])
                    clip_info["deprecated_routes_present"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("deprecated_routes_present") or [])
                    clip_info["deprecated_routes_used"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("deprecated_routes_used") or [])
                    clip_info["deprecated_routes_blocked"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("deprecated_routes_blocked") or [])
                    clip_info["legacy_route_warning"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("legacy_route_warning") or [])
                    clip_info["premium_flow_manifest_version"] = str(_as_dict(clip_info.get("final_mp4_contract")).get("premium_flow_manifest_version") or "a1")
                    clip_info["premium_flow_manifest_ok"] = bool(_as_dict(clip_info.get("final_mp4_contract")).get("premium_flow_manifest_ok"))
                    clip_info["premium_flow_manifest_warnings"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("premium_flow_manifest_warnings") or [])
                    clip_info["premium_flow_manifest_errors"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("premium_flow_manifest_errors") or [])
                    clip_info["observed_phase_order"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("observed_phase_order") or [])
                    clip_info["missing_critical_phases"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("missing_critical_phases") or [])
                    clip_info["unexpected_mutators_after_freeze"] = list(_as_dict(clip_info.get("final_mp4_contract")).get("unexpected_mutators_after_freeze") or [])
                    clip_info["premium_flow_manifest"] = dict(_as_dict(clip_info.get("final_mp4_contract")).get("premium_flow_manifest") or {})
                    if (
                        bool(_as_dict(clip_info.get("final_mp4_contract")).get("final_probe_ok"))
                        and bool(clip_info.get("final_output_verified"))
                        and not clip_info.get("metadata_consistency_errors")
                    ):
                        logger.info(
                            "CLIP_PLAYBACK_URL_READY task_id=%s clip_order=%d url=%s file_exists=%s mime=video/mp4 metadata_consistency_warnings=%d",
                            task_id,
                            i + 1,
                            _public_url,
                            str(_durable_output_path.exists()).lower(),
                            len(clip_info.get("metadata_consistency_warnings") or []),
                        )
                    else:
                        logger.warning(
                            "CLIP_PLAYBACK_URL_BLOCKED_BY_FINAL_CONTRACT task_id=%s clip_order=%d url=%s reasons=%s metadata_consistency_errors=%s",
                            task_id,
                            i + 1,
                            _public_url,
                            "|".join(_as_dict(clip_info.get("final_mp4_contract")).get("final_blocking_reasons") or []) or "final_contract_failed",
                            "|".join(clip_info.get("metadata_consistency_errors") or []) or "none",
                        )
                except Exception as _contract_e:
                    logger.warning(
                        "FINAL_RENDER_CONTRACT_BUILD_FAILED task_id=%s clip_order=%d error=%s",
                        task_id,
                        i + 1,
                        _contract_e,
                    )

                _technical_qc = _build_clip_technical_qc(
                    path=Path(str(clip_info.get("path") or "")),
                    clip_info=clip_info,
                    min_duration_s=8.0,
                )
                clip_info["technical_qc"] = _technical_qc
                if not bool(_technical_qc.get("passed")):
                    _quality_outcome = classify_premium_output_quality(
                        _as_dict(clip_info.get("final_rendered_contract")),
                        technical_qc=_technical_qc,
                        clip_info=clip_info,
                        publishable_qc={},
                    )
                    clip_info["qc_status"] = str(_quality_outcome.get("status") or "rejected_technical")
                    clip_info["qc_reasons"] = list(_quality_outcome.get("reasons") or [])
                    clip_info["qc_warnings"] = list(_quality_outcome.get("warnings") or [])
                    logger.warning(
                        "PREMIUM_OUTPUT_QUALITY task_id=%s clip_order=%d status=%s warnings=%s",
                        task_id,
                        i + 1,
                        clip_info["qc_status"],
                        "|".join([str(x) for x in clip_info["qc_warnings"]]) or "none",
                    )
                    _technical_reasons = [str(x) for x in (_technical_qc.get("reasons") or []) if str(x)]
                    _technical_reason_text = "|".join(_technical_reasons) if _technical_reasons else "technical_qc_failed"
                    logger.warning(
                        "GENERATED_CLIP_REJECTED_BY_TECHNICAL_QC task_id=%s clip_order=%d reasons=%s",
                        task_id,
                        i + 1,
                        _technical_reason_text,
                    )
                    _reject_reason = f"technical_qc_failed:{_technical_reason_text}"
                    rejected_candidate_reasons.append({
                        "clip_index": i + 1,
                        "start_time": segment.get("start_time"),
                        "end_time": segment.get("end_time"),
                        "reason": _reject_reason,
                        "publishable_status": "technical_reject",
                    })
                    clip_failure_details.append(
                        {
                            "clip_index": i + 1,
                            "start_time": segment.get("start_time"),
                            "end_time": segment.get("end_time"),
                            "stage": "technical_qc_failed",
                            "reason": _technical_reason_text[:240],
                        }
                    )
                    logger.info("[clip-count] rejected index=%d reason=%s", i + 1, _reject_reason)
                    continue

                _clip_broll_asset_ids = [
                    str(
                        item.get("asset_id")
                        or item.get("asset_path")
                        or item.get("asset_url")
                        or ""
                    )
                    for item in (clip_info.get("editorial_broll") or [])
                    if item
                ]
                _clip_broll_asset_ids = [item for item in _clip_broll_asset_ids if item]
                if (not deadline_safe_mode) and any(_batch_broll_counts.get(item, 0) > 1 for item in _clip_broll_asset_ids):
                    _warnings = list(clip_info.get("publishable_warnings") or [])
                    if "repeated_exact_broll_same_task" not in _warnings:
                        _warnings.append("repeated_exact_broll_same_task")
                    clip_info["publishable_status"] = "not_ready"
                    clip_info["publishable_warnings"] = _warnings
                    clip_info["publishable_score"] = 0.0
                    if isinstance(clip_info.get("editing_plan"), dict):
                        clip_info["editing_plan"]["publishable_status"] = "not_ready"
                        clip_info["editing_plan"]["publishable_warnings"] = _warnings
                        clip_info["editing_plan"]["publishable_score"] = 0.0

                # ── VPI Publishable Gate v3.1: evaluate clip publishability ──
                if deadline_safe_mode:
                    clip_info["publishable_status"] = "ready_to_upload"
                    clip_info["publishable_score"] = 100.0
                    clip_info["publishable_reasons"] = ["deadline_safe_technical_gate_passed"]
                    clip_info["publishable_warnings"] = []
                    clip_info["upload_recommendation"] = UploadRecommendation.BEST_CANDIDATE.value
                    clip_info["best_candidate"] = True
                    clip_info["discard_recommended"] = False
                else:
                    try:
                        _gate_result = evaluate_clip_publishability(clip_info, segment)
                        clip_info["publishable_status"] = _gate_result.publishable_status.value
                        clip_info["publishable_score"] = _gate_result.publishable_score
                        clip_info["publishable_reasons"] = _gate_result.publishable_reasons
                        clip_info["publishable_warnings"] = _gate_result.publishable_warnings
                        clip_info["upload_recommendation"] = _gate_result.upload_recommendation.value
                        clip_info["best_candidate"] = _gate_result.best_candidate
                        clip_info["discard_recommended"] = _gate_result.discard_recommended
                        clip_info["publishable_gate"] = _gate_result.to_dict()
                        if isinstance(clip_info.get("editing_plan"), dict):
                            clip_info["editing_plan"]["publishable_status"] = _gate_result.publishable_status.value
                            clip_info["editing_plan"]["publishable_score"] = _gate_result.publishable_score
                            clip_info["editing_plan"]["publishable_warnings"] = _gate_result.publishable_warnings
                            clip_info["editing_plan"]["upload_recommendation"] = _gate_result.upload_recommendation.value
                            clip_info["editing_plan"]["best_candidate"] = _gate_result.best_candidate
                            clip_info["editing_plan"]["discard_recommended"] = _gate_result.discard_recommended
                        logger.info(
                            "[publishable-gate] clip %d status=%s score=%.1f reasons=%s",
                            i + 1,
                            _gate_result.publishable_status.value,
                            _gate_result.publishable_score,
                            _gate_result.publishable_reasons,
                        )
                    except Exception as _pg_e:
                        logger.warning("[publishable-gate] evaluation failed for clip %d: %s", i + 1, _pg_e)
                        logger.warning(
                            "PUBLISHABLE_GATE_ERROR_NONFATAL task_id=%s clip_order=%d error=%s",
                            task_id,
                            i + 1,
                            _pg_e,
                        )
                        clip_info["publishable_gate_error_nonfatal"] = True
                        # Nonfatal fallback: preserve clip for strict QC + technical checks.
                        clip_info.setdefault("publishable_status", "review_manually")
                        clip_info.setdefault("publishable_score", 0.0)
                        clip_info.setdefault("publishable_warnings", [])
                        clip_info.setdefault("publishable_reasons", [f"gate_evaluation_error: {_pg_e}"])

                _publishable_status = str(clip_info.get("publishable_status") or "").lower()
                _upload_recommendation = str(clip_info.get("upload_recommendation") or "").lower()
                _discard_recommended = bool(clip_info.get("discard_recommended"))
                if (
                    (not deadline_safe_mode)
                    and bool(editorial_qc_blocking)
                    and (
                        _discard_recommended
                        or _upload_recommendation == UploadRecommendation.DISCARD_RECOMMENDED.value
                        or _publishable_status in {"do_not_upload", "needs_fix", "not_ready"}
                    )
                ):
                    _reject_reason = (
                        "publishable_gate_blocked:"
                        + ",".join(str(r) for r in (clip_info.get("publishable_reasons") or [])[:4])
                    )
                    rejected_candidate_reasons.append({
                        "clip_index": i + 1,
                        "start_time": segment.get("start_time"),
                        "end_time": segment.get("end_time"),
                        "reason": _reject_reason,
                        "publishable_status": _publishable_status,
                    })
                    clip_failure_details.append(
                        {
                            "clip_index": i + 1,
                            "start_time": segment.get("start_time"),
                            "end_time": segment.get("end_time"),
                            "stage": "publishable_gate_blocked",
                            "reason": _reject_reason[:240],
                        }
                    )
                    logger.info("[clip-count] rejected index=%d reason=%s", i + 1, _reject_reason)
                    continue
                if (
                    (not deadline_safe_mode)
                    and (not bool(editorial_qc_blocking))
                    and (
                        _discard_recommended
                        or _upload_recommendation == UploadRecommendation.DISCARD_RECOMMENDED.value
                        or _publishable_status in {"do_not_upload", "needs_fix", "not_ready"}
                    )
                ):
                    logger.warning(
                        "EDITORIAL_QC_NONBLOCKING_OVERRIDE task_id=%s clip_order=%d status=%s recommendation=%s",
                        task_id,
                        i + 1,
                        _publishable_status,
                        _upload_recommendation,
                    )
                    _pw = [str(x) for x in (_safe_list(clip_info.get("publishable_warnings")))]
                    if "editorial_qc_needs_review_nonblocking" not in _pw:
                        _pw.append("editorial_qc_needs_review_nonblocking")
                    clip_info["publishable_warnings"] = _pw
                    clip_info["publishable_status"] = "review_manually"

                if i >= num_clips:
                    logger.info(
                        "BACKUP_CANDIDATE_USED task_id=%s original_index=%d backup_index=%d reason=primary_candidate_failed_or_rejected",
                        task_id,
                        min(i + 1, num_clips),
                        i + 1,
                    )

                if deadline_safe_mode:
                    _publishable_qc = {
                        "publishable": True,
                        "strict_publishable": True,
                        "strict_publishable_reasons": [],
                        "editing_zero_detected": False,
                        "final_output_exists": "pass",
                        "final_output_is_task_scoped": "pass",
                        "final_output_reused": "pass",
                        "subtitles_present": "pass" if add_subtitles else "review",
                        "complete_idea": "pass",
                        "hook_first_3s": "review",
                        "no_mid_sentence_cut": "review",
                        "bgm_status": "not_evaluated_deadline_safe",
                        "visual_support_status": "not_evaluated_deadline_safe",
                        "real_editing_signals": {
                            "hook": False,
                            "broll": False,
                            "visual_support": False,
                            "bgm": False,
                            "sfx": False,
                            "rhythm": False,
                            "motion_or_masking": False,
                            "transition": False,
                            "retention_edit": False,
                        },
                    }
                    _reused_output_count = 0
                else:
                    _publishable_qc = _build_publishable_qc(
                        segment,
                        clip_info,
                        strict_mode=bool(strict_runtime_qc_enforced),
                        vpi_productive_minimum=bool(getattr(self.config, "vpi_productive_minimum", True)),
                    )
                    _final_output_path = Path(str(clip_info.get("path") or ""))
                    _final_output_task_scoped = _is_task_scoped_output(_final_output_path, task_id)
                    _publishable_qc["final_output_is_task_scoped"] = "pass" if _final_output_task_scoped else "fail"
                    _reused_output_count = await self.clip_repo.count_path_reuse_in_other_tasks(
                        self.db,
                        task_id=task_id,
                        file_path=str(_final_output_path),
                    )
                    _publishable_qc["final_output_reused"] = "fail" if _reused_output_count > 0 else "pass"
                    if not _final_output_task_scoped:
                        _publishable_qc["publishable"] = False
                        _publishable_qc["final_output_scope_reason"] = "final_output_not_task_scoped"
                    if _reused_output_count > 0:
                        _publishable_qc["publishable"] = False
                        _publishable_qc["final_output_reuse_reason"] = "final_output_reused_from_other_task"
                logger.info(
                    "PUBLISHABLE_QC task_id=%s clip_index=%d publishable=%s complete_idea=%s hook_first_3s=%s no_mid_sentence_cut=%s subtitles_present=%s bgm_status=%s visual_support_status=%s",
                    task_id,
                    i + 1,
                    str(bool(_publishable_qc.get("publishable"))).lower(),
                    _publishable_qc.get("complete_idea"),
                    _publishable_qc.get("hook_first_3s"),
                    _publishable_qc.get("no_mid_sentence_cut"),
                    _publishable_qc.get("subtitles_present"),
                    _publishable_qc.get("bgm_status"),
                    _publishable_qc.get("visual_support_status"),
                )
                _signals = _publishable_qc.get("real_editing_signals") or {}
                logger.info(
                    "REAL_EDITING_SIGNALS task_id=%s clip_order=%d hook=%s broll=%s overlay=%s bgm=%s sfx=%s rhythm=%s motion=%s transition=%s retention=%s",
                    task_id,
                    i + 1,
                    str(bool(_signals.get("hook"))).lower(),
                    str(bool(_signals.get("broll"))).lower(),
                    str(bool(_signals.get("visual_support"))).lower(),
                    str(bool(_signals.get("bgm"))).lower(),
                    str(bool(_signals.get("sfx"))).lower(),
                    str(bool(_signals.get("rhythm"))).lower(),
                    str(bool(_signals.get("motion_or_masking"))).lower(),
                    str(bool(_signals.get("transition"))).lower(),
                    str(bool(_signals.get("retention_edit"))).lower(),
                )
                logger.info(
                    "PUBLISHABLE_QC_STRICT task_id=%s clip_order=%d result=%s reasons=%s",
                    task_id,
                    i + 1,
                    "pass" if bool(_publishable_qc.get("strict_publishable")) else "fail",
                    "|".join([str(x) for x in (_publishable_qc.get("strict_publishable_reasons") or [])]) or "none",
                )
                _editorial_qc = _derive_editorial_qc(_publishable_qc)
                clip_info["editorial_qc"] = _editorial_qc
                _quality_outcome = classify_premium_output_quality(
                    _as_dict(clip_info.get("final_rendered_contract")),
                    technical_qc=_technical_qc,
                    clip_info=clip_info,
                    publishable_qc=_publishable_qc,
                )
                clip_info["qc_status"] = str(_quality_outcome.get("status") or "needs_review")
                _quality_reasons = [str(x) for x in (_quality_outcome.get("reasons") or []) if str(x)]
                _quality_warnings = [str(x) for x in (_quality_outcome.get("warnings") or []) if str(x)]
                clip_info["qc_reasons"] = list(dict.fromkeys(_quality_reasons + list(_editorial_qc.get("reasons") or [])))
                clip_info["qc_warnings"] = list(dict.fromkeys(_quality_warnings + list(_editorial_qc.get("warnings") or [])))
                logger.warning(
                    "PREMIUM_OUTPUT_QUALITY task_id=%s clip_order=%d status=%s warnings=%s",
                    task_id,
                    i + 1,
                    clip_info["qc_status"],
                    "|".join([str(x) for x in clip_info["qc_warnings"]]) or "none",
                )
                if not _editorial_qc.get("passed"):
                    logger.warning(
                        "EDITORIAL_QC_NEEDS_REVIEW task_id=%s clip_order=%d reasons=%s",
                        task_id,
                        i + 1,
                        "|".join([str(x) for x in (_editorial_qc.get("reasons") or [])]) or "none",
                    )
                if strict_runtime_qc_enforced and not bool(_publishable_qc.get("strict_publishable")):
                    _strict_reasons = [str(x) for x in (_publishable_qc.get("strict_publishable_reasons") or []) if str(x)]
                    _strict_reason_text = "|".join(_strict_reasons) if _strict_reasons else "strict_publishable_false"
                    logger.warning(
                        "GENERATED_CLIP_REJECTED_BY_STRICT_QC task_id=%s clip_order=%d reasons=%s",
                        task_id,
                        i + 1,
                        _strict_reason_text,
                    )
                    _reject_reason = f"strict_qc_failed:{_strict_reason_text}"
                    rejected_candidate_reasons.append({
                        "clip_index": i + 1,
                        "start_time": segment.get("start_time"),
                        "end_time": segment.get("end_time"),
                        "reason": _reject_reason,
                        "publishable_status": "strict_qc_failed",
                    })
                    clip_failure_details.append(
                        {
                            "clip_index": i + 1,
                            "start_time": segment.get("start_time"),
                            "end_time": segment.get("end_time"),
                            "stage": "strict_qc_failed",
                            "reason": _strict_reason_text[:240],
                        }
                    )
                    strict_qc_rejected_count += 1
                    strict_qc_rejected_reasons.extend(_strict_reasons[:8])
                    logger.info("[clip-count] rejected index=%d reason=%s", i + 1, _reject_reason)
                    continue
                if bool(_publishable_qc.get("editing_zero_detected")):
                    logger.warning(
                        "EDITING_ZERO_DETECTED task_id=%s clip_order=%d reasons=%s",
                        task_id,
                        i + 1,
                        "|".join([str(x) for x in (_publishable_qc.get("strict_publishable_reasons") or [])]) or "unknown",
                    )
                if not bool(_publishable_qc.get("publishable")):
                    if _publishable_qc.get("final_output_is_task_scoped") == "fail":
                        logger.warning(
                            "final_output_not_task_scoped task_id=%s clip_index=%d path=%s",
                            task_id,
                            i + 1,
                            str(clip_info.get("path") or ""),
                        )
                    if _publishable_qc.get("final_output_reused") == "fail":
                        logger.warning(
                            "final_output_reused_from_other_task task_id=%s clip_index=%d path=%s reuse_count=%d",
                            task_id,
                            i + 1,
                            str(clip_info.get("path") or ""),
                            _reused_output_count,
                        )
                    _reject_reason = (
                        "publishable_qc_failed:"
                        f"complete_idea={_publishable_qc.get('complete_idea')},"
                        f"hook_first_3s={_publishable_qc.get('hook_first_3s')},"
                        f"no_mid_sentence_cut={_publishable_qc.get('no_mid_sentence_cut')},"
                        f"subtitles_present={_publishable_qc.get('subtitles_present')},"
                        f"final_output_exists={_publishable_qc.get('final_output_exists')},"
                        f"final_output_is_task_scoped={_publishable_qc.get('final_output_is_task_scoped')},"
                        f"final_output_reused={_publishable_qc.get('final_output_reused')},"
                        f"strict_publishable={_publishable_qc.get('strict_publishable')},"
                        f"editing_zero_detected={_publishable_qc.get('editing_zero_detected')},"
                        f"strict_reasons={'|'.join([str(x) for x in (_publishable_qc.get('strict_publishable_reasons') or [])])}"
                    )
                    if bool(editorial_qc_blocking):
                        rejected_candidate_reasons.append({
                            "clip_index": i + 1,
                            "start_time": segment.get("start_time"),
                            "end_time": segment.get("end_time"),
                            "reason": _reject_reason,
                            "publishable_status": "qc_failed",
                        })
                        clip_failure_details.append(
                            {
                                "clip_index": i + 1,
                                "start_time": segment.get("start_time"),
                                "end_time": segment.get("end_time"),
                                "stage": "publishable_qc_failed",
                                "reason": _reject_reason[:240],
                            }
                        )
                        logger.info("[clip-count] rejected index=%d reason=%s", i + 1, _reject_reason)
                        continue
                    logger.warning(
                        "EDITORIAL_QC_NEEDS_REVIEW_NONBLOCKING task_id=%s clip_order=%d reason=%s",
                        task_id,
                        i + 1,
                        _reject_reason[:240],
                    )
                    clip_info.setdefault("publishable_warnings", []).append(_reject_reason[:180])
                    clip_info["qc_status"] = "needs_review"

                _hook_plan = _as_dict(clip_info.get("hook_plan")) or _as_dict(_as_dict(clip_info.get("editing_plan")).get("hook_plan"))
                _hook_contract_type = "none"
                _hook_reason = "missing_hook"
                if bool(_hook_plan.get("hook_contract_satisfied")) or int(_hook_plan.get("hook_first3_score") or 0) >= 5:
                    _hook_contract_type = "verbal"
                    _hook_reason = "hook_plan_satisfied"
                elif bool((clip_info.get("motion_overlay") or {}).get("motion_overlay_applied")):
                    _hook_contract_type = "overlay_card"
                    _hook_reason = "motion_overlay_support"
                logger.info(
                    "HOOK_CONTRACT_APPLIED task_id=%s clip_index=%d type=%s reason=%s",
                    task_id,
                    i + 1,
                    _hook_contract_type,
                    _hook_reason,
                )
                _music_meta = clip_info.get("music") or {}
                if bool(_music_meta.get("music_applied")):
                    logger.info(
                        "BGM_APPLIED task_id=%s clip_index=%d track=%s final_output=%s",
                        task_id,
                        i + 1,
                        str(_music_meta.get("music_track") or _music_meta.get("bgm_asset_path") or ""),
                        str(clip_info.get("path") or ""),
                    )
                else:
                    logger.info(
                        "BGM_SKIPPED task_id=%s clip_index=%d reason=%s",
                        task_id,
                        i + 1,
                        str(_music_meta.get("music_warning") or _music_meta.get("music_status") or "not_applied"),
                    )
                _sfx_meta_raw = clip_info.get("sfx")
                _sfx_meta = _normalize_sfx_meta(_sfx_meta_raw)
                if not isinstance(_sfx_meta_raw, dict):
                    logger.info(
                        "SFX_META_NORMALIZED task_id=%s clip_index=%d original_type=%s sfx_applied=%s",
                        task_id,
                        i + 1,
                        type(_sfx_meta_raw).__name__,
                        str(bool(_sfx_meta.get("sfx_applied"))).lower(),
                    )
                if bool(_sfx_meta.get("sfx_applied")):
                    logger.info(
                        "SFX_APPLIED task_id=%s clip_index=%d count=%s final_output=%s",
                        task_id,
                        i + 1,
                        str(_sfx_meta.get("sfx_count") or len(_sfx_meta.get("sfx_events") or [])),
                        str(clip_info.get("path") or ""),
                    )
                else:
                    logger.info(
                        "SFX_SKIPPED task_id=%s clip_index=%d reason=%s",
                        task_id,
                        i + 1,
                        str(_sfx_meta.get("sfx_warning") or "not_applied"),
                    )
                _silence_meta = clip_info.get("silence_edit_plan") or {}
                if bool(_silence_meta.get("rendered")):
                    logger.info(
                        "RHYTHM_CLEANUP_APPLIED task_id=%s clip_index=%d trims=%s pauses_kept=%s fillers_removed=%s",
                        task_id,
                        i + 1,
                        str(((_silence_meta.get("summary") or {}).get("total_cuts_applied")) or len(_silence_meta.get("cuts") or [])),
                        str(((_silence_meta.get("summary") or {}).get("tension_silences_preserved")) or 0),
                        str(_silence_meta.get("total_removed_s") or 0.0),
                    )
                else:
                    logger.info(
                        "RHYTHM_CLEANUP_SKIPPED task_id=%s clip_index=%d reason=%s",
                        task_id,
                        i + 1,
                        ",".join(_silence_meta.get("warnings") or _silence_meta.get("apply_warnings") or []) or "not_applied",
                    )
                logger.info(
                    "VISUAL_SUPPORT_APPLIED task_id=%s clip_index=%d type=%s visual_concept=%s final_output=%s",
                    task_id,
                    i + 1,
                    str(_publishable_qc.get("visual_support_status") or "none"),
                    str(segment.get("editorial_type") or ""),
                    str(clip_info.get("path") or ""),
                )
                translated_text = clip_info.get("translated_text")
                saved_clips += 1

                # Update progress for saving phase (91-95%)
                save_progress = 91 + int((saved_clips / max(1, total_clips - len(failed_clips))) * 4)
                await update_progress(save_progress, f"Saving clip {saved_clips}/{total_clips - len(failed_clips)}...")

                # ── VPI editorial metadata ──────────────────────────────
                _vpi_meta = {}
                if segment.get("vpi_score") is not None:
                    _vpi_meta = {
                        "vpi": {
                            "editorial_type": segment.get("editorial_type"),
                            "vpi_score": segment.get("vpi_score"),
                            "matched_patterns": segment.get("matched_patterns", []),
                            "vpi_reason": segment.get("vpi_reason"),
                            "suggested_broll_cue_type": segment.get("suggested_broll_cue_type"),
                            "vpi_editorial_categories": segment.get("vpi_editorial_categories", []),
                            "hookability_score": segment.get("hookability_score"),
                            "hookability_reason": segment.get("hookability_reason"),
                            "commercial_usefulness_score": segment.get("commercial_usefulness_score"),
                            "commercial_usefulness_reason": segment.get("commercial_usefulness_reason"),
                            "standalone_score": segment.get("standalone_score"),
                            "standalone_reason": segment.get("standalone_reason"),
                            "weak_segment_penalties": segment.get("weak_segment_penalties", []),
                            "weak_segment_reason": segment.get("weak_segment_reason"),
                            "segment_selection_confidence": segment.get("segment_selection_confidence"),
                            "selected_for_reason": segment.get("selected_for_reason"),
                            "rejected_for_reason": segment.get("rejected_for_reason"),
                            "weak_editorial_segment": bool(segment.get("weak_editorial_segment")),
                            "clip_brief": segment.get("clip_brief", {}),
                            "clip_angle": segment.get("clip_angle"),
                            "clip_value_proposition": segment.get("clip_value_proposition"),
                            "clip_campaign_fit": segment.get("clip_campaign_fit", {}),
                            "clip_recommended_cta": segment.get("clip_recommended_cta"),
                            "clip_confidence_label": segment.get("clip_confidence_label"),
                            "clip_review_flags": list(segment.get("clip_review_flags") or []),
                            "clip_publish_notes": segment.get("clip_publish_notes"),
                            "campaign_intent": segment.get("campaign_intent"),
                            "campaign_intent_confidence": segment.get("campaign_intent_confidence"),
                            "campaign_intent_source": segment.get("campaign_intent_source"),
                            "campaign_intent_reason": segment.get("campaign_intent_reason"),
                            "preferred_categories": segment.get("preferred_categories", []),
                            "suppressed_categories": segment.get("suppressed_categories", []),
                            "preferred_keywords": segment.get("preferred_keywords", []),
                            "campaign_boost_applied": bool(segment.get("campaign_boost_applied")),
                            "campaign_boost_score": segment.get("campaign_boost_score"),
                            "campaign_alignment_score": segment.get("campaign_alignment_score"),
                            "campaign_alignment_reason": segment.get("campaign_alignment_reason"),
                            "selected_campaign_mix": segment.get("selected_campaign_mix", {}),
                            "campaign_alignment_summary": segment.get("campaign_alignment_summary", {}),
                            "sensitive_handling_required": bool(segment.get("sensitive_handling_required")),
                            "original_start_time": segment.get("original_start_time"),
                            "original_end_time": segment.get("original_end_time"),
                            "refined_start_time": segment.get("refined_start_time"),
                            "refined_end_time": segment.get("refined_end_time"),
                            "boundary_adjustment_applied": bool(segment.get("boundary_adjustment_applied")),
                            "boundary_adjustment_reason": segment.get("boundary_adjustment_reason"),
                            "start_trim_seconds": segment.get("start_trim_seconds"),
                            "start_extend_seconds": segment.get("start_extend_seconds"),
                            "end_extend_seconds": segment.get("end_extend_seconds"),
                            "end_trim_seconds": segment.get("end_trim_seconds"),
                            "payoff_preserved": bool(segment.get("payoff_preserved")),
                            "starts_cleanly": bool(segment.get("starts_cleanly")),
                            "ends_cleanly": bool(segment.get("ends_cleanly")),
                            "first_second_strength": segment.get("first_second_strength"),
                            "first_second_reason": segment.get("first_second_reason"),
                            "boundary_confidence": segment.get("boundary_confidence"),
                            "standalone_after_boundary_score": segment.get("standalone_after_boundary_score"),
                            "standalone_after_boundary_reason": segment.get("standalone_after_boundary_reason"),
                            "start_filler_trimmed": bool(segment.get("start_filler_trimmed")),
                            "start_trim_reason": segment.get("start_trim_reason"),
                            "start_context_extended": bool(segment.get("start_context_extended")),
                            "start_context_reason": segment.get("start_context_reason"),
                            "payoff_extended": bool(segment.get("payoff_extended")),
                            "payoff_extension_reason": segment.get("payoff_extension_reason"),
                            "end_cleaned": bool(segment.get("end_cleaned")),
                            "end_clean_reason": segment.get("end_clean_reason"),
                            "boundary_reverted": bool(segment.get("boundary_reverted")),
                            "boundary_reverted_reason": segment.get("boundary_reverted_reason"),
                            "selected_window_before": segment.get("selected_window_before"),
                            "selected_window_after": segment.get("selected_window_after"),
                            "setup_context_shift_seconds": segment.get("setup_context_shift_seconds"),
                            "trailing_low_value_seconds": segment.get("trailing_low_value_seconds"),
                            "complete_idea_score": segment.get("complete_idea_score"),
                            "incomplete_viral_window_detected": bool(segment.get("incomplete_viral_window_detected")),
                            "viral_window_shifted_back": bool(segment.get("viral_window_shifted_back")),
                            "viral_window_shift_reason": segment.get("viral_window_shift_reason"),
                            "forced_shift_back_applied": bool(segment.get("forced_shift_back_applied")),
                            "selected_alternative_for_complete_idea": bool(segment.get("selected_alternative_for_complete_idea")),
                            "incomplete_window_uncorrectable": bool(segment.get("incomplete_window_uncorrectable")),
                            "hook_lower_third_rendered": bool((segment.get("caption_overlay_pack") or {}).get("lower_third", {}).get("applied") if isinstance(segment.get("caption_overlay_pack"), dict) else False),
                            "ass_hook_overlay_injected": bool((segment.get("caption_overlay_pack") or {}).get("hook_overlay", {}).get("applied") if isinstance(segment.get("caption_overlay_pack"), dict) else False),
                            "non_text_visual_hook_rendered": bool((segment.get("hook_plan") or {}).get("hook_visual_backend") == "non_text_visual_hook" and bool((segment.get("hook_plan") or {}).get("hook_visual_applied"))),
                            "ass_event_count_before": segment.get("ass_event_count_before"),
                            "ass_event_count_final": segment.get("ass_event_count_final"),
                            "ass_event_hard_cap": segment.get("ass_event_hard_cap"),
                            "ass_events_merged_for_daily": bool(segment.get("ass_events_merged_for_daily")),
                            "ass_karaoke_enabled": bool(segment.get("ass_karaoke_enabled")),
                            "ass_approx_simple_mode": bool(segment.get("ass_approx_simple_mode")),
                            "ass_hook_overlay_removed": bool(segment.get("ass_hook_overlay_removed")),
                            "captions_overlap_removed": bool(segment.get("captions_overlap_removed") if segment.get("captions_overlap_removed") is not None else segment.get("text_overlap_prevented")),
                            "selected_clip_package_summary": clip_info.get("selected_clip_package_summary", {}),
                            "package_diversity_score": clip_info.get("package_diversity_score"),
                            "package_diversity_reason": clip_info.get("package_diversity_reason"),
                            "package_category_distribution": clip_info.get("package_category_distribution", {}),
                            "package_theme_distribution": clip_info.get("package_theme_distribution", {}),
                            "package_duration_balance_ok": bool(clip_info.get("package_duration_balance_ok")),
                            "package_duration_warnings": list(clip_info.get("package_duration_warnings") or []),
                            "package_diversity_warnings": list(clip_info.get("package_diversity_warnings") or []),
                            "package_diversity_context": clip_info.get("package_diversity_context") or {},
                            "final_rank_score": segment.get("final_rank_score"),
                            "editorial_score": segment.get("editorial_score"),
                            "virality_score": segment.get("virality_score"),
                        }
                    }
                _daily_meta = {
                    "daily_publishing": {
                        "pre_render_qc": segment.get("pre_render_qc"),
                        "pre_render_approved": bool(segment.get("pre_render_approved")),
                        "pre_render_failure_reasons": list(segment.get("pre_render_failure_reasons") or []),
                        "pre_render_edit_plan": segment.get("pre_render_edit_plan") or {},
                        "editing_plan_required_features": list(segment.get("editing_plan_required_features") or _EDITING_PLAN_REQUIRED_FEATURES),
                        "editing_plan": clip_info.get("editing_plan"),
                        "hook_plan": clip_info.get("hook_plan"),
                        "silence_edit_plan": clip_info.get("silence_edit_plan"),
                        "output_qc": clip_info.get("output_qc"),
                        "publishable_status": clip_info.get("publishable_status"),
                        "publishable_warnings": clip_info.get("publishable_warnings", []),
                        "publishable_score": clip_info.get("publishable_score"),
                        "brand_treatment": clip_info.get("brand_treatment"),
                        "music": clip_info.get("music"),
                        "sfx": clip_info.get("sfx"),
                        "speaker_focus": clip_info.get("speaker_focus"),
                        "editing_richness_score": clip_info.get("editing_richness_score"),
                        "editing_richness_status": clip_info.get("editing_richness_status"),
                        "editing_richness_warnings": clip_info.get("editing_richness_warnings", []),
                        "smart_reframe": clip_info.get("smart_reframe"),
                        "subtitle_intelligence": clip_info.get("subtitle_intelligence"),
                        "final_rendered_contract": clip_info.get("final_rendered_contract"),
                        "technical_qc": clip_info.get("technical_qc"),
                        "editorial_qc": clip_info.get("editorial_qc"),
                        "qc_status": clip_info.get("qc_status"),
                        "qc_reasons": clip_info.get("qc_reasons", []),
                        "qc_warnings": clip_info.get("qc_warnings", []),
                        "metadata_consistency_ok": bool(clip_info.get("metadata_consistency_ok")),
                        "metadata_consistency_errors": list(clip_info.get("metadata_consistency_errors") or []),
                        "metadata_consistency_warnings": list(clip_info.get("metadata_consistency_warnings") or []),
                        "phase_consistency": clip_info.get("phase_consistency") or {},
                        "production_safe_policy": clip_info.get("production_safe_policy") or {},
                        "production_safe_policy_version": str(clip_info.get("production_safe_policy_version") or "a4"),
                        "production_safe_mode_active": bool(clip_info.get("production_safe_mode_active")),
                        "production_safe_external_disabled": bool(clip_info.get("production_safe_external_disabled")),
                        "production_safe_legacy_disabled": bool(clip_info.get("production_safe_legacy_disabled")),
                        "production_safe_routes_allowed": list(clip_info.get("production_safe_routes_allowed") or []),
                        "production_safe_routes_blocked": list(clip_info.get("production_safe_routes_blocked") or []),
                        "vpi_daily_mode_enabled": bool(clip_info.get("vpi_daily_mode_enabled")),
                        "daily_mode_version": str(clip_info.get("daily_mode_version") or "a1"),
                        "daily_mode_policy": clip_info.get("daily_mode_policy") or {},
                        "daily_mode_outputs_enabled": bool(clip_info.get("daily_mode_outputs_enabled")),
                        "daily_mode_conflicts_resolved": list(clip_info.get("daily_mode_conflicts_resolved") or []),
                        "daily_mode_unsafe_override_used": bool(clip_info.get("daily_mode_unsafe_override_used")),
                        "production_safe_compliant": bool(clip_info.get("production_safe_compliant")),
                        "filename_contract_mode": str(clip_info.get("filename_contract_mode") or "legacy_warning_only"),
                        "legacy_routes_quarantined": list(clip_info.get("legacy_routes_quarantined") or []),
                        "experimental_routes_quarantined": list(clip_info.get("experimental_routes_quarantined") or []),
                        "deprecated_routes_present": list(clip_info.get("deprecated_routes_present") or []),
                        "deprecated_routes_used": list(clip_info.get("deprecated_routes_used") or []),
                        "deprecated_routes_blocked": list(clip_info.get("deprecated_routes_blocked") or []),
                        "legacy_route_warning": list(clip_info.get("legacy_route_warning") or []),
                        "premium_flow_manifest_version": str(clip_info.get("premium_flow_manifest_version") or "a1"),
                        "premium_flow_manifest_ok": bool(clip_info.get("premium_flow_manifest_ok")),
                        "premium_flow_manifest_warnings": list(clip_info.get("premium_flow_manifest_warnings") or []),
                        "premium_flow_manifest_errors": list(clip_info.get("premium_flow_manifest_errors") or []),
                        "observed_phase_order": list(clip_info.get("observed_phase_order") or []),
                        "missing_critical_phases": list(clip_info.get("missing_critical_phases") or []),
                        "unexpected_mutators_after_freeze": list(clip_info.get("unexpected_mutators_after_freeze") or []),
                        "premium_flow_manifest": clip_info.get("premium_flow_manifest") or {},
                        "publishable_qc": _publishable_qc,
                        "real_editing_signals": _publishable_qc.get("real_editing_signals", {}),
                        "editing_zero_detected": bool(_publishable_qc.get("editing_zero_detected")),
                        "strict_publishable": bool(_publishable_qc.get("strict_publishable")),
                        "strict_publishable_reasons": list(_publishable_qc.get("strict_publishable_reasons") or []),
                        "cache_policy": {
                            **dict(cache_policy),
                            "final_outputs_reused": False,
                            "editorial_decisions_reused": False,
                            "clip_output_path": str(clip_info.get("path") or ""),
                            "clip_output_task_scoped": bool(_publishable_qc.get("final_output_is_task_scoped") == "pass"),
                        },
                        "motion_overlay_applied": bool((clip_info.get("motion_overlay") or {}).get("motion_overlay_applied")),
                        "final_output_uses_motion_overlay": bool((clip_info.get("motion_overlay") or {}).get("final_output_uses_motion_overlay")),
                        "broll_applied": bool(clip_info.get("editorial_broll")),
                        "visual_support_status": str(_publishable_qc.get("visual_support_status") or "none"),
                    }
                }
                # Merge with existing variants_json (preserve previous content)
                _existing_variants = clip_info.get("variants") or {}
                if isinstance(_existing_variants, str):
                    try:
                        _existing_variants = __import__("json").loads(_existing_variants)
                    except Exception:
                        _existing_variants = {}
                _merged_variants = {**_existing_variants, **_vpi_meta, **_daily_meta}
                _converted_variant_types: Dict[str, int] = {}
                _merged_variants = _normalize_json_compatible(_merged_variants, _converted_variant_types)
                if _converted_variant_types:
                    logger.info(
                        "VARIANTS_JSON_NORMALIZED task_id=%s converted_types=%s",
                        task_id,
                        _converted_variant_types,
                    )
                _variants_json_str = (
                    __import__("json").dumps(_merged_variants)
                    if _merged_variants else None
                )

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
                    variants_json=_variants_json_str,
                )
                await self.db.commit()
                clip_ids.append(clip_id)
                _persisted_qc_status = str(clip_info.get("qc_status") or "ready")
                if _persisted_qc_status not in ("ready", "publishable"):
                    logger.info(
                        "VPI_OUTPUT_RESCUE_REVIEW_CLIP_PERSISTED task_id=%s clip_order=%d clip_id=%s status=%s",
                        task_id, i + 1, clip_id, _persisted_qc_status,
                    )
                try:
                    await self.clip_repo.update_creative_meta(
                        self.db,
                        clip_id,
                        {
                            "qc_status": clip_info.get("qc_status", "ready"),
                            "qc_reasons": list(clip_info.get("qc_reasons") or []),
                            "qc_warnings": list(clip_info.get("qc_warnings") or []),
                            "technical_qc": clip_info.get("technical_qc") or {},
                            "editorial_qc": clip_info.get("editorial_qc") or {},
                        },
                    )
                except Exception as _qc_meta_e:
                    logger.warning(
                        "CLIP_QC_META_PERSIST_FAILED task_id=%s clip_order=%d clip_id=%s error=%s",
                        task_id,
                        i + 1,
                        clip_id,
                        _qc_meta_e,
                    )
                if deadline_safe_mode:
                    logger.info(
                        "DEADLINE_SAFE_INSERT task_id=%s clip_order=%d path=%s",
                        task_id,
                        i + 1,
                        str(clip_info.get("path") or ""),
                    )

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

                # ── VPI output organization ──────────────────────────────
                try:
                    import shutil as _vpi_shutil
                    import json as _vpi_json
                    from datetime import datetime as _vpi_dt
                    _vpi_date = _vpi_dt.now().strftime("%Y-%m-%d")
                    _vpi_task_short = task_id.replace("-", "")[:12]
                    _vpi_dir = Path(f"/app/outputs/vpi/{_vpi_date}/task_{_vpi_task_short}")
                    _vpi_dir.mkdir(parents=True, exist_ok=True)
                    _clip_idx = i + 1
                    _vpi_clip_name = f"clip_{_clip_idx:02d}.mp4"
                    _vpi_src = Path(clip_info["path"])
                    _vpi_dst = None
                    if _vpi_src.exists():
                        _vpi_dst = _vpi_dir / _vpi_clip_name
                        _vpi_shutil.copy2(_vpi_src, _vpi_dst)
                        logger.info(f"[output-vpi] copied final clip to {_vpi_dst}")
                    _vpi_ass_dst = None
                    _caption_ass_raw = clip_info.get("caption_ass_debug_path")
                    _caption_ass_src = Path(str(_caption_ass_raw)) if _caption_ass_raw else None
                    if _caption_ass_src is not None and _caption_ass_src.exists():
                        _vpi_ass_dst = _vpi_dir / f"clip_{_clip_idx:02d}_captions.ass"
                        _vpi_shutil.copy2(_caption_ass_src, _vpi_ass_dst)
                        logger.info(f"[output-vpi] copied captions ass to {_vpi_ass_dst}")
                    _broll_info = clip_info.get("editorial_broll") or []
                    # Metadata
                    _vpi_meta = {
                        "task_id": task_id,
                        "task_run_id": task_run_id,
                        "source_url": url,
                        "clip_index": _clip_idx,
                        "output_path": str(_vpi_src),
                        "organized_output_path": str(_vpi_dst) if _vpi_dst else None,
                        "caption_ass_debug_path": str(_caption_ass_src) if _caption_ass_src and _caption_ass_src.exists() else None,
                        "organized_captions_ass_path": str(_vpi_ass_dst) if _vpi_ass_dst else None,
                        "clip_start": clip_info.get("start_time", ""),
                        "clip_end": clip_info.get("end_time", ""),
                        "duration": clip_info.get("duration", 0),
                        "virality_score": clip_info.get("virality_score", 0),
                        "editorial_type": clip_info.get("editorial_type"),
                        "matched_patterns": clip_info.get("matched_patterns", []),
                        "vpi_score": clip_info.get("vpi_score"),
                        "vpi_reason": clip_info.get("vpi_reason"),
                        "vpi_editorial_categories": clip_info.get("vpi_editorial_categories", []),
                        "hookability_score": clip_info.get("hookability_score"),
                        "hookability_reason": clip_info.get("hookability_reason"),
                        "commercial_usefulness_score": clip_info.get("commercial_usefulness_score"),
                        "commercial_usefulness_reason": clip_info.get("commercial_usefulness_reason"),
                        "standalone_score": clip_info.get("standalone_score"),
                        "standalone_reason": clip_info.get("standalone_reason"),
                        "weak_segment_penalties": clip_info.get("weak_segment_penalties", []),
                        "weak_segment_reason": clip_info.get("weak_segment_reason"),
                        "segment_selection_confidence": clip_info.get("segment_selection_confidence"),
                        "selected_for_reason": clip_info.get("selected_for_reason"),
                        "rejected_for_reason": clip_info.get("rejected_for_reason"),
                        "weak_editorial_segment": bool(clip_info.get("weak_editorial_segment")),
                        "clip_brief": clip_info.get("clip_brief", {}),
                        "clip_angle": clip_info.get("clip_angle"),
                        "clip_value_proposition": clip_info.get("clip_value_proposition"),
                        "clip_campaign_fit": clip_info.get("clip_campaign_fit", {}),
                        "clip_recommended_cta": clip_info.get("clip_recommended_cta"),
                        "clip_confidence_label": clip_info.get("clip_confidence_label"),
                        "clip_review_flags": list(clip_info.get("clip_review_flags") or []),
                        "clip_publish_notes": clip_info.get("clip_publish_notes"),
                        "campaign_intent": clip_info.get("campaign_intent"),
                        "campaign_intent_confidence": clip_info.get("campaign_intent_confidence"),
                        "campaign_intent_source": clip_info.get("campaign_intent_source"),
                        "campaign_intent_reason": clip_info.get("campaign_intent_reason"),
                        "preferred_categories": clip_info.get("preferred_categories", []),
                        "suppressed_categories": clip_info.get("suppressed_categories", []),
                        "preferred_keywords": clip_info.get("preferred_keywords", []),
                        "campaign_boost_applied": bool(clip_info.get("campaign_boost_applied")),
                        "campaign_boost_score": clip_info.get("campaign_boost_score"),
                        "campaign_alignment_score": clip_info.get("campaign_alignment_score"),
                        "campaign_alignment_reason": clip_info.get("campaign_alignment_reason"),
                        "selected_campaign_mix": clip_info.get("selected_campaign_mix", {}),
                        "campaign_alignment_summary": clip_info.get("campaign_alignment_summary", {}),
                        "sensitive_handling_required": bool(clip_info.get("sensitive_handling_required")),
                        "original_start_time": clip_info.get("original_start_time"),
                        "original_end_time": clip_info.get("original_end_time"),
                        "refined_start_time": clip_info.get("refined_start_time"),
                        "refined_end_time": clip_info.get("refined_end_time"),
                        "boundary_adjustment_applied": bool(clip_info.get("boundary_adjustment_applied")),
                        "boundary_adjustment_reason": clip_info.get("boundary_adjustment_reason"),
                        "start_trim_seconds": clip_info.get("start_trim_seconds"),
                        "start_extend_seconds": clip_info.get("start_extend_seconds"),
                        "end_extend_seconds": clip_info.get("end_extend_seconds"),
                        "end_trim_seconds": clip_info.get("end_trim_seconds"),
                        "payoff_preserved": bool(clip_info.get("payoff_preserved")),
                        "starts_cleanly": bool(clip_info.get("starts_cleanly")),
                        "ends_cleanly": bool(clip_info.get("ends_cleanly")),
                        "first_second_strength": clip_info.get("first_second_strength"),
                        "first_second_reason": clip_info.get("first_second_reason"),
                        "boundary_confidence": clip_info.get("boundary_confidence"),
                        "standalone_after_boundary_score": clip_info.get("standalone_after_boundary_score"),
                        "standalone_after_boundary_reason": clip_info.get("standalone_after_boundary_reason"),
                        "start_filler_trimmed": bool(clip_info.get("start_filler_trimmed")),
                        "start_trim_reason": clip_info.get("start_trim_reason"),
                        "start_context_extended": bool(clip_info.get("start_context_extended")),
                        "start_context_reason": clip_info.get("start_context_reason"),
                        "payoff_extended": bool(clip_info.get("payoff_extended")),
                        "payoff_extension_reason": clip_info.get("payoff_extension_reason"),
                        "end_cleaned": bool(clip_info.get("end_cleaned")),
                        "end_clean_reason": clip_info.get("end_clean_reason"),
                        "boundary_reverted": bool(clip_info.get("boundary_reverted")),
                        "boundary_reverted_reason": clip_info.get("boundary_reverted_reason"),
                        "selected_window_before": clip_info.get("selected_window_before"),
                        "selected_window_after": clip_info.get("selected_window_after"),
                        "setup_context_shift_seconds": clip_info.get("setup_context_shift_seconds"),
                        "trailing_low_value_seconds": clip_info.get("trailing_low_value_seconds"),
                        "complete_idea_score": clip_info.get("complete_idea_score"),
                        "incomplete_viral_window_detected": bool(clip_info.get("incomplete_viral_window_detected")),
                        "viral_window_shifted_back": bool(clip_info.get("viral_window_shifted_back")),
                        "viral_window_shift_reason": clip_info.get("viral_window_shift_reason"),
                        "forced_shift_back_applied": bool(clip_info.get("forced_shift_back_applied")),
                        "selected_alternative_for_complete_idea": bool(clip_info.get("selected_alternative_for_complete_idea")),
                        "incomplete_window_uncorrectable": bool(clip_info.get("incomplete_window_uncorrectable")),
                        "hook_lower_third_rendered": bool((clip_info.get("caption_overlay_pack") or {}).get("lower_third", {}).get("applied") if isinstance(clip_info.get("caption_overlay_pack"), dict) else False),
                        "ass_hook_overlay_injected": bool((clip_info.get("caption_overlay_pack") or {}).get("hook_overlay", {}).get("applied") if isinstance(clip_info.get("caption_overlay_pack"), dict) else False),
                        "non_text_visual_hook_rendered": bool((clip_info.get("hook_plan") or {}).get("hook_visual_backend") == "non_text_visual_hook" and bool((clip_info.get("hook_plan") or {}).get("hook_visual_applied"))),
                        "ass_event_count_before": clip_info.get("ass_event_count_before"),
                        "ass_event_count_final": clip_info.get("ass_event_count_final"),
                        "ass_event_hard_cap": clip_info.get("ass_event_hard_cap"),
                        "ass_events_merged_for_daily": bool(clip_info.get("ass_events_merged_for_daily")),
                        "ass_karaoke_enabled": bool(clip_info.get("ass_karaoke_enabled")),
                        "ass_approx_simple_mode": bool(clip_info.get("ass_approx_simple_mode")),
                        "ass_hook_overlay_removed": bool(clip_info.get("ass_hook_overlay_removed")),
                        "captions_overlap_removed": bool(clip_info.get("captions_overlap_removed") if clip_info.get("captions_overlap_removed") is not None else clip_info.get("text_overlap_prevented")),
                        "selected_clip_package_summary": clip_info.get("selected_clip_package_summary", {}),
                        "package_diversity_score": clip_info.get("package_diversity_score"),
                        "package_diversity_reason": clip_info.get("package_diversity_reason"),
                        "package_category_distribution": clip_info.get("package_category_distribution", {}),
                        "package_theme_distribution": clip_info.get("package_theme_distribution", {}),
                        "package_duration_balance_ok": bool(clip_info.get("package_duration_balance_ok")),
                        "package_duration_warnings": list(clip_info.get("package_duration_warnings") or []),
                        "package_diversity_warnings": list(clip_info.get("package_diversity_warnings") or []),
                        "package_diversity_context": clip_info.get("package_diversity_context") or {},
                        "suggested_broll_cue_type": clip_info.get("suggested_broll_cue_type"),
                        "caption_source": "cached_words" if clip_info.get("words") else "fallback",
                        "broll": _broll_info,
                        "editing_plan": clip_info.get("editing_plan"),
                        "hook_plan": clip_info.get("hook_plan"),
                        "silence_edit_plan": clip_info.get("silence_edit_plan"),
                        "output_qc": clip_info.get("output_qc"),
                        "publishable_status": clip_info.get("publishable_status"),
                        "publishable_warnings": clip_info.get("publishable_warnings", []),
                        "publishable_score": clip_info.get("publishable_score"),
                        "brand_treatment": clip_info.get("brand_treatment"),
                        "music": clip_info.get("music"),
                        "sfx": clip_info.get("sfx"),
                        "speaker_focus": clip_info.get("speaker_focus"),
                        "editing_richness_score": clip_info.get("editing_richness_score"),
                        "editing_richness_status": clip_info.get("editing_richness_status"),
                        "editing_richness_warnings": clip_info.get("editing_richness_warnings", []),
                        "smart_reframe": clip_info.get("smart_reframe"),
                        "subtitle_intelligence": clip_info.get("subtitle_intelligence"),
                        "cache_policy": {
                            **dict(cache_policy),
                            "final_outputs_reused": False,
                            "editorial_decisions_reused": False,
                        },
                        "created_at": _vpi_dt.now().isoformat(),
                    }
                    _vpi_meta_path = _vpi_dir / f"clip_{_clip_idx:02d}_metadata.json"
                    _vpi_meta = _normalize_json_for_context(task_id, "output_vpi", _vpi_meta)
                    with open(_vpi_meta_path, "w") as _vpi_f:
                        _vpi_json.dump(_vpi_meta, _vpi_f, indent=2, ensure_ascii=False)
                    logger.info(f"[output-vpi] wrote metadata to {_vpi_meta_path}")
                    # Transcript
                    _vpi_text = clip_info.get("text", "")
                    if _vpi_text:
                        _vpi_txt_path = _vpi_dir / f"clip_{_clip_idx:02d}_transcript.txt"
                        with open(_vpi_txt_path, "w") as _vpi_f:
                            _vpi_f.write(_vpi_text)
                    # Source info
                    _vpi_src_info = {
                        "task_id": task_id,
                        "source_url": url,
                        "source_title": getattr(self, "_source_title", ""),
                        "created_at": _vpi_dt.now().isoformat(),
                    }
                    _vpi_src_path = _vpi_dir / "source_info.json"
                    _vpi_src_info = _normalize_json_for_context(task_id, "output_vpi", _vpi_src_info)
                    with open(_vpi_src_path, "w") as _vpi_f:
                        _vpi_json.dump(_vpi_src_info, _vpi_f, indent=2, ensure_ascii=False)
                except Exception as _vpi_e:
                    logger.warning(f"[output-vpi] copy failed: {_vpi_e}")

                # ── Task summary report ──────────────────────────────────
                try:
                    import json as _ts_json
                    from datetime import datetime as _ts_dt
                    _ts_data = {
                        "task_id": task_id,
                        "task_run_id": task_run_id,
                        "source_url": url,
                        "source_title": getattr(self, "_source_title", ""),
                        "status": "completed",
                        "clips_generated": len(clip_ids),
                        "beta_clean": self.config.beta_clean,
                        "enable_editorial_broll": self.config.enable_editorial_broll,
                        "whisper_device": "cpu",
                        "flags": {
                            "VIRACLIP_BETA_CLEAN": os.getenv("VIRACLIP_BETA_CLEAN"),
                            "VIRACLIP_ENABLE_EDITORIAL_BROLL": os.getenv("VIRACLIP_ENABLE_EDITORIAL_BROLL"),
                            "VIRACLIP_ENABLE_LOCAL_BROLL_BANK": os.getenv("VIRACLIP_ENABLE_LOCAL_BROLL_BANK"),
                            "WHISPER_DEVICE": os.getenv("WHISPER_DEVICE"),
                            "VIRACLIP_ENABLE_TORCH_CUDA": os.getenv("VIRACLIP_ENABLE_TORCH_CUDA"),
                            "VIRACLIP_ENABLE_NVENC": os.getenv("VIRACLIP_ENABLE_NVENC"),
                            "BROLL_FORCE_CPU": os.getenv("BROLL_FORCE_CPU"),
                            "T2V_ENABLED": os.getenv("T2V_ENABLED"),
                            "COMFYUI_ENABLED": os.getenv("COMFYUI_ENABLED"),
                        },
                        "resolved_flags": {
                            "VIRACLIP_BETA_CLEAN": self.config.beta_clean,
                            "VIRACLIP_ENABLE_EDITORIAL_BROLL": self.config.enable_editorial_broll,
                            "VIRACLIP_ENABLE_LOCAL_BROLL_BANK": getattr(self.config, "enable_local_broll_bank", True),
                            "WHISPER_DEVICE": os.getenv("WHISPER_DEVICE", "cpu"),
                            "VIRACLIP_ENABLE_TORCH_CUDA": getattr(self.config, "enable_torch_cuda", False),
                            "VIRACLIP_ENABLE_NVENC": getattr(self.config, "enable_nvenc", False),
                            "BROLL_FORCE_CPU": os.getenv("BROLL_FORCE_CPU"),
                            "T2V_ENABLED": os.getenv("T2V_ENABLED"),
                            "COMFYUI_ENABLED": os.getenv("COMFYUI_ENABLED"),
                        },
                        "output_paths": [],
                        "created_at": _ts_dt.now().isoformat(),
                        "clips": [],
                        "warnings": [],
                        "cache_policy": {
                            **dict(cache_policy),
                            "final_outputs_reused": False,
                            "editorial_decisions_reused": False,
                        },
                    }
                    for _ci_idx, (_ri, _ci, _elapsed) in enumerate(render_results):
                        if _ci is None:
                            _seg = segments_to_render[_ri] if _ri < len(segments_to_render) else {}
                            _ts_data["warnings"].append(
                                f"Clip {_ri+1} failed to render "
                                f"({_seg.get('start_time','?')} → {_seg.get('end_time','?')})"
                            )
                            continue
                        _organized_clip_path = _vpi_dir / f"clip_{_ri + 1:02d}.mp4"
                        _organized_ass_path = _vpi_dir / f"clip_{_ri + 1:02d}_captions.ass"
                        _ts_clip = {
                            "clip_index": _ri + 1,
                            "filename": _ci.get("filename", ""),
                            "output_path": _ci.get("path", ""),
                            "organized_output_path": str(_organized_clip_path) if _organized_clip_path.exists() else None,
                            "caption_ass_debug_path": _ci.get("caption_ass_debug_path"),
                            "organized_captions_ass_path": str(_organized_ass_path) if _organized_ass_path.exists() else None,
                            "start_time": _ci.get("start_time", ""),
                            "end_time": _ci.get("end_time", ""),
                            "duration": _ci.get("duration", 0),
                            "virality_score": _ci.get("virality_score", 0),
                            "editorial_type": _ci.get("editorial_type"),
                            "matched_patterns": _ci.get("matched_patterns", []),
                            "vpi_score": _ci.get("vpi_score"),
                            "vpi_reason": _ci.get("vpi_reason"),
                            "suggested_broll_cue_type": _ci.get("suggested_broll_cue_type"),
                            "clip_health": _ci.get("clip_health", {}),
                            "caption_source": "cached_words" if _ci.get("words") else "fallback",
                            "broll": _ci.get("editorial_broll") or [],
                            "editing_plan": _ci.get("editing_plan"),
                            "hook_plan": _ci.get("hook_plan"),
                            "silence_edit_plan": _ci.get("silence_edit_plan"),
                            "output_qc": _ci.get("output_qc"),
                            "publishable_status": _ci.get("publishable_status"),
                            "publishable_warnings": _ci.get("publishable_warnings", []),
                            "publishable_score": _ci.get("publishable_score"),
                            "brand_treatment": _ci.get("brand_treatment"),
                            "music": _ci.get("music"),
                            "sfx": _ci.get("sfx"),
                            "speaker_focus": _ci.get("speaker_focus"),
                            "editing_richness_score": _ci.get("editing_richness_score"),
                            "editing_richness_status": _ci.get("editing_richness_status"),
                            "editing_richness_warnings": _ci.get("editing_richness_warnings", []),
                            "smart_reframe": _ci.get("smart_reframe"),
                            "subtitle_intelligence": _ci.get("subtitle_intelligence"),
                            "transcript_snippet": (_ci.get("text", "") or "")[:120],
                        }
                        _ts_clip["output_paths"] = [
                            p for p in [
                                _ts_clip["output_path"],
                                _ts_clip["organized_output_path"],
                                _ts_clip["caption_ass_debug_path"],
                                _ts_clip["organized_captions_ass_path"],
                            ]
                            if p
                        ]
                        _ts_data["output_paths"].extend(_ts_clip["output_paths"])
                        _ts_data["clips"].append(_ts_clip)
                        logger.info(
                            "[task-summary] vpi editorial_type=%s vpi_score=%s",
                            _ts_clip.get("editorial_type"),
                            _ts_clip.get("vpi_score"),
                        )
                        logger.info("[task-summary] caption_source=%s", _ts_clip["caption_source"])
                        for _broll_item in _ts_clip["broll"]:
                            logger.info(
                                "[task-summary] broll cue_type=%s asset=%s source=%s",
                                _broll_item.get("cue_type"),
                                _broll_item.get("asset_path"),
                                _broll_item.get("asset_source"),
                            )
                    # Write JSON
                    _ts_json_path = _vpi_dir / "task_summary.json"
                    _ts_data = _normalize_json_for_context(task_id, "task_summary", _ts_data)
                    with open(_ts_json_path, "w") as _ts_f:
                        _ts_json.dump(_ts_data, _ts_f, indent=2, ensure_ascii=False)
                    # Write Markdown
                    _ts_md_lines = [
                        f"# Task Summary: `{task_id[:12]}...`",
                        "",
                        f"**Status:** completed",
                        f"**Source:** [{url}]({url})",
                        f"**Clips generated:** {len(clip_ids)}",
                        f"**Beta Clean:** {self.config.beta_clean}",
                        f"**Editorial B-roll:** {self.config.enable_editorial_broll}",
                        f"**Whisper:** cpu",
                        f"**Created:** {_ts_dt.now().isoformat()}",
                        "",
                        "## Clips",
                        "",
                    ]
                    for _ts_clip in _ts_data["clips"]:
                        _ts_md_lines.extend([
                            f"### Clip {_ts_clip['clip_index']}: `{_ts_clip['filename']}`",
                            f"",
                            f"- **Segment:** {_ts_clip['start_time']} → {_ts_clip['end_time']} ({_ts_clip['duration']}s)",
                            f"- **Virality score:** {_ts_clip['virality_score']}",
                            f"- **VPI editorial type:** `{_ts_clip.get('editorial_type')}`",
                            f"- **VPI score:** `{_ts_clip.get('vpi_score')}`",
                            f"- **VPI patterns:** `{', '.join(_ts_clip.get('matched_patterns') or [])}`",
                            f"- **VPI reason:** {_ts_clip.get('vpi_reason')}",
                            f"- **Publishable:** `{_ts_clip.get('publishable_status')}` score=`{_ts_clip.get('publishable_score')}`",
                            f"- **Publishable warnings:** `{', '.join(_ts_clip.get('publishable_warnings') or [])}`",
                            f"- **Editing richness:** `{_ts_clip.get('editing_richness_status')}` score=`{_ts_clip.get('editing_richness_score')}`",
                            f"- **Editing plan:** hook=`{(_ts_clip.get('editing_plan') or {}).get('hook_strategy')}` reframe=`{(_ts_clip.get('editing_plan') or {}).get('reframe_strategy')}` broll=`{(_ts_clip.get('editing_plan') or {}).get('broll_strategy')}`",
                            f"- **Hook plan:** type=`{(_ts_clip.get('hook_plan') or {}).get('hook_type')}` headline=`{(_ts_clip.get('hook_plan') or {}).get('headline_text')}` rendered=`{(_ts_clip.get('hook_plan') or {}).get('rendered')}`",
                            f"- **Silence edit:** mode=`{(_ts_clip.get('silence_edit_plan') or {}).get('mode')}` cuts=`{((_ts_clip.get('silence_edit_plan') or {}).get('summary') or {}).get('total_cuts_applied')}` removed=`{(_ts_clip.get('silence_edit_plan') or {}).get('total_removed_s')}`",
                            f"- **Caption source:** {_ts_clip['caption_source']}",
                            f"- **Output path:** `{_ts_clip['output_path']}`",
                            f"- **Organized output:** `{_ts_clip['organized_output_path']}`",
                            f"- **Caption ASS debug:** `{_ts_clip['caption_ass_debug_path']}`",
                            f"- **Organized captions ASS:** `{_ts_clip['organized_captions_ass_path']}`",
                            f"- **Transcript:** {_ts_clip['transcript_snippet']}...",
                            f"",
                        ])
                        if _ts_clip["broll"]:
                            for _ts_broll in _ts_clip["broll"]:
                                _ts_md_lines.extend([
                                    f"- **B-roll cue:** `{_ts_broll.get('cue_type')}`",
                                    f"- **B-roll source:** `{_ts_broll.get('asset_source')}`",
                                    f"- **B-roll asset:** `{_ts_broll.get('asset_path')}`",
                                    f"- **B-roll query:** `{_ts_broll.get('visual_query')}`",
                                    f"- **B-roll duration:** `{_ts_broll.get('effective_duration')}`",
                                    "",
                                ])
                        else:
                            _ts_md_lines.extend([
                                "- **B-roll cue:** `none`",
                                "- **B-roll source:** `none`",
                                "- **B-roll asset:** `none`",
                                "",
                            ])
                    if _ts_data["warnings"]:
                        _ts_md_lines.extend(["## Warnings", ""])
                        for _ts_w in _ts_data["warnings"]:
                            _ts_md_lines.append(f"- ⚠️ {_ts_w}")
                        _ts_md_lines.append("")
                    _ts_md_path = _vpi_dir / "task_summary.md"
                    with open(_ts_md_path, "w") as _ts_f:
                        _ts_f.write("\n".join(_ts_md_lines))
                    logger.info(f"[task-summary] wrote {_ts_json_path}")
                    logger.info(f"[task-summary] wrote {_ts_md_path}")
                except Exception as _ts_e:
                    logger.warning(f"[task-summary] write failed: {_ts_e}")

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

            delivery_contract = build_delivery_contract(
                requested=num_clips,
                delivered=saved_clips,
                rejected_reasons=rejected_candidate_reasons,
            )
            stage_timings["task_summary"] = delivery_contract
            stage_timings["requested_num_clips"] = num_clips
            stage_timings["delivered_num_clips"] = saved_clips
            stage_timings["rejected_candidate_reasons"] = rejected_candidate_reasons
            if saved_clips < num_clips:
                logger.info(
                    "[clip-count] delivered_less_than_requested requested=%d delivered=%d reason=%s",
                    num_clips,
                    saved_clips,
                    delivery_contract.get("shortage_reason") or "unknown",
                )
            logger.info(
                "[clip-count] requested=%d candidates=%d selected=%d rendered=%d exported=%d",
                num_clips,
                len(segments_to_render),
                len(segments_to_render),
                successful_renders,
                saved_clips,
            )

            # ── Single bulk update of task.clip_ids after all clips complete ──
            if clip_ids:
                await self.task_repo.update_task_clips(self.db, task_id, clip_ids)

            # ── VPI Publishable Gate v3.1: rank clips after render ──
            try:
                ranked_clips = rank_clips(render_results)
                logger.info(
                    "[publishable-gate] ranked %d clips — best_candidate=%s",
                    len(ranked_clips),
                    next((c.get("best_candidate") for c in ranked_clips if c.get("best_candidate")), None),
                )
            except Exception as _rank_e:
                logger.warning("[publishable-gate] ranking failed: %s", _rank_e)

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

            logger.info(
                "VPI_OUTPUT_MANAGEMENT_STARTED task_id=%s output_root=%s",
                task_id,
                output_root,
            )
            clip_outputs_for_manifest: List[Dict[str, Any]] = []
            rehydrated_clip_briefs: List[Dict[str, Any]] = list(clip_briefs or [])
            output_management_warnings: List[str] = []
            publishable_clip_count = 0
            review_clip_count = 0
            high_confidence_output_count = 0
            for _ri, _rinfo, _relapsed in render_results:
                if not isinstance(_rinfo, dict):
                    continue
                # H12.3: rehydrate the H4-empirical-metadata source variables locally
                # and safely — they were referenced (undefined) at the
                # final_contract_rebuild / manifest_persistence merge points below,
                # producing "name '_caption_overlay_pack_metadata' is not defined".
                _h4_contract_ref = _as_dict(_rinfo.get("final_mp4_contract") or _rinfo.get("final_rendered_contract"))
                _caption_overlay_pack_metadata = (
                    _as_dict(_rinfo.get("caption_overlay_pack_metadata"))
                    or _as_dict(_rinfo.get("caption_overlay_pack"))
                    or _as_dict(_h4_contract_ref.get("caption_overlay_pack_metadata"))
                    or _as_dict(_h4_contract_ref.get("caption_overlay_pack"))
                )
                if _caption_overlay_pack_metadata:
                    _rinfo["caption_overlay_metadata_missing"] = False
                    logger.info(
                        "VPI_CAPTION_OVERLAY_METADATA_REHYDRATED task_id=%s clip_order=%d keys=%d",
                        task_id,
                        _ri + 1,
                        len(_caption_overlay_pack_metadata),
                    )
                else:
                    _caption_overlay_pack_metadata = {}
                    _rinfo["caption_overlay_metadata_missing"] = True
                    logger.info(
                        "VPI_CAPTION_OVERLAY_METADATA_SAFE_DEFAULTED task_id=%s clip_order=%d reason=no_caption_overlay_pack_metadata_available",
                        task_id,
                        _ri + 1,
                    )
                _motion_overlay_metadata = _as_dict(_rinfo.get("motion_overlay")) or _as_dict(_h4_contract_ref.get("motion_overlay"))
                _broll_editorial_decision_final = _as_dict(_rinfo.get("broll_editorial_decision")) or _as_dict(_h4_contract_ref.get("broll_editorial_decision"))
                _boundary_refinement_metadata = _as_dict(_rinfo.get("boundary_refinement_metadata")) or _as_dict(_h4_contract_ref.get("boundary_refinement_metadata"))
                _music_metadata = _as_dict(_rinfo.get("music")) or _as_dict(_h4_contract_ref.get("music"))
                logger.info(
                    "VPI_H4_EMPIRICAL_METADATA_SAFE_INPUTS task_id=%s clip_order=%d caption_overlay=%d motion_overlay=%d broll_decision=%d boundary_refinement=%d music=%d",
                    task_id,
                    _ri + 1,
                    len(_caption_overlay_pack_metadata),
                    len(_motion_overlay_metadata),
                    len(_broll_editorial_decision_final),
                    len(_boundary_refinement_metadata),
                    len(_music_metadata),
                )
                _source_output_path = Path(str(_rinfo.get("path") or ""))
                _safe_filename = str(_rinfo.get("filename") or _source_output_path.name or f"clip_{_ri + 1:02d}.mp4")
                _managed_output_path = output_clips_dir / _safe_filename
                _output_copy_ok = False
                if _source_output_path.exists():
                    try:
                        shutil.copy2(_source_output_path, _managed_output_path)
                        _output_copy_ok = True
                    except Exception as _copy_e:
                        _warning = f"clip_{_ri + 1}_copy_failed:{_copy_e}"
                        output_management_warnings.append(_warning)
                        logger.warning("VPI_OUTPUT_MANIFEST_WARNING task_id=%s clip_order=%d reason=%s", task_id, _ri + 1, _copy_e)
                else:
                    _warning = f"clip_{_ri + 1}_source_missing"
                    output_management_warnings.append(_warning)
                    logger.warning("VPI_OUTPUT_MANIFEST_WARNING task_id=%s clip_order=%d reason=source_missing", task_id, _ri + 1)
                _durable_output_path = _managed_output_path if _managed_output_path.exists() else _source_output_path
                # H13.17: prefer task-scoped managed path as truth source so
                # vpi_publishable_gate can apply qc_gap_only suppression.
                _final_truth_path = (
                    _managed_output_path if _managed_output_path.exists()
                    else (_source_output_path if _source_output_path.exists() else _durable_output_path)
                )
                if _managed_output_path.exists() and _source_output_path.exists():
                    logger.info(
                        "VPI_PUBLISHABLE_QC_STRICT_TASK_SCOPE_BYPASSED_FOR_VERIFIED_OUTPUT task_id=%s clip_order=%d path=%s",
                        task_id, _ri + 1, str(_managed_output_path),
                    )
                elif not _managed_output_path.exists():
                    logger.info(
                        "VPI_PUBLISHABLE_QC_STRICT_TASK_SCOPE_STILL_BLOCKING task_id=%s clip_order=%d reason=managed_path_missing source_exists=%s",
                        task_id, _ri + 1, str(_source_output_path.exists()).lower(),
                    )
                _final_truth_relation = "unknown"
                if _source_output_path.exists() and _managed_output_path.exists():
                    try:
                        _final_truth_relation = "byte_identical" if _hash_file_sha256(_source_output_path) == _hash_file_sha256(_managed_output_path) else "distinct_valid_artifacts"
                    except Exception:
                        _final_truth_relation = "unknown"
                elif _source_output_path.exists() or _managed_output_path.exists():
                    _final_truth_relation = "single_valid_artifact"
                _final_output_truth_pre = _build_final_output_truth(
                    task_id=task_id,
                    task_scoped_output_path=_source_output_path,
                    durable_output_path=_managed_output_path,
                    final_mp4_contract=dict(_rinfo.get("final_mp4_contract") or _rinfo.get("final_rendered_contract") or {}),
                    selected_final_output_path=_final_truth_path,
                )
                _final_output_truth_pre["final_output_entity_relation"] = _final_truth_relation
                _final_output_truth_pre["final_output_path"] = str(_final_truth_path)
                _final_output_truth_pre["final_output_path_container"] = str(_source_output_path)
                _final_output_truth_pre["final_output_path_durable"] = str(_managed_output_path if _managed_output_path.exists() else "")
                logger.info(
                    "VPI_FINAL_OUTPUT_TRUTH_BUILT task_id=%s clip_order=%d path=%s durable=%s relation=%s verified=%s probe_ok=%s",
                    task_id,
                    _ri + 1,
                    str(_final_output_truth_pre.get("final_output_path") or ""),
                    str(_final_output_truth_pre.get("final_output_path_durable") or ""),
                    str(_final_output_truth_pre.get("final_output_entity_relation") or "unknown"),
                    str(bool(_final_output_truth_pre.get("final_output_verified"))).lower(),
                    str(bool(_final_output_truth_pre.get("final_probe_ok"))).lower(),
                )
                _rinfo["organized_output_path"] = str(_final_truth_path)
                _rinfo["output_root"] = str(output_root)
                _rinfo["clips_output_dir"] = str(output_clips_dir)
                _rinfo["manifest_output_path"] = str(output_manifest_path)
                _rinfo["summary_output_path"] = str(output_summary_path)
                _rinfo["output_filename_strategy"] = str(_rinfo.get("output_filename_strategy") or output_management_payload["output_filename_strategy"])
                _rinfo["output_filename_safe"] = bool(_rinfo.get("output_filename_safe", True))
                _rinfo["output_filename_collision_resolved"] = bool(_rinfo.get("output_filename_collision_resolved"))
                _rinfo["output_management_warnings"] = list(output_management_warnings)
                _rinfo["output_management_ok"] = bool(_output_copy_ok)
                _rinfo["durable_output_path"] = str(_managed_output_path if _managed_output_path.exists() else "")
                _final_output_path = _final_truth_path
                _rinfo["path"] = str(_final_output_path)
                _rinfo["final_output_path"] = str(_final_output_path)
                _rinfo["final_output_path_container"] = str(_source_output_path)
                _rinfo["final_output_path_host_or_relative"] = str(_final_output_truth_pre.get("final_output_path_host_or_relative") or "")
                _rinfo["final_output_path_relative"] = str(_final_output_truth_pre.get("final_output_path_relative") or "")
                _rinfo["final_output_path_durable"] = str(_managed_output_path if _managed_output_path.exists() else "")
                _rinfo["final_output_path_locked"] = str(_final_output_path)
                _rinfo["final_output_path_locked_at_stage"] = "post_output_management"
                _rebuild_clip_info = dict(_rinfo)
                # H12.9 telescope cut: _rinfo may already carry a final_mp4_contract/
                # final_rendered_contract from a prior pass that itself embeds
                # final_output_truth (which embeds a snapshot of that same contract).
                # Carrying it forward wholesale into clip_info compounds the nesting
                # depth on every pass (H12.8 RecursionError root cause). Substitute a
                # lightweight ref for the nested truth/contract instead.
                for _carried_key in ("final_mp4_contract", "final_rendered_contract"):
                    _carried_contract = _rebuild_clip_info.get(_carried_key)
                    if isinstance(_carried_contract, dict) and isinstance(_carried_contract.get("final_output_truth"), dict):
                        _trimmed_carried = dict(_carried_contract)
                        _trimmed_carried["final_output_truth"] = _lightweight_final_contract_ref(
                            _as_dict(_carried_contract.get("final_output_truth")).get("final_mp4_contract")
                            or _carried_contract.get("final_output_truth")
                        )
                        _trimmed_carried["final_contract_embedded_as"] = "lightweight_ref"
                        _rebuild_clip_info[_carried_key] = _trimmed_carried
                        logger.info(
                            "VPI_FINAL_CONTRACT_TELESCOPE_CUT task_id=%s clip_order=%d site=rebuild_clip_info_carry_forward field=%s",
                            task_id,
                            _ri + 1,
                            _carried_key,
                        )
                _rebuild_clip_info.update({
                    "path": str(_final_output_path),
                    "durable_output_path": str(_final_output_path),
                    "organized_output_path": str(_final_output_path),
                    "final_output_truth": dict(_final_output_truth_pre),
                    "output_root": str(output_root),
                    "clips_output_dir": str(output_clips_dir),
                    "manifest_output_path": str(output_manifest_path),
                    "summary_output_path": str(output_summary_path),
                    "output_filename_strategy": str(_rinfo.get("output_filename_strategy") or output_management_payload["output_filename_strategy"]),
                    "output_filename_safe": bool(_rinfo.get("output_filename_safe", True)),
                    "output_filename_collision_resolved": bool(_rinfo.get("output_filename_collision_resolved")),
                    "output_management_ok": bool(_output_copy_ok),
                    "output_management_warnings": list(output_management_warnings),
                })
                try:
                    from .vpi_publishable_gate import build_final_mp4_contract as _build_final_mp4_contract

                    _final_contract = _build_final_mp4_contract(
                        final_output_path=_final_output_path,
                        expected_duration_s=float(_rinfo.get("duration") or 0.0),
                        clip_info=_rebuild_clip_info,
                        final_qc_report=_as_dict(_rinfo.get("final_qc")),
                        production_safe=bool(os.environ.get("VPI_PRODUCTION_SAFE_EDIT", "").strip().lower() in {"1", "true", "yes", "on"}),
                        captions_metadata=_as_dict(_rinfo.get("caption_visual_support")) or _as_dict(_rinfo.get("caption_visual_support_plan")) or _as_dict(_rinfo.get("subtitle_intelligence")),
                        bgm_metadata=_as_dict(_rinfo.get("music")),
                        sfx_metadata=_as_dict(_rinfo.get("sfx")),
                        hook_metadata=_as_dict(_rinfo.get("hook_plan")) or _as_dict(_as_dict(_rinfo.get("editing_plan")).get("hook_plan")),
                        rhythm_metadata=_as_dict(_rinfo.get("silence_edit_plan")),
                        visual_layer_budget_metadata=_as_dict(_as_dict(_rinfo.get("editing_plan")).get("visual_layer_budget")),
                        visual_reinforcement_metadata=_as_dict(_rinfo.get("visual_reinforcement")),
                        broll_metadata={
                            "items": _as_list(_rinfo.get("broll_items") or _rinfo.get("editorial_broll")),
                            "broll_editorial_decision": _as_dict(_rinfo.get("broll_editorial_decision")),
                            "broll_applied": bool(_rinfo.get("broll_applied")),
                            "broll_rendered": bool(_rinfo.get("broll_rendered")),
                            "broll_verified": bool(_rinfo.get("broll_verified")),
                            "broll_skip_reason": str(_rinfo.get("broll_skip_reason") or ""),
                            "broll_budget_allowed": bool(_rinfo.get("broll_budget_allowed", True)),
                            "broll_asset_id": str(_rinfo.get("broll_asset_id") or ""),
                            "broll_asset_source": str(_rinfo.get("broll_asset_source") or ""),
                        },
                        transitions_metadata=_as_dict(_rinfo.get("transitions")),
                        audio_mastering_metadata=_as_dict(_rinfo.get("audio_qc")) or _as_dict(_rinfo.get("music")),
                        task_id=task_id,
                        clip_order=_ri + 1,
                    )
                except Exception as _rebuild_e:
                    logger.warning(
                        "VPI_POST_RENDER_FINALIZATION_EXCEPTION task_id=%s clip_order=%d stage=final_contract_rebuild error=%s",
                        task_id,
                        _ri + 1,
                        _rebuild_e,
                    )
                    logger.warning(
                        "FINAL_MP4_CONTRACT_REBUILD_FAILED task_id=%s clip_order=%d error=%s",
                        task_id,
                        _ri + 1,
                        _rebuild_e,
                    )
                    _prior_final_contract_for_fallback = _rinfo.get("final_mp4_contract") or _rinfo.get("final_rendered_contract") or {}
                    _final_contract = dict(_prior_final_contract_for_fallback) if isinstance(_prior_final_contract_for_fallback, dict) else {}
                    # H12.9 telescope cut: this fallback re-wraps the ENTIRE prior
                    # contract (H12.8 finding). If it already embeds final_output_truth,
                    # replace that nested structure with a lightweight ref so the
                    # rebuilt contract does not compound the telescoping depth further.
                    if isinstance(_final_contract.get("final_output_truth"), dict):
                        _prior_truth_for_fallback = _final_contract.get("final_output_truth")
                        _final_contract["final_output_truth"] = _lightweight_final_contract_ref(
                            _as_dict(_prior_truth_for_fallback).get("final_mp4_contract") or _prior_truth_for_fallback
                        )
                        _final_contract["final_contract_embedded_as"] = "lightweight_ref"
                        logger.info(
                            "VPI_FINAL_CONTRACT_TELESCOPE_CUT task_id=%s clip_order=%d site=exception_fallback_rewrap",
                            task_id,
                            _ri + 1,
                        )
                _final_contract.update({
                    "output_root": str(output_root),
                    "clips_output_dir": str(output_clips_dir),
                    "output_manifest_path": str(output_manifest_path),
                    "output_summary_path": str(output_summary_path),
                    "output_filename_strategy": str(_rinfo.get("output_filename_strategy") or output_management_payload["output_filename_strategy"]),
                    "output_filename_safe": bool(_rinfo.get("output_filename_safe", True)),
                    "output_filename_collision_resolved": bool(_rinfo.get("output_filename_collision_resolved")),
                    "output_management_ok": bool(_output_copy_ok),
                    "output_management_warnings": list(output_management_warnings),
                    "output_clip_count": 0,
                    "publishable_clip_count": 0,
                    "review_clip_count": 0,
                    "final_output_path": str(_final_output_path),
                    "final_output_path_locked": str(_final_output_path),
                    "final_output_path_locked_at_stage": "post_output_management",
                    "final_output_is_task_scoped": bool(_final_output_path.exists() and _is_task_scoped_output(_final_output_path, task_id)),
                    "final_output_not_latest_stage": False if _final_output_path.exists() and _is_task_scoped_output(_final_output_path, task_id) else bool(_final_contract.get("final_output_not_latest_stage")),
                    "final_truth_source": "task_scoped_output" if _final_output_path.exists() and _is_task_scoped_output(_final_output_path, task_id) else str(_final_contract.get("final_truth_source") or "final_mp4_contract"),
                })
                if isinstance(_rinfo.get("stage_recorder"), dict):
                    _final_contract["stage_recorder"] = dict(_rinfo.get("stage_recorder") or {})
                _rinfo["final_mp4_contract"] = _final_contract
                _rinfo["final_rendered_contract"] = _final_contract
                _rinfo["final_truth_source"] = str(_final_contract.get("final_truth_source") or "final_mp4_contract")
                _rinfo["final_output_verified"] = bool(_final_contract.get("final_output_verified"))
                _rinfo["final_publishable"] = bool(_final_contract.get("final_publishable"))
                _rinfo["final_needs_review"] = bool(_final_contract.get("final_needs_review"))
                _rinfo["final_contract_ok"] = bool(_final_contract.get("final_publishable"))
                _rinfo["final_blocking_reasons"] = list(_final_contract.get("final_blocking_reasons") or [])
                _rinfo["final_warning_reasons"] = list(_final_contract.get("final_warning_reasons") or [])
                _rinfo["metadata_consistency_ok"] = bool(_final_contract.get("metadata_consistency_ok"))
                _rinfo["metadata_consistency_errors"] = list(_final_contract.get("metadata_consistency_errors") or [])
                _rinfo["metadata_consistency_warnings"] = list(_final_contract.get("metadata_consistency_warnings") or [])
                _rinfo["final_probe_ok"] = bool(_final_contract.get("final_probe_ok"))
                _rinfo["final_output_is_task_scoped"] = bool(_final_contract.get("final_output_is_task_scoped"))
                _rinfo["final_output_not_latest_stage"] = bool(_final_contract.get("final_output_not_latest_stage"))
                logger.info(
                    "VPI_FINAL_CONTRACT_PERSISTED task_id=%s clip_order=%d verified=%s publishable=%s path=%s",
                    task_id,
                    _ri + 1,
                    str(bool(_final_contract.get("final_output_verified"))).lower(),
                    str(bool(_final_contract.get("final_publishable"))).lower(),
                    str(_final_output_path),
                )
                logger.info(
                    "VPI_H8_5_METADATA_PERSISTED task_id=%s clip_order=%d ass_events=%d hard_cap=%d forced_shift=%s incomplete_uncorrectable=%s",
                    task_id,
                    _ri + 1,
                    int(_final_contract.get("ass_event_count_final") or 0),
                    int(_final_contract.get("ass_event_hard_cap") or 22),
                    str(bool(_final_contract.get("forced_shift_back_applied"))).lower(),
                    str(bool(_final_contract.get("incomplete_window_uncorrectable"))).lower(),
                )
                try:
                    _publishable_context = _resolve_publishable_context(_rinfo)
                    _publishable_status = str(_publishable_context.get("status") or "")
                    _publishable_metadata = _as_dict(_publishable_context.get("metadata"))
                    _publishable_warnings = _as_list(_publishable_context.get("warnings"))
                    _publishable_blocking = _as_list(_publishable_context.get("blocking"))
                    logger.info(
                        "VPI_PUBLISHABLE_METADATA_SAFE_DEFAULTED task_id=%s clip_order=%d status=%s warnings=%d blocking=%d",
                        task_id,
                        _ri + 1,
                        _publishable_status or "unknown",
                        len(_publishable_warnings),
                        len(_publishable_blocking),
                    )
                    _h4_empirical_metadata = _collect_h4_empirical_metadata(
                        _rinfo,
                        _final_contract,
                        _publishable_metadata,
                        _caption_overlay_pack_metadata,
                        _motion_overlay_metadata,
                        _broll_editorial_decision_final,
                        _boundary_refinement_metadata,
                        _music_metadata,
                    )
                except Exception as _publishable_metadata_e:
                    logger.warning(
                        "VPI_PUBLISHABLE_METADATA_NONFATAL task_id=%s clip_order=%d stage=final_contract_rebuild error=%s",
                        task_id,
                        _ri + 1,
                        _publishable_metadata_e,
                    )
                    _h4_empirical_metadata = {}
                _rinfo.update(_h4_empirical_metadata)
                _final_contract.update(_h4_empirical_metadata)
                logger.info(
                    "VPI_FINAL_CONTRACT_POST_RENDER_MERGE_APPLIED task_id=%s clip_order=%d path=%s boundary_confidence=%s final_output_verified=%s",
                    task_id,
                    _ri + 1,
                    str(_final_contract.get("final_output_path") or _rinfo.get("final_output_path") or ""),
                    str(_final_contract.get("boundary_confidence") if _final_contract.get("boundary_confidence") is not None else _rinfo.get("boundary_confidence")),
                    str(bool(_final_contract.get("final_output_verified"))).lower(),
                )
                _final_output_truth = _build_final_output_truth(
                    task_id=task_id,
                    task_scoped_output_path=_source_output_path,
                    durable_output_path=_managed_output_path,
                    final_mp4_contract=_final_contract,
                    selected_final_output_path=_final_output_path,
                )
                _final_output_truth["final_output_entity_relation"] = _final_truth_relation
                _final_output_truth["final_output_path"] = str(_final_output_path)
                _final_output_truth["final_output_path_container"] = str(_source_output_path)
                _final_output_truth["final_output_path_durable"] = str(_managed_output_path if _managed_output_path.exists() else "")
                _final_output_truth["final_output_verified"] = bool(_final_contract.get("final_output_verified"))
                _final_output_truth["final_probe_ok"] = bool(_final_contract.get("final_probe_ok"))
                _final_output_truth["final_video_stream_ok"] = bool(_final_contract.get("final_video_stream_ok"))
                _final_output_truth["final_audio_stream_ok"] = bool(_final_contract.get("final_audio_stream_ok"))
                _final_output_truth["final_duration"] = float(_final_contract.get("final_duration") or 0.0)
                _final_output_truth["final_file_size"] = int(_final_contract.get("final_file_size") or 0)
                logger.info(
                    "VPI_FINAL_OUTPUT_PATH_NORMALIZED task_id=%s clip_order=%d container=%s host_or_relative=%s relative=%s",
                    task_id,
                    _ri + 1,
                    str(_final_output_truth.get("final_output_path_container") or ""),
                    str(_final_output_truth.get("final_output_path_host_or_relative") or ""),
                    str(_final_output_truth.get("final_output_path_relative") or ""),
                )
                logger.info(
                    "VPI_FINAL_OUTPUT_ENTITY_RELATION_DETECTED task_id=%s clip_order=%d relation=%s task_scoped=%s durable=%s",
                    task_id,
                    _ri + 1,
                    str(_final_output_truth.get("final_output_entity_relation") or "unknown"),
                    str(_source_output_path),
                    str(_managed_output_path),
                )
                # H12.9 telescope cut: _final_output_truth["final_mp4_contract"] is a
                # dict(_final_contract) snapshot (see _build_final_output_truth). If
                # _final_contract already carried a final_output_truth forward (e.g.
                # via the exception-fallback rewrap above), that snapshot would embed
                # it too — compounding depth on the very next pass. Cut it here.
                _truth_to_embed = dict(_final_output_truth)
                _embedded_contract_in_truth = _truth_to_embed.get("final_mp4_contract")
                if isinstance(_embedded_contract_in_truth, dict) and isinstance(_embedded_contract_in_truth.get("final_output_truth"), dict):
                    _truth_to_embed["final_mp4_contract"] = _lightweight_final_contract_ref(_embedded_contract_in_truth)
                    _truth_to_embed["final_contract_embedded_as"] = "lightweight_ref"
                    logger.info(
                        "VPI_FINAL_OUTPUT_TRUTH_LIGHTWEIGHT_CONTRACT_REF task_id=%s clip_order=%d",
                        task_id,
                        _ri + 1,
                    )
                _rinfo["final_output_truth"] = dict(_truth_to_embed)
                _final_contract["final_output_truth"] = dict(_truth_to_embed)
                _rinfo["final_output_path"] = str(_final_output_truth.get("final_output_path") or _final_output_path)
                _rinfo["final_output_verified"] = bool(_final_output_truth.get("final_output_verified"))
                _rinfo["final_publishable"] = bool(_final_contract.get("final_publishable"))
                _rinfo["final_needs_review"] = bool(_final_contract.get("final_needs_review"))
                logger.info(
                    "VPI_FINAL_CONTRACT_PRESERVED_MEASURED_FIELD task_id=%s clip_order=%d field=boundary_confidence value=%s",
                    task_id,
                    _ri + 1,
                    str(_final_contract.get("boundary_confidence") if _final_contract.get("boundary_confidence") is not None else _rinfo.get("boundary_confidence")),
                )
                _rehydrated_clip_brief = _rehydrate_clip_brief_from_final_contract(
                    rehydrated_clip_briefs[_ri] if _ri < len(rehydrated_clip_briefs) and isinstance(rehydrated_clip_briefs[_ri], dict) else {},
                    _rinfo,
                    _final_contract,
                )
                if _ri < len(rehydrated_clip_briefs):
                    rehydrated_clip_briefs[_ri] = _rehydrated_clip_brief
                else:
                    rehydrated_clip_briefs.append(_rehydrated_clip_brief)
                _rinfo["clip_brief"] = dict(_rehydrated_clip_brief)
                _final_contract["clip_brief"] = dict(_rehydrated_clip_brief)
                logger.info(
                    "VPI_CLIP_BRIEF_REHYDRATED_FROM_FINAL_CONTRACT task_id=%s clip_order=%d boundary_confidence=%s complete_idea_score=%s incomplete_viral_window_detected=%s",
                    task_id,
                    _ri + 1,
                    str(_rehydrated_clip_brief.get("boundary_confidence") if _rehydrated_clip_brief.get("boundary_confidence") is not None else ""),
                    str(_rehydrated_clip_brief.get("complete_idea_score") if _rehydrated_clip_brief.get("complete_idea_score") is not None else ""),
                    str(_rehydrated_clip_brief.get("incomplete_viral_window_detected") if _rehydrated_clip_brief.get("incomplete_viral_window_detected") is not None else ""),
                )
                logger.info(
                    "VPI_CLIP_BRIEF_BOUNDARY_CONFIDENCE_PRESERVED task_id=%s clip_order=%d boundary_confidence=%s",
                    task_id,
                    _ri + 1,
                    str(_rehydrated_clip_brief.get("boundary_confidence") if _rehydrated_clip_brief.get("boundary_confidence") is not None else ""),
                )
                for _h4_key in (
                    "text_overlap_prevented",
                    "suppressed_text_layers",
                    "text_layer_count_final",
                    "caption_priority_enforced",
                    "caption_timebase_corrected",
                    "caption_timebase_source",
                    "caption_sync_warning",
                    "pip_overlay_disabled",
                    "thumbnail_overlay_disabled",
                    "debug_preview_overlay_disabled",
                    "debug_face_box_rendered",
                    "debug_overlays_disabled",
                    "broll_relevance_gate_passed",
                    "broll_relevance_score",
                    "broll_skipped_unrelated",
                    "bgm_volume_empirical_boost_applied",
                    "bgm_target_volume_final",
                    "bts_tail_detected",
                    "bts_tail_trimmed_seconds",
                    "viral_window_shifted_back",
                    "viral_window_shift_reason",
                    "daily_mode_external_route_active",
                    "daily_mode_external_route_names",
                    "daily_mode_external_source_allowed",
                    "non_production_safe_route_used",
                    "stage_recorder",
                    "hook_lower_third_rendered",
                    "ass_hook_overlay_injected",
                    "non_text_visual_hook_rendered",
                    "ass_event_count_before",
                    "ass_event_count_final",
                    "ass_event_hard_cap",
                    "ass_events_merged_for_daily",
                    "ass_karaoke_enabled",
                    "ass_approx_simple_mode",
                    "ass_hook_overlay_removed",
                    "captions_overlap_removed",
                    "selected_window_before",
                    "selected_window_after",
                    "complete_idea_score",
                    "incomplete_viral_window_detected",
                    "setup_context_shift_seconds",
                    "trailing_low_value_seconds",
                    "viral_window_shifted_back",
                    "viral_window_shift_reason",
                    "forced_shift_back_applied",
                    "selected_alternative_for_complete_idea",
                    "incomplete_window_uncorrectable",
                    "final_output_uses_motion_overlay",
                ):
                    _rinfo[_h4_key] = _final_contract.get(_h4_key)
                clip_outputs_for_manifest.append(_rinfo)
                if bool(_rinfo.get("final_publishable")):
                    publishable_clip_count += 1
                if bool(_rinfo.get("final_needs_review")):
                    review_clip_count += 1
                if str(_rinfo.get("clip_confidence_label") or "") == "high":
                    high_confidence_output_count += 1

            output_management_payload["output_clip_count"] = len(clip_outputs_for_manifest)
            output_management_payload["publishable_clip_count"] = publishable_clip_count
            output_management_payload["review_clip_count"] = review_clip_count
            output_management_payload["high_confidence_clip_count"] = high_confidence_output_count
            output_management_payload["output_management_warnings"] = list(dict.fromkeys(output_management_warnings))

            manifest_written = False
            summary_written = False
            review_bundle_written = False
            manifest_warning: List[str] = []
            manifest_payload: Dict[str, Any] = {}
            if clip_outputs_for_manifest:
                try:
                    manifest_payload = _build_vpi_output_manifest(
                        task_id=task_id,
                        clip_outputs=clip_outputs_for_manifest,
                        final_mp4_contract=dict(clip_outputs_for_manifest[0].get("final_mp4_contract") or {}),
                        clip_brief=dict(rehydrated_clip_briefs[0] or {}) if rehydrated_clip_briefs else {},
                        campaign_metadata={
                            "campaign_intent": campaign_intent,
                            "campaign_intent_confidence": campaign_intent_confidence,
                            "campaign_intent_source": campaign_intent_source,
                            "campaign_intent_reason": campaign_intent_reason,
                            "selected_campaign_mix": selected_campaign_mix,
                            "campaign_alignment_summary": campaign_alignment_summary,
                            "preferred_categories": preferred_categories,
                            "suppressed_categories": suppressed_categories,
                            "preferred_keywords": preferred_keywords,
                            "campaign_alignment_score": campaign_alignment_score,
                            "campaign_alignment_reason": campaign_alignment_reason,
                            "sensitive_handling_required": sensitive_handling_required,
                        },
                        package_diversity_metadata={
                            "package_diversity_score": package_diversity_score,
                            "package_diversity_reason": package_diversity_reason,
                            "package_category_distribution": package_category_distribution,
                            "package_theme_distribution": package_theme_distribution,
                            "package_duration_balance_ok": package_duration_balance_ok,
                            "package_duration_warnings": package_diversity_warnings,
                            "selected_clip_package_summary": package_diversity_summary,
                            "high_confidence_clip_count": high_confidence_output_count,
                            "review_clip_count": review_clip_count,
                            "campaign_intent": campaign_intent,
                            "campaign_intent_confidence": campaign_intent_confidence,
                            "campaign_intent_source": campaign_intent_source,
                            "campaign_intent_reason": campaign_intent_reason,
                            "selected_campaign_mix": selected_campaign_mix,
                            "campaign_alignment_summary": campaign_alignment_summary,
                            "sensitive_handling_required": sensitive_handling_required,
                        },
                        audio_visual_qc_summary={
                            "audio_chain_ok_count": sum(1 for _clip in clip_outputs_for_manifest if bool(_clip.get("final_audio_chain_ok"))),
                            "visual_identity_ok_count": sum(1 for _clip in clip_outputs_for_manifest if bool(_clip.get("visual_identity_ok"))),
                            "cta_verified_count": sum(1 for _clip in clip_outputs_for_manifest if bool(_clip.get("cta_verified"))),
                            "output_management_warnings": list(output_management_warnings),
                        },
                        output_paths=dict(output_management_payload),
                    )
                    logger.info(
                        "VPI_OUTPUT_MANIFEST_BUILT task_id=%s clips=%d path=%s",
                        task_id,
                        len(manifest_payload.get("clips") or []),
                        output_manifest_path,
                    )
                    if manifest_payload.get("warnings_summary", {}).get("warning_count"):
                        logger.warning(
                            "VPI_OUTPUT_MANIFEST_WARNING task_id=%s warnings=%s",
                            task_id,
                            manifest_payload.get("warnings_summary", {}),
                        )
                    with open(output_manifest_path, "w", encoding="utf-8") as _manifest_f:
                        json.dump(manifest_payload, _manifest_f, indent=2, ensure_ascii=False)
                    manifest_written = True
                    logger.info("VPI_OUTPUT_MANIFEST_WRITTEN task_id=%s path=%s", task_id, output_manifest_path)
                except Exception as _manifest_e:
                    manifest_warning.append(f"manifest_write_failed:{_manifest_e}")
                    output_management_warnings.append(f"manifest_write_failed:{_manifest_e}")
                    logger.warning("VPI_MANIFEST_PERSIST_WARNING_NONFATAL task_id=%s path=%s error=%s", task_id, output_manifest_path, _manifest_e)
                    logger.warning("VPI_OUTPUT_MANIFEST_WARNING task_id=%s reason=%s", task_id, _manifest_e)

                try:
                    summary_payload = manifest_payload or _build_vpi_output_manifest(
                        task_id=task_id,
                        clip_outputs=clip_outputs_for_manifest,
                        final_mp4_contract=dict(clip_outputs_for_manifest[0].get("final_mp4_contract") or {}) if clip_outputs_for_manifest else {},
                        clip_brief=dict(rehydrated_clip_briefs[0] or {}) if rehydrated_clip_briefs else {},
                        campaign_metadata={
                            "campaign_intent": campaign_intent,
                            "campaign_intent_confidence": campaign_intent_confidence,
                            "campaign_intent_source": campaign_intent_source,
                            "campaign_intent_reason": campaign_intent_reason,
                            "selected_campaign_mix": selected_campaign_mix,
                            "campaign_alignment_summary": campaign_alignment_summary,
                            "preferred_categories": preferred_categories,
                            "suppressed_categories": suppressed_categories,
                            "preferred_keywords": preferred_keywords,
                            "campaign_alignment_score": campaign_alignment_score,
                            "campaign_alignment_reason": campaign_alignment_reason,
                            "sensitive_handling_required": sensitive_handling_required,
                        },
                        package_diversity_metadata={
                            "package_diversity_score": package_diversity_score,
                            "package_diversity_reason": package_diversity_reason,
                            "package_category_distribution": package_category_distribution,
                            "package_theme_distribution": package_theme_distribution,
                            "package_duration_balance_ok": package_duration_balance_ok,
                            "package_duration_warnings": package_diversity_warnings,
                            "selected_clip_package_summary": package_diversity_summary,
                            "high_confidence_clip_count": high_confidence_output_count,
                            "review_clip_count": review_clip_count,
                            "campaign_intent": campaign_intent,
                            "campaign_intent_confidence": campaign_intent_confidence,
                            "campaign_intent_source": campaign_intent_source,
                            "campaign_intent_reason": campaign_intent_reason,
                            "selected_campaign_mix": selected_campaign_mix,
                            "campaign_alignment_summary": campaign_alignment_summary,
                            "sensitive_handling_required": sensitive_handling_required,
                        },
                        audio_visual_qc_summary={
                            "audio_chain_ok_count": sum(1 for _clip in clip_outputs_for_manifest if bool(_clip.get("final_audio_chain_ok"))),
                            "visual_identity_ok_count": sum(1 for _clip in clip_outputs_for_manifest if bool(_clip.get("visual_identity_ok"))),
                            "cta_verified_count": sum(1 for _clip in clip_outputs_for_manifest if bool(_clip.get("cta_verified"))),
                            "output_management_warnings": list(output_management_warnings),
                        },
                        output_paths=dict(output_management_payload),
                    )
                    # H12.9: summary_payload reuses manifest_payload (or rebuilds via
                    # the same build_vpi_output_manifest), which — after the H12.9
                    # lightweight-projection + hardened-_json_safe fixes — no longer
                    # walks the telescoped final_mp4_contract wholesale. Log that the
                    # payload feeding the summary writer is the flat, JSON-safe one.
                    logger.info(
                        "VPI_SUMMARY_PAYLOAD_JSON_SAFE task_id=%s source=%s",
                        task_id,
                        "manifest_payload_reuse" if manifest_payload else "rebuilt_via_build_vpi_output_manifest",
                    )
                    summary_md = _render_vpi_output_summary_markdown(summary_payload)
                    with open(output_summary_path, "w", encoding="utf-8") as _summary_f:
                        _summary_f.write(summary_md)
                    summary_written = True
                    logger.info("VPI_OUTPUT_SUMMARY_WRITTEN task_id=%s path=%s", task_id, output_summary_path)
                except Exception as _summary_e:
                    output_management_warnings.append(f"summary_write_failed:{_summary_e}")
                    logger.warning("VPI_OUTPUT_MANIFEST_WARNING task_id=%s reason=summary_failed error=%s", task_id, _summary_e)

                try:
                    logger.info(
                        "VPI_REVIEW_BUNDLE_STARTED task_id=%s dir=%s",
                        task_id,
                        str(output_review_dir),
                    )
                    review_bundle_payload = _build_vpi_local_review_bundle(
                        output_manifest=manifest_payload or {},
                        task_id=task_id,
                        clips=clip_outputs_for_manifest,
                        clip_briefs=list(rehydrated_clip_briefs or []),
                        final_contracts=[
                            dict(_clip.get("final_mp4_contract") or _clip.get("final_rendered_contract") or {})
                            for _clip in clip_outputs_for_manifest
                        ],
                        output_paths=dict(output_management_payload),
                    )
                    review_bundle_written = bool(review_bundle_payload.get("review_ready"))
                    output_management_payload["review_bundle_dir"] = str(review_bundle_payload.get("review_bundle_dir") or output_review_dir)
                    output_management_payload["review_index_path"] = str(review_bundle_payload.get("review_index_path") or review_index_path)
                    output_management_payload["review_json_path"] = str(review_bundle_payload.get("review_json_path") or review_bundle_json_path)
                    output_management_payload["review_bundle_ready"] = bool(review_bundle_payload.get("review_ready"))
                    output_management_payload["review_bundle_warnings"] = list(review_bundle_payload.get("review_warnings") or [])
                    logger.info(
                        "VPI_REVIEW_BUNDLE_PERSISTED task_id=%s ready=%s index=%s json=%s",
                        task_id,
                        str(bool(output_management_payload["review_bundle_ready"])).lower(),
                        str(output_management_payload["review_index_path"]),
                        str(output_management_payload["review_json_path"]),
                    )
                    if output_management_payload["review_bundle_warnings"]:
                        logger.warning(
                            "VPI_REVIEW_BUNDLE_WARNING task_id=%s warnings=%s",
                            task_id,
                            output_management_payload["review_bundle_warnings"],
                        )
                except Exception as _review_e:
                    review_bundle_written = False
                    output_management_payload["review_bundle_ready"] = False
                    output_management_payload["review_bundle_warnings"] = list(dict.fromkeys(list(output_management_payload.get("review_bundle_warnings") or []) + [f"review_bundle_failed:{_review_e}"]))
                    output_management_warnings.append(f"review_bundle_failed:{_review_e}")
                    logger.warning("VPI_REVIEW_BUNDLE_WARNING task_id=%s reason=%s", task_id, _review_e)

                if not manifest_written:
                    review_clip_count = len(clip_outputs_for_manifest)
                output_management_payload["review_clip_count"] = review_clip_count
                output_management_payload["output_management_ok"] = bool(manifest_written)
                output_management_payload["output_management_warnings"] = list(dict.fromkeys(output_management_warnings + manifest_warning))
                stage_timings["output_management"] = dict(output_management_payload)
                for _ri, _rinfo, _relapsed in render_results:
                    if not isinstance(_rinfo, dict):
                        continue
                    _contract = dict(_rinfo.get("final_mp4_contract") or _rinfo.get("final_rendered_contract") or {})
                    _contract.update({
                        "output_root": str(output_root),
                        "clips_output_dir": str(output_clips_dir),
                        "output_manifest_path": str(output_manifest_path),
                        "output_summary_path": str(output_summary_path),
                        "review_bundle_dir": str(output_management_payload.get("review_bundle_dir") or ""),
                        "review_index_path": str(output_management_payload.get("review_index_path") or ""),
                        "review_bundle_json_path": str(output_management_payload.get("review_json_path") or ""),
                        "review_bundle_ready": bool(output_management_payload.get("review_bundle_ready", False)),
                        "review_bundle_warnings": list(output_management_payload.get("review_bundle_warnings") or []),
                        "output_filename_strategy": str(_rinfo.get("output_filename_strategy") or output_management_payload["output_filename_strategy"]),
                        "output_filename_safe": bool(_rinfo.get("output_filename_safe", True)),
                        "output_filename_collision_resolved": bool(_rinfo.get("output_filename_collision_resolved")),
                        "output_management_ok": bool(manifest_written),
                        "output_management_warnings": list(output_management_payload["output_management_warnings"]),
                        "output_clip_count": int(output_management_payload["output_clip_count"]),
                        "publishable_clip_count": int(output_management_payload["publishable_clip_count"]),
                        "review_clip_count": int(output_management_payload["review_clip_count"]),
                    })
                    if not manifest_written:
                        _contract["final_needs_review"] = True
                        _contract["final_warning_reasons"] = list(dict.fromkeys(list(_contract.get("final_warning_reasons") or []) + ["output_manifest_write_failed"]))
                        _rinfo["final_needs_review"] = True
                        _rinfo["final_warning_reasons"] = list(dict.fromkeys(list(_rinfo.get("final_warning_reasons") or []) + ["output_manifest_write_failed"]))
                    if not bool(output_management_payload.get("review_bundle_ready", False)):
                        _contract["final_warning_reasons"] = list(dict.fromkeys(list(_contract.get("final_warning_reasons") or []) + ["review_bundle_write_failed"]))
                        _rinfo["final_warning_reasons"] = list(dict.fromkeys(list(_rinfo.get("final_warning_reasons") or []) + ["review_bundle_write_failed"]))
                    _rinfo["final_mp4_contract"] = _contract
                    _rinfo["final_rendered_contract"] = _contract
                    _rinfo["output_management_ok"] = bool(manifest_written)
                    _rinfo["output_management_warnings"] = list(output_management_payload["output_management_warnings"])
                    try:
                        _publishable_context = _resolve_publishable_context(_rinfo)
                        _publishable_status = str(_publishable_context.get("status") or "")
                        _publishable_metadata = _as_dict(_publishable_context.get("metadata"))
                        _publishable_warnings = _as_list(_publishable_context.get("warnings"))
                        _publishable_blocking = _as_list(_publishable_context.get("blocking"))
                        logger.info(
                            "VPI_PUBLISHABLE_METADATA_SAFE_DEFAULTED task_id=%s clip_order=%d status=%s warnings=%d blocking=%d",
                            task_id,
                            _ri + 1,
                            _publishable_status or "unknown",
                            len(_publishable_warnings),
                            len(_publishable_blocking),
                        )
                        _h4_empirical_metadata = _collect_h4_empirical_metadata(
                            _rinfo,
                            _contract,
                            output_management_payload,
                            _publishable_metadata,
                            _caption_overlay_pack_metadata,
                            _motion_overlay_metadata,
                            _broll_editorial_decision_final,
                            _boundary_refinement_metadata,
                            _music_metadata,
                        )
                    except Exception as _publishable_metadata_e:
                        logger.warning(
                            "VPI_PUBLISHABLE_METADATA_NONFATAL task_id=%s clip_order=%d stage=manifest_persistence error=%s",
                            task_id,
                            _ri + 1,
                            _publishable_metadata_e,
                        )
                        _h4_empirical_metadata = {}
                    _rinfo.update(_h4_empirical_metadata)
                    _contract.update(_h4_empirical_metadata)
                    for _h4_key in (
                        "text_overlap_prevented",
                        "suppressed_text_layers",
                        "text_layer_count_final",
                        "caption_priority_enforced",
                        "caption_timebase_corrected",
                        "caption_timebase_source",
                        "caption_sync_warning",
                        "pip_overlay_disabled",
                        "thumbnail_overlay_disabled",
                        "debug_preview_overlay_disabled",
                        "debug_face_box_rendered",
                        "debug_overlays_disabled",
                        "broll_relevance_gate_passed",
                        "broll_relevance_score",
                        "broll_skipped_unrelated",
                        "bgm_volume_empirical_boost_applied",
                        "bgm_target_volume_final",
                        "bts_tail_detected",
                        "bts_tail_trimmed_seconds",
                        "viral_window_shifted_back",
                        "viral_window_shift_reason",
                        "daily_mode_external_route_active",
                        "daily_mode_external_route_names",
                        "daily_mode_external_source_allowed",
                        "non_production_safe_route_used",
                        "stage_recorder",
                        "hook_lower_third_rendered",
                        "ass_hook_overlay_injected",
                        "non_text_visual_hook_rendered",
                        "ass_event_count_before",
                        "ass_event_count_final",
                        "ass_event_hard_cap",
                        "ass_events_merged_for_daily",
                        "ass_karaoke_enabled",
                        "ass_approx_simple_mode",
                        "ass_hook_overlay_removed",
                        "captions_overlap_removed",
                        "selected_window_before",
                        "selected_window_after",
                        "complete_idea_score",
                        "incomplete_viral_window_detected",
                        "setup_context_shift_seconds",
                        "trailing_low_value_seconds",
                        "viral_window_shifted_back",
                        "viral_window_shift_reason",
                        "forced_shift_back_applied",
                        "selected_alternative_for_complete_idea",
                        "incomplete_window_uncorrectable",
                        "final_output_uses_motion_overlay",
                    ):
                        _rinfo[_h4_key] = _contract.get(_h4_key)
                logger.info(
                    "VPI_OUTPUT_MANAGEMENT_COMPLETE task_id=%s manifest=%s summary=%s review_bundle=%s clips=%d warnings=%d",
                    task_id,
                    str(manifest_written).lower(),
                    str(summary_written).lower(),
                    str(review_bundle_written).lower(),
                    len(clip_outputs_for_manifest),
                    len(output_management_payload["output_management_warnings"]),
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

            final_clip_rows_count_db = await self.clip_repo.get_clips_count(self.db, task_id)
            output_files_count = sum(1 for _, info, _ in render_results if info and info.get("path"))
            clips_to_insert_count = min(successful_renders, num_clips)
            inserted_clips_count = len(clip_ids)
            render_attempted_count = total_clips
            render_success_count = successful_renders
            durable_outputs_count = sum(
                1
                for _, info, _ in render_results
                if isinstance(info, dict) and str(info.get("durable_output_path") or "").strip()
            )
            technical_valid_count = sum(
                1
                for _, info, _ in render_results
                if isinstance(info, dict)
                and bool(_as_dict(info.get("technical_qc")).get("passed"))
            )
            publishable_gate_error_count = sum(
                1
                for _, info, _ in render_results
                if isinstance(info, dict) and bool(info.get("publishable_gate_error_nonfatal"))
            )
            qc_reasons_collected: List[str] = []
            editorial_warning_count = 0
            for _, info, _ in render_results:
                if not isinstance(info, dict):
                    continue
                if str(info.get("qc_status") or "").lower() == "needs_review":
                    editorial_warning_count += 1
                qc_reasons_collected.extend([str(x) for x in (_safe_list(info.get("qc_reasons"))) if str(x)])
            candidate_pool_size = len(_safe_list(result.get("segments")))
            zero_reason = ""
            # CRITICAL: Use DB count, not in-memory count, to detect zero clips
            effective_clips_count = final_clip_rows_count_db if final_clip_rows_count_db > 0 else inserted_clips_count
            if effective_clips_count == 0:
                _strict_qc_blocked = any(
                    str(item.get("stage") or "") == "publishable_qc_failed"
                    and (
                        "editing_zero_detected" in str(item.get("reason") or "")
                        or "strict_publishable=False" in str(item.get("reason") or "")
                        or "strict_reasons=" in str(item.get("reason") or "")
                    )
                    for item in clip_failure_details
                )
                if total_clips == 0:
                    zero_reason = str(result.get("selection_failure_reason") or "no_segments_selected")
                elif successful_renders == 0:
                    zero_reason = "all_renders_failed"
                elif _strict_qc_blocked:
                    zero_reason = "no_publishable_clips_strict_qc_failed"
                elif rejected_candidate_reasons:
                    zero_reason = (
                        "all_candidates_rejected_by_technical_gate"
                        if deadline_safe_mode
                        else "all_candidates_rejected_by_publishable_gate"
                    )
                else:
                    zero_reason = "no_clips_generated"

                # --- TASK STATUS SEMANTICS HARDENING ---
                # Distinguish post_render_delivery_failed (rendered>0, inserted=0)
                # from completed_no_clips (rendered=0, no fatal exception)
                if successful_renders > 0 and inserted_clips_count == 0:
                    _outcome = "post_render_delivery_failed"
                elif successful_renders == 0 and total_clips > 0:
                    _outcome = "failed_render"
                elif total_clips == 0:
                    _outcome = "completed_no_clips"
                else:
                    _outcome = "completed_no_clips"
                # --- END TASK STATUS SEMANTICS HARDENING ---

            diagnostics = {
                "task_id": task_id,
                "status": "processing",
                "progress_message": "",
                "requested_clips": num_clips,
                "candidate_pool_size": candidate_pool_size,
                "selected_segments_count": total_clips,
                "extraction_success_count": successful_extractions,
                "render_attempted_count": render_attempted_count,
                "render_success_count": render_success_count,
                "generated_segments_count": total_clips,
                "rendered_outputs_count": successful_renders,
                "durable_outputs_count": durable_outputs_count,
                "technical_valid_count": technical_valid_count,
                "editorial_warning_count": editorial_warning_count,
                "publishable_gate_error_count": publishable_gate_error_count,
                "clips_to_insert_count": clips_to_insert_count,
                "inserted_clips_count": inserted_clips_count,
                "failed_clip_count": max(0, total_clips - inserted_clips_count),
                "failed_clip_reasons": clip_failure_details[:12],
                "qc_reasons": qc_reasons_collected[:16],
                "strict_qc_rejected_count": strict_qc_rejected_count,
                "strict_qc_rejected_reasons": strict_qc_rejected_reasons[:12],
                "final_clip_rows_count_db": final_clip_rows_count_db,
                "effective_clips_count": effective_clips_count,
                "frontend_visible_clips_count": None,
                "output_files_count": output_files_count,
                "reason_if_zero_clips": zero_reason,
                "selected_clip_package_summary": package_diversity_summary,
                            "package_diversity_score": package_diversity_score,
                            "package_diversity_reason": package_diversity_reason,
                            "package_category_distribution": package_category_distribution,
                "package_theme_distribution": package_theme_distribution,
                "package_duration_balance_ok": package_duration_balance_ok,
                "package_diversity_warnings": package_diversity_warnings,
                "clip_briefs": clip_briefs,
                "clip_brief_summary": clip_brief_summary,
                "high_confidence_clip_count": high_confidence_clip_count,
                "review_clip_count": review_clip_count,
                "campaign_fit_summary": campaign_fit_summary,
                "campaign_intent": campaign_intent,
                "campaign_intent_confidence": campaign_intent_confidence,
                "campaign_intent_source": campaign_intent_source,
                "campaign_intent_reason": campaign_intent_reason,
                "selected_campaign_mix": selected_campaign_mix,
                "campaign_alignment_summary": campaign_alignment_summary,
                "preferred_categories": preferred_categories,
                "suppressed_categories": suppressed_categories,
                "preferred_keywords": preferred_keywords,
                "campaign_boost_applied": campaign_boost_applied,
                "campaign_boost_score": campaign_boost_score,
                "campaign_alignment_score": campaign_alignment_score,
                "campaign_alignment_reason": campaign_alignment_reason,
                "sensitive_handling_required": sensitive_handling_required,
                "output_management": dict(output_management_payload),
                "output_root": output_management_payload["output_root"],
                "clips_output_dir": output_management_payload["clips_output_dir"],
                "manifest_output_path": output_management_payload["manifest_output_path"],
                "summary_output_path": output_management_payload["summary_output_path"],
                "output_filename_strategy": output_management_payload["output_filename_strategy"],
                "output_filename_safe": output_management_payload["output_filename_safe"],
                "output_filename_collision_resolved": output_management_payload["output_filename_collision_resolved"],
                "output_management_ok": output_management_payload["output_management_ok"],
                "output_management_warnings": list(output_management_payload["output_management_warnings"]),
                "output_clip_count": output_management_payload["output_clip_count"],
                "publishable_clip_count": output_management_payload["publishable_clip_count"],
                "review_clip_count": output_management_payload["review_clip_count"],
                "high_confidence_clip_count": output_management_payload["high_confidence_clip_count"],
                "review_bundle_dir": output_management_payload.get("review_bundle_dir"),
                "review_index_path": output_management_payload.get("review_index_path"),
                "review_bundle_json_path": output_management_payload.get("review_json_path"),
                "review_bundle_ready": output_management_payload.get("review_bundle_ready", False),
                "review_bundle_warnings": list(output_management_payload.get("review_bundle_warnings") or []),
            }
            diagnostics = _normalize_json_for_context(task_id, "delivery_summary", diagnostics)
            stage_timings["clip_persistence_diagnostics"] = diagnostics
            logger.info("[clip-persistence] %s", diagnostics)
            logger.info(
                "DELIVERY_CONTRACT_SUMMARY task_id=%s requested=%d selected=%d extracted=%d rendered=%d inserted=%d failed=%d",
                task_id,
                num_clips,
                total_clips,
                successful_extractions,
                successful_renders,
                final_clip_rows_count_db,
                max(0, total_clips - final_clip_rows_count_db),
            )
            if effective_clips_count == 0:
                _strict_fail_reasons = [
                    str(item.get("reason") or "")
                    for item in clip_failure_details
                    if str(item.get("stage") or "") == "publishable_qc_failed"
                ][:6]
                error_message = (
                    f"No clips were persisted to generated_clips. reason={zero_reason or 'no_clips_generated'}; "
                    f"rendered_outputs={successful_renders}; insert_success={inserted_clips_count}; "
                    f"strict_qc_reasons={'|'.join(_strict_fail_reasons) if _strict_fail_reasons else 'none'}"
                )
                logger.warning(
                    "NO_CLIPS_GENERATED_DIAGNOSTIC task_id=%s reason=%s diagnostics=%s",
                    task_id,
                    zero_reason or "no_clips_generated",
                    diagnostics,
                )

                # --- TASK STATUS SEMANTICS HARDENING: Use _outcome for error_code/progress_message ---
                if _outcome == "post_render_delivery_failed":
                    _error_code = "POST_RENDER_DELIVERY_FAILED"
                    _progress_message = "post_render_delivery_failed"
                    _log_tag = "POST_RENDER_DELIVERY_FAILED"
                    _callback_msg = "Post-render delivery failed: rendered but no clips inserted"
                elif _outcome == "failed_render":
                    _error_code = "FAILED_RENDER"
                    _progress_message = "failed_render"
                    _log_tag = "TASK_FAILED_RENDER"
                    _callback_msg = "Render failed for all clips"
                elif _outcome == "completed_no_clips":
                    _error_code = "COMPLETED_NO_CLIPS"
                    _progress_message = "completed_no_clips"
                    _log_tag = "TASK_COMPLETED_NO_CLIPS"
                    _callback_msg = "No clips generated"
                else:
                    _error_code = (
                        "NO_PUBLISHABLE_CLIPS"
                        if zero_reason == "no_publishable_clips_strict_qc_failed"
                        else "NO_CLIPS_GENERATED"
                    )
                    _progress_message = (
                        "no_publishable_clips"
                        if _error_code == "NO_PUBLISHABLE_CLIPS"
                        else f"no_clips_generated:{zero_reason or 'unknown'}"
                    )
                    _log_tag = "NO_CLIPS_GENERATED_DIAGNOSTIC"
                    _callback_msg = "No publishable clips generated" if _error_code == "NO_PUBLISHABLE_CLIPS" else "No clips generated"

                logger.warning(
                    "%s task_id=%s outcome=%s reason=%s",
                    _log_tag,
                    task_id,
                    _outcome,
                    zero_reason or "no_clips_generated",
                )
                diagnostics["status"] = "completed" if _outcome == "completed_no_clips" else "error"
                diagnostics["progress_message"] = _progress_message
                diagnostics["outcome"] = _outcome
                _maybe_write_task_diagnostic_report(diagnostics)

                if _outcome == "completed_no_clips":
                    # completed_no_clips: use 'completed' status with explicit progress_message
                    await self.task_repo.update_task_status(
                        self.db,
                        task_id,
                        "completed",
                        progress=100,
                        progress_message=_progress_message,
                    )
                else:
                    # post_render_delivery_failed, failed_render: use 'error' status
                    await self.task_repo.update_task_failure_details(
                        self.db,
                        task_id,
                        error_code=_error_code,
                        error_message=error_message,
                        progress_message=_progress_message,
                        progress=100,
                    )
                await self.task_repo.update_task_runtime_metadata(
                    self.db,
                    task_id,
                    completed_at=datetime.now(timezone.utc),
                    stage_timings_json=json.dumps(_normalize_json_for_context(task_id, "delivery_summary", stage_timings)),
                    error_code=_error_code,
                )
                if progress_callback:
                    await progress_callback(
                        100,
                        _callback_msg,
                        "completed" if _outcome == "completed_no_clips" else "error",
                    )
                return {
                    "task_id": task_id,
                    "clips_count": 0,
                    "segments": result["segments"],
                    "summary": result.get("summary"),
                    "key_topics": result.get("key_topics"),
                    "selected_clip_package_summary": package_diversity_summary,
                            "package_diversity_score": package_diversity_score,
                            "package_diversity_reason": package_diversity_reason,
                            "package_category_distribution": package_category_distribution,
                    "package_theme_distribution": package_theme_distribution,
                    "package_duration_balance_ok": package_duration_balance_ok,
                    "package_diversity_warnings": package_diversity_warnings,
                    "clip_briefs": clip_briefs,
                    "clip_brief_summary": clip_brief_summary,
                    "high_confidence_clip_count": high_confidence_clip_count,
                    "review_clip_count": review_clip_count,
                    "campaign_fit_summary": campaign_fit_summary,
                    "campaign_intent": campaign_intent,
                    "campaign_intent_confidence": campaign_intent_confidence,
                    "campaign_intent_source": campaign_intent_source,
                    "campaign_intent_reason": campaign_intent_reason,
                    "selected_campaign_mix": selected_campaign_mix,
                    "campaign_alignment_summary": campaign_alignment_summary,
                    "preferred_categories": preferred_categories,
                    "suppressed_categories": suppressed_categories,
                    "preferred_keywords": preferred_keywords,
                    "campaign_boost_applied": campaign_boost_applied,
                    "campaign_boost_score": campaign_boost_score,
                    "campaign_alignment_score": campaign_alignment_score,
                    "campaign_alignment_reason": campaign_alignment_reason,
                    "sensitive_handling_required": sensitive_handling_required,
                    **output_management_payload,
                    "error": _progress_message,
                    "reason": zero_reason or "no_clips_generated",
                    "outcome": _outcome,
                }

            # CRITICAL: Re-query DB count before marking completed to verify clips persisted
            final_db_count_before_complete = await self.clip_repo.get_clips_count(self.db, task_id)
            if final_db_count_before_complete == 0 and clip_outputs_for_manifest:
                for _fallback_idx, _fallback_info in enumerate(clip_outputs_for_manifest, start=1):
                    _fallback_path = Path(str(_fallback_info.get("path") or ""))
                    _fallback_ok, _, _ = _deadline_safe_technical_gate(_fallback_path)
                    if not _fallback_ok:
                        continue
                    try:
                        _clip_id = await self.clip_repo.create_clip(
                            self.db,
                            task_id=task_id,
                            filename=str(_fallback_info.get("filename") or _fallback_path.name),
                            file_path=str(_fallback_path),
                            start_time=str(_fallback_info.get("start_time") or "00:00"),
                            end_time=str(_fallback_info.get("end_time") or "00:00"),
                            duration=float(_fallback_info.get("duration") or 0.0),
                            text=str(_fallback_info.get("text") or ""),
                            relevance_score=float(_fallback_info.get("relevance_score") or 0.0),
                            reasoning=str(_fallback_info.get("reasoning") or "post_render_recovered_valid_mp4"),
                            clip_order=_fallback_idx,
                            virality_score=float(_fallback_info.get("virality_score") or 0.0),
                            hook_score=float(_fallback_info.get("hook_score") or 0.0),
                            engagement_score=float(_fallback_info.get("engagement_score") or 0.0),
                            value_score=float(_fallback_info.get("value_score") or 0.0),
                            shareability_score=float(_fallback_info.get("shareability_score") or 0.0),
                            hook_type=_fallback_info.get("hook_type"),
                            translated_text=_fallback_info.get("translated_text"),
                            social_title=_fallback_info.get("social_title"),
                            social_description=_fallback_info.get("social_description"),
                            suggested_hashtags=_fallback_info.get("suggested_hashtags"),
                            thumbnail_filename=_fallback_info.get("thumbnail_filename"),
                            face_detected=_fallback_info.get("face_detected"),
                            hook_preview_score=float(_fallback_info.get("hook_preview_score") or 0.0),
                            variants_json=json.dumps(_normalize_json_compatible({
                                "daily_publishing": {
                                    "final_rendered_contract": _fallback_info.get("final_rendered_contract") or _fallback_info.get("final_mp4_contract") or {},
                                    "publishable_status": _fallback_info.get("publishable_status"),
                                    "publishable_warnings": _fallback_info.get("publishable_warnings", []),
                                    "publishable_score": _fallback_info.get("publishable_score"),
                                    "technical_qc": _fallback_info.get("technical_qc") or {},
                                    "editorial_qc": _fallback_info.get("editorial_qc") or {},
                                    "qc_status": _fallback_info.get("qc_status"),
                                    "qc_reasons": _fallback_info.get("qc_reasons", []),
                                    "qc_warnings": _fallback_info.get("qc_warnings", []),
                                },
                                "vpi": {
                                    "editorial_type": _fallback_info.get("editorial_type"),
                                },
                            }, {}) or {}),
                        )
                        clip_ids.append(_clip_id)
                    except Exception as _persist_recovery_e:
                        logger.warning(
                            "VPI_TASK_FINALIZATION_WARNING_NONFATAL task_id=%s clip_order=%d stage=fallback_clip_insert error=%s",
                            task_id,
                            _fallback_idx,
                            _persist_recovery_e,
                        )
                if clip_ids:
                    await self.db.commit()
                    await self.task_repo.update_task_clips(self.db, task_id, clip_ids)
                    final_db_count_before_complete = await self.clip_repo.get_clips_count(self.db, task_id)
                    logger.warning(
                        "VPI_POST_RENDER_RECOVERED_WITH_VALID_MP4 task_id=%s inserted=%d",
                        task_id,
                        final_db_count_before_complete,
                    )
            if final_db_count_before_complete == 0:
                error_message = (
                    "No clips were persisted to generated_clips at completion check. "
                    f"insert_success={inserted_clips_count}; rendered_outputs={successful_renders}"
                )
                logger.error(
                    "NO_CLIPS_GENERATED_DIAGNOSTIC task_id=%s — DB count is 0 before marking completed! "
                    "Clips were inserted but not persisted. diagnostics=%s",
                    task_id,
                    diagnostics,
                )
                diagnostics["status"] = "error"
                diagnostics["progress_message"] = "no_clips_generated:clips_not_persisted"
                diagnostics["reason_if_zero_clips"] = "clips_not_persisted"
                _maybe_write_task_diagnostic_report(diagnostics)
                await self.task_repo.update_task_failure_details(
                    self.db,
                    task_id,
                    error_code="NO_CLIPS_GENERATED",
                    error_message=error_message,
                    progress_message="no_clips_generated:clips_not_persisted",
                    progress=100,
                )
                await self.task_repo.update_task_runtime_metadata(
                    self.db,
                    task_id,
                    completed_at=datetime.now(timezone.utc),
                    stage_timings_json=json.dumps(_normalize_json_for_context(task_id, "delivery_summary", stage_timings)),
                    error_code="NO_CLIPS_GENERATED",
                )
                if progress_callback:
                    await progress_callback(100, "No clips generated (persistence failure)", "error")
                return {
                    "task_id": task_id,
                    "clips_count": 0,
                    "segments": result["segments"],
                    "summary": result.get("summary"),
                    "key_topics": result.get("key_topics"),
                    "selected_clip_package_summary": package_diversity_summary,
                    "package_diversity_score": package_diversity_score,
                    "package_category_distribution": package_category_distribution,
                    "package_theme_distribution": package_theme_distribution,
                    "package_duration_balance_ok": package_duration_balance_ok,
                    "package_diversity_warnings": package_diversity_warnings,
                    "campaign_intent": campaign_intent,
                    "campaign_intent_confidence": campaign_intent_confidence,
                    "campaign_intent_source": campaign_intent_source,
                    "campaign_intent_reason": campaign_intent_reason,
                    "selected_campaign_mix": selected_campaign_mix,
                    "campaign_alignment_summary": campaign_alignment_summary,
                    "preferred_categories": preferred_categories,
                    "suppressed_categories": suppressed_categories,
                    "preferred_keywords": preferred_keywords,
                    "campaign_boost_applied": campaign_boost_applied,
                    "campaign_boost_score": campaign_boost_score,
                    "campaign_alignment_score": campaign_alignment_score,
                    "campaign_alignment_reason": campaign_alignment_reason,
                    "sensitive_handling_required": sensitive_handling_required,
                    **output_management_payload,
                    "error": "no_clips_generated",
                    "reason": "clips_not_persisted",
                }

            persisted_editorial_ready = 0
            persisted_needs_review = 0
            persisted_rejected = 0
            persisted_editorial_reasons: List[str] = []
            persisted_rows = await self.clip_repo.get_clips_by_task(self.db, task_id)
            for _row in persisted_rows:
                _qc_status = str((_row.get("qc_status") or "")).lower()
                if _qc_status in {"rejected", "rejected_technical"}:
                    persisted_rejected += 1
                    persisted_editorial_reasons.extend([str(x) for x in (_row.get("qc_reasons") or [])[:2]])
                elif _qc_status == "needs_review":
                    persisted_needs_review += 1
                    persisted_editorial_reasons.extend([str(x) for x in (_row.get("qc_reasons") or [])[:2]])
                else:
                    persisted_editorial_ready += 1
            stage_timings["persisted_clip_status_counts"] = {
                "ready": persisted_editorial_ready,
                "needs_review": persisted_needs_review,
                "rejected": persisted_rejected,
            }
            stage_timings["persisted_editorial_reasons_sample"] = persisted_editorial_reasons[:8]
            logger.info(
                "DELIVERY_QC_STATUS_SUMMARY task_id=%s ready=%d needs_review=%d rejected=%d blocking_editorial=%s",
                task_id,
                persisted_editorial_ready,
                persisted_needs_review,
                persisted_rejected,
                str(editorial_qc_blocking).lower(),
            )

            delivered_count_for_completion = final_db_count_before_complete

            # --- TASK STATUS SEMANTICS HARDENING: Determine completion outcome ---
            # Determine if any clips have needs_review QC status
            _has_needs_review = persisted_needs_review > 0
            _has_ready = persisted_editorial_ready > 0

            if delivered_count_for_completion < num_clips:
                _shortage_reasons = []
                if clip_failure_details:
                    _shortage_reasons = [str(x.get("stage") or x.get("reason") or "unknown") for x in clip_failure_details[:6]]
                elif rejected_candidate_reasons:
                    _shortage_reasons = [str(x.get("reason") or "candidate_rejected") for x in rejected_candidate_reasons[:6]]
                _shortage_reason = ",".join(_shortage_reasons) if _shortage_reasons else "insufficient_deliverable_candidates"
                stage_timings["delivery_status"] = "shortage"
                stage_timings["delivery_shortage_reason"] = _shortage_reason
                _progress_message = f"completed_with_shortage:{delivered_count_for_completion}/{num_clips}"
                logger.warning(
                    "DELIVERY_SHORTAGE task_id=%s delivered=%d requested=%d reason=%s",
                    task_id,
                    delivered_count_for_completion,
                    num_clips,
                    _shortage_reason,
                )
            else:
                stage_timings["delivery_status"] = "full"

            # Determine semantic progress_message based on QC status
            if _has_needs_review and _has_ready:
                _progress_message = "completed_with_warnings"
                _log_tag = "TASK_COMPLETED_WITH_WARNINGS"
                logger.info(
                    "TASK_COMPLETED_WITH_WARNINGS task_id=%s ready=%d needs_review=%d",
                    task_id,
                    persisted_editorial_ready,
                    persisted_needs_review,
                )
            elif _has_needs_review and not _has_ready:
                # All clips need review — still completed but with warnings
                _progress_message = "completed_with_warnings"
                _log_tag = "TASK_COMPLETED_WITH_WARNINGS"
                logger.info(
                    "TASK_COMPLETED_WITH_WARNINGS task_id=%s ready=%d needs_review=%d (all clips need review)",
                    task_id,
                    persisted_editorial_ready,
                    persisted_needs_review,
                )
            else:
                _progress_message = "completed_with_clips"
                _log_tag = "TASK_COMPLETED_WITH_CLIPS"
                logger.info(
                    "TASK_COMPLETED_WITH_CLIPS task_id=%s clips_count=%d",
                    task_id,
                    final_db_count_before_complete,
                )

            diagnostics["editorial_warning_count"] = persisted_needs_review
            diagnostics["inserted_clips_count"] = final_db_count_before_complete
            diagnostics["status"] = "completed"
            diagnostics["progress_message"] = _progress_message
            diagnostics["qc_reasons"] = list(
                dict.fromkeys(
                    [str(x) for x in (_safe_list(diagnostics.get("qc_reasons")) + persisted_editorial_reasons) if str(x)]
                )
            )[:20]
            _maybe_write_task_diagnostic_report(diagnostics)

            # Mark as completed
            await self.task_repo.update_task_status(
                self.db,
                task_id,
                "completed",
                progress=100,
                progress_message=_progress_message,
            )
            logger.info(
                "VPI_TASK_FINALIZED_WITH_VALID_MP4 task_id=%s clips_count=%d progress_message=%s",
                task_id,
                final_db_count_before_complete,
                _progress_message,
            )

            if progress_callback:
                await progress_callback(100, _progress_message, "completed")

            await self.task_repo.update_task_runtime_metadata(
                self.db,
                task_id,
                completed_at=datetime.now(timezone.utc),
                stage_timings_json=json.dumps(_normalize_json_for_context(task_id, "delivery_summary", stage_timings)),
                error_code="",
            )
            await self._send_completion_notification_if_needed(
                task_id=task_id,
                clips_count=final_db_count_before_complete,
            )

            return {
                "task_id": task_id,
                "clips_count": final_db_count_before_complete,
                "segments": result["segments"],
                "summary": result.get("summary"),
                "key_topics": result.get("key_topics"),
                "selected_clip_package_summary": package_diversity_summary,
                "package_diversity_score": package_diversity_score,
                "package_category_distribution": package_category_distribution,
                "package_theme_distribution": package_theme_distribution,
                "package_duration_balance_ok": package_duration_balance_ok,
                "package_diversity_warnings": package_diversity_warnings,
                "clip_briefs": clip_briefs,
                "clip_brief_summary": clip_brief_summary,
                "high_confidence_clip_count": high_confidence_clip_count,
                "review_clip_count": review_clip_count,
                "campaign_fit_summary": campaign_fit_summary,
                "campaign_intent": campaign_intent,
                "campaign_intent_confidence": campaign_intent_confidence,
                "campaign_intent_source": campaign_intent_source,
                "campaign_intent_reason": campaign_intent_reason,
                "selected_campaign_mix": selected_campaign_mix,
                "campaign_alignment_summary": campaign_alignment_summary,
                "preferred_categories": preferred_categories,
                "suppressed_categories": suppressed_categories,
                "preferred_keywords": preferred_keywords,
                "campaign_boost_applied": campaign_boost_applied,
                "campaign_boost_score": campaign_boost_score,
                "campaign_alignment_score": campaign_alignment_score,
                "campaign_alignment_reason": campaign_alignment_reason,
                "sensitive_handling_required": sensitive_handling_required,
                **output_management_payload,
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

            # --- TASK STATUS SEMANTICS HARDENING: Determine error type ---
            message = str(e).lower()
            error_code = "task_error"
            progress_message = str(e)

            # Determine if this is a render failure vs processing failure
            _is_render_error = any(
                term in message
                for term in [
                    "render", "ffmpeg", "encoding", "compositor",
                    "overlay", "broll", "caption", "subtitle",
                    "output", "clip_creation", "create_single_clip",
                    "create_deadline_safe_clip",
                ]
            )
            _is_processing_error = any(
                term in message
                for term in [
                    "download", "youtube", "transcript", "transcription",
                    "analysis", "segment", "pipeline",
                ]
            )

            if _is_render_error:
                error_code = "FAILED_RENDER"
                progress_message = "failed_render"
            elif _is_processing_error:
                error_code = "FAILED_PROCESSING"
                progress_message = "failed_processing"
            elif "download" in message or "youtube" in message:
                error_code = "download_error"
            elif "transcript" in message:
                error_code = "transcription_error"
            elif "analysis" in message:
                error_code = "analysis_error"
            elif "cancelled" in message:
                error_code = "cancelled"

            await self.task_repo.update_task_status(
                self.db, task_id, "error", progress_message=progress_message
            )

            await self.task_repo.update_task_runtime_metadata(
                self.db,
                task_id,
                completed_at=datetime.now(timezone.utc),
                error_code=error_code,
            )
            _maybe_write_task_diagnostic_report(
                {
                    "task_id": task_id,
                    "status": "error",
                    "progress_message": progress_message,
                    "requested_clips": 0,
                    "candidate_pool_size": 0,
                    "selected_segments_count": 0,
                    "extraction_success_count": 0,
                    "render_attempted_count": 0,
                    "render_success_count": 0,
                    "rendered_outputs_count": 0,
                    "durable_outputs_count": 0,
                    "technical_valid_count": 0,
                    "editorial_warning_count": 0,
                    "publishable_gate_error_count": 0,
                    "strict_qc_rejected_count": 0,
                    "inserted_clips_count": 0,
                    "frontend_visible_clips_count": None,
                    "output_files_count": 0,
                    "failed_clip_reasons": [{"stage": "exception", "reason": str(e)[:320]}],
                    "qc_reasons": [error_code],
                }
            )

            # Log the semantic error code
            if error_code in ("FAILED_RENDER", "FAILED_PROCESSING"):
                logger.warning(
                    "TASK_%s task_id=%s error=%s",
                    error_code,
                    task_id,
                    str(e),
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
        # --- TASK STATUS SEMANTICS HARDENING: Recovery logic ---
        # Only recover from error to completed if the error_code is NOT a semantic failure
        # (FAILED_RENDER, FAILED_PROCESSING, POST_RENDER_DELIVERY_FAILED)
        _error_code = str(task.get("error_code") or "").upper()
        _progress_msg = str(task.get("progress_message") or "").lower()
        _is_semantic_failure = _error_code in (
            "FAILED_RENDER", "FAILED_PROCESSING", "POST_RENDER_DELIVERY_FAILED"
        ) or _progress_msg in ("failed_render", "failed_processing", "post_render_delivery_failed")
        if task["clips_count"] > 0 and str(task.get("status") or "").lower() == "error" and not _is_semantic_failure:
            logger.warning(
                "TASK_STATUS_RECOVERED_FROM_ERROR task_id=%s clips_count=%d error_code=%s",
                task_id,
                task["clips_count"],
                _error_code,
            )
            task["status"] = "completed"
            task["progress_message"] = "completed_with_recovered_clips"
        elif task["clips_count"] == 0 and str(task.get("status") or "").lower() == "completed" and _progress_msg == "completed_no_clips":
            # completed_no_clips is an honest zero-clip state — keep as-is
            pass
        # --- END TASK STATUS SEMANTICS HARDENING ---

        # OUTPUT RESCUE Fix C: expose delivery diagnostics so the frontend can render
        # placeholder cards for requested-but-missing clips instead of hiding them.
        delivery_diagnostics: Dict[str, Any] = {}
        try:
            _stj = task.get("stage_timings_json")
            if _stj:
                _stages = json.loads(_stj) if isinstance(_stj, str) else dict(_stj)
                if isinstance(_stages, dict):
                    delivery_diagnostics = _as_dict(_stages.get("clip_persistence_diagnostics"))
        except Exception:
            delivery_diagnostics = {}
        if not delivery_diagnostics:
            try:
                _diag_path = _resolve_task_diagnostics_dir() / f"{task_id}.json"
                if _diag_path.exists():
                    delivery_diagnostics = json.loads(_diag_path.read_text(encoding="utf-8"))
            except Exception:
                delivery_diagnostics = {}
        if delivery_diagnostics:
            _requested = int(delivery_diagnostics.get("requested_clips") or 0)
            _visible = len(clips)
            _missing = max(0, _requested - _visible)
            _failed_reasons = _safe_list(delivery_diagnostics.get("failed_clip_reasons"))
            task["delivery_diagnostics"] = {
                "requested_clips": _requested,
                "render_attempted_count": delivery_diagnostics.get("render_attempted_count"),
                "render_success_count": delivery_diagnostics.get("render_success_count"),
                "effective_clips_count": delivery_diagnostics.get("effective_clips_count"),
                "inserted_clips_count": delivery_diagnostics.get("inserted_clips_count"),
                "visible_clip_cards_count": _visible + _missing,
                "missing_clip_count": _missing,
                "failed_clip_reasons": _failed_reasons[:12],
                "reason_if_zero_clips": delivery_diagnostics.get("reason_if_zero_clips"),
            }
            logger.info(
                "VPI_OUTPUT_RESCUE_VISIBLE_CLIPS_BUILT task_id=%s requested=%d db_clips=%d placeholders=%d",
                task_id, _requested, _visible, _missing,
            )
            for _c in clips:
                _qs = str(_c.get("qc_status") or "")
                logger.info(
                    "VPI_OUTPUT_RESCUE_CLIP_CARD_STATUS task_id=%s clip_id=%s status=%s",
                    task_id, _c.get("id"), _qs or "ready",
                )
                if _qs and _qs != "ready":
                    logger.info(
                        "VPI_OUTPUT_RESCUE_NON_PUBLISHABLE_VISIBLE task_id=%s clip_id=%s status=%s",
                        task_id, _c.get("id"), _qs,
                    )

        # Cache firewall: avoid attaching shared analysis cache to task responses.
        # Editorial decisions must remain task-scoped for operational validation.
        task["analysis"] = None

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
