"""
vpi_visual_priority_guard.py — "One Strong Thing" visual priority guard.

Enforces the "One Strong Thing" rule: only one primary visual event should
occur in any 3-5 second window.  This prevents visual overload and ensures
the viewer's attention is focused on the most important element at any time.

Design
------
- Priority ordering for all visual event types.
- 3-5 second sliding window conflict detection.
- Conflict resolution by demoting or delaying lower-priority events.
- Pure data: no FFmpeg, no rendering.
- Compatible with ViraClipTimelinePlan.

Integration
-----------
- vpi_timeline_plan.py: consumes resolved events → timeline items
- vpi_retention_editing_service.py: visual_coherence → priority guard
- vpi_visual_effects_service.py: motion decisions → priority guard
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Visual event types ──────────────────────────────────────────────────────────


class VisualEventType(Enum):
    """Types of visual events that can appear on the timeline."""

    # Highest priority
    DISFLUENCY_COVER_TRANSITION = auto()  # Cover transition for disfluency
    HOOK_CARD = auto()                    # Hook card (first 3s)

    # Medium-high priority
    BROLL = auto()                        # B-roll footage
    STRONG_CAPTION_HIGHLIGHT = auto()     # Emphasis caption highlight

    # Medium priority
    SEMANTIC_OBJECT = auto()              # Animated icon / motion overlay
    MAJOR_MOTION_REVEAL = auto()          # Push-in, sweep, mask reveal

    # Lowest priority
    DECORATIVE_TRANSITION = auto()        # Decorative transition effect


# Priority ordering (lower number = higher priority)
EVENT_PRIORITY: Dict[VisualEventType, int] = {
    VisualEventType.DISFLUENCY_COVER_TRANSITION: 0,
    VisualEventType.HOOK_CARD: 1,
    VisualEventType.BROLL: 2,
    VisualEventType.STRONG_CAPTION_HIGHLIGHT: 3,
    VisualEventType.SEMANTIC_OBJECT: 4,
    VisualEventType.MAJOR_MOTION_REVEAL: 5,
    VisualEventType.DECORATIVE_TRANSITION: 6,
}


# ── Visual event ────────────────────────────────────────────────────────────────


@dataclass
class VisualEvent:
    """A visual event on the timeline."""
    event_id: str
    event_type: VisualEventType
    start_time: float
    end_time: float
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.priority = EVENT_PRIORITY.get(self.event_type, 99)

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def overlaps(self, other: VisualEvent) -> bool:
        return self.start_time < other.end_time and other.start_time < self.end_time


# ── Conflict ────────────────────────────────────────────────────────────────────


@dataclass
class VisualConflict:
    """A detected conflict between two visual events."""
    event_a_id: str
    event_b_id: str
    event_a_type: str
    event_b_type: str
    overlap_start: float
    overlap_end: float
    resolution: Optional[str] = None


# ── Resolution action ───────────────────────────────────────────────────────────


class ResolutionAction(Enum):
    """Action taken to resolve a visual conflict."""
    KEEP_BOTH = auto()           # Both can coexist (e.g., B-roll + caption)
    DEMOTE_LOWER = auto()        # Lower-priority event is demoted
    DELAY_LOWER = auto()         # Lower-priority event is delayed
    REMOVE_LOWER = auto()        # Lower-priority event is removed
    SPLIT_WINDOW = auto()        # Events are split into separate windows


# ── Resolution plan ─────────────────────────────────────────────────────────────


@dataclass
class VisualPriorityPlan:
    """Plan for resolving visual priority conflicts."""
    clip_id: str
    events: List[VisualEvent] = field(default_factory=list)
    conflicts: List[VisualConflict] = field(default_factory=list)
    resolutions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_event(self, event: VisualEvent) -> None:
        self.events.append(event)

    def events_in_range(self, start: float, end: float) -> List[VisualEvent]:
        return [
            e for e in self.events
            if e.start_time < end and e.end_time > start
        ]


# ── Conflict detection ──────────────────────────────────────────────────────────


def detect_visual_event_conflicts(
    events: List[VisualEvent],
    window_size: float = 4.0,  # 3-5 second window (default 4s)
    step: float = 1.0,
) -> List[VisualConflict]:
    """Detect conflicts where multiple high-priority events overlap.

    Uses a sliding window approach.  Any window containing more than one
    event with priority < 3 (i.e., DISFLUENCY_COVER_TRANSITION, HOOK_CARD,
    BROLL, STRONG_CAPTION_HIGHLIGHT) is flagged as a conflict.

    Returns a list of VisualConflict objects.
    """
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: e.start_time)
    conflicts: List[VisualConflict] = []
    seen_pairs: set = set()

    # Sliding window
    max_time = max(e.end_time for e in sorted_events)
    window_start = 0.0

    while window_start < max_time:
        window_end = window_start + window_size
        window_events = [
            e for e in sorted_events
            if e.start_time < window_end and e.end_time > window_start
        ]

        # Check for high-priority conflicts (priority < 3)
        high_priority = [e for e in window_events if e.priority < 3]
        if len(high_priority) > 1:
            for i in range(len(high_priority)):
                for j in range(i + 1, len(high_priority)):
                    a, b = high_priority[i], high_priority[j]
                    pair_key = (a.event_id, b.event_id)
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        conflicts.append(VisualConflict(
                            event_a_id=a.event_id,
                            event_b_id=b.event_id,
                            event_a_type=a.event_type.name,
                            event_b_type=b.event_type.name,
                            overlap_start=max(a.start_time, b.start_time),
                            overlap_end=min(a.end_time, b.end_time),
                        ))

        window_start += step

    return conflicts


# ── Conflict resolution ─────────────────────────────────────────────────────────


def resolve_visual_event_conflicts(
    events: List[VisualEvent],
    conflicts: List[VisualConflict],
    window_size: float = 4.0,
) -> VisualPriorityPlan:
    """Resolve visual event conflicts using the One Strong Thing rule.

    Resolution strategy:
    1. Higher-priority event keeps its slot.
    2. Lower-priority event is delayed by `window_size` seconds (if possible).
    3. If delaying would push the event past clip end, it is removed.
    4. If both events have the same priority, the shorter one is delayed.

    Returns a VisualPriorityPlan with resolved events.
    """
    plan = VisualPriorityPlan(clip_id="")
    resolved_events = list(events)
    resolutions: List[Dict[str, Any]] = []

    # Determine clip duration from events
    clip_duration = max(e.end_time for e in events) if events else 60.0

    for conflict in conflicts:
        a = next((e for e in resolved_events if e.event_id == conflict.event_a_id), None)
        b = next((e for e in resolved_events if e.event_id == conflict.event_b_id), None)
        if not a or not b:
            continue

        # Determine which event has higher priority
        if a.priority < b.priority:
            keep, demote = a, b
        elif b.priority < a.priority:
            keep, demote = b, a
        else:
            # Same priority — shorter one is demoted
            if a.duration <= b.duration:
                keep, demote = a, b
            else:
                keep, demote = b, a

        # Try delaying the lower-priority event
        new_start = keep.end_time + 0.5  # Small gap after higher-priority event
        new_end = new_start + demote.duration

        if new_end <= clip_duration:
            # Delay is possible
            demote.start_time = new_start
            demote.end_time = new_end
            resolutions.append({
                "event_id": demote.event_id,
                "action": ResolutionAction.DELAY_LOWER.name,
                "old_start": conflict.overlap_start,
                "new_start": new_start,
                "reason": f"Delayed to avoid conflict with {keep.event_type.name}",
            })
        else:
            # Cannot delay — remove the lower-priority event
            resolved_events = [e for e in resolved_events if e.event_id != demote.event_id]
            resolutions.append({
                "event_id": demote.event_id,
                "action": ResolutionAction.REMOVE_LOWER.name,
                "reason": f"Removed to avoid conflict with {keep.event_type.name} "
                          f"(cannot delay past clip end)",
            })
            plan.warnings.append(
                f"Removed {demote.event_type.name} ({demote.event_id}) "
                f"due to conflict with {keep.event_type.name}"
            )

    plan.events = resolved_events
    plan.conflicts = conflicts
    plan.resolutions = resolutions

    return plan


# ── Main entry point ────────────────────────────────────────────────────────────


def build_visual_priority_plan(
    clip_id: str,
    events: List[VisualEvent],
    window_size: float = 4.0,
) -> VisualPriorityPlan:
    """Build a complete visual priority plan for a clip.

    Detects conflicts and resolves them using the One Strong Thing rule.
    """
    # Detect conflicts
    conflicts = detect_visual_event_conflicts(events, window_size=window_size)

    # Resolve conflicts
    plan = resolve_visual_event_conflicts(events, conflicts, window_size=window_size)
    plan.clip_id = clip_id

    return plan


# ── Timeline integration ─────────────────────────────────────────────────────────


def visual_priority_plan_to_timeline_items(
    plan: VisualPriorityPlan,
    clip_id: str,
) -> List[Dict[str, Any]]:
    """Convert a VisualPriorityPlan to timeline items for ViraClipTimelinePlan.

    Returns a list of item dicts compatible with TimelineItem construction.
    """
    items: List[Dict[str, Any]] = []
    for i, event in enumerate(plan.events):
        # Map event type to track kind
        track_kind_map = {
            VisualEventType.DISFLUENCY_COVER_TRANSITION: "TRANSITION",
            VisualEventType.HOOK_CARD: "OVERLAY_TEXT",
            VisualEventType.BROLL: "BROLL",
            VisualEventType.STRONG_CAPTION_HIGHLIGHT: "CAPTION_TEXT",
            VisualEventType.SEMANTIC_OBJECT: "SEMANTIC_OBJECT",
            VisualEventType.MAJOR_MOTION_REVEAL: "MOTION_EFFECT",
            VisualEventType.DECORATIVE_TRANSITION: "TRANSITION",
        }
        track_kind = track_kind_map.get(event.event_type, "OVERLAY_TEXT")

        items.append({
            "item_id": f"{clip_id}_priority_{i}",
            "track_kind": track_kind,
            "time": {
                "start": event.start_time,
                "end": event.end_time,
            },
            "metadata": {
                "event_type": event.event_type.name,
                "priority": event.priority,
                "source": "visual_priority_guard",
            },
        })
    return items
