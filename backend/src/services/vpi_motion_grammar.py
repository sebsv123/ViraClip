"""
vpi_motion_grammar.py — Motion grammar for ViraClipTimelinePlan.

A lightweight, rule-based motion grammar that selects camera/motion primitives
based on visual style, hook intent, and discourse context.  This is a *planning*
module — it does NOT render anything.  Downstream services (vpi_visual_effects_service,
editing_pipeline) consume MotionDecisions to apply the actual motion effects.

Design
------
- 12 motion primitives covering push/pull, reveal, object emphasis, transitions.
- 6 rules that constrain primitive selection (budget, style compatibility,
  hook-first-3s, no-overlap, density, robotic-cut avoidance).
- Pure data: no FFmpeg, no file I/O.
- Compatible with ViraClipTimelinePlan (MOTION_EFFECT track).

Integration
-----------
- vpi_visual_effects_service.py: consumes MotionDecision → applies motion pack
- vpi_timeline_plan.py: MOTION_EFFECT track items → motion primitives
- vpi_retention_editing_service.py: visual_coherence → motion grammar
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Motion primitives ────────────────────────────────────────────────────────────


class MotionPrimitive(Enum):
    """The 12 motion primitives in the ViraClip motion grammar."""

    # Push / pull
    PUSH_IN = auto()           # Slow zoom in (1.0 → 1.035)
    PULL_BACK = auto()         # Slow zoom out (1.035 → 1.0)

    # Reveal
    SWEEP_REVEAL = auto()      # Horizontal/vertical sweep across frame
    MASK_REVEAL = auto()       # Circular/rectangular mask wipe

    # Object emphasis
    OBJECT_POP_5_10 = auto()   # Brief scale pop (1.0 → 1.1 → 1.0, 5-10 frames)
    CAPTION_BEAT_REVEAL = auto()  # Caption sync: scale + position shift

    # Document / list
    DOCUMENT_SLIDE = auto()    # Slide document/UI element into frame
    CHECKLIST_STEP_REVEAL = auto()  # Step-by-step checklist reveal

    # Shield / protection
    SHIELD_SCALE = auto()      # Scale up a protective element (icon, badge)

    # Transition-adjacent
    SOFT_DISSOLVE = auto()     # Gentle opacity dissolve
    LUMA_FADE = auto()         # Luma-keyed fade (brightness threshold)

    # Micro-motion
    MICRO_SHAKE_SUBTLE = auto()  # Very subtle handheld shake (1-3 px)


# ── Primitive metadata ──────────────────────────────────────────────────────────

PRIMITIVE_META: Dict[MotionPrimitive, Dict[str, Any]] = {
    MotionPrimitive.PUSH_IN: {
        "category": "push_pull",
        "default_duration": 0.4,
        "max_duration": 1.0,
        "scale_range": (1.0, 1.035),
        "compatible_styles": ["calm_trust", "clear_explanation", "practical_advice"],
        "avoid_with": ["aggressive_punch", "glitch"],
    },
    MotionPrimitive.PULL_BACK: {
        "category": "push_pull",
        "default_duration": 0.4,
        "max_duration": 1.0,
        "scale_range": (1.035, 1.0),
        "compatible_styles": ["calm_trust", "emotional_closure"],
        "avoid_with": ["aggressive_boom"],
    },
    MotionPrimitive.SWEEP_REVEAL: {
        "category": "reveal",
        "default_duration": 0.5,
        "max_duration": 1.2,
        "scale_range": None,
        "compatible_styles": ["revelation_hook", "clear_explanation"],
        "avoid_with": ["glitch", "shake"],
    },
    MotionPrimitive.MASK_REVEAL: {
        "category": "reveal",
        "default_duration": 0.6,
        "max_duration": 1.5,
        "scale_range": None,
        "compatible_styles": ["revelation_hook", "serious_warning"],
        "avoid_with": ["glitch"],
    },
    MotionPrimitive.OBJECT_POP_5_10: {
        "category": "emphasis",
        "default_duration": 0.2,
        "max_duration": 0.4,
        "scale_range": (1.0, 1.1),
        "compatible_styles": ["clear_explanation", "practical_advice", "revelation_hook"],
        "avoid_with": ["shake"],
    },
    MotionPrimitive.CAPTION_BEAT_REVEAL: {
        "category": "emphasis",
        "default_duration": 0.3,
        "max_duration": 0.6,
        "scale_range": (1.0, 1.05),
        "compatible_styles": ["clear_explanation", "practical_advice", "revelation_hook"],
        "avoid_with": ["aggressive_punch"],
    },
    MotionPrimitive.DOCUMENT_SLIDE: {
        "category": "ui",
        "default_duration": 0.5,
        "max_duration": 1.0,
        "scale_range": None,
        "compatible_styles": ["clear_explanation", "practical_advice"],
        "avoid_with": ["shake", "glitch"],
    },
    MotionPrimitive.CHECKLIST_STEP_REVEAL: {
        "category": "ui",
        "default_duration": 0.3,
        "max_duration": 0.6,
        "scale_range": None,
        "compatible_styles": ["practical_advice", "clear_explanation"],
        "avoid_with": ["aggressive_impact"],
    },
    MotionPrimitive.SHIELD_SCALE: {
        "category": "protection",
        "default_duration": 0.3,
        "max_duration": 0.6,
        "scale_range": (0.8, 1.0),
        "compatible_styles": ["serious_warning", "calm_trust"],
        "avoid_with": ["glitch", "shake"],
    },
    MotionPrimitive.SOFT_DISSOLVE: {
        "category": "transition",
        "default_duration": 0.4,
        "max_duration": 1.0,
        "scale_range": None,
        "compatible_styles": ["calm_trust", "emotional_closure", "clear_explanation"],
        "avoid_with": ["aggressive_impact"],
    },
    MotionPrimitive.LUMA_FADE: {
        "category": "transition",
        "default_duration": 0.5,
        "max_duration": 1.2,
        "scale_range": None,
        "compatible_styles": ["serious_warning", "revelation_hook"],
        "avoid_with": ["glitch"],
    },
    MotionPrimitive.MICRO_SHAKE_SUBTLE: {
        "category": "micro",
        "default_duration": 0.3,
        "max_duration": 0.8,
        "scale_range": None,
        "compatible_styles": ["serious_warning", "revelation_hook"],
        "avoid_with": ["calm_trust", "emotional_closure"],
    },
}


# ── Visual style → compatible primitives ────────────────────────────────────────

_STYLE_PRIMITIVE_MAP: Dict[str, List[MotionPrimitive]] = {
    "calm_trust": [
        MotionPrimitive.PUSH_IN,
        MotionPrimitive.PULL_BACK,
        MotionPrimitive.SOFT_DISSOLVE,
        MotionPrimitive.SHIELD_SCALE,
    ],
    "protection_calm": [
        MotionPrimitive.PUSH_IN,
        MotionPrimitive.PULL_BACK,
        MotionPrimitive.SOFT_DISSOLVE,
        MotionPrimitive.SHIELD_SCALE,
    ],
    "serious_warning": [
        MotionPrimitive.MASK_REVEAL,
        MotionPrimitive.MICRO_SHAKE_SUBTLE,
        MotionPrimitive.LUMA_FADE,
        MotionPrimitive.SHIELD_SCALE,
    ],
    "clear_explanation": [
        MotionPrimitive.PUSH_IN,
        MotionPrimitive.OBJECT_POP_5_10,
        MotionPrimitive.CAPTION_BEAT_REVEAL,
        MotionPrimitive.DOCUMENT_SLIDE,
        MotionPrimitive.CHECKLIST_STEP_REVEAL,
        MotionPrimitive.SOFT_DISSOLVE,
    ],
    "paperwork_clarity": [
        MotionPrimitive.PUSH_IN,
        MotionPrimitive.DOCUMENT_SLIDE,
        MotionPrimitive.CHECKLIST_STEP_REVEAL,
        MotionPrimitive.SOFT_DISSOLVE,
    ],
    "revelation_hook": [
        MotionPrimitive.SWEEP_REVEAL,
        MotionPrimitive.MASK_REVEAL,
        MotionPrimitive.OBJECT_POP_5_10,
        MotionPrimitive.CAPTION_BEAT_REVEAL,
        MotionPrimitive.LUMA_FADE,
    ],
    "practical_advice": [
        MotionPrimitive.PUSH_IN,
        MotionPrimitive.OBJECT_POP_5_10,
        MotionPrimitive.CAPTION_BEAT_REVEAL,
        MotionPrimitive.DOCUMENT_SLIDE,
        MotionPrimitive.CHECKLIST_STEP_REVEAL,
    ],
    "coverage_explanation": [
        MotionPrimitive.PUSH_IN,
        MotionPrimitive.DOCUMENT_SLIDE,
        MotionPrimitive.SOFT_DISSOLVE,
        MotionPrimitive.CHECKLIST_STEP_REVEAL,
    ],
    "emotional_closure": [
        MotionPrimitive.PULL_BACK,
        MotionPrimitive.SOFT_DISSOLVE,
        MotionPrimitive.SHIELD_SCALE,
    ],
}



# ── Motion decision ─────────────────────────────────────────────────────────────


@dataclass
class MotionDecision:
    """A single motion decision for a timeline segment."""
    primitive: MotionPrimitive
    start_time: float
    duration: float
    scale_start: float = 1.0
    scale_end: float = 1.035
    easing: str = "smooth"
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def end_time(self) -> float:
        return self.start_time + self.duration


# ── Rule 1: Motion budget ───────────────────────────────────────────────────────


@dataclass
class MotionBudget:
    """Budget constraints for motion effects in a clip."""
    max_motions_per_clip: int = 5
    max_motions_per_10s: int = 3
    min_gap_between_motions: float = 1.5
    max_consecutive_same_primitive: int = 2
    warnings: List[str] = field(default_factory=list)


def enforce_motion_budget(
    decisions: List[MotionDecision],
    budget: Optional[MotionBudget] = None,
) -> List[MotionDecision]:
    """Rule 1: Enforce motion budget constraints.

    Filters decisions to stay within budget limits.  Returns the filtered list.
    """
    if budget is None:
        budget = MotionBudget()

    if not decisions:
        return decisions

    # Sort by start time
    sorted_decisions = sorted(decisions, key=lambda d: d.start_time)

    # 1. Max motions per clip
    if len(sorted_decisions) > budget.max_motions_per_clip:
        budget.warnings.append(
            f"Truncated from {len(sorted_decisions)} to {budget.max_motions_per_clip} "
            f"(max_motions_per_clip)"
        )
        sorted_decisions = sorted_decisions[:budget.max_motions_per_clip]

    # 2. Max motions per 10s window
    filtered: List[MotionDecision] = []
    for d in sorted_decisions:
        window_start = d.start_time - 10.0
        count_in_window = sum(
            1 for f in filtered if f.start_time >= window_start
        )
        if count_in_window < budget.max_motions_per_10s:
            filtered.append(d)
        else:
            budget.warnings.append(
                f"Skipped {d.primitive.name} at t={d.start_time:.2f}s "
                f"(max_motions_per_10s={budget.max_motions_per_10s})"
            )

    # 3. Min gap between motions
    gapped: List[MotionDecision] = []
    for d in filtered:
        if gapped and (d.start_time - gapped[-1].end_time) < budget.min_gap_between_motions:
            budget.warnings.append(
                f"Skipped {d.primitive.name} at t={d.start_time:.2f}s "
                f"(min_gap={budget.min_gap_between_motions}s)"
            )
            continue
        gapped.append(d)

    # 4. Max consecutive same primitive
    final: List[MotionDecision] = []
    same_count = 0
    for d in gapped:
        if final and d.primitive == final[-1].primitive:
            same_count += 1
        else:
            same_count = 1
        if same_count <= budget.max_consecutive_same_primitive:
            final.append(d)
        else:
            budget.warnings.append(
                f"Skipped consecutive {d.primitive.name} at t={d.start_time:.2f}s "
                f"(max_consecutive={budget.max_consecutive_same_primitive})"
            )

    return final


# ── Rule 2: Style compatibility ─────────────────────────────────────────────────


def _is_style_compatible(
    primitive: MotionPrimitive,
    visual_style: str,
) -> bool:
    """Check if a primitive is compatible with the given visual style."""
    compatible = _STYLE_PRIMITIVE_MAP.get(visual_style, [])
    return primitive in compatible


# ── Rule 3: Hook first-3s constraint ────────────────────────────────────────────


def _is_hook_first_3s(start_time: float, clip_duration: float) -> bool:
    """Check if a time falls within the first 3 seconds (hook window)."""
    return 0.0 <= start_time < 3.0


# ── Rule 4: No overlapping motion effects ───────────────────────────────────────


def _has_overlap(
    decision: MotionDecision,
    existing: List[MotionDecision],
) -> bool:
    """Check if a decision overlaps with any existing decision."""
    for e in existing:
        if decision.start_time < e.end_time and e.start_time < decision.end_time:
            return True
    return False


# ── Rule 5: Density check ───────────────────────────────────────────────────────


def _is_density_ok(
    decision: MotionDecision,
    existing: List[MotionDecision],
    max_per_5s: int = 2,
) -> bool:
    """Check if adding this decision would exceed density limits."""
    window_start = decision.start_time - 5.0
    count = sum(
        1 for e in existing
        if e.start_time >= window_start and e.start_time < decision.start_time + 5.0
    )
    return count < max_per_5s


# ── Rule 6: Avoid robotic cut zones ─────────────────────────────────────────────


def _is_in_robotic_cut_zone(
    start_time: float,
    robotic_cut_times: List[float],
    buffer: float = 0.3,
) -> bool:
    """Check if a time falls within buffer of a robotic cut."""
    for cut_time in robotic_cut_times:
        if abs(start_time - cut_time) < buffer:
            return True
    return False


# ── Main primitive selection ─────────────────────────────────────────────────────


def select_motion_primitive(
    start_time: float,
    duration: float,
    visual_style: str,
    hook_intent: Optional[str] = None,
    existing_decisions: Optional[List[MotionDecision]] = None,
    robotic_cut_times: Optional[List[float]] = None,
    clip_duration: Optional[float] = None,
    preferred_primitive: Optional[MotionPrimitive] = None,
) -> Optional[MotionDecision]:
    """Select a motion primitive for a given timeline segment.

    Applies all 6 rules:
    1. Motion budget (caller should call enforce_motion_budget separately)
    2. Style compatibility
    3. Hook first-3s constraint (only PUSH_IN or SWEEP_REVEAL allowed)
    4. No overlapping motion effects
    5. Density check (max 2 per 5s window)
    6. Avoid robotic cut zones

    Returns a MotionDecision or None if no primitive is suitable.
    """
    existing = existing_decisions or []
    robotic_times = robotic_cut_times or []

    # Determine candidate primitives
    candidates: List[MotionPrimitive] = []

    if preferred_primitive:
        candidates = [preferred_primitive]
    else:
        candidates = _STYLE_PRIMITIVE_MAP.get(visual_style, list(MotionPrimitive))

    # Rule 3: Hook first-3s constraint
    if clip_duration and _is_hook_first_3s(start_time, clip_duration):
        candidates = [
            p for p in candidates
            if p in (MotionPrimitive.PUSH_IN, MotionPrimitive.SWEEP_REVEAL)
        ]
        if not candidates:
            candidates = [MotionPrimitive.PUSH_IN]

    for primitive in candidates:
        meta = PRIMITIVE_META.get(primitive, {})

        # Rule 2: Style compatibility
        if not _is_style_compatible(primitive, visual_style):
            continue

        # Rule 4: No overlapping motion effects
        if _has_overlap(
            MotionDecision(primitive=primitive, start_time=start_time, duration=duration),
            existing,
        ):
            continue

        # Rule 5: Density check
        if not _is_density_ok(
            MotionDecision(primitive=primitive, start_time=start_time, duration=duration),
            existing,
        ):
            continue

        # Rule 6: Avoid robotic cut zones
        if _is_in_robotic_cut_zone(start_time, robotic_times):
            continue

        # Build decision
        scale_range = meta.get("scale_range")
        if scale_range:
            scale_start, scale_end = scale_range
        else:
            scale_start, scale_end = 1.0, 1.0

        return MotionDecision(
            primitive=primitive,
            start_time=start_time,
            duration=min(duration, meta.get("max_duration", 1.0)),
            scale_start=scale_start,
            scale_end=scale_end,
            easing=meta.get("easing", "smooth"),
            reason=f"style={visual_style} intent={hook_intent or 'none'}",
        )

    logger.info(
        "[motion-grammar] No suitable primitive for t=%.2f style=%s",
        start_time, visual_style,
    )
    return None


# ── Batch selection ──────────────────────────────────────────────────────────────


def select_motion_primitives_batch(
    segments: List[Dict[str, Any]],
    visual_style: str,
    hook_intent: Optional[str] = None,
    clip_duration: Optional[float] = None,
    robotic_cut_times: Optional[List[float]] = None,
    budget: Optional[MotionBudget] = None,
) -> List[MotionDecision]:
    """Select motion primitives for multiple segments in batch.

    Each segment dict should have:
        - start_time: float
        - duration: float
        - preferred_primitive: Optional[MotionPrimitive]
        - reason: Optional[str]

    Applies all 6 rules and budget enforcement.
    """
    decisions: List[MotionDecision] = []

    for seg in segments:
        decision = select_motion_primitive(
            start_time=seg.get("start_time", 0.0),
            duration=seg.get("duration", 0.5),
            visual_style=visual_style,
            hook_intent=hook_intent,
            existing_decisions=decisions,
            robotic_cut_times=robotic_cut_times,
            clip_duration=clip_duration,
            preferred_primitive=seg.get("preferred_primitive"),
        )
        if decision:
            decision.reason = seg.get("reason", decision.reason)
            decisions.append(decision)

    # Rule 1: Enforce motion budget
    decisions = enforce_motion_budget(decisions, budget)

    return decisions


# ── Timeline integration ─────────────────────────────────────────────────────────


def motion_decisions_to_timeline_items(
    decisions: List[MotionDecision],
    clip_id: str,
) -> List[Dict[str, Any]]:
    """Convert MotionDecisions to timeline items for ViraClipTimelinePlan.

    Returns a list of item dicts compatible with TimelineItem construction
    on the MOTION_EFFECT track.
    """
    items: List[Dict[str, Any]] = []
    for i, d in enumerate(decisions):
        items.append({
            "item_id": f"{clip_id}_motion_{i}",
            "track_kind": "MOTION_EFFECT",
            "time": {
                "start": d.start_time,
                "end": d.end_time,
            },
            "effects": [
                {
                    "type": d.primitive.name.lower(),
                    "scale_start": d.scale_start,
                    "scale_end": d.scale_end,
                    "easing": d.easing,
                    "duration": d.duration,
                },
            ],
            "metadata": {
                "primitive": d.primitive.name,
                "reason": d.reason,
                "source": "motion_grammar",
            },
        })
    return items
