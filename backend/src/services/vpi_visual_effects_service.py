"""CPU-only VPI visual effects layer for Beta Clean post-production."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


MOTION_PACK_PROFILES: Dict[str, Dict[str, Any]] = {
    "myth_flip": {
        "visual_profile": "calm_reveal",
        "effect_type": "hook_push_in",
        "scale_start": 1.0,
        "scale_end": 1.035,
        "duration_frames": 12,
        "hold_frames": 0,
        "easing": "smooth",
        "contextual": True,
        "reason": "hook_intent",
        "avoid": ["aggressive_punch", "aggressive_boom"],
    },
    "risk_warning": {
        "visual_profile": "tension_push",
        "effect_type": "punch_zoom",
        "scale_start": 1.0,
        "scale_end": 1.05,
        "duration_frames": 12,
        "hold_frames": 5,
        "easing": "smooth_tension",
        "contextual": True,
        "reason": "hook_intent",
        "avoid": ["glitch", "emotional_push_in"],
    },
    "practical_advice": {
        "visual_profile": "clean_explanation",
        "effect_type": "hook_push_in",
        "scale_start": 1.0,
        "scale_end": 1.025,
        "duration_frames": 12,
        "hold_frames": 0,
        "easing": "smooth",
        "contextual": True,
        "reason": "hook_intent",
        "subtitle_emphasis": "early_clarity",
    },
    "autonomous_business_stakes": {
        "visual_profile": "business_punch",
        "effect_type": "emphasis_zoom",
        "scale_start": 1.0,
        "scale_end": 1.06,
        "duration_frames": 15,
        "hold_frames": 0,
        "easing": "kick_smooth",
        "contextual": True,
        "reason": "hook_intent",
    },
    "emotional_closure": {
        "visual_profile": "soft_cinematic_push",
        "effect_type": "hook_push_in",
        "scale_start": 1.0,
        "scale_end": 1.035,
        "duration_frames": 12,
        "hold_frames": 0,
        "easing": "soft",
        "contextual": True,
        "reason": "hook_intent",
        "preserve_pause_before_closure": True,
        "avoid": ["aggressive_impact", "glitch"],
    },
    "neutral_explanation": {
        "visual_profile": "basic_clean_motion",
        "effect_type": "subtle_push_in",
        "scale_start": 1.0,
        "scale_end": 1.015,
        "duration_frames": 12,
        "hold_frames": 0,
        "easing": "smooth",
        "contextual": False,
        "reason": "minimal_neutral_motion",
    },
}

_KICKFRAME_MOMENTS = {
    "hook_first3",
    "contrast_phrase",
    "risk_phrase",
    "strong_closure",
}


def get_hook_motion_profile(hook_intent: str) -> Dict[str, Any]:
    intent = str(hook_intent or "neutral_explanation")
    profile = dict(MOTION_PACK_PROFILES.get(intent) or MOTION_PACK_PROFILES["neutral_explanation"])
    profile["hook_intent"] = intent if intent in MOTION_PACK_PROFILES else "neutral_explanation"
    logger.info("[motion-pack] hook_intent=%s visual_profile=%s", profile["hook_intent"], profile["visual_profile"])
    logger.info(
        "[motion-pack] scale_start=%.3f scale_end=%.3f frames=%d",
        float(profile["scale_start"]),
        float(profile["scale_end"]),
        int(profile["duration_frames"]),
    )
    logger.info("[motion-pack] contextual=%s reason=%s", str(bool(profile.get("contextual"))).lower(), profile.get("reason") or "none")
    return profile


# ── VPI Premium Composition Pack v1 ─────────────────────────────────────────────

_COMPOSITION_MODE_BY_INTENT: Dict[str, Dict[str, Any]] = {
    "myth_flip": {
        "composition_mode": "hook_driven",
        "screen_priority": "hook_overlay",
        "max_simultaneous_layers": 2,
        "priority_order": ["hook_overlay", "caption", "face"],
        "reason": "myth_flip needs hook overlay first, then caption support",
    },
    "risk_warning": {
        "composition_mode": "warning_tension",
        "screen_priority": "face",
        "max_simultaneous_layers": 2,
        "priority_order": ["face", "caption", "hook_overlay", "sfx"],
        "reason": "risk_warning keeps face visible, caption secondary, hook overlay only if needed",
    },
    "practical_advice": {
        "composition_mode": "explanation_clean",
        "screen_priority": "caption",
        "max_simultaneous_layers": 2,
        "priority_order": ["caption", "face", "lower_third"],
        "reason": "practical_advice prioritises caption readability, lower third for context",
    },
    "autonomous_business_stakes": {
        "composition_mode": "business_punch",
        "screen_priority": "caption",
        "max_simultaneous_layers": 3,
        "priority_order": ["caption", "motion", "sfx"],
        "reason": "business_punch allows up to 3 layers for punchy emphasis",
    },
    "emotional_closure": {
        "composition_mode": "emotional_soft",
        "screen_priority": "face",
        "max_simultaneous_layers": 2,
        "priority_order": ["face", "caption", "music"],
        "reason": "emotional_closure keeps face visible, caption soft, no aggressive layers",
    },
    "neutral_explanation": {
        "composition_mode": "minimal_safe",
        "screen_priority": "caption",
        "max_simultaneous_layers": 1,
        "priority_order": ["caption", "face"],
        "reason": "neutral_explanation uses minimal layers, caption only",
    },
}


def build_composition_decision(
    *,
    hook_intent: str = "",
    visual_profile: str = "",
    caption_overlay_pack: Optional[Dict[str, Any]] = None,
    transition_plan: Optional[Dict[str, Any]] = None,
    sfx_plan: Optional[Dict[str, Any]] = None,
    private_premium_status: str = "",
    segment_text: str = "",
) -> Dict[str, Any]:
    """Build a composition decision for the current clip.

    Returns:
        composition_mode: one of hook_driven, explanation_clean, emotional_soft,
                          warning_tension, business_punch, minimal_safe
        screen_priority: the primary visual element (face, caption, hook_overlay,
                         lower_third, transition, sfx)
        max_simultaneous_layers: 1, 2, or 3 depending on context
        priority_order: ordered list of visual priorities
        reason: human-readable explanation
    """
    resolved_intent = str(hook_intent or "neutral_explanation")
    if resolved_intent not in _COMPOSITION_MODE_BY_INTENT:
        resolved_intent = "neutral_explanation"

    config = _COMPOSITION_MODE_BY_INTENT[resolved_intent]
    composition_mode = str(config["composition_mode"])
    screen_priority = str(config["screen_priority"])
    max_layers = int(config["max_simultaneous_layers"])
    priority_order = list(config["priority_order"])
    reason = str(config["reason"])

    # ── Override: if private_premium_status is DO_NOT_UPLOAD, force minimal_safe ──
    if private_premium_status == "DO_NOT_UPLOAD":
        composition_mode = "minimal_safe"
        screen_priority = "caption"
        max_layers = 1
        priority_order = ["caption"]
        reason = "private_premium_status=DO_NOT_UPLOAD forces minimal_safe"

    # ── Override: if no hook overlay planned, adjust priority ────────────────────
    cap_pack = caption_overlay_pack or {}
    hook_overlay = cap_pack.get("hook_overlay") or {}
    if not hook_overlay.get("applied") and screen_priority == "hook_overlay":
        # Fallback: if hook_overlay was planned but not applied, use caption
        screen_priority = "caption"
        priority_order = [p for p in priority_order if p != "hook_overlay"]
        if "caption" not in priority_order:
            priority_order.insert(0, "caption")
        reason += "; hook_overlay not applied, fallback to caption"

    # ── Override: if transition is strong, adjust layers ─────────────────────────
    trans = transition_plan or {}
    trans_types = trans.get("transition_types") or trans.get("transition_events") or []
    has_strong_transition = any(
        t in {"glitch_clean", "shape_morph_beta", "mask_reveal"}
        for t in trans_types
    )
    if has_strong_transition and composition_mode == "minimal_safe":
        composition_mode = "explanation_clean"
        max_layers = max(max_layers, 2)
        reason += "; strong transition upgrades minimal_safe to explanation_clean"

    # ── Override: if SFX has aggressive impact, warn in reason ───────────────────
    sfx = sfx_plan or {}
    if sfx.get("aggressive_impact_allowed") and composition_mode == "emotional_soft":
        reason += "; WARNING: aggressive SFX conflicts with emotional_soft"

    contextual = bool(
        visual_profile
        or (caption_overlay_pack or {}).get("caption_overlay_pack")
        or (transition_plan or {}).get("transition_types")
        or (sfx_plan or {}).get("sfx_motion_sync_type")
        or segment_text
    )
    logger.info("[composition-pack] mode=%s priority=%s max_layers=%d", composition_mode, screen_priority, max_layers)
    logger.info("[composition-pack] reason=%s", reason)

    return {
        "composition_pack": True,
        "mode": composition_mode,
        "composition_mode": composition_mode,
        "screen_priority": screen_priority,
        "max_layers": max_layers,
        "max_simultaneous_layers": max_layers,
        "priority_order": priority_order,
        "reason": reason,
        "intent": resolved_intent,
        "contextual": contextual,
        "visual_profile": visual_profile,
    }


def resolve_visual_layer_conflicts(
    layers: List[Dict[str, Any]],
    composition_decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve conflicts between visual layers based on composition decision.

    Rules:
      1. Never hook_overlay + icon + lower_third simultaneously.
      2. Never strong transition during hook_overlay.
      3. Never boom SFX in emotional_closure.
      4. Never icon if long caption (>3 words).
      5. Never lower_third in first second if hook overlay active.
      6. Max 2 layers (3 for business_punch).
      7. Never sweeping_reveal in emotional_soft mode.
      8. Never mask_reveal in minimal_safe mode.
    """
    comp_mode = str(composition_decision.get("composition_mode") or "minimal_safe")
    max_layers = int(composition_decision.get("max_simultaneous_layers") or 2)
    priority_order = list(composition_decision.get("priority_order") or [])
    allowed_layers: List[Dict[str, Any]] = []
    skipped_layers: List[Dict[str, Any]] = []
    active_types: List[str] = []
    layer_overload = False

    for index, layer in enumerate(layers):
        layer_type = str(layer.get("type") or layer.get("layer_type") or "")
        if not layer_type:
            allowed_layers.append(layer)
            continue
        reason = "allowed_by_priority"
        allowed = True

        # Rule 1: Never hook_overlay + icon + lower_third simultaneously
        if layer_type in {"hook_overlay", "icon", "lower_third"}:
            triad_count = sum(1 for t in active_types if t in {"hook_overlay", "icon", "lower_third"})
            if triad_count >= 2:
                allowed = False
                reason = "hook_overlay_icon_lower_third_conflict"

        # Rule 2: Never strong transition during hook_overlay
        if allowed and layer_type in {"glitch_clean", "shape_morph_beta", "mask_reveal", "sweeping_reveal", "sweeping_object_reveal"} and "hook_overlay" in active_types:
            allowed = False
            reason = "strong_transition_during_hook_overlay"

        # Rule 2b: avoid B-roll when hook overlay owns the first beat.
        if allowed and layer_type == "broll" and "hook_overlay" in active_types:
            allowed = False
            reason = "broll_during_hook_overlay"

        # Rule 3: Never boom SFX in emotional_closure
        if allowed and layer_type in {"deep_boom", "sfx_hit", "glitch_hit"} and comp_mode == "emotional_soft":
            allowed = False
            reason = "boom_in_emotional_closure"

        # Rule 3b: minimal_safe blocks strong SFX layers by default.
        if allowed and comp_mode == "minimal_safe" and layer_type in {"sfx_riser", "sfx_hit", "sfx_whoosh"}:
            allowed = False
            reason = "minimal_safe_no_strong_sfx"

        # Rule 4: Never icon if long caption
        if allowed and layer_type == "icon":
            caption_text = str(layer.get("text") or layer.get("caption_text") or layer.get("reference_caption") or "")
            if len(caption_text.split()) > 8 or len(caption_text) > 60:
                allowed = False
                reason = "long_caption_with_icon"

        # Rule 5: Never lower_third in first second if hook overlay active
        if allowed and layer_type == "lower_third" and "hook_overlay" in active_types:
            start_s = float(layer.get("start_s") or layer.get("start_time") or 0)
            if start_s < 1.0:
                allowed = False
                reason = "lower_third_first_second_with_hook"

        # Rule 6: Max layers cap
        if allowed and len(active_types) >= max_layers:
            allowed = False
            reason = f"max_layers={max_layers}"
            layer_overload = True

        # Rule 7: Never sweeping_reveal in emotional_soft mode
        if allowed and layer_type == "sweeping_reveal" and comp_mode == "emotional_soft":
            allowed = False
            reason = "sweeping_reveal_in_emotional_soft"

        # Rule 8: Never mask_reveal in minimal_safe mode
        if allowed and layer_type == "mask_reveal" and comp_mode == "minimal_safe":
            allowed = False
            reason = "mask_reveal_in_minimal_safe"

        # Rule 9: B-roll is blocked for minimal_safe and long caption overload.
        if allowed and layer_type == "broll" and comp_mode == "minimal_safe":
            allowed = False
            reason = "broll_in_minimal_safe"
        if allowed and layer_type == "broll":
            caption_text = str(layer.get("caption_text") or layer.get("text") or "")
            if len(caption_text.split()) > 12 or len(caption_text) > 90:
                allowed = False
                reason = "broll_with_long_caption"

        if allowed and priority_order and layer_type not in priority_order and layer_type not in {"caption", "face", "motion", "sfx", "keyword_emphasis"}:
            reason = "allowed_secondary_contextual"

        logger.info("[composition-pack] layer_allowed name=%s yes=%s reason=%s", layer_type, str(allowed).lower(), reason)
        if allowed:
            active_types.append(layer_type)
            allowed_layers.append(layer)
        else:
            skipped_layers.append({**layer, "reason": reason, "index": index})
            logger.info("[composition-pack] conflict_resolved skipped=%s reason=%s", layer_type, reason)

    result = {
        "allowed_layers": allowed_layers,
        "skipped_layers": skipped_layers,
        "layers_final": [str(item.get("type") or item.get("layer_type") or "") for item in allowed_layers],
        "layer_overload": layer_overload,
        "composition_decision_applied": bool(skipped_layers or allowed_layers),
        "conflicts_resolved_count": len(skipped_layers),
    }
    logger.info("[composition-pack] layers_final=%s", "|".join(result["layers_final"]) or "none")
    return result


