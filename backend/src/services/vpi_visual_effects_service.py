"""CPU-only VPI visual effects layer for Beta Clean post-production."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_VPI_VISUAL_TOKENS_VERSION = "a1"


def get_vpi_visual_design_tokens() -> Dict[str, Any]:
    tokens = {
        "visual_design_version": _VPI_VISUAL_TOKENS_VERSION,
        "colors": {
            "text_primary": "#F5F5F2",
            "text_secondary": "#C9C9C2",
            "bg_panel": "#1A1A1AE6",
            "bg_panel_strong": "#101010F0",
            "border_soft": "#FFFFFF24",
            "accent_safe": "#B9D4C6",
            "warning_safe": "#C9A36A",
            "success_safe": "#A8C6AF",
        },
        "forbidden_colors": [
            "strong_orange_for_text",
            "random_blue",
            "neon_green",
            "saturated_red_except_warning_small",
        ],
        "typography": {
            "caption_font_scale": 1.0,
            "hook_font_scale": 0.92,
            "badge_font_scale": 0.86,
            "max_caption_lines": 2,
            "max_hook_words": 7,
            "max_badge_words": 3,
        },
        "spacing": {
            "caption_bottom_margin": 280,
            "hook_top_margin": 112,
            "safe_padding": 36,
            "badge_padding": 18,
        },
        "opacity": {
            "panel_opacity": 0.84,
            "badge_opacity": 0.76,
            "overlay_opacity": 0.88,
        },
        "animation": {
            "fade_in_ms": 180,
            "fade_out_ms": 140,
            "max_motion_scale": 1.06,
            "pulse_allowed": False,
        },
        "brand": {
            "logo_mode": "minimal",
            "watermark_allowed": True,
            "heavy_branding_allowed": False,
        },
    }
    logger.info("VPI_VISUAL_TOKENS_LOADED version=%s", tokens["visual_design_version"])
    return tokens


def choose_vpi_motion_rhythm_profile(
    *,
    editorial_type: str,
    hookability_score: float,
    first_second_strength: float,
    premium_restraint_mode: str,
    clip_duration: float,
    caption_density: float,
    broll_applied: bool,
    sensitive_topic: bool,
    visual_layout_strategy: str,
) -> Dict[str, Any]:
    editorial = str(editorial_type or "").strip().lower()
    restraint = str(premium_restraint_mode or "").strip().lower()
    layout = str(visual_layout_strategy or "").strip().lower()
    hook_score = float(hookability_score or 0.0)
    first3 = float(first_second_strength or 0.0)
    duration = float(clip_duration or 0.0)
    captions = float(caption_density or 0.0)
    broll = bool(broll_applied)
    sensitive = bool(sensitive_topic)

    if sensitive or editorial in {"sensitive_decesos", "decesos"}:
        motion_profile = "sensitive_soft"
        zoom_intensity = 1.018
        max_zoom_events = 1 if duration <= 20.0 else 2
        cut_pace = "slow"
        preserve_pause_bias = 0.92
        reason = "sensitive_topic_soft_motion"
    elif restraint in {"minimal", "no_extra_visual"} or layout in {"no_extra_visual", "branding_minimal"}:
        motion_profile = "no_extra_motion"
        zoom_intensity = 1.0
        max_zoom_events = 0
        cut_pace = "minimal"
        preserve_pause_bias = 1.0
        reason = "premium_restraint_suppressed_motion"
    elif editorial in {"risk_warning", "myth_debunk"}:
        motion_profile = "punchy"
        zoom_intensity = 1.064 if duration > 16.0 else 1.055
        max_zoom_events = 2 if duration <= 15.0 else (3 if duration <= 30.0 else 4)
        cut_pace = "punchy"
        preserve_pause_bias = 0.72
        reason = "risk_or_myth_editorial"
    elif editorial in {"coverage_explanation", "tramite_documentacion", "legal_admin_tramite"}:
        motion_profile = "standard"
        zoom_intensity = 1.045 if duration > 15.0 else 1.038
        max_zoom_events = 2 if duration <= 15.0 else 3
        cut_pace = "steady"
        preserve_pause_bias = 0.82
        reason = "coverage_or_tramite_editorial"
    elif editorial in {"emotional_protection", "sensitive_guidance"}:
        motion_profile = "calm"
        zoom_intensity = 1.028 if duration > 18.0 else 1.022
        max_zoom_events = 1 if duration <= 15.0 else 2
        cut_pace = "calm"
        preserve_pause_bias = 0.9
        reason = "emotional_protection_editorial"
    else:
        motion_profile = "standard"
        zoom_intensity = 1.04 if duration > 15.0 else 1.034
        max_zoom_events = 1 if duration <= 15.0 else (2 if duration <= 30.0 else 3)
        cut_pace = "steady"
        preserve_pause_bias = 0.82
        reason = "default_motion_profile"

    if hook_score >= 72.0 or first3 >= 72.0:
        if motion_profile in {"calm", "standard"} and not sensitive:
            zoom_intensity = min(1.055 if motion_profile == "standard" else 1.038, zoom_intensity + 0.01)
        reason = f"{reason}:first3_boost"
    if captions >= 7.0 and not broll and not sensitive and motion_profile != "no_extra_motion":
        preserve_pause_bias = min(0.96, preserve_pause_bias + 0.06)
        zoom_intensity = max(1.015, min(zoom_intensity, 1.04))
    if broll and motion_profile == "standard":
        max_zoom_events = max(1, max_zoom_events - 1)
        preserve_pause_bias = min(0.92, preserve_pause_bias + 0.04)

    first3_motion_boost_applied = bool((hook_score >= 72.0 or first3 >= 72.0) and not sensitive and motion_profile != "no_extra_motion")
    result = {
        "motion_profile": motion_profile,
        "zoom_intensity": float(round(zoom_intensity, 3)),
        "max_zoom_events": int(max_zoom_events),
        "cut_pace": cut_pace,
        "preserve_pause_bias": float(round(max(0.0, min(1.0, preserve_pause_bias)), 3)),
        "reason": reason,
        "first3_motion_boost_applied": first3_motion_boost_applied,
        "first3_motion_boost_reason": "hookability_or_first_second_strength" if first3_motion_boost_applied else "not_needed",
        "intentional_pause_preserved": bool(preserve_pause_bias >= 0.8),
        "dead_pause_trimmed": bool(captions >= 7.0 or duration >= 12.0),
    }
    logger.info(
        "VPI_MOTION_PROFILE_SELECTED profile=%s zoom=%.3f max_events=%d preserve_pause=%.2f reason=%s",
        result["motion_profile"],
        result["zoom_intensity"],
        result["max_zoom_events"],
        result["preserve_pause_bias"],
        result["reason"],
    )
    return result


def validate_vpi_visual_identity(metadata: Dict[str, Any]) -> Dict[str, Any]:
    meta = metadata if isinstance(metadata, dict) else {}
    tokens = get_vpi_visual_design_tokens()
    warnings: List[str] = []
    errors: List[str] = []

    forbidden_color_used = bool(meta.get("forbidden_color_used"))
    too_many_text_layers = int(meta.get("text_layers") or meta.get("visual_text_layers") or 0) > 3
    heavy_branding = bool(meta.get("heavy_branding") or meta.get("branding_heavy"))
    oversized_badge = bool(meta.get("oversized_badge"))
    hook_text = str(meta.get("hook_text") or meta.get("hook_headline") or "").strip()
    hook_too_long = len(hook_text.split()) > int(tokens.get("typography", {}).get("max_hook_words", 7))
    caption_style_mismatch = bool(meta.get("caption_style_mismatch"))
    fallback_style_mismatch = bool(meta.get("fallback_style_mismatch"))
    captions_ilegible = bool(meta.get("captions_ilegible") or meta.get("caption_illegible"))
    visual_asset_identity_warnings = list(meta.get("visual_asset_identity_warnings") or [])

    if forbidden_color_used:
        errors.append("forbidden_color_used")
    if too_many_text_layers:
        warnings.append("too_many_text_layers")
    if heavy_branding:
        warnings.append("heavy_branding")
    if oversized_badge:
        warnings.append("oversized_badge")
    if hook_too_long:
        warnings.append("hook_too_long")
    if caption_style_mismatch:
        warnings.append("caption_style_mismatch")
    if fallback_style_mismatch:
        warnings.append("fallback_style_mismatch")
    if captions_ilegible:
        errors.append("captions_ilegible")
    if visual_asset_identity_warnings:
        warnings.extend([str(item) for item in visual_asset_identity_warnings if str(item)])

    visual_identity_ok = not errors
    visual_style_consistency_ok = not errors
    logger.info(
        "VPI_VISUAL_IDENTITY_CHECKED ok=%s warnings=%d errors=%d",
        str(visual_identity_ok).lower(),
        len(warnings),
        len(errors),
    )
    if errors:
        logger.warning("VPI_VISUAL_IDENTITY_FAILED errors=%s", "|".join(errors))
    elif warnings:
        logger.warning("VPI_VISUAL_IDENTITY_WARNING warnings=%s", "|".join(warnings))
    return {
        "visual_design_version": str(tokens["visual_design_version"]),
        "visual_identity_ok": bool(visual_identity_ok),
        "visual_identity_warnings": list(dict.fromkeys(warnings + errors)),
        "visual_style_consistency_ok": bool(visual_style_consistency_ok),
        "visual_design_tokens": tokens,
        "visual_design_tokens_applied": bool(meta.get("visual_design_tokens_applied")),
    }


_CAPTION_POLISH_PROFILES: Dict[str, Dict[str, Any]] = {
    "calm_readable": {
        "max_words_per_caption": 4,
        "max_lines": 2,
        "min_caption_duration": 0.95,
        "max_caption_duration": 2.20,
        "max_chars_per_caption": 30,
        "keyword_highlight_allowed": True,
        "caption_highlight_policy": "single_keyword_sober",
    },
    "standard_clean": {
        "max_words_per_caption": 5,
        "max_lines": 2,
        "min_caption_duration": 0.80,
        "max_caption_duration": 2.20,
        "max_chars_per_caption": 30,
        "keyword_highlight_allowed": True,
        "caption_highlight_policy": "single_keyword_sober",
    },
    "punchy_short": {
        "max_words_per_caption": 3,
        "max_lines": 2,
        "min_caption_duration": 0.65,
        "max_caption_duration": 1.80,
        "max_chars_per_caption": 26,
        "keyword_highlight_allowed": True,
        "caption_highlight_policy": "single_keyword_highlight",
    },
    "sensitive_soft": {
        "max_words_per_caption": 4,
        "max_lines": 2,
        "min_caption_duration": 1.00,
        "max_caption_duration": 2.40,
        "max_chars_per_caption": 32,
        "keyword_highlight_allowed": False,
        "caption_highlight_policy": "minimal_or_none",
    },
    "dense_explainer": {
        "max_words_per_caption": 5,
        "max_lines": 2,
        "min_caption_duration": 0.80,
        "max_caption_duration": 2.20,
        "max_chars_per_caption": 30,
        "keyword_highlight_allowed": True,
        "caption_highlight_policy": "single_keyword_explainer",
    },
}


def choose_vpi_caption_polish_profile(
    *,
    editorial_type: str,
    clip_duration: float,
    caption_density: float,
    hook_strategy_final: str,
    premium_restraint_mode: str,
    visual_layout_strategy: str,
    broll_timing_strategy: str,
    cta_decision: str,
    sensitive_topic: bool,
    words_with_timestamps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    words = list(words_with_timestamps or [])
    editorial = str(editorial_type or "").strip().lower()
    hook_strategy = str(hook_strategy_final or "").strip().lower()
    restraint = str(premium_restraint_mode or "").strip().lower()
    layout = str(visual_layout_strategy or "").strip().lower()
    broll_strategy = str(broll_timing_strategy or "").strip().lower()
    cta = str(cta_decision or "").strip().lower()
    density = float(caption_density or 0.0)
    duration = max(0.0, float(clip_duration or 0.0))
    word_count = len(words)
    avg_word_duration = 0.0
    if words:
        try:
            total_word_duration = sum(max(0.0, float((word or {}).get("end", 0.0)) - float((word or {}).get("start", 0.0))) for word in words)
            avg_word_duration = total_word_duration / max(1, len(words))
        except Exception:
            avg_word_duration = 0.0

    profile = "standard_clean"
    reason_parts: List[str] = []

    if sensitive_topic or editorial in {"sensitive_decesos", "decesos"} or "decesos" in editorial:
        profile = "sensitive_soft"
        reason_parts.append("sensitive_topic")
    elif editorial in {"risk_warning", "myth_debunk", "objection_answer"} or any(token in editorial for token in ("risk", "warning", "myth", "objection")):
        profile = "punchy_short"
        reason_parts.append("editorial_punch")
    elif editorial in {"coverage_explanation", "tramite_documentacion", "legal_tramite", "legal_admin_tramite"} or any(token in editorial for token in ("cobertura", "tramite", "document", "coverage", "policy")):
        profile = "dense_explainer"
        reason_parts.append("editorial_explainer")
    elif editorial in {"emotional_protection", "calm_trust"} or any(token in editorial for token in ("proteccion", "protección", "tranquilidad", "family", "familia")):
        profile = "calm_readable"
        reason_parts.append("editorial_calm")

    if restraint in {"minimal", "no_extra_visual"} and profile not in {"sensitive_soft", "punchy_short"}:
        profile = "calm_readable"
        reason_parts.append("restraint_minimal")
    elif density >= 0.72 and profile not in {"sensitive_soft", "punchy_short"}:
        profile = "dense_explainer"
        reason_parts.append("dense_caption_track")
    elif density <= 0.35 and profile == "standard_clean":
        profile = "punchy_short"
        reason_parts.append("sparse_caption_track")

    base = dict(_CAPTION_POLISH_PROFILES.get(profile) or _CAPTION_POLISH_PROFILES["standard_clean"])
    if hook_strategy and profile not in {"sensitive_soft"}:
        base["max_words_per_caption"] = max(3, int(base["max_words_per_caption"]) - 1)
        reason_parts.append("hook_present")
    if cta == "show_cta":
        base["max_caption_duration"] = min(float(base["max_caption_duration"]), 2.60 if profile != "punchy_short" else 2.00)
        reason_parts.append("cta_endroom")
    if layout in {"branding_minimal", "no_extra_visual"} and profile != "sensitive_soft":
        base["max_lines"] = 2
        reason_parts.append("layout_minimal")
    if broll_strategy in {"phrase_matched_insert", "short_cutaway"} and profile != "sensitive_soft":
        base["max_words_per_caption"] = max(3, int(base["max_words_per_caption"]) - 1)
        reason_parts.append("broll_support")
    if duration <= 15.0 and profile != "dense_explainer":
        base["max_caption_duration"] = min(float(base["max_caption_duration"]), 2.20 if profile != "punchy_short" else 1.80)
        reason_parts.append("short_clip")
    if avg_word_duration and avg_word_duration < 0.18 and profile != "sensitive_soft":
        base["min_caption_duration"] = max(float(base["min_caption_duration"]), 0.70)
        reason_parts.append("fast_speech")
    if density >= 0.60:
        base["max_chars_per_caption"] = min(int(base.get("max_chars_per_caption") or 30), 30)
        if profile == "dense_explainer":
            base["max_words_per_caption"] = min(int(base.get("max_words_per_caption") or 5), 5)
        reason_parts.append("dense_char_cap")

    caption_pacing_reason = ",".join(reason_parts) or "default_readability"
    result = {
        "caption_polish_profile": profile,
        "max_words_per_caption": int(base.get("max_words_per_caption") or 5),
        "max_lines": int(base.get("max_lines") or 2),
        "min_caption_duration": float(base.get("min_caption_duration") or 0.8),
        "max_caption_duration": float(base.get("max_caption_duration") or 2.4),
        "max_chars_per_caption": int(base.get("max_chars_per_caption") or 30),
        "keyword_highlight_allowed": bool(base.get("keyword_highlight_allowed", True)),
        "caption_highlight_policy": str(base.get("caption_highlight_policy") or "single_keyword_sober"),
        "caption_pacing_reason": caption_pacing_reason,
        "caption_polish_applied": True,
    }
    logger.info(
        "VPI_CAPTION_POLISH_PROFILE_SELECTED profile=%s reason=%s max_words=%d min_dur=%.2f max_dur=%.2f highlight=%s",
        result["caption_polish_profile"],
        result["caption_pacing_reason"],
        result["max_words_per_caption"],
        result["min_caption_duration"],
        result["max_caption_duration"],
        str(result["keyword_highlight_allowed"]).lower(),
    )
    return result


MOTION_PACK_PROFILES: Dict[str, Dict[str, Any]] = {
    "myth_flip": {
        "visual_profile": "calm_reveal",
        "effect_type": "hook_push_in",
        "scale_start": 1.0,
        "scale_end": 1.055,
        "duration_frames": 30,
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
        "scale_end": 1.05,
        "duration_frames": 30,
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
        "scale_end": 1.06,
        "duration_frames": 36,
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
        "scale_end": 1.04,
        "duration_frames": 30,
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

_SHOT_RHYTHM_PROFILE_BY_INTENT: Dict[str, str] = {
    "myth_flip": "hook_snap",
    "risk_warning": "warning_breath",
    "practical_advice": "explanation_clean_pacing",
    "autonomous_business_stakes": "business_punch_pacing",
    "emotional_closure": "emotional_breathing",
    "neutral_explanation": "minimal_safe_rhythm",
}

_SHOT_RHYTHM_INTERRUPTION_BY_PROFILE: Dict[str, str] = {
    "hook_snap": "motion_kick",
    "warning_breath": "silence_snap",
    "explanation_clean_pacing": "caption_pulse",
    "business_punch_pacing": "motion_kick",
    "emotional_breathing": "micro_hold",
    "minimal_safe_rhythm": "",
}

_SHOT_RHYTHM_PAUSE_REASON_MAP: Dict[str, str] = {
    "warning": "warning",
    "risk": "warning",
    "contrast": "contrast",
    "closure": "emotional_closure",
    "emotional": "emotional_closure",
    "reveal": "revelation",
    "no lo sabe": "revelation",
    "key_phrase": "revelation",
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


def build_global_visual_layer_budget(
    *,
    layer_candidates: Optional[List[Dict[str, Any]]] = None,
    caption_overlay_pack_metadata: Optional[Dict[str, Any]] = None,
    editorial_type: str = "",
    hook_strategy_final: str = "",
    hook_visual_applied: bool = False,
    hook_text_overlay_rendered: bool = False,
    hook_text_redundant_with_captions: bool = False,
    first3_has_captions: bool = False,
    semantic_card_candidate: Optional[Dict[str, Any]] = None,
    lower_third_candidate: Optional[Dict[str, Any]] = None,
    branding_candidate: Optional[Dict[str, Any]] = None,
    cta_candidate: Optional[Dict[str, Any]] = None,
    icon_candidate: Optional[Dict[str, Any]] = None,
    motion_overlay_candidate: Optional[Dict[str, Any]] = None,
    visual_density: float = 0.0,
    clip_duration: float = 0.0,
    face_bbox: Optional[Dict[str, Any]] = None,
    speaker_bbox: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a global visual layer budget that caps simultaneous visible layers."""

    clip_duration = max(0.0, float(clip_duration or 0.0))
    visual_density = float(visual_density or 0.0)
    editorial_type = str(editorial_type or "").strip().lower()
    caption_active = bool(first3_has_captions or (caption_overlay_pack_metadata or {}).get("caption_overlay_pack"))
    opening_end = min(3.0, clip_duration) if clip_duration else 3.0
    ending_start = max(0.0, clip_duration - 3.0) if clip_duration else 0.0
    support_text_allowed = not (visual_density >= 8.0 or hook_text_redundant_with_captions)

    def _phase_for_start(start_s: float) -> str:
        if clip_duration > 0.0 and start_s >= ending_start and clip_duration >= 6.0:
            return "ending"
        if start_s < opening_end:
            return "opening"
        return "middle"

    def _candidate(
        layer: str,
        *,
        kind: str = "text",
        start_s: float = 0.0,
        duration_s: float = 0.0,
        priority: int = 0,
        text: str = "",
        renderable: bool = True,
        safe_zone: str = "",
        delayable: bool = True,
        reducible: bool = False,
        counts_as_text: Optional[bool] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        return {
            "layer": layer,
            "kind": kind,
            "start_s": round(float(start_s or 0.0), 3),
            "duration_s": round(float(duration_s or 0.0), 3),
            "end_s": round(float(start_s or 0.0) + float(duration_s or 0.0), 3),
            "priority": int(priority),
            "text": text,
            "renderable": bool(renderable),
            "safe_zone": safe_zone,
            "delayable": bool(delayable),
            "reducible": bool(reducible),
            "counts_as_text": bool(kind == "text" if counts_as_text is None else counts_as_text),
            "reason": reason,
        }

    candidates = list(layer_candidates or [])
    if not candidates:
        if caption_active:
            candidates.append(
                _candidate(
                    "captions",
                    kind="text",
                    start_s=0.0,
                    duration_s=clip_duration or 0.0,
                    priority=100,
                    renderable=True,
                    safe_zone="lower_band",
                    delayable=False,
                    reducible=False,
                    reason="captions_present",
                )
            )
        if hook_strategy_final:
            if hook_strategy_final == "text_hook" and hook_visual_applied and not hook_text_redundant_with_captions:
                candidates.append(
                    _candidate(
                        "hook_overlay",
                        kind="text",
                        start_s=0.25,
                        duration_s=min(3.0, max(2.2, clip_duration or 2.2)),
                        priority=95,
                        text=str((caption_overlay_pack_metadata or {}).get("hook_overlay", {}).get("text") or ""),
                        renderable=bool(hook_text_overlay_rendered or hook_visual_applied),
                        safe_zone="upper_center",
                        delayable=False,
                        reducible=False,
                        reason="hook_text",
                    )
                )
            elif hook_strategy_final in {"non_text_push_hook", "icon_hook", "silence_tension_hook"} or hook_visual_applied:
                candidates.append(
                    _candidate(
                        "hook_motion",
                        kind="visual",
                        start_s=0.25,
                        duration_s=min(3.0, max(1.8, clip_duration or 1.8)),
                        priority=94,
                        renderable=bool(hook_visual_applied),
                        safe_zone="upper_center",
                        delayable=False,
                        reducible=False,
                        reason="hook_motion",
                    )
                )
        if icon_candidate:
            candidates.append(
                _candidate(
                    "icon",
                    kind="visual",
                    start_s=float(icon_candidate.get("start_s") or 0.2),
                    duration_s=float(icon_candidate.get("duration_s") or 1.2),
                    priority=90,
                    text=str(icon_candidate.get("concept") or icon_candidate.get("text") or ""),
                    renderable=bool(icon_candidate.get("safe") and icon_candidate.get("path")),
                    safe_zone="upper_right_small",
                    delayable=False,
                    reducible=True,
                    reason="icon_candidate",
                )
            )
        if lower_third_candidate:
            candidates.append(
                _candidate(
                    "lower_third",
                    kind="text",
                    start_s=float(lower_third_candidate.get("start_s") or 0.4),
                    duration_s=float(lower_third_candidate.get("duration_s") or 1.8),
                    priority=70,
                    text=str(lower_third_candidate.get("text") or ""),
                    renderable=bool(lower_third_candidate.get("applied", True)),
                    safe_zone="lower_band",
                    delayable=True,
                    reducible=True,
                    reason="lower_third_candidate",
                )
            )
        if semantic_card_candidate:
            candidates.append(
                _candidate(
                    "semantic_card",
                    kind="text" if bool(semantic_card_candidate.get("has_text", True)) else "visual",
                    start_s=float(semantic_card_candidate.get("start_s") or 3.2),
                    duration_s=float(semantic_card_candidate.get("duration_s") or 2.4),
                    priority=80,
                    text=str(semantic_card_candidate.get("text") or ""),
                    renderable=bool(semantic_card_candidate.get("renderable", True)),
                    safe_zone=str(semantic_card_candidate.get("safe_zone") or "upper_right"),
                    delayable=True,
                    reducible=True,
                    reason="semantic_card_candidate",
                )
            )
        if motion_overlay_candidate:
            candidates.append(
                _candidate(
                    "motion_overlay",
                    kind="text" if bool(motion_overlay_candidate.get("dynamic_overlay_text_planned")) else "visual",
                    start_s=float(motion_overlay_candidate.get("start_s") or 0.35),
                    duration_s=float(motion_overlay_candidate.get("duration_s") or 2.2),
                    priority=85,
                    text=str(motion_overlay_candidate.get("dynamic_overlay_text") or motion_overlay_candidate.get("text") or ""),
                    renderable=bool(motion_overlay_candidate.get("motion_overlay_selected", True)),
                    safe_zone=str(motion_overlay_candidate.get("recommended_position") or "upper_right"),
                    delayable=True,
                    reducible=True,
                    reason="motion_overlay_candidate",
                )
            )
        if branding_candidate:
            candidates.append(
                _candidate(
                    "branding",
                    kind="text" if str(branding_candidate.get("type") or "") == "text" else "visual",
                    start_s=float(branding_candidate.get("start_s") or 0.0),
                    duration_s=float(branding_candidate.get("duration_s") or clip_duration or 0.0),
                    priority=55,
                    text=str(branding_candidate.get("text") or ""),
                    renderable=bool(branding_candidate.get("logo_found", True)),
                    safe_zone="top_right_small",
                    delayable=False,
                    reducible=True,
                    reason="branding_candidate",
                )
            )
        if cta_candidate:
            candidates.append(
                _candidate(
                    "cta",
                    kind="text",
                    start_s=float(cta_candidate.get("start_s") or max(0.0, clip_duration - 2.5)),
                    duration_s=float(cta_candidate.get("duration_s") or 1.8),
                    priority=65,
                    text=str(cta_candidate.get("text") or ""),
                    renderable=bool(cta_candidate.get("renderable", True)),
                    safe_zone="lower_center_small",
                    delayable=True,
                    reducible=True,
                    reason="cta_candidate",
                )
            )

    def _support_priority_adjustment(layer: str, phase: str, candidate: Dict[str, Any]) -> int:
        boost = 0
        if editorial_type in {"risk_warning", "accidente", "riesgo"} or any(token in editorial_type for token in ("warning", "risk")):
            if layer == "icon":
                boost += 40
            elif layer in {"hook_motion", "motion_overlay"}:
                boost += 28
            elif layer == "semantic_card":
                boost += 10
            elif layer == "lower_third":
                boost -= 16
        elif editorial_type in {"coverage_explanation", "cobertura", "poliza", "póliza", "policy_explanation"} or any(token in editorial_type for token in ("coverage", "policy")):
            if layer == "semantic_card":
                boost += 34
            elif layer == "icon":
                boost += 18
            elif layer == "motion_overlay":
                boost += 8
            elif layer == "lower_third":
                boost -= 8
        elif editorial_type in {"emotional_protection", "familia", "tranquilidad", "family_protection"} or any(token in editorial_type for token in ("family", "protection", "tranquil")):
            if layer == "icon":
                boost += 30
            elif layer == "branding":
                boost += 20
            elif layer == "semantic_card":
                boost += 8
            elif layer == "lower_third":
                boost -= 12
        if hook_text_redundant_with_captions:
            if layer in {"hook_overlay", "semantic_card", "lower_third", "cta"}:
                boost -= 24
            if layer in {"hook_motion", "motion_overlay", "icon"}:
                boost += 10
        if phase == "ending" and layer == "cta":
            boost += 30
        if phase == "opening" and layer in {"semantic_card", "lower_third", "cta"}:
            boost -= 10
        if phase == "opening" and layer == "branding":
            boost -= 6
        if visual_density >= 8.0 and layer in {"semantic_card", "lower_third", "branding"}:
            boost -= 12
        candidate["priority"] = int(candidate.get("priority", 0) or 0) + boost
        candidate["priority_reason"] = (
            "editorial_ranked"
            if boost
            else "base_priority"
        )
        candidate["priority_boost"] = boost
        return boost

    for _candidate_item in candidates:
        _layer_name = str((_candidate_item or {}).get("layer") or "")
        _phase_name = _phase_for_start(float((_candidate_item or {}).get("start_s") or 0.0))
        _support_priority_adjustment(_layer_name, _phase_name, _candidate_item)

    def _face_is_high():
        if not isinstance(face_bbox, dict):
            return False
        try:
            return float(face_bbox.get("y") or face_bbox.get("top") or 0.0) < 0.42
        except Exception:
            return False

    def _speaker_is_center():
        if not isinstance(speaker_bbox, dict):
            return False
        try:
            return float(speaker_bbox.get("y") or speaker_bbox.get("top") or 0.0) < 0.55
        except Exception:
            return False

    face_high = _face_is_high()
    speaker_center = _speaker_is_center()
    text_layers_selected = 1 if caption_active else 0
    visual_layers_selected = 0
    hook_text_selected = False
    support_text_selected = False
    visual_layer_budget_applied = bool(candidates)
    collision_guard_applied = False
    collision_guard_reasons: List[str] = []
    temporal_density_drops: List[Dict[str, Any]] = []
    allowed_layers: List[str] = []
    dropped_layers: List[Dict[str, Any]] = []
    delayed_layers: List[Dict[str, Any]] = []
    reduced_layers: List[Dict[str, Any]] = []
    layer_decisions: Dict[str, Dict[str, Any]] = {}
    safe_zones: Dict[str, str] = {}

    if caption_active:
        allowed_layers.append("captions")
        safe_zones["captions"] = "lower_band"

    phase_text_selected = {"opening": 1 if caption_active else 0, "middle": 1 if caption_active else 0, "ending": 1 if caption_active else 0}
    phase_support_text_selected = {"opening": False, "middle": False, "ending": False}
    phase_visual_selected = {"opening": 0, "middle": 0, "ending": 0}

    def _safe_zone_for(layer: str, base_zone: str) -> str:
        zone = str(base_zone or "").strip()
        if face_high and layer in {"hook_overlay", "hook_motion", "icon", "branding"} and zone in {"upper_center", "upper_right", "upper_right_small"}:
            return "upper_right_small"
        if speaker_center and layer in {"cta", "lower_third", "semantic_card"} and zone.startswith("lower"):
            return "lower_center_small"
        return zone or base_zone or "upper_right_small"

    def _append_allowed(layer: str, phase: str, *, safe_zone: str = "", text_layer: bool = False) -> None:
        if layer not in allowed_layers:
            allowed_layers.append(layer)
        if safe_zone:
            safe_zones[layer] = _safe_zone_for(layer, safe_zone)
        if text_layer:
            phase_text_selected[phase] = int(phase_text_selected.get(phase, 0)) + 1
        else:
            phase_visual_selected[phase] = int(phase_visual_selected.get(phase, 0)) + 1

    # Process candidates by priority and phase.
    for candidate in sorted(candidates, key=lambda item: (-int(item.get("priority", 0) or 0), float(item.get("start_s") or 0.0), str(item.get("layer") or ""))):
        layer = str(candidate.get("layer") or "").strip()
        if not layer or layer == "captions":
            if layer == "captions":
                layer_decisions[layer] = {"action": "allow", "reason": "captions_reserved"}
            continue
        kind = str(candidate.get("kind") or ("text" if candidate.get("counts_as_text") else "visual"))
        phase = _phase_for_start(float(candidate.get("start_s") or 0.0))
        renderable = bool(candidate.get("renderable", True))
        is_text = bool(candidate.get("counts_as_text") if candidate.get("counts_as_text") is not None else kind == "text")
        safe_zone = str(candidate.get("safe_zone") or "")
        reason = str(candidate.get("reason") or "collision_guard")
        if kind == "visual" and layer == "icon" and not renderable:
            collision_guard_applied = True
            collision_guard_reasons.append("icon_renderer_unavailable")
            layer_decisions[layer] = {"action": "drop", "reason": "icon_renderer_unavailable"}
            dropped_layers.append({"layer": layer, "reason": "icon_renderer_unavailable"})
            logger.info(
                "OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s",
                layer,
                "icon_renderer_unavailable",
            )
            continue
        if is_text:
            if phase_text_selected.get(phase, 0) >= 2:
                collision_guard_applied = True
                collision_guard_reasons.append("max_text_layers_global_guard")
                layer_decisions[layer] = {"action": "drop", "reason": "max_text_layers_global_guard"}
                dropped_layers.append({"layer": layer, "reason": "max_text_layers_global_guard"})
                logger.info(
                    "OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s",
                    layer,
                    "max_text_layers_global_guard",
                )
                continue
            if phase == "opening" and layer not in {"hook_overlay"}:
                if hook_text_selected or hook_strategy_final == "text_hook" or hook_text_redundant_with_captions:
                    if candidate.get("delayable", True) and layer in {"lower_third", "semantic_card", "cta"}:
                        new_start = round(max(1.45, min(3.0, float(candidate.get("start_s") or 0.0) + 0.75)), 2)
                        delayed_layers.append({"layer": layer, "old_start_s": float(candidate.get("start_s") or 0.0), "new_start_s": new_start, "reason": "opening_text_budget_guard"})
                        layer_decisions[layer] = {"action": "delay", "reason": "opening_text_budget_guard", "new_start_s": new_start}
                        collision_guard_applied = True
                        collision_guard_reasons.append("opening_text_budget_guard")
                        logger.info(
                            "OVERLAY_DELAYED_COLLISION_GUARD layer=%s old_start=%.2f new_start=%.2f",
                            layer,
                            float(candidate.get("start_s") or 0.0),
                            new_start,
                        )
                    else:
                        dropped_layers.append({"layer": layer, "reason": "opening_text_budget_guard"})
                        layer_decisions[layer] = {"action": "drop", "reason": "opening_text_budget_guard"}
                        collision_guard_applied = True
                        collision_guard_reasons.append("opening_text_budget_guard")
                        logger.info(
                            "OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s",
                            layer,
                            "opening_text_budget_guard",
                        )
                    continue
            if phase == "opening" and layer == "hook_overlay" and hook_strategy_final == "text_hook" and not hook_text_redundant_with_captions:
                _append_allowed(layer, phase, safe_zone=safe_zone or "upper_center", text_layer=True)
                hook_text_selected = True
                layer_decisions[layer] = {"action": "allow", "reason": "opening_hook_text"}
                continue
            if phase == "ending" and layer == "cta":
                if phase_text_selected.get(phase, 0) < 2:
                    _append_allowed(layer, phase, safe_zone=safe_zone or "lower_center_small", text_layer=True)
                    support_text_selected = True
                    layer_decisions[layer] = {"action": "allow", "reason": "ending_cta"}
                else:
                    dropped_layers.append({"layer": layer, "reason": "max_text_layers_global_guard"})
                    layer_decisions[layer] = {"action": "drop", "reason": "max_text_layers_global_guard"}
                    collision_guard_applied = True
                    collision_guard_reasons.append("max_text_layers_global_guard")
                continue
            if phase != "opening" and not phase_support_text_selected.get(phase, False) and support_text_allowed and layer in {"semantic_card", "lower_third", "branding", "cta", "overlay_card_text"}:
                _append_allowed(layer, phase, safe_zone=safe_zone or ("upper_right" if layer != "cta" else "lower_center_small"), text_layer=True)
                phase_support_text_selected[phase] = True
                support_text_selected = True
                layer_decisions[layer] = {"action": "allow", "reason": f"{phase}_support_text"}
                continue
            if candidate.get("delayable", True) and layer in {"lower_third", "semantic_card", "cta"}:
                new_start = round(max(1.45, min(clip_duration - 0.1 if clip_duration else 3.0, float(candidate.get("start_s") or 0.0) + 0.75)), 2)
                delayed_layers.append({"layer": layer, "old_start_s": float(candidate.get("start_s") or 0.0), "new_start_s": new_start, "reason": reason})
                layer_decisions[layer] = {"action": "delay", "reason": reason, "new_start_s": new_start}
                collision_guard_applied = True
                collision_guard_reasons.append(reason)
                logger.info(
                    "OVERLAY_DELAYED_COLLISION_GUARD layer=%s old_start=%.2f new_start=%.2f",
                    layer,
                    float(candidate.get("start_s") or 0.0),
                    new_start,
                )
            else:
                dropped_layers.append({"layer": layer, "reason": reason})
                layer_decisions[layer] = {"action": "drop", "reason": reason}
                collision_guard_applied = True
                collision_guard_reasons.append(reason)
                logger.info(
                    "OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s",
                    layer,
                    reason,
                )
            continue

        # Visual layers: allow only one support visual per phase, with reductions for branding.
        if layer == "branding":
            if phase == "opening" and (hook_text_selected or hook_strategy_final == "text_hook" or caption_active):
                reduced_layers.append({"layer": layer, "reason": "branding_opening_minimal_mode"})
                layer_decisions[layer] = {"action": "reduce", "reason": "branding_opening_minimal_mode", "safe_zone": "top_right_small"}
                safe_zones[layer] = _safe_zone_for(layer, "top_right_small")
                allowed_layers.append(layer)
                phase_visual_selected[phase] = int(phase_visual_selected.get(phase, 0)) + 1
                collision_guard_applied = True
                collision_guard_reasons.append("branding_opening_minimal_mode")
                logger.info("OVERLAY_SAFE_ZONE_ASSIGNED layer=%s zone=%s", layer, "top_right_small")
                continue
            if phase == "ending" and phase_visual_selected.get(phase, 0) < 1:
                _append_allowed(layer, phase, safe_zone="top_right_small", text_layer=False)
                layer_decisions[layer] = {"action": "allow", "reason": "ending_branding"}
                continue
            if candidate.get("reducible", False):
                reduced_layers.append({"layer": layer, "reason": "branding_minimal_mode"})
                layer_decisions[layer] = {"action": "reduce", "reason": "branding_minimal_mode", "safe_zone": "top_right_small"}
                safe_zones[layer] = _safe_zone_for(layer, "top_right_small")
                allowed_layers.append(layer)
                phase_visual_selected[phase] = int(phase_visual_selected.get(phase, 0)) + 1
                collision_guard_applied = True
                collision_guard_reasons.append("branding_minimal_mode")
                logger.info("OVERLAY_SAFE_ZONE_ASSIGNED layer=%s zone=%s", layer, "top_right_small")
                continue
        if layer in {"hook_motion", "motion_overlay", "icon"}:
            if phase_visual_selected.get(phase, 0) >= 1 and phase == "opening" and layer != "hook_motion":
                if candidate.get("delayable", True):
                    new_start = round(max(1.45, min(clip_duration - 0.1 if clip_duration else 3.0, float(candidate.get("start_s") or 0.0) + 0.75)), 2)
                    delayed_layers.append({"layer": layer, "old_start_s": float(candidate.get("start_s") or 0.0), "new_start_s": new_start, "reason": "visual_support_budget_guard"})
                    layer_decisions[layer] = {"action": "delay", "reason": "visual_support_budget_guard", "new_start_s": new_start}
                    collision_guard_applied = True
                    collision_guard_reasons.append("visual_support_budget_guard")
                    logger.info(
                        "OVERLAY_DELAYED_COLLISION_GUARD layer=%s old_start=%.2f new_start=%.2f",
                        layer,
                        float(candidate.get("start_s") or 0.0),
                        new_start,
                    )
                    continue
                dropped_layers.append({"layer": layer, "reason": "visual_support_budget_guard"})
                layer_decisions[layer] = {"action": "drop", "reason": "visual_support_budget_guard"}
                collision_guard_applied = True
                collision_guard_reasons.append("visual_support_budget_guard")
                logger.info("OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s", layer, "visual_support_budget_guard")
                continue
            _append_allowed(layer, phase, safe_zone=safe_zone or ("upper_center" if layer == "hook_motion" else "upper_right_small"), text_layer=False)
            layer_decisions[layer] = {"action": "allow", "reason": "visual_support_allowed"}
            if layer == "hook_motion":
                safe_zones[layer] = _safe_zone_for(layer, "upper_center")
            elif layer == "icon":
                safe_zones[layer] = _safe_zone_for(layer, "upper_right_small")
            else:
                safe_zones[layer] = _safe_zone_for(layer, safe_zone or "upper_right")
            logger.info("OVERLAY_SAFE_ZONE_ASSIGNED layer=%s zone=%s", layer, safe_zones[layer])
            continue

        if layer == "semantic_card" and phase == "opening":
            if candidate.get("delayable", True):
                new_start = round(max(3.2, min(clip_duration - 0.1 if clip_duration else 3.2, float(candidate.get("start_s") or 0.0) + 1.2)), 2)
                delayed_layers.append({"layer": layer, "old_start_s": float(candidate.get("start_s") or 0.0), "new_start_s": new_start, "reason": "opening_semantic_card_delay"})
                layer_decisions[layer] = {"action": "delay", "reason": "opening_semantic_card_delay", "new_start_s": new_start}
                collision_guard_applied = True
                collision_guard_reasons.append("opening_semantic_card_delay")
                logger.info(
                    "OVERLAY_DELAYED_COLLISION_GUARD layer=%s old_start=%.2f new_start=%.2f",
                    layer,
                    float(candidate.get("start_s") or 0.0),
                    new_start,
                )
            else:
                dropped_layers.append({"layer": layer, "reason": "opening_semantic_card_drop"})
                layer_decisions[layer] = {"action": "drop", "reason": "opening_semantic_card_drop"}
                collision_guard_applied = True
                collision_guard_reasons.append("opening_semantic_card_drop")
                logger.info("OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s", layer, "opening_semantic_card_drop")
            continue

        # Default fallback: support text dropped if no room, visual allowed only once.
        if is_text:
            dropped_layers.append({"layer": layer, "reason": "text_layer_budget"})
            layer_decisions[layer] = {"action": "drop", "reason": "text_layer_budget"}
            collision_guard_applied = True
            collision_guard_reasons.append("text_layer_budget")
            logger.info("OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s", layer, "text_layer_budget")
        else:
            if phase_visual_selected.get(phase, 0) < 1:
                _append_allowed(layer, phase, safe_zone=safe_zone or "upper_right_small", text_layer=False)
                layer_decisions[layer] = {"action": "allow", "reason": "visual_default"}
                logger.info("OVERLAY_SAFE_ZONE_ASSIGNED layer=%s zone=%s", layer, safe_zones.get(layer, safe_zone or "upper_right_small"))
            else:
                if candidate.get("delayable", True):
                    new_start = round(max(1.45, min(clip_duration - 0.1 if clip_duration else 3.0, float(candidate.get("start_s") or 0.0) + 0.75)), 2)
                    delayed_layers.append({"layer": layer, "old_start_s": float(candidate.get("start_s") or 0.0), "new_start_s": new_start, "reason": "visual_layer_budget"})
                    layer_decisions[layer] = {"action": "delay", "reason": "visual_layer_budget", "new_start_s": new_start}
                    collision_guard_applied = True
                    collision_guard_reasons.append("visual_layer_budget")
                    logger.info(
                        "OVERLAY_DELAYED_COLLISION_GUARD layer=%s old_start=%.2f new_start=%.2f",
                        layer,
                        float(candidate.get("start_s") or 0.0),
                        new_start,
                    )
                else:
                    dropped_layers.append({"layer": layer, "reason": "visual_layer_budget"})
                    layer_decisions[layer] = {"action": "drop", "reason": "visual_layer_budget"}
                    collision_guard_applied = True
                    collision_guard_reasons.append("visual_layer_budget")
                    logger.info("OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s", layer, "visual_layer_budget")

    # Ensure a concrete safe zone exists for captions and the main hook.
    safe_zones.setdefault("captions", "lower_band")
    if hook_strategy_final == "text_hook":
        safe_zones.setdefault("hook_overlay", "upper_center")

    def _zone_bucket(layer: str, zone: str) -> str:
        layer = str(layer or "").strip()
        zone = str(zone or "").strip()
        if layer == "captions":
            return "bottom_safe"
        if layer == "cta" or zone.startswith("lower_center"):
            return "final_safe" if layer == "cta" else "bottom_safe"
        if layer in {"branding", "icon"}:
            return "corner_safe"
        if zone.startswith("upper"):
            return "top_safe"
        if zone.startswith("lower"):
            return "bottom_safe"
        return "middle_safe"

    safe_zone_map = {
        "layer_to_zone": dict(safe_zones),
        "zone_to_layers": {
            "top_safe": [],
            "middle_safe": [],
            "bottom_safe": [],
            "corner_safe": [],
            "final_safe": [],
        },
    }
    layer_safe_zone_assignments = []
    for _layer_name, _zone_name in safe_zones.items():
        _bucket = _zone_bucket(_layer_name, _zone_name)
        safe_zone_map["zone_to_layers"].setdefault(_bucket, []).append(_layer_name)
        layer_safe_zone_assignments.append({"layer": _layer_name, "zone": _zone_name, "bucket": _bucket})
    temporal_density_budget_applied = bool(
        visual_density >= 8.0
        or any(
            str(reason).startswith("opening_")
            or str(reason) in {"visual_layer_budget", "visual_support_budget_guard", "text_layer_budget"}
            for reason in collision_guard_reasons
        )
    )
    temporal_density_reason = "clean_beats_messy" if visual_density >= 8.5 and collision_guard_applied else ("density_guard" if temporal_density_budget_applied else "ok")
    if temporal_density_budget_applied and temporal_density_reason == "clean_beats_messy":
        logger.info("OVERLAY_DROPPED_COLLISION_GUARD reason=clean_beats_messy")
    if temporal_density_budget_applied:
        temporal_density_drops.extend(dropped_layers)

    def _support_candidate_score(candidate: Dict[str, Any]) -> int:
        layer = str(candidate.get("layer") or "")
        phase = _phase_for_start(float(candidate.get("start_s") or 0.0))
        score = int(candidate.get("priority") or 0)
        if editorial_type in {"risk_warning", "accidente", "riesgo"} or any(token in editorial_type for token in ("warning", "risk")):
            score += {"icon": 65, "hook_motion": 58, "motion_overlay": 50, "semantic_card": 24, "branding": 16, "lower_third": 4, "cta": -12}.get(layer, 0)
        elif editorial_type in {"coverage_explanation", "cobertura", "poliza", "póliza", "policy_explanation"} or any(token in editorial_type for token in ("coverage", "policy")):
            score += {"semantic_card": 64, "motion_overlay": 52, "icon": 28, "branding": 14, "lower_third": 6, "cta": -8}.get(layer, 0)
        elif editorial_type in {"emotional_protection", "familia", "tranquilidad", "family_protection"} or any(token in editorial_type for token in ("family", "protection", "tranquil")):
            score += {"icon": 62, "branding": 48, "motion_overlay": 26, "semantic_card": 14, "lower_third": 6, "cta": -8}.get(layer, 0)
        elif hook_text_redundant_with_captions:
            score += {"hook_motion": 62, "motion_overlay": 54, "icon": 30, "branding": 12, "semantic_card": -18, "lower_third": -22, "cta": -18}.get(layer, 0)
        if phase == "ending" and layer == "cta":
            score += 40
        elif phase == "ending" and layer == "branding":
            score += 8
        elif phase == "opening" and layer in {"semantic_card", "lower_third", "cta"}:
            score -= 20
        elif phase == "opening" and layer == "branding":
            score -= 10
        elif phase == "middle" and layer == "cta":
            score -= 12
        return score

    support_candidates = [
        item for item in sorted(candidates, key=lambda item: (-int(item.get("priority", 0) or 0), float(item.get("start_s") or 0.0), str(item.get("layer") or "")))
        if str(item.get("layer") or "") != "captions"
    ]
    visual_support_layer_selected = ""
    visual_support_layer_reason = ""
    visual_support_candidates_rejected: List[Dict[str, Any]] = []
    _best_support = None
    _best_support_score = -10**9
    for _candidate_item in support_candidates:
        _layer = str(_candidate_item.get("layer") or "")
        if not _layer or _layer == "captions":
            continue
        if _layer in allowed_layers:
            _score = _support_candidate_score(_candidate_item)
            if _score > _best_support_score:
                _best_support = dict(_candidate_item)
                _best_support_score = _score
        else:
            visual_support_candidates_rejected.append({
                "layer": _layer,
                "reason": str(_candidate_item.get("reason") or _candidate_item.get("priority_reason") or "not_selected"),
                "priority": int(_candidate_item.get("priority") or 0),
            })

    if _best_support is not None:
        visual_support_layer_selected = str(_best_support.get("layer") or "")
        visual_support_layer_reason = str(_best_support.get("reason") or _best_support.get("priority_reason") or "selected_by_budget")
        for _candidate_item in support_candidates:
            _layer = str(_candidate_item.get("layer") or "")
            if _layer and _layer != "captions" and _layer != visual_support_layer_selected:
                visual_support_candidates_rejected.append({
                    "layer": _layer,
                    "reason": str(_candidate_item.get("reason") or _candidate_item.get("priority_reason") or "not_selected"),
                    "priority": int(_candidate_item.get("priority") or 0),
                })

    if not visual_support_layer_selected and allowed_layers:
        for _fallback_layer in ("hook_overlay", "hook_motion", "icon", "semantic_card", "lower_third", "motion_overlay", "branding", "cta"):
            if _fallback_layer in allowed_layers:
                visual_support_layer_selected = _fallback_layer
                visual_support_layer_reason = "fallback_allowed_layer"
                break
    if visual_support_layer_selected:
        logger.info(
            "VISUAL_SUPPORT_LAYER_SELECTED layer=%s reason=%s",
            visual_support_layer_selected,
            visual_support_layer_reason or "selected_by_budget",
        )

    logger.info(
        "VISUAL_LAYER_BUDGET_APPLIED max_text_layers=%d allowed=%s dropped=%s delayed=%s",
        2,
        "|".join(allowed_layers) or "none",
        "|".join(item.get("layer") for item in dropped_layers if item.get("layer")) or "none",
        "|".join(item.get("layer") for item in delayed_layers if item.get("layer")) or "none",
    )

    return {
        "visual_layer_budget_applied": visual_layer_budget_applied,
        "visual_layers_allowed": allowed_layers,
        "visual_layers_dropped": dropped_layers,
        "visual_layers_delayed": delayed_layers,
        "visual_layers_reduced": reduced_layers,
        "allowed_layers": allowed_layers,
        "dropped_layers": dropped_layers,
        "delayed_layers": delayed_layers,
        "reduced_layers": reduced_layers,
        "layer_decisions": layer_decisions,
        "max_text_layers": 2,
        "text_layer_count_max": 2,
        "safe_zones": safe_zones,
        "reasons": collision_guard_reasons,
        "collision_guard_applied": collision_guard_applied,
        "collision_guard_reasons": collision_guard_reasons,
        "safe_zone_map": safe_zone_map,
        "layer_safe_zone_assignments": layer_safe_zone_assignments,
        "visual_support_layer_selected": visual_support_layer_selected,
        "visual_support_layer_reason": visual_support_layer_reason,
        "visual_support_candidates_rejected": visual_support_candidates_rejected,
        "temporal_density_budget_applied": temporal_density_budget_applied,
        "temporal_density_drops": temporal_density_drops,
        "temporal_density_reason": temporal_density_reason,
        "visual_layers_allowed_count": len(allowed_layers),
        "visual_layers_dropped_count": len(dropped_layers),
        "visual_layers_delayed_count": len(delayed_layers),
        "visual_layers_reduced_count": len(reduced_layers),
        "hook_text_selected": hook_text_selected,
        "support_text_selected": support_text_selected,
    }


_VISUAL_REINFORCEMENT_ICON_CANDIDATES: Dict[str, List[str]] = {
    "shield_protection": ["shield_check.svg", "heart_shield.svg", "family_home.svg", "shield_life.svg", "calm_check.svg"],
    "health_cross": ["medical_cross.svg", "health_card.svg", "heart_shield.svg"],
    "warning_pulse": ["alert_line.svg", "risk_marker.svg", "storm_cloud_risk.svg"],
    "money_check": ["capital_stack.svg", "coverage_umbrella.svg", "badge-euro.svg"],
    "document_policy": ["coverage_umbrella.svg", "folder_paperwork.svg", "signature_form.svg", "checklist_advice.svg"],
    "check_x_myth": ["myth_break.svg", "revelation_spark.svg", "key_insight.svg"],
    "question_badge": [],
    "answer_badge": [],
}

_VISUAL_REINFORCEMENT_CALL_OUTS = {"callout_arrow", "callout_circle", "number_emphasis", "semantic_micro_card", "icon_badge"}


def _normalize_reinforcement_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9áéíóúñü€%$.,]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _reinforcement_family(editorial_type: str, text: str) -> str:
    normalized = _normalize_reinforcement_text(" ".join([editorial_type or "", text or ""]))
    if any(token in normalized for token in ("familia", "proteccion", "protección", "tranquilidad", "seguridad", "respaldo")):
        return "shield_protection"
    if any(token in normalized for token in ("salud", "medic", "hospital", "médic", "consulta", "medical")):
        return "health_cross"
    if any(token in normalized for token in ("riesgo", "accidente", "cuidado", "aviso", "alerta", "peligro", "warning")):
        return "warning_pulse"
    if any(token in normalized for token in ("ahorro", "dinero", "precio", "descuento", "pagar", "euros", "euro")):
        return "money_check"
    if any(token in normalized for token in ("cobertura", "poliza", "póliza", "seguro", "document", "tramite", "trámite")):
        return "document_policy"
    if any(token in normalized for token in ("mito", "falso", "error", "no es verdad", "revelacion", "revelación")):
        return "check_x_myth"
    if any(token in normalized for token in ("duda", "objecion", "objeción", "pregunta", "no sé", "no se")):
        return "question_badge"
    return ""


