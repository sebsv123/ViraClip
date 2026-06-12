"""
vpi_face_safe_layout.py — Face-safe / overlay-safe layout planner.

A lightweight heuristic layout planner that determines safe zones for placing
overlay elements (captions, icons, branding) relative to detected face regions.
This is a *planning* module — it does NOT render anything.  Downstream services
(overlay_renderer, caption_service) consume layout decisions to position elements.

Design
------
- Heuristic face zones based on typical talking-head framing (centre-top).
- 6 named zones with priority ordering for conflict resolution.
- Pure data: no FFmpeg, no ML face detection (caller provides face regions).
- Compatible with ViraClipTimelinePlan (OVERLAY_TEXT, CAPTION_TEXT, BRANDING tracks).

Integration
-----------
- overlay_renderer.py: consumes SafeZone → positions overlay elements
- caption_service.py: consumes SafeZone → positions caption bars
- vpi_retention_editing_service.py: caption_decisions → layout plan
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Named zones ─────────────────────────────────────────────────────────────────


class LayoutZone(Enum):
    """Named layout zones on the canvas (1080×1920 portrait)."""
    FACE_ZONE = auto()           # Centre-top: talking head region
    CAPTION_ZONE = auto()        # Centre-bottom: primary caption area
    OBJECT_LEFT_ZONE = auto()    # Left third: semantic object / icon
    OBJECT_RIGHT_ZONE = auto()   # Right third: semantic object / icon
    HOOK_CARD_ZONE = auto()      # Centre: hook card / title card
    LOWER_THIRD_ZONE = auto()    # Bottom-left: lower-third text


# ── Zone definitions (normalised 0-1 coordinates) ───────────────────────────────


@dataclass
class NormalisedRect:
    """A rectangle in normalised coordinates (0-1)."""
    x: float       # Centre x
    y: float       # Centre y
    width: float   # Total width
    height: float  # Total height

    @property
    def left(self) -> float:
        return self.x - self.width / 2

    @property
    def right(self) -> float:
        return self.x + self.width / 2

    @property
    def top(self) -> float:
        return self.y - self.height / 2

    @property
    def bottom(self) -> float:
        return self.y + self.height / 2

    def overlaps(self, other: NormalisedRect, margin: float = 0.02) -> bool:
        """Check if this rect overlaps with another, with optional margin."""
        return (
            self.left - margin < other.right + margin
            and self.right + margin > other.left - margin
            and self.top - margin < other.bottom + margin
            and self.bottom + margin > other.top - margin
        )

    def area(self) -> float:
        return self.width * self.height


# Default zone rectangles (normalised, for 1080×1920 portrait)
DEFAULT_ZONES: Dict[LayoutZone, NormalisedRect] = {
    LayoutZone.FACE_ZONE: NormalisedRect(x=0.5, y=0.25, width=0.4, height=0.3),
    LayoutZone.CAPTION_ZONE: NormalisedRect(x=0.5, y=0.78, width=0.85, height=0.15),
    LayoutZone.OBJECT_LEFT_ZONE: NormalisedRect(x=0.2, y=0.55, width=0.25, height=0.25),
    LayoutZone.OBJECT_RIGHT_ZONE: NormalisedRect(x=0.8, y=0.55, width=0.25, height=0.25),
    LayoutZone.HOOK_CARD_ZONE: NormalisedRect(x=0.5, y=0.5, width=0.7, height=0.4),
    LayoutZone.LOWER_THIRD_ZONE: NormalisedRect(x=0.25, y=0.88, width=0.4, height=0.08),
}

# Priority ordering for conflict resolution (lower = higher priority)
ZONE_PRIORITY: Dict[LayoutZone, int] = {
    LayoutZone.FACE_ZONE: 0,           # Highest — never occlude face
    LayoutZone.HOOK_CARD_ZONE: 1,      # Hook card is critical
    LayoutZone.CAPTION_ZONE: 2,        # Captions are important
    LayoutZone.OBJECT_LEFT_ZONE: 3,
    LayoutZone.OBJECT_RIGHT_ZONE: 3,
    LayoutZone.LOWER_THIRD_ZONE: 4,    # Lowest — can be moved
}


# ── Safe zone decision ──────────────────────────────────────────────────────────


@dataclass
class SafeZone:
    """A safe zone for placing an overlay element."""
    zone: LayoutZone
    rect: NormalisedRect
    priority: int
    occupied: bool = False
    occupant: Optional[str] = None  # e.g. "caption", "icon", "branding"
    conflict_resolved: bool = False


@dataclass
class LayoutPlan:
    """Complete layout plan for a clip."""
    clip_id: str
    zones: List[SafeZone] = field(default_factory=list)
    face_regions: List[NormalisedRect] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def zone_by_type(self, zone_type: LayoutZone) -> Optional[SafeZone]:
        for z in self.zones:
            if z.zone == zone_type:
                return z
        return None

    def is_zone_available(self, zone_type: LayoutZone) -> bool:
        sz = self.zone_by_type(zone_type)
        return sz is not None and not sz.occupied


# ── Face region adjustment ──────────────────────────────────────────────────────


def adjust_zones_for_face(
    zones: Dict[LayoutZone, NormalisedRect],
    face_regions: List[NormalisedRect],
) -> Dict[LayoutZone, NormalisedRect]:
    """Adjust zone positions to avoid overlapping with detected face regions.

    If a zone overlaps with a face region, it is shifted downward or to the side.
    """
    adjusted = dict(zones)

    for zone_type, zone_rect in adjusted.items():
        if zone_type == LayoutZone.FACE_ZONE:
            # Face zone is defined by the face region itself
            continue

        for face in face_regions:
            if zone_rect.overlaps(face, margin=0.05):
                # Shift zone below the face
                new_y = face.bottom + zone_rect.height / 2 + 0.05
                if new_y + zone_rect.height / 2 <= 1.0:
                    adjusted[zone_type] = NormalisedRect(
                        x=zone_rect.x,
                        y=new_y,
                        width=zone_rect.width,
                        height=zone_rect.height,
                    )
                else:
                    # Shift to the side
                    if zone_rect.x <= 0.5:
                        new_x = max(0.05, zone_rect.x - zone_rect.width / 2 - 0.05)
                    else:
                        new_x = min(0.95, zone_rect.x + zone_rect.width / 2 + 0.05)
                    adjusted[zone_type] = NormalisedRect(
                        x=new_x,
                        y=zone_rect.y,
                        width=zone_rect.width,
                        height=zone_rect.height,
                    )

    return adjusted


# ── Conflict detection ──────────────────────────────────────────────────────────


def detect_layout_conflicts(
    zones: List[SafeZone],
    margin: float = 0.02,
) -> List[Dict[str, Any]]:
    """Detect conflicts between occupied zones.

    Returns a list of conflict dicts with:
        - zone_a: LayoutZone name
        - zone_b: LayoutZone name
        - overlap_area: float
        - severity: str ("info", "warning", "error")
    """
    conflicts: List[Dict[str, Any]] = []

    for i, a in enumerate(zones):
        if not a.occupied:
            continue
        for j, b in enumerate(zones):
            if j <= i or not b.occupied:
                continue
            if a.rect.overlaps(b.rect, margin):
                overlap_area = (
                    min(a.rect.right, b.rect.right)
                    - max(a.rect.left, b.rect.left)
                ) * (
                    min(a.rect.bottom, b.rect.bottom)
                    - max(a.rect.top, b.rect.top)
                )
                severity = "error" if overlap_area > 0.05 else "warning"
                conflicts.append({
                    "zone_a": a.zone.name,
                    "zone_b": b.zone.name,
                    "overlap_area": overlap_area,
                    "severity": severity,
                })

    return conflicts


# ── Conflict resolution ─────────────────────────────────────────────────────────


def resolve_layout_conflicts(
    zones: List[SafeZone],
    conflicts: List[Dict[str, Any]],
) -> List[SafeZone]:
    """Resolve layout conflicts by moving lower-priority zones.

    Strategy:
    1. Higher-priority zone stays in place.
    2. Lower-priority zone is shifted to the nearest available position.
    3. If no position is available, the lower-priority zone is marked as
       conflict_resolved=True and its occupant is flagged for removal.
    """
    resolved = list(zones)

    for conflict in conflicts:
        zone_a_name = conflict["zone_a"]
        zone_b_name = conflict["zone_b"]

        # Find the zones
        a = next((z for z in resolved if z.zone.name == zone_a_name), None)
        b = next((z for z in resolved if z.zone.name == zone_b_name), None)
        if not a or not b:
            continue

        # Determine which has higher priority (lower number = higher)
        if a.priority <= b.priority:
            keep, move = a, b
        else:
            keep, move = b, a

        # Try shifting the lower-priority zone
        # Shift right if possible
        new_x = move.rect.x + move.rect.width + 0.05
        if new_x + move.rect.width / 2 <= 1.0:
            move.rect = NormalisedRect(
                x=new_x,
                y=move.rect.y,
                width=move.rect.width,
                height=move.rect.height,
            )
            move.conflict_resolved = True
        else:
            # Shift down
            new_y = move.rect.y + move.rect.height + 0.05
            if new_y + move.rect.height / 2 <= 1.0:
                move.rect = NormalisedRect(
                    x=move.rect.x,
                    y=new_y,
                    width=move.rect.width,
                    height=move.rect.height,
                )
                move.conflict_resolved = True
            else:
                # Cannot resolve — flag the lower-priority zone
                move.conflict_resolved = True
                move.occupied = False
                logger.warning(
                    "[face-safe-layout] Cannot resolve conflict between %s and %s; "
                    "removing %s",
                    keep.zone.name, move.zone.name, move.zone.name,
                )

    return resolved


# ── Main layout planner ─────────────────────────────────────────────────────────


def plan_safe_overlay_zone(
    clip_id: str,
    element_type: str,
    preferred_zone: Optional[LayoutZone] = None,
    face_regions: Optional[List[NormalisedRect]] = None,
    existing_plan: Optional[LayoutPlan] = None,
) -> LayoutPlan:
    """Plan a safe overlay zone for a given element type.

    Args:
        clip_id: Unique clip identifier.
        element_type: Type of element ("caption", "icon", "branding", "hook_card",
                     "lower_third").
        preferred_zone: Preferred LayoutZone for this element.
        face_regions: Optional list of detected face regions.
        existing_plan: Optional existing LayoutPlan to extend.

    Returns:
        A LayoutPlan with the element placed in a safe zone.
    """
    if existing_plan:
        plan = existing_plan
    else:
        plan = LayoutPlan(clip_id=clip_id)

    # Determine face regions
    face_regions = face_regions or []
    plan.face_regions = face_regions

    # Adjust zones for face regions
    adjusted_zones = adjust_zones_for_face(DEFAULT_ZONES, face_regions)

    # Build SafeZone list if not already present
    if not plan.zones:
        for zone_type, rect in adjusted_zones.items():
            plan.zones.append(SafeZone(
                zone=zone_type,
                rect=rect,
                priority=ZONE_PRIORITY.get(zone_type, 99),
            ))

    # Determine which zone to use
    zone_map: Dict[str, LayoutZone] = {
        "caption": LayoutZone.CAPTION_ZONE,
        "icon": LayoutZone.OBJECT_LEFT_ZONE,
        "branding": LayoutZone.LOWER_THIRD_ZONE,
        "hook_card": LayoutZone.HOOK_CARD_ZONE,
        "lower_third": LayoutZone.LOWER_THIRD_ZONE,
    }

    target_zone = preferred_zone or zone_map.get(element_type)
    if target_zone is None:
        plan.warnings.append(f"No zone mapping for element_type={element_type}")
        return plan

    # Check if the target zone is available
    if plan.is_zone_available(target_zone):
        sz = plan.zone_by_type(target_zone)
        if sz:
            sz.occupied = True
            sz.occupant = element_type
    else:
        # Find the next best available zone
        available = [z for z in plan.zones if not z.occupied]
        if available:
            # Pick the highest-priority available zone
            available.sort(key=lambda z: z.priority)
            chosen = available[0]
            chosen.occupied = True
            chosen.occupant = element_type
            plan.warnings.append(
                f"Preferred zone {target_zone.name} occupied; "
                f"placed {element_type} in {chosen.zone.name}"
            )
        else:
            plan.warnings.append(
                f"No available zone for {element_type}; element may overlap"
            )

    # Detect and resolve conflicts
    conflicts = detect_layout_conflicts(plan.zones)
    plan.conflicts = conflicts
    if conflicts:
        plan.zones = resolve_layout_conflicts(plan.zones, conflicts)

    return plan


# ── Timeline integration ─────────────────────────────────────────────────────────


def layout_plan_to_timeline_items(
    plan: LayoutPlan,
    clip_id: str,
) -> List[Dict[str, Any]]:
    """Convert a LayoutPlan to timeline items for ViraClipTimelinePlan.

    Returns a list of item dicts compatible with TimelineItem construction
    on the OVERLAY_TEXT or BRANDING tracks.
    """
    items: List[Dict[str, Any]] = []
    for i, zone in enumerate(plan.zones):
        if not zone.occupied:
            continue

        track_kind = "OVERLAY_TEXT"
        if zone.occupant == "branding":
            track_kind = "BRANDING"
        elif zone.occupant == "caption":
            track_kind = "CAPTION_TEXT"

        items.append({
            "item_id": f"{clip_id}_layout_{i}",
            "track_kind": track_kind,
            "time": {
                "start": 0.0,
                "end": 0.0,  # Full clip duration — caller should set
            },
            "position": (zone.rect.x, zone.rect.y),
            "metadata": {
                "zone": zone.zone.name,
                "occupant": zone.occupant,
                "conflict_resolved": zone.conflict_resolved,
                "source": "face_safe_layout",
            },
        })
    return items
