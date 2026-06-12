"""
vpi_timeline_plan.py — ViraClipTimelinePlan (OTIO-like internal timeline schema)

A lightweight, OTIO-inspired internal timeline representation that models a finished
clip as a multi-track composition.  Each track holds a sequence of *items* with
precise start/end times, source references, and metadata.

This is a *plan/contract* schema — it does NOT render anything.  Downstream
services (editing_pipeline, overlay_renderer, caption_service, etc.) consume
a ViraClipTimelinePlan to produce the final video.

Design principles
-----------------
- Immutable-ish dataclasses (frozen where practical).
- Tracks are ordered by z-index (lower = background, higher = foreground).
- All times are in seconds (float).
- No FFmpeg filter graph logic — that belongs in the renderers.
- Compatible with existing dataclasses (RetentionEditingPlan, EditingPlan, etc.).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ── Track kinds ────────────────────────────────────────────────────────────────


class TrackKind(Enum):
    """Semantic kind for each track.  Ordered by typical z-index (back→front)."""
    BACKGROUND_COLOR = auto()       # Solid colour / gradient wash
    SPEAKER_VIDEO = auto()          # Main talking-head clip
    BROLL = auto()                  # B-roll / stock footage
    TRANSITION = auto()             # Transition overlay (glitch, morph, etc.)
    CAPTION_BG = auto()             # Caption background bar / box
    CAPTION_TEXT = auto()           # ASS subtitle text
    SEMANTIC_OBJECT = auto()        # Animated icon / motion overlay
    SFX = auto()                    # Sound effect (audio-only track)
    BGM = auto()                    # Background music (audio-only track)
    MOTION_EFFECT = auto()          # Camera push/pull, shake, etc.
    OVERLAY_TEXT = auto()           # Dynamic overlay text (lower-third, etc.)
    BRANDING = auto()               # Logo / watermark
    CINEMATIC_FINISH = auto()       # Film grain, LUT, colour grade


# ── Time references ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimeRange:
    """A time range in seconds."""
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end

    def overlaps(self, other: TimeRange) -> bool:
        return self.start < other.end and other.start < self.end

    def shift(self, offset: float) -> TimeRange:
        return TimeRange(self.start + offset, self.end + offset)


# ── Source references ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceReference:
    """Reference to an external media source."""
    path: str                          # File path or URL
    source_start: float = 0.0          # In-point in source (seconds)
    source_end: float = 0.0            # Out-point in source (seconds)
    media_type: str = "video"          # "video", "audio", "image", "text"
    asset_id: Optional[str] = None     # Asset bank ID if applicable


# ── Track items ────────────────────────────────────────────────────────────────


@dataclass
class TimelineItem:
    """A single item on a track."""
    item_id: str                       # Unique identifier
    track_kind: TrackKind
    time: TimeRange                    # Position on the timeline
    source: Optional[SourceReference] = None
    effects: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Visual properties (applied by renderers)
    opacity: float = 1.0
    scale: Tuple[float, float] = (1.0, 1.0)
    position: Tuple[float, float] = (0.0, 0.0)  # Normalised 0-1 x,y
    rotation: float = 0.0              # Degrees
    blend_mode: str = "normal"         # "normal", "multiply", "screen", etc.

    # Audio properties
    volume: float = 1.0
    pan: float = 0.0                   # -1 (left) to 1 (right)
    fade_in: float = 0.0
    fade_out: float = 0.0


# ── Track ──────────────────────────────────────────────────────────────────────


@dataclass
class Track:
    """A single track containing ordered items."""
    kind: TrackKind
    items: List[TimelineItem] = field(default_factory=list)
    enabled: bool = True
    z_index: int = 0                   # Lower = further back
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_item(self, item: TimelineItem) -> None:
        self.items.append(item)
        self.items.sort(key=lambda i: i.time.start)

    def items_in_range(self, tr: TimeRange) -> List[TimelineItem]:
        return [i for i in self.items if i.time.overlaps(tr)]


# ── Layer budget ───────────────────────────────────────────────────────────────


@dataclass
class LayerBudget:
    """Budget for visual/audio layers to avoid overwhelming the viewer."""
    max_visible_layers: int = 4        # Max simultaneous visual layers
    max_audio_streams: int = 3         # Max simultaneous audio streams
    max_overlay_text_items: int = 2    # Max on-screen text elements
    max_motion_effects: int = 1        # Max simultaneous motion effects
    warnings: List[str] = field(default_factory=list)


# ── Conflict resolution ────────────────────────────────────────────────────────


@dataclass
class LayerConflict:
    """A detected conflict between two timeline items."""
    item_a_id: str
    item_b_id: str
    conflict_type: str                 # "overlap", "z_order", "audio_clash", etc.
    severity: str = "warning"          # "info", "warning", "error"
    resolution: Optional[str] = None   # Suggested fix


@dataclass
class ConflictResolutionPlan:
    """Plan for resolving layer conflicts."""
    conflicts: List[LayerConflict] = field(default_factory=list)
    resolved: bool = False
    actions: List[Dict[str, Any]] = field(default_factory=list)


# ── Quality warnings ───────────────────────────────────────────────────────────


@dataclass
class QualityWarning:
    """A quality concern about the timeline."""
    code: str                          # e.g. "empty_track", "overlapping_items"
    message: str
    severity: str = "warning"          # "info", "warning", "error"
    affected_items: List[str] = field(default_factory=list)


# ── The main timeline plan ─────────────────────────────────────────────────────


@dataclass
class ViraClipTimelinePlan:
    """
    OTIO-like internal timeline representation for a single clip.

    Tracks are ordered by z-index (ascending).  The first track is the
    background; the last is the topmost foreground layer.
    """
    clip_id: str
    duration: float                    # Total duration in seconds
    fps: float = 30.0
    resolution: Tuple[int, int] = (1080, 1920)  # width, height

    tracks: List[Track] = field(default_factory=list)
    layer_budget: LayerBudget = field(default_factory=LayerBudget)
    conflicts: ConflictResolutionPlan = field(default_factory=ConflictResolutionPlan)
    quality_warnings: List[QualityWarning] = field(default_factory=list)

    # Cross-track metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Track accessors ────────────────────────────────────────────────────────

    def track_by_kind(self, kind: TrackKind) -> Optional[Track]:
        for t in self.tracks:
            if t.kind == kind:
                return t
        return None

    def get_or_create_track(self, kind: TrackKind, z_index: int = 0) -> Track:
        existing = self.track_by_kind(kind)
        if existing is not None:
            return existing
        track = Track(kind=kind, z_index=z_index)
        self.tracks.append(track)
        self.tracks.sort(key=lambda t: t.z_index)
        return track

    def all_items(self) -> List[TimelineItem]:
        return [item for track in self.tracks for item in track.items]

    def items_at_time(self, t: float) -> List[TimelineItem]:
        return [item for item in self.all_items() if item.time.contains(t)]

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate(self) -> List[QualityWarning]:
        """Run basic validation and return quality warnings."""
        warnings: List[QualityWarning] = []

        for track in self.tracks:
            if not track.enabled:
                continue
            if not track.items:
                warnings.append(QualityWarning(
                    code="empty_track",
                    message=f"Track {track.kind.name} has no items",
                    severity="info",
                ))
            # Check for overlapping items on the same track
            sorted_items = sorted(track.items, key=lambda i: i.time.start)
            for i in range(len(sorted_items) - 1):
                a = sorted_items[i]
                b = sorted_items[i + 1]
                if a.time.overlaps(b.time):
                    warnings.append(QualityWarning(
                        code="overlapping_items",
                        message=f"Items {a.item_id} and {b.item_id} overlap on track {track.kind.name}",
                        severity="warning",
                        affected_items=[a.item_id, b.item_id],
                    ))

        # Check layer budget
        for t in range(int(self.duration)):
            items_at_t = self.items_at_time(float(t))
            visible = [i for i in items_at_t if i.opacity > 0]
            if len(visible) > self.layer_budget.max_visible_layers:
                warnings.append(QualityWarning(
                    code="layer_budget_exceeded",
                    message=f"At t={t}s: {len(visible)} visible layers (max {self.layer_budget.max_visible_layers})",
                    severity="warning",
                ))

        self.quality_warnings = warnings
        return warnings

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ViraClipTimelinePlan:
        return cls(**data)


# ── Builder helper ─────────────────────────────────────────────────────────────


class TimelinePlanBuilder:
    """Fluent builder for constructing a ViraClipTimelinePlan incrementally."""

    def __init__(self, clip_id: str, duration: float) -> None:
        self._plan = ViraClipTimelinePlan(clip_id=clip_id, duration=duration)

    def with_resolution(self, width: int, height: int) -> TimelinePlanBuilder:
        self._plan.resolution = (width, height)
        return self

    def with_fps(self, fps: float) -> TimelinePlanBuilder:
        self._plan.fps = fps
        return self

    def add_track(self, kind: TrackKind, z_index: int = 0) -> TimelinePlanBuilder:
        self._plan.get_or_create_track(kind, z_index)
        return self

    def add_item(self, track_kind: TrackKind, item: TimelineItem) -> TimelinePlanBuilder:
        track = self._plan.get_or_create_track(track_kind)
        track.add_item(item)
        return self

    def with_layer_budget(self, budget: LayerBudget) -> TimelinePlanBuilder:
        self._plan.layer_budget = budget
        return self

    def build(self) -> ViraClipTimelinePlan:
        self._plan.validate()
        return self._plan
