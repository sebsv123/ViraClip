"""
vpi_3d_object_registry.py — VPI Premium 3D Object Registry Service.

Defines and manages a registry of 3D/2.5D objects for the VPI visual identity.
Supports real 3D assets (future), pseudo-3D cards/objects (now), static/SVG
fallback, and Remotion component fallback.

Design
------
- Pure data: no rendering, no file I/O beyond loading the JSON registry.
- Fallback chain: 3D object → pseudo-3D SVG → 2D animated asset → no asset.
- Brand safety: prohibited_contexts, brand_fit_score >= 0.7, clarity_gain >= 0.5.
- One Strong Thing: hero_3d_object counts as primary visual element.
- No generic decorative objects: every 3D object must clarify an insurance concept.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

MIN_BRAND_FIT_SCORE = 0.7
MIN_CLARITY_GAIN_SCORE = 0.5
DEFAULT_MAX_USES_PER_CLIP = 2
MAX_HERO_OBJECTS_PER_CLIP = 1
MAX_SMALL_BADGES_PER_CLIP = 2
MIN_SECONDS_BETWEEN_3D_OBJECTS = 8.0

# ── Enums / type aliases ──────────────────────────────────────────────────────

USE_AS_TYPES = {
    "hero_object",
    "small_badge",
    "background_depth",
    "transition_object",
    "document_object",
}

FORMATS_AVAILABLE = {
    "glb",
    "gltf",
    "webm_alpha",
    "png_sequence",
    "remotion_component",
    "pseudo_3d_svg",
    "static_svg",
    "symbolic",
}

DEPTH_STYLES = {
    "soft_3d",
    "clay",
    "glassmorphism",
    "clean_corporate",
    "low_poly",
}


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class VPI3DObject:
    """A single 3D object entry in the registry."""
    object_id: str
    name: str
    visual_family: str
    category: str
    allowed_intents: List[str]
    allowed_visual_styles: List[str]
    prohibited_contexts: List[str]
    tone: str
    intensity: float
    brand_fit_score: float
    clarity_gain_score: float
    use_as: List[str]
    formats_available: List[str]
    file_paths: Dict[str, str]
    fallback_2d_asset_id: str
    remotion_component: str = ""
    preferred_motion: str = "subtle_float"
    entry_animation: str = "fade_in_scale_up"
    exit_animation: str = "fade_out_scale_down"
    max_duration_frames: int = 90
    safe_area_preference: str = "object_left_zone"
    depth_style: str = "clean_corporate"
    license_source: str = ""
    license_type: str = ""
    attribution_required: bool = False
    notes: str = ""


@dataclass
class VPI3DObjectCandidate:
    """A candidate 3D object for a specific segment."""
    object_id: str
    name: str
    visual_family: str
    category: str
    use_as: str
    format_used: str
    depth_style: str
    brand_fit_score: float
    clarity_gain_score: float
    fallback_2d_asset_id: str
    remotion_component: str
    preferred_motion: str
    entry_animation: str
    exit_animation: str
    max_duration_frames: int
    safe_area_preference: str
    license_source: str
    license_type: str
    attribution_required: bool
    score: float = 0.0


@dataclass
class VPI3DObjectSelectionResult:
    """Result of selecting a 3D object for a segment."""
    selected: bool
    candidate: Optional[VPI3DObjectCandidate] = None
    fallback_used: bool = False
    fallback_2d_asset_id: str = ""
    status: str = "skipped"
    reason: str = ""
    clarity_gain_score: float = 0.0
    brand_fit_score: float = 0.0


# ── Registry loading ───────────────────────────────────────────────────────────


def load_3d_object_registry(
    registry_path: Optional[Path] = None,
) -> Dict[str, VPI3DObject]:
    """Load the 3D object registry from a JSON file.

    Args:
        registry_path: Path to the JSON registry file. If None, uses default.

    Returns:
        Dict mapping object_id -> VPI3DObject.
    """
    if registry_path is None:
        repo_root = Path(__file__).resolve().parents[3]
        registry_path = repo_root / "assets" / "vpi_3d_object_registry.json"

    if not registry_path.exists():
        logger.warning(
            "[3d-registry] Registry file not found at %s — returning empty",
            registry_path,
        )
        return {}

    try:
        with open(registry_path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning("[3d-registry] Invalid JSON: %s — returning empty", e)
        return {}

    objects: Dict[str, VPI3DObject] = {}
    for raw in data.get("objects", []):
        try:
            obj = VPI3DObject(
                object_id=raw.get("object_id", ""),
                name=raw.get("name", ""),
                visual_family=raw.get("visual_family", ""),
                category=raw.get("category", ""),
                allowed_intents=raw.get("allowed_intents", []),
                allowed_visual_styles=raw.get("allowed_visual_styles", []),
                prohibited_contexts=raw.get("prohibited_contexts", []),
                tone=raw.get("tone", ""),
                intensity=float(raw.get("intensity", 0.5)),
                brand_fit_score=float(raw.get("brand_fit_score", 0.0)),
                clarity_gain_score=float(raw.get("clarity_gain_score", 0.0)),
                use_as=raw.get("use_as", []),
                formats_available=raw.get("formats_available", []),
                file_paths=raw.get("file_paths", {}),
                fallback_2d_asset_id=raw.get("fallback_2d_asset_id", ""),
                remotion_component=raw.get("remotion_component", ""),
                preferred_motion=raw.get("preferred_motion", "subtle_float"),
                entry_animation=raw.get("entry_animation", "fade_in_scale_up"),
                exit_animation=raw.get("exit_animation", "fade_out_scale_down"),
                max_duration_frames=int(raw.get("max_duration_frames", 90)),
                safe_area_preference=raw.get("safe_area_preference", "object_left_zone"),
                depth_style=raw.get("depth_style", "clean_corporate"),
                license_source=raw.get("license_source", ""),
                license_type=raw.get("license_type", ""),
                attribution_required=bool(raw.get("attribution_required", False)),
                notes=raw.get("notes", ""),
            )
            objects[obj.object_id] = obj
        except Exception as e:
            logger.warning(
                "[3d-registry] Skipping invalid object '%s': %s",
                raw.get("object_id", "unknown"),
                e,
            )

    logger.info(
        "[3d-registry] Loaded %d objects from %s",
        len(objects), registry_path,
    )
    return objects


# ── Selection logic ────────────────────────────────────────────────────────────


def _score_object_for_segment(
    obj: VPI3DObject,
    intent: str,
    visual_style: str,
    spoken_anchor: Optional[str] = None,
    active_layers: Optional[List[str]] = None,
) -> float:
    """Score a 3D object for a given segment context.

    Returns a score 0.0-1.0. Higher is better.
    """
    score = 0.0

    # Intent match (highest weight)
    if intent in obj.allowed_intents:
        score += 0.4
    elif any(intent.startswith(ai) for ai in obj.allowed_intents):
        score += 0.2

    # Visual style match (strict: if style not allowed, score is 0)
    if visual_style not in obj.allowed_visual_styles:
        return 0.0
    score += 0.2

    # Brand fit
    score += obj.brand_fit_score * 0.15

    # Clarity gain
    score += obj.clarity_gain_score * 0.15

    # Spoken anchor bonus
    if spoken_anchor and obj.name.lower() in spoken_anchor.lower():
        score += 0.1

    # Active layers penalty (avoid clutter)
    if active_layers:
        if "hook_card" in active_layers and "hero_object" in obj.use_as:
            score -= 0.15
        if "semantic_object" in active_layers and "hero_object" in obj.use_as:
            score -= 0.1

    return max(0.0, min(1.0, score))


def _check_brand_safety_3d(
    obj: VPI3DObject,
    segment_context: Optional[str] = None,
    segment_intent: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """Check brand safety for a 3D object.

    Returns (is_safe, reasons).
    """
    reasons: List[str] = []

    # Rule 1: Prohibited contexts
    if segment_context:
        for prohibited in obj.prohibited_contexts:
            if prohibited.lower() in segment_context.lower():
                reasons.append(
                    f"Context '{segment_context}' matches prohibited context "
                    f"'{prohibited}' for object '{obj.object_id}'"
                )

    # Rule 2: Brand fit score
    if obj.brand_fit_score < MIN_BRAND_FIT_SCORE:
        reasons.append(
            f"brand_fit_score={obj.brand_fit_score} < {MIN_BRAND_FIT_SCORE} "
            f"for object '{obj.object_id}'"
        )

    # Rule 3: Clarity gain score
    if obj.clarity_gain_score < MIN_CLARITY_GAIN_SCORE:
        reasons.append(
            f"clarity_gain_score={obj.clarity_gain_score} < {MIN_CLARITY_GAIN_SCORE} "
            f"for object '{obj.object_id}'"
        )

    is_safe = len(reasons) == 0
    if not is_safe:
        logger.info(
            "[3d-registry] Brand safety FAIL for %s: %s",
            obj.object_id, "; ".join(reasons),
        )
    return is_safe, reasons


def select_3d_object(
    intent: str,
    visual_style: str,
    objects: Dict[str, VPI3DObject],
    *,
    category: Optional[str] = None,
    spoken_anchor: Optional[str] = None,
    available_formats: Optional[List[str]] = None,
    active_layers: Optional[List[str]] = None,
    segment_context: Optional[str] = None,
    preferred_use_as: Optional[str] = None,
) -> VPI3DObjectSelectionResult:
    """Select the best 3D object for a given segment context.

    Args:
        intent: The editorial intent for this segment.
        visual_style: The visual style for this segment.
        objects: The full 3D object registry dict.
        category: Optional category filter.
        spoken_anchor: Optional spoken anchor text for relevance scoring.
        available_formats: Optional list of available formats to filter by.
        active_layers: Optional list of active visual layers.
        segment_context: Optional context string for brand safety.
        preferred_use_as: Optional preferred use_as type.

    Returns:
        VPI3DObjectSelectionResult with selection status.
    """
    if not objects:
        return VPI3DObjectSelectionResult(
            selected=False,
            status="unavailable",
            reason="No 3D objects in registry",
        )

    # Score all candidates
    scored: List[Tuple[float, VPI3DObject]] = []
    for obj in objects.values():
        # Filter by category if specified
        if category and obj.category != category:
            continue

        # Filter by available formats if specified
        if available_formats:
            if not any(fmt in obj.formats_available for fmt in available_formats):
                continue

        # Filter by preferred use_as if specified
        if preferred_use_as and preferred_use_as not in obj.use_as:
            continue

        # Brand safety check
        is_safe, _ = _check_brand_safety_3d(
            obj, segment_context=segment_context, segment_intent=intent,
        )
        if not is_safe:
            continue

        score = _score_object_for_segment(
            obj, intent, visual_style,
            spoken_anchor=spoken_anchor,
            active_layers=active_layers,
        )
        if score > 0:
            scored.append((score, obj))

    if not scored:
        return VPI3DObjectSelectionResult(
            selected=False,
            status="skipped_no_match",
            reason="No 3D object matched the segment context",
        )

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_obj = scored[0]

    # Determine the best format to use
    format_used = "static_svg"  # default fallback
    if best_obj.formats_available:
        format_priority = [
            "glb", "gltf", "webm_alpha", "png_sequence",
            "remotion_component", "pseudo_3d_svg", "static_svg", "symbolic",
        ]
        for fmt in format_priority:
            if fmt in best_obj.formats_available:
                format_used = fmt
                break

    # Determine use_as
    use_as = preferred_use_as or best_obj.use_as[0] if best_obj.use_as else "hero_object"

    candidate = VPI3DObjectCandidate(
        object_id=best_obj.object_id,
        name=best_obj.name,
        visual_family=best_obj.visual_family,
        category=best_obj.category,
        use_as=use_as,
        format_used=format_used,
        depth_style=best_obj.depth_style,
        brand_fit_score=best_obj.brand_fit_score,
        clarity_gain_score=best_obj.clarity_gain_score,
        fallback_2d_asset_id=best_obj.fallback_2d_asset_id,
        remotion_component=best_obj.remotion_component,
        preferred_motion=best_obj.preferred_motion,
        entry_animation=best_obj.entry_animation,
        exit_animation=best_obj.exit_animation,
        max_duration_frames=best_obj.max_duration_frames,
        safe_area_preference=best_obj.safe_area_preference,
        license_source=best_obj.license_source,
        license_type=best_obj.license_type,
        attribution_required=best_obj.attribution_required,
        score=best_score,
    )

    # Determine if fallback is needed
    fallback_used = format_used in ("static_svg", "symbolic", "pseudo_3d_svg")
    status = "planned"
    if fallback_used:
        status = "fallback_2d"

    logger.info(
        "[3d-registry] Selected object=%s for intent=%s style=%s "
        "score=%.2f format=%s fallback=%s",
        best_obj.object_id, intent, visual_style,
        best_score, format_used, fallback_used,
    )

    return VPI3DObjectSelectionResult(
        selected=True,
        candidate=candidate,
        fallback_used=fallback_used,
        fallback_2d_asset_id=best_obj.fallback_2d_asset_id,
        status=status,
        reason=f"Selected {best_obj.object_id} ({format_used})",
        clarity_gain_score=best_obj.clarity_gain_score,
        brand_fit_score=best_obj.brand_fit_score,
    )


# ── Fallback to 2D asset ───────────────────────────────────────────────────────


def fallback_to_2d_asset(
    object_id: str,
    objects: Dict[str, VPI3DObject],
) -> Optional[str]:
    """Get the 2D fallback asset ID for a 3D object.

    Args:
        object_id: The 3D object ID.
        objects: The full 3D object registry dict.

    Returns:
        The 2D asset ID to fall back to, or None.
    """
    obj = objects.get(object_id)
    if obj is None:
        return None
    return obj.fallback_2d_asset_id or None


# ── Validation ─────────────────────────────────────────────────────────────────


def validate_3d_object_context(
    object_id: str,
    objects: Dict[str, VPI3DObject],
    *,
    intent: Optional[str] = None,
    visual_style: Optional[str] = None,
    active_layers: Optional[List[str]] = None,
    segment_context: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """Validate whether a 3D object is appropriate for a given context.

    Returns (is_valid, reasons).
    """
    reasons: List[str] = []
    obj = objects.get(object_id)
    if obj is None:
        return False, [f"Object '{object_id}' not found in registry"]

    # Brand safety
    is_safe, safety_reasons = _check_brand_safety_3d(
        obj, segment_context=segment_context, segment_intent=intent,
    )
    if not is_safe:
        reasons.extend(safety_reasons)

    # Intent check
    if intent and intent not in obj.allowed_intents:
        reasons.append(
            f"Intent '{intent}' not in allowed_intents for '{object_id}'"
        )

    # Visual style check
    if visual_style and visual_style not in obj.allowed_visual_styles:
        reasons.append(
            f"Visual style '{visual_style}' not in allowed_visual_styles "
            f"for '{object_id}'"
        )

    # Active layers check (avoid clutter)
    if active_layers:
        if "hook_card" in active_layers and "hero_object" in obj.use_as:
            reasons.append(
                "hero_3d_object conflicts with active hook_card layer"
            )
        if "semantic_object" in active_layers and "hero_object" in obj.use_as:
            reasons.append(
                "hero_3d_object conflicts with active semantic_object layer"
            )

    is_valid = len(reasons) == 0
    return is_valid, reasons


# ── Integration helpers ────────────────────────────────────────────────────────


def get_2d_fallback_for_3d_object(
    object_id: str,
    objects: Dict[str, VPI3DObject],
) -> Optional[str]:
    """Get the 2D fallback asset ID for a 3D object.

    This is the integration point with vpi_animated_asset_registry.
    """
    return fallback_to_2d_asset(object_id, objects)


def map_visual_asset_to_3d_candidate(
    asset_id: str,
    objects: Dict[str, VPI3DObject],
) -> Optional[VPI3DObject]:
    """Map a 2D animated asset ID to a 3D candidate.

    Searches the 3D registry for objects whose fallback_2d_asset_id
    matches the given asset_id.

    Args:
        asset_id: The 2D animated asset ID.
        objects: The full 3D object registry dict.

    Returns:
        The matching VPI3DObject, or None.
    """
    for obj in objects.values():
        if obj.fallback_2d_asset_id == asset_id:
            return obj
    return None


def get_objects_by_family(
    visual_family: str,
    objects: Dict[str, VPI3DObject],
) -> List[VPI3DObject]:
    """Get all 3D objects for a given visual family."""
    return [
        obj for obj in objects.values()
        if obj.visual_family == visual_family
    ]


def get_objects_by_category(
    category: str,
    objects: Dict[str, VPI3DObject],
) -> List[VPI3DObject]:
    """Get all 3D objects for a given category."""
    return [
        obj for obj in objects.values()
        if obj.category == category
    ]


def get_objects_by_intent(
    intent: str,
    objects: Dict[str, VPI3DObject],
) -> List[VPI3DObject]:
    """Get all 3D objects that support a given intent."""
    return [
        obj for obj in objects.values()
        if intent in obj.allowed_intents
    ]