def first3_visual_contract(
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    caption_overlay_pack: Optional[Dict[str, Any]] = None,
    composition_decision: Optional[Dict[str, Any]] = None,
    visual_effects: Optional[List[Dict[str, Any]]] = None,
    transition_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Check the first 3 seconds visual contract.

    Returns dict with 5 boolean checks:
      - hook_visible_before_1_5s: hook overlay or kickframe visible before 1.5s
      - caption_readable: caption starts within first 3s
      - face_not_obstructed: no layer covers face in first 3s
      - no_layer_overload: max 2 layers active in first 3s
      - motion_contextual: motion pack applied in first 3s

    If contract fails, private_premium_status can drop to REVIEW but not DO_NOT_UPLOAD.
    """
    hp = hook_plan or {}
    cap = caption_overlay_pack or {}
    comp = composition_decision or {}
    vfx = visual_effects or []
    tp = transition_plan or {}
    _resolved_layers = cap.get("composition_allowed_layers") or []

    # Check 1: hook visible before 1.5s
    hook_overlay = cap.get("hook_overlay") or {}
    hook_start = float(hook_overlay.get("start_s") or 99)
    hook_visible = hook_overlay.get("applied") and hook_start < 1.5
    kickframe = hp.get("kickframe_applied") or hp.get("hook_motion_rendered")
    hook_visible_before_1_5s = bool(hook_visible or kickframe)

    # Check 2: caption readable in first 3s
    caption_start = float(cap.get("caption_start_s") or cap.get("start_s") or 0.0)
    caption_readable = bool(caption_start < 3.0)

    # Check 3: face not obstructed
    _has_obstructive_overlay = any(
        str(item.get("type") or item.get("layer_type") or "") in {"hook_overlay", "mask_reveal", "glitch_clean"}
        and float(item.get("start_s") or item.get("start_time") or 99.0) < 1.5
        for item in _resolved_layers
    )
    face_not_obstructed = not _has_obstructive_overlay or str(comp.get("screen_priority") or "") == "hook_overlay"

    # Check 4: no layer overload in first 3s
    no_layer_overload = not bool(cap.get("layer_overload"))

    # Check 5: motion contextual in first 3s
    motion_contextual = any(
        bool(e.get("motion_pack_contextual") or e.get("contextual"))
        and float(e.get("start_s") or 99.0) < 3.0
        for e in vfx
    )

    checks = {
        "hook_visible_before_1_5s": hook_visible_before_1_5s,
        "caption_readable": caption_readable,
        "face_not_obstructed": face_not_obstructed,
        "no_layer_overload": no_layer_overload,
        "motion_contextual": motion_contextual,
    }

    failed_checks = [name for name, value in checks.items() if not value]
    fail_count = len(failed_checks)
    severe_fail = any(name in {"caption_readable", "no_layer_overload"} for name in failed_checks)
    status = "pass" if fail_count == 0 else ("fail" if severe_fail and fail_count >= 2 else "review")
    downgrade_required = fail_count >= 2 or severe_fail
    logger.info("[first3-visual] hook_visible_before_1_5s=%s", str(hook_visible_before_1_5s).lower())
    logger.info("[first3-visual] caption_readable=%s", str(caption_readable).lower())
    logger.info("[first3-visual] face_not_obstructed=%s", str(face_not_obstructed).lower())
    logger.info("[first3-visual] no_layer_overload=%s", str(no_layer_overload).lower())
    logger.info("[first3-visual] motion_contextual=%s", str(motion_contextual).lower())
    logger.info("[first3-visual] status=%s", status)
    logger.info(
        "[first3-visual] private_premium_downgrade=%s reason=%s",
        str(downgrade_required).lower(),
        "|".join(failed_checks) or "none",
    )

    return {
        "first3_visual_contract": checks,
        "first3_visual_passed": status == "pass",
        "first3_visual_fail_count": fail_count,
        "status": status,
        "failed_checks": failed_checks,
        "downgrade_required": downgrade_required,
    }


def build_kickframe_rhythm(intent: str, moment_type: str) -> Dict[str, Any]:
    resolved_intent = str(intent or "neutral_explanation")
    moment = str(moment_type or "")
    if resolved_intent == "neutral_explanation" or moment not in _KICKFRAME_MOMENTS:
        logger.info("[frame-rhythm] skipped reason=no_editorial_moment")
        return {
            "applied": False,
            "reason": "no_editorial_moment",
            "intent": resolved_intent,
            "moment_type": moment,
        }
    profile = get_hook_motion_profile(resolved_intent)
    rhythm = {
        "applied": True,
        "first_kick_frames": 5,
        "second_kick_frames": 10,
        "hold_frames": int(profile.get("hold_frames") or 0),
        "easing": str(profile.get("easing") or "smooth"),
        "intent": profile["hook_intent"],
        "moment_type": moment,
    }
    logger.info("[frame-rhythm] kickframes=5->10 intent=%s reason=%s", profile["hook_intent"], moment)
    return rhythm


def build_frame_rhythm_events(
    events: Optional[List[Dict[str, Any]]] = None,
    *,
    fps: int = 30,
    has_progression_context: bool = True,
) -> Dict[str, Any]:
    if not has_progression_context:
        logger.info("[frame-rhythm] skipped reason=no_progression_context")
        return {
            "frame_rhythm_applied": False,
            "frame_rhythm_pattern": [],
            "frame_rhythm_events": [],
            "reason": "no_progression_context",
        }
    source = list(events or [{"event": "hook_emphasis"}, {"event": "transition_reveal"}])
    out: List[Dict[str, Any]] = []
    for idx, event in enumerate(source):
        frames = 5 if idx % 2 == 0 else 10
        next_frames = 10 if frames == 5 else 5
        item = {
            **event,
            "frames": frames,
            "duration_s": round(frames / float(fps), 3),
            "next_frames": next_frames,
            "applied": True,
        }
        out.append(item)
        if frames == 5:
            logger.info("[frame-rhythm] event=%s frames=5 next=10 applied=true", event.get("event") or event.get("type") or idx)
    return {
        "frame_rhythm_applied": True,
        "frame_rhythm_pattern": "5_to_10",
        "frame_rhythm_events": out,
        "fps": fps,
    }


def plan_premium_transition(
    *,
    event_type: str = "idea_shift",
    bbox: Optional[Dict[str, float]] = None,
    subject_area: Optional[Dict[str, float]] = None,
    fps: int = 30,
) -> Dict[str, Any]:
    if event_type in {"idea_shift", "concept_entry", "sweeping_reveal"}:
        logger.info("[transition] type=sweeping_reveal reason=idea_shift frames=5")
        return {
            "transition_type": "sweeping_reveal",
            "transition_reason": "idea_shift",
            "transition_duration_frames": 5,
            "sweeping_reveal_applied": True,
            "mask_reveal_bbox": None,
            "duration_s": round(5 / float(fps), 3),
        }
    if event_type in {"object_focus", "mask_reveal", "bbox_focus"}:
        safe_bbox = bbox or subject_area
        if safe_bbox:
            logger.info("[transition] type=mask_reveal bbox=%s reason=object_focus", safe_bbox)
            return {
                "transition_type": "mask_reveal_bbox",
                "transition_reason": "object_focus",
                "transition_duration_frames": 10,
                "mask_reveal_bbox": safe_bbox,
                "sweeping_reveal_applied": False,
                "duration_s": round(10 / float(fps), 3),
            }
        logger.info("[transition] fallback=clean_cut reason=no_bbox")
        return {
            "transition_type": "clean_cut",
            "transition_reason": "no_bbox",
            "transition_duration_frames": 5,
            "mask_reveal_bbox": None,
            "sweeping_reveal_applied": False,
            "duration_s": round(5 / float(fps), 3),
        }
    return {
        "transition_type": "short_fade" if event_type == "soft_shift" else "clean_cut",
        "transition_reason": event_type,
        "transition_duration_frames": 5,
        "mask_reveal_bbox": None,
        "sweeping_reveal_applied": False,
        "duration_s": round(5 / float(fps), 3),
    }


def plan_motion_scaling(
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    bbox: Optional[Dict[str, float]] = None,
    static_shot: bool = True,
    duration_s: float = 0.0,
) -> Dict[str, Any]:
    hook_type = str((hook_plan or {}).get("hook_type") or "")
    motion_type = "hook_push_in" if hook_type and hook_type != "weak_intro" else "subtle_push_in"
    if bbox:
        motion_type = "object_scale"
    if not static_shot:
        motion_type = "camera_follow_scale"
    event = {
        "type": motion_type,
        "start_s": 0.3,
        "duration_s": min(1.4, max(0.7, float(duration_s or 2.0) * 0.25)),
        "scale": 1.04 if motion_type != "object_scale" else 1.035,
        "target": "bbox" if bbox else "speaker",
        "bbox_used": bool(bbox),
        "bbox": bbox,
        "reason": "hook_or_keyword_focus",
    }
    logger.info("[motion-scale] type=%s target=%s scale=%.3f reason=%s", event["type"], event["target"], event["scale"], event["reason"])
    blur_frames = 5 if motion_type in {"hook_push_in", "object_scale", "camera_follow_scale"} else 0
    if blur_frames:
        logger.info("[motion-blur] applied=true frames=%d", blur_frames)
    return {
        "motion_scaling_events": [event],
        "motion_scaling_target": event["target"],
        "motion_blur_applied": bool(blur_frames),
        "motion_blur_frames": blur_frames,
        "bbox_used": bool(bbox),
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
        )
        raw = (result.stdout or "").strip().splitlines()[0]
        width, height = raw.split("x", 1)
        return max(2, int(width)), max(2, int(height))
    except Exception:
        return 1080, 1920


def _classify_visual_effect_quality(
    events: List[Dict[str, Any]],
) -> str:
    """Classify visual effect quality as 'basic_motion' or 'premium_visual_effect'.

    FASE 6 — Visual Effects Honesty:
    If the only visual effect is a generic subtle_push_in (or micro_zoom),
    classify as basic_motion, not premium_visual_effect.
    """
    if not events:
        return "none"

    for event in events:
        profile = str(event.get("visual_profile") or "")
        scale_start = float(event.get("scale_start") or 1.0)
        scale_end = float(event.get("scale") or event.get("scale_end") or 1.0)
        contextual = bool(event.get("motion_pack_contextual") or event.get("contextual"))
        if profile == "basic_clean_motion":
            continue
        if profile and contextual and abs(scale_end - scale_start) >= 0.025:
            return "premium_visual_effect"

    # Premium effects that genuinely enhance retention
    premium_types = {"hook_push_in", "punch_zoom", "emphasis_zoom", "object_scale",
                     "camera_follow_scale", "ken_burns", "dynamic_zoom"}

    # Basic motion types that are generic / low-effort
    basic_types = {"subtle_push_in", "micro_zoom"}

    all_types = {e.get("type", "") for e in events}

    # If any premium effect is present, classify as premium
    if all_types & premium_types:
        return "premium_visual_effect"

    # If only basic motion types, classify as basic_motion
    if all_types and all_types.issubset(basic_types):
        return "basic_motion"

    # Fallback: if mixed or unknown, be conservative
    return "basic_motion"


def plan_visual_effects(
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    no_broll: bool = False,
    editorial_type: str = "",
    duration_s: float = 0.0,
) -> List[Dict[str, Any]]:
    """Plan subtle visible edit events for clips that need post-production energy.

    v4.0 retention: ensures first-3-seconds visual support when hook is strong.
    Adds hook_push_in effect for strong hooks to reinforce the first 3 seconds.

    FASE 6 — Visual Effects Honesty + Intent-Aware Effects:
    Each event includes a 'visual_effect_classification' field:
      - 'premium_visual_effect' for hook_push_in, punch_zoom, emphasis_zoom, etc.
      - 'basic_motion' for generic subtle_push_in or micro_zoom only.

    When hook_intent is available from hook_plan, uses the recommended_visual
    from the style map instead of defaulting to hook_push_in, making effects
    contextually appropriate per intent.
    """
    hook_plan = hook_plan or {}
    hook_type = str(hook_plan.get("hook_type") or "").lower()
    if hook_type == "weak_intro" or str(editorial_type or "").lower() == "weak_intro":
        return []

    events: List[Dict[str, Any]] = []

    hook_intent = str(hook_plan.get("hook_intent") or "")
    motion_profile = get_hook_motion_profile(hook_intent or "neutral_explanation")
    intent_aware_effect = str(motion_profile.get("effect_type") or "subtle_push_in")
    visual_profile = str(motion_profile.get("visual_profile") or "basic_clean_motion")
    kickframe = build_kickframe_rhythm(
        str(motion_profile.get("hook_intent") or hook_intent or "neutral_explanation"),
        "hook_first3" if hook_type != "weak_intro" else "none",
    )

    def _motion_event(reason: str, start_s: float = 0.30) -> Dict[str, Any]:
        return {
            "type": intent_aware_effect,
            "visual_profile": visual_profile,
            "start_s": start_s,
            "duration_s": round(int(motion_profile.get("duration_frames") or 12) / 30.0, 3),
            "duration_frames": int(motion_profile.get("duration_frames") or 12),
            "scale_start": float(motion_profile.get("scale_start") or 1.0),
            "scale": float(motion_profile.get("scale_end") or 1.025),
            "scale_end": float(motion_profile.get("scale_end") or 1.025),
            "easing": str(motion_profile.get("easing") or "smooth"),
            "hold_frames": int(motion_profile.get("hold_frames") or 0),
            "motion_pack_contextual": bool(motion_profile.get("contextual")),
            "motion_pack_profile": visual_profile,
            "motion_pack_applied": bool(motion_profile.get("contextual")),
            "kickframe_rhythm": kickframe if kickframe.get("applied") else None,
            "reason": reason,
        }

    # ── v4.0: First 3 seconds hook visual reinforcement ──────────────────────
    # When hook_first3_status is READY, ensure a strong visual push in first 3s.
    hook_first3_status = str(hook_plan.get("hook_first3_status") or "")
    hook_first3_score = int(hook_plan.get("hook_first3_score") or 0)

    if hook_first3_status == "READY" and hook_first3_score >= 5:
        events.append(_motion_event(f"intent_aware_{hook_intent or 'neutral_explanation'}_motion_pack"))
        logger.info("[visual-effects] intent_aware_effect type=%s intent=%s status=%s score=%d", intent_aware_effect, hook_intent, hook_first3_status, hook_first3_score)
    elif hook_first3_status == "strong" and hook_first3_score >= 7:
        events.append(_motion_event(f"intent_aware_{hook_intent or 'neutral_explanation'}_motion_pack"))
        logger.info("[visual-effects] intent_aware_effect type=%s intent=%s status=%s score=%d", intent_aware_effect, hook_intent, hook_first3_status, hook_first3_score)
    elif hook_plan.get("kickframe_applied") or hook_type in {"objection_breaker", "client_objection", "myth_debunk", "risk_warning"}:
        events.append(_motion_event("motion_pack_kickframe_hook", start_s=0.42))
    elif hook_plan.get("hook_motion_rendered") or hook_plan.get("rendered"):
        events.append(_motion_event("motion_pack_rendered_hook", start_s=0.45))
    else:
        events.append(_motion_event("motion_pack_first3_support", start_s=0.55))

    if no_broll and duration_s >= 12.0:
        events.append({"type": "emphasis_zoom", "start_s": min(6.0, max(3.2, duration_s * 0.32)), "duration_s": 1.2, "scale": 1.035, "reason": "speaker_focus_no_broll"})

    # ── FASE 6: Classify each event's visual effect quality ──────────────────
    overall_classification = _classify_visual_effect_quality(events)
    contextual_actions = [
        str(event.get("visual_profile") or event.get("type"))
        for event in events
        if event.get("motion_pack_contextual") or event.get("kickframe_rhythm")
    ]
    motion_pack_applied = bool(contextual_actions)
    logger.info("[motion-pack] applied=%s contextual_actions=%s", str(motion_pack_applied).lower(), "|".join(contextual_actions) or "none")
    logger.info("[editing-richness] motion_pack=%s", str(motion_pack_applied).lower())
    logger.info(
        "[editing-richness] premium_visual_effect=%s reason=%s",
        str(overall_classification == "premium_visual_effect").lower(),
        "contextual_motion_pack" if overall_classification == "premium_visual_effect" else "basic_or_no_contextual_motion",
    )
    for event in events:
        event["visual_effect_classification"] = overall_classification
        event["premium_visual_effect"] = overall_classification == "premium_visual_effect"
        event["motion_pack_applied"] = motion_pack_applied
        event["motion_pack_contextual_actions"] = contextual_actions
        if overall_classification == "basic_motion":
            logger.info("[vfx-qc] type=basic_motion premium=false reason=generic_push_in")
        else:
            logger.info(
                "[vfx-qc] type=contextual_emphasis premium=true reason=%s",
                event.get("reason") or "intent_aware_visual_effect",
            )

    return events[:2]



def apply_visual_effects(
    input_path: Path,
    output_path: Path,
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    no_broll: bool = False,
    editorial_type: str = "",
    duration_s: float = 0.0,
) -> Dict[str, Any]:
    events = plan_visual_effects(
        hook_plan=hook_plan,
        no_broll=no_broll,
        editorial_type=editorial_type,
        duration_s=duration_s,
    )
    logger.info("[visual-effects] planned events=%s", events)
    if not events:
        logger.info("[visual-effects] skipped reason=no_visual_effect_events")
        return {
            "visual_effects_applied": False,
            "visual_effects_count": 0,
            "visual_effects_events": [],
            "visual_effects_warning": "no_visual_effect_events",
        }

    motion_meta = plan_motion_scaling(
        hook_plan=hook_plan,
        static_shot=True,
        duration_s=duration_s,
    )
    motion_blur_requested = any(
        str(event.get("visual_profile") or "") not in {"", "basic_clean_motion"}
        and float(event.get("scale") or 1.0) > 1.02
        for event in events
    )
    if motion_blur_requested:
        logger.info("[motion-blur] applied=true frames=5 reason=motion_scale")
    else:
        logger.info("[motion-blur] skipped reason=no_motion")
    rhythm_meta = build_frame_rhythm_events(
        [{"event": event.get("type", "visual_effect"), "type": event.get("type")} for event in events],
        has_progression_context=len(events) > 0,
    )

    width, height = _probe_size(input_path)
    scale_expr = "1"
    blur_filters: List[str] = []
    for event in reversed(events):
        start = max(0.0, float(event.get("start_s") or 0.0))
        end = start + max(0.1, float(event.get("duration_s") or 0.5))
        scale = max(1.0, min(1.07, float(event.get("scale") or 1.035)))
        scale_expr = f"if(between(t\\,{start:.3f}\\,{end:.3f})\\,{scale:.4f}\\,{scale_expr})"
        if (
            str(event.get("visual_profile") or "") not in {"", "basic_clean_motion"}
            and scale > 1.02
        ):
            blur_filters.append(
                f"boxblur=luma_radius=1:luma_power=1:enable='between(t\\,{start:.3f}\\,{end:.3f})'"
            )
    blur_vf = ("," + ",".join(reversed(blur_filters))) if blur_filters else ""
    vf = (
        f"crop=w='iw/({scale_expr})':h='ih/({scale_expr})':"
        "x='(iw-out_w)/2':y='(ih-out_h)/2',"
        f"scale={width}:{height}{blur_vf},setsar=1"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
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
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        logger.info("[visual-effects] applied=true count=%d output=%s", len(events), output_path)
        return {
            "visual_effects_applied": True,
            "visual_effects_count": len(events),
            "visual_effects_events": events,
            "visual_effect_quality": _classify_visual_effect_quality(events),
            "premium_visual_effect": _classify_visual_effect_quality(events) == "premium_visual_effect",
            **motion_meta,
            **rhythm_meta,
            "motion_pack_applied": any(bool(event.get("motion_pack_applied")) for event in events),
            "motion_pack_contextual_actions": list(dict.fromkeys(
                action
                for event in events
                for action in (event.get("motion_pack_contextual_actions") or [])
            )),
            "motion_blur_applied": bool(motion_blur_requested),
            "motion_blur_frames": 5 if motion_blur_requested else 0,
            "visual_effects_warning": None,
        }

    reason = (result.stderr or "ffmpeg_failed").strip()[-700:]
    logger.warning("[visual-effects] failed reason=%s", reason)
    return {
        "visual_effects_applied": False,
        "visual_effects_count": 0,
        "visual_effects_events": events,
        "visual_effect_quality": _classify_visual_effect_quality(events),
        "premium_visual_effect": _classify_visual_effect_quality(events) == "premium_visual_effect",
        **motion_meta,
        **rhythm_meta,
        "motion_pack_applied": any(bool(event.get("motion_pack_applied")) for event in events),
        "motion_pack_contextual_actions": list(dict.fromkeys(
            action
            for event in events
            for action in (event.get("motion_pack_contextual_actions") or [])
        )),
        "motion_blur_applied": bool(motion_blur_requested),
        "motion_blur_frames": 5 if motion_blur_requested else 0,
        "visual_effects_warning": reason,
    }
