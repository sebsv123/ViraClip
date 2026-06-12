"""
vpi_remotion_scene_plan.py — Remotion scene plan schema & builder.

Produces a JSON-serialisable *scene plan* that a Remotion composition can
consume.  This is a pure data transformation — no rendering happens here.

Design
------
- RemotionScenePlan: JSON schema with composition metadata, events array,
  style tokens, and quality warnings.
- build_remotion_scene_plan(): consumes ViraClipTimelinePlan + optional
  safe layout + motion decisions → RemotionScenePlan.
- export_remotion_scene_plan(): writes the plan to a JSON file.
- Respects the "One Strong Thing" rule via visual_priority_guard.
- Respects face-safe zones via vpi_face_safe_layout.
- No filler captions, no duplicated events.

Event type mapping (visual_style → Remotion event types):
  revelation_hook → HookCard / CaptionEmphasis
  paperwork       → DocumentReveal
  advice          → ChecklistReveal
  risk_warning    → WarningBadge
  (default)       → SemanticObject / LowerThird

Integration
-----------
- vpi_overlay_renderer_adapter.py: RemotionAdapter.build_scene_plan() calls
  build_remotion_scene_plan() internally.
- vpi_timeline_plan.py: consumes ViraClipTimelinePlan as input.
- vpi_visual_priority_guard.py: enforces One Strong Thing rule.
- vpi_face_safe_layout.py: provides safe zone positions.
- vpi_motion_grammar.py: provides motion decisions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Visual style → Remotion event type mapping ────────────────────────────────

# Maps a visual_style string to one or more Remotion event types.
# The first event type is the primary; the second is a fallback/companion.
VISUAL_STYLE_EVENT_MAP: Dict[str, List[str]] = {
    "revelation_hook":   ["hook_card", "caption_emphasis"],
    "paperwork":         ["document_reveal"],
    "advice":            ["checklist_reveal"],
    "risk_warning":      ["warning_badge"],
    "serious_warning":   ["warning_badge", "lower_third"],
    "calm_trust":        ["lower_third", "semantic_object"],
    "clear_explanation": ["semantic_object", "caption_emphasis"],
    "practical_advice":  ["checklist_reveal", "semantic_object"],
    "emotional_closure": ["lower_third", "semantic_object"],
}

# ── Visual family → Remotion event type mapping ──────────────────────────────

# Maps a visual_family string to one or more Remotion event types.
# This is used when the asset registry provides a visual_family instead of
# a visual_style string.
_FAMILY_EVENT_MAP: Dict[str, List[str]] = {
    "protection_calm":       ["lower_third", "semantic_object"],
    "serious_warning":       ["warning_badge", "lower_third"],
    "paperwork_clarity":     ["document_reveal", "checklist_reveal"],
    "practical_advice":      ["checklist_reveal", "semantic_object"],
    "revelation_hook":       ["hook_card", "caption_emphasis"],
    "coverage_explanation":  ["semantic_object", "caption_emphasis"],
    "emotional_closure":     ["lower_third", "semantic_object"],
}

# ── Visual family → style token overrides ────────────────────────────────────

# Maps a visual_family to style token overrides (accent_color, background_color,
# primary_color).  These are applied when the asset registry provides a
# visual_family instead of a visual_style string.
_FAMILY_TOKEN_OVERRIDES: Dict[str, Dict[str, str]] = {
    "protection_calm": {
        "accent_color": "#4A90D9",
        "background_color": "#0D1B2A",
        "primary_color": "#FFFFFF",
    },
    "serious_warning": {
        "accent_color": "#FF4444",
        "background_color": "#1A0000",
        "primary_color": "#FFFFFF",
    },
    "paperwork_clarity": {
        "accent_color": "#2ECC71",
        "background_color": "#0D1A0D",
        "primary_color": "#FFFFFF",
    },
    "practical_advice": {
        "accent_color": "#2ECC71",
        "background_color": "#1A2E1A",
        "primary_color": "#FFFFFF",
    },
    "revelation_hook": {
        "accent_color": "#F1C40F",
        "background_color": "#1A1A00",
        "primary_color": "#FFFFFF",
    },
    "coverage_explanation": {
        "accent_color": "#1ABC9C",
        "background_color": "#0D1A1A",
        "primary_color": "#FFFFFF",
    },
    "emotional_closure": {
        "accent_color": "#E040FB",
        "background_color": "#1A0D2E",
        "primary_color": "#FFFFFF",
    },
}

# ── Visual family → entry/exit motion pairs ──────────────────────────────────

# Maps a visual_family to recommended entry_motion and exit_motion strings.
# These correspond to the entry_motion / exit_motion fields in the asset
# registry entries, and are used to populate semantic event metadata.
_FAMILY_MOTION_MAP: Dict[str, Dict[str, str]] = {
    "protection_calm": {
        "entry_motion": "shield_scale_in",
        "exit_motion": "soft_dissolve_out",
    },
    "serious_warning": {
        "entry_motion": "luma_fade_in",
        "exit_motion": "mask_reveal_out",
    },
    "paperwork_clarity": {
        "entry_motion": "document_slide_in",
        "exit_motion": "soft_dissolve_out",
    },
    "practical_advice": {
        "entry_motion": "checklist_step_reveal_in",
        "exit_motion": "soft_dissolve_out",
    },
    "revelation_hook": {
        "entry_motion": "sweep_reveal_in",
        "exit_motion": "luma_fade_out",
    },
    "coverage_explanation": {
        "entry_motion": "document_slide_in",
        "exit_motion": "soft_dissolve_out",
    },
    "emotional_closure": {
        "entry_motion": "pull_back_in",
        "exit_motion": "soft_dissolve_out",
    },
}


# TrackKind → Remotion event type (fallback when visual_style is not mapped)
TRACK_KIND_EVENT_MAP: Dict[str, str] = {
    "OVERLAY_TEXT":    "hook_card",
    "CAPTION_TEXT":    "caption_emphasis",
    "SEMANTIC_OBJECT": "semantic_object",
    "BRANDING":        "lower_third",
    "BROLL":           "broll",
    "TRANSITION":      "transition",
    "MOTION_EFFECT":   "motion_effect",
}


# ── RemotionScenePlan dataclass ───────────────────────────────────────────────


@dataclass
class RemotionScenePlan:
    """A JSON-serialisable scene plan for a Remotion composition.

    Fields
    ------
    schema_version : str
        Version of the scene plan schema (e.g. "1.0").
    composition : dict
        Composition metadata: id, durationInFrames, fps, width, height.
    events : list[dict]
        Ordered list of visual events.  Each event has:
        - event_id, event_type, start (seconds), end (seconds),
          zone (face-safe zone name), metadata.
    style_tokens : dict
        Visual style tokens: visual_style, font_family, primary_color,
        accent_color, background_color.
    quality_warnings : list[str]
        Any quality concerns detected during plan construction.
    """
    schema_version: str = "1.0"
    composition: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    style_tokens: Dict[str, str] = field(default_factory=dict)
    quality_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _infer_zone_from_position(
    position: Tuple[float, float],
) -> str:
    """Infer a face-safe zone name from normalised (0-1) position."""
    x, y = position
    if y < 0.4:
        return "face_zone"
    elif y > 0.7:
        return "caption_zone"
    elif x < 0.4:
        return "object_left_zone"
    elif x > 0.6:
        return "object_right_zone"
    else:
        return "hook_card_zone"


def _is_filler_caption(item: Any) -> bool:
    """Check if a timeline item is a filler caption (not an emphasis).

    Filler captions are CAPTION_TEXT items that:
    - Have no 'emphasis' or 'highlight' in metadata
    - Have short duration (< 0.5s)
    - Are not associated with any visual event
    """
    if not hasattr(item, "track_kind"):
        return False
    kind_name = (
        item.track_kind.name
        if hasattr(item.track_kind, "name")
        else str(item.track_kind)
    )
    if kind_name != "CAPTION_TEXT":
        return False

    meta = getattr(item, "metadata", {}) or {}
    if meta.get("emphasis") or meta.get("highlight"):
        return False

    duration = getattr(item, "time", None)
    if duration and hasattr(duration, "duration"):
        if duration.duration < 0.5:
            return True

    return False


def _is_duplicate_event(
    event: Dict[str, Any],
    existing_events: List[Dict[str, Any]],
    time_threshold: float = 0.5,
) -> bool:
    """Check if an event is a duplicate of an existing event.

    Two events are considered duplicates if they have the same event_type
    and their start times are within `time_threshold` seconds.
    """
    for existing in existing_events:
        if existing["event_type"] != event["event_type"]:
            continue
        if abs(existing["start"] - event["start"]) < time_threshold:
            return True
    return False


# ── Main builder ──────────────────────────────────────────────────────────────


def build_remotion_scene_plan(
    timeline_plan: Any,  # ViraClipTimelinePlan
    visual_style: Optional[str] = None,
    safe_layout: Optional[Any] = None,  # LayoutPlan
    motion_decisions: Optional[List[Any]] = None,  # List[MotionDecision]
    priority_plan: Optional[Any] = None,  # VisualPriorityPlan
    asset_registry: Optional[Dict[str, Any]] = None,  # Dict[str, AssetRegistryEntry]
    asset_tracker: Optional[Any] = None,  # AssetUsageTracker
) -> RemotionScenePlan:
    """Build a RemotionScenePlan from a ViraClipTimelinePlan.

    Args:
        timeline_plan: The source ViraClipTimelinePlan.
        visual_style: Optional visual style string (e.g. "revelation_hook").
        safe_layout: Optional LayoutPlan from vpi_face_safe_layout.
        motion_decisions: Optional list of MotionDecisions from vpi_motion_grammar.
        priority_plan: Optional VisualPriorityPlan from vpi_visual_priority_guard.
        asset_registry: Optional asset registry dict from vpi_animated_asset_registry.
        asset_tracker: Optional AssetUsageTracker for overuse prevention.

    Returns:
        A fully populated RemotionScenePlan.
    """
    clip_id = getattr(timeline_plan, "clip_id", "unknown")
    duration = getattr(timeline_plan, "duration", 10.0)
    fps = getattr(timeline_plan, "fps", 30.0)
    resolution = getattr(timeline_plan, "resolution", (1080, 1920))

    # ── Composition ────────────────────────────────────────────────────────
    composition: Dict[str, Any] = {
        "id": clip_id,
        "durationInFrames": int(duration * fps),
        "fps": fps,
        "width": resolution[0],
        "height": resolution[1],
    }

    # ── Style tokens ───────────────────────────────────────────────────────
    style_tokens: Dict[str, str] = {
        "visual_style": visual_style or "clear_explanation",
        "font_family": "Inter, sans-serif",
        "primary_color": "#FFFFFF",
        "accent_color": "#FFD700",
        "background_color": "#1A1A2E",
    }

    # Override style tokens based on visual_style
    _style_token_overrides: Dict[str, Dict[str, str]] = {
        "revelation_hook": {
            "accent_color": "#FF6B35",
            "primary_color": "#FFFFFF",
        },
        "serious_warning": {
            "accent_color": "#FF4444",
            "background_color": "#1A0000",
        },
        "calm_trust": {
            "accent_color": "#4A90D9",
            "background_color": "#0D1B2A",
        },
        "practical_advice": {
            "accent_color": "#00C853",
            "background_color": "#1A2E1A",
        },
        "emotional_closure": {
            "accent_color": "#E040FB",
            "background_color": "#1A0D2E",
        },
    }
    if visual_style in _style_token_overrides:
        style_tokens.update(_style_token_overrides[visual_style])

    # If visual_style is not set but we have an asset_registry, try to infer
    # from the first segment's intent
    inferred_visual_family: Optional[str] = None
    if visual_style is None and asset_registry:
        # Try to get the first segment's intent from timeline items
        all_items = getattr(timeline_plan, "all_items", lambda: [])()
        for item in all_items:
            meta = getattr(item, "metadata", {}) or {}
            intent = meta.get("intent", "")
            if intent:
                # Look up the intent in the asset registry to find a visual family
                from vpi_animated_asset_registry import get_assets_by_intent
                matching = get_assets_by_intent(intent, asset_registry)
                if matching:
                    inferred_visual_family = matching[0].visual_family
                    break

    # Apply family token overrides if we have an inferred visual family
    if inferred_visual_family and inferred_visual_family in _FAMILY_TOKEN_OVERRIDES:
        style_tokens.update(_FAMILY_TOKEN_OVERRIDES[inferred_visual_family])
        style_tokens["visual_family"] = inferred_visual_family


    # ── Build events ───────────────────────────────────────────────────────
    events: List[Dict[str, Any]] = []
    quality_warnings: List[str] = []
    object_registry_3d: Dict[str, Any] = {}
    map_visual_asset_to_3d_candidate = None
    try:
        from .vpi_3d_object_registry import (
            load_3d_object_registry as _load_3d_object_registry,
            map_visual_asset_to_3d_candidate as _map_visual_asset_to_3d_candidate,
        )
        object_registry_3d = _load_3d_object_registry()
        map_visual_asset_to_3d_candidate = _map_visual_asset_to_3d_candidate
    except Exception:
        try:
            from vpi_3d_object_registry import (  # type: ignore
                load_3d_object_registry as _load_3d_object_registry,
                map_visual_asset_to_3d_candidate as _map_visual_asset_to_3d_candidate,
            )
            object_registry_3d = _load_3d_object_registry()
            map_visual_asset_to_3d_candidate = _map_visual_asset_to_3d_candidate
        except Exception:
            object_registry_3d = {}
            map_visual_asset_to_3d_candidate = None

    # Determine which event types to use based on visual_style
    preferred_event_types = VISUAL_STYLE_EVENT_MAP.get(
        visual_style or "",
        ["semantic_object", "caption_emphasis"],
    )

    # Collect all items from the timeline plan
    all_items = getattr(timeline_plan, "all_items", lambda: [])()
    if not all_items:
        quality_warnings.append("No items found in timeline plan")

    # Build events from timeline items, respecting One Strong Thing rule
    for item in all_items:
        # Skip filler captions
        if _is_filler_caption(item):
            continue

        kind_name = (
            item.track_kind.name
            if hasattr(item.track_kind, "name")
            else str(item.track_kind)
        )

        # Determine event type
        event_type = TRACK_KIND_EVENT_MAP.get(kind_name)

        # If we have a preferred event type for this visual_style, use it
        # for OVERLAY_TEXT and CAPTION_TEXT items
        if kind_name in ("OVERLAY_TEXT", "CAPTION_TEXT") and preferred_event_types:
            # Map visual_style to specific event types
            if visual_style == "revelation_hook" and kind_name == "OVERLAY_TEXT":
                event_type = "hook_card"
            elif visual_style == "revelation_hook" and kind_name == "CAPTION_TEXT":
                event_type = "caption_emphasis"
            elif visual_style in ("paperwork",) and kind_name == "OVERLAY_TEXT":
                event_type = "document_reveal"
            elif visual_style in ("advice", "practical_advice") and kind_name == "OVERLAY_TEXT":
                event_type = "checklist_reveal"
            elif visual_style in ("risk_warning", "serious_warning") and kind_name == "OVERLAY_TEXT":
                event_type = "warning_badge"

        if event_type is None:
            continue

        # Determine position and zone
        position = getattr(item, "position", (0.5, 0.5))
        zone = _infer_zone_from_position(position)

        # If safe_layout is provided, use its zone assignments
        if safe_layout is not None:
            layout_zones = getattr(safe_layout, "zones", [])
            for sz in layout_zones:
                if getattr(sz, "occupied", False) and getattr(sz, "occupant", None):
                    zone = sz.zone.name.lower() if hasattr(sz.zone, "name") else str(sz.zone)

        time_range = getattr(item, "time", None)
        start = getattr(time_range, "start", 0.0)
        end = getattr(time_range, "end", duration)

        # ── Asset registry integration ──────────────────────────────────────
        # Select a premium visual asset for this segment if the item has an
        # editorial intent and we have an asset_registry + tracker.
        asset_meta: Dict[str, Any] = {}
        item_meta = getattr(item, "metadata", {}) or {}
        item_intent = item_meta.get("intent", "")
        if item_intent and asset_registry and asset_tracker is not None:
            try:
                from vpi_animated_asset_registry import select_asset_for_segment
                segment_context = item_meta.get("context", "")
                selected = select_asset_for_segment(
                    intent=item_intent,
                    assets=asset_registry,
                    tracker=asset_tracker,
                    visual_style=visual_style,
                    segment_context=segment_context,
                )
                if selected:
                    # Determine entry/exit motion from family map or asset
                    family_motion = _FAMILY_MOTION_MAP.get(
                        selected.visual_family, {}
                    )
                    entry_motion = selected.entry_motion or family_motion.get(
                        "entry_motion", "fade_in"
                    )
                    exit_motion = selected.exit_motion or family_motion.get(
                        "exit_motion", "fade_out"
                    )

                    asset_meta = {
                        "visual_family": selected.visual_family,
                        "asset_id": selected.asset_id,
                        "asset_name": selected.name,
                        "static_svg_path": selected.static_svg_path,
                        "lottie_future_path": selected.lottie_future_path,
                        "remotion_component": selected.remotion_component,
                        "entry_motion": entry_motion,
                        "exit_motion": exit_motion,
                        "clarity_gain_score": selected.clarity_gain_score,
                        "brand_fit_score": selected.brand_fit_score,
                        "spoken_anchor": item_meta.get("spoken_anchor", ""),
                        "fallback_used": False,
                    }
                    # Optional 3D bridge: map selected 2D asset to a 3D candidate.
                    if map_visual_asset_to_3d_candidate and object_registry_3d:
                        try:
                            object_3d = map_visual_asset_to_3d_candidate(
                                selected.asset_id,
                                object_registry_3d,
                            )
                            if object_3d:
                                object_3d_format = "symbolic"
                                formats = list(getattr(object_3d, "formats_available", []) or [])
                                if "remotion_component" in formats:
                                    object_3d_format = "remotion_component"
                                elif formats:
                                    object_3d_format = str(formats[0])
                                asset_meta.update(
                                    {
                                        "object_3d_id": str(getattr(object_3d, "object_id", "") or ""),
                                        "object_3d_format": object_3d_format,
                                        "object_3d_depth_style": str(getattr(object_3d, "depth_style", "") or ""),
                                        "object_3d_motion": str(getattr(object_3d, "preferred_motion", "") or ""),
                                        "object_3d_fallback_used": object_3d_format != "remotion_component",
                                        "object_3d_license_source": str(getattr(object_3d, "license_source", "") or ""),
                                        "object_3d_attribution_required": bool(getattr(object_3d, "attribution_required", False)),
                                    }
                                )
                        except Exception:
                            logger.debug("[remotion-scene-plan] 3D mapping skipped", exc_info=True)
                    logger.info(
                        "[remotion-scene-plan] Selected asset %s for event %s "
                        "(intent=%s, family=%s)",
                        selected.asset_id,
                        getattr(item, "item_id", "unknown"),
                        item_intent,
                        selected.visual_family,
                    )
            except Exception:
                logger.warning(
                    "[remotion-scene-plan] Asset selection failed for intent=%s",
                    item_intent,
                    exc_info=True,
                )

        event: Dict[str, Any] = {
            "event_id": getattr(item, "item_id", f"{clip_id}_event_{len(events)}"),
            "event_type": event_type,
            "start": start,
            "end": end,
            "zone": zone,
            "metadata": {
                "track_kind": kind_name,
                "opacity": getattr(item, "opacity", 1.0),
                "scale": list(getattr(item, "scale", (1.0, 1.0))),
                "source": "timeline_plan",
                **asset_meta,  # Merge asset registry fields into metadata
            },
        }
        if asset_meta.get("object_3d_id"):
            event["event_type"] = "semantic_object_3d"

        # Skip duplicate events
        if _is_duplicate_event(event, events):
            continue

        events.append(event)

    # ── Apply One Strong Thing rule via priority plan ──────────────────────
    if priority_plan is not None:
        resolved_events = getattr(priority_plan, "events", [])
        if resolved_events:
            # Rebuild events list from resolved priority events
            resolved_ids = {e.event_id for e in resolved_events}
            events = [e for e in events if e["event_id"] in resolved_ids]
            for warning in getattr(priority_plan, "warnings", []):
                quality_warnings.append(f"[priority-guard] {warning}")

    # ── Add motion decisions as events ─────────────────────────────────────
    if motion_decisions:
        for md in motion_decisions:
            primitive_name = (
                md.primitive.name
                if hasattr(md.primitive, "name")
                else str(md.primitive)
            )
            motion_event: Dict[str, Any] = {
                "event_id": f"{clip_id}_motion_{primitive_name}_{md.start_time:.2f}",
                "event_type": "motion_effect",
                "start": md.start_time,
                "end": md.end_time,
                "zone": "full_frame",
                "metadata": {
                    "primitive": primitive_name,
                    "scale_start": md.scale_start,
                    "scale_end": md.scale_end,
                    "easing": md.easing,
                    "reason": md.reason,
                    "source": "motion_grammar",
                },
            }
            if not _is_duplicate_event(motion_event, events):
                events.append(motion_event)

    # ── Sort events by start time ──────────────────────────────────────────
    events.sort(key=lambda e: e["start"])

    # ── Quality checks ─────────────────────────────────────────────────────
    # Check for empty events
    if not events:
        quality_warnings.append("No events generated for scene plan")

    # Check for One Strong Thing violations (more than 1 high-priority event
    # in any 4-second window)
    _check_one_strong_thing(events, quality_warnings)

    # Check for events outside clip duration
    for event in events:
        if event["end"] > duration:
            quality_warnings.append(
                f"Event {event['event_id']} ends at {event['end']:.2f}s "
                f"but clip duration is {duration:.2f}s"
            )

    # ── Build plan ─────────────────────────────────────────────────────────
    plan = RemotionScenePlan(
        schema_version="1.0",
        composition=composition,
        events=events,
        style_tokens=style_tokens,
        quality_warnings=quality_warnings,
    )

    return plan


# ── One Strong Thing check ────────────────────────────────────────────────────


def _check_one_strong_thing(
    events: List[Dict[str, Any]],
    warnings: List[str],
    window_size: float = 4.0,
) -> None:
    """Check that no more than one high-priority event overlaps in a window.

    High-priority event types: hook_card, caption_emphasis, document_reveal,
    checklist_reveal, warning_badge.
    """
    high_priority_types = {
        "hook_card", "caption_emphasis", "document_reveal",
        "checklist_reveal", "warning_badge",
    }

    sorted_events = sorted(events, key=lambda e: e["start"])
    max_time = max((e["end"] for e in sorted_events), default=0.0)
    window_start = 0.0

    while window_start < max_time:
        window_end = window_start + window_size
        window_events = [
            e for e in sorted_events
            if e["start"] < window_end and e["end"] > window_start
            and e["event_type"] in high_priority_types
        ]
        if len(window_events) > 1:
            warnings.append(
                f"[one-strong-thing] Window {window_start:.1f}s-{window_end:.1f}s "
                f"has {len(window_events)} high-priority events: "
                f"{', '.join(e['event_type'] for e in window_events)}"
            )
        window_start += 1.0


# ── Export ─────────────────────────────────────────────────────────────────────


def export_remotion_scene_plan(
    plan: RemotionScenePlan,
    path: str,
) -> str:
    """Export a RemotionScenePlan to a JSON file.

    Args:
        plan: The scene plan to export.
        path: File path to write to.

    Returns:
        The path that was written to.
    """
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w") as f:
        json.dump(plan.to_dict(), f, indent=2, default=str)

    logger.info(
        "[remotion-scene-plan] Exported scene plan to %s (%d events, %d warnings)",
        path,
        len(plan.events),
        len(plan.quality_warnings),
    )
    return path


# ── Convenience: build + export ────────────────────────────────────────────────


def build_and_export_remotion_scene_plan(
    timeline_plan: Any,
    output_path: str,
    visual_style: Optional[str] = None,
    safe_layout: Optional[Any] = None,
    motion_decisions: Optional[List[Any]] = None,
    priority_plan: Optional[Any] = None,
    asset_registry: Optional[Dict[str, Any]] = None,
    asset_tracker: Optional[Any] = None,
) -> RemotionScenePlan:
    """Build and export a RemotionScenePlan in one call.

    Returns the plan (already exported to output_path).
    """
    plan = build_remotion_scene_plan(
        timeline_plan=timeline_plan,
        visual_style=visual_style,
        safe_layout=safe_layout,
        motion_decisions=motion_decisions,
        priority_plan=priority_plan,
        asset_registry=asset_registry,
        asset_tracker=asset_tracker,
    )
    export_remotion_scene_plan(plan, output_path)
    return plan
