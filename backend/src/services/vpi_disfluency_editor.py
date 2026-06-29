"""
vpi_disfluency_editor.py — Auto-Editor-inspired disfluency engine enhancements

Extends the existing disfluency detection in vpi_editorial_fluency_service.py and
vpi_retention_editing_service.py with Auto-Editor-inspired actions.

Auto-Editor (https://github.com/WyattBlue/auto-editor) works by analysing audio
silences and cutting them out.  This module applies the same philosophy to
*spoken disfluencies*: filler words, repetitions, false starts, and awkward
pauses are treated as "dead air" that should be cut, compressed, or covered.

Key enhancements over existing logic
------------------------------------
- More granular action types (cut, compress, speed_up, preserve_emphasis,
  cover_with_broll, cover_with_transition, ignore)
- Padding (small buffers around cuts to avoid robotic transitions)
- Speed factor for time-compression (playback speed > 1.0)
- Cover strategy metadata (which B-roll or transition to use)
- Robotic cut risk assessment (too many cuts = unnatural)
- Integration with ViraClipTimelinePlan

Design
------
- Pure data: no FFmpeg, no rendering.
- Consumes word timestamps and produces a DisfluencyEditPlan.
- Downstream services (vpi_silence_editor, editing_pipeline) apply the edits.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ── Action types ───────────────────────────────────────────────────────────────


class DisfluencyAction(Enum):
    """Action to take on a detected disfluency.

    Inspired by Auto-Editor's cutting philosophy, extended for ViraClip's
    premium editing pipeline.
    """
    CUT = auto()                       # Remove entirely (like Auto-Editor silence cut)
    COMPRESS = auto()                  # Speed up to reduce duration (1.5x-3x)
    SPEED_UP = auto()                  # Speed up moderately (1.2x-1.5x)
    PRESERVE_EMPHASIS = auto()         # Keep as-is (it adds rhetorical value)
    COVER_WITH_BROLL = auto()          # Keep audio but cover video with B-roll
    COVER_WITH_TRANSITION = auto()     # Keep audio, cover with transition effect
    IGNORE = auto()                    # Leave untouched


class DisfluencyType(Enum):
    """Type of disfluency detected."""
    FILLER = auto()                    # "um", "uh", "like", "you know"
    REPETITION = auto()                # Repeated word or phrase
    FALSE_START = auto()               # Abandoned sentence beginning
    AWKWARD_PAUSE = auto()             # Pause > 0.5s mid-sentence
    BTS_LINE = auto()                  # Behind-the-scenes / meta comment
    AUTO_CORRECTION = auto()           # Self-correction ("I mean...")
    THINKING_PAUSE = auto()            # Pause indicating active thought
    BREATH = auto()                    # Audible breath
    DEAD_AIR = auto()                  # Silence > 1.0s


# ── Disfluency segment ─────────────────────────────────────────────────────────


@dataclass
class DisfluencySegment:
    """A single disfluency segment with detection and action metadata."""
    disfluency_type: DisfluencyType
    start_s: float
    end_s: float
    original_text: str = ""
    confidence: float = 1.0            # Detection confidence 0-1
    action: DisfluencyAction = DisfluencyAction.CUT
    reason: str = ""

    # Auto-Editor-inspired parameters
    padding_before: float = 0.05       # Small buffer before cut (seconds)
    padding_after: float = 0.05        # Small buffer after cut (seconds)
    speed_factor: float = 1.0          # Playback speed if COMPRESS or SPEED_UP
    cover_strategy: Optional[str] = None  # "broll", "transition", "overlay"

    # Robotic cut risk
    is_robotic_risk: bool = False      # True if this cut would feel robotic


# ── Edit plan ──────────────────────────────────────────────────────────────────


@dataclass
class DisfluencyEdit:
    """A single edit operation resulting from disfluency analysis."""
    action: DisfluencyAction
    segment: DisfluencySegment
    adjusted_start: float              # start_s - padding_before
    adjusted_end: float                # end_s + padding_after
    new_duration: float                # Duration after edit (0 for CUT)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DisfluencyEditPlan:
    """Complete disfluency editing plan for a clip."""
    enabled: bool = True
    segments: List[DisfluencySegment] = field(default_factory=list)
    edits: List[DisfluencyEdit] = field(default_factory=list)

    # Summary stats
    total_disfluencies: int = 0
    total_cut_duration: float = 0.0    # Total time removed by cuts
    total_compressed_duration: float = 0.0  # Total time saved by compression
    original_duration: float = 0.0
    new_duration: float = 0.0

    # Robotic cut assessment
    robotic_cut_count: int = 0
    robotic_cut_risk: str = "low"      # "low", "medium", "high"
    robotic_cut_warnings: List[str] = field(default_factory=list)

    # Cover strategy tracking
    broll_covers: int = 0
    transition_covers: int = 0

    # Integration with timeline plan
    timeline_plan_compatible: bool = True
    warnings: List[str] = field(default_factory=list)


# ── Detection constants ────────────────────────────────────────────────────────


# Spanish filler words (matches existing _DISFLUENCY_FILLERS in retention_editing)
FILLER_WORDS: set = {
    "eh", "ah", "mm", "mmm", "um", "este", "o sea", "bueno", "pues",
    "digamos", "vamos", "entonces", "como", "tipo", "prácticamente",
    "básicamente", "literalmente", "en plan", "o sea que", "es decir",
    "la verdad", "realmente", "obviamente", "claramente", "sabes",
    "sabéis", "mira", "oye", "venga", "vale", "ok", "listo",
}

# Short interjections that are usually filler
SHORT_INTERJECTIONS: set = {
    "sí", "no", "ya", "bien", "claro", "correcto", "exacto",
    "perfecto", "genial", "estupendo", "vale", "ok", "okey",
}

# Repetition detection threshold (same word repeated within N words)
REPETITION_WINDOW: int = 5

# Pause thresholds (seconds)
AWKWARD_PAUSE_MIN: float = 0.5
DEAD_AIR_MIN: float = 1.0
THINKING_PAUSE_MAX: float = 1.5

# Robotic cut risk thresholds
MAX_CUTS_PER_10S: int = 3
MAX_CUTS_PER_30S: int = 6
MIN_SEGMENT_BETWEEN_CUTS: float = 1.0


# ── Detection functions ────────────────────────────────────────────────────────


def detect_fillers(
    words: List[Dict[str, Any]],
    filler_set: set = FILLER_WORDS,
) -> List[DisfluencySegment]:
    """Detect filler words from word-level timestamps.

    Each word dict should have keys: 'text', 'start', 'end'.
    """
    segments: List[DisfluencySegment] = []
    for w in words:
        text = w.get("text", "").strip().lower()
        if text in filler_set:
            segments.append(DisfluencySegment(
                disfluency_type=DisfluencyType.FILLER,
                start_s=w.get("start", 0.0),
                end_s=w.get("end", 0.0),
                original_text=text,
                confidence=0.9,
                action=DisfluencyAction.CUT,
                reason=f"Filler word: '{text}'",
            ))
    return segments


def detect_repetitions(
    words: List[Dict[str, Any]],
    window: int = REPETITION_WINDOW,
) -> List[DisfluencySegment]:
    """Detect repeated words or short phrases within a window."""
    segments: List[DisfluencySegment] = []
    texts = [w.get("text", "").strip().lower() for w in words]

    for i in range(len(texts)):
        for j in range(i + 1, min(i + window, len(texts))):
            if texts[i] and texts[i] == texts[j]:
                # Found a repetition
                segments.append(DisfluencySegment(
                    disfluency_type=DisfluencyType.REPETITION,
                    start_s=words[j].get("start", 0.0),
                    end_s=words[j].get("end", 0.0),
                    original_text=texts[j],
                    confidence=0.85,
                    action=DisfluencyAction.CUT,
                    reason=f"Repetition of '{texts[i]}'",
                ))
                break  # Only flag the first repetition of each word
    return segments


def detect_false_starts(
    words: List[Dict[str, Any]],
    min_gap: float = 0.3,
) -> List[DisfluencySegment]:
    """Detect false starts: abandoned sentence beginnings.

    A false start is typically a short phrase followed by a pause > min_gap
    and then a different continuation.
    """
    segments: List[DisfluencySegment] = []
    if len(words) < 3:
        return segments

    for i in range(len(words) - 2):
        gap = words[i + 1].get("start", 0.0) - words[i].get("end", 0.0)
        if gap >= min_gap:
            # Check if the words before the pause look like a false start
            pre_text = words[i].get("text", "").strip().lower()
            post_text = words[i + 1].get("text", "").strip().lower()

            # False start indicators: short word followed by pause
            if len(pre_text.split()) <= 3 and pre_text not in {"y", "o", "pero", "que"}:
                # Check if the next word is a conjunction or different topic
                if post_text in {"pero", "sin embargo", "no", "es que", "la verdad"}:
                    segments.append(DisfluencySegment(
                        disfluency_type=DisfluencyType.FALSE_START,
                        start_s=words[i].get("start", 0.0),
                        end_s=words[i + 1].get("start", 0.0),
                        original_text=pre_text,
                        confidence=0.7,
                        action=DisfluencyAction.CUT,
                        reason=f"False start: '{pre_text}' before pause",
                    ))
    return segments


def detect_awkward_pauses(
    words: List[Dict[str, Any]],
    min_pause: float = AWKWARD_PAUSE_MIN,
    max_pause: float = 3.0,
) -> List[DisfluencySegment]:
    """Detect awkward mid-sentence pauses."""
    segments: List[DisfluencySegment] = []
    for i in range(len(words) - 1):
        gap = words[i + 1].get("start", 0.0) - words[i].get("end", 0.0)
        if min_pause <= gap <= max_pause:
            pre_text = words[i].get("text", "").strip().lower()
            post_text = words[i + 1].get("text", "").strip().lower()

            # Don't flag pauses at sentence boundaries
            if pre_text.endswith((".", "!", "?", "...")):
                continue

            # Classify the pause
            if gap >= DEAD_AIR_MIN:
                dtype = DisfluencyType.DEAD_AIR
                action = DisfluencyAction.CUT
                reason = f"Dead air: {gap:.1f}s pause"
            elif gap >= 0.8:
                dtype = DisfluencyType.AWKWARD_PAUSE
                action = DisfluencyAction.COMPRESS
                reason = f"Awkward pause: {gap:.1f}s"
            else:
                dtype = DisfluencyType.THINKING_PAUSE
                action = DisfluencyAction.PRESERVE_EMPHASIS
                reason = f"Thinking pause: {gap:.1f}s"

            segments.append(DisfluencySegment(
                disfluency_type=dtype,
                start_s=words[i].get("end", 0.0),
                end_s=words[i + 1].get("start", 0.0),
                original_text=f"{pre_text} [...] {post_text}",
                confidence=0.8,
                action=action,
                reason=reason,
                speed_factor=2.0 if action == DisfluencyAction.COMPRESS else 1.0,
            ))
    return segments


# ── Action assignment ──────────────────────────────────────────────────────────


def assign_actions(
    segments: List[DisfluencySegment],
    clip_duration: float,
    visual_style: str = "calm_trust",
) -> List[DisfluencySegment]:
    """Assign appropriate actions to disfluency segments based on context.

    Rules:
    - Fillers → CUT (always)
    - Repetitions → CUT (first occurrence kept)
    - False starts → CUT
    - Dead air (>=1.0s) → CUT
    - Awkward pause (0.5-0.8s) → COMPRESS (2x speed)
    - Thinking pause (0.3-0.5s) → PRESERVE_EMPHASIS
    - Breaths → CUT (if short) or IGNORE (if part of delivery)
    - BTS lines → COVER_WITH_BROLL (keep audio, cover video)

    Visual style adjustments:
    - calm_trust: fewer cuts, more preserves
    - serious_warning: more cuts, tighter pacing
    - revelation_hook: preserve pauses for dramatic effect
    """
    for seg in segments:
        if seg.action != DisfluencyAction.CUT:
            continue  # Already assigned by detector

        # Apply visual style rules
        if visual_style == "calm_trust":
            if seg.disfluency_type in (DisfluencyType.THINKING_PAUSE,):
                seg.action = DisfluencyAction.PRESERVE_EMPHASIS
                seg.reason += " (calm_trust: preserve)"
        elif visual_style == "serious_warning":
            if seg.disfluency_type in (DisfluencyType.AWKWARD_PAUSE, DisfluencyType.THINKING_PAUSE):
                seg.action = DisfluencyAction.CUT
                seg.reason += " (serious_warning: tighten)"
        elif visual_style == "revelation_hook":
            if seg.disfluency_type == DisfluencyType.THINKING_PAUSE:
                seg.action = DisfluencyAction.PRESERVE_EMPHASIS
                seg.reason += " (revelation_hook: dramatic pause)"

        # BTS lines → cover with B-roll
        if seg.disfluency_type == DisfluencyType.BTS_LINE:
            seg.action = DisfluencyAction.COVER_WITH_BROLL
            seg.cover_strategy = "broll"
            seg.reason += " (BTS: cover with B-roll)"

    return segments


# ── Robotic cut risk assessment ────────────────────────────────────────────────


def assess_robotic_cut_risk(
    edits: List[DisfluencyEdit],
    clip_duration: float,
) -> Tuple[int, str, List[str]]:
    """Assess risk of edits feeling robotic due to too many cuts.

    Returns (robotic_cut_count, risk_level, warnings).
    """
    cuts = [e for e in edits if e.action == DisfluencyAction.CUT]
    robotic_count = 0
    warnings: List[str] = []

    # Check cut density
    if len(cuts) > MAX_CUTS_PER_30S and clip_duration > 0:
        cuts_per_10s = len(cuts) / (clip_duration / 10)
        if cuts_per_10s > MAX_CUTS_PER_10S:
            robotic_count = len(cuts)
            warnings.append(
                f"High cut density: {cuts_per_10s:.1f} cuts per 10s "
                f"(max {MAX_CUTS_PER_10S})"
            )

    # Check minimum spacing between cuts
    cut_times = sorted([c.adjusted_start for c in cuts])
    for i in range(len(cut_times) - 1):
        gap = cut_times[i + 1] - cut_times[i]
        if gap < MIN_SEGMENT_BETWEEN_CUTS:
            robotic_count += 1
            warnings.append(
                f"Cuts too close: {gap:.2f}s gap at t={cut_times[i]:.1f}s"
            )

    # Determine risk level
    if robotic_count >= 5 or len(warnings) >= 3:
        risk = "high"
    elif robotic_count >= 2 or len(warnings) >= 1:
        risk = "medium"
    else:
        risk = "low"

    return robotic_count, risk, warnings


# ── Main builder ───────────────────────────────────────────────────────────────


def build_disfluency_edit_plan(
    words: List[Dict[str, Any]],
    clip_duration: float,
    visual_style: str = "calm_trust",
    enabled: bool = True,
) -> DisfluencyEditPlan:
    """Build a complete disfluency edit plan for a clip.

    This is the main entry point, analogous to Auto-Editor's core algorithm
    but operating on word-level disfluencies rather than raw silence.

    Args:
        words: List of word dicts with 'text', 'start', 'end' keys.
        clip_duration: Total duration of the clip in seconds.
        visual_style: Visual style preset name.
        enabled: Whether disfluency editing is enabled.

    Returns:
        DisfluencyEditPlan with all detected segments and edits.
    """
    plan = DisfluencyEditPlan(enabled=enabled)
    if not enabled or not words:
        return plan

    # 1. Detect all disfluency types
    fillers = detect_fillers(words)
    repetitions = detect_repetitions(words)
    false_starts = detect_false_starts(words)
    pauses = detect_awkward_pauses(words)

    # 2. Merge all segments, deduplicate by time range
    all_segments: List[DisfluencySegment] = []
    seen_ranges: set = set()

    for seg in fillers + repetitions + false_starts + pauses:
        key = (round(seg.start_s, 1), round(seg.end_s, 1))
        if key not in seen_ranges:
            seen_ranges.add(key)
            all_segments.append(seg)

    # 3. Assign actions based on visual style
    all_segments = assign_actions(all_segments, clip_duration, visual_style)

    # 4. Build edits
    edits: List[DisfluencyEdit] = []
    total_cut = 0.0
    total_compressed = 0.0

    for seg in all_segments:
        adj_start = max(0.0, seg.start_s - seg.padding_before)
        adj_end = min(clip_duration, seg.end_s + seg.padding_after)

        if seg.action == DisfluencyAction.CUT:
            new_dur = 0.0
            total_cut += adj_end - adj_start
        elif seg.action in (DisfluencyAction.COMPRESS, DisfluencyAction.SPEED_UP):
            orig_dur = adj_end - adj_start
            new_dur = orig_dur / seg.speed_factor
            total_compressed += orig_dur - new_dur
        else:
            new_dur = adj_end - adj_start

        edits.append(DisfluencyEdit(
            action=seg.action,
            segment=seg,
            adjusted_start=adj_start,
            adjusted_end=adj_end,
            new_duration=new_dur,
            metadata={
                "disfluency_type": seg.disfluency_type.name,
                "cover_strategy": seg.cover_strategy,
            },
        ))

    # 5. Assess robotic cut risk
    robotic_count, risk, risk_warnings = assess_robotic_cut_risk(edits, clip_duration)

    # 6. Populate plan
    plan.segments = all_segments
    plan.edits = edits
    plan.total_disfluencies = len(all_segments)
    plan.total_cut_duration = total_cut
    plan.total_compressed_duration = total_compressed
    plan.original_duration = clip_duration
    plan.new_duration = clip_duration - total_cut - total_compressed
    plan.robotic_cut_count = robotic_count
    plan.robotic_cut_risk = risk
    plan.robotic_cut_warnings = risk_warnings
    plan.broll_covers = sum(1 for e in edits if e.action == DisfluencyAction.COVER_WITH_BROLL)
    plan.transition_covers = sum(1 for e in edits if e.action == DisfluencyAction.COVER_WITH_TRANSITION)

    return plan


# ── Timeline integration ───────────────────────────────────────────────────────


def disfluency_plan_to_timeline_items(
    plan: DisfluencyEditPlan,
    clip_id: str,
) -> List[Dict[str, Any]]:
    """Convert a DisfluencyEditPlan to timeline items for ViraClipTimelinePlan.

    Returns a list of item dicts compatible with TimelineItem construction.
    Each CUT edit becomes a gap (no item).  Each COVER_WITH_BROLL edit
    becomes a B-roll item.  Each COVER_WITH_TRANSITION becomes a transition item.
    """
    items: List[Dict[str, Any]] = []
    for i, edit in enumerate(plan.edits):
        if edit.action == DisfluencyAction.COVER_WITH_BROLL:
            items.append({
                "item_id": f"{clip_id}_disfluency_broll_{i}",
                "track_kind": "BROLL",
                "time": {
                    "start": edit.adjusted_start,
                    "end": edit.adjusted_end,
                },
                "metadata": {
                    "source": "disfluency_cover",
                    "reason": edit.segment.reason,
                    "disfluency_type": edit.segment.disfluency_type.name,
                },
            })
        elif edit.action == DisfluencyAction.COVER_WITH_TRANSITION:
            items.append({
                "item_id": f"{clip_id}_disfluency_transition_{i}",
                "track_kind": "TRANSITION",
                "time": {
                    "start": edit.adjusted_start,
                    "end": edit.adjusted_end,
                },
                "metadata": {
                    "source": "disfluency_cover",
                    "reason": edit.segment.reason,
                    "disfluency_type": edit.segment.disfluency_type.name,
                },
            })

    return items


def apply_disfluency_items_to_timeline(
    plan: DisfluencyEditPlan,
    timeline_plan: Any,  # ViraClipTimelinePlan instance
    clip_id: str,
) -> List[str]:
    """Apply disfluency edits to a ViraClipTimelinePlan.

    For each COVER_WITH_BROLL edit, adds a BROLL track item.
    For each COVER_WITH_TRANSITION edit, adds a TRANSITION track item.
    CUT edits are represented as gaps (no item added).

    Returns a list of warning messages for any issues encountered.
    """
    warnings: List[str] = []
    if not plan.enabled or not plan.edits:
        return warnings

    items = disfluency_plan_to_timeline_items(plan, clip_id)
    for item_dict in items:
        track_kind_str = item_dict.get("track_kind", "")
        try:
            # Import here to avoid circular imports
            from vpi_timeline_plan import TrackKind, TimelineItem, TimeRange

            kind = TrackKind[track_kind_str]
            timeline_item = TimelineItem(
                item_id=item_dict["item_id"],
                track_kind=kind,
                time=TimeRange(
                    start=item_dict["time"]["start"],
                    end=item_dict["time"]["end"],
                ),
                metadata=item_dict.get("metadata", {}),
            )
            timeline_plan.get_or_create_track(kind).add_item(timeline_item)
        except (KeyError, ValueError, ImportError) as exc:
            warnings.append(
                f"Failed to apply disfluency item {item_dict.get('item_id', '?')}: {exc}"

            )

    return warnings


# ── OUTPUT-CUTS-8: applied cut plan (editorial treatment policy) ──────────────
#
# Bridges the *existing* detections (word gaps, phrase-level retakes/false
# starts/BTS lines from vpi_editorial_fluency_service, consecutive word
# duplicates) into physical media cuts for vpi_silence_editor's keep/concat
# renderer.  No new detector: it reuses the detection primitives above and the
# fluency-service line detectors, then applies the editorial treatment policy:
#   HARD_CUT            → remove physically (retakes, false starts, backstage)
#   COMPRESS_SILENCE    → reduce dead air >1.2s to 0.25-0.55s
#   KEEP_EDITORIAL_PAUSE→ preserve useful short pauses (no cut emitted)
#   MASK_WITH_VISUAL    → metadata-only suggestion (micro-disfluencies)
#   SFX_PUNCTUATE       → metadata-only suggestion (strong phrase after pause)

import logging as _logging

_oc_logger = _logging.getLogger(__name__)

_OC_SENTENCE_END = (".", "!", "?", "…", "...")
_OC_LINE_GAP_S = 0.45
_OC_LINE_MAX_WORDS = 14
_OC_HARD_DEAD_AIR_S = 1.2
_OC_COMPRESS_LEAVE_S = 0.30
_OC_LEADING_SILENCE_S = 0.8
_OC_LEADING_LEAVE_S = 0.25
_OC_MIN_LINE_CUT_S = 0.4
_OC_MIN_WORD_CUT_S = 0.12
_OC_MIN_FINAL_DURATION_S = 4.0
_OC_MICRO_REPAIR_MIN_S = 0.18
_OC_MICRO_REPAIR_MAX_S = 0.75
_OC_MICRO_REPAIR_MAX_PER_CLIP = 2

# ── OUTPUT-CUTS-8B: false-positive guard for false starts ─────────────────────
_OC_FALSE_START_GUARD_VERSION = "8b"
_OC_FS_PAUSE_EVIDENCE_S = 0.6
# Markers that on their own are NOT proof of a correction (rhetorical Spanish).
_OC_WEAK_CORRECTION_MARKERS = (
    "starts_with_auto_correction_no",
    "starts_with_auto_correction_bueno",
    "starts_with_auto_correction_digo",
    "starts_with_auto_correction_o sea",
    "starts_with_auto_correction_quiero decir",
    "starts_with_auto_correction_mejor dicho",
    "starts_with_auto_correction_es mas",
    "starts_with_auto_correction_es más",
)
# Phrases that DO prove the speaker is correcting herself.
_OC_EXPLICIT_CORRECTION_PHRASES = (
    "no no",
    "me equivoque",
    "espera",
    "otra vez",
    "vamos de nuevo",
    "de nuevo",
    "perdon",
    "rectifico",
    "corrijo",
    "disculpa",
    "repito",
    "corta eso",
)


def _oc_has_explicit_correction(normalized: str) -> bool:
    # Word-boundary match: "espera" must not match "esperas".
    padded = f" {normalized} "
    return any(f" {phrase} " in padded for phrase in _OC_EXPLICIT_CORRECTION_PHRASES)


# ── OUTPUT-NARRATIVE-9: rhetorical refrain protection ─────────────────────────
_OC_REFRAIN_THEME_TOKENS = (
    "salud", "avisa", "miedo", "tranquilidad", "proteccion", "protege",
    "conviene", "revisar", "contratar", "seguro", "seguros", "familia",
    "cuidado", "calma", "claridad", "importante", "respaldo", "prevenir",
)


def _oc_cluster_group_indices(indices: List[int]) -> List[List[int]]:
    """Adjacent line indices inside a repetition group form ONE instance — a
    phrase split by a pause ("La salud" + [pausa] + "no siempre avisa.") must be
    treated as a single occurrence, never as two cuttable repetitions."""
    clusters: List[List[int]] = []
    current = [indices[0]]
    for i in indices[1:]:
        if i - current[-1] <= 1:
            current.append(i)
        else:
            clusters.append(current)
            current = [i]
    clusters.append(current)
    return clusters


def _oc_is_rhetorical_refrain(
    lines: List[Dict[str, Any]],
    indices: List[int],
) -> Tuple[bool, str]:
    """A repeated phrase is a rhetorical refrain (protected), not retake junk,
    when 2-3 instances are separated by useful content, carry a thematic idea,
    and show no correction markers around them."""
    clusters = _oc_cluster_group_indices(indices)
    if len(clusters) < 2 or len(clusters) > 3:
        return False, "instance_count_outside_2_3"
    for prev, nxt in zip(clusters, clusters[1:]):
        between = lines[prev[-1] + 1:nxt[0]]
        if not any(int(l.get("word_count") or 0) >= 3 for l in between):
            return False, "no_useful_content_between"
    for i in indices:
        if _oc_has_explicit_correction(str(lines[i].get("normalized") or "")):
            return False, "explicit_correction_marker"
        if i + 1 < len(lines) and _oc_has_explicit_correction(str(lines[i + 1].get("normalized") or "")):
            return False, "correction_after_instance"
    base = max((lines[i] for i in indices), key=lambda l: int(l.get("word_count") or 0))
    wc = int(base.get("word_count") or 0)
    padded = f" {str(base.get('normalized') or '')} "
    thematic = any(f" {t} " in padded for t in _OC_REFRAIN_THEME_TOKENS)
    complete = str(base.get("text") or "").strip().endswith((".", "!", "?", "…"))
    if wc >= 3 and (thematic or (complete and wc >= 4)):
        return True, "separated_thematic_refrain" if thematic else "separated_complete_refrain"
    return False, "fragment_without_theme"


def _oc_validate_simulated_ending(kept_words: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """FASE 4: the simulated post-cut transcript must end on a closed idea."""
    if not kept_words:
        return False, "empty_transcript"
    tokens = [str(w.get("text") or "").strip() for w in kept_words if str(w.get("text") or "").strip()]
    if not tokens:
        return False, "empty_transcript"
    last_raw = tokens[-1]
    last_norm = _oc_normalize(last_raw)
    open_connectors = {
        "pero", "porque", "sino", "desde", "para", "cuando", "y", "o", "que",
        "de", "del", "la", "el", "en", "con", "al", "los", "las", "un", "una",
        "mi", "tu", "su", "es", "son", "como", "si", "a",
    }
    if last_norm in open_connectors:
        return False, f"open_connector_end:{last_norm}"
    last_has_punct = last_raw.rstrip().endswith((".", "!", "?", "…"))
    # Trailing fragment after the last closed sentence (catches "sino de... Por").
    frag_len = 0
    for tok in reversed(tokens[:-1] if last_has_punct else tokens):
        if tok.rstrip().endswith((".", "!", "?", "…")):
            break
        frag_len += 1
    if not last_has_punct and frag_len <= 2:
        return False, "trailing_fragment_after_close"
    return True, ""


def _oc_is_complete_short_question(line: Dict[str, Any]) -> bool:
    text = str(line.get("text") or "").strip()
    return text.endswith("?") and int(line.get("word_count") or 0) <= 6


def _oc_near_repeat_after(lines: List[Dict[str, Any]], idx: int, lookahead: int = 2) -> bool:
    base = set(str(lines[idx].get("normalized") or "").split())
    if not base:
        return False
    for j in range(idx + 1, min(len(lines), idx + 1 + lookahead)):
        other = set(str(lines[j].get("normalized") or "").split())
        smaller = min(len(base), len(other))
        if smaller and len(base & other) / smaller >= 0.6:
            return True
    return False


def _oc_false_start_evidence(
    lines: List[Dict[str, Any]],
    idx: int,
    reason: str,
) -> Tuple[bool, str, str]:
    """Decide whether a detected false start has real evidence behind it.

    Returns (confirmed, protect_log, evidence). When confirmed is False the
    candidate must be dropped and protect_log carries the log token to emit.
    """
    line = lines[idx]
    normalized = str(line.get("normalized") or "")
    word_count = int(line.get("word_count") or 0)
    explicit = _oc_has_explicit_correction(normalized)
    pause_after = 0.0
    if idx + 1 < len(lines):
        pause_after = float(lines[idx + 1].get("start") or 0.0) - float(line.get("end") or 0.0)
    near_repeat = _oc_near_repeat_after(lines, idx)

    if explicit:
        return True, "", "explicit_correction"
    if _oc_is_complete_short_question(line):
        return False, "VPI_OUTPUT_CUTS_SHORT_QUESTION_PROTECTED", ""
    if reason.startswith(_OC_WEAK_CORRECTION_MARKERS):
        # Rhetorical "No ..." (or bueno/digo/o sea) opening a complete thought:
        # only a real pause right after a very short fragment confirms it.
        if pause_after >= _OC_FS_PAUSE_EVIDENCE_S and word_count <= 3:
            return True, "", f"weak_marker_with_pause_{pause_after:.2f}s"
        if near_repeat:
            return True, "", "weak_marker_with_near_repeat"
        return False, "VPI_OUTPUT_CUTS_RETHORICAL_NO_PROTECTED", ""
    if idx == 0:
        # First line of the clip: strong evidence only.
        if near_repeat:
            return True, "", "first_line_near_repeat"
        if pause_after >= _OC_FS_PAUSE_EVIDENCE_S and word_count <= 3:
            return True, "", f"first_line_pause_{pause_after:.2f}s"
        return False, "VPI_OUTPUT_CUTS_FALSE_START_PROTECTED", ""
    # Generic temporal-evidence requirement.
    if pause_after >= _OC_FS_PAUSE_EVIDENCE_S or near_repeat:
        return True, "", f"pause_{pause_after:.2f}s" if pause_after >= _OC_FS_PAUSE_EVIDENCE_S else "near_repeat"
    return False, "VPI_OUTPUT_CUTS_FALSE_START_PROTECTED", ""



def _oc_normalize(text: str) -> str:
    import re
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _oc_words_to_lines(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group clip-relative word timestamps into analysis lines.

    Splits on sentence punctuation, on word gaps >= _OC_LINE_GAP_S, or when a
    line grows past _OC_LINE_MAX_WORDS.  The lines feed the existing
    phrase-level detectors of vpi_editorial_fluency_service.
    """
    lines: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []

    def _flush() -> None:
        if not current:
            return
        text = " ".join(str(w.get("text") or "").strip() for w in current).strip()
        if not text:
            current.clear()
            return
        lines.append({
            "start": float(current[0].get("start") or 0.0),
            "end": float(current[-1].get("end") or 0.0),
            "text": text,
            "normalized": _oc_normalize(text),
            "word_count": len(current),
        })
        current.clear()

    prev_end: Optional[float] = None
    for w in words or []:
        start = float(w.get("start") or 0.0)
        if prev_end is not None and start - prev_end >= _OC_LINE_GAP_S:
            _flush()
        current.append(w)
        prev_end = float(w.get("end") or start)
        token = str(w.get("text") or "").strip()
        if token.endswith(_OC_SENTENCE_END) or len(current) >= _OC_LINE_MAX_WORDS:
            _flush()
    _flush()
    return lines


