"""
vpi_editly_exporter.py — Export a ViraClipTimelinePlan to Editly JSON format.

Editly (https://github.com/mifi/editly) is a declarative video editing tool
that consumes a JSON spec.  This module converts a ViraClipTimelinePlan into
an Editly-compatible JSON spec for *export only* — no Editly execution happens
here.

Design
------
- export_timeline_to_editly_json(timeline_plan) → dict
- Maps ViraClip timeline concepts to Editly concepts:
    speaker clips     → clips[]
    broll             → clips[] / layers[]
    captions          → clips[].layers[].type: "title"
    transitions       → clips[].transition
    bgm               → clips[].audio
    sfx               → clips[].audio (overlay)
    semantic objects  → unsupported (noted in metadata)
    motion effects    → unsupported (noted in metadata)

Editly JSON structure (simplified):
{
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "clips": [
    {
      "duration": 5.0,
      "layers": [
        { "type": "video", "path": "..." },
        { "type": "title", "text": "...", "position": "bottom" }
      ],
      "transition": { "name": "fade", "duration": 0.5 },
      "audio": { "path": "...", "mix": 0.5 }
    }
  ],
  "audioTracks": [...]
}

Integration
-----------
- vpi_timeline_plan.py: consumes ViraClipTimelinePlan as input.
- editing_pipeline.py: can optionally export to Editly for external rendering.
- No Editly execution — this is a pure data transformation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── TrackKind → Editly layer type mapping ───────────────────────────────────────

# Maps ViraClip TrackKind names to Editly layer types.
# Unsupported types are marked as "unsupported" and noted in metadata.
TRACK_KIND_EDITLY_MAP: Dict[str, str] = {
    "SPEAKER_VIDEO": "video",
    "BROLL": "video",
    "CAPTION_TEXT": "title",
    "OVERLAY_TEXT": "title",
    "BRANDING": "image",
    "BACKGROUND_COLOR": "color",
    "CAPTION_BG": "color",
    "TRANSITION": "transition_hint",
    "SFX": "audio_overlay",
    "BGM": "audio",
    "SEMANTIC_OBJECT": "unsupported",
    "MOTION_EFFECT": "unsupported",
    "CINEMATIC_FINISH": "unsupported",
}


# ── Editly transition name mapping ──────────────────────────────────────────────

# Maps ViraClip transition names to Editly transition names.
EDITLY_TRANSITION_MAP: Dict[str, str] = {
    "fade": "fade",
    "crossfade": "fade",
    "dissolve": "fade",
    "slide_left": "slide-left",
    "slide_right": "slide-right",
    "slide_up": "slide-up",
    "slide_down": "slide-down",
    "zoom_in": "zoom-in",
    "zoom_out": "zoom-out",
    "glitch": "fade",  # No glitch in Editly; fallback to fade
    "wipe_left": "wipe-left",
    "wipe_right": "wipe-right",
    "radial": "fade",  # No radial in Editly; fallback to fade
}


# ── Position mapping ────────────────────────────────────────────────────────────

# Maps normalised y-position to Editly title position.
def _map_position_to_editly(position_y: float) -> str:
    """Map a normalised y-position to an Editly title position."""
    if position_y < 0.33:
        return "top"
    elif position_y < 0.66:
        return "center"
    else:
        return "bottom"


# ── Main export function ────────────────────────────────────────────────────────


def export_timeline_to_editly_json(
    timeline_plan: Any,  # ViraClipTimelinePlan
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a ViraClipTimelinePlan to an Editly-compatible JSON spec.

    Args:
        timeline_plan: The source ViraClipTimelinePlan.
        output_path: Optional file path to write the JSON spec.

    Returns:
        An Editly-compatible JSON dict.

    Notes
    -----
    - Semantic objects and motion effects are NOT supported by Editly.
      They are noted in the returned dict's "unsupported_notes" field.
    - Transitions are mapped to Editly's built-in transition names.
      Unsupported transitions fall back to "fade".
    - Audio tracks (BGM, SFX) are mapped to Editly's audioTracks array.
    """
    clip_id = getattr(timeline_plan, "clip_id", "unknown")
    duration = getattr(timeline_plan, "duration", 10.0)
    fps = getattr(timeline_plan, "fps", 30.0)
    resolution = getattr(timeline_plan, "resolution", (1080, 1920))

    editly_spec: Dict[str, Any] = {
        "width": resolution[0],
        "height": resolution[1],
        "fps": fps,
        "clips": [],
        "audioTracks": [],
        "unsupported_notes": [],
        "metadata": {
            "source": "vpi_editly_exporter",
            "clip_id": clip_id,
            "original_duration": duration,
        },
    }

    # Collect all items from the timeline plan
    all_items = getattr(timeline_plan, "all_items", lambda: [])()
    if not all_items:
        logger.warning(
            "[editly-exporter] No items found in timeline plan %s",
            clip_id,
        )
        return editly_spec

    # Sort items by start time
    all_items.sort(key=lambda i: getattr(getattr(i, "time", None), "start", 0.0))

    # ── Build clips ─────────────────────────────────────────────────────────
    current_clip: Optional[Dict[str, Any]] = None
    clip_start_time: float = 0.0

    for item in all_items:
        kind_name = (
            item.track_kind.name
            if hasattr(item.track_kind, "name")
            else str(item.track_kind)
        )
        editly_type = TRACK_KIND_EDITLY_MAP.get(kind_name, "unsupported")

        time_range = getattr(item, "time", None)
        item_start = getattr(time_range, "start", 0.0)
        item_end = getattr(time_range, "end", duration)
        item_duration = item_end - item_start

        # Handle unsupported types
        if editly_type == "unsupported":
            editly_spec["unsupported_notes"].append(
                f"Item '{getattr(item, 'item_id', 'unknown')}' "
                f"of type '{kind_name}' is not supported by Editly. "
                f"Time: {item_start:.2f}s-{item_end:.2f}s"
            )
            continue

        # Handle audio tracks (BGM, SFX)
        if editly_type in ("audio", "audio_overlay"):
            source = getattr(item, "source", None)
            path = getattr(source, "path", "") if source else ""
            if path:
                audio_entry: Dict[str, Any] = {
                    "path": path,
                    "start": item_start,
                    "duration": item_duration,
                    "volume": getattr(item, "volume", 1.0),
                }
                if editly_type == "audio_overlay":
                    audio_entry["mix"] = 0.3  # Lower volume for SFX
                editly_spec["audioTracks"].append(audio_entry)
            continue

        # Handle transition hints
        if editly_type == "transition_hint":
            if current_clip is not None:
                meta = getattr(item, "metadata", {}) or {}
                transition_name = meta.get("transition", "fade")
                editly_transition = EDITLY_TRANSITION_MAP.get(
                    transition_name, "fade"
                )
                current_clip["transition"] = {
                    "name": editly_transition,
                    "duration": meta.get("duration", 0.5),
                }
            continue

        # Create a new clip if needed (time gap or different video source)
        if current_clip is None or _should_start_new_clip(
            current_clip, item, kind_name, clip_start_time, item_start
        ):
            if current_clip is not None:
                # Finalise previous clip duration
                current_clip["duration"] = item_start - clip_start_time
                editly_spec["clips"].append(current_clip)

            clip_start_time = item_start
            current_clip = {
                "duration": item_duration,
                "layers": [],
            }

        # Add layer to current clip
        layer = _build_editly_layer(item, kind_name, editly_type)
        if layer is not None:
            current_clip["layers"].append(layer)

    # Finalise the last clip
    if current_clip is not None:
        current_clip["duration"] = duration - clip_start_time
        editly_spec["clips"].append(current_clip)

    # ── Log summary ─────────────────────────────────────────────────────────
    logger.info(
        "[editly-exporter] Exported timeline %s to Editly spec: "
        "%d clips, %d audio tracks, %d unsupported notes",
        clip_id,
        len(editly_spec["clips"]),
        len(editly_spec["audioTracks"]),
        len(editly_spec["unsupported_notes"]),
    )

    # ── Write to file if output_path provided ───────────────────────────────
    if output_path:
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(editly_spec, f, indent=2, default=str)
        logger.info("[editly-exporter] Wrote Editly spec to %s", output_path)

    return editly_spec


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _should_start_new_clip(
    current_clip: Dict[str, Any],
    item: Any,
    kind_name: str,
    clip_start_time: float,
    item_start: float,
) -> bool:
    """Determine if a new clip should be started.

    A new clip is started when:
    1. The item is a SPEAKER_VIDEO or BROLL (new video source).
    2. There's a significant time gap (> 0.5s) since the last clip.
    """
    if kind_name in ("SPEAKER_VIDEO", "BROLL"):
        # Check if the current clip already has a video layer
        has_video = any(
            layer.get("type") == "video"
            for layer in current_clip.get("layers", [])
        )
        if has_video:
            return True

    # Check for time gap
    if item_start - clip_start_time > 0.5:
        return True

    return False


