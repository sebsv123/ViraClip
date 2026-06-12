"""VPI Premium Transition Pack v4.1.

CPU-only transition planning and application for Beta Clean VPI.
Transitions are selected only when they improve clarity, retention, or rhythm.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TransitionEvent:
    transition_type: str
    start_time: float
    duration_frames: int
    duration_seconds: float
    reason: str
    intensity: str = "medium"
    target_bbox: Optional[Dict[str, float]] = None
    subject_hint: str = ""
    sfx_hint: str = ""
    frame_rhythm_group: str = "transition"
    safe_fallback: str = "clean_cut"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransitionPlan:
    enabled: bool
    events: List[TransitionEvent] = field(default_factory=list)
    transition_warnings: List[str] = field(default_factory=list)
    frame_rhythm_applied: bool = False
    frame_rhythm_pattern: str = ""
    frame_rhythm_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["transition_events"] = [event.to_dict() for event in self.events]
        data["transition_types"] = [event.transition_type for event in self.events]
        data["transitions_applied"] = False
        return data


@dataclass
class TransitionResult:
    applied: bool
    output_path: str
    transition_type: str
    frames_used: List[int] = field(default_factory=list)
    fallback_used: bool = False
    warning: str = ""
    ffmpeg_cmd_summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(self.metadata)
        return data


FPS = 30
PREMIUM_TYPES = {
    "match_cut",
    "glitch_clean",
    "shape_morph_beta",
    "mask_reveal",
    "sweeping_reveal",
    "sweeping_object_reveal",
}


def _duration_seconds(frames: int, fps: int = FPS) -> float:
    return round(max(1, int(frames)) / float(fps), 3)


def _safe_bbox(bbox: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    if bbox:
        return {
            "x": float(bbox.get("x", 0.35)),
            "y": float(bbox.get("y", 0.25)),
            "w": float(bbox.get("w", 0.30)),
            "h": float(bbox.get("h", 0.35)),
        }
    return {"x": 0.30, "y": 0.22, "w": 0.40, "h": 0.42}


def _has_strong_reason(context: Dict[str, Any]) -> bool:
    reason = " ".join(str(item).lower() for item in (
        context.get("reason"),
        context.get("transition_reason"),
        context.get("phrase"),
        context.get("matched_pattern"),
    ))
    return any(term in reason for term in ("objec", "mito", "desment", "no es asi", "contraste", "interrup"))


def choose_transition_type(context: Dict[str, Any]) -> str:
    editorial = str(context.get("editorial_type") or "").lower()
    has_bbox = bool(context.get("target_bbox") or context.get("bbox") or context.get("subject_bbox"))
    narrative = str(context.get("narrative_event") or context.get("event") or "").lower()
    continuity = bool(context.get("visual_continuity") or context.get("semantic_continuity"))
    important_broll = bool(context.get("important_broll") or context.get("broll_important"))
    concept_shift = str(context.get("concept_shift") or "").lower()

    if editorial in {"client_objection", "myth_debunk"} and _has_strong_reason(context):
        logger.info("[transition-select] chosen=glitch_clean reason=objection_or_myth_contrast")
        return "glitch_clean"
    if concept_shift in {"risk_to_protection", "problem_to_solution", "doubt_to_answer"}:
        chosen = "shape_morph_beta" if context.get("shape_morph_viable", True) else "mask_reveal"
        logger.info("[transition-select] chosen=%s reason=concept_shift_%s", chosen, concept_shift)
        return chosen
    if has_bbox:
        logger.info("[transition-select] chosen=mask_reveal reason=bbox_or_subject_focus")
        return "mask_reveal"
    if narrative in {"block_change", "hook_to_explanation", "idea_shift"} or important_broll:
        logger.info("[transition-select] chosen=sweeping_reveal reason=narrative_block_or_broll")
        return "sweeping_reveal"
    if continuity:
        logger.info("[transition-select] chosen=match_cut reason=visual_or_semantic_continuity")
        return "match_cut"
    logger.info("[transition-select] fallback=clean_cut reason=no_editorial_gain")
    return "clean_cut"


def choose_transition_strategy(
    *,
    editorial_type: str = "",
    hook_strategy_final: str = "",
    hook_visual_applied: bool = False,
    hook_overlay_active: bool = False,
    broll_applied: bool = False,
    broll_mode: str = "",
    broll_start_time: float = 0.0,
    broll_duration: float = 0.0,
    rhythm_edit_applied: bool = False,
    visual_reinforcement_applied: bool = False,
    captions_active: bool = False,
    caption_density: float = 0.0,
    visual_layer_budget_applied: bool = False,
    clip_duration: float = 0.0,
    face_bbox: Optional[Dict[str, Any]] = None,
    speaker_bbox: Optional[Dict[str, Any]] = None,
    transition_routes_used: Optional[List[str]] = None,
) -> Dict[str, Any]:
    clip_duration = max(0.0, float(clip_duration or 0.0))
    editorial = str(editorial_type or "").lower()
    hook_strategy = str(hook_strategy_final or "").lower()
    broll_mode = str(broll_mode or "").lower()
    routes_used = [str(item) for item in (transition_routes_used or []) if str(item)]
    first3_protected = clip_duration > 0.0 and (
        hook_visual_applied or hook_overlay_active or hook_strategy in {"text_hook", "non_text_push_hook", "silence_tension_hook"}
    )
    before_first3 = clip_duration <= 3.0 or first3_protected
    budget_blocked = bool(visual_layer_budget_applied and (captions_active and caption_density >= 7.0))
    if hook_visual_applied and hook_overlay_active and clip_duration <= 3.0:
        logger.info(
            "TRANSITION_STRATEGY_SELECTED decision=%s strategy=%s reason=%s start=%.2f dur_frames=%d max=%d hook_blocked=%s budget_blocked=%s",
            "no_transition",
            "no_transition",
            "hook_first3",
            3.0,
            0,
            1 if clip_duration < 20.0 else 2,
            "true",
            str(bool(caption_density >= 7.0 and visual_layer_budget_applied)).lower(),
        )
        return {
            "transition_decision": "no_transition",
            "transition_strategy": "no_transition",
            "reason": "hook_first3",
            "start_time": 3.0,
            "duration_frames": 0,
            "max_transitions": 1 if clip_duration < 20.0 else 2,
            "sfx_sync_allowed": False,
            "blocked_by_hook": True,
            "blocked_by_budget": budget_blocked,
            "heavy_route_allowed": False,
        }
    if budget_blocked:
        logger.info(
            "TRANSITION_STRATEGY_SELECTED decision=%s strategy=%s reason=%s start=%.2f dur_frames=%d max=%d hook_blocked=%s budget_blocked=%s",
            "no_transition",
            "no_transition",
            "visual_budget_blocked",
            3.0 if clip_duration > 3.0 else clip_duration,
            0,
            1 if clip_duration < 20.0 else 2,
            "false",
            "true",
        )
        return {
            "transition_decision": "no_transition",
            "transition_strategy": "no_transition",
            "reason": "visual_budget_blocked",
            "start_time": 3.0 if clip_duration > 3.0 else clip_duration,
            "duration_frames": 0,
            "max_transitions": 1 if clip_duration < 20.0 else 2,
            "sfx_sync_allowed": False,
            "blocked_by_hook": False,
            "blocked_by_budget": True,
            "heavy_route_allowed": False,
        }
    if clip_duration < 3.0 and strategy not in {"hard_cut_clean", "soft_push", "no_transition"}:
        logger.info(
            "TRANSITION_STRATEGY_SELECTED decision=%s strategy=%s reason=%s start=%.2f dur_frames=%d max=%d hook_blocked=%s budget_blocked=%s",
            "no_transition",
            "no_transition",
            "clip_too_short",
            clip_duration,
            0,
            1 if clip_duration < 20.0 else 2,
            "false",
            "false",
        )
        return {
            "transition_decision": "no_transition",
            "transition_strategy": "no_transition",
            "reason": "clip_too_short",
            "start_time": clip_duration,
            "duration_frames": 0,
            "max_transitions": 1 if clip_duration < 20.0 else 2,
            "sfx_sync_allowed": False,
            "blocked_by_hook": False,
            "blocked_by_budget": False,
            "heavy_route_allowed": False,
        }
    strategy = "hard_cut_clean"
    reason = "default_clean_cut"
    start_time = 0.0
    duration_frames = 0
    sfx_sync_allowed = False
    heavy_route_allowed = False

    if broll_applied:
        strategy = "broll_fade_in_out" if not any(r.startswith("broll") for r in routes_used) else "hard_cut_clean"
        reason = "broll_entry_exit" if strategy == "broll_fade_in_out" else "duplicate_broll_route"
        start_time = max(3.0 if before_first3 else 0.0, float(broll_start_time or 0.0))
        duration_frames = 7
        sfx_sync_allowed = strategy == "broll_fade_in_out"
    elif rhythm_edit_applied:
        strategy = "soft_push"
        reason = "rhythm_visible_edit"
        start_time = 3.0 if before_first3 else max(0.0, min(clip_duration, 0.6))
        duration_frames = 8
        sfx_sync_allowed = True
    elif visual_reinforcement_applied:
        strategy = "short_fade"
        reason = "visual_reinforcement_support"
        start_time = max(3.0 if before_first3 else 0.0, 0.45)
        duration_frames = 5
        sfx_sync_allowed = False
    elif editorial in {"myth_debunk", "client_objection"} and hook_strategy != "no_extra_hook":
        strategy = "match_cut"
        reason = "editorial_match_cut"
        start_time = max(3.0 if before_first3 else 0.0, 0.45)
        duration_frames = 5
        sfx_sync_allowed = True
    elif editorial in {"risk_warning", "coverage_explanation"} and captions_active and caption_density < 7.0:
        strategy = "dip_blur_short"
        reason = "subtle_context_shift"
        start_time = max(3.0 if before_first3 else 0.0, 0.55)
        duration_frames = 5
        sfx_sync_allowed = False
    elif editorial in {"travel", "emotional_protection", "health", "money_saving"}:
        strategy = "slide_minimal"
        reason = "gentle_context_shift"
        start_time = max(3.0 if before_first3 else 0.0, 0.5)
        duration_frames = 5
        sfx_sync_allowed = False
    if (hook_visual_applied or hook_overlay_active) and strategy not in {"hard_cut_clean", "soft_push", "no_transition"}:
        start_time = max(start_time, 3.0)
    if hook_strategy in {"text_hook", "non_text_push_hook", "silence_tension_hook"} and clip_duration <= 8.0:
        strategy = "hard_cut_clean" if strategy == "hard_cut_clean" else strategy
        reason = reason or "hook_protected"
    if hook_visual_applied and not before_first3 and strategy not in {"hard_cut_clean", "soft_push"}:
        heavy_route_allowed = False
    if strategy in {"match_cut", "dip_blur_short", "slide_minimal", "short_fade"}:
        heavy_route_allowed = False
    if strategy == "broll_fade_in_out":
        heavy_route_allowed = False
    decision = "use_transition" if strategy not in {"no_transition", "hard_cut_clean"} else "no_transition"
    logger.info(
        "TRANSITION_STRATEGY_SELECTED decision=%s strategy=%s reason=%s start=%.2f dur_frames=%d max=%d hook_blocked=%s budget_blocked=%s",
        decision,
        strategy,
        reason,
        start_time,
        duration_frames,
        1 if clip_duration < 20.0 else 2,
        str(bool(hook_visual_applied or hook_overlay_active)).lower(),
        str(budget_blocked).lower(),
    )
    return {
        "transition_decision": decision,
        "transition_strategy": strategy,
        "reason": reason,
        "start_time": round(float(start_time), 3),
        "duration_frames": int(duration_frames),
        "max_transitions": 1 if clip_duration < 20.0 else 2,
        "sfx_sync_allowed": bool(sfx_sync_allowed),
        "blocked_by_hook": bool(hook_visual_applied or hook_overlay_active) and decision == "no_transition" and strategy != "hard_cut_clean",
        "blocked_by_budget": bool(budget_blocked),
        "heavy_route_allowed": bool(heavy_route_allowed),
    }


def choose_vpi_transition_polish(
    *,
    transition_strategy: str = "",
    editorial_type: str = "",
    motion_profile: str = "",
    broll_timing_strategy: str = "",
    broll_entry_style: str = "",
    broll_exit_style: str = "",
    premium_restraint_mode: str = "",
    hook_strategy_final: str = "",
    first_second_strength: float = 0.0,
    sensitive_topic: bool = False,
    clip_duration: float = 0.0,
    caption_density: float = 0.0,
    sfx_allowed: bool = True,
) -> Dict[str, Any]:
    strategy = str(transition_strategy or "no_transition")
    editorial = str(editorial_type or "").lower()
    motion = str(motion_profile or "").lower()
    restraint = str(premium_restraint_mode or "").lower()
    broll_strategy = str(broll_timing_strategy or "").lower()
    broll_entry = str(broll_entry_style or "").lower()
    broll_exit = str(broll_exit_style or "").lower()
    hook = str(hook_strategy_final or "").lower()
    strong_first3 = float(first_second_strength or 0.0) >= 72.0 or hook in {"text_hook", "non_text_push_hook", "silence_tension_hook"}

    transition_polish_mode = "none"
    transition_duration_ms = 0
    transition_sfx_allowed = False
    transition_sfx_family = ""
    transition_reason = "default_no_transition"
    transition_should_render = False
    transition_repetition_avoided = False
    transition_broll_sync_ok = True
    transition_broll_sync_reason = "no_broll_conflict"

    if sensitive_topic or editorial in {"sensitive_decesos", "decesos"}:
        transition_polish_mode = "sensitive_cut"
        transition_duration_ms = 180
        transition_reason = "sensitive_topic"
    elif restraint in {"no_extra_visual", "minimal"}:
        transition_polish_mode = "hard_cut_clean"
        transition_duration_ms = 0
        transition_reason = "minimal_restraint"
    elif editorial in {"risk_warning", "myth_debunk"}:
        transition_polish_mode = "punch_cut"
        transition_duration_ms = 220
        transition_reason = "risk_or_myth_emphasis"
    elif editorial in {"coverage_explanation", "tramite_documentacion"}:
        transition_polish_mode = "hard_cut_clean" if caption_density >= 7.0 else "soft_cut"
        transition_duration_ms = 120 if transition_polish_mode == "soft_cut" else 0
        transition_reason = "coverage_or_tramite"
    elif editorial in {"emotional_protection"}:
        transition_polish_mode = "soft_fade" if motion in {"calm", "sensitive_soft"} else "soft_cut"
        transition_duration_ms = 240 if transition_polish_mode == "soft_fade" else 140
        transition_reason = "emotional_protection"
    elif motion == "punchy":
        transition_polish_mode = "subtle_push"
        transition_duration_ms = 180
        transition_reason = "punchy_motion"
    elif motion in {"calm", "sensitive_soft"}:
        transition_polish_mode = "soft_cut"
        transition_duration_ms = 140 if motion == "calm" else 100
        transition_reason = "calm_motion"
    else:
        transition_polish_mode = "soft_cut" if strategy not in {"no_transition", "hard_cut_clean"} else "hard_cut_clean"
        transition_duration_ms = 120 if transition_polish_mode == "soft_cut" else 0
        transition_reason = "default_polish"

    if broll_strategy in {"phrase_matched_insert", "supportive_overlay", "late_context_insert", "short_cutaway"}:
        transition_broll_sync_ok = broll_entry in {"cut", "soft_fade", "subtle_push"} and broll_exit in {"cut", "soft_fade"}
        transition_broll_sync_reason = "broll_style_already_sober" if transition_broll_sync_ok else "broll_needs_no_extra_transition"
        if not transition_broll_sync_ok:
            transition_polish_mode = "none"
            transition_reason = "broll_sync_conflict"
        else:
            logger.info("VPI_TRANSITION_BROLL_SYNC_OK reason=%s", transition_broll_sync_reason)

    if motion == "punchy" and transition_polish_mode in {"soft_cut", "subtle_push"} and not strong_first3:
        transition_polish_mode = "subtle_push"
        transition_reason = "punchy_motion_without_first3_boost"

    if strong_first3 and strategy not in {"no_transition", "hard_cut_clean"} and float(clip_duration or 0.0) > 3.0:
        if transition_polish_mode == "soft_cut":
            transition_polish_mode = "subtle_push"
            transition_reason = "first3_motion_support"

    if sensitive_topic:
        transition_sfx_allowed = False
        transition_sfx_family = ""
        if transition_polish_mode not in {"sensitive_cut", "soft_fade"}:
            transition_polish_mode = "sensitive_cut"
            transition_reason = "sensitive_topic"
        transition_sfx_suppressed_reason = "sensitive_topic"
    else:
        transition_sfx_allowed = bool(sfx_allowed and transition_polish_mode not in {"hard_cut_clean", "none", "soft_fade", "sensitive_cut"})
        if transition_polish_mode == "punch_cut":
            transition_sfx_family = "soft_hit"
            transition_sfx_suppressed_reason = "" if transition_sfx_allowed else "punch_cut_policy"
        elif transition_polish_mode == "subtle_push":
            transition_sfx_family = "soft_whoosh"
            transition_sfx_suppressed_reason = "" if transition_sfx_allowed else "voice_or_policy"
        elif transition_polish_mode == "soft_cut" and editorial in {"risk_warning", "myth_debunk"}:
            transition_sfx_family = "soft_hit"
            transition_sfx_suppressed_reason = "" if transition_sfx_allowed else "voice_or_policy"
        elif transition_polish_mode == "soft_cut":
            transition_sfx_family = "soft_whoosh"
            transition_sfx_suppressed_reason = "" if transition_sfx_allowed else "voice_or_policy"
        else:
            transition_sfx_suppressed_reason = "" if transition_sfx_allowed else "voice_or_policy"

    if transition_polish_mode in {"none", "hard_cut_clean"}:
        transition_should_render = strategy not in {"no_transition"} and transition_polish_mode != "none"
    else:
        transition_should_render = strategy not in {"no_transition"} and float(clip_duration or 0.0) >= 3.0

    if strategy in {"no_transition", "hard_cut_clean"} and transition_polish_mode not in {"sensitive_cut"}:
        transition_repetition_avoided = True
        logger.info("VPI_TRANSITION_REPETITION_AVOIDED mode=%s reason=%s", transition_polish_mode, transition_reason)
    if broll_strategy in {"phrase_matched_insert", "supportive_overlay"} and transition_polish_mode in {"soft_cut", "subtle_push"}:
        transition_repetition_avoided = True

    if not transition_should_render:
        transition_reason = transition_reason or "polish_suppressed"
        logger.info("VPI_TRANSITION_POLISH_WARNING reason=%s mode=%s", transition_reason, transition_polish_mode)
    if sensitive_topic or not transition_sfx_allowed:
        logger.info(
            "VPI_TRANSITION_SFX_SUPPRESSED reason=%s family=%s",
            transition_sfx_suppressed_reason,
            transition_sfx_family or "none",
        )

    logger.info(
        "VPI_TRANSITION_POLISH_SELECTED mode=%s duration_ms=%d sfx_allowed=%s family=%s reason=%s",
        transition_polish_mode,
        transition_duration_ms,
        str(bool(transition_sfx_allowed)).lower(),
        transition_sfx_family or "none",
        transition_reason,
    )
    return {
        "transition_polish_mode": transition_polish_mode,
        "transition_duration_ms": int(transition_duration_ms),
        "transition_sfx_allowed": bool(transition_sfx_allowed),
        "transition_sfx_family": transition_sfx_family,
        "transition_reason": transition_reason,
        "transition_should_render": bool(transition_should_render),
        "transition_repetition_avoided": bool(transition_repetition_avoided),
        "transition_broll_sync_ok": bool(transition_broll_sync_ok),
        "transition_broll_sync_reason": transition_broll_sync_reason,
        "transition_sfx_suppressed_reason": "" if transition_sfx_allowed else ("sensitive_topic" if sensitive_topic else "voice_or_policy"),
    }


def _sfx_hint_for(transition_type: str, context: Dict[str, Any]) -> str:
    if transition_type in {"sweeping_reveal", "sweeping_object_reveal", "mask_reveal", "shape_morph_beta"}:
        return "magic_whoosh"
    if transition_type == "glitch_clean":
        return "glitch_tick"
    if transition_type == "match_cut" and context.get("narrative_weight") in {"high", "emotional", "risk"}:
        return "soft_hit"
    return ""


def _apply_frame_rhythm(events: List[TransitionEvent], *, fps: int = FPS) -> Dict[str, Any]:
    if len(events) < 1:
        logger.info("[frame-rhythm] skipped reason=no_related_event")
        return {"applied": False, "pattern": "", "events": []}
    rhythm_events: List[Dict[str, Any]] = []
    for index, event in enumerate(events):
        related_frames = [5, 10]
        if event.transition_type == "shape_morph_beta" and event.intensity == "high":
            related_frames = [5, 10, 15]
        frames = related_frames[min(index, len(related_frames) - 1)] if len(events) > 1 else event.duration_frames
        if index == 0 and frames == 5:
            logger.info(
                "[frame-rhythm] group=%s event=%s frames=5 next=10 applied=true",
                event.frame_rhythm_group,
                event.transition_type,
            )
        event.duration_frames = frames
        event.duration_seconds = _duration_seconds(frames, fps)
        rhythm_events.append({
            "group": event.frame_rhythm_group,
            "event": event.transition_type,
            "frames": frames,
            "duration_seconds": event.duration_seconds,
            "next_frames": 10 if frames == 5 else None,
        })
    return {"applied": True, "pattern": "5_to_10", "events": rhythm_events}


def plan_transition_events(context: Dict[str, Any]) -> TransitionPlan:
    transition_type = str(context.get("transition_type") or choose_transition_type(context))
    if transition_type in {"clean_cut", "short_fade"}:
        warning = "no_premium_transition_needed"
        return TransitionPlan(enabled=False, transition_warnings=[warning])
    if transition_type == "shape_morph_beta" and context.get("shape_morph_viable") is False:
        logger.info("[transition-shape-morph] fallback=mask_reveal reason=no_shape_assets")
        transition_type = "mask_reveal"

    if transition_type == "glitch_clean" and str(context.get("editorial_type") or "") == "emotional_protection" and not _has_strong_reason(context):
        logger.info("[transition-glitch] skipped reason=not_editorially_justified")
        return TransitionPlan(enabled=False, transition_warnings=["glitch_not_editorially_justified"])

    # ── VPI Premium Composition Pack v1: block transitions based on composition_mode ──
    _composition_decision = context.get("composition_decision")
    if _composition_decision and isinstance(_composition_decision, dict) and _composition_decision.get("composition_pack"):
        _comp_mode = str(_composition_decision.get("composition_mode") or "")
        _screen_priority = str(_composition_decision.get("screen_priority") or "")
        _hook_overlay_active = bool(context.get("hook_overlay_active"))
        if transition_type in {"sweeping_reveal", "sweeping_object_reveal", "mask_reveal"}:
            if _comp_mode == "emotional_soft":
                logger.info("[composition-pack] transition blocked=%s reason=emotional_soft_no_strong_transition", transition_type)
                logger.info("[transition-qc] composition_allowed=false reason=emotional_soft_no_strong_transition")
                return TransitionPlan(enabled=False, transition_warnings=[f"composition_blocked_{transition_type}_emotional_soft"])
            if _comp_mode == "minimal_safe":
                logger.info("[composition-pack] transition blocked=%s reason=minimal_safe_no_transition", transition_type)
                logger.info("[transition-qc] composition_allowed=false reason=minimal_safe_no_transition")
                return TransitionPlan(enabled=False, transition_warnings=[f"composition_blocked_{transition_type}_minimal_safe"])
            if (_screen_priority == "hook_overlay" or _hook_overlay_active) and transition_type in {"sweeping_reveal", "sweeping_object_reveal"}:
                logger.info("[composition-pack] transition blocked=%s reason=hook_overlay_priority_no_sweep", transition_type)
                logger.info("[transition-qc] composition_allowed=false reason=hook_overlay_text_conflict")
                return TransitionPlan(enabled=False, transition_warnings=[f"composition_blocked_{transition_type}_hook_overlay"])
        if transition_type == "glitch_clean" and _comp_mode == "emotional_soft":
            logger.info("[composition-pack] transition blocked=glitch_clean reason=emotional_soft_no_glitch")
            logger.info("[transition-qc] composition_allowed=false reason=emotional_soft_no_glitch")
            return TransitionPlan(enabled=False, transition_warnings=["composition_blocked_glitch_emotional_soft"])
        logger.info("[composition-pack] transition allowed=%s mode=%s", transition_type, _comp_mode)
        logger.info("[transition-qc] composition_allowed=true reason=%s", _comp_mode or "composition_context")

    start = float(context.get("start_time") or context.get("start_s") or 0.25)
    base_frames = int(context.get("duration_frames") or (10 if transition_type in {"shape_morph_beta", "mask_reveal"} else 5))
    if transition_type == "shape_morph_beta":
        base_frames = min(15, max(10, base_frames))
    elif transition_type == "glitch_clean":
        base_frames = min(10, max(5, base_frames))
    elif transition_type in {"mask_reveal", "sweeping_reveal", "sweeping_object_reveal"}:
        base_frames = min(12, max(8, base_frames if context.get("duration_frames") else 10))

    bbox = context.get("target_bbox") or context.get("bbox") or context.get("subject_bbox")
    event = TransitionEvent(
        transition_type=transition_type,
        start_time=round(start, 3),
        duration_frames=base_frames,
        duration_seconds=_duration_seconds(base_frames),
        reason=str(context.get("reason") or context.get("transition_reason") or transition_type),
        intensity=str(context.get("intensity") or "medium"),
        target_bbox=_safe_bbox(bbox) if transition_type in {"match_cut", "mask_reveal", "sweeping_object_reveal"} else bbox,
        subject_hint=str(context.get("subject_hint") or context.get("subject") or ""),
        sfx_hint=_sfx_hint_for(transition_type, context),
        frame_rhythm_group=str(context.get("frame_rhythm_group") or transition_type),
        safe_fallback="short_fade" if transition_type in {"sweeping_reveal", "sweeping_object_reveal"} else ("mask_reveal" if transition_type == "shape_morph_beta" else "clean_cut"),
        metadata=_metadata_for_event(transition_type, context, base_frames, bbox),
    )
    related = context.get("related_events")
    events = [event]
    if isinstance(related, list) and related:
        events.append(TransitionEvent(
            transition_type=transition_type,
            start_time=round(start + event.duration_seconds, 3),
            duration_frames=10,
            duration_seconds=_duration_seconds(10),
            reason=f"{event.reason}:related_followthrough",
            intensity=event.intensity,
            target_bbox=event.target_bbox,
            subject_hint=event.subject_hint,
            sfx_hint="",
            frame_rhythm_group=event.frame_rhythm_group,
            safe_fallback=event.safe_fallback,
            metadata={"related_followthrough": True},
        ))
    rhythm = _apply_frame_rhythm(events)
    for item in events:
        logger.info(
            "[transition-plan] type=%s reason=%s start=%.3f frames=%d",
            item.transition_type,
            item.reason,
            item.start_time,
            item.duration_frames,
        )
    return TransitionPlan(
        enabled=True,
        events=events,
        frame_rhythm_applied=bool(rhythm["applied"]),
        frame_rhythm_pattern=str(rhythm["pattern"]),
        frame_rhythm_events=list(rhythm["events"]),
    )


def _metadata_for_event(transition_type: str, context: Dict[str, Any], frames: int, bbox: Optional[Dict[str, float]]) -> Dict[str, Any]:
    if transition_type == "match_cut":
        return {
            "match_cut_applied": False,
            "match_cut_timing_frames": [5, 10],
            "match_cut_bbox": _safe_bbox(bbox),
            "match_cut_reason": str(context.get("reason") or "continuity"),
        }
    if transition_type == "glitch_clean":
        return {
            "glitch_transition_applied": False,
            "glitch_fragments": 3,
            "glitch_frames": frames,
            "glitch_reason": str(context.get("reason") or "pattern_interrupt"),
        }
    if transition_type == "shape_morph_beta":
        return {
            "shape_morph_applied": False,
            "shape_morph_from": str(context.get("shape_from") or "problem"),
            "shape_morph_to": str(context.get("shape_to") or "solution"),
            "shape_morph_beta": True,
        }
    if transition_type == "mask_reveal":
        return {
            "mask_reveal_applied": False,
            "mask_reveal_bbox": _safe_bbox(bbox),
            "mask_reveal_direction": str(context.get("direction") or "center_out"),
            "mask_reveal_opacity_keyframes": [{"frame": 0, "opacity": 0.0}, {"frame": frames, "opacity": 1.0}],
            "mask_reveal_alpha_ramp": True,
            "mask_reveal_feather": "light",
        }
    if transition_type in {"sweeping_reveal", "sweeping_object_reveal"}:
        return {
            "sweeping_reveal_applied": False,
            "sweeping_reveal_direction": str(context.get("direction") or "left_to_right"),
            "sweeping_reveal_mask_used": True,
            "sweeping_reveal_alpha_ramp": [{"frame": 0, "alpha": 0.0}, {"frame": frames, "alpha": 1.0}],
            "sweeping_reveal_scale_keyframes": [{"frame": 0, "scale": 1.0}, {"frame": 5, "scale": 1.025}, {"frame": frames, "scale": 1.0}],
            "sweeping_reveal_position_keyframes": [{"frame": 0, "x": -0.16}, {"frame": 5, "x": 0.42}, {"frame": frames, "x": 1.16}],
            "transition_pack_contextual": True,
        }
    return {}


def plan_sweeping_reveal(context: Dict[str, Any]) -> Dict[str, Any]:
    intent = str(context.get("hook_intent") or context.get("intent") or "")
    reason = str(context.get("reason") or context.get("narrative_event") or context.get("event") or "")
    contextual = any(term in reason for term in ("topic_shift", "contrast", "hook", "block_change", "idea_shift")) or bool(context.get("important_broll"))
    if intent == "emotional_closure":
        logger.info("[transition-pack] skipped reason=not_contextual")
        return {"applied": False, "transition_type": "short_fade", "skipped_reason": "emotional_closure_softness"}
    if not contextual:
        logger.info("[transition-pack] skipped reason=not_contextual")
        return {"applied": False, "transition_type": "clean_cut", "skipped_reason": "not_contextual"}
    frames = min(12, max(8, int(context.get("duration_frames") or 10)))
    logger.info("[transition-pack] type=sweeping_reveal applied=true frames=%d", frames)
    logger.info("[transition-pack] contextual=true reason=%s", reason or "hook")
    return {
        "applied": True,
        "transition_type": "sweeping_reveal",
        "duration_frames": frames,
        "alpha_ramp": True,
        "horizontal_shift": "subtle",
        "contextual": True,
        "reason": reason or "hook",
    }


def plan_mask_reveal(context: Dict[str, Any]) -> Dict[str, Any]:
    bbox = context.get("bbox") or context.get("target_bbox") or context.get("subject_bbox")
    if not bbox:
        logger.info("[mask-reveal] fallback=sweeping_reveal reason=no_bbox")
        fallback = plan_sweeping_reveal({**context, "reason": context.get("reason") or "hook"})
        return {
            **fallback,
            "fallback": "sweeping_reveal",
            "fallback_used": True,
            "fallback_reason": "no_bbox",
        }
    frames = min(12, max(8, int(context.get("duration_frames") or 10)))
    safe = _safe_bbox(bbox)
    logger.info("[mask-reveal] applied=true bbox=%s", safe)
    return {
        "applied": True,
        "transition_type": "mask_reveal",
        "duration_frames": frames,
        "bbox": safe,
        "feather": "light",
        "alpha_ramp": [{"frame": 0, "opacity": 0.0}, {"frame": frames, "opacity": 1.0}],
        "contextual": True,
        "reason": str(context.get("reason") or "bbox_reveal"),
    }


def _probe_size(path: Path) -> tuple[int, int]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        width, height = (result.stdout or "1080x1920").strip().splitlines()[0].split("x", 1)
        return max(2, int(width)), max(2, int(height))
    except Exception:
        return 1080, 1920


def _vf_for_event(event: TransitionEvent, width: int, height: int) -> str:
    start = max(0.0, float(event.start_time))
    end = start + max(0.033, float(event.duration_seconds))
    t = f"between(t\\,{start:.3f}\\,{end:.3f})"
    frames = max(1, int(event.duration_frames))
    bbox = _safe_bbox(event.target_bbox)
    cx = int((bbox["x"] + bbox["w"] / 2.0) * width)
    cy = int((bbox["y"] + bbox["h"] / 2.0) * height)

    transition_type = "sweeping_object_reveal" if event.transition_type == "sweeping_reveal" else event.transition_type

    if transition_type == "match_cut":
        scale_expr = f"if({t}\\,1.045\\,1)"
        blur = f",gblur=sigma='if({t},0.65,0)'"
        return (
            f"crop=w='iw/({scale_expr})':h='ih/({scale_expr})':"
            f"x='min(max({cx}-out_w/2,0),iw-out_w)':y='min(max({cy}-out_h/2,0),ih-out_h)',"
            f"scale={width}:{height}{blur}"
        )

    if transition_type == "glitch_clean":
        band_h = max(4, int(height * 0.035))
        y1 = int(height * 0.28)
        y2 = int(height * 0.52)
        return (
            f"drawbox=x='if({t},18,0)':y={y1}:w=iw:h={band_h}:color=white@0.42:t=fill:enable='{t}',"
            f"drawbox=x='if({t},-14,0)':y={y2}:w=iw:h={band_h}:color=white@0.30:t=fill:enable='{t}',"
            f"drawbox=x='if({t},36,0)':y={int(height * 0.70)}:w=iw:h={max(3, band_h // 2)}:color=white@0.22:t=fill:enable='{t}',"
            "format=yuv420p"
        )

    if transition_type == "shape_morph_beta":
        size = max(32, int(min(width, height) * 0.22))
        x = int(width * 0.5 - size / 2)
        y = int(height * 0.5 - size / 2)
        return (
            f"drawbox=x={x}:y={y}:w={size}:h={size}:color=white@0.16:t=fill:enable='{t}',"
            f"drawbox=x={x + int(size*0.16)}:y={y + int(size*0.16)}:w={int(size*0.68)}:h={int(size*0.68)}:"
            f"color=white@0.20:t=6:enable='{t}'"
        )

    if transition_type == "mask_reveal":
        x = int(bbox["x"] * width)
        y = int(bbox["y"] * height)
        w = int(bbox["w"] * width)
        h = int(bbox["h"] * height)
        return (
            f"drawbox=x={x}:y={y}:w={w}:h={h}:color=white@0.18:t=fill:enable='{t}',"
            f"drawbox=x={x}:y={y}:w={w}:h={h}:color=white@0.40:t=5:enable='{t}'"
        )

    if transition_type == "sweeping_object_reveal":
        sweep_w = int(width * 0.22)
        return (
            f"drawbox=x='if({t}, -{sweep_w} + (t-{start:.3f})/{max(0.001, end-start):.3f}*{width + 2*sweep_w}, -{sweep_w})':"
            f"y=0:w={sweep_w}:h=ih:color=white@0.28:t=fill:enable='{t}',"
            f"drawbox=x='if({t}, -{sweep_w} + (t-{start:.3f})/{max(0.001, end-start):.3f}*{width + 2*sweep_w}, -{sweep_w})':"
            f"y=0:w={max(6, int(sweep_w*0.08))}:h=ih:color=white@0.55:t=fill:enable='{t}'"
        )

    return "null"


def _metadata_applied(event: TransitionEvent) -> Dict[str, Any]:
    metadata = dict(event.metadata)
    if event.transition_type == "match_cut":
        metadata["match_cut_applied"] = True
        logger.info("[transition-matchcut] applied=true frames=5,10 bbox=%s reason=%s", event.target_bbox, event.reason)
    elif event.transition_type == "glitch_clean":
        metadata["glitch_transition_applied"] = True
        logger.info("[transition-glitch] applied=true fragments=%s frames=%s", metadata.get("glitch_fragments", 3), event.duration_frames)
    elif event.transition_type == "shape_morph_beta":
        metadata["shape_morph_applied"] = True
        logger.info(
            "[transition-shape-morph] applied=true shape_from=%s shape_to=%s frames=%s",
            metadata.get("shape_morph_from"),
            metadata.get("shape_morph_to"),
            event.duration_frames,
        )
    elif event.transition_type == "mask_reveal":
        metadata["mask_reveal_applied"] = True
        logger.info(
            "[transition-mask] applied=true bbox=%s frames=%s opacity_keyframes=%s",
            event.target_bbox,
            event.duration_frames,
            metadata.get("mask_reveal_opacity_keyframes"),
        )
    elif event.transition_type in {"sweeping_reveal", "sweeping_object_reveal"}:
        metadata["sweeping_reveal_applied"] = True
        logger.info(
            "[transition-sweep] applied=true direction=%s frames=5,10 mask=true scale_keyframes=true",
            metadata.get("sweeping_reveal_direction"),
        )
        logger.info("[transition-pack] type=sweeping_reveal applied=true frames=%s", event.duration_frames)
    return metadata


def apply_transition(
    input_a: Path,
    input_b_or_same_clip: Optional[Path],
    output_path: Path,
    transition_event: TransitionEvent | Dict[str, Any],
) -> TransitionResult:
    event = transition_event if isinstance(transition_event, TransitionEvent) else TransitionEvent(**transition_event)
    if event.transition_type not in PREMIUM_TYPES:
        return TransitionResult(
            applied=False,
            output_path=str(input_a),
            transition_type=event.transition_type,
            frames_used=[event.duration_frames],
            fallback_used=True,
            warning="no_premium_transition_needed",
        )

    if not input_a.exists():
        metadata = _metadata_applied(event)
        metadata["simulated"] = True
        metadata["transition_rendered"] = False
        metadata["transition_verified"] = False
        metadata["transition_skip_reason"] = "input_missing"
        logger.warning("TRANSITION_SKIPPED_REASON reason=input_missing")
        return TransitionResult(
            applied=False,
            output_path=str(output_path),
            transition_type=event.transition_type,
            frames_used=[event.duration_frames],
            warning="input_missing",
            ffmpeg_cmd_summary="simulated",
            metadata=metadata,
        )

    width, height = _probe_size(input_a)
    vf = _vf_for_event(event, width, height)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_a),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            metadata = _metadata_applied(event)
            metadata["transition_rendered"] = True
            metadata["transition_verified"] = True
            metadata["transition_skip_reason"] = ""
            if event.sfx_hint:
                logger.info("[transition-sweep] sfx=%s applied=false", event.sfx_hint)
                metadata.update({
                    "transition_sfx_applied": False,
                    "transition_sfx_type": event.sfx_hint,
                    "transition_sfx_asset": None,
                })
                logger.info("[transition-sfx] missing=%s transition=%s", event.sfx_hint, event.transition_type)
            logger.info("[transition-apply] type=%s applied=true output=%s", event.transition_type, output_path)
            logger.info("TRANSITION_RENDERED")
            return TransitionResult(
                applied=True,
                output_path=str(output_path),
                transition_type=event.transition_type,
                frames_used=[event.duration_frames],
                fallback_used=False,
                ffmpeg_cmd_summary=f"ffmpeg -vf {event.transition_type}",
                metadata=metadata,
            )
        reason = (result.stderr or "ffmpeg_failed").strip()[-500:]
    except Exception as exc:
        reason = str(exc)
    logger.warning("[transition-apply] failed type=%s fallback=%s reason=%s", event.transition_type, event.safe_fallback, reason)
    logger.warning("TRANSITION_SKIPPED_REASON reason=output_unverified")
    return TransitionResult(
        applied=False,
        output_path=str(input_a),
        transition_type=event.safe_fallback,
        frames_used=[event.duration_frames],
        fallback_used=True,
        warning=reason,
        ffmpeg_cmd_summary=f"fallback={event.safe_fallback}",
        metadata={
            "transition_failed_fallback_used": True,
            "transition_rendered": False,
            "transition_verified": False,
            "transition_skip_reason": "output_unverified",
            "simulated": False,
        },
    )


def apply_transition_plan(
    input_path: Path,
    output_path: Path,
    plan: TransitionPlan | Dict[str, Any],
) -> Dict[str, Any]:
    transition_plan = plan if isinstance(plan, TransitionPlan) else _plan_from_dict(plan)
    if not transition_plan.enabled or not transition_plan.events:
        logger.info("[transition-apply] skipped reason=no_premium_transition_needed")
        return {
            "transitions_applied": False,
            "transition_planned": False,
            "transition_rendered": False,
            "transition_verified": False,
            "transition_strategy": "no_transition",
            "transition_backend": "vpi_transition_engine",
            "transition_skip_reason": "no_premium_transition_needed",
            "transition_output_path": str(input_path),
            "transition_routes_used": [],
            "transition_routes_blocked": [],
            "transition_sfx_sync_allowed": False,
            "transition_count": 0,
            "transition_visible_count": 0,
            "transition_budget_exhausted": False,
            "transition_events": [],
            "transition_types": [],
            "transition_warnings": list(transition_plan.transition_warnings or ["no_premium_transition_needed"]),
            "final_output_uses_transition": False,
        }
    current = input_path
    applied_events: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for idx, event in enumerate(transition_plan.events[:2]):
        target = output_path if idx == len(transition_plan.events[:2]) - 1 else output_path.with_name(f"trans_step{idx}_{output_path.name}")
        result = apply_transition(current, current, target, event)
        contextual = str(event.reason or "") not in {"", "generic", "default"} and event.transition_type not in {"clean_cut", ""}
        logger.info(
            "[transition-qc] contextual=%s reason=%s",
            str(contextual).lower(),
            event.reason or "no_editorial_reason",
        )
        applied_events.append({**event.to_dict(), **result.to_dict(), "contextual": contextual})
        if result.applied and Path(result.output_path).exists():
            current = Path(result.output_path)
        else:
            warnings.append(result.warning or "transition_failed_fallback_used")
    final_verified = current == output_path and output_path.exists()
    logger.info("[transition-final] final_output_uses_transition=%s path=%s", str(final_verified).lower(), current)
    logger.info("[transition-qc] final_verified=%s warnings=%s", str(final_verified).lower(), "|".join(warnings) or "none")
    return {
        "transitions_applied": final_verified,
        "transition_planned": bool(transition_plan.enabled and transition_plan.events),
        "transition_rendered": final_verified,
        "transition_verified": final_verified,
        "transition_strategy": str(transition_plan.events[0].transition_type if transition_plan.events else "no_transition"),
        "transition_backend": "vpi_transition_engine",
        "transition_skip_reason": "" if final_verified else (warnings[-1] if warnings else "output_unverified"),
        "transition_output_path": str(current),
        "transition_routes_used": [event.transition_type for event in transition_plan.events],
        "transition_routes_blocked": warnings,
        "transition_sfx_sync_allowed": bool(any(bool(event.sfx_hint) for event in transition_plan.events) and final_verified),
        "transition_count": len(applied_events),
        "transition_visible_count": int(sum(1 for item in applied_events if bool(item.get("applied") or item.get("transition_rendered") or item.get("transition_verified")))),
        "transition_budget_exhausted": False,
        "transition_events": applied_events,
        "transition_types": [event.transition_type for event in transition_plan.events],
        "transition_contextual": any(bool(item.get("contextual")) for item in applied_events),
        "transition_warnings": warnings,
        "frame_rhythm_applied": transition_plan.frame_rhythm_applied,
        "frame_rhythm_pattern": transition_plan.frame_rhythm_pattern,
        "frame_rhythm_events": transition_plan.frame_rhythm_events,
        "final_output_uses_transition": final_verified,
        "transition_final_path": str(current),
    }


def _plan_from_dict(raw: Dict[str, Any]) -> TransitionPlan:
    events = [
        TransitionEvent(**event)
        for event in raw.get("events") or raw.get("transition_events") or []
        if isinstance(event, dict)
    ]
    return TransitionPlan(
        enabled=bool(raw.get("enabled") or events),
        events=events,
        transition_warnings=list(raw.get("transition_warnings") or []),
        frame_rhythm_applied=bool(raw.get("frame_rhythm_applied")),
        frame_rhythm_pattern=str(raw.get("frame_rhythm_pattern") or ""),
        frame_rhythm_events=list(raw.get("frame_rhythm_events") or []),
    )