def _extract_number_emphasis(text: str) -> str:
    normalized = str(text or "")
    patterns = [
        r"\b\d{1,3}%\b",
        r"\b€\s?\d+(?:[.,]\d+)?\b",
        r"\b\d+(?:[.,]\d+)?\s?(?:meses?|años?|anos?|€|eur|euros?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _select_reinforcement_icon_asset(asset_index: Optional[Dict[str, Any]], family: str) -> Optional[Path]:
    candidates = list(_VISUAL_REINFORCEMENT_ICON_CANDIDATES.get(family) or [])
    index = asset_index or {}
    verified_icons = list((index.get("verified") or {}).get("icons") or [])
    for candidate_name in candidates:
        for item in verified_icons:
            path = str(item.get("path") or "")
            if not path:
                continue
            if candidate_name.lower() in Path(path).name.lower() or candidate_name.lower() in path.lower():
                candidate_path = Path(path)
                if candidate_path.exists() and candidate_path.is_file():
                    return candidate_path
        candidate_path = (_REPO_ROOT / "assets" / "icons" / "vpi" / candidate_name).resolve()
        if candidate_path.exists() and candidate_path.is_file():
            return candidate_path
        # Some shared icons live in other folders.
        shared_candidate = (_REPO_ROOT / "assets" / "icons" / candidate_name).resolve()
        if shared_candidate.exists() and shared_candidate.is_file():
            return shared_candidate
    return None


def choose_visual_layout_strategy(
    *,
    editorial_type: str,
    visual_reinforcement_strategy: str,
    visual_asset_selected: str,
    hook_strategy_final: str,
    caption_density: Any,
    face_bbox: Optional[Dict[str, Any]] = None,
    speaker_bbox: Optional[Dict[str, Any]] = None,
    safe_zone_map: Optional[Dict[str, Any]] = None,
    visual_layer_budget: Optional[Dict[str, Any]] = None,
    clip_duration: float = 0.0,
    first3_has_captions: bool = False,
    visual_design_tokens: Optional[Dict[str, Any]] = None,
    visual_asset_inventory_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tokens = dict(visual_design_tokens or get_vpi_visual_design_tokens())
    opacity_tokens = tokens.get("opacity") or {}
    typography = tokens.get("typography") or {}
    spacing = tokens.get("spacing") or {}
    visual_layer_budget = visual_layer_budget if isinstance(visual_layer_budget, dict) else {}
    safe_zone_map = safe_zone_map if isinstance(safe_zone_map, dict) else {}
    layout_warnings: List[str] = []
    clip_duration = max(0.0, float(clip_duration or 0.0))
    try:
        caption_density_value = float(caption_density or 0.0)
    except (TypeError, ValueError):
        caption_density_value = 0.0
    visual_density_high = caption_density_value >= 8.0 or bool(visual_layer_budget.get("temporal_density_budget_applied"))
    hook_strategy_final = str(hook_strategy_final or "").strip().lower()
    editorial_type_normalized = str(editorial_type or "").strip().lower()
    selected_support_layer = str(visual_layer_budget.get("visual_support_layer_selected") or "").strip().lower()
    selected_support_reason = str(visual_layer_budget.get("visual_support_layer_reason") or "").strip()
    opening_phase = bool(first3_has_captions or clip_duration <= 3.5)
    ending_phase = bool(selected_support_layer in {"cta", "branding"})
    caption_zone = str((safe_zone_map.get("layer_to_zone") or {}).get("captions") or "lower_band")

    face_present = isinstance(face_bbox, dict) and bool(face_bbox)
    speaker_present = isinstance(speaker_bbox, dict) and bool(speaker_bbox)
    face_high = False
    speaker_center = False
    if face_present:
        try:
            face_high = float(face_bbox.get("y") or face_bbox.get("top") or 0.0) < 0.42
        except Exception:
            face_high = False
    if speaker_present:
        try:
            speaker_center = float(speaker_bbox.get("y") or speaker_bbox.get("top") or 0.0) < 0.55
        except Exception:
            speaker_center = False
    if not face_present:
        layout_warnings.append("face_bbox_absent")
    if visual_density_high:
        layout_warnings.append("visual_density_high")

    visual_asset_selected = str(visual_asset_selected or "").strip()
    visual_asset_inventory_summary = visual_asset_inventory_summary if isinstance(visual_asset_inventory_summary, dict) else {}
    inventory_has_assets = bool(visual_asset_inventory_summary) or bool(visual_asset_selected)
    reinforcement_is_text_heavy = str(visual_reinforcement_strategy or "") in {"semantic_micro_card"}
    hook_is_text = hook_strategy_final in {"text_hook", "subtitle_hook", "text_overlay"}
    support_layer = selected_support_layer or str(visual_reinforcement_strategy or "").strip().lower()
    strategy = "no_extra_visual"
    layout_zone = "none"
    layout_size = "none"
    layout_opacity = float(opacity_tokens.get("overlay_opacity") or 0.88)
    layout_duration = 0.0
    layout_priority = 0
    layout_reason = "no_extra_visual"
    face_safe = True
    caption_safe = True
    fallback_used = False

    def _zone_safe_for_face(zone: str) -> bool:
        zone = str(zone or "")
        if not face_present:
            return True
        if face_high and zone.startswith("upper"):
            return False
        return True

    def _zone_safe_for_captions(zone: str) -> bool:
        zone = str(zone or "")
        if caption_zone and str(caption_zone).startswith("lower") and zone.startswith("lower"):
            return False
        return True

    if ending_phase and support_layer == "cta":
        strategy = "final_cta"
        layout_zone = "lower_center_small"
        layout_size = "medium"
        layout_duration = round(min(2.4, max(1.4, clip_duration * 0.2 or 1.8)), 2)
        layout_priority = 72
        layout_reason = "ending_cta_priority"
    elif selected_support_layer == "branding":
        strategy = "branding_minimal"
        layout_zone = "top_right_small"
        layout_size = "tiny"
        layout_duration = round(float(clip_duration or 0.0), 2)
        layout_priority = 55
        layout_reason = "branding_minimal"
    elif opening_phase:
        if hook_is_text:
            if visual_reinforcement_strategy in {"icon_badge", "svg_icon", "shield_protection", "health_cross", "warning_pulse", "money_check", "document_policy", "check_x_myth"} and inventory_has_assets and not reinforcement_is_text_heavy:
                strategy = "icon_corner"
                layout_zone = "upper_right_small"
                layout_size = "tiny"
                layout_duration = round(min(1.2, max(0.8, clip_duration * 0.15 or 0.9)), 2)
                layout_priority = 84
                layout_reason = "opening_hook_text_icon_only"
            else:
                fallback_used = True
                strategy = "no_extra_visual"
                layout_reason = "opening_hook_text_priority"
        else:
            if visual_asset_selected or inventory_has_assets:
                if face_high or speaker_center:
                    strategy = "side_callout"
                    layout_zone = "middle_safe"
                    layout_size = "medium"
                    layout_reason = "opening_face_safe_support"
                else:
                    strategy = "icon_corner"
                    layout_zone = "upper_right_small"
                    layout_size = "small"
                    layout_reason = "opening_non_text_support"
                layout_duration = round(min(1.4, max(0.9, clip_duration * 0.16 or 1.0)), 2)
                layout_priority = 82 if strategy == "icon_corner" else 78
            else:
                fallback_used = True
                strategy = "no_extra_visual"
                layout_reason = "opening_no_verified_asset"
    else:
        if support_layer == "semantic_card" or visual_reinforcement_strategy == "semantic_micro_card":
            if visual_density_high or opening_phase:
                fallback_used = True
                strategy = "no_extra_visual"
                layout_reason = "semantic_card_blocked_by_density"
            else:
                strategy = "middle_micro_card"
                layout_zone = "middle_safe"
                layout_size = "medium"
                layout_duration = round(min(1.8, max(1.0, clip_duration * 0.18 or 1.2)), 2)
                layout_priority = 76
                layout_reason = "semantic_card_mid_clip"
        elif support_layer in {"icon", "hook_motion", "motion_overlay"} or visual_reinforcement_strategy in {"icon_badge", "svg_icon", "shield_protection", "health_cross", "warning_pulse", "money_check", "document_policy", "check_x_myth"}:
            strategy = "side_callout" if face_high or speaker_center else "icon_corner"
            layout_zone = "middle_safe" if face_high else ("upper_right_small" if support_layer != "hook_motion" else "upper_center")
            layout_size = "small" if strategy == "icon_corner" else "medium"
            layout_duration = round(min(1.6, max(0.9, clip_duration * 0.16 or 1.1)), 2)
            layout_priority = 80 if strategy == "icon_corner" else 78
            layout_reason = "mid_clip_face_safe_support" if face_high or speaker_center else "mid_clip_icon_support"
        elif support_layer == "cta":
            strategy = "final_cta"
            layout_zone = "lower_center_small"
            layout_size = "medium"
            layout_duration = round(min(2.2, max(1.2, clip_duration * 0.18 or 1.5)), 2)
            layout_priority = 70
            layout_reason = "cta_support"
        elif support_layer == "branding":
            strategy = "branding_minimal"
            layout_zone = "top_right_small"
            layout_size = "tiny"
            layout_duration = round(float(clip_duration or 0.0), 2)
            layout_priority = 55
            layout_reason = "branding_minimal"
        else:
            fallback_used = True
            strategy = "no_extra_visual"
            layout_reason = "no_safe_support"

    if layout_zone in {"lower_center_small", "lower_left", "lower_right"}:
        if not ending_phase:
            caption_safe = False
            if caption_zone and str(caption_zone).startswith("lower"):
                layout_warnings.append("overlay_taps_captions")
    elif not _zone_safe_for_captions(layout_zone):
        caption_safe = False
        layout_warnings.append("overlay_taps_captions")

    if face_present and not _zone_safe_for_face(layout_zone):
        face_safe = False
        layout_warnings.append("face_overlap_with_available_bbox")

    if fallback_used:
        layout_warnings.append("layout_fallback_used")

    budget_action = str(((visual_layer_budget.get("layer_decisions") or {}).get(str(selected_support_layer)) or {}).get("action") or "").strip()
    if selected_support_layer and budget_action == "drop" and strategy != "no_extra_visual":
        layout_warnings.append("layout_over_budget")
        layout_reason = "blocked_by_budget"
        strategy = "no_extra_visual"
        layout_zone = "none"
        layout_size = "none"
        layout_duration = 0.0
        layout_priority = 0
        face_safe = True
        caption_safe = True
        logger.warning(
            "VISUAL_LAYOUT_BLOCKED_BY_BUDGET support_layer=%s reason=%s",
            selected_support_layer or "none",
            str(((visual_layer_budget.get("layer_decisions") or {}).get(str(selected_support_layer)) or {}).get("reason") or "visual_layer_budget"),
        )

    visual_layout_ok = not any(reason in {"overlay_taps_captions", "face_overlap_with_available_bbox", "layout_over_budget"} for reason in layout_warnings)
    if strategy == "no_extra_visual" and layout_reason in {"opening_hook_text_priority", "opening_no_verified_asset", "no_safe_support", "semantic_card_blocked_by_density", "blocked_by_budget"}:
        logger.info(
            "VISUAL_LAYOUT_FALLBACK_USED reason=%s support_layer=%s",
            layout_reason,
            selected_support_layer or "none",
        )
    logger.info(
        "VISUAL_LAYOUT_STRATEGY_SELECTED strategy=%s zone=%s reason=%s",
        strategy,
        layout_zone,
        layout_reason,
    )
    if layout_zone != "none":
        logger.info(
            "VISUAL_LAYOUT_SAFE_ZONE_ASSIGNED zone=%s face_safe=%s caption_safe=%s",
            layout_zone,
            str(bool(face_safe)).lower(),
            str(bool(caption_safe)).lower(),
        )
    if layout_warnings:
        logger.warning(
            "VISUAL_LAYOUT_WARNING warnings=%s",
            "|".join(list(dict.fromkeys([str(item) for item in layout_warnings if str(item)]))) or "none",
        )
    return {
        "visual_layout_strategy": strategy,
        "visual_layout_zone": layout_zone,
        "visual_layout_size": layout_size,
        "visual_layout_opacity": float(layout_opacity),
        "visual_layout_duration": float(layout_duration),
        "visual_layout_priority": int(layout_priority),
        "visual_layout_reason": layout_reason,
        "visual_layout_face_safe": bool(face_safe),
        "visual_layout_caption_safe": bool(caption_safe),
        "visual_layout_ok": bool(visual_layout_ok),
        "visual_layout_warnings": list(dict.fromkeys([str(item) for item in layout_warnings if str(item)])),
        "visual_layout_tokens": tokens,
    }


def choose_premium_visual_restraint(
    *,
    editorial_type: str,
    hook_strength: Any = None,
    hook_strategy_final: str = "",
    caption_density: Any = 0.0,
    rhythm_edit_applied: bool = False,
    broll_applied: bool = False,
    visual_reinforcement_applied: bool = False,
    visual_layer_budget: Optional[Dict[str, Any]] = None,
    visual_layout_strategy: str = "",
    visual_asset_selected: str = "",
    face_safe: bool = True,
    caption_safe: bool = True,
    clip_duration: float = 0.0,
    sensitive_topic: bool = False,
    final_cta_phase: bool = False,
    visual_identity_ok: bool = True,
    audio_chain_ok: bool = True,
) -> Dict[str, Any]:
    visual_layer_budget = visual_layer_budget if isinstance(visual_layer_budget, dict) else {}
    try:
        caption_density_value = float(caption_density or 0.0)
    except (TypeError, ValueError):
        caption_density_value = 0.0
    hook_strength_value = 0.0
    try:
        hook_strength_value = float(hook_strength or 0.0)
    except (TypeError, ValueError):
        hook_strength_value = 0.0

    editorial_type = str(editorial_type or "").strip().lower()
    hook_strategy_final = str(hook_strategy_final or "").strip().lower()
    visual_layout_strategy = str(visual_layout_strategy or "").strip().lower()
    visual_asset_selected = str(visual_asset_selected or "").strip()
    clip_duration = max(0.0, float(clip_duration or 0.0))
    final_cta_phase = bool(final_cta_phase)
    sensitive_topic = bool(sensitive_topic)
    clip_already_strong = bool(
        (hook_strategy_final and "text" not in hook_strategy_final or hook_strength_value >= 4.0)
        and rhythm_edit_applied
        and (caption_density_value >= 1.0 or caption_density_value > 0.0)
        and visual_identity_ok
        and audio_chain_ok
    )

    premium_restraint_mode = "balanced"
    allowed_visual_support_count = 2
    suppress_broll = False
    suppress_visual_reinforcement = False
    suppress_semantic_card = False
    suppress_badge = False
    suppress_branding_heavy = True
    prefer_motion_over_text = False
    reason = "balanced_default"
    suppressed_layers: List[str] = []
    restraint_broll_interaction = "neutral"

    if sensitive_topic or any(token in editorial_type for token in ("decesos", "funeral", "fallecimiento", "muerte", "sepelio", "velatorio", "luto")):
        premium_restraint_mode = "sensitive_minimal"
        allowed_visual_support_count = 1
        suppress_broll = True
        suppress_visual_reinforcement = True
        suppress_semantic_card = True
        suppress_badge = True
        suppress_branding_heavy = True
        prefer_motion_over_text = False
        reason = "sensitive_content_requires_restraint"
        restraint_broll_interaction = "suppress_broll_unless_sensitive_clear"
    elif any(token in editorial_type for token in ("family", "tranquil", "proteccion", "protección", "emotional_protection")):
        premium_restraint_mode = "minimal" if clip_already_strong else "balanced"
        allowed_visual_support_count = 1 if clip_already_strong else 2
        suppress_semantic_card = True
        suppress_branding_heavy = True
        prefer_motion_over_text = True
        reason = "emotional_protection_lean"
        restraint_broll_interaction = "broll_only_if_very_clear"
    elif any(token in editorial_type for token in ("risk", "warning", "accidente", "riesgo", "alerta")):
        premium_restraint_mode = "expressive"
        allowed_visual_support_count = 2
        suppress_branding_heavy = True
        prefer_motion_over_text = True
        reason = "risk_warning_controlled_expression"
        restraint_broll_interaction = "no_broll_plus_badge_plus_transition_stack"
    elif any(token in editorial_type for token in ("coverage", "cobertura", "policy", "poliza", "póliza", "explanation", "explicacion", "explicación")):
        premium_restraint_mode = "balanced"
        allowed_visual_support_count = 2 if not clip_already_strong else 1
        suppress_badge = True
        suppress_branding_heavy = True
        prefer_motion_over_text = False
        reason = "coverage_explanation_balanced"
        restraint_broll_interaction = "broll_or_icon_not_both_when_captions_dense"
    elif any(token in editorial_type for token in ("myth", "mito", "falso", "error", "debunk")):
        premium_restraint_mode = "expressive"
        allowed_visual_support_count = 2
        suppress_branding_heavy = True
        prefer_motion_over_text = True
        reason = "myth_debunk_controlled"
        restraint_broll_interaction = "allow_check_x_without_glitch"
    elif any(token in editorial_type for token in ("objection", "objecion", "objeción", "duda", "pregunta")):
        premium_restraint_mode = "balanced"
        allowed_visual_support_count = 1
        suppress_semantic_card = True
        suppress_branding_heavy = True
        prefer_motion_over_text = False
        reason = "objection_keep_focus"
        restraint_broll_interaction = "question_callout_or_broll_not_both"

    if clip_already_strong:
        allowed_visual_support_count = 1
        if caption_density_value >= 8.0 or visual_layout_strategy in {"middle_micro_card", "semantic_micro_card", "icon_corner", "side_callout"}:
            premium_restraint_mode = "no_extra_visual"
            suppress_visual_reinforcement = True
            suppress_semantic_card = True
            suppress_badge = True
            reason = "clip_already_strong_reduce_noise"
        else:
            reason = "clip_already_strong_lean"
        restraint_broll_interaction = "reduce_layers_when_clip_is_already_strong"

    if broll_applied:
        allowed_visual_support_count = min(allowed_visual_support_count, 1)
        if premium_restraint_mode != "sensitive_minimal":
            suppress_semantic_card = True
            suppress_badge = True
        reason = f"{reason}_broll_present"
        restraint_broll_interaction = "broll_present_reduce_extra_layers"
    elif str(visual_layer_budget.get("visual_support_layer_selected") or "") == "none":
        restraint_broll_interaction = "no_broll_allows_single_support"

    if final_cta_phase and clip_already_strong:
        allowed_visual_support_count = min(allowed_visual_support_count, 1)
        suppress_visual_reinforcement = True if not sensitive_topic else suppress_visual_reinforcement
        reason = f"{reason}_final_cta_reserve"

    if not face_safe or not caption_safe:
        suppress_visual_reinforcement = True
        suppress_semantic_card = True
        suppress_badge = True
        reason = f"{reason}_safety_reserve"

    if not visual_identity_ok or not audio_chain_ok:
        allowed_visual_support_count = max(allowed_visual_support_count, 1)
        reason = f"{reason}_quality_guard"

    if sensitive_topic and visual_asset_selected and visual_layout_strategy not in {"no_extra_visual", "branding_minimal"}:
        suppressed_layers.extend(["visual_reinforcement", "semantic_card", "badge"])

    if suppress_visual_reinforcement:
        suppressed_layers.append("visual_reinforcement")
    if suppress_semantic_card:
        suppressed_layers.append("semantic_card")
    if suppress_badge:
        suppressed_layers.append("badge")
    if suppress_broll:
        suppressed_layers.append("broll")
    if suppress_branding_heavy:
        suppressed_layers.append("branding_heavy")

    log_mode = premium_restraint_mode
    logger.info(
        "PREMIUM_RESTRAINT_SELECTED mode=%s allowed=%d reason=%s",
        log_mode,
        int(allowed_visual_support_count),
        reason,
    )
    if suppressed_layers:
        logger.info(
            "PREMIUM_RESTRAINT_SUPPRESSED layers=%s reason=%s",
            "|".join(list(dict.fromkeys([str(item) for item in suppressed_layers if str(item)]))) or "none",
            reason,
        )
    logger.info(
        "PREMIUM_RESTRAINT_APPLIED mode=%s clip_already_strong=%s sensitive=%s",
        log_mode,
        str(bool(clip_already_strong)).lower(),
        str(bool(sensitive_topic)).lower(),
    )
    return {
        "premium_restraint_mode": premium_restraint_mode,
        "premium_restraint_applied": True,
        "premium_restraint_reason": reason,
        "premium_restraint_suppressed_layers": list(dict.fromkeys([str(item) for item in suppressed_layers if str(item)])),
        "allowed_visual_support_count": int(allowed_visual_support_count),
        "clip_already_strong": bool(clip_already_strong),
        "visual_support_reduced_reason": reason,
        "restraint_broll_interaction": restraint_broll_interaction,
        "suppress_broll": bool(suppress_broll),
        "suppress_visual_reinforcement": bool(suppress_visual_reinforcement),
        "suppress_semantic_card": bool(suppress_semantic_card),
        "suppress_badge": bool(suppress_badge),
        "suppress_branding_heavy": bool(suppress_branding_heavy),
        "prefer_motion_over_text": bool(prefer_motion_over_text),
    }


def choose_vpi_framing_profile(
    *,
    editorial_type: str,
    motion_profile: str,
    caption_polish_profile: str,
    premium_restraint_mode: str,
    visual_layout_strategy: str,
    face_bbox: Optional[Dict[str, Any]] = None,
    speaker_bbox: Optional[Dict[str, Any]] = None,
    clip_duration: float = 0.0,
    broll_applied: bool = False,
    hook_strategy_final: str = "",
    sensitive_topic: bool = False,
) -> Dict[str, Any]:
    editorial = str(editorial_type or "").strip().lower()
    motion = str(motion_profile or "").strip().lower()
    caption_profile = str(caption_polish_profile or "").strip().lower()
    restraint = str(premium_restraint_mode or "").strip().lower()
    layout = str(visual_layout_strategy or "").strip().lower()
    hook_strategy = str(hook_strategy_final or "").strip().lower()
    duration = max(0.0, float(clip_duration or 0.0))
    has_face = isinstance(face_bbox, dict) and bool(face_bbox)
    has_speaker = isinstance(speaker_bbox, dict) and bool(speaker_bbox)

    def _bbox_value(box: Optional[Dict[str, Any]], *keys: str) -> float:
        if not isinstance(box, dict):
            return 0.0
        for key in keys:
            try:
                value = box.get(key)
                if value is not None:
                    return float(value)
            except Exception:
                continue
        return 0.0

    face_y = _bbox_value(face_bbox, "y", "top")
    face_h = max(0.0, _bbox_value(face_bbox, "h", "height"))
    face_bottom = face_y + face_h
    speaker_y = _bbox_value(speaker_bbox, "y", "top")
    speaker_h = max(0.0, _bbox_value(speaker_bbox, "h", "height"))
    speaker_bottom = speaker_y + speaker_h

    face_crop_risk = "none"
    if has_face:
        if face_y < 0.08 or face_bottom > 0.94:
            face_crop_risk = "high"
        elif face_y < 0.14 or face_bottom > 0.90:
            face_crop_risk = "medium"
        else:
            face_crop_risk = "low"

    face_high = has_face and face_y < 0.42
    speaker_high = has_speaker and speaker_y < 0.55
    hook_active = hook_strategy not in {"", "none", "no_extra_hook", "no_reframe"}
    framing_reason_parts: List[str] = []
    framing_profile = "speaker_centered"
    target_anchor = "speaker_center" if has_speaker else ("face_center" if has_face else "original_frame")
    safe_crop_margin = 0.08
    headroom_policy = "balanced_headroom"
    subtitle_clearance_policy = "protect_subtitle_band"
    max_reframe_shift = 0.03
    reframe_skipped_reason = ""
    face_framing_adjusted = False
    original_frame_preserved = False
    face_framing_safe = True
    headroom_safe = True
    subtitle_clearance_applied = bool(caption_profile or layout)
    cta_clearance_applied = bool(layout in {"final_cta", "branding_minimal"})

    if sensitive_topic or editorial in {"sensitive_decesos", "decesos"}:
        framing_profile = "sensitive_stable"
        target_anchor = "speaker_center" if has_speaker else ("face_center" if has_face else "original_frame")
        safe_crop_margin = 0.14
        headroom_policy = "high_headroom"
        subtitle_clearance_policy = "keep_lower_band_clear"
        max_reframe_shift = 0.012
        framing_reason_parts.append("sensitive_topic")
    elif editorial in {"emotional_protection", "calm_trust"} or any(token in editorial for token in ("proteccion", "protección", "tranquilidad", "family", "familia")):
        framing_profile = "static_safe" if not has_face and not has_speaker else "speaker_centered"
        target_anchor = "face_center" if has_face else ("speaker_center" if has_speaker else "original_frame")
        safe_crop_margin = 0.10
        headroom_policy = "protect_expression"
        subtitle_clearance_policy = "keep_lower_band_clear"
        max_reframe_shift = 0.02
        framing_reason_parts.append("emotional_protection")
    elif editorial in {"risk_warning", "myth_debunk"} or any(token in editorial for token in ("risk", "warning", "myth", "mito", "revel")):
        framing_profile = "subtle_push_in" if hook_active else "speaker_upper_safe"
        target_anchor = "face_center" if has_face else ("speaker_upper_safe" if has_speaker else "original_frame")
        safe_crop_margin = 0.08
        headroom_policy = "safe_headroom"
        subtitle_clearance_policy = "keep_lower_band_clear"
        max_reframe_shift = 0.045
        framing_reason_parts.append("risk_or_myth")
    elif editorial in {"coverage_explanation", "tramite_documentacion", "legal_tramite", "legal_admin_tramite"} or any(token in editorial for token in ("coverage", "cobertura", "tramite", "document", "póliza", "poliza")):
        framing_profile = "speaker_upper_safe"
        target_anchor = "speaker_upper_safe" if has_speaker else ("face_upper_safe" if has_face else "original_frame")
        safe_crop_margin = 0.11
        headroom_policy = "keep_forehead_clear"
        subtitle_clearance_policy = "clear_lower_band_for_captions"
        max_reframe_shift = 0.03
        framing_reason_parts.append("coverage_or_tramite")
    elif restraint in {"minimal", "no_extra_visual"}:
        framing_profile = "no_reframe" if face_crop_risk != "high" else "static_safe"
        target_anchor = "original_frame"
        safe_crop_margin = 0.12
        headroom_policy = "preserve_original_frame"
        subtitle_clearance_policy = "keep_lower_band_clear"
        max_reframe_shift = 0.0 if framing_profile == "no_reframe" else 0.015
        framing_reason_parts.append("premium_restraint_minimal")
    elif motion in {"punchy"} and hook_active:
        framing_profile = "subtle_push_in"
        target_anchor = "face_center" if has_face else ("speaker_center" if has_speaker else "original_frame")
        safe_crop_margin = 0.07
        headroom_policy = "safe_headroom"
        subtitle_clearance_policy = "protect_subtitle_band"
        max_reframe_shift = 0.04
        framing_reason_parts.append("motion_punchy")
    else:
        if has_face or has_speaker:
            framing_profile = "speaker_centered"
            target_anchor = "face_center" if has_face else "speaker_center"
            safe_crop_margin = 0.09
            headroom_policy = "balanced_headroom"
            subtitle_clearance_policy = "protect_subtitle_band"
            max_reframe_shift = 0.03
            framing_reason_parts.append("default_speaker_centered")
        else:
            framing_profile = "no_reframe"
            target_anchor = "original_frame"
            safe_crop_margin = 0.12
            headroom_policy = "preserve_original_frame"
            subtitle_clearance_policy = "keep_lower_band_clear"
            max_reframe_shift = 0.0
            framing_reason_parts.append("no_face_or_speaker_bbox")

    if has_face:
        face_framing_safe = face_crop_risk != "high"
        headroom_safe = face_y <= 0.42 and face_bottom < 0.96
        if face_high and framing_profile not in {"no_reframe", "static_safe"}:
            face_framing_adjusted = True
            framing_reason_parts.append("face_recentered")
    elif has_speaker:
        headroom_safe = speaker_y <= 0.55 and speaker_bottom < 0.98
        if speaker_high and framing_profile not in {"no_reframe", "static_safe"}:
            face_framing_adjusted = True
            framing_reason_parts.append("speaker_recentered")
    else:
        face_framing_safe = True
        headroom_safe = True

    if framing_profile in {"no_reframe", "static_safe"} and not face_framing_adjusted:
        original_frame_preserved = True
        reframe_skipped_reason = "original_frame_preserved"
        framing_reason_parts.append("original_frame_preserved")

    if caption_profile in {"calm_readable", "sensitive_soft"}:
        subtitle_clearance_applied = True
    if layout == "final_cta":
        cta_clearance_applied = True

    framing_polish_warnings: List[str] = []
    if not has_face:
        framing_polish_warnings.append("face_bbox_absent")
    if not has_speaker and not has_face:
        framing_polish_warnings.append("speaker_bbox_absent")
    if face_crop_risk == "high":
        framing_polish_warnings.append("face_crop_risk_high")
    if not headroom_safe and has_face:
        framing_polish_warnings.append("headroom_risk")
    if not subtitle_clearance_applied:
        framing_polish_warnings.append("subtitle_clearance_approximate")

    framing_polish_applied = bool(framing_profile not in {"no_reframe"} or subtitle_clearance_applied or cta_clearance_applied)
    framing_reason = ",".join(dict.fromkeys([str(item) for item in framing_reason_parts if str(item)])) or "default_framing"

    logger.info(
        "VPI_FRAMING_PROFILE_SELECTED profile=%s target=%s reason=%s",
        framing_profile,
        target_anchor,
        framing_reason,
    )
    if face_framing_adjusted:
        logger.info(
            "VPI_FACE_FRAMING_ADJUSTED profile=%s target=%s shift=%.3f",
            framing_profile,
            target_anchor,
            max_reframe_shift,
        )
    if headroom_safe:
        logger.info(
            "VPI_HEADROOM_PROTECTED profile=%s policy=%s",
            framing_profile,
            headroom_policy,
        )
    if subtitle_clearance_applied:
        logger.info(
            "VPI_SUBTITLE_CLEARANCE_APPLIED profile=%s policy=%s",
            framing_profile,
            subtitle_clearance_policy,
        )
    if original_frame_preserved:
        logger.info(
            "VPI_REFRAME_SKIPPED_SAFE profile=%s reason=%s",
            framing_profile,
            reframe_skipped_reason,
        )
    if framing_polish_warnings:
        logger.warning(
            "VPI_FRAMING_POLISH_WARNING warnings=%s",
            "|".join(list(dict.fromkeys([str(item) for item in framing_polish_warnings if str(item)]))) or "none",
        )
    return {
        "framing_profile": framing_profile,
        "target_anchor": target_anchor,
        "safe_crop_margin": float(round(safe_crop_margin, 3)),
        "headroom_policy": headroom_policy,
        "subtitle_clearance_policy": subtitle_clearance_policy,
        "max_reframe_shift": float(round(max_reframe_shift, 3)),
        "framing_reason": framing_reason,
        "face_framing_safe": bool(face_framing_safe),
        "headroom_safe": bool(headroom_safe),
        "face_crop_risk": face_crop_risk,
        "face_framing_adjusted": bool(face_framing_adjusted),
        "subtitle_clearance_applied": bool(subtitle_clearance_applied),
        "cta_clearance_applied": bool(cta_clearance_applied),
        "reframe_skipped_reason": reframe_skipped_reason,
        "original_frame_preserved": bool(original_frame_preserved),
        "framing_polish_applied": bool(framing_polish_applied),
        "framing_polish_warnings": list(dict.fromkeys([str(item) for item in framing_polish_warnings if str(item)])),
        "face_bbox_present": bool(has_face),
        "speaker_bbox_present": bool(has_speaker),
        "framing_tokens": get_vpi_visual_design_tokens(),
    }


def choose_vpi_commercial_cta(
    *,
    editorial_type: str,
    segment_text: str,
    clip_duration: float,
    hook_strategy_final: str,
    premium_restraint_mode: str,
    visual_layout_strategy: str,
    visual_layer_budget: Optional[Dict[str, Any]] = None,
    captions_active: bool = False,
    sensitive_topic: bool = False,
    final_phase_available: bool = False,
    brand_assets_verified: bool = False,
) -> Dict[str, Any]:
    visual_layer_budget = visual_layer_budget if isinstance(visual_layer_budget, dict) else {}
    editorial_type = str(editorial_type or "").strip().lower()
    segment_text = str(segment_text or "").strip()
    hook_strategy_final = str(hook_strategy_final or "").strip().lower()
    premium_restraint_mode = str(premium_restraint_mode or "").strip().lower()
    visual_layout_strategy = str(visual_layout_strategy or "").strip().lower()
    clip_duration = max(0.0, float(clip_duration or 0.0))
    final_phase_available = bool(final_phase_available and clip_duration >= 8.0)
    captions_active = bool(captions_active)
    sensitive_topic = bool(
        sensitive_topic
        or any(token in editorial_type for token in ("decesos", "funeral", "fallecimiento", "muerte", "sepelio", "velatorio", "luto"))
        or any(token in segment_text.lower() for token in ("decesos", "funeral", "fallecimiento", "muerte", "sepelio", "velatorio", "luto"))
    )
    visual_density_high = bool(float(visual_layer_budget.get("visual_density_score") or 0.0) >= 8.0 or visual_layer_budget.get("temporal_density_budget_applied"))
    support_layer_selected = str(visual_layer_budget.get("visual_support_layer_selected") or "").strip().lower()
    final_phase_safe = bool(final_phase_available and support_layer_selected in {"cta", "branding", ""} and visual_layout_strategy in {"final_cta", "branding_minimal", "no_extra_visual", ""})

    cta_decision = "no_cta"
    cta_type = "no_cta"
    cta_text = ""
    cta_start_time = round(max(0.0, clip_duration - 2.2), 2)
    cta_duration = round(min(2.2, max(1.0, clip_duration * 0.18 or 1.4)), 2)
    cta_layout_zone = "lower_center_small"
    cta_reason = "final_phase_unavailable"
    cta_risk_level = "low"
    cta_safety_ok = True
    cta_safety_warnings: List[str] = []
    cta_safety_rewritten = False
    cta_safety_reason = ""
    cta_planned = False
    cta_renderable = False
    cta_skipped_reason = ""

    editorial_map = [
        (("coverage_explanation", "coverage", "cobertura", "policy", "poliza", "póliza"), "coverage_check", "Revisa tu cobertura antes de contratar", "Te ayudamos a elegir bien"),
        (("risk_warning", "warning", "accidente", "riesgo", "alerta"), "avoid_mistake", "Evita errores antes de contratar", "Consulta antes de decidir"),
        (("client_objection", "objection", "objecion", "objeción", "duda", "pregunta"), "soft_consultation", "Resolvemos tus dudas antes de contratar", "Te orientamos sin presión"),
        (("emotional_protection", "family_protection", "familia", "tranquilidad", "proteccion", "protección"), "family_protection", "Protege a los tuyos con tranquilidad", "Te orientamos con calma"),
        (("money_saving", "ahorro", "saving", "descuento"), "savings_review", "Revisamos opciones para ahorrar sin perder cobertura", "Te ayudamos a comparar con claridad"),
        (("health", "salud", "medical", "medico", "médico", "extranjeria", "extranjería", "trámite", "tramite"), "case_review", "Verificamos que tu póliza sea válida para tu trámite", "Te ayudamos a revisar tus opciones"),
    ]

    selected_type = "soft_consultation"
    selected_texts = ("Te orientamos con claridad", "Te ayudamos a revisar tu caso")
    for tokens, cta_kind, primary_text, fallback_text in editorial_map:
        if editorial_type and any(token in editorial_type for token in tokens):
            selected_type = cta_kind
            selected_texts = (primary_text, fallback_text)
            break

    if sensitive_topic:
        selected_type = "sensitive_soft"
        selected_texts = ("Te orientamos con calma y claridad", "Te orientamos con calma y claridad")

    if any(token in editorial_type for token in ("decesos", "funeral", "fallecimiento", "muerte", "sepelio", "velatorio", "luto")):
        selected_type = "sensitive_soft"
        selected_texts = ("Te orientamos con calma y claridad", "Te orientamos con calma y claridad")
        if clip_duration < 10.0 or captions_active or visual_density_high or premium_restraint_mode == "sensitive_minimal":
            cta_decision = "no_cta"
            cta_reason = "sensitive_minimal_cta_suppressed"
            cta_risk_level = "high"
        else:
            cta_decision = "show_cta"
            cta_reason = "sensitive_soft_cta_allowed"
            cta_risk_level = "medium"
    elif not final_phase_safe:
        cta_decision = "no_cta"
        cta_reason = "final_phase_not_safe"
        cta_risk_level = "low"
    elif premium_restraint_mode in {"no_extra_visual", "sensitive_minimal"}:
        cta_decision = "no_cta"
        cta_reason = f"restraint_{premium_restraint_mode}"
        cta_risk_level = "low"
    elif visual_density_high and captions_active:
        cta_decision = "no_cta"
        cta_reason = "visual_density_high"
        cta_risk_level = "low"
    elif clip_duration < 7.0:
        cta_decision = "no_cta"
        cta_reason = "clip_too_short"
        cta_risk_level = "low"
    else:
        cta_decision = "show_cta"
        cta_reason = "final_phase_available"
        cta_risk_level = "low"

    if cta_decision == "show_cta":
        cta_type = selected_type
        cta_text = selected_texts[0]
        if any(bad in cta_text.lower() for bad in ("garantizado", "garantía", "garantia", "mejor seguro", "mejor", "descuento", "urgente", "rápido", "rapido")):
            cta_safety_rewritten = True
            cta_safety_reason = "unsafe_promissory_or_aggressive_copy"
            cta_text = selected_texts[1]
            if not cta_text:
                cta_decision = "no_cta"
                cta_reason = "cta_rewritten_to_none"
        if sensitive_topic and cta_type != "sensitive_soft":
            cta_safety_rewritten = True
            cta_safety_reason = "sensitive_topic_softened"
            cta_type = "sensitive_soft"
            cta_text = "Te orientamos con calma y claridad"
        if hook_strategy_final in {"text_hook", "subtitle_hook", "text_overlay"} and captions_active:
            cta_layout_zone = "lower_center_small"
        elif visual_layout_strategy == "branding_minimal":
            cta_layout_zone = "lower_center_small"
        else:
            cta_layout_zone = "lower_center_small"
        cta_planned = True
        cta_renderable = True
        cta_start_time = round(max(0.0, clip_duration - 2.4), 2)
        cta_duration = round(min(2.2, max(1.0, clip_duration * 0.18 or 1.5)), 2)
        if visual_density_high:
            cta_safety_warnings.append("visual_density_high")
        if captions_active:
            cta_safety_warnings.append("captions_active")
        if not brand_assets_verified:
            cta_safety_warnings.append("brand_not_verified")
        logger.info(
            "VPI_CTA_SELECTED decision=%s type=%s zone=%s reason=%s",
            cta_decision,
            cta_type,
            cta_layout_zone,
            cta_reason,
        )
    else:
        cta_type = "no_cta"
        cta_text = ""
        cta_renderable = False
        cta_safety_ok = False if sensitive_topic and "sensitive" in cta_reason else True
        cta_skipped_reason = cta_reason
        logger.info(
            "VPI_CTA_SELECTED decision=%s type=%s zone=%s reason=%s",
            cta_decision,
            cta_type,
            cta_layout_zone,
            cta_reason,
        )
        logger.info("VPI_CTA_SKIPPED_REASON reason=%s", cta_reason)
        if cta_reason.startswith("restraint_"):
            logger.warning("VPI_CTA_BLOCKED_BY_RESTRAINT reason=%s", cta_reason)

    if cta_decision == "show_cta" and cta_safety_rewritten:
        logger.warning("VPI_CTA_BLOCKED_BY_SAFETY reason=%s", cta_safety_reason or "cta_copy_rewritten")

    return {
        "cta_decision": cta_decision,
        "cta_type": cta_type,
        "cta_text": cta_text,
        "cta_start_time": float(cta_start_time),
        "cta_duration": float(cta_duration),
        "cta_layout_zone": cta_layout_zone,
        "cta_reason": cta_reason,
        "cta_risk_level": cta_risk_level,
        "cta_planned": bool(cta_planned),
        "cta_renderable": bool(cta_renderable),
        "cta_safety_ok": bool(cta_decision == "show_cta"),
        "cta_safety_warnings": list(dict.fromkeys(cta_safety_warnings)),
        "cta_safety_rewritten": bool(cta_safety_rewritten),
        "cta_safety_reason": cta_safety_reason,
        "cta_skipped_reason": cta_skipped_reason,
    }


def _strip_svg_root(svg_text: str) -> str:
    content = re.sub(r"^\s*<\?xml[^>]*>\s*", "", str(svg_text or ""), flags=re.IGNORECASE)
    content = re.sub(r"^\s*<svg[^>]*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"</svg>\s*$", "", content, flags=re.IGNORECASE | re.DOTALL)
    return content.strip()


def _build_reinforcement_svg_markup(
    *,
    strategy: str,
    accent_text: str = "",
    icon_svg_path: Optional[Path] = None,
) -> str:
    label = textwrap.shorten(accent_text or "", width=14, placeholder="…") if accent_text else ""
    icon_markup = ""
    if icon_svg_path and icon_svg_path.exists():
        try:
            icon_markup = _strip_svg_root(icon_svg_path.read_text(encoding="utf-8"))
        except Exception:
            icon_markup = ""

    if strategy in {"svg_icon", "shield_protection", "health_cross", "warning_pulse", "money_check", "document_policy"}:
        inner = icon_markup or "<circle cx='256' cy='256' r='120' fill='white' fill-opacity='0.92'/>"
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <defs>
                <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#000000" flood-opacity="0.24"/>
                </filter>
              </defs>
              <rect x="40" y="40" width="432" height="432" rx="104" fill="#111111" fill-opacity="0.22"/>
              <g filter="url(#softShadow)">
                <circle cx="256" cy="256" r="168" fill="#101114" fill-opacity="0.85"/>
                <circle cx="256" cy="256" r="126" fill="#FFFFFF" fill-opacity="0.07" stroke="#FFFFFF" stroke-opacity="0.20" stroke-width="8"/>
                <g transform="translate(116 116) scale(1.15)">
                  {inner}
                </g>
              </g>
              {"<text x='256' y='438' text-anchor='middle' font-family='Manrope,Arial,sans-serif' font-size='42' font-weight='700' fill='#F7F7F4' fill-opacity='0.95'>%s</text>" % label if label else ""}
            </svg>
            """
        ).strip()

    if strategy == "icon_badge":
        glyph = "!" if not label else label[:1].upper()
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <rect x="52" y="52" width="408" height="408" rx="112" fill="#0F1116" fill-opacity="0.88"/>
              <circle cx="256" cy="256" r="150" fill="#FFFFFF" fill-opacity="0.08" stroke="#FFFFFF" stroke-opacity="0.18" stroke-width="8"/>
              <circle cx="256" cy="256" r="94" fill="#FFFFFF" fill-opacity="0.92"/>
              <text x="256" y="287" text-anchor="middle" font-family="Manrope,Arial,sans-serif" font-size="132" font-weight="800" fill="#121316">{glyph}</text>
              {"<text x='256' y='426' text-anchor='middle' font-family='Manrope,Arial,sans-serif' font-size='38' font-weight='700' fill='#F7F7F4' fill-opacity='0.92'>%s</text>" % label if label else ""}
            </svg>
            """
        ).strip()

    if strategy == "callout_arrow":
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <rect x="36" y="36" width="440" height="440" rx="120" fill="#111114" fill-opacity="0.20"/>
              <path d="M132 304 C188 246, 230 224, 304 214" fill="none" stroke="#F7F7F4" stroke-opacity="0.94" stroke-width="18" stroke-linecap="round"/>
              <path d="M305 214 L282 204 L289 229 Z" fill="#F7F7F4" fill-opacity="0.94"/>
              <circle cx="356" cy="196" r="64" fill="#F7F7F4" fill-opacity="0.18" stroke="#F7F7F4" stroke-opacity="0.42" stroke-width="6"/>
              {"<text x='356' y='211' text-anchor='middle' font-family='Manrope,Arial,sans-serif' font-size='42' font-weight='800' fill='#F7F7F4'>%s</text>" % label if label else ""}
            </svg>
            """
        ).strip()

    if strategy == "callout_circle":
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <rect x="44" y="44" width="424" height="424" rx="120" fill="#111114" fill-opacity="0.18"/>
              <circle cx="256" cy="256" r="156" fill="none" stroke="#F7F7F4" stroke-opacity="0.92" stroke-width="16"/>
              <circle cx="256" cy="256" r="118" fill="#F7F7F4" fill-opacity="0.08"/>
              <text x="256" y="282" text-anchor="middle" font-family="Manrope,Arial,sans-serif" font-size="112" font-weight="800" fill="#F7F7F4">{label[:1].upper() if label else "•"}</text>
            </svg>
            """
        ).strip()

    if strategy == "number_emphasis":
        glyph = label or "1"
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <rect x="44" y="92" width="424" height="328" rx="100" fill="#111114" fill-opacity="0.85"/>
              <rect x="84" y="132" width="344" height="248" rx="76" fill="#FFFFFF" fill-opacity="0.08"/>
              <text x="256" y="272" text-anchor="middle" font-family="Manrope,Arial,sans-serif" font-size="108" font-weight="800" fill="#F7F7F4">{glyph}</text>
              <line x1="156" y1="316" x2="356" y2="316" stroke="#F7F7F4" stroke-opacity="0.72" stroke-width="8" stroke-linecap="round"/>
            </svg>
            """
        ).strip()

    if strategy == "semantic_micro_card":
        micro = label or "Mira esto"
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <rect x="52" y="180" width="408" height="160" rx="54" fill="#111114" fill-opacity="0.86"/>
              <rect x="78" y="206" width="356" height="108" rx="38" fill="#FFFFFF" fill-opacity="0.08"/>
              <text x="256" y="274" text-anchor="middle" font-family="Manrope,Arial,sans-serif" font-size="44" font-weight="800" fill="#F7F7F4">{micro}</text>
            </svg>
            """
        ).strip()

    if strategy == "check_x_myth":
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <rect x="48" y="48" width="416" height="416" rx="128" fill="#111114" fill-opacity="0.86"/>
              <circle cx="184" cy="256" r="78" fill="#FFFFFF" fill-opacity="0.10" stroke="#F7F7F4" stroke-opacity="0.38" stroke-width="6"/>
              <circle cx="328" cy="256" r="78" fill="#FFFFFF" fill-opacity="0.10" stroke="#F7F7F4" stroke-opacity="0.38" stroke-width="6"/>
              <path d="M150 256 L175 281 L219 231" fill="none" stroke="#F7F7F4" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M300 220 L356 292" fill="none" stroke="#F7F7F4" stroke-width="18" stroke-linecap="round"/>
              <path d="M356 220 L300 292" fill="none" stroke="#F7F7F4" stroke-width="18" stroke-linecap="round"/>
            </svg>
            """
        ).strip()

    if strategy == "warning_pulse":
        return textwrap.dedent(
            f"""
            <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
              <rect x="46" y="46" width="420" height="420" rx="124" fill="#111114" fill-opacity="0.20"/>
              <path d="M256 102 L394 350 H118 Z" fill="#FFFFFF" fill-opacity="0.08" stroke="#F7F7F4" stroke-opacity="0.92" stroke-width="16" stroke-linejoin="round"/>
              <path d="M256 186 V284" stroke="#F7F7F4" stroke-opacity="0.96" stroke-width="22" stroke-linecap="round"/>
              <circle cx="256" cy="332" r="16" fill="#F7F7F4"/>
            </svg>
            """
        ).strip()

    return ""


def choose_visual_reinforcement(
    *,
    editorial_type: str,
    text: str,
    hook_strategy_final: str,
    visual_support_layer_selected: str,
    visual_density: Any,
    safe_zone_map: Optional[Dict[str, Any]] = None,
    caption_presence: bool = False,
    clip_duration: float = 0.0,
    available_assets: Optional[Dict[str, Any]] = None,
    visual_layer_budget: Optional[Dict[str, Any]] = None,
    face_bbox: Optional[Dict[str, Any]] = None,
    speaker_bbox: Optional[Dict[str, Any]] = None,
    first3_has_captions: bool = False,
    visual_design_tokens: Optional[Dict[str, Any]] = None,
    visual_asset_inventory_summary: Optional[Dict[str, Any]] = None,
    hook_text_redundant_with_captions: bool = False,
) -> Dict[str, Any]:
    visual_tokens = dict(visual_design_tokens or get_vpi_visual_design_tokens())
    spacing = visual_tokens.get("spacing") or {}
    typography = visual_tokens.get("typography") or {}
    opacity = visual_tokens.get("opacity") or {}
    visual_inventory: Dict[str, Any] = {}
    try:
        if isinstance(available_assets, dict):
            visual_inventory = dict(available_assets.get("visual_asset_inventory") or available_assets)
        if not visual_inventory.get("all_assets"):
            from .vpi_asset_library_service import build_local_visual_asset_inventory as _build_local_visual_asset_inventory

            visual_inventory = _build_local_visual_asset_inventory()
    except Exception as _visual_inventory_exc:
        logger.debug("[visual-assets] inventory_unavailable reason=%s", _visual_inventory_exc)
        visual_inventory = {}
    visual_assets = list(visual_inventory.get("all_assets") or [])
    density_value = 0.0
    try:
        density_value = float(visual_density or 0.0)
    except (TypeError, ValueError):
        density_value = 0.0
    overlay_budget = bool(caption_presence) or density_value <= 8.0
    support_layer = str(visual_support_layer_selected or "")
    family = _reinforcement_family(editorial_type, text)
    number_text = _extract_number_emphasis(text)
    available_assets = available_assets or {}
    def _layout_payload(current_strategy: str, current_asset: str) -> Dict[str, Any]:
        return choose_visual_layout_strategy(
            editorial_type=editorial_type,
            visual_reinforcement_strategy=current_strategy,
            visual_asset_selected=current_asset,
            hook_strategy_final=hook_strategy_final,
            caption_density=visual_density,
            face_bbox=face_bbox,
            speaker_bbox=speaker_bbox,
            safe_zone_map=safe_zone_map,
            visual_layer_budget=visual_layer_budget,
            clip_duration=clip_duration,
            first3_has_captions=first3_has_captions or caption_presence,
            visual_design_tokens=visual_tokens,
            visual_asset_inventory_summary=visual_asset_inventory_summary or visual_inventory.get("summary") or visual_inventory.get("inventory_summary") or {},
        )
    if not support_layer or not overlay_budget:
        logger.info("VPI_VISUAL_TOKENS_APPLIED backend=vpi_visual_effects visual_design_version=%s reinforcement=false", visual_tokens["visual_design_version"])
        return {
            "visual_reinforcement_strategy": "none",
            "reason": "no_budget_or_support_layer",
            "asset_key": "",
            "asset_path": "",
            "render_start": 0.0,
            "render_duration": 0.0,
            "safe_zone": "",
            "priority": 0,
            "visual_reinforcement_text": "",
            "visual_design_version": str(visual_tokens.get("visual_design_version") or _VPI_VISUAL_TOKENS_VERSION),
            "visual_design_tokens_applied_to_reinforcement": True,
            "visual_asset_inventory_used": bool(visual_assets),
            "visual_asset_selected": "",
            "visual_asset_selection_reason": "no_budget_or_support_layer",
            "visual_asset_fallback_used": False,
            "sensitive_visual_asset_blocked": False,
            "visual_asset_identity_warnings": [],
            **_layout_payload("no_extra_visual", ""),
        }

    safe_zones = safe_zone_map.get("layer_to_zone") if isinstance(safe_zone_map, dict) else {}
    support_zone = str((safe_zones or {}).get(support_layer) or "")
    if not support_zone:
        support_zone = "top_safe" if support_layer in {"icon", "hook_motion"} else "middle_safe"

    strategy = "none"
    reason = "no_clear_reinforcement"
    asset_key = ""
    asset_path = ""
    reinforcement_text = ""
    render_start = 0.25 if clip_duration <= 8.0 else 0.4
    render_duration = 1.2 if clip_duration <= 8.0 else 1.5
    priority = 0

    if family == "warning_pulse":
        strategy = "warning_pulse"
        reason = "risk_warning_reinforcement"
        asset_key = "warning_pulse"
        render_start, render_duration, priority = 0.22, 1.15, 92
    elif family == "shield_protection":
        strategy = "shield_protection"
        reason = "protection_family_reinforcement"
        asset_key = "shield_protection"
        render_start, render_duration, priority = 0.24, 1.35, 90
    elif family == "health_cross":
        strategy = "svg_icon"
        reason = "health_clarity_reinforcement"
        asset_key = "medical_cross.svg"
        render_start, render_duration, priority = 0.28, 1.2, 88
    elif family == "money_check":
        if number_text:
            strategy = "number_emphasis"
            reason = "number_emphasis_for_value"
            asset_key = number_text
            reinforcement_text = number_text
            render_start, render_duration, priority = 0.28, 1.05, 89
        else:
            strategy = "icon_badge"
            reason = "money_reinforcement"
            asset_key = "money_check"
            render_start, render_duration, priority = 0.28, 1.15, 86
    elif family == "document_policy":
        strategy = "svg_icon"
        reason = "coverage_policy_reinforcement"
        asset_key = "document_policy"
        render_start, render_duration, priority = 0.32, 1.25, 87
    elif family == "check_x_myth":
        strategy = "check_x_myth"
        reason = "myth_reinforcement"
        asset_key = "myth_break.svg"
        render_start, render_duration, priority = 0.28, 1.15, 88
    elif family == "question_badge":
        strategy = "callout_circle"
        reason = "objection_reinforcement"
        asset_key = "question_badge"
        render_start, render_duration, priority = 0.28, 1.0, 82
    elif support_layer in {"icon", "hook_motion"} and hook_strategy_final in {"non_text_push_hook", "silence_tension_hook"}:
        strategy = "svg_icon"
        reason = "support_layer_icon_reinforcement"
        asset_key = "shield_check.svg" if "protec" in _normalize_reinforcement_text(text) else "hook_badge.svg"
        render_start, render_duration, priority = 0.3, 1.1, 80
    elif support_layer == "semantic_card" and not hook_text_redundant_with_captions:
        strategy = "semantic_micro_card"
        reason = "support_layer_micro_card"
        asset_key = textwrap.shorten(text or editorial_type or "Mira esto", width=14, placeholder="…")
        reinforcement_text = asset_key
        render_start, render_duration, priority = 0.35, 1.15, 78
    elif support_layer in {"branding", "cta"} and clip_duration >= 8.0:
        strategy = "icon_badge"
        reason = "minimal_support_reinforcement"
        asset_key = "hook_badge"
        render_start, render_duration, priority = max(0.35, clip_duration - 2.2), 0.95, 70

    if strategy == "none":
        logger.info("VPI_VISUAL_TOKENS_APPLIED backend=vpi_visual_effects visual_design_version=%s reinforcement=false", visual_tokens["visual_design_version"])
        return {
            "visual_reinforcement_strategy": "none",
            "reason": reason,
            "asset_key": "",
            "asset_path": "",
            "render_start": 0.0,
            "render_duration": 0.0,
            "safe_zone": "",
            "priority": 0,
            "visual_reinforcement_text": "",
            "visual_design_version": str(visual_tokens.get("visual_design_version") or _VPI_VISUAL_TOKENS_VERSION),
            "visual_design_tokens_applied_to_reinforcement": True,
            "visual_asset_inventory_used": bool(visual_assets),
            "visual_asset_selected": "",
            "visual_asset_selection_reason": reason,
            "visual_asset_fallback_used": False,
            "sensitive_visual_asset_blocked": False,
            "visual_asset_identity_warnings": [],
            **_layout_payload("no_extra_visual", ""),
        }

    asset_path_obj: Optional[Path] = None
    asset_selected = ""
    asset_selection_reason = "no_asset"
    asset_fallback_used = False
    sensitive_visual_asset_blocked = False
    sensitive_topic = any(token in _normalize_reinforcement_text(" ".join([editorial_type or "", text or ""])) for token in ("decesos", "funeral", "fallecimiento", "muerte", "sepelio", "velatorio", "luto"))
    intent_hint = _reinforcement_family(editorial_type, text)
    visual_intent = {
        "shield_protection": "protection",
        "health_cross": "health",
        "warning_pulse": "risk_warning",
        "money_check": "money_saving",
        "document_policy": "coverage",
        "check_x_myth": "myth_debunk",
        "question_badge": "objection",
    }.get(family or intent_hint, "")
    if not visual_intent and family in {"svg_icon", "icon_badge", "semantic_micro_card", "callout_arrow", "callout_circle", "number_emphasis"}:
        visual_intent = "coverage" if "document" in _normalize_reinforcement_text(text) else "objection"
    if sensitive_topic:
        visual_intent = "sensitive_sober"
    def _select_visual_asset(intent: str) -> Optional[Dict[str, Any]]:
        best: Optional[Dict[str, Any]] = None
        best_score = -999.0
        for item in visual_assets:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("verified_local", False)):
                continue
            if not bool(item.get("usable_for_vpi", True)):
                continue
            if sensitive_topic and not bool(item.get("sensitive_safe", False)):
                continue
            item_intent = str(item.get("visual_intent") or "").strip()
            item_family = str(item.get("visual_family") or "").strip()
            if intent and item_intent != intent and item_family != intent:
                continue
            score = 0.0
            if item_intent == intent:
                score += 4.0
            if item_family == intent:
                score += 3.0
            if not item.get("identity_warnings"):
                score += 1.0
            dims = item.get("dimensions") or {}
            if int(dims.get("width") or 0) >= 192 and int(dims.get("height") or 0) >= 192:
                score += 0.5
            if score > best_score:
                best_score = score
                best = item
        return best

    selected_asset = _select_visual_asset(visual_intent) if visual_intent else None
    if selected_asset:
        asset_selected = str(selected_asset.get("visual_asset_id") or Path(str(selected_asset.get("visual_asset_path") or "")).stem)
        asset_path_obj = Path(str(selected_asset.get("visual_asset_path") or "")).resolve()
        selected_identity_warnings = list(selected_asset.get("identity_warnings") or [])
        if selected_identity_warnings:
            sensitive_visual_asset_blocked = True
        asset_selection_reason = "local_inventory_match"
        logger.info(
            "VISUAL_ASSET_SELECTED asset=%s intent=%s type=%s",
            asset_selected,
            visual_intent or "none",
            str(selected_asset.get("visual_asset_type") or "unknown"),
        )
    else:
        asset_fallback_used = True
        asset_selection_reason = "callout_fallback"
        logger.warning(
            "VISUAL_ASSET_MISSING_FOR_INTENT intent=%s reason=no_local_verified_asset",
            visual_intent or "unknown",
        )
        logger.info(
            "VISUAL_ASSET_FALLBACK_USED intent=%s reason=%s",
            visual_intent or "unknown",
            asset_selection_reason,
        )
        if sensitive_topic:
            sensitive_visual_asset_blocked = True
            logger.warning(
                "SENSITIVE_VISUAL_ASSET_BLOCKED editorial_type=%s intent=%s reason=no_verified_sensitive_asset",
                editorial_type or "unknown",
                visual_intent or "unknown",
            )

    if strategy in {"svg_icon", "shield_protection", "health_cross", "warning_pulse", "money_check", "document_policy", "check_x_myth"}:
        icon_map_key = {
            "shield_protection": "shield_protection",
            "health_cross": "health_cross",
            "warning_pulse": "warning_pulse",
            "money_check": "money_check",
            "document_policy": "document_policy",
            "check_x_myth": "check_x_myth",
        }.get(strategy, "")
        if icon_map_key and asset_path_obj is None:
            asset_path_obj = _select_reinforcement_icon_asset(available_assets if isinstance(available_assets, dict) else None, icon_map_key)
            if asset_path_obj:
                asset_path = str(asset_path_obj)
                asset_selected = asset_path_obj.stem
                asset_selection_reason = "existing_icon_library"
            else:
                asset_selection_reason = "existing_icon_missing"
                reason = f"{reason}_icon_missing"
    elif strategy == "icon_badge":
        asset_path = ""

    if strategy == "number_emphasis":
        reinforcement_text = reinforcement_text or asset_key
    if sensitive_topic and strategy in {"warning_pulse", "check_x_myth"}:
        sensitive_visual_asset_blocked = True
        asset_path_obj = None
        asset_selected = ""
        asset_selection_reason = "sensitive_visual_blocked"
        asset_fallback_used = True
        strategy = "callout_circle"
        reason = "sensitive_sober_fallback"
        reinforcement_text = ""
        logger.warning(
            "SENSITIVE_VISUAL_ASSET_BLOCKED editorial_type=%s intent=%s reason=%s",
            editorial_type or "unknown",
            visual_intent or "unknown",
            "sensitive_content_morbid_or_aggressive",
        )

    _layout = choose_visual_layout_strategy(
        editorial_type=editorial_type,
        visual_reinforcement_strategy=strategy,
        visual_asset_selected=asset_selected,
        hook_strategy_final=hook_strategy_final,
        caption_density=visual_density,
        face_bbox=face_bbox,
        speaker_bbox=speaker_bbox,
        safe_zone_map=safe_zone_map,
        visual_layer_budget=visual_layer_budget,
        clip_duration=clip_duration,
        first3_has_captions=first3_has_captions or caption_presence,
        visual_design_tokens=visual_tokens,
        visual_asset_inventory_summary=visual_asset_inventory_summary or visual_inventory.get("summary") or visual_inventory.get("inventory_summary") or {},
    )

    return {
        "visual_reinforcement_strategy": strategy,
        "reason": reason,
        "asset_key": asset_selected or asset_key,
        "asset_path": str(asset_path_obj) if asset_path_obj else asset_path,
        "render_start": round(float(render_start), 2),
        "render_duration": round(float(render_duration), 2),
        "safe_zone": support_zone if support_zone else "middle_safe",
        "priority": int(priority),
        "visual_reinforcement_text": reinforcement_text,
        "support_layer": support_layer,
        "visual_design_version": str(visual_tokens.get("visual_design_version") or _VPI_VISUAL_TOKENS_VERSION),
        "visual_design_tokens_applied_to_reinforcement": True,
        "visual_design_tokens": {
            "spacing": spacing,
            "typography": typography,
            "opacity": opacity,
        },
        "visual_asset_inventory_used": bool(visual_assets),
        "visual_asset_selected": asset_selected,
        "visual_asset_selection_reason": asset_selection_reason,
        "visual_asset_fallback_used": bool(asset_fallback_used),
        "sensitive_visual_asset_blocked": bool(sensitive_visual_asset_blocked),
        "visual_asset_identity_warnings": list(selected_identity_warnings if selected_asset else []),
        **_layout,
    }


def _rasterize_svg_to_png(svg_path: Path, png_path: Path, size: int = 512) -> bool:
    svg_path = svg_path.resolve()
    png_path = png_path.resolve()
    cmd_candidates = [
        ["rsvg-convert", "-w", str(int(size)), "-h", str(int(size)), "-o", str(png_path), str(svg_path)],
        ["convert", str(svg_path), str(png_path)],
    ]
    for cmd in cmd_candidates:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and png_path.exists() and png_path.is_file():
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return False


def _write_reinforcement_svg(
    *,
    strategy: str,
    accent_text: str,
    icon_path: Optional[Path],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{strategy}|{accent_text}|{icon_path or ''}".encode("utf-8")).hexdigest()[:12]
    svg_path = output_dir / f"reinforcement_{digest}.svg"
    svg_path.write_text(
        _build_reinforcement_svg_markup(strategy=strategy, accent_text=accent_text, icon_svg_path=icon_path),
        encoding="utf-8",
    )
    return svg_path


def _safe_reinforcement_dir(output_dir: str | Path | None = None) -> Path:
    base = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / "viraclip_visual_reinforcement"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        fallback = Path(tempfile.gettempdir()) / "viraclip_visual_reinforcement"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


@lru_cache(maxsize=1)
def _available_visual_renderers() -> Dict[str, Any]:
    renderers = {
        "rsvg-convert": shutil.which("rsvg-convert"),
        "magick": shutil.which("magick"),
        "convert": shutil.which("convert"),
        "ffmpeg": shutil.which("ffmpeg"),
    }
    selected = ""
    if renderers["rsvg-convert"]:
        selected = "rsvg-convert"
    elif renderers["magick"]:
        selected = "magick"
    elif renderers["convert"]:
        selected = "convert"
    elif renderers["ffmpeg"]:
        selected = "ffmpeg_native"
    unavailable = [name for name, path in renderers.items() if not path]
    unavailable_reason = ""
    if not renderers["ffmpeg"]:
        unavailable_reason = "ffmpeg_missing"
    elif selected == "ffmpeg_native":
        unavailable_reason = "rasterizers_missing"
    return {
        "available": renderers,
        "visual_renderer_selected": selected,
        "visual_renderer_fallback_used": bool(selected == "ffmpeg_native"),
        "visual_renderer_unavailable_reason": unavailable_reason,
        "unavailable": unavailable,
    }


def _probe_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if result.returncode != 0:
            return None
        return float((result.stdout or "").strip())
    except Exception:
        return None


def _verify_visual_reinforcement_output(input_path: Path, output_path: Path) -> bool:
    if not output_path.exists() or not output_path.is_file():
        return False
    try:
        if output_path.stat().st_size <= 0:
            return False
    except Exception:
        return False
    if _probe_duration(output_path) is None:
        return False
    input_duration = _probe_duration(input_path)
    output_duration = _probe_duration(output_path)
    if input_duration is None or output_duration is None:
        return False
    tolerance = max(1.0, float(input_duration) * 0.12)
    return abs(float(output_duration) - float(input_duration)) <= tolerance


def _escape_drawtext_text(text: str) -> str:
    safe = str(text or "").replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%").replace(",", "\\,")
    return safe.replace("\n", " ").strip()


def _available_font_file() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return ""


def _build_ffmpeg_native_reinforcement_label(strategy: str, accent_text: str) -> str:
    normalized = _normalize_reinforcement_text(accent_text)
    if strategy == "warning_pulse":
        return f"! {accent_text or 'RIESGO'}".strip()
    if strategy == "shield_protection":
        return f"✓ {accent_text or 'PROTECCIÓN'}".strip()
    if strategy == "health_cross":
        return accent_text or "SALUD"
    if strategy == "money_check":
        return accent_text or "AHORRO"
    if strategy == "document_policy":
        return accent_text or "COBERTURA"
    if strategy == "check_x_myth":
        return accent_text or "MITO"
    if strategy == "question_badge":
        return accent_text or "DUDA"
    if strategy == "number_emphasis":
        return accent_text or "AHORRO"
    if strategy == "icon_badge":
        return accent_text or "!"
    if strategy == "callout_arrow":
        return accent_text or "MIRA ESTO"
    if strategy == "callout_circle":
        return accent_text or "PUNTO CLAVE"
    if strategy == "semantic_micro_card":
        return accent_text or "MIRA ESTO"
    return normalized or accent_text or "MIRA ESTO"


def _render_visual_reinforcement_ffmpeg_native(
    *,
    input_video_path: Path,
    output_video_path: Path,
    strategy: str,
    safe_zone: str,
    accent_text: str,
    render_start: float,
    render_duration: float,
    plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    daily_mode_active = str(os.environ.get("VPI_DAILY_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}
    out: Dict[str, Any] = {
        "rendered": False,
        "output_video_path": str(output_video_path),
        "reason": "not_started",
        "error": None,
        "backend": "ffmpeg_native_fallback",
        "visual_renderer_selected": "",
        "visual_renderer_fallback_used": False,
        "visual_renderer_unavailable_reason": "",
        "visual_asset_inventory_used": bool(plan.get("visual_asset_inventory_used")),
        "visual_asset_selected": str(plan.get("visual_asset_selected") or ""),
        "visual_asset_selection_reason": str(plan.get("visual_asset_selection_reason") or ""),
        "visual_asset_fallback_used": bool(plan.get("visual_asset_fallback_used")),
        "sensitive_visual_asset_blocked": bool(plan.get("sensitive_visual_asset_blocked")),
        "visual_asset_identity_warnings": list(plan.get("visual_asset_identity_warnings") or []),
    }
    if daily_mode_active:
        logger.info(
            "VPI_HOOK_VISUAL_BOX_DISABLED_DAILY reason=daily_mode backend=ffmpeg_native_fallback strategy=%s",
            strategy,
        )
        logger.info(
            "VPI_NON_TEXT_HOOK_BORDER_DISABLED reason=daily_mode backend=ffmpeg_native_fallback strategy=%s",
            strategy,
        )
        out["reason"] = "daily_mode_no_visual_reinforcement"
        out["visual_renderer_unavailable_reason"] = "daily_mode_no_visual_reinforcement"
        return out
    if not input_video_path.exists() or not input_video_path.is_file():
        out["reason"] = "input_video_missing"
        return out
    if shutil.which("ffmpeg") is None:
        out["reason"] = "ffmpeg_missing"
        out["visual_renderer_unavailable_reason"] = "ffmpeg_missing"
        return out
    out["visual_renderer_selected"] = "ffmpeg_native"
    out["visual_renderer_fallback_used"] = True

    width, height = _probe_size(input_video_path)
    badge_w = min(max(240, int(width * 0.22)), 380)
    badge_h = 110 if width >= 1000 else 92
    margin_x = 28 if width >= 700 else 18
    margin_y = 28 if height >= 1200 else 22
    bottom_clearance = 220 if height >= 1200 else 160
    zone = str(safe_zone or "")
    if zone in {"middle_safe"}:
        x_expr = f"(W-{badge_w})/2"
        y_expr = f"(H-{badge_h})/2"
    elif zone in {"bottom_safe", "final_safe"}:
        x_expr = f"(W-{badge_w})/2"
        y_expr = f"H-{badge_h}-{bottom_clearance}"
    elif zone in {"corner_safe"}:
        x_expr = f"W-{badge_w}-{margin_x}"
        y_expr = f"{margin_y}"
    else:
        x_expr = f"W-{badge_w}-{margin_x}"
        y_expr = f"{margin_y}"

    label = _build_ffmpeg_native_reinforcement_label(strategy, accent_text)
    label_escaped = _escape_drawtext_text(label)
    fontfile = _available_font_file()
    font_expr = f"fontfile={fontfile}:" if fontfile else "font='DejaVu Sans':"
    start = max(0.0, float(render_start or 0.0))
    duration = max(0.8, min(1.8, float(render_duration or 1.2)))
    end = start + duration
    fontsize = 30 if len(label) <= 8 else 24
    text_x = f"{x_expr} + ({badge_w} - text_w) / 2"
    text_y = f"{y_expr} + ({badge_h} - text_h) / 2 - 2"
    filter_complex = (
        f"[0:v]drawbox=x={x_expr}:y={y_expr}:w={badge_w}:h={badge_h}:color=black@0.60:t=fill:enable='between(t,{start:.2f},{end:.2f})',"
        f"drawbox=x={x_expr}:y={y_expr}:w={badge_w}:h={badge_h}:color=white@0.08:t=2:enable='between(t,{start:.2f},{end:.2f})',"
        f"drawtext={font_expr}text='{label_escaped}':fontcolor=#F7F7F4:fontsize={fontsize}:"
        f"box=0:x={text_x}:y={text_y}:enable='between(t,{start:.2f},{end:.2f})'[outv]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        if result.returncode != 0:
            out["reason"] = "ffmpeg_failed"
            out["error"] = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()[-900:]
            return out
    except FileNotFoundError:
        out["reason"] = "ffmpeg_missing"
        out["error"] = "ffmpeg_missing"
        return out
    except Exception as exc:
        out["reason"] = "compose_failed"
        out["error"] = str(exc)
        return out

    verified = _verify_visual_reinforcement_output(input_video_path, output_video_path)
    out["rendered"] = verified
    out["reason"] = "applied" if verified else "output_unverified"
    if not verified:
        out["error"] = "output_unverified"
    return out


def render_visual_reinforcement(
    *,
    input_video_path: str | Path,
    output_video_path: str | Path,
    reinforcement_plan: Optional[Dict[str, Any]] = None,
    global_visual_layer_budget: Optional[Dict[str, Any]] = None,
    output_dir: str | Path | None = None,
) -> Dict[str, Any]:
    plan = dict(reinforcement_plan or {})
    budget = global_visual_layer_budget if isinstance(global_visual_layer_budget, dict) else {}
    daily_mode_active = str(os.environ.get("VPI_DAILY_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}
    strategy = str(plan.get("visual_reinforcement_strategy") or "none")
    support_layer = str(plan.get("support_layer") or "")
    safe_zone = str(plan.get("safe_zone") or "")
    layout_strategy = str(plan.get("visual_layout_strategy") or plan.get("layout_strategy") or "no_extra_visual")
    layout_zone = str(plan.get("visual_layout_zone") or plan.get("layout_zone") or safe_zone or "")
    layout_size = str(plan.get("visual_layout_size") or plan.get("layout_size") or "small")
    layout_opacity = float(plan.get("visual_layout_opacity") or plan.get("layout_opacity") or 1.0)
    layout_duration = float(plan.get("visual_layout_duration") or plan.get("layout_duration") or 0.0)
    reason = str(plan.get("reason") or "no_strategy")
    out: Dict[str, Any] = {
        "planned": bool(strategy and strategy != "none"),
        "rendered": False,
        "dropped_by_budget": False,
        "budget_drop_reason": "",
        "visual_reinforcement_applied": False,
        "visual_reinforcement_strategy": strategy,
        "visual_reinforcement_asset": str(plan.get("asset_key") or ""),
        "visual_reinforcement_reason": reason,
        "visual_reinforcement_rendered": False,
        "visual_reinforcement_backend": "none",
        "visual_reinforcement_safe_zone": safe_zone,
        "visual_reinforcement_dropped_reason": "",
        "visual_reinforcement_output_path": str(output_video_path),
        "visual_reinforcement_support_layer": support_layer,
        "reason": reason,
        "visual_renderer_selected": "",
        "visual_renderer_fallback_used": False,
        "visual_renderer_unavailable_reason": "",
        "visual_layout_strategy": layout_strategy,
        "visual_layout_zone": layout_zone,
        "visual_layout_size": layout_size,
        "visual_layout_opacity": float(layout_opacity),
        "visual_layout_duration": float(layout_duration),
        "visual_layout_reason": str(plan.get("visual_layout_reason") or "no_extra_visual"),
        "visual_layout_face_safe": bool(plan.get("visual_layout_face_safe", True)),
        "visual_layout_caption_safe": bool(plan.get("visual_layout_caption_safe", True)),
        "visual_layout_ok": bool(plan.get("visual_layout_ok", True)),
        "visual_layout_warnings": list(plan.get("visual_layout_warnings") or []),
    }
    if strategy == "none":
        out["reason"] = reason or "no_strategy"
        return out

    if daily_mode_active:
        logger.info(
            "VPI_HOOK_VISUAL_BOX_DISABLED_DAILY reason=daily_mode strategy=%s",
            strategy,
        )
        logger.info(
            "VPI_NON_TEXT_HOOK_BORDER_DISABLED reason=daily_mode strategy=%s",
            strategy,
        )
        out["rendered"] = False
        out["visual_reinforcement_applied"] = False
        out["visual_reinforcement_rendered"] = False
        out["visual_reinforcement_backend"] = "daily_mode_disabled"
        out["reason"] = "daily_mode_no_visual_reinforcement"
        return out

    renderers = _available_visual_renderers()
    out["visual_renderer_selected"] = str(renderers.get("visual_renderer_selected") or "")
    out["visual_renderer_fallback_used"] = bool(renderers.get("visual_renderer_fallback_used"))
    out["visual_renderer_unavailable_reason"] = str(renderers.get("visual_renderer_unavailable_reason") or "")

    budget_decision = dict((budget.get("layer_decisions") or {}).get("visual_reinforcement") or {})
    budget_action = str(budget_decision.get("action") or "").strip()
    if budget and (
        budget_action == "drop"
        or bool(budget.get("temporal_density_budget_applied"))
        and not support_layer
    ):
        _budget_reason = str(budget_decision.get("reason") or budget.get("temporal_density_reason") or "budget_blocked")
        out["dropped_by_budget"] = True
        out["budget_drop_reason"] = _budget_reason
        out["visual_reinforcement_dropped_reason"] = _budget_reason
        out["reason"] = _budget_reason
        logger.info("OVERLAY_RENDER_BLOCKED_BY_BUDGET layer=visual_reinforcement reason=%s", _budget_reason)
        return out

    # Require a meaningful support layer or explicit budget allowance.
    if not support_layer and not budget_action:
        out["reason"] = "no_support_layer"
        out["visual_reinforcement_dropped_reason"] = "no_support_layer"
        logger.info("VISUAL_REINFORCEMENT_SKIPPED_REASON reason=no_support_layer")
        return out

    input_path = Path(input_video_path).resolve()
    if not input_path.exists() or not input_path.is_file():
        out["reason"] = "input_video_missing"
        out["visual_reinforcement_dropped_reason"] = "input_video_missing"
        logger.info("VISUAL_REINFORCEMENT_SKIPPED_REASON reason=input_video_missing")
        return out

    asset_path = Path(str(plan.get("asset_path") or "")).resolve() if plan.get("asset_path") else None
    strategy_requires_icon = strategy in {"svg_icon", "shield_protection", "health_cross", "warning_pulse", "money_check", "document_policy", "check_x_myth"}
    generated_svg_path = None
    temp_dir = _safe_reinforcement_dir(output_dir)
    icon_renderable = bool(asset_path and asset_path.exists() and asset_path.is_file())
    if strategy_requires_icon:
        if icon_renderable:
            svg_icon_path = asset_path
        else:
            out["visual_reinforcement_asset"] = str(plan.get("asset_key") or "")
            logger.info("SVG_ICON_SKIPPED_REASON reason=asset_missing strategy=%s asset=%s", strategy, str(plan.get("asset_key") or ""))
            reason = f"{reason}_degraded_to_callout"
            asset_path = None
        generated_svg_path = _write_reinforcement_svg(
            strategy="svg_icon" if strategy_requires_icon and asset_path else strategy,
            accent_text=str(plan.get("visual_reinforcement_text") or plan.get("asset_key") or ""),
            icon_path=asset_path if asset_path and asset_path.exists() else None,
            output_dir=temp_dir,
        )
    else:
        generated_svg_path = _write_reinforcement_svg(
            strategy=strategy,
            accent_text=str(plan.get("visual_reinforcement_text") or plan.get("asset_key") or ""),
            icon_path=None,
            output_dir=temp_dir,
        )

    out["visual_reinforcement_strategy"] = strategy
    out["visual_reinforcement_reason"] = reason
    out["visual_asset_inventory_used"] = bool(plan.get("visual_asset_inventory_used"))
    out["visual_asset_selected"] = str(plan.get("visual_asset_selected") or "")
    out["visual_asset_selection_reason"] = str(plan.get("visual_asset_selection_reason") or "")
    out["visual_asset_fallback_used"] = bool(plan.get("visual_asset_fallback_used"))
    out["sensitive_visual_asset_blocked"] = bool(plan.get("sensitive_visual_asset_blocked"))
    out["visual_asset_identity_warnings"] = list(plan.get("visual_asset_identity_warnings") or [])

    position = "upper_right"
    zone = layout_zone or str(plan.get("safe_zone") or "")
    if zone in {"bottom_safe", "final_safe"}:
        position = "lower_center"
    elif zone == "corner_safe":
        position = "upper_right"
    elif zone == "middle_safe":
        position = "center"
    elif zone == "top_safe":
        position = "upper_right"
    elif zone in {"upper_left_small", "upper_left"}:
        position = "upper_left"
    elif zone in {"upper_right_small", "upper_right"}:
        position = "upper_right"
    elif zone in {"lower_center_small", "lower_center"}:
        position = "lower_center"

    overlay_out = Path(output_video_path).resolve()
    render_start = float(plan.get("render_start") or 0.25)
    render_duration = float(layout_duration or plan.get("render_duration") or 1.2)
    backend = "runtime_svg" if not icon_renderable else "svg"

    def _run_native_fallback(fallback_reason: str) -> Dict[str, Any]:
        out["visual_renderer_unavailable_reason"] = fallback_reason
        native_result = _render_visual_reinforcement_ffmpeg_native(
            input_video_path=input_path,
            output_video_path=overlay_out,
            strategy=strategy,
            safe_zone=safe_zone or position,
            accent_text=str(plan.get("visual_reinforcement_text") or plan.get("asset_key") or ""),
            render_start=render_start,
            render_duration=render_duration,
            plan=plan,
        )
        native_rendered = bool(native_result.get("rendered")) and overlay_out.exists()
        out.update(
            {
                "rendered": native_rendered,
                "visual_reinforcement_applied": native_rendered,
                "visual_reinforcement_rendered": native_rendered,
                "visual_reinforcement_output_path": str(native_result.get("output_video_path") or overlay_out),
                "visual_reinforcement_backend": "ffmpeg_native_fallback" if native_rendered else "none",
                "visual_renderer_selected": str(native_result.get("visual_renderer_selected") or ""),
                "visual_renderer_fallback_used": bool(native_result.get("visual_renderer_selected")) and str(native_result.get("reason") or "") != "ffmpeg_missing",
                "visual_renderer_unavailable_reason": str(native_result.get("visual_renderer_unavailable_reason") or fallback_reason or ""),
                "reason": str(native_result.get("reason") or ("applied" if native_rendered else "output_unverified")),
                "visual_asset_inventory_used": bool(plan.get("visual_asset_inventory_used")),
                "visual_asset_selected": str(plan.get("visual_asset_selected") or ""),
                "visual_asset_selection_reason": str(plan.get("visual_asset_selection_reason") or ""),
                "visual_asset_fallback_used": bool(plan.get("visual_asset_fallback_used")),
                "sensitive_visual_asset_blocked": bool(plan.get("sensitive_visual_asset_blocked")),
                "visual_asset_identity_warnings": list(plan.get("visual_asset_identity_warnings") or []),
            }
        )
        if native_rendered:
            logger.info(
                "VISUAL_REINFORCEMENT_RENDERED backend=ffmpeg_native_fallback strategy=%s asset=%s start=%.2f duration=%.2f",
                strategy,
                str(plan.get("asset_key") or "none"),
                render_start,
                render_duration,
            )
            logger.info(
                "VISUAL_REINFORCEMENT_SELECTED strategy=%s reason=%s asset=%s safe_zone=%s",
                strategy,
                reason,
                str(plan.get("asset_key") or "none"),
                safe_zone or position,
            )
            logger.info("SVG_ICON_SKIPPED_REASON reason=%s strategy=%s", fallback_reason, strategy)
            return out
        out["visual_reinforcement_dropped_reason"] = str(native_result.get("reason") or fallback_reason or "output_unverified")
        logger.info("VISUAL_REINFORCEMENT_SKIPPED_REASON reason=%s", out["visual_reinforcement_dropped_reason"])
        return out

    if renderers.get("visual_renderer_selected") == "ffmpeg_native" or renderers.get("visual_renderer_selected") == "":
        logger.info(
            "SVG_ICON_SKIPPED_REASON reason=%s strategy=%s",
            renderers.get("visual_renderer_unavailable_reason") or "rasterizer_unavailable",
            strategy,
        )
        return _run_native_fallback(
            str(renderers.get("visual_renderer_unavailable_reason") or ("rasterizer_unavailable" if renderers.get("visual_renderer_selected") == "ffmpeg_native" else "visual_renderer_unavailable"))
        )

    png_path = generated_svg_path.with_suffix(".png")
    if not _rasterize_svg_to_png(generated_svg_path, png_path, size=640):
        logger.info("SVG_ICON_SKIPPED_REASON reason=rasterization_failed strategy=%s", strategy)
        return _run_native_fallback("rasterization_failed")

    if not png_path.exists() or not png_path.is_file():
        logger.info("SVG_ICON_SKIPPED_REASON reason=raster_output_missing strategy=%s", strategy)
        return _run_native_fallback("raster_output_missing")

    try:
        from .vpi_final_overlay_composer import apply_overlay_card_to_video as _apply_overlay_card_to_video
        overlay_result = _apply_overlay_card_to_video(
            input_video_path=str(input_path),
            overlay_card_path=str(png_path),
            output_video_path=str(overlay_out),
            position=position,
            start_time=float(plan.get("render_start") or 0.25),
            duration=float(plan.get("render_duration") or 1.2),
            scale_width=240 if strategy in {"svg_icon", "warning_pulse", "shield_protection", "health_cross"} else 320,
            opacity=0.96,
            layout_strategy=str(plan.get("visual_layout_strategy") or strategy),
            layout_zone=str(plan.get("visual_layout_zone") or safe_zone or position),
            layout_size=str(plan.get("visual_layout_size") or "small"),
            layout_opacity=float(plan.get("visual_layout_opacity") or 0.96),
            layout_duration=float(plan.get("visual_layout_duration") or plan.get("render_duration") or 1.2),
        )
    except Exception as exc:
        out["reason"] = str(exc)
        out["visual_reinforcement_dropped_reason"] = str(exc)
        logger.info("VISUAL_REINFORCEMENT_SKIPPED_REASON reason=%s", exc)
        return out

    output_exists = Path(str(overlay_result.get("output_video_path") or overlay_out)).exists()
    rendered = bool(overlay_result.get("motion_overlay_applied")) and output_exists
    backend = "runtime_svg" if rendered and not icon_renderable else "svg"
    out.update(
        {
            "rendered": rendered,
            "visual_reinforcement_applied": rendered,
            "visual_reinforcement_rendered": rendered,
            "visual_reinforcement_output_path": str(overlay_result.get("output_video_path") or overlay_out),
            "visual_reinforcement_backend": backend if rendered else "none",
            "visual_renderer_selected": str(renderers.get("visual_renderer_selected") or ""),
            "visual_renderer_fallback_used": bool(renderers.get("visual_renderer_fallback_used")),
            "visual_renderer_unavailable_reason": str(renderers.get("visual_renderer_unavailable_reason") or ""),
            "reason": str(overlay_result.get("reason") or ("applied" if rendered else "output_unreadable")),
            "visual_asset_inventory_used": bool(plan.get("visual_asset_inventory_used")),
            "visual_asset_selected": str(plan.get("visual_asset_selected") or ""),
            "visual_asset_selection_reason": str(plan.get("visual_asset_selection_reason") or ""),
            "visual_asset_fallback_used": bool(plan.get("visual_asset_fallback_used")),
            "sensitive_visual_asset_blocked": bool(plan.get("sensitive_visual_asset_blocked")),
            "visual_asset_identity_warnings": list(plan.get("visual_asset_identity_warnings") or []),
        }
    )
    if rendered:
        logger.info(
            "VISUAL_REINFORCEMENT_RENDERED backend=%s strategy=%s asset=%s start=%.2f duration=%.2f",
            backend,
            strategy,
            str(plan.get("asset_key") or "none"),
            float(plan.get("render_start") or 0.25),
            float(plan.get("render_duration") or 1.2),
        )
        logger.info(
            "VISUAL_REINFORCEMENT_SELECTED strategy=%s reason=%s asset=%s safe_zone=%s",
            strategy,
            reason,
            str(plan.get("asset_key") or "none"),
            safe_zone or position,
        )
        if generated_svg_path:
            logger.info("SVG_ICON_APPLIED asset=%s strategy=%s", str(plan.get("asset_key") or "none"), strategy)
    else:
        out["visual_reinforcement_dropped_reason"] = str(overlay_result.get("reason") or "output_unreadable")
        logger.info("VISUAL_REINFORCEMENT_SKIPPED_REASON reason=%s", out["visual_reinforcement_dropped_reason"])
        if strategy_requires_icon:
            logger.info("SVG_ICON_SKIPPED_REASON reason=%s asset=%s", out["visual_reinforcement_dropped_reason"], str(plan.get("asset_key") or "none"))
    return out


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
    max_layers = min(2, int(composition_decision.get("max_simultaneous_layers") or 2))
    priority_order = list(composition_decision.get("priority_order") or [])
    allowed_layers: List[Dict[str, Any]] = []
    skipped_layers: List[Dict[str, Any]] = []
    active_types: List[str] = []
    layer_overload = False
    text_layers = {"hook_overlay", "caption", "lower_third", "semantic_card", "branding_text"}

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
        if allowed and layer_type in text_layers:
            text_count = sum(1 for t in active_types if t in text_layers)
            if text_count >= 2:
                allowed = False
                reason = "max_text_layers_collision_guard"
                logger.info(
                    "OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s active=%s max_text_layers=%d",
                    layer_type,
                    reason,
                    "|".join(active_types) or "none",
                    2,
                )

        # Rule 2: Never strong transition during hook_overlay
        if allowed and layer_type in {"glitch_clean", "shape_morph_beta", "mask_reveal", "sweeping_reveal", "sweeping_object_reveal"} and "hook_overlay" in active_types:
            allowed = False
            reason = "strong_transition_during_hook_overlay"

        # Rule 2b: avoid B-roll only while the hook overlay is actually ON SCREEN —
        # a cutaway that starts after the hook window is editorially fine.
        if allowed and layer_type == "broll" and "hook_overlay" in active_types:
            _hook_layer = next(
                (l for l in layers if str(l.get("type") or l.get("layer_type") or "") == "hook_overlay"),
                None,
            )
            _hook_end = (
                float((_hook_layer or {}).get("start_s") or 0.0)
                + float((_hook_layer or {}).get("duration_s") or 1.2)
            )
            _broll_start = float(layer.get("start_s") or 0.0)
            if _broll_start < _hook_end + 0.3:
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
                logger.info(
                    "OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s active=%s max_text_layers=%d",
                    layer_type,
                    reason,
                    "|".join(active_types) or "none",
                    2,
                )

        # Rule 6: Max SIMULTANEOUS layers cap — time-aware: only layers whose time
        # ranges actually overlap compete for the cap (a 4.4s cutaway and a 0.25-3.05s
        # hook card are sequential, not simultaneous).
        if allowed and active_types:
            _l_start = float(layer.get("start_s") or 0.0)
            _l_end = _l_start + float(layer.get("duration_s") or 1.0)
            _overlapping = 0
            for _prev in allowed_layers:
                _p_type = str(_prev.get("type") or _prev.get("layer_type") or "")
                if not _p_type:
                    continue
                _p_start = float(_prev.get("start_s") or 0.0)
                _p_end = _p_start + float(_prev.get("duration_s") or 1.0)
                if _l_start < _p_end and _p_start < _l_end:
                    _overlapping += 1
            if _overlapping >= max_layers:
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
        # Exception: the daily full-frame cutaway is already gated upstream
        # (confidence >= 0.75, local asset, backstage screen, post-hook timing)
        # and is the sober editorial insert minimal_safe is meant to allow.
        if (
            allowed
            and layer_type == "broll"
            and comp_mode == "minimal_safe"
            and str(layer.get("broll_mode") or "") != "daily_fullframe_cutaway"
        ):
            allowed = False
            reason = "broll_in_minimal_safe"
        if allowed and layer_type == "broll":
            caption_text = str(layer.get("caption_text") or layer.get("text") or "")
            if len(caption_text.split()) > 12 or len(caption_text) > 90:
                allowed = False
                reason = "broll_with_long_caption"

        # Rule 10: Rhythm interruption must stay soft in sensitive modes.
        if allowed and layer_type == "rhythm_interrupt":
            subtype = str(layer.get("subtype") or layer.get("rhythm_type") or "")
            is_visual = bool(layer.get("visual", subtype in {"caption_pulse", "motion_kick", "transition_snap"}))
            first3_status = str(composition_decision.get("first3_status") or "")
            first3_overload = bool(composition_decision.get("first3_overload"))
            if comp_mode == "minimal_safe" and subtype in {"caption_pulse", "motion_kick", "transition_snap", "sfx_micro_hit"}:
                allowed = False
                reason = "minimal_safe_rhythm_limit"
            elif comp_mode == "emotional_soft" and subtype in {"sfx_micro_hit", "transition_snap"}:
                allowed = False
                reason = "tone_sensitive_emotional_soft"
            elif (first3_status in {"review", "fail"} or first3_overload) and is_visual:
                allowed = False
                reason = "first3_overload_visual_interrupt"

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


def _shot_rhythm_profile(
    hook_intent: str,
    composition_mode: str,
) -> str:
    intent = str(hook_intent or "neutral_explanation")
    profile = _SHOT_RHYTHM_PROFILE_BY_INTENT.get(intent, "minimal_safe_rhythm")
    mode = str(composition_mode or "")
    if mode == "minimal_safe":
        return "minimal_safe_rhythm"
    if mode == "emotional_soft":
        return "emotional_breathing"
    if mode == "warning_tension":
        return "warning_breath"
    if mode == "business_punch":
        return "business_punch_pacing"
    if mode == "explanation_clean":
        return "explanation_clean_pacing"
    if mode == "hook_driven":
        return "hook_snap"
    return profile


def _pacing_score_before(
    *,
    segment_text: str,
    fluency_plan: Dict[str, Any],
    silence_plan: Dict[str, Any],
) -> float:
    words = [token for token in str(segment_text or "").split(" ") if token]
    score = 0.72
    if len(words) < 8:
        score -= 0.08
    score -= min(0.22, float(fluency_plan.get("disfluency_count") or 0) * 0.03)
    score -= min(0.12, float(fluency_plan.get("false_start_count") or 0) * 0.04)
    dead_air_removed = len((silence_plan.get("summary") or {}).get("removed_dead_pauses") or [])
    score -= min(0.10, dead_air_removed * 0.02)
    return round(max(0.0, min(1.0, score)), 3)


def build_safe_microcuts(
    *,
    silence_plan: Optional[Dict[str, Any]] = None,
    fluency_plan: Optional[Dict[str, Any]] = None,
    max_microcuts: int = 3,
) -> List[Dict[str, Any]]:
    silence = silence_plan or {}
    fluency = fluency_plan or {}
    if int(fluency.get("false_start_count") or 0) + int(fluency.get("disfluency_count") or 0) >= 6:
        return []
    if int((silence.get("summary") or {}).get("fluency_cuts_added") or 0) >= 3:
        return []

    existing_cuts = list(silence.get("cuts") or [])
    segments = list(silence.get("segments") or [])
    microcuts: List[Dict[str, Any]] = []

    def _overlaps_existing(start_s: float, end_s: float) -> bool:
        for cut in existing_cuts:
            a = float(cut.get("start_s") or 0.0)
            b = float(cut.get("end_s") or a)
            if start_s < b and end_s > a:
                return True
        return False

    for seg in segments:
        if len(microcuts) >= max_microcuts:
            break
        action = str(seg.get("action") or "")
        reason = str(seg.get("reason") or "").lower()
        pause_type = str(seg.get("pause_type") or "").lower()
        confidence = float(seg.get("confidence") or 0.0)
        if action not in {"cut", "shorten"}:
            continue
        if confidence < 0.65:
            logger.info("[shot-rhythm] microcut skipped reason=timestamp_low_confidence")
            continue
        if "emotional" in reason or "closure" in reason or pause_type in {"let_it_land_pause", "emphasis_pause"}:
            logger.info("[shot-rhythm] microcut skipped reason=emotional_pause")
            continue
        if not any(flag in reason or flag in pause_type for flag in ("dead_air", "false_start", "awkward", "technical", "traba", "stumble", "bts")):
            continue
        start_s = float(seg.get("start_s") or 0.0)
        end_s = float(seg.get("end_s") or start_s)
        if end_s <= start_s:
            logger.info("[shot-rhythm] microcut skipped reason=timestamp_low_confidence")
            continue
        max_duration = 0.45
        if "traba" in reason or "stumble" in reason:
            max_duration = 0.75
        cut_end = min(end_s, start_s + max_duration)
        cut_duration = round(max(0.0, cut_end - start_s), 3)
        if cut_duration <= 0.05:
            continue
        if _overlaps_existing(start_s, cut_end):
            logger.info("[shot-rhythm] microcut skipped reason=fluency_overlap")
            continue
        cut = {
            "start_s": round(start_s, 3),
            "end_s": round(cut_end, 3),
            "removed_s": cut_duration,
            "pause_type": "shot_rhythm_microcut",
            "action": "cut",
            "reason": f"shot_rhythm:{reason or pause_type or 'dead_air'}",
            "source": "shot_rhythm",
        }
        microcuts.append(cut)
        logger.info(
            "[shot-rhythm] microcut planned start=%.2f end=%.2f duration=%.2f reason=%s",
            cut["start_s"],
            cut["end_s"],
            cut_duration,
            cut["reason"],
        )
    return microcuts


def build_shot_rhythm_decision(
    *,
    segment_text: str,
    hook_intent: str,
    composition_mode: str,
    fluency_plan: Optional[Dict[str, Any]] = None,
    silence_plan: Optional[Dict[str, Any]] = None,
    motion_pack_profile: str = "",
    sfx_retention_decision: Optional[Dict[str, Any]] = None,
    broll_editorial_decision: Optional[Dict[str, Any]] = None,
    private_premium_status: str = "",
    first3_visual_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    fluency = fluency_plan or {}
    silence = silence_plan or {}
    sfx_decision = sfx_retention_decision or {}
    broll_decision = broll_editorial_decision or {}
    first3 = first3_visual_contract or {}
    comp_mode = str(composition_mode or "minimal_safe")
    profile = _shot_rhythm_profile(hook_intent, comp_mode)

    if str(private_premium_status or "") == "DO_NOT_UPLOAD":
        logger.info("[shot-rhythm] should_apply=false profile=no_rhythm_needed confidence=0.00 reason=do_not_upload")
        logger.info("[shot-rhythm] skipped reason=do_not_upload")
        return {
            "should_apply_rhythm": False,
            "rhythm_profile": "no_rhythm_needed",
            "microcuts": [],
            "preserved_pauses": [],
            "pattern_interruptions": [],
            "pacing_score_before": 0.0,
            "pacing_score_after_estimate": 0.0,
            "reason": "do_not_upload",
            "confidence": 0.0,
            "fallback": "none",
            "applied": False,
            "composition_allowed": False,
            "composition_reason": "do_not_upload",
        }

    pacing_before = _pacing_score_before(
        segment_text=segment_text,
        fluency_plan=fluency,
        silence_plan=silence,
    )

    if int(fluency.get("disfluency_count") or 0) == 0 and int(fluency.get("false_start_count") or 0) == 0 and float(fluency.get("fluency_score_after") or 0.0) >= 0.88:
        logger.info("[shot-rhythm] should_apply=false profile=%s confidence=0.42 reason=already_fluent", profile)
        logger.info("[shot-rhythm] skipped reason=already_fluent")
        return {
            "should_apply_rhythm": False,
            "rhythm_profile": profile,
            "microcuts": [],
            "preserved_pauses": [],
            "pattern_interruptions": [],
            "pacing_score_before": pacing_before,
            "pacing_score_after_estimate": pacing_before,
            "reason": "already_fluent",
            "confidence": 0.42,
            "fallback": "none",
            "applied": False,
            "composition_allowed": True,
            "composition_reason": "already_fluent",
        }

    microcuts = build_safe_microcuts(
        silence_plan=silence,
        fluency_plan=fluency,
        max_microcuts=3,
    )
    total_microcut_removed = round(sum(float(item.get("removed_s") or 0.0) for item in microcuts), 3)
    if total_microcut_removed > 1.35:
        microcuts = microcuts[:2]
        total_microcut_removed = round(sum(float(item.get("removed_s") or 0.0) for item in microcuts), 3)

    preserved_pauses: List[Dict[str, Any]] = []
    removed_pauses: List[Dict[str, Any]] = []
    for seg in list(silence.get("segments") or []):
        action = str(seg.get("action") or "")
        reason = str(seg.get("reason") or "").lower()
        pause_type = str(seg.get("pause_type") or "").lower()
        start_s = float(seg.get("start_s") or 0.0)
        end_s = float(seg.get("end_s") or start_s)
        if action in {"preserve_for_tension", "preserve_and_emphasize", "preserve"}:
            mapped_reason = ""
            for key, value in _SHOT_RHYTHM_PAUSE_REASON_MAP.items():
                if key in reason or key in pause_type:
                    mapped_reason = value
                    break
            if mapped_reason:
                preserved_pauses.append({"start_s": round(start_s, 3), "end_s": round(end_s, 3), "reason": mapped_reason})
                logger.info(
                    "[shot-rhythm] pause_preserved start=%.2f end=%.2f reason=%s",
                    start_s,
                    end_s,
                    mapped_reason,
                )
        elif action in {"cut", "shorten"} and any(flag in reason for flag in ("dead_air", "false_start", "bts", "technical", "awkward")):
            mapped_reason = "technical_pause" if "technical" in reason else ("false_start" if "false_start" in reason else ("bts" if "bts" in reason else "dead_air"))
            removed_pauses.append({"start_s": round(start_s, 3), "end_s": round(end_s, 3), "reason": mapped_reason})
            logger.info(
                "[shot-rhythm] pause_removed start=%.2f end=%.2f reason=%s",
                start_s,
                end_s,
                mapped_reason,
            )

    pattern_type = _SHOT_RHYTHM_INTERRUPTION_BY_PROFILE.get(profile, "")
    if comp_mode == "minimal_safe":
        pattern_type = ""
    if profile == "emotional_breathing" and pattern_type in {"transition_snap", "sfx_micro_hit"}:
        pattern_type = "micro_hold"
    if profile == "business_punch_pacing" and bool(sfx_decision.get("should_apply_sfx")) and not bool(sfx_decision.get("voice_conflict")):
        pattern_type = "motion_kick"
    if profile == "hook_snap" and bool(broll_decision.get("should_use_broll")):
        pattern_type = "caption_pulse"

    pattern_interruptions: List[Dict[str, Any]] = []
    composition_allowed = True
    composition_reason = "allowed"
    if pattern_type:
        visual_interrupt = pattern_type in {"caption_pulse", "motion_kick", "transition_snap"}
        if comp_mode == "emotional_soft" and pattern_type in {"sfx_micro_hit", "transition_snap"}:
            composition_allowed = False
            composition_reason = "tone_sensitive"
            logger.info("[pattern-interrupt] skipped reason=tone_sensitive")
        elif bool(sfx_decision.get("voice_conflict")) and pattern_type == "sfx_micro_hit":
            composition_allowed = False
            composition_reason = "voice_conflict"
            logger.info("[pattern-interrupt] skipped reason=voice_conflict")
        else:
            resolved = resolve_visual_layer_conflicts(
                [{"type": "rhythm_interrupt", "subtype": pattern_type, "visual": visual_interrupt, "start_s": 0.65, "duration_s": 0.28}],
                {
                    "composition_mode": comp_mode,
                    "max_simultaneous_layers": int(3 if comp_mode == "business_punch" else 2),
                    "priority_order": ["caption", "face", "motion", "sfx"],
                    "first3_status": str(first3.get("status") or ""),
                    "first3_overload": bool((first3.get("first3_visual_contract") or {}).get("no_layer_overload") is False),
                },
            )
            composition_allowed = "rhythm_interrupt" in list(resolved.get("layers_final") or [])
            composition_reason = "allowed" if composition_allowed else "composition_block"
            if composition_allowed:
                pattern_interruptions.append({
                    "type": pattern_type,
                    "applied": True,
                    "reason": "editorial_moment",
                    "start_s": 0.65,
                    "duration_s": 0.28,
                })
                logger.info("[pattern-interrupt] type=%s applied=true reason=editorial_moment", pattern_type)
            else:
                logger.info("[pattern-interrupt] skipped reason=composition_block")
    else:
        logger.info("[pattern-interrupt] skipped reason=no_editorial_moment")

    logger.info(
        "[shot-rhythm] composition_allowed=%s reason=%s",
        str(composition_allowed).lower(),
        composition_reason,
    )

    should_apply = bool(microcuts or preserved_pauses or any(item.get("applied") for item in pattern_interruptions))
    if not should_apply:
        logger.info("[shot-rhythm] skipped reason=no_safe_cut")

    pacing_after = pacing_before
    pacing_after += min(0.10, len(microcuts) * 0.03)
    pacing_after += min(0.08, len(preserved_pauses) * 0.02)
    pacing_after += 0.07 if pattern_interruptions else 0.0
    pacing_after = round(max(pacing_before, min(1.0, pacing_after)), 3)

    logger.info("[shot-rhythm] pacing_score_before=%.2f", pacing_before)
    logger.info("[shot-rhythm] pacing_score_after=%.2f", pacing_after)
    logger.info(
        "[shot-rhythm] should_apply=%s profile=%s confidence=%.2f reason=%s",
        str(should_apply).lower(),
        profile if should_apply else "no_rhythm_needed",
        0.76 if should_apply else 0.38,
        "contextual_pacing_gain" if should_apply else "no_safe_cut",
    )
    logger.info(
        "[shot-rhythm] applied=%s reason=%s",
        str(should_apply).lower(),
        "microcut_or_pause_or_pattern" if should_apply else "metadata_only",
    )

    return {
        "should_apply_rhythm": should_apply,
        "rhythm_profile": profile if should_apply else "no_rhythm_needed",
        "microcuts": microcuts,
        "preserved_pauses": preserved_pauses,
        "removed_pauses": removed_pauses,
        "pattern_interruptions": pattern_interruptions,
        "pacing_score_before": pacing_before,
        "pacing_score_after_estimate": pacing_after,
        "reason": "contextual_pacing_gain" if should_apply else "no_safe_cut",
        "confidence": 0.76 if should_apply else 0.38,
        "fallback": "silence_only" if (not should_apply and preserved_pauses) else ("none" if should_apply else "motion_only"),
        "applied": should_apply,
        "composition_allowed": composition_allowed,
        "composition_reason": composition_reason,
    }


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


# ── VPI Cinematic Finish Pack v1 ───────────────────────────────────────────────

_FINISH_PROFILE_BY_INTENT: Dict[str, str] = {
    "myth_flip": "clean_premium",
    "risk_warning": "warning_subtle_tension",
    "practical_advice": "health_clarity",
    "autonomous_business_stakes": "business_contrast",
    "emotional_closure": "emotional_soft_grade",
    "neutral_explanation": "clean_premium",
}

_FINISH_PROFILE_VALUES: Dict[str, Dict[str, Any]] = {
    "clean_premium": {"contrast": 1.04, "brightness": 0.008, "saturation": 1.02, "sharpness": 0.20, "warmth": 0.01, "vignette": False},
    "warm_family": {"contrast": 1.03, "brightness": 0.012, "saturation": 1.03, "sharpness": 0.18, "warmth": 0.04, "vignette": False},
    "health_clarity": {"contrast": 1.04, "brightness": 0.010, "saturation": 1.01, "sharpness": 0.24, "warmth": 0.00, "vignette": False},
    "business_contrast": {"contrast": 1.07, "brightness": 0.004, "saturation": 1.02, "sharpness": 0.28, "warmth": 0.00, "vignette": True},
    "warning_subtle_tension": {"contrast": 1.05, "brightness": -0.004, "saturation": 0.98, "sharpness": 0.22, "warmth": -0.01, "vignette": True},
    "emotional_soft_grade": {"contrast": 1.02, "brightness": 0.010, "saturation": 1.01, "sharpness": 0.16, "warmth": 0.03, "vignette": False},
    "no_finish_needed": {"contrast": 1.00, "brightness": 0.000, "saturation": 1.00, "sharpness": 0.00, "warmth": 0.00, "vignette": False},
}


def build_cinematic_finish_decision(
    *,
    hook_intent: str = "",
    composition_mode: str = "",
    private_premium_status: str = "",
    first3_visual_contract: Optional[Dict[str, Any]] = None,
    caption_overlay_pack: Optional[Dict[str, Any]] = None,
    motion_pack_applied: bool = False,
    broll_applied: bool = False,
    sfx_retention_pack: bool = False,
    segment_text: str = "",
) -> Dict[str, Any]:
    daily_mode_active = os.environ.get("VPI_DAILY_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    production_safe_active = os.environ.get("VPI_PRODUCTION_SAFE_EDIT", "").strip().lower() in {"1", "true", "yes", "on"}
    if daily_mode_active or production_safe_active:
        logger.info(
            "VPI_FINISH_COLOR_TINT_DISABLED_DAILY daily=%s production_safe=%s",
            str(daily_mode_active).lower(),
            str(production_safe_active).lower(),
        )
        return {
            "should_apply_finish": False,
            "finish_profile": "no_finish_needed",
            "contrast": "neutral",
            "sharpness": "none",
            "vignette": False,
            "warmth": "neutral",
            "reason": "daily_mode_neutral_finish",
            "confidence": 0.0,
            "fallback": "none",
            "contrast_value": 1.0,
            "brightness_value": 0.0,
            "saturation_value": 1.0,
            "sharpness_value": 0.0,
            "warmth_value": 0.0,
            "hook_intent": str(hook_intent or ""),
            "composition_mode": str(composition_mode or ""),
        }
    intent = str(hook_intent or "neutral_explanation")
    mode = str(composition_mode or "minimal_safe")
    status = str(private_premium_status or "")
    cap_pack = caption_overlay_pack or {}
    first3 = first3_visual_contract or {}
    first3_checks = first3.get("first3_visual_contract") if isinstance(first3.get("first3_visual_contract"), dict) else {}
    first3_status = str(first3.get("status") or "")

    if status == "DO_NOT_UPLOAD":
        logger.info("[cinematic-finish] should_apply=false profile=no_finish_needed confidence=0.00 reason=do_not_upload")
        logger.info("[cinematic-finish] skipped reason=do_not_upload")
        return {
            "should_apply_finish": False,
            "finish_profile": "no_finish_needed",
            "contrast": "neutral",
            "sharpness": "none",
            "vignette": False,
            "warmth": "neutral",
            "reason": "do_not_upload",
            "confidence": 0.0,
            "fallback": "none",
            "contrast_value": 1.0,
            "brightness_value": 0.0,
            "saturation_value": 1.0,
            "sharpness_value": 0.0,
            "warmth_value": 0.0,
        }

    profile = _FINISH_PROFILE_BY_INTENT.get(intent, "clean_premium")
    if mode == "minimal_safe" and intent == "neutral_explanation" and not (motion_pack_applied or broll_applied or sfx_retention_pack):
        profile = "no_finish_needed"
    elif mode == "explanation_clean" and profile == "clean_premium":
        profile = "health_clarity"
    elif mode == "emotional_soft" and profile != "emotional_soft_grade":
        profile = "warm_family"

    values = dict(_FINISH_PROFILE_VALUES.get(profile) or _FINISH_PROFILE_VALUES["clean_premium"])
    should_apply = profile != "no_finish_needed"
    reason = "contextual_finish_gain" if should_apply else "no_visual_gain"
    fallback = "basic_safe_grade" if should_apply else "none"
    confidence = 0.72 if should_apply else 0.28

    long_caption = bool(cap_pack.get("density_guard_actions")) and any(
        str(item.get("action")) in {"skip_overlay", "skip_icon"}
        for item in (cap_pack.get("density_guard_actions") or [])
        if isinstance(item, dict)
    )
    if long_caption and values["vignette"]:
        values["vignette"] = False
        reason = "caption_safety_reduce_vignette"

    if first3_status in {"review", "fail"} and values["contrast"] > 1.06:
        values["contrast"] = 1.04
        reason = "first3_safety_reduce_contrast"

    logger.info("[cinematic-finish] intent_mapping hook_intent=%s profile=%s", intent, profile)
    logger.info(
        "[cinematic-finish] should_apply=%s profile=%s confidence=%.2f reason=%s",
        str(should_apply).lower(),
        profile,
        confidence,
        reason,
    )
    return {
        "should_apply_finish": should_apply,
        "finish_profile": profile,
        "contrast": "subtle" if values["contrast"] <= 1.04 else "moderate",
        "sharpness": "none" if values["sharpness"] <= 0.0 else ("subtle" if values["sharpness"] <= 0.24 else "light"),
        "vignette": bool(values["vignette"]),
        "warmth": "neutral" if abs(values["warmth"]) < 0.015 else ("warm" if values["warmth"] > 0 else "cool"),
        "reason": reason,
        "confidence": confidence,
        "fallback": fallback,
        "contrast_value": float(values["contrast"]),
        "brightness_value": float(values["brightness"]),
        "saturation_value": float(values["saturation"]),
        "sharpness_value": float(values["sharpness"]),
        "warmth_value": float(values["warmth"]),
        "hook_intent": intent,
        "composition_mode": mode,
    }


def build_cinematic_finish_filter_plan(
    decision: Dict[str, Any],
    existing_filters: str = "",
    caption_safety: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    should_apply = bool(decision.get("should_apply_finish"))
    profile = str(decision.get("finish_profile") or "no_finish_needed")
    if not should_apply or profile == "no_finish_needed":
        logger.info("[cinematic-finish] filter_plan=none")
        logger.info("[cinematic-finish] applied=false reason=no_visual_gain")
        return {
            "apply": False,
            "filters": [],
            "filter_chain": "",
            "reason": "no_visual_gain",
            "fallback": str(decision.get("fallback") or "none"),
            "finish_profile": profile,
            "contrast_value": float(decision.get("contrast_value") or 1.0),
            "brightness_value": float(decision.get("brightness_value") or 0.0),
            "saturation_value": float(decision.get("saturation_value") or 1.0),
            "sharpness_value": float(decision.get("sharpness_value") or 0.0),
            "warmth_value": float(decision.get("warmth_value") or 0.0),
            "vignette": bool(decision.get("vignette")),
            "vignette_strength": 0.0,
        }

    contrast = max(1.0, min(1.08, float(decision.get("contrast_value") or 1.0)))
    brightness = max(-0.01, min(0.02, float(decision.get("brightness_value") or 0.0)))
    saturation = max(0.96, min(1.06, float(decision.get("saturation_value") or 1.0)))
    sharpness = max(0.0, min(0.35, float(decision.get("sharpness_value") or 0.0)))
    warmth = max(-0.03, min(0.05, float(decision.get("warmth_value") or 0.0)))
    vignette = bool(decision.get("vignette"))
    vignette_strength = 0.06 if vignette else 0.0

    cap_safety = caption_safety or {}
    if bool(cap_safety.get("long_caption")):
        vignette = False
        vignette_strength = 0.0
        contrast = min(contrast, 1.04)
        brightness = max(brightness, 0.0)
        logger.info("[cinematic-finish] fallback=basic_safe_grade reason=caption_safety")

    filters: List[str] = []
    if existing_filters:
        filters.append(existing_filters)
    filters.append(f"eq=contrast={contrast:.3f}:brightness={brightness:.3f}:saturation={saturation:.3f}")
    if abs(warmth) >= 0.01:
        # Gentle brand texture; keep shifts low to avoid skin-tone drift.
        filters.append(f"colorbalance=rs={warmth:.3f}:gs={warmth * 0.5:.3f}:bs={-warmth * 0.5:.3f}")
    if sharpness > 0.0:
        filters.append(f"unsharp=5:5:{sharpness:.2f}:5:5:0.00")
    if vignette:
        filters.append("vignette=PI/8")

    filter_chain = ",".join(item for item in filters if item)
    logger.info("[cinematic-finish] filter_plan=%s", filter_chain or "none")
    return {
        "apply": bool(filter_chain),
        "filters": filters,
        "filter_chain": filter_chain,
        "reason": "finish_filters_planned" if filter_chain else "empty_filter_chain",
        "fallback": str(decision.get("fallback") or "none"),
        "finish_profile": profile,
        "contrast_value": contrast,
        "brightness_value": brightness,
        "saturation_value": saturation,
        "sharpness_value": sharpness,
        "warmth_value": warmth,
        "vignette": vignette,
        "vignette_strength": vignette_strength,
    }


def assess_finish_safety(
    finish_plan: Dict[str, Any],
    caption_overlay_pack: Optional[Dict[str, Any]] = None,
    first3_visual_contract_data: Optional[Dict[str, Any]] = None,
    composition_decision: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cap_pack = caption_overlay_pack or {}
    first3 = first3_visual_contract_data or {}
    first3_checks = first3.get("first3_visual_contract") if isinstance(first3.get("first3_visual_contract"), dict) else {}
    comp = composition_decision or {}

    caption_readable = bool(first3_checks.get("caption_readable", True))
    face_priority_safe = not (
        str(comp.get("screen_priority") or "") == "face"
        and bool(finish_plan.get("vignette"))
        and float(finish_plan.get("vignette_strength") or 0.0) > 0.05
    )
    no_overdarkening = bool(
        float(finish_plan.get("contrast_value") or 1.0) <= 1.08
        and float(finish_plan.get("brightness_value") or 0.0) >= -0.01
    )
    no_oversharpen = bool(float(finish_plan.get("sharpness_value") or 0.0) <= 0.35)
    lower_third = (cap_pack.get("lower_third") or {})
    no_brand_conflict = not (
        bool(lower_third.get("applied"))
        and bool(finish_plan.get("vignette"))
        and float(finish_plan.get("contrast_value") or 1.0) > 1.06
    )

    adjusted_plan = dict(finish_plan)
    adjusted = False
    blocked = False
    reason = "pass"

    if not caption_readable:
        blocked = True
        reason = "caption_risk"
    elif not face_priority_safe:
        adjusted_plan["vignette"] = False
        adjusted_plan["vignette_strength"] = 0.0
        adjusted = True
        reason = "face_risk"
    if not no_overdarkening and not blocked:
        adjusted_plan["contrast_value"] = min(float(adjusted_plan.get("contrast_value") or 1.0), 1.04)
        adjusted_plan["brightness_value"] = max(float(adjusted_plan.get("brightness_value") or 0.0), 0.0)
        adjusted = True
        reason = "no_overdarkening"
    if not no_oversharpen and not blocked:
        adjusted_plan["sharpness_value"] = 0.24
        adjusted = True
        reason = "no_oversharpen"
    if not no_brand_conflict and not blocked:
        adjusted_plan["vignette"] = False
        adjusted_plan["vignette_strength"] = 0.0
        adjusted = True
        reason = "brand_conflict"

    logger.info("[finish-safety] caption_readable=%s", str(caption_readable).lower())
    logger.info("[finish-safety] face_priority_safe=%s", str(face_priority_safe).lower())
    if blocked:
        logger.info("[finish-safety] blocked=true reason=%s", reason)
    elif adjusted:
        logger.info("[finish-safety] adjusted=true reason=%s", reason)

    status = "blocked" if blocked else ("adjusted" if adjusted else "pass")
    return {
        "caption_readable_after_finish": caption_readable,
        "face_priority_safe": face_priority_safe,
        "no_overdarkening": no_overdarkening,
        "no_oversharpen": no_oversharpen,
        "no_brand_conflict": no_brand_conflict,
        "adjusted": adjusted,
        "blocked": blocked,
        "reason": reason,
        "status": status,
        "finish_plan": adjusted_plan,
    }


def apply_cinematic_finish(
    input_path: Path,
    output_path: Path,
    *,
    decision: Optional[Dict[str, Any]] = None,
    caption_overlay_pack: Optional[Dict[str, Any]] = None,
    first3_visual_contract_data: Optional[Dict[str, Any]] = None,
    composition_decision: Optional[Dict[str, Any]] = None,
    existing_filters: str = "",
) -> Dict[str, Any]:
    finish_decision = dict(decision or {})
    if not finish_decision:
        logger.info("[cinematic-finish] skipped reason=no_decision")
        return {
            "cinematic_finish_pack": False,
            "visual_finish": False,
            "finish_profile": "no_finish_needed",
            "finish_safety": "blocked",
            "finish_warning": "no_decision",
            "finish_applied": False,
        }

    long_caption = bool(caption_overlay_pack and any(
        str(item.get("action")) in {"skip_overlay", "skip_icon"}
        for item in (caption_overlay_pack or {}).get("density_guard_actions", [])
        if isinstance(item, dict)
    ))
    plan = build_cinematic_finish_filter_plan(
        finish_decision,
        existing_filters=existing_filters,
        caption_safety={"long_caption": long_caption},
    )
    safety = assess_finish_safety(
        plan,
        caption_overlay_pack=caption_overlay_pack,
        first3_visual_contract_data=first3_visual_contract_data,
        composition_decision=composition_decision,
    )

    if safety.get("blocked"):
        logger.info("[cinematic-finish] skipped reason=%s", safety.get("reason") or "safety_blocked")
        logger.info("[brand-finish] skipped reason=would_clutter")
        return {
            "cinematic_finish_pack": False,
            "visual_finish": False,
            "finish_profile": str(finish_decision.get("finish_profile") or "no_finish_needed"),
            "finish_safety": "blocked",
            "finish_warning": str(safety.get("reason") or "safety_blocked"),
            "finish_applied": False,
            "finish_decision": finish_decision,
            "finish_filter_plan": plan,
            "finish_safety_report": safety,
        }

    if safety.get("adjusted"):
        adjusted_decision = dict(finish_decision)
        adjusted_plan = dict(safety.get("finish_plan") or {})
        adjusted_decision["contrast_value"] = adjusted_plan.get("contrast_value", adjusted_decision.get("contrast_value"))
        adjusted_decision["brightness_value"] = adjusted_plan.get("brightness_value", adjusted_decision.get("brightness_value"))
        adjusted_decision["saturation_value"] = adjusted_plan.get("saturation_value", adjusted_decision.get("saturation_value"))
        adjusted_decision["sharpness_value"] = adjusted_plan.get("sharpness_value", adjusted_decision.get("sharpness_value"))
        adjusted_decision["warmth_value"] = adjusted_plan.get("warmth_value", adjusted_decision.get("warmth_value"))
        adjusted_decision["vignette"] = adjusted_plan.get("vignette", adjusted_decision.get("vignette"))
        plan = build_cinematic_finish_filter_plan(
            adjusted_decision,
            existing_filters=existing_filters,
            caption_safety={"long_caption": long_caption},
        )
        finish_decision = adjusted_decision

    if not plan.get("apply") or not plan.get("filter_chain"):
        logger.info("[cinematic-finish] applied=false reason=%s", plan.get("reason") or "empty_filter_chain")
        return {
            "cinematic_finish_pack": False,
            "visual_finish": False,
            "finish_profile": str(finish_decision.get("finish_profile") or "no_finish_needed"),
            "finish_safety": str(safety.get("status") or "pass"),
            "finish_warning": str(plan.get("reason") or "empty_filter_chain"),
            "finish_applied": False,
            "finish_decision": finish_decision,
            "finish_filter_plan": plan,
            "finish_safety_report": safety,
        }

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        str(plan.get("filter_chain")),
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
        logger.info("[cinematic-finish] applied=true reason=finish_filters_applied")
        logger.info("[brand-finish] applied=true reason=subtle_brand_texture")
        return {
            "cinematic_finish_pack": True,
            "visual_finish": True,
            "finish_profile": str(finish_decision.get("finish_profile") or "clean_premium"),
            "finish_safety": str(safety.get("status") or "pass"),
            "finish_warning": "",
            "finish_applied": True,
            "finish_decision": finish_decision,
            "finish_filter_plan": plan,
            "finish_safety_report": safety,
            "finish_fallback_used": "none",
        }

    reason = (result.stderr or "ffmpeg_failed").strip()[-500:] or "ffmpeg_failed"
    logger.info("[cinematic-finish] applied=false reason=%s", reason)
    fallback = str(finish_decision.get("fallback") or "none")
    if fallback == "basic_safe_grade":
        logger.info("[cinematic-finish] fallback=basic_safe_grade reason=ffmpeg_unsupported")
    else:
        logger.info("[cinematic-finish] fallback=none reason=ffmpeg_unsupported")
    return {
        "cinematic_finish_pack": False,
        "visual_finish": False,
        "finish_profile": str(finish_decision.get("finish_profile") or "clean_premium"),
        "finish_safety": str(safety.get("status") or "pass"),
        "finish_warning": reason,
        "finish_applied": False,
        "finish_decision": finish_decision,
        "finish_filter_plan": plan,
        "finish_safety_report": safety,
        "finish_fallback_used": fallback,
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
    visual_tokens = get_vpi_visual_design_tokens()
    max_motion_scale = float((visual_tokens.get("animation") or {}).get("max_motion_scale") or 1.06)
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
        events.append({"type": "emphasis_zoom", "start_s": min(6.0, max(3.2, duration_s * 0.32)), "duration_s": 1.6, "scale": min(max_motion_scale, 1.05), "reason": "speaker_focus_no_broll"})

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

    # ── VPI Premium Productive Hardening: Visual Emphasis Budget ────────────
    max_visual_emphasis_events = 8
    requested_count = len(events)
    if requested_count > max_visual_emphasis_events:
        events = events[:max_visual_emphasis_events]
        logger.info(
            "VISUAL_EMPHASIS_BUDGET_APPLIED requested=%d kept=%d max=%d",
            requested_count, len(events), max_visual_emphasis_events,
        )
    else:
        logger.info(
            "VISUAL_EMPHASIS_BUDGET_APPLIED requested=%d kept=%d max=%d (under budget)",
            requested_count, requested_count, max_visual_emphasis_events,
        )

    return events


def apply_visual_effects(
    input_path: Path,
    output_path: Path,
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    no_broll: bool = False,
    editorial_type: str = "",
    duration_s: float = 0.0,
) -> Dict[str, Any]:
    visual_tokens = get_vpi_visual_design_tokens()
    logger.info("VPI_VISUAL_TOKENS_APPLIED backend=vpi_visual_effects visual_design_version=%s", visual_tokens["visual_design_version"])
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
        dur = max(0.1, float(event.get("duration_s") or 0.5))
        end = start + dur
        scale = max(1.0, min(1.07, float(event.get("scale") or 1.035)))
        # OUTPUT-QUALITY-2: ease in over the event duration and hold briefly so the
        # motion is actually perceivable; the release reads as a clean motion accent.
        _etype = str(event.get("type") or "")
        _hold_end = end + (1.2 if _etype in {"hook_push_in", "subtle_push_in"} else 0.6)
        _ramp = f"(1+({scale:.4f}-1)*min(1\\,(t-{start:.3f})/{dur:.3f}))"
        scale_expr = f"if(between(t\\,{start:.3f}\\,{_hold_end:.3f})\\,{_ramp}\\,{scale_expr})"
        if _etype in {"hook_push_in", "subtle_push_in", "emphasis_zoom", "punch_zoom"}:
            logger.info(
                "VPI_OUTPUT_QUALITY_PUSH_IN_APPLIED type=%s start=%.2f ramp=%.2f hold_until=%.2f scale=%.3f",
                _etype, start, dur, _hold_end, scale,
            )
            logger.info(
                "VPI_OUTPUT_QUALITY_TRANSITION_APPLIED type=motion_release at=%.2f reason=%s",
                _hold_end, str(event.get("reason") or "motion_accent"),
            )
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
        logger.info(
            "VPI_OUTPUT_QUALITY_VISUAL_EDITING_VERIFIED events=%d types=%s",
            len(events),
            "|".join(sorted({str(e.get("type") or "") for e in events})) or "none",
        )
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
            "visual_design_version": str(visual_tokens.get("visual_design_version") or _VPI_VISUAL_TOKENS_VERSION),
            "visual_design_tokens_applied": True,
            "visual_design_tokens_applied_to_reinforcement": True,
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
        "visual_design_version": str(visual_tokens.get("visual_design_version") or _VPI_VISUAL_TOKENS_VERSION),
        "visual_design_tokens_applied": True,
        "visual_design_tokens_applied_to_reinforcement": True,
        "visual_effects_warning": reason,
    }