def _build_editly_layer(
    item: Any,
    kind_name: str,
    editly_type: str,
) -> Optional[Dict[str, Any]]:
    """Build an Editly layer dict from a TimelineItem."""
    source = getattr(item, "source", None)
    path = getattr(source, "path", "") if source else ""
    meta = getattr(item, "metadata", {}) or {}
    position = getattr(item, "position", (0.5, 0.5))

    if editly_type == "video":
        if not path:
            return None
        return {
            "type": "video",
            "path": path,
            "resizeMode": "cover",
            "volume": getattr(item, "volume", 1.0),
        }

    elif editly_type == "title":
        text = meta.get("text", "") or meta.get("content", "")
        if not text:
            return None
        return {
            "type": "title",
            "text": text,
            "position": _map_position_to_editly(position[1]),
            "fontPath": meta.get("font_path", ""),
            "fontSize": meta.get("font_size", 36),
            "color": meta.get("color", "#FFFFFF"),
        }

    elif editly_type == "image":
        if not path:
            return None
        return {
            "type": "image",
            "path": path,
            "resizeMode": "contain",
            "position": _map_position_to_editly(position[1]),
        }

    elif editly_type == "color":
        color = meta.get("color", "#1A1A2E")
        return {
            "type": "color",
            "color": color,
        }

    return None


# ── Convenience: export to file ─────────────────────────────────────────────────


def export_timeline_to_editly_file(
    timeline_plan: Any,
    output_path: str,
) -> str:
    """Export a ViraClipTimelinePlan to an Editly JSON file.

    Args:
        timeline_plan: The source ViraClipTimelinePlan.
        output_path: File path to write the Editly JSON spec.

    Returns:
        The output path that was written to.
    """
    export_timeline_to_editly_json(timeline_plan, output_path=output_path)
    return output_path