def _oc_overlaps(start: float, end: float, ranges: List[Tuple[float, float]]) -> bool:
    return any(start < r_end and end > r_start for r_start, r_end in ranges)


def _oc_overlap_duration(start: float, end: float, ranges: List[Tuple[float, float]]) -> float:
    total = 0.0
    for r_start, r_end in ranges:
        total += max(0.0, min(end, r_end) - max(start, r_start))
    return round(total, 3)


def _oc_is_content_word(token: str) -> bool:
    return token not in {
        "a", "al", "de", "del", "el", "la", "los", "las", "un", "una",
        "unos", "unas", "y", "o", "que", "se", "es", "son", "con",
        "por", "pero", "sino", "no", "eso",
    }


def _oc_find_micro_repetition_repairs(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find short repeated-token repairs that line-level planning cannot cut."""
    repairs: List[Dict[str, Any]] = []
    accepted_ranges: List[Tuple[float, float]] = []
    for i, word in enumerate(words[:-1]):
        token = _oc_normalize(str(word.get("text") or ""))
        if not token or len(token) < 2:
            continue
        if token not in {"por", "eso", "no", "pero", "sino"}:
            continue
        start = float(word.get("start") or 0.0)
        end = float(word.get("end") or start)
        dur = end - start
        if dur < _OC_MICRO_REPAIR_MIN_S or dur > _OC_MICRO_REPAIR_MAX_S:
            continue
        later_idx: Optional[int] = None
        for j in range(i + 1, min(len(words), i + 9)):
            other = _oc_normalize(str(words[j].get("text") or ""))
            if other != token:
                continue
            gap = float(words[j].get("start") or 0.0) - end
            if 0.0 <= gap <= 6.0:
                later_idx = j
                break
        if later_idx is None:
            continue
        prev_tok = _oc_normalize(str(words[i - 1].get("text") or "")) if i > 0 else ""
        next_tok = _oc_normalize(str(words[i + 1].get("text") or "")) if i + 1 < len(words) else ""
        later_next = _oc_normalize(str(words[later_idx + 1].get("text") or "")) if later_idx + 1 < len(words) else ""
        phrase_restart = bool(next_tok and later_next and next_tok == later_next)
        connector_context = prev_tok in {"sino", "de", "trata", "perdon", "perdón", "eh", "mmm", "no"}
        connector_restart = token in {"por", "eso", "pero", "sino", "no"} and later_idx - i <= 7 and connector_context
        if token in {"por", "eso", "pero", "sino", "no"} and not connector_context:
            _oc_logger.info(
                "VPI_MICRO_REPETITION_REJECTED start=%.3f token=%s reason=no_restart_context",
                start, token,
            )
            continue
        if _oc_is_content_word(token) and not phrase_restart and not connector_restart:
            _oc_logger.info(
                "VPI_MICRO_REPETITION_REJECTED start=%.3f token=%s reason=unique_content_risk",
                start, token,
            )
            continue
        if i >= len(words) - 8:
            _oc_logger.info(
                "VPI_MICRO_REPETITION_REJECTED start=%.3f token=%s reason=closure_risk",
                start, token,
            )
            continue
        gap_before = start - float(words[i - 1].get("end") or start) if i > 0 else start
        gap_after = float(words[i + 1].get("start") or end) - end if i + 1 < len(words) else 0.0
        expanded_start = max(0.0, start - min(0.10, max(0.0, gap_before * 0.5)))
        expanded_end = end + min(0.10, max(0.0, gap_after * 0.5))
        if _oc_overlaps(expanded_start, expanded_end, accepted_ranges):
            _oc_logger.info(
                "VPI_MICRO_REPETITION_REJECTED start=%.3f token=%s reason=overlap",
                start, token,
            )
            continue
        if len(repairs) >= _OC_MICRO_REPAIR_MAX_PER_CLIP:
            _oc_logger.info(
                "VPI_MICRO_REPETITION_REJECTED start=%.3f token=%s reason=budget_exceeded",
                start, token,
            )
            continue
        treatment = "MICRO_STITCH" if expanded_end - expanded_start < 0.35 else "HARD_CUT"
        repair = {
            "start_s": round(expanded_start, 3),
            "end_s": round(expanded_end, 3),
            "treatment": treatment,
            "priority": 6,
            "confidence": 0.86 if phrase_restart else 0.78,
            "reason": f"micro_repetition_repair:{token[:20]}",
            "text_preview": token[:30],
            "micro_repetition_original_span": [round(start, 3), round(end, 3)],
            "micro_repetition_expanded_span": [round(expanded_start, 3), round(expanded_end, 3)],
            "micro_repetition_crossfade_frames": 5,
            "micro_repetition_audio_crossfade_ms": 40,
        }
        _oc_logger.info(
            "VPI_REPETITION_MICRO_REPAIR_CANDIDATE start=%.3f end=%.3f reason=%s",
            float(repair["start_s"]), float(repair["end_s"]), repair["reason"],
        )
        _oc_logger.info(
            "VPI_MICRO_REPETITION_REPAIR_SELECTED start=%.3f end=%.3f treatment=%s",
            float(repair["start_s"]), float(repair["end_s"]), treatment,
        )
        _oc_logger.info("VPI_MICRO_REPETITION_AUDIO_CROSSFADE ms=40")
        _oc_logger.info("VPI_MICRO_REPETITION_VIDEO_CROSSFADE frames=5")
        repairs.append(repair)
        accepted_ranges.append((expanded_start, expanded_end))
    return repairs


def _oc_micro_repair_retained_word_overlap(
    start: float,
    end: float,
    words: List[Dict[str, Any]],
) -> bool:
    """Return true if the span clips an adjacent retained word."""
    for word in words:
        w_start = float(word.get("start") or 0.0)
        w_end = float(word.get("end") or w_start)
        if end <= w_start or start >= w_end:
            continue
        # The repeated word itself is expected to be fully covered.  Partial
        # coverage indicates the repair would cut a retained word/phoneme.
        if start <= w_start + 0.01 and end >= w_end - 0.01:
            continue
        return True
    return False


def _oc_classify_micro_repair_pause_overlap(
    candidate: Dict[str, Any],
    *,
    start: float,
    end: float,
    preserved_ranges: List[Tuple[float, float]],
    words: List[Dict[str, Any]],
    tail_protect_start: float,
) -> Tuple[bool, float, float, str, Dict[str, Any]]:
    """Classify preserved-pause overlap for micro repairs.

    Generic preserved-pause rejection is too coarse for restart-token repairs:
    the protected pause can be the breath/restart gap that makes the duplicate
    audible.  This keeps hard protections but allows safe, local consumption.
    """
    overlap_s = _oc_overlap_duration(start, end, preserved_ranges)
    meta: Dict[str, Any] = {
        "micro_repair_overlap_duration_s": overlap_s,
        "micro_repair_pause_consumed": False,
        "micro_repair_padding_shrunk": False,
    }
    if overlap_s <= 0:
        meta["micro_repair_overlap_class"] = "NO_OVERLAP"
        meta["micro_repair_acceptance_reason"] = "no_preserved_pause_overlap"
        return True, start, end, "NO_OVERLAP", meta

    if end > tail_protect_start:
        meta["micro_repair_overlap_class"] = "CLOSURE_OR_REFRAIN_OVERLAP"
        meta["micro_repair_acceptance_reason"] = "reject_tail_protection"
        return False, start, end, "CLOSURE_OR_REFRAIN_OVERLAP", meta

    original = candidate.get("micro_repetition_original_span") or [start, end]
    try:
        orig_start = float(original[0])
        orig_end = float(original[1])
    except Exception:
        orig_start, orig_end = start, end

    padding_only = all(
        max(0.0, min(orig_end, r_end) - max(orig_start, r_start)) <= 0.01
        for r_start, r_end in preserved_ranges
        if start < r_end and end > r_start
    )
    if padding_only:
        shrunk_start = max(start, orig_start)
        shrunk_end = min(end, orig_end)
        if shrunk_end - shrunk_start >= 0.08 and not _oc_micro_repair_retained_word_overlap(shrunk_start, shrunk_end, words):
            meta.update({
                "micro_repair_overlap_class": "CANDIDATE_PADDING_OVERLAP",
                "micro_repair_padding_shrunk": True,
                "micro_repair_acceptance_reason": "padding_shrunk_to_original_word_span",
            })
            _oc_logger.info(
                "VPI_MICRO_REPAIR_PADDING_SHRUNK start=%.3f end=%.3f shrunk_start=%.3f shrunk_end=%.3f overlap=%.3f",
                start, end, shrunk_start, shrunk_end, overlap_s,
            )
            return True, round(shrunk_start, 3), round(shrunk_end, 3), "CANDIDATE_PADDING_OVERLAP", meta
        meta["micro_repair_overlap_class"] = "RETAINED_WORD_OVERLAP"
        meta["micro_repair_acceptance_reason"] = "reject_padding_shrink_would_clip_word"
        return False, start, end, "RETAINED_WORD_OVERLAP", meta

    if _oc_micro_repair_retained_word_overlap(start, end, words):
        meta["micro_repair_overlap_class"] = "RETAINED_WORD_OVERLAP"
        meta["micro_repair_acceptance_reason"] = "reject_retained_word_overlap"
        return False, start, end, "RETAINED_WORD_OVERLAP", meta

    if overlap_s <= 0.12:
        meta.update({
            "micro_repair_overlap_class": "ADJACENT_BREATH_OVERLAP",
            "micro_repair_pause_consumed": True,
            "micro_repair_acceptance_reason": "consume_short_adjacent_breath",
        })
        _oc_logger.info(
            "VPI_MICRO_REPAIR_PAUSE_CONSUMED start=%.3f end=%.3f overlap=%.3f class=ADJACENT_BREATH_OVERLAP",
            start, end, overlap_s,
        )
        return True, start, end, "ADJACENT_BREATH_OVERLAP", meta

    meta.update({
        "micro_repair_overlap_class": "SELF_GENERATED_PAUSE_OVERLAP",
        "micro_repair_pause_consumed": True,
        "micro_repair_acceptance_reason": "consume_restart_group_pause",
    })
    _oc_logger.info(
        "VPI_MICRO_REPAIR_PAUSE_CONSUMED start=%.3f end=%.3f overlap=%.3f class=SELF_GENERATED_PAUSE_OVERLAP",
        start, end, overlap_s,
    )
    return True, start, end, "SELF_GENERATED_PAUSE_OVERLAP", meta


def build_output_cut_plan(
    *,
    words: List[Dict[str, Any]],
    clip_duration: float,
    silence_segments: Optional[List[Dict[str, Any]]] = None,
    existing_cuts: Optional[List[Dict[str, Any]]] = None,
    source_start_s: float = 0.0,
    max_total_cut_s: Optional[float] = None,
    protect_tail_s: float = 1.2,
) -> Dict[str, Any]:
    """Build the applied_cut_plan contract from already-detected disfluencies.

    Returns a dict with: source_start_s, source_end_s, cuts, keep_segments,
    total_cut_seconds, final_duration_after_cuts, cut_plan_source,
    cuts_detected_count, treatments, suggestions (metadata-only) and
    skip_reason when nothing is applicable.
    """
    duration = max(0.0, float(clip_duration or 0.0))
    plan: Dict[str, Any] = {
        "source_start_s": round(float(source_start_s or 0.0), 3),
        "source_end_s": round(float(source_start_s or 0.0) + duration, 3),
        "cuts": [],
        "keep_segments": [],
        "total_cut_seconds": 0.0,
        "final_duration_after_cuts": round(duration, 3),
        "cut_plan_source": "vpi_disfluency_editor+vpi_editorial_fluency_service+word_gaps",
        "cuts_detected_count": 0,
        "treatments": {},
        "suggestions": [],
        "skip_reason": "",
        "protected_cut_candidates_count": 0,
        "protected_cut_reasons": [],
        "false_start_guard_version": _OC_FALSE_START_GUARD_VERSION,
        "narrative_refrain_detected": False,
        "protected_refrain_text": [],
        "protected_refrain_reason": [],
        "repetition_cut_blocked_count": 0,
        "needs_review_reason": "",
        "micro_repetition_repairs_planned": 0,
        "micro_repetition_repairs_applied": 0,
        "micro_repetition_original_span": [],
        "micro_repetition_expanded_span": [],
        "micro_repetition_crossfade_frames": 0,
        "micro_repetition_audio_crossfade_ms": 0,
        "micro_repetition_skip_reason": "",
        "micro_repair_overlap_class": [],
        "micro_repair_overlap_duration_s": [],
        "micro_repair_pause_consumed": [],
        "micro_repair_padding_shrunk": [],
        "micro_repair_acceptance_reason": [],
        "intentional_pause_inserted": False,
        "intentional_pause_start_s": 0.0,
        "intentional_pause_duration_s": 0.0,
        "intentional_pause_reason": "",
    }
    if not words or duration <= 1.0:
        plan["skip_reason"] = "no_word_timestamps" if not words else "clip_too_short"
        return plan

    budget = float(max_total_cut_s) if max_total_cut_s else max(2.5, min(12.0, duration * 0.45))
    existing_ranges: List[Tuple[float, float]] = [
        (float(c.get("start_s") or 0.0), float(c.get("end_s") or 0.0))
        for c in (existing_cuts or [])
    ]
    last_word_end = float(words[-1].get("end") or duration)
    tail_protect_start = max(0.0, last_word_end - protect_tail_s)

    preserved_ranges: List[Tuple[float, float]] = []
    for seg in silence_segments or []:
        action = str(seg.get("action") or "")
        dur_s = float(seg.get("duration_s") or 0.0)
        if action in {"preserve_for_tension", "pattern_interruption", "preserve_and_emphasize", "preserve"} and dur_s < _OC_HARD_DEAD_AIR_S:
            preserved_ranges.append((float(seg.get("start_s") or 0.0), float(seg.get("end_s") or 0.0)))

    candidates: List[Dict[str, Any]] = []
    suggestions: List[Dict[str, Any]] = []

    # 1. Phrase-level retakes / false starts / backstage lines (existing detectors).
    lines = _oc_words_to_lines(words)
    if len(lines) >= 2:
        try:
            from .vpi_editorial_fluency_service import (
                _detect_repetition_groups,
                _detect_false_starts,
                _detect_bts_lines,
            )
            removed_line_idx: set = set()
            for idx in _detect_bts_lines(lines):
                if idx in removed_line_idx or idx == len(lines) - 1:
                    continue
                line = lines[idx]
                candidates.append({
                    "start_s": line["start"], "end_s": line["end"],
                    "treatment": "HARD_CUT", "priority": 0, "confidence": 0.9,
                    "reason": "backstage_line", "text_preview": line["text"][:60],
                })
                removed_line_idx.add(idx)
            refrain_protected_texts: List[str] = []
            refrain_reasons: List[str] = []
            repetition_cut_blocked = 0
            for group in _detect_repetition_groups(lines):
                indices = sorted(int(i) for i in (group.get("indices") or []))
                if len(indices) < 2:
                    continue
                is_refrain, refrain_reason = _oc_is_rhetorical_refrain(lines, indices)
                group_text = lines[indices[0]]["text"][:60]
                if is_refrain:
                    repetition_cut_blocked += len(indices) - 1
                    refrain_protected_texts.append(group_text)
                    refrain_reasons.append(refrain_reason)
                    _oc_logger.info(
                        "VPI_OUTPUT_NARRATIVE_REFRAIN_DETECTED text=%s instances=%d",
                        group_text, len(indices),
                    )
                    _oc_logger.info(
                        "VPI_OUTPUT_NARRATIVE_REFRAIN_PROTECTED text=%s reason=%s",
                        group_text, refrain_reason,
                    )
                    _oc_logger.info(
                        "VPI_OUTPUT_NARRATIVE_REPETITION_CUT_BLOCKED text=%s count=%d",
                        group_text, len(indices) - 1,
                    )
                    continue
                # Cut whole instances (clusters), keeping the most complete one
                # so a truncated refrain can never be left behind; ties resolve
                # to the LAST take, which is normally the good one.  A single
                # cluster means adjacent stutter: fall back to line-level units.
                clusters = _oc_cluster_group_indices(indices)
                units = [[i] for i in clusters[0]] if len(clusters) == 1 else clusters
                def _unit_words(unit: List[int]) -> int:
                    return sum(int(lines[i].get("word_count") or 0) for i in unit)
                keep_unit = max(units, key=lambda u: (_unit_words(u), u[-1]))
                _oc_logger.info(
                    "VPI_OUTPUT_NARRATIVE_REPETITION_CUT_ALLOWED text=%s keep_lines=%s instances=%d reason=%s",
                    group_text, ",".join(str(i) for i in keep_unit), len(units), refrain_reason,
                )
                for unit in units:
                    if unit is keep_unit:
                        continue
                    # OUTPUT-CUTS-30: cut a non-kept duplicate instance as ONE contiguous
                    # span instead of line-by-line. A repeat split into short (<0.4s) sub-lines
                    # was silently left in (each sub-line failed the per-line min length); the
                    # span (whole duplicate phrase) clears the threshold. Closure protection
                    # (never cut the clip's last line) and overlap protection stay at unit level.
                    unit_idx = [ix for ix in unit if ix not in removed_line_idx]
                    if not unit_idx:
                        continue
                    if any(ix == len(lines) - 1 for ix in unit_idx):
                        continue
                    u_start = min(lines[ix]["start"] for ix in unit_idx)
                    u_end = max(lines[ix]["end"] for ix in unit_idx)
                    if u_end - u_start < _OC_MIN_LINE_CUT_S:
                        continue
                    candidates.append({
                        "start_s": u_start, "end_s": u_end,
                        "treatment": "HARD_CUT", "priority": 1, "confidence": 0.9,
                        "reason": f"retake_repetition_keep_last:{str(group.get('type') or 'exact_repeat')}",
                        "text_preview": lines[unit_idx[0]]["text"][:60],
                    })
                    for ix in unit_idx:
                        removed_line_idx.add(ix)
            plan["narrative_refrain_detected"] = bool(refrain_protected_texts)
            plan["protected_refrain_text"] = refrain_protected_texts
            plan["protected_refrain_reason"] = refrain_reasons
            plan["repetition_cut_blocked_count"] = repetition_cut_blocked
            protected_count = 0
            protected_reasons: List[str] = []
            for fs in _detect_false_starts(lines):
                idx = int(fs.get("index") or 0)
                if idx in removed_line_idx or idx == len(lines) - 1:
                    continue
                line = lines[idx]
                if line["end"] - line["start"] < _OC_MIN_LINE_CUT_S:
                    continue
                fs_reason = str(fs.get("reason") or "")
                confirmed, protect_log, evidence = _oc_false_start_evidence(lines, idx, fs_reason)
                if not confirmed:
                    protected_count += 1
                    protected_reasons.append(f"{protect_log}:{fs_reason[:40]}")
                    _oc_logger.info(
                        "%s text=%s reason=%s",
                        protect_log,
                        line["text"][:60],
                        fs_reason[:60],
                    )
                    continue
                _oc_logger.info(
                    "VPI_OUTPUT_CUTS_FALSE_START_CONFIRMED text=%s evidence=%s",
                    line["text"][:60],
                    evidence,
                )
                candidates.append({
                    "start_s": line["start"], "end_s": line["end"],
                    "treatment": "HARD_CUT", "priority": 2, "confidence": 0.85,
                    "reason": f"false_start:{fs_reason[:40]}",
                    "text_preview": line["text"][:60],
                })
                removed_line_idx.add(idx)
            # Explicit correction lines ("me equivoqué, repito", "espera…") are
            # hard cuts even when the upstream detector misses them.
            for idx, line in enumerate(lines):
                if idx in removed_line_idx or idx == len(lines) - 1:
                    continue
                if int(line.get("word_count") or 0) > 6:
                    continue
                if line["end"] - line["start"] < 0.2:
                    continue
                if _oc_has_explicit_correction(str(line.get("normalized") or "")):
                    _oc_logger.info(
                        "VPI_OUTPUT_CUTS_FALSE_START_CONFIRMED text=%s evidence=explicit_correction_line",
                        line["text"][:60],
                    )
                    candidates.append({
                        "start_s": line["start"], "end_s": line["end"],
                        "treatment": "HARD_CUT", "priority": 2, "confidence": 0.9,
                        "reason": "explicit_correction_line",
                        "text_preview": line["text"][:60],
                    })
                    removed_line_idx.add(idx)
            if protected_count:
                _oc_logger.info(
                    "VPI_OUTPUT_CUTS_FALSE_POSITIVE_GUARD_APPLIED version=%s protected=%d reasons=%s",
                    _OC_FALSE_START_GUARD_VERSION,
                    protected_count,
                    "|".join(protected_reasons)[:200],
                )
            plan["protected_cut_candidates_count"] = protected_count
            plan["protected_cut_reasons"] = protected_reasons
            plan["false_start_guard_version"] = _OC_FALSE_START_GUARD_VERSION
        except Exception as exc:  # pragma: no cover - defensive import bridge
            _oc_logger.debug("[output-cuts] line_detectors_skipped reason=%s", exc)

    # 2. Consecutive duplicated word (true stutter: "por por", "la la").
    for i in range(len(words) - 1):
        a = _oc_normalize(str(words[i].get("text") or ""))
        b = _oc_normalize(str(words[i + 1].get("text") or ""))
        if not a or len(a) < 2 or a != b:
            continue
        gap = float(words[i + 1].get("start") or 0.0) - float(words[i].get("end") or 0.0)
        if gap > 0.6:
            continue
        start = float(words[i].get("start") or 0.0)
        end = float(words[i + 1].get("start") or 0.0)
        if end - start >= _OC_MIN_WORD_CUT_S:
            candidates.append({
                "start_s": start, "end_s": end,
                "treatment": "HARD_CUT", "priority": 5, "confidence": 0.85,
                "reason": f"word_stutter:{a[:20]}", "text_preview": a[:30],
            })

    # 2b. Non-consecutive short restart tokens ("por eso ... por eso ...").
    micro_repairs = _oc_find_micro_repetition_repairs(words)
    plan["micro_repetition_repairs_planned"] = len(micro_repairs)
    if micro_repairs:
        candidates.extend(micro_repairs)
    else:
        plan["micro_repetition_skip_reason"] = "no_safe_micro_repetition"

    # 3. Silences: leading dead start + long internal dead air (COMPRESS_SILENCE).
    first_word_start = float(words[0].get("start") or 0.0)
    if first_word_start >= _OC_LEADING_SILENCE_S:
        candidates.append({
            "start_s": 0.0, "end_s": round(first_word_start - _OC_LEADING_LEAVE_S, 3),
            "treatment": "COMPRESS_SILENCE", "priority": 3, "confidence": 0.9,
            "reason": "leading_silence", "text_preview": "",
        })
    for i in range(len(words) - 1):
        gap_start = float(words[i].get("end") or 0.0)
        gap_end = float(words[i + 1].get("start") or 0.0)
        gap = gap_end - gap_start
        if gap < _OC_HARD_DEAD_AIR_S:
            if 0.5 <= gap < _OC_HARD_DEAD_AIR_S and _oc_overlaps(gap_start, gap_end, preserved_ranges):
                suggestions.append({
                    "treatment": "SFX_PUNCTUATE", "start_s": round(gap_end, 3),
                    "reason": "strong_phrase_after_preserved_pause",
                })
            continue
        candidates.append({
            "start_s": round(gap_start + _OC_COMPRESS_LEAVE_S, 3), "end_s": round(gap_end, 3),
            "treatment": "COMPRESS_SILENCE", "priority": 4, "confidence": 0.86,
            "reason": f"dead_air_{gap:.1f}s_compress", "text_preview": "",
        })

    # 4. Micro-disfluency mask suggestions (metadata only, never rendered here).
    for w in words:
        token = _oc_normalize(str(w.get("text") or ""))
        if token in {"eh", "mmm", "um", "ah"}:
            suggestions.append({
                "treatment": "MASK_WITH_VISUAL", "start_s": round(float(w.get("start") or 0.0), 3),
                "reason": f"micro_filler:{token}",
            })

    plan["cuts_detected_count"] = len(candidates)
    plan["suggestions"] = suggestions[:8]
    if not candidates:
        plan["skip_reason"] = "no_applicable_cuts"
        return plan

    # Clamp, drop overlaps with existing cuts / preserved pauses / tail zone.
    filtered: List[Dict[str, Any]] = []
    for c in candidates:
        start = max(0.0, min(duration, float(c["start_s"])))
        end = max(start, min(duration, float(c["end_s"])))
        if end - start < 0.08:
            continue
        if end > tail_protect_start and str(c.get("reason") or "") != "backstage_line":
            end = min(end, tail_protect_start)
            if end - start < 0.08:
                continue
        is_micro_repair = str(c.get("reason") or "").startswith("micro_repetition_repair:")
        if is_micro_repair:
            _oc_logger.info(
                "VPI_MICRO_REPAIR_ACCEPTANCE_ENTER start=%.3f end=%.3f reason=%s",
                start, end, str(c.get("reason") or ""),
            )
        if _oc_overlaps(start, end, existing_ranges):
            if is_micro_repair:
                plan["micro_repetition_skip_reason"] = "overlaps_existing_cut"
                _oc_logger.info(
                    "VPI_MICRO_REPAIR_REJECTED start=%.3f end=%.3f reason=overlaps_existing_cut",
                    start, end,
                )
            continue
        if _oc_overlaps(start, end, preserved_ranges):
            if not is_micro_repair:
                continue
            accept_micro, start, end, overlap_class, overlap_meta = _oc_classify_micro_repair_pause_overlap(
                c,
                start=start,
                end=end,
                preserved_ranges=preserved_ranges,
                words=words,
                tail_protect_start=tail_protect_start,
            )
            _oc_logger.info(
                "VPI_MICRO_REPAIR_OVERLAP_CLASSIFIED start=%.3f end=%.3f class=%s overlap=%.3f accepted=%s",
                start, end, overlap_class, float(overlap_meta.get("micro_repair_overlap_duration_s") or 0.0), accept_micro,
            )
            if not accept_micro:
                plan["micro_repetition_skip_reason"] = str(overlap_meta.get("micro_repair_acceptance_reason") or overlap_class)
                _oc_logger.info(
                    "VPI_MICRO_REPAIR_REJECTED start=%.3f end=%.3f reason=%s",
                    start, end, plan["micro_repetition_skip_reason"],
                )
                continue
            c = {**c, **overlap_meta}
        elif is_micro_repair:
            c = {
                **c,
                "micro_repair_overlap_class": "NO_OVERLAP",
                "micro_repair_overlap_duration_s": 0.0,
                "micro_repair_pause_consumed": False,
                "micro_repair_padding_shrunk": False,
                "micro_repair_acceptance_reason": "no_preserved_pause_overlap",
            }
        if is_micro_repair:
            _oc_logger.info(
                "VPI_MICRO_REPAIR_PHYSICAL_ACCEPTED start=%.3f end=%.3f class=%s",
                start, end, str(c.get("micro_repair_overlap_class") or "NO_OVERLAP"),
            )
        filtered.append({**c, "start_s": round(start, 3), "end_s": round(end, 3)})

    # Merge overlapping candidates (keep highest priority metadata).
    filtered.sort(key=lambda c: (c["start_s"], c["priority"]))
    merged: List[Dict[str, Any]] = []
    for c in filtered:
        if merged and c["start_s"] < merged[-1]["end_s"]:
            merged[-1]["end_s"] = round(max(merged[-1]["end_s"], c["end_s"]), 3)
            continue
        merged.append(dict(c))

    # Budget: take by priority (backstage > retake > false start > silences > stutter).
    merged.sort(key=lambda c: (c["priority"], -(c["end_s"] - c["start_s"])))
    accepted: List[Dict[str, Any]] = []
    total = 0.0
    for c in merged:
        removed = c["end_s"] - c["start_s"]
        if total + removed > budget:
            continue
        if duration - (total + removed) < _OC_MIN_FINAL_DURATION_S:
            continue
        if len(accepted) >= 8:
            break
        accepted.append(c)
        total = round(total + removed, 3)
    if not accepted:
        plan["skip_reason"] = "budget_or_safety_filtered_all"
        return plan
    accepted.sort(key=lambda c: c["start_s"])

    # Snap pass: HARD_CUTs of whole lines leave slivers of silence around the
    # removed take.  Extend each hard cut backwards to the previous kept word
    # (or to 0.0 when the cut opens the clip) and forwards to just before the
    # next kept word, so the cut timeline stays tight and natural.
    word_bounds = [(float(w.get("start") or 0.0), float(w.get("end") or 0.0)) for w in words]
    for c in accepted:
        if c.get("treatment") != "HARD_CUT":
            continue
        if str(c.get("reason") or "").startswith("micro_repetition_repair:"):
            continue
        prev_word_end = max((e for _s, e in word_bounds if e <= c["start_s"] + 0.01), default=None)
        if prev_word_end is None:
            c["start_s"] = 0.0
        elif c["start_s"] - prev_word_end <= 0.8:
            # 0.12s padding: whisper end timestamps run short and a tighter cut
            # audibly clips the tail of the kept word (e.g. "pensadas").
            c["start_s"] = round(max(0.0, prev_word_end + 0.12), 3)
        next_word_start = min((b for b, _e in word_bounds if b >= c["end_s"] - 0.01), default=None)
        if next_word_start is not None and next_word_start - c["end_s"] <= 1.0:
            c["end_s"] = round(max(c["end_s"], next_word_start - 0.20), 3)
    # Re-merge in case snapping created overlaps, then recompute the total.
    accepted.sort(key=lambda c: c["start_s"])
    snapped: List[Dict[str, Any]] = []
    for c in accepted:
        if snapped and c["start_s"] < snapped[-1]["end_s"]:
            snapped[-1]["end_s"] = round(max(snapped[-1]["end_s"], c["end_s"]), 3)
            continue
        snapped.append(c)
    accepted = snapped
    total = round(sum(c["end_s"] - c["start_s"] for c in accepted), 3)
    if duration - total < _OC_MIN_FINAL_DURATION_S:
        plan["skip_reason"] = "snap_pass_exceeded_safety_floor"
        return plan

    # ── OUTPUT-NARRATIVE-9 FASE 4: simulate the final transcript after cuts and
    # validate the ending; drop trailing cuts (up to 2) if they truncate the close.
    def _oc_kept_words(cuts_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ranges = [(float(c["start_s"]), float(c["end_s"])) for c in cuts_list]
        return [
            w for w in words
            if not any(
                r0 <= (float(w.get("start") or 0.0) + float(w.get("end") or 0.0)) / 2.0 < r1
                for r0, r1 in ranges
            )
        ]

    sim_attempts = 0
    while True:
        kept_words = _oc_kept_words(accepted)
        sim_tail = " ".join(str(w.get("text") or "").strip() for w in kept_words[-12:])
        ok, fail_reason = _oc_validate_simulated_ending(kept_words)
        _oc_logger.info(
            "VPI_OUTPUT_NARRATIVE_FINAL_TRANSCRIPT_SIMULATED words=%d tail=%s",
            len(kept_words), sim_tail[-90:],
        )
        if ok:
            _oc_logger.info("VPI_OUTPUT_NARRATIVE_FINAL_TRANSCRIPT_PASSED")
            break
        _oc_logger.info("VPI_OUTPUT_NARRATIVE_FINAL_TRANSCRIPT_FAILED reason=%s", fail_reason)
        # Only retry when a cut near the clip tail could be the culprit.
        if sim_attempts >= 2 or not accepted or float(accepted[-1]["end_s"]) < tail_protect_start - 2.0:
            plan["needs_review_reason"] = f"narrative_final_transcript_weak:{fail_reason}"
            break
        sim_attempts += 1
        dropped = accepted.pop()
        _oc_logger.info(
            "VPI_OUTPUT_NARRATIVE_FINAL_TRANSCRIPT_RETRY dropped_cut=%s reason=%s",
            str(dropped.get("reason") or "")[:50], fail_reason,
        )
        total = round(sum(c["end_s"] - c["start_s"] for c in accepted), 3)
    if not accepted:
        plan["skip_reason"] = "all_cuts_dropped_by_final_transcript_guard"
        return plan

    keep_segments: List[Dict[str, Any]] = []
    cursor = 0.0
    new_cursor = 0.0
    for c in accepted:
        if c["start_s"] - cursor > 0.03:
            seg_len = c["start_s"] - cursor
            keep_segments.append({
                "start_s": round(new_cursor, 3), "end_s": round(new_cursor + seg_len, 3),
                "source_start_s": round(float(source_start_s or 0.0) + cursor, 3),
                "source_end_s": round(float(source_start_s or 0.0) + c["start_s"], 3),
            })
            new_cursor += seg_len
        cursor = max(cursor, c["end_s"])
    if duration - cursor > 0.03:
        seg_len = duration - cursor
        keep_segments.append({
            "start_s": round(new_cursor, 3), "end_s": round(new_cursor + seg_len, 3),
            "source_start_s": round(float(source_start_s or 0.0) + cursor, 3),
            "source_end_s": round(float(source_start_s or 0.0) + duration, 3),
        })
        new_cursor += seg_len

    treatments: Dict[str, int] = {}
    for c in accepted:
        treatments[c["treatment"]] = treatments.get(c["treatment"], 0) + 1
    for seg in silence_segments or []:
        if str(seg.get("action") or "") in {"preserve", "preserve_for_tension", "preserve_and_emphasize"}:
            treatments["KEEP_EDITORIAL_PAUSE"] = treatments.get("KEEP_EDITORIAL_PAUSE", 0) + 1

    plan["cuts"] = [
        {
            "start_s": c["start_s"], "end_s": c["end_s"],
            "reason": c["reason"], "confidence": c["confidence"],
            "treatment": c["treatment"], "text_preview": c.get("text_preview") or "",
            **({
                "micro_repetition_original_span": c.get("micro_repetition_original_span"),
                "micro_repetition_expanded_span": c.get("micro_repetition_expanded_span"),
                "micro_repetition_crossfade_frames": c.get("micro_repetition_crossfade_frames"),
                "micro_repetition_audio_crossfade_ms": c.get("micro_repetition_audio_crossfade_ms"),
                "micro_repair_overlap_class": c.get("micro_repair_overlap_class"),
                "micro_repair_overlap_duration_s": c.get("micro_repair_overlap_duration_s"),
                "micro_repair_pause_consumed": c.get("micro_repair_pause_consumed"),
                "micro_repair_padding_shrunk": c.get("micro_repair_padding_shrunk"),
                "micro_repair_acceptance_reason": c.get("micro_repair_acceptance_reason"),
            } if str(c.get("reason") or "").startswith("micro_repetition_repair:") else {}),
        }
        for c in accepted
    ]
    accepted_micro = [
        c for c in accepted
        if str(c.get("reason") or "").startswith("micro_repetition_repair:")
    ]
    plan["micro_repetition_repairs_applied"] = len(accepted_micro)
    plan["micro_repetition_original_span"] = [
        c.get("micro_repetition_original_span") for c in accepted_micro
    ]
    plan["micro_repetition_expanded_span"] = [
        c.get("micro_repetition_expanded_span") for c in accepted_micro
    ]
    plan["micro_repair_overlap_class"] = [
        c.get("micro_repair_overlap_class") for c in accepted_micro
    ]
    plan["micro_repair_overlap_duration_s"] = [
        c.get("micro_repair_overlap_duration_s") for c in accepted_micro
    ]
    plan["micro_repair_pause_consumed"] = [
        c.get("micro_repair_pause_consumed") for c in accepted_micro
    ]
    plan["micro_repair_padding_shrunk"] = [
        c.get("micro_repair_padding_shrunk") for c in accepted_micro
    ]
    plan["micro_repair_acceptance_reason"] = [
        c.get("micro_repair_acceptance_reason") for c in accepted_micro
    ]
    if accepted_micro:
        plan["micro_repetition_crossfade_frames"] = max(
            int(c.get("micro_repetition_crossfade_frames") or 0) for c in accepted_micro
        )
        plan["micro_repetition_audio_crossfade_ms"] = max(
            int(c.get("micro_repetition_audio_crossfade_ms") or 0) for c in accepted_micro
        )
        plan["micro_repetition_skip_reason"] = ""
    plan["keep_segments"] = keep_segments
    plan["total_cut_seconds"] = round(total, 3)
    plan["final_duration_after_cuts"] = round(max(0.0, duration - total), 3)
    plan["treatments"] = treatments
    return plan
