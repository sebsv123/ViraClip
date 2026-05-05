"""Build a JSON-safe render context for a clip.

The auto-pipeline produces in-memory ``segment`` dicts that contain rich
metadata (transcript, words, narrative cuts, broll suggestions, hook info,
multimodal timeline references, etc.) plus opaque objects emitted by
analysers (``_render_plan``, ``_semantic_plan``). The applicator that re-
renders a clip with a different approval set needs the data — but only the
pieces that can be serialised to JSONB.

This module produces a compact, deterministic dict snapshot that:
- only keeps primitives + list/dict trees,
- drops keys that start with ``_`` (analyser internals),
- preserves the source video path and the task config so the applicator can
  rebuild the original ``create_single_clip`` call.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# Internal segment keys we deliberately keep (everything else is filtered out
# unless it is JSON-serialisable on its own).
_PRESERVED_SEGMENT_KEYS = {
    "start_time",
    "end_time",
    "text",
    "transcript",
    "virality_score",
    "hook_score",
    "engagement_score",
    "value_score",
    "shareability_score",
    "hook_type",
    "phi3_hook_type",
    "scroll_stop_probability",
    "recommended_duration",
    "intensity",
    "vfx_trigger",
    "bgm_style",
    "broll_suggestions",
    "narrative_cuts",
    "social_title",
    "social_description",
    "suggested_hashtags",
    "reasoning",
    "relevance_score",
    "clip_order",
    "_source_video_path",
    "words",
}

_PRESERVED_CLIP_INFO_KEYS = {
    "filename",
    "path",
    "start_time",
    "end_time",
    "duration",
    "preset_used",
    "broll_overlays",
    "zoom_punch_applied",
    "color_grade_applied",
    "loudnorm_applied",
    "audio_ducking_applied",
    "speed_control_applied",
    "audio_denoised",
    "background_composite_applied",
    "hook_reorder_applied",
    "hook_text",
    "hook_type",
    "cta_overlay_applied",
    "emoji_overlays_applied",
    "text_pops_applied",
    "contextual_overlays",
    "sfx_injected",
    "bgm_track",
    "bgm_style",
    "qa_passed",
    "qa_issues",
    "creative_enhanced",
    "creative_steps_ok",
    "creative_steps_failed",
    # Suggestion Studio keys (needed by suggestion_seeder.py)
    "hook_reorder_suggested",
    "virality_score",
    "hook_score",
    "engagement_score",
    "value_score",
    "shareability_score",
    "timeline_events",
    "timeline_event_details",
    "broll_items",
    "broll_details",
    "overlay_items",
    "sfx_items",
    "zoom_punch_zoom",
    "zoom_punch_duration",
    "extra_vf_filters",
    "sharpen_applied",
    "sharpen_intensity",
    "vignette_applied",
    "vignette_intensity",
    "vignette_color",
    "film_grain_applied",
    "grain_intensity",
    "blur_applied",
    "blur_radius",
    "blur_type",
    "ducking_reduction",
    "ducking_threshold",
    "composite_mode",
    "bgm_volume",
    "steps_failed",
    "steps_ok",
    "hook_already_optimized",
}


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Return ``value`` if JSON-serialisable, otherwise convert it to ``repr``.

    Recursive but shallow (``depth`` capped) to stop runaway dumps from
    pathological objects.
    """
    if depth > 6:
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(k): _json_safe(v, depth + 1)
            for k, v in value.items()
            if not str(k).startswith("_")
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, depth + 1) for v in value]
    # Fall back to a stable string for unknown objects.
    try:
        return str(value)
    except Exception:
        return None


def _filter_segment(segment: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, val in segment.items():
        if key.startswith("_") and key not in _PRESERVED_SEGMENT_KEYS:
            continue
        if key in _PRESERVED_SEGMENT_KEYS or isinstance(
            val, (str, int, float, bool, type(None))
        ):
            out[key] = _json_safe(val)
        elif isinstance(val, (list, tuple, dict)):
            out[key] = _json_safe(val)
        # silently drop unknown opaque objects
    return out


def _filter_clip_info(clip_info: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in _PRESERVED_CLIP_INFO_KEYS:
        if key in clip_info:
            out[key] = _json_safe(clip_info[key])
    return out


def build_clip_render_context(
    *,
    clip_index: int,
    segment: Dict[str, Any],
    clip_info: Dict[str, Any],
    source_video_path: str,
    task_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Produce a JSON-safe snapshot suitable for ``ClipRepository.set_render_context``.

    The schema is intentionally explicit so the applicator never has to guess.
    """
    return {
        "schema_version": 1,
        "clip_index": int(clip_index),
        "source_video_path": source_video_path,
        "task_config": _json_safe(task_config),
        "segment": _filter_segment(segment or {}),
        "clip_info": _filter_clip_info(clip_info or {}),
    }


def list_known_segment_keys() -> List[str]:
    """Helper for tests / docs: returns the segment keys we keep on purpose."""
    return sorted(_PRESERVED_SEGMENT_KEYS)


def list_known_clip_info_keys() -> List[str]:
    return sorted(_PRESERVED_CLIP_INFO_KEYS)


def merge_pending_overrides(
    base_context: Dict[str, Any], overrides: Optional[Iterable[Dict[str, Any]]]
) -> Dict[str, Any]:
    """Used by the applicator: layer suggestion payload overrides on top of the
    persisted context. Each override is expected to look like
    ``{"path": ["task_config", "caption_template"], "value": "tiktok"}`` so we
    can evolve it without changing the contract.
    """
    if not overrides:
        return base_context
    ctx = _json_safe(base_context)
    for override in overrides:
        path = override.get("path") or []
        if not path:
            continue
        cursor = ctx
        for key in path[:-1]:
            cursor = cursor.setdefault(key, {})
            if not isinstance(cursor, dict):
                break
        else:
            cursor[path[-1]] = _json_safe(override.get("value"))
    return ctx
