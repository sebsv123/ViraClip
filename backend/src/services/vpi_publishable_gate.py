"""
VPI Publishable Gate v3.1 — Beta Clean clip publishability classification.

Deterministic, local-only heuristic engine that classifies each rendered clip
into one of four publishability statuses:

    READY_TO_UPLOAD  — safe to publish as-is
    REVIEW_MANUALLY  — minor issues, human should check
    NEEDS_FIX        — significant issues, needs rework before upload
    DO_NOT_UPLOAD    — forbidden content detected, must not be published

Input data is gathered from the existing VPI pipeline outputs:
  - segment metadata (editorial_type, vpi_score, matched_patterns)
  - hook_plan (hook_type, hook_first_4s_score, low_publish_priority)
  - editing_activity_score (from editing_plan)
  - broll metadata (categories, asset paths, forbidden detection)
  - output_qc (ClipQualityReport)
  - audio_qc (from audio mastering)
  - silence_plan (SilenceEditPlan)
  - captions/branding status
  - editorial_type
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PublishableStatus(str, Enum):
    """Publishability classification for a single clip."""
    READY_TO_UPLOAD = "ready_to_upload"
    REVIEW_MANUALLY = "review_manually"
    NEEDS_FIX = "needs_fix"
    DO_NOT_UPLOAD = "do_not_upload"


class UploadRecommendation(str, Enum):
    """Upload recommendation after ranking across all clips."""
    BEST_CANDIDATE = "best_candidate"
    GOOD_CANDIDATE = "good_candidate"
    REVIEW_BEFORE_UPLOAD = "review_before_upload"
    DISCARD_RECOMMENDED = "discard_recommended"


@dataclass
class PublishableGateResult:
    """Complete publishability assessment for one clip."""
    publishable_status: PublishableStatus
    publishable_score: float          # 0-100 numeric score
    publishable_reasons: List[str]    # why this status was assigned
    publishable_warnings: List[str]   # non-blocking concerns
    upload_recommendation: UploadRecommendation = UploadRecommendation.REVIEW_BEFORE_UPLOAD
    best_candidate: bool = False
    discard_recommended: bool = False
    weak_intro_detected: bool = False
    generic_broll_detected: bool = False
    forbidden_broll_detected: bool = False
    editing_activity_ok: bool = True
    hook_first_4s_ok: bool = True
    technical_qc_ok: bool = True
    audio_qc_ok: bool = True
    silence_ok: bool = True
    captions_ok: bool = True
    branding_ok: bool = True
    missing_editing_layers: List[str] = field(default_factory=list)
    recommended_next_fix: str = ""
    retention_quality_score: int = 0
    retention_quality_status: str = ""
    retention_missing_layers: List[str] = field(default_factory=list)
    private_premium_status: str = ""
    private_premium_editorial_quality: str = ""
    private_premium_postproduction_richness: str = ""
    private_premium_limited_assets: bool = False

    # ── FASE 5: Editorial Fluency fields ──────────────────────────────────
    editorial_fluency_ok: bool = True
    editorial_fluency_score: float = 0.0
    complete_idea_score: float = 0.0
    fluency_score_after: float = 0.0
    hook_fit_acceptable: bool = False
    editorial_fluency_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "publishable_status": self.publishable_status.value,
            "publishable_score": self.publishable_score,
            "publishable_reasons": self.publishable_reasons,
            "publishable_warnings": self.publishable_warnings,
            "upload_recommendation": self.upload_recommendation.value,
            "best_candidate": self.best_candidate,
            "discard_recommended": self.discard_recommended,
            "weak_intro_detected": self.weak_intro_detected,
            "generic_broll_detected": self.generic_broll_detected,
            "forbidden_broll_detected": self.forbidden_broll_detected,
            "editing_activity_ok": self.editing_activity_ok,
            "hook_first_4s_ok": self.hook_first_4s_ok,
            "technical_qc_ok": self.technical_qc_ok,
            "audio_qc_ok": self.audio_qc_ok,
            "silence_ok": self.silence_ok,
            "captions_ok": self.captions_ok,
            "branding_ok": self.branding_ok,
            "missing_editing_layers": self.missing_editing_layers,
            "recommended_next_fix": self.recommended_next_fix,
            "retention_quality_score": self.retention_quality_score,
            "retention_quality_status": self.retention_quality_status,
            "retention_missing_layers": self.retention_missing_layers,
            "private_premium_status": self.private_premium_status,
            "private_premium_editorial_quality": self.private_premium_editorial_quality,
            "private_premium_postproduction_richness": self.private_premium_postproduction_richness,
            "private_premium_limited_assets": self.private_premium_limited_assets,
            "editorial_fluency_ok": self.editorial_fluency_ok,
            "editorial_fluency_score": self.editorial_fluency_score,
            "complete_idea_score": self.complete_idea_score,
            "fluency_score_after": self.fluency_score_after,
            "hook_fit_acceptable": self.hook_fit_acceptable,
            "editorial_fluency_warnings": self.editorial_fluency_warnings,
        }


# ── Threshold constants ──────────────────────────────────────────────────────

# Editing activity: number of editorial actions applied (reframe, broll, hook,
# silence, captions, branding).  >= 6 → good activity.
EDITING_ACTIVITY_READY_THRESHOLD = 6
EDITING_ACTIVITY_NEEDS_FIX_THRESHOLD = 5

# Hook first 4s score (0-5).  >= 2 → acceptable hook presence.
HOOK_FIRST_4S_MIN_SCORE = 2

# Minimum publishable score thresholds for each status.
SCORE_READY_MIN = 70.0
SCORE_REVIEW_MIN = 40.0
SCORE_NEEDS_FIX_MIN = 20.0

# B-roll generic penalty when documents_admin is used with emotional editorial.
BROLL_GENERIC_DOCUMENTS_PENALTY = 25.0

# No-B-roll penalty when speaker is the focus (no penalty for talking-head).
NO_BROLL_SPEAKER_PENALTY = 0.0

# Weak intro base penalty.
WEAK_INTRO_PENALTY = 30.0


def assess_retention_quality(clip_info: Dict[str, Any]) -> Dict[str, Any]:
    editing_plan = clip_info.get("editing_plan") or {}
    hook_plan = clip_info.get("hook_plan") or editing_plan.get("hook_plan") or {}
    music = clip_info.get("music") or editing_plan.get("music") or {}
    sfx = clip_info.get("sfx") or editing_plan.get("sfx") or {}
    visual = clip_info.get("visual_effects") or editing_plan.get("visual_effects") or {}
    transitions = clip_info.get("transitions") or editing_plan.get("transitions") or {}
    broll_items = clip_info.get("editorial_broll") or []
    silence = clip_info.get("silence_edit_plan") or editing_plan.get("silence_edit_plan") or {}
    caption_support = editing_plan.get("caption_visual_support_plan") or clip_info.get("caption_visual_support") or {}
    score = 0
    missing: List[str] = []

    hook_score = int(hook_plan.get("hook_first3_score") or hook_plan.get("hook_first3_retention_score") or 0)
    hook_status = str(hook_plan.get("hook_first3_status") or "")
    hook_strong = hook_score >= 5 and hook_status not in {"weak", "weak_intro"} and hook_plan.get("hook_type") != "weak_intro"
    if hook_strong:
        score += 2
    else:
        missing.append("strong_first3_hook")

    silence_summary = silence.get("summary") or {}
    if silence_summary.get("pattern_interruption_opportunities") or silence_summary.get("tension_silences_preserved"):
        score += 2
    else:
        missing.append("silence_pattern_interruption")

    tracks_found = int(music.get("music_tracks_found") or 0)
    music_verified = bool(music.get("music_final_verified"))
    if music_verified:
        score += 2
    elif tracks_found > 0:
        missing.append("music_final_verified")

    sfx_assets = sfx.get("sfx_assets_available") or {}
    sfx_assets_found = any(int(sfx_assets.get(key) or 0) > 0 for key in ("low_risers", "high_risers", "whooshes", "booms"))
    if sfx.get("sfx_final_verified") or sfx.get("sfx_applied"):
        score += 2
    elif sfx_assets_found:
        missing.append("sfx_design")

    if visual.get("visual_effects_final_verified") or visual.get("visual_effects_applied") or visual.get("motion_scaling_events"):
        score += 2
    else:
        missing.append("visual_effects")

    broll_useful = any((item or {}).get("reason") or (item or {}).get("semantic_score") for item in broll_items)
    abrupt_broll = any(
        not bool((item or {}).get("broll_transition_applied"))
        and (item or {}).get("transition_type") in {"", None, "none"}
        for item in broll_items
    )
    image_without_kenburns = any(
        bool((item or {}).get("is_image") or (item or {}).get("broll_is_image"))
        and not bool((item or {}).get("ken_burns_applied") or (item or {}).get("broll_ken_burns_applied"))
        for item in broll_items
    )
    if broll_items and broll_useful and not abrupt_broll and not image_without_kenburns:
        score += 2
    elif broll_items:
        missing.append("broll_transition_or_kenburns")

    if caption_support.get("caption_visual_support_applied") or caption_support.get("enabled"):
        score += 1
    if visual.get("frame_rhythm_applied") or editing_plan.get("frame_rhythm_applied"):
        score += 1
    else:
        missing.append("frame_rhythm")

    planned_transitions = bool(transitions.get("transition_events") or transitions.get("transition_plan"))
    final_transition = bool(transitions.get("final_output_uses_transition") or transitions.get("transitions_applied"))
    if planned_transitions and not final_transition:
        missing.append("premium_transition_final_verified")
    elif final_transition:
        score += 1

    if score <= 4:
        status = "poor"
    elif score <= 7:
        status = "acceptable"
    elif score <= 10:
        status = "good"
    else:
        status = "strong"
    if not (sfx.get("sfx_final_verified") or sfx.get("sfx_applied")):
        if sfx.get("sfx_warning") == "sfx_missing_worker_assets" and status == "strong":
            status = "good"
        elif sfx_assets_found and status in {"good", "strong"}:
            status = "acceptable"

    if "strong_first3_hook" in missing:
        next_fix = "strengthen_first3_hook"
    elif "music_final_verified" in missing:
        next_fix = "verify_music_final_mix"
    elif "sfx_design" in missing:
        next_fix = "apply_intentional_sfx"
    elif "visual_effects" in missing:
        next_fix = "apply_intentional_visual_effect"
    elif "broll_transition_or_kenburns" in missing:
        next_fix = "fix_broll_transition_or_kenburns"
    else:
        next_fix = "manual_review"
    logger.info("[retention-gate] score=%d status=%s missing=%s", score, status, "|".join(missing) or "none")
    return {
        "retention_quality_score": score,
        "retention_quality_status": status,
        "retention_missing_layers": missing,
        "recommended_next_fix": next_fix,
    }


def assess_private_premium_status(
    *,
    content_quality_reject: bool,
    complete_idea_score: float,
    fluency_score_after: float,
    hook_first3_ok: bool,
    hook_fit_acceptable: bool,
    tech_qc_ok: bool,
    audio_qc_ok: bool,
    captions_ok: bool,
    branding_ok: bool,
    silence_plan: Dict[str, Any],
    visual_effects_meta: Dict[str, Any],
    transitions_meta: Dict[str, Any],
    sfx_meta: Dict[str, Any],
    broll_items: List[Dict[str, Any]],
    editing_richness_status: str,
    editing_richness_warnings: List[str],
    first3_visual_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    visual_events = list(visual_effects_meta.get("visual_effects_events") or [])
    visual_quality = str(
        visual_effects_meta.get("visual_effect_quality")
        or visual_effects_meta.get("visual_effects_quality")
        or ""
    )
    has_premium_visual = bool(
        visual_quality == "premium_visual_effect"
        or any((event or {}).get("visual_effect_classification") == "premium_visual_effect" for event in visual_events)
    )
    has_basic_motion = bool(
        visual_quality == "basic_motion"
        or any((event or {}).get("visual_effect_classification") == "basic_motion" for event in visual_events)
    )
    contextual_transition = bool(
        transitions_meta.get("transition_contextual")
        or any((event or {}).get("contextual") for event in transitions_meta.get("transition_events") or [])
    )
    contextual_sfx = bool(
        sfx_meta.get("sfx_contextual")
        or any((event or {}).get("contextual") for event in (sfx_meta.get("sfx_design_events") or sfx_meta.get("sfx_events") or []))
    )
    meaningful_silence = bool(
        silence_plan.get("rendered")
        or float(silence_plan.get("total_removed_s") or 0.0) > 0.15
        or (silence_plan.get("summary") or {}).get("tension_silences_preserved")
    )
    has_broll = bool(broll_items)
    perceptible_editorial_action = bool(
        meaningful_silence
        or has_premium_visual
        or contextual_transition
        or contextual_sfx
        or has_broll
        or hook_first3_ok
    )
    broll_missing_opportunity = any(
        str(item) in {"broll_asset_missing_or_conflict", "broll_editorial_opportunity_unfulfilled"}
        for item in (editing_richness_warnings or [])
    )
    sfx_missing_opportunity = any(
        str(item) in {"sfx_editorial_opportunity_unfulfilled", "sfx_low_variation"}
        for item in (editing_richness_warnings or [])
    )
    limited_assets = (not has_broll and not has_premium_visual and not contextual_transition) or broll_missing_opportunity or sfx_missing_opportunity

    if has_broll or has_premium_visual or contextual_transition:
        richness = "rich" if contextual_sfx or visual_effects_meta.get("visual_effects_applied") else "moderate"
    elif has_basic_motion or contextual_sfx or meaningful_silence:
        richness = "moderate"
    else:
        richness = "limited"

    # ── CAMBIO 5: first3_visual_contract downgrade ──────────────────────────
    _first3_contract = first3_visual_contract or {}
    _first3_fail_count = int(_first3_contract.get("first3_visual_fail_count") or 0)
    _first3_contract_failed = _first3_fail_count >= 2

    if content_quality_reject:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "blocked_bts_or_low_speech"
        reason = "bts_contamination"
    elif complete_idea_score < 0.75:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "incomplete"
        reason = "incomplete_idea"
    elif fluency_score_after < 0.70:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "disfluent"
        reason = "visible_disfluency"
    elif not tech_qc_ok or not audio_qc_ok or not captions_ok:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "technical_blocked"
        reason = "technical_audio_or_caption_failure"
    elif not hook_first3_ok:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_hook"
        reason = "weak_hook"
    elif _first3_contract_failed:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_first3_visual_contract"
        reason = f"first3_visual_contract_failed:{_first3_fail_count}_failures"
    elif not perceptible_editorial_action:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_editorial_action"
        reason = "no_perceptible_editorial_action"
    elif limited_assets:
        status = "PRIVATE_PREMIUM_LIMITED_ASSETS"
        editorial_quality = "solid"
        reason = "limited_assets"
    else:
        status = "PRIVATE_PREMIUM_READY"
        editorial_quality = "solid"
        reason = "complete_fluent_contextual_hook"

    if editing_richness_status == "rich" and (
        complete_idea_score < 0.75
        or (not hook_first3_ok and not hook_fit_acceptable)
        or ("visually_too_plain" in editing_richness_warnings)
        or (limited_assets and not has_premium_visual)
    ):
        logger.info("[quality-gate] rich_blocked reason=private_premium_honesty")

    if status == "PRIVATE_PREMIUM_READY":
        logger.info("[quality-gate] ready reason=%s", reason)
    elif status == "PRIVATE_PREMIUM_REVIEW":
        logger.info("[quality-gate] review reason=%s", reason)

    logger.info("[private-premium] status=%s", status)
    logger.info("[private-premium] editorial_quality=%s", editorial_quality)
    logger.info("[private-premium] postproduction_richness=%s", richness)
    logger.info("[private-premium] limited_assets=%s", str(limited_assets).lower())
    if broll_missing_opportunity:
        logger.info("[private-premium] limited_assets=true reason=broll_asset_missing")
    elif sfx_missing_opportunity:
        logger.info("[private-premium] limited_assets=true reason=sfx_asset_missing_or_low_variation")
    return {
        "private_premium_status": status,
        "private_premium_editorial_quality": editorial_quality,
        "private_premium_postproduction_richness": richness,
        "private_premium_limited_assets": limited_assets,
        "private_premium_reason": reason,
        "private_premium_perceptible_editorial_action": perceptible_editorial_action,
    }


def _count_editing_activities(clip_info: Dict[str, Any]) -> int:
    """Count how many editorial activities were applied to this clip.

    Activities counted:
      - reframe applied
      - broll applied (at least one editorial_broll item)
      - hook overlay rendered
      - silence edit applied (cuts > 0)
      - captions rendered
      - branding applied
    """
    count = 0
    editing_plan = clip_info.get("editing_plan") or {}

    # Reframe
    if editing_plan.get("reframe_strategy") and editing_plan.get("reframe_strategy") != "none":
        count += 1

    # B-roll
    broll_items = clip_info.get("editorial_broll") or []
    if broll_items:
        count += 1

    visual_effects = clip_info.get("visual_effects") or editing_plan.get("visual_effects") or {}
    if visual_effects.get("visual_effects_applied"):
        count += 1

    # Hook overlay
    hook_plan = clip_info.get("hook_plan") or {}
    if hook_plan.get("rendered") or hook_plan.get("overlay_rendered"):
        count += 1

    # Silence edit
    silence_plan = clip_info.get("silence_edit_plan") or {}
    silence_summary = silence_plan.get("summary") or {}
    if silence_plan.get("enabled") and (silence_summary.get("total_cuts_applied", 0) > 0 or silence_plan.get("total_removed_s", 0) > 0):
        count += 1

    # Captions
    if clip_info.get("caption_source") or clip_info.get("words"):
        count += 1

    # Branding
    brand_treatment = clip_info.get("brand_treatment") or {}
    if brand_treatment.get("applied"):
        count += 1

    return count


def _detect_weak_intro(hook_plan: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Detect if the clip has a weak intro based on hook_plan signals."""
    if not hook_plan:
        return False, ["no_hook_plan_available"]

    reasons: List[str] = []
    is_weak = False

    hook_type = hook_plan.get("hook_type", "")
    low_priority = hook_plan.get("low_publish_priority", False)
    hook_first_4s = hook_plan.get("hook_first_4s_score", 0)

    if hook_type == "weak_intro":
        reasons.append(f"hook_type_is_weak_intro")
        is_weak = True

    if low_priority:
        reasons.append("low_publish_priority_flag")
        is_weak = True

    if hook_first_4s < HOOK_FIRST_4S_MIN_SCORE and hook_type != "weak_intro":
        reasons.append(f"hook_first_4s_score_{hook_first_4s}_below_min_{HOOK_FIRST_4S_MIN_SCORE}")
        is_weak = True

    if not hook_plan.get("hook_contract_satisfied", False):
        reasons.append("hook_contract_not_satisfied")
        is_weak = True

    return is_weak, reasons


def _detect_generic_broll(
    broll_items: List[Dict[str, Any]],
    editorial_type: str,
) -> Tuple[bool, List[str]]:
    """Detect if B-roll is generic/uninspired.

    Rules:
      - documents_admin category + emotional editorial_type → generic warning
      - No B-roll but speaker focus → no severe penalty (talking-head is fine)
    """
    if not broll_items:
        return False, ["no_broll_available_no_penalty_for_talking_head"]

    reasons: List[str] = []
    is_generic = False

    for item in broll_items:
        category = (item.get("cue_type") or item.get("category") or "").lower()
        asset_path = str(item.get("asset_path") or item.get("asset_url") or "")

        # documents_admin + emotional editorial → generic
        if category == "documents_admin" and editorial_type in (
            "emotional_protection", "client_objection", "risk_warning"
        ):
            reasons.append(
                f"documents_admin_broll_for_{editorial_type}_editorial: {asset_path}"
            )
            is_generic = True

        # Known generic assets (from VPI_ASSET_PENALTIES)
        if "documents_admin/03.jpg" in asset_path:
            reasons.append(f"known_generic_asset_documents_admin_03: {asset_path}")
            is_generic = True

    return is_generic, reasons


def _detect_forbidden_broll(
    broll_items: List[Dict[str, Any]],
    segment_text: str,
) -> Tuple[bool, List[str]]:
    """Detect forbidden B-roll using vpi_broll_intent.is_broll_asset_forbidden().

    Also checks the 'forbidden' flag directly on each broll item as a fallback.
    """
    if not broll_items:
        return False, []

    reasons: List[str] = []
    is_forbidden = False

    # First pass: check direct 'forbidden' flag on items
    for item in broll_items:
        if item.get("forbidden"):
            reason = item.get("forbidden_reason") or "flagged_as_forbidden"
            reasons.append(f"forbidden_flag_{reason}")
            is_forbidden = True

    # Second pass: use vpi_broll_intent if available
    try:
        from .vpi_broll_intent import is_broll_asset_forbidden
    except ImportError:
        if not is_forbidden:
            logger.warning("vpi_broll_intent not available, skipping forbidden broll check")
            reasons.append("vpi_broll_intent_not_available")
        return is_forbidden, reasons

    for item in broll_items:
        context = {
            "category": item.get("cue_type") or item.get("category"),
            "cue_type": item.get("cue_type"),
            "query": item.get("query"),
            "title": item.get("title"),
            "asset_id": item.get("asset_id"),
            "provider_video_id": item.get("provider_video_id"),
            "visual_fingerprint": item.get("visual_fingerprint"),
            "tags": item.get("tags", []),
            "metadata": item.get("metadata"),
            "intent_type": item.get("intent_type"),
        }
        forbidden, forbidden_reasons = is_broll_asset_forbidden(item, context)
        if forbidden:
            reasons.extend(forbidden_reasons)
            is_forbidden = True

    return is_forbidden, reasons


def _assess_technical_qc(output_qc: Optional[Dict[str, Any]]) -> Tuple[bool, float, List[str]]:
    """Assess technical quality from output_qc.

    Returns (passed, score_contribution, reasons).
    """
    if not output_qc:
        return True, 0.0, ["no_output_qc_available"]

    reasons: List[str] = []
    overall_score = output_qc.get("overall_score", 100.0)
    quality_level = output_qc.get("quality_level", "good")
    checks = output_qc.get("checks", [])
    passed = output_qc.get("passed", True)

    if not passed:
        reasons.append(f"output_qc_failed_overall_score_{overall_score}")
        return False, -20.0, reasons

    if quality_level in ("poor", "reject"):
        reasons.append(f"output_qc_quality_level_{quality_level}")
        return False, -30.0, reasons

    # Check individual checks
    for check in checks:
        if not check.get("passed", True):
            check_name = check.get("name", "unknown")
            reasons.append(f"qc_check_failed_{check_name}")

    return True, min(overall_score / 100.0 * 10.0, 10.0), reasons


def _assess_audio_qc(audio_qc: Optional[Dict[str, Any]]) -> Tuple[bool, float, List[str]]:
    """Assess audio quality.

    Returns (passed, score_contribution, reasons).
    """
    if not audio_qc:
        return True, 0.0, ["no_audio_qc_available"]

    reasons: List[str] = []
    voice_status = audio_qc.get("audio_voice_status") or audio_qc.get("voice_loudness_classification", "unknown")
    input_lufs = audio_qc.get("input_lufs")
    output_lufs = audio_qc.get("output_lufs")

    if voice_status == "too_low":
        reasons.append(f"audio_voice_too_low_lufs_{input_lufs}")
        return False, -15.0, reasons

    if voice_status == "clipping_risk":
        reasons.append(f"audio_clipping_risk_peak_{audio_qc.get('input_peak')}")
        return False, -10.0, reasons

    if voice_status == "slightly_low":
        reasons.append(f"audio_voice_slightly_low_lufs_{input_lufs}")
        return True, -5.0, reasons

    return True, 5.0, reasons


def _assess_silence_quality(silence_plan: Optional[Dict[str, Any]]) -> Tuple[bool, float, List[str]]:
    """Assess silence editing quality.

    Returns (passed, score_contribution, reasons).
    """
    if not silence_plan:
        return True, 0.0, ["no_silence_plan_available"]

    reasons: List[str] = []
    warnings = silence_plan.get("warnings", [])
    total_removed = silence_plan.get("total_removed_s", 0.0)

    if warnings:
        for w in warnings[:3]:
            reasons.append(f"silence_warning_{w}")

    # If silence editing removed too much (>40% of typical 30s clip), flag it
    if total_removed > 12.0:
        reasons.append(f"silence_excessive_removal_{total_removed}s")
        return False, -10.0, reasons

    return True, 5.0, reasons


def _assess_captions_branding(clip_info: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    """Assess captions and branding status.

    Returns (captions_ok, branding_ok, reasons).
    """
    reasons: List[str] = []
    captions_ok = True
    branding_ok = True

    # Captions check
    has_words = bool(clip_info.get("words"))
    has_caption_source = bool(clip_info.get("caption_source"))
    if not has_words and not has_caption_source:
        captions_ok = False
        reasons.append("no_captions_rendered")

    # Branding check
    brand_treatment = clip_info.get("brand_treatment") or {}
    if brand_treatment.get("error"):
        branding_ok = False
        reasons.append(f"branding_error_{brand_treatment.get('error')}")

    return captions_ok, branding_ok, reasons


def _compute_base_score(
    vpi_score: Optional[float],
    virality_score: Optional[float],
    editorial_type: str,
) -> float:
    """Compute base publishable score from VPI and virality scores."""
    vpi = float(vpi_score or 0.0)
    virality = float(virality_score or 0.0)

    # Base: weighted combination of VPI score and virality
    base = (vpi * 0.6) + (virality * 0.4)

    # Editorial type bonus
    editorial_bonus = {
        "risk_warning": 8.0,
        "myth_debunk": 6.0,
        "client_objection": 5.0,
        "actionable_advice": 4.0,
        "emotional_protection": 3.0,
        "coverage_explanation": 2.0,
        "revelation": 2.0,
        "generic": -5.0,
    }
    base += editorial_bonus.get(editorial_type, 0.0)

    return max(0.0, min(100.0, base))


def evaluate_clip_publishability(
    clip_info: Dict[str, Any],
    segment: Optional[Dict[str, Any]] = None,
    first3_visual_contract: Optional[Dict[str, Any]] = None,
) -> PublishableGateResult:
    """Evaluate a single clip's publishability.

    Args:
        clip_info: Dict with clip metadata (editing_plan, hook_plan,
                   editorial_broll, output_qc, silence_edit_plan,
                   brand_treatment, words, caption_source, etc.)
        segment: Optional segment dict with editorial metadata
                 (editorial_type, vpi_score, virality_score, etc.)
        first3_visual_contract: Optional result from first3_visual_contract()
                                used to downgrade private premium status.

    Returns:
        PublishableGateResult with full classification.
    """
    segment = segment or clip_info

    # ── 1. Gather input data ────────────────────────────────────────────────
    editorial_type = str(segment.get("editorial_type") or clip_info.get("editorial_type") or "generic")
    vpi_score = segment.get("vpi_score") or clip_info.get("vpi_score")
    virality_score = segment.get("virality_score") or clip_info.get("virality_score")
    hook_plan = clip_info.get("hook_plan") or {}
    broll_items = clip_info.get("editorial_broll") or []
    output_qc = clip_info.get("output_qc")
    audio_qc = clip_info.get("audio_qc")
    silence_plan = clip_info.get("silence_edit_plan")
    segment_text = str(segment.get("text") or clip_info.get("text") or "")
    if not segment_text and isinstance(clip_info.get("words"), list):
        segment_text = " ".join(
            str((word or {}).get("word") or "")
            for word in clip_info.get("words") or []
            if isinstance(word, dict)
        ).strip()
    editing_richness_score = int(
        clip_info.get("editing_richness_score")
        or (clip_info.get("editing_plan") or {}).get("editing_richness_score")
        or 0
    )
    editing_richness_status = str(
        clip_info.get("editing_richness_status")
        or (clip_info.get("editing_plan") or {}).get("editing_richness_status")
        or ""
    )
    editing_richness_warnings = list(
        clip_info.get("editing_richness_warnings")
        or (clip_info.get("editing_plan") or {}).get("editing_richness_warnings")
        or []
    )
    music_meta = clip_info.get("music") or (clip_info.get("editing_plan") or {}).get("music") or {}
    sfx_meta = clip_info.get("sfx") or (clip_info.get("editing_plan") or {}).get("sfx") or {}
    visual_effects_meta = clip_info.get("visual_effects") or (clip_info.get("editing_plan") or {}).get("visual_effects") or {}
    transitions_meta = clip_info.get("transitions") or (clip_info.get("editing_plan") or {}).get("transitions") or {}
    speaker_focus_meta = clip_info.get("speaker_focus") or (clip_info.get("editing_plan") or {}).get("speaker_focus") or {}
    no_broll_reason = (
        clip_info.get("broll_no_broll_reason")
        or (clip_info.get("editing_plan") or {}).get("broll_no_broll_reason")
    )
    hook_first3_ok = bool(
        hook_plan.get("hook_type") != "weak_intro"
        and str(hook_plan.get("hook_first3_status") or "") == "strong"
        and int(hook_plan.get("hook_first3_score") or 0) >= 5
        and bool(hook_plan.get("hook_first3_final_verified", hook_plan.get("hook_first3_perceptible")))
    )
    visual_final_verified = bool(visual_effects_meta.get("visual_effects_final_verified") or visual_effects_meta.get("visual_effects_applied"))
    music_required_missing = int((music_meta or {}).get("music_tracks_found") or 0) > 0 and not music_meta.get("music_final_verified")
    static_broll_without_kenburns = any(
        bool((item or {}).get("is_image") or (item or {}).get("broll_is_image"))
        and not bool((item or {}).get("ken_burns_applied") or (item or {}).get("broll_ken_burns_applied"))
        for item in broll_items
    )
    broll_cut_is_dry = any(
        not bool((item or {}).get("broll_transition_applied"))
        and not bool((item or {}).get("transition_type"))
        for item in broll_items
    )
    missing_layers: List[str] = []
    if not broll_items:
        missing_layers.append("broll")
    if not visual_final_verified:
        missing_layers.append("visual_effects")
    if not music_meta.get("music_applied"):
        missing_layers.append("music")
    if not sfx_meta.get("sfx_applied"):
        missing_layers.append("sfx")
    no_post_layers = all(layer in missing_layers for layer in ("broll", "visual_effects", "music", "sfx"))
    retention_gate = assess_retention_quality(clip_info)
    content_quality: Dict[str, Any] = {}
    try:
        from .vpi_retention_editing_service import evaluate_content_quality

        quality_source = dict(segment or {})
        if segment_text and not quality_source.get("text"):
            quality_source["text"] = segment_text
        content_quality = evaluate_content_quality(quality_source)
        clip_info.update(content_quality)
        segment.update(content_quality)
    except Exception as exc:
        logger.warning("[content-quality] gate_check_skipped reason=%s", exc)
        content_quality = {
            "content_quality_label": str(clip_info.get("content_quality_label") or ""),
            "content_quality_reason": str(clip_info.get("content_quality_reason") or ""),
        }
    content_quality_reject = (
        content_quality.get("content_quality_label") == "reject"
        or content_quality.get("content_quality_reason") == "behind_the_scenes_low_speech"
    )

    # ── 1.5. Assess editorial fluency (FASE 5) ──────────────────────────────
    editorial_fluency_ok = True
    editorial_fluency_score = 0.0
    complete_idea_score = 0.0
    fluency_score_after = 0.0
    hook_fit_acceptable = False
    editorial_fluency_warnings: List[str] = []
    try:
        from .vpi_editorial_fluency_service import assess_editorial_fluency

        fluency_result = assess_editorial_fluency(
            text=segment_text,
            editorial_type=editorial_type,
            hook_plan=hook_plan,
            silence_plan=silence_plan,
            duration_s=float(clip_info.get("duration_s") or 0.0),
        )
        editorial_fluency_score = float(fluency_result.get("editorial_fluency_score", 0.0))
        complete_idea_score = float(fluency_result.get("complete_idea_score", 0.0))
        fluency_score_after = float(fluency_result.get("fluency_score_after", 0.0))
        hook_fit_acceptable = bool(fluency_result.get("hook_fit", {}).get("hook_fit_acceptable", False))
        editorial_fluency_warnings = list(fluency_result.get("editorial_fluency_warnings", []))

        # Block conditions for READY_TO_UPLOAD
        if complete_idea_score < 0.75:
            editorial_fluency_ok = False
            editorial_fluency_warnings.append("incomplete_idea")
        if fluency_score_after < 0.70:
            editorial_fluency_ok = False
            if "low_fluency" not in editorial_fluency_warnings:
                editorial_fluency_warnings.append("low_fluency")
        hook_first3_score = int(hook_plan.get("hook_first3_score") or 0)
        if hook_first3_score < 5 and not hook_fit_acceptable:
            editorial_fluency_ok = False
            if "hook_fit_unacceptable" not in editorial_fluency_warnings:
                editorial_fluency_warnings.append("hook_fit_unacceptable")
        # Check for at least one perceptible editorial action
        fluency_plan = fluency_result.get("fluency_plan", {})
        edit_list = fluency_result.get("edit_decision_list", {})
        has_editorial_action = bool(
            fluency_plan.get("edits")
            or edit_list.get("decisions")
            or fluency_result.get("complete_idea_assessment") == "expanded"
        )
        if not has_editorial_action:
            editorial_fluency_ok = False
            if "no_editorial_action" not in editorial_fluency_warnings:
                editorial_fluency_warnings.append("no_editorial_action")
    except Exception as exc:
        logger.warning("[editorial-fluency] gate_check_skipped reason=%s", exc)
        editorial_fluency_ok = True  # don't block if service unavailable

    # ── 1.6. Weak hook gate (FASE 4) ─────────────────────────────────────────
    # If hook-first3 stays weak (< 5) and unresolved, force REVIEW_MANUALLY,
    # never READY, never rich.  Try before giving up: adjust start, subtitle
    # emphasis before 1.5s, micro pause/cut entry, visual contextual.
    hook_fit_unresolved = False
    hook_first3_score = int(hook_plan.get("hook_first3_score") or 0)
    if hook_first3_score < 5 and hook_plan.get("hook_type") != "weak_intro":
        try:
            from .vpi_hook_engine import is_weak_hook_unresolved, assess_hook_fit

            hook_fit_result = assess_hook_fit(
                text=segment_text,
                editorial_type=editorial_type,
                hook_type=str(hook_plan.get("hook_type") or ""),
                hook_plan=hook_plan,
            )
            if is_weak_hook_unresolved(hook_plan, hook_fit_result=hook_fit_result):
                hook_fit_unresolved = True
                logger.info(
                    "[hook-fit] status=weak_unresolved "
                    "score=%d intent=%s style=%s",
                    hook_first3_score,
                    hook_fit_result.get("intent", "unknown"),
                    hook_fit_result.get("style", "unknown"),
                )
                logger.info(
                    "[quality-gate] rich_blocked reason=weak_contextual_hook"
                )
                # Force editorial_fluency_ok to False to block READY
                editorial_fluency_ok = False
                if "hook_fit_unresolved" not in editorial_fluency_warnings:
                    editorial_fluency_warnings.append("hook_fit_unresolved")
        except Exception as exc:
            logger.warning("[hook-fit] gate_check_skipped reason=%s", exc)

    # ── 2. Compute editing activity score ───────────────────────────────────
    editing_activity = _count_editing_activities(clip_info)
    editing_activity_ok = editing_activity >= EDITING_ACTIVITY_READY_THRESHOLD

    # ── 3. Detect weak intro ────────────────────────────────────────────────
    is_weak_intro, weak_intro_reasons = _detect_weak_intro(hook_plan)

    # ── 4. Detect generic B-roll ────────────────────────────────────────────
    is_generic_broll, generic_broll_reasons = _detect_generic_broll(
        broll_items, editorial_type
    )

    # ── 5. Detect forbidden B-roll ──────────────────────────────────────────
    is_forbidden_broll, forbidden_broll_reasons = _detect_forbidden_broll(
        broll_items, segment_text
    )

    # ── 6. Assess technical QC ──────────────────────────────────────────────
    tech_qc_ok, tech_qc_score, tech_qc_reasons = _assess_technical_qc(output_qc)

    # ── 7. Assess audio QC ──────────────────────────────────────────────────
    audio_qc_ok, audio_qc_score, audio_qc_reasons = _assess_audio_qc(audio_qc)

    # ── 8. Assess silence quality ───────────────────────────────────────────
    silence_ok, silence_score, silence_reasons = _assess_silence_quality(silence_plan)

    # ── 9. Assess captions and branding ─────────────────────────────────────
    captions_ok, branding_ok, cb_reasons = _assess_captions_branding(clip_info)

    # ── 10. Compute base score ──────────────────────────────────────────────
    base_score = _compute_base_score(vpi_score, virality_score, editorial_type)

    # ── 11. Apply penalties ─────────────────────────────────────────────────
    total_penalty = 0.0
    status_reasons: List[str] = []
    warnings: List[str] = []

    # Forbidden B-roll → DO_NOT_UPLOAD (immediate)
    if is_forbidden_broll:
        for reason in forbidden_broll_reasons:
            status_reasons.append(f"forbidden_broll_{reason}")
        return PublishableGateResult(
            publishable_status=PublishableStatus.DO_NOT_UPLOAD,
            publishable_score=0.0,
            publishable_reasons=status_reasons,
            publishable_warnings=forbidden_broll_reasons,
            upload_recommendation=UploadRecommendation.DISCARD_RECOMMENDED,
            discard_recommended=True,
            forbidden_broll_detected=True,
            editing_activity_ok=editing_activity_ok,
            hook_first_4s_ok=(not is_weak_intro),
            technical_qc_ok=tech_qc_ok,
            audio_qc_ok=audio_qc_ok,
            silence_ok=silence_ok,
            captions_ok=captions_ok,
            branding_ok=branding_ok,
        )

    # Weak intro penalty
    if is_weak_intro:
        total_penalty += WEAK_INTRO_PENALTY
        for reason in weak_intro_reasons:
            status_reasons.append(f"weak_intro_{reason}")

    # Generic B-roll penalty
    if is_generic_broll:
        total_penalty += BROLL_GENERIC_DOCUMENTS_PENALTY
        for reason in generic_broll_reasons:
            warnings.append(f"generic_broll_{reason}")
    if content_quality_reject:
        total_penalty += 60.0
        reason = str(content_quality.get("content_quality_reason") or "content_quality_reject")
        status_reasons.append(f"content_quality_{reason}")
        warnings.append("behind_the_scenes_or_low_speech")

    # Editing activity penalty
    if editing_activity < EDITING_ACTIVITY_NEEDS_FIX_THRESHOLD:
        total_penalty += 20.0
        status_reasons.append(f"low_editing_activity_{editing_activity}")
    elif editing_activity < EDITING_ACTIVITY_READY_THRESHOLD:
        total_penalty += 10.0
        warnings.append(f"moderate_editing_activity_{editing_activity}")

    if editing_richness_status == "too_plain" or "visually_too_plain" in editing_richness_warnings:
        total_penalty += 15.0
        warnings.append("visually_too_plain")
        status_reasons.append(f"editing_richness_too_plain_{editing_richness_score}")
    elif editing_richness_status == "acceptable":
        warnings.append(f"editing_richness_acceptable_{editing_richness_score}")
    if music_meta.get("music_warning") == "missing_music_library":
        warnings.append("missing_music_library")
    if sfx_meta.get("sfx_warning") in {"missing_sfx_library", "missing_sfx_worker_assets"}:
        warnings.append(str(sfx_meta.get("sfx_warning")))
    if no_broll_reason:
        warnings.append(f"no_broll_reason_{no_broll_reason}")
    if speaker_focus_meta.get("speaker_focus_enhanced") and not broll_items:
        status_reasons.append("speaker_focus_preferred")
    if not hook_first3_ok and hook_plan.get("hook_type") != "weak_intro":
        total_penalty += 10.0
        warnings.append("weak_first_3_seconds")
        status_reasons.append("hook_first3_not_perceptible")
    if hook_plan.get("hook_type") != "weak_intro" and not visual_final_verified:
        total_penalty += 15.0
        warnings.append("visual_effects_planned_not_in_final")
        status_reasons.append("visual_effects_final_not_verified")
    if static_broll_without_kenburns:
        total_penalty += 20.0
        warnings.append("static_broll_without_kenburns")
        status_reasons.append("static_broll_without_kenburns")
    if broll_cut_is_dry:
        total_penalty += 15.0
        warnings.append("broll_cut_is_dry")
        status_reasons.append("broll_cut_is_dry")
    if no_post_layers:
        total_penalty += 10.0
        warnings.append("missing_editing_layers")
        status_reasons.append("no_post_production_layers_applied")
    if (transitions_meta.get("transition_events") or transitions_meta.get("transition_plan")) and not transitions_meta.get("final_output_uses_transition"):
        total_penalty += 15.0
        warnings.append("transition_planned_not_in_final")
        status_reasons.append("transition_planned_not_in_final")
    for transition_warning in transitions_meta.get("transition_warnings", []) or []:
        if transition_warning == "transition_failed_fallback_used" or "fallback" in str(transition_warning):
            warnings.append("transition_failed_fallback_used")
            total_penalty += 5.0
        elif transition_warning == "no_premium_transition_needed":
            warnings.append("no_premium_transition_needed")
        elif transition_warning:
            warnings.append(str(transition_warning))
    if retention_gate["retention_quality_status"] == "poor":
        total_penalty += 25.0
        status_reasons.append("retention_quality_poor")
    elif retention_gate["retention_quality_status"] == "acceptable":
        warnings.append("retention_quality_acceptable")
    if music_required_missing:
        total_penalty += 20.0
        status_reasons.append("music_tracks_found_but_not_final_verified")
        warnings.append("music_planned_not_in_final")
    if hook_plan.get("hook_type") == "weak_intro":
        status_reasons.append("weak_intro_never_ready")
    final_name = str(clip_info.get("filename") or clip_info.get("path") or "")
    marker_mismatches: List[str] = []
    if music_meta.get("music_applied") and "music_" not in final_name:
        marker_mismatches.append("music_marker_missing_or_false_positive")
    if sfx_meta.get("sfx_applied") and "sfx_" not in final_name:
        marker_mismatches.append("sfx_marker_missing_or_false_positive")
    if transitions_meta.get("transitions_applied") and "trans_" not in final_name:
        marker_mismatches.append("trans_marker_missing_or_false_positive")
    if visual_effects_meta.get("visual_effects_applied") and "vfx_" not in final_name:
        marker_mismatches.append("vfx_marker_missing_or_false_positive")
    if broll_items and "broll_" not in final_name:
        marker_mismatches.append("broll_marker_missing_or_false_positive")
    if not broll_items and "broll_" in final_name:
        marker_mismatches.append("broll_marker_false_positive")
    if marker_mismatches:
        total_penalty += 10.0
        warnings.extend(marker_mismatches)
        status_reasons.append("final_filename_contract_failed")

    # Technical QC penalties
    if not tech_qc_ok:
        total_penalty += abs(tech_qc_score)
        status_reasons.extend(tech_qc_reasons)

    # Audio QC penalties
    if not audio_qc_ok:
        total_penalty += abs(audio_qc_score)
        status_reasons.extend(audio_qc_reasons)
    elif audio_qc_score < 0:
        warnings.extend(audio_qc_reasons)

    # Silence penalties
    if not silence_ok:
        total_penalty += abs(silence_score)
        status_reasons.extend(silence_reasons)

    # Captions/branding warnings
    if not captions_ok:
        total_penalty += 10.0
        status_reasons.extend(cb_reasons)
    if not branding_ok:
        warnings.extend(cb_reasons)

    # ── 12. Compute final score ─────────────────────────────────────────────
    final_score = max(0.0, min(100.0, base_score - total_penalty))

    # ── 13. Classify status ─────────────────────────────────────────────────
    hook_first_4s_ok = True
    if is_weak_intro:
        hook_first_4s_ok = False

    if is_forbidden_broll:
        status = PublishableStatus.DO_NOT_UPLOAD
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED
    elif content_quality_reject:
        status = PublishableStatus.DO_NOT_UPLOAD
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED
        if "content_quality_rejected" not in status_reasons:
            status_reasons.append("content_quality_rejected")
    elif (
        final_score >= SCORE_READY_MIN
        and editing_activity_ok
        and not is_weak_intro
        and hook_first3_ok
        and visual_final_verified
        and not music_required_missing
        and not static_broll_without_kenburns
        and not broll_cut_is_dry
        and retention_gate["retention_quality_status"] in {"good", "strong"}
        and not ((transitions_meta.get("transition_events") or transitions_meta.get("transition_plan")) and not transitions_meta.get("final_output_uses_transition"))
        and not no_post_layers
        and editing_richness_status not in {"too_plain"}
        and "visually_too_plain" not in editing_richness_warnings
        and editorial_fluency_ok
    ):
        status = PublishableStatus.READY_TO_UPLOAD
        recommendation = UploadRecommendation.GOOD_CANDIDATE
        status_reasons.append("all_checks_passed")
    elif final_score >= SCORE_REVIEW_MIN and not is_weak_intro:
        status = PublishableStatus.REVIEW_MANUALLY
        recommendation = UploadRecommendation.REVIEW_BEFORE_UPLOAD
        if is_generic_broll:
            status_reasons.append("generic_broll_needs_review")
        if not editing_activity_ok:
            status_reasons.append("moderate_editing_activity_needs_review")
    elif final_score >= SCORE_NEEDS_FIX_MIN or is_weak_intro:
        status = PublishableStatus.NEEDS_FIX
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED if is_weak_intro else UploadRecommendation.REVIEW_BEFORE_UPLOAD
        if is_weak_intro:
            status_reasons.append("weak_intro_needs_fix")
        if final_score < SCORE_REVIEW_MIN:
            status_reasons.append(f"low_publishable_score_{final_score:.1f}")
    else:
        status = PublishableStatus.DO_NOT_UPLOAD
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED
        status_reasons.append(f"very_low_publishable_score_{final_score:.1f}")

    # Deduplicate reasons
    seen: set[str] = set()
    unique_reasons: List[str] = []
    for r in status_reasons:
        if r not in seen:
            unique_reasons.append(r)
            seen.add(r)

    if not hook_first3_ok:
        recommended_next_fix = "strengthen_first3_hook"
    elif retention_gate["retention_quality_status"] == "poor":
        recommended_next_fix = retention_gate["recommended_next_fix"]
    elif no_post_layers:
        recommended_next_fix = "apply_visual_effects_or_music"
    elif editing_richness_status == "too_plain":
        recommended_next_fix = "increase_editing_richness"
    else:
        recommended_next_fix = "manual_review"

    private_premium = assess_private_premium_status(
        content_quality_reject=content_quality_reject,
        complete_idea_score=complete_idea_score,
        fluency_score_after=fluency_score_after,
        hook_first3_ok=hook_first3_ok,
        hook_fit_acceptable=hook_fit_acceptable,
        tech_qc_ok=tech_qc_ok,
        audio_qc_ok=audio_qc_ok,
        captions_ok=captions_ok,
        branding_ok=branding_ok,
        silence_plan=silence_plan or {},
        visual_effects_meta=visual_effects_meta or {},
        transitions_meta=transitions_meta or {},
        sfx_meta=sfx_meta or {},
        broll_items=broll_items,
        editing_richness_status=editing_richness_status,
        editing_richness_warnings=editing_richness_warnings,
        first3_visual_contract=first3_visual_contract,
    )

    result = PublishableGateResult(
        publishable_status=status,
        publishable_score=round(final_score, 1),
        publishable_reasons=unique_reasons,
        publishable_warnings=warnings,
        upload_recommendation=recommendation,
        discard_recommended=(recommendation == UploadRecommendation.DISCARD_RECOMMENDED),
        weak_intro_detected=is_weak_intro,
        generic_broll_detected=is_generic_broll,
        forbidden_broll_detected=is_forbidden_broll,
        editing_activity_ok=editing_activity_ok,
        hook_first_4s_ok=hook_first_4s_ok,
        technical_qc_ok=tech_qc_ok,
        audio_qc_ok=audio_qc_ok,
        silence_ok=silence_ok,
        captions_ok=captions_ok,
        branding_ok=branding_ok,
        missing_editing_layers=list(dict.fromkeys([*missing_layers, *retention_gate["retention_missing_layers"]])),
        recommended_next_fix=recommended_next_fix,
        retention_quality_score=int(retention_gate["retention_quality_score"]),
        retention_quality_status=str(retention_gate["retention_quality_status"]),
        retention_missing_layers=list(retention_gate["retention_missing_layers"]),
        private_premium_status=str(private_premium["private_premium_status"]),
        private_premium_editorial_quality=str(private_premium["private_premium_editorial_quality"]),
        private_premium_postproduction_richness=str(private_premium["private_premium_postproduction_richness"]),
        private_premium_limited_assets=bool(private_premium["private_premium_limited_assets"]),
        # ── FASE 5: Editorial Fluency ──────────────────────────────────────
        editorial_fluency_ok=editorial_fluency_ok,
        editorial_fluency_score=round(editorial_fluency_score, 2),
        complete_idea_score=round(complete_idea_score, 2),
        fluency_score_after=round(fluency_score_after, 2),
        hook_fit_acceptable=hook_fit_acceptable,
        editorial_fluency_warnings=editorial_fluency_warnings,
    )
    logger.info("[publishable-gate] upload_recommendation=%s", result.upload_recommendation.value)
    return result


def rank_clips(
    clip_results: List[Tuple[int, Dict[str, Any], float]],
) -> List[Dict[str, Any]]:
    """Rank clips after render, marking best_candidate and discard_recommended.

    Args:
        clip_results: List of (index, clip_info_dict, elapsed_s) tuples,
                      same format as render_results in task_service.py.

    Returns:
        The same clip_info dicts with publishable gate metadata injected.
        Each dict gets:
          - publishable_status
          - publishable_score
          - publishable_reasons
          - publishable_warnings
          - upload_recommendation
          - best_candidate (True for the single best clip)
          - discard_recommended (True for clips that should not be uploaded)
    """
    evaluated: List[Tuple[int, Dict[str, Any], PublishableGateResult]] = []

    for idx, clip_info, elapsed in clip_results:
        if clip_info is None:
            continue

        result = evaluate_clip_publishability(clip_info)
        evaluated.append((idx, clip_info, result))

    if not evaluated:
        return []

    # Sort by publishable_score descending
    evaluated.sort(key=lambda x: x[2].publishable_score, reverse=True)

    # Mark best candidate (top scorer that is not DO_NOT_UPLOAD)
    best_found = False
    for idx, clip_info, result in evaluated:
        if not best_found and result.publishable_status != PublishableStatus.DO_NOT_UPLOAD:
            result.best_candidate = True
            result.upload_recommendation = UploadRecommendation.BEST_CANDIDATE
            best_found = True

    # Mark discard_recommended for weak/forbidden clips
    for idx, clip_info, result in evaluated:
        if result.publishable_status in (
            PublishableStatus.DO_NOT_UPLOAD,
            PublishableStatus.NEEDS_FIX,
        ):
            result.discard_recommended = True
            if result.upload_recommendation == UploadRecommendation.REVIEW_BEFORE_UPLOAD:
                result.upload_recommendation = UploadRecommendation.DISCARD_RECOMMENDED

    # Inject metadata back into clip_info dicts
    for idx, clip_info, result in evaluated:
        clip_info["publishable_status"] = result.publishable_status.value
        clip_info["publishable_score"] = result.publishable_score
        clip_info["publishable_reasons"] = result.publishable_reasons
        clip_info["publishable_warnings"] = result.publishable_warnings
        clip_info["upload_recommendation"] = result.upload_recommendation.value
        clip_info["best_candidate"] = result.best_candidate
        clip_info["discard_recommended"] = result.discard_recommended
        clip_info["missing_editing_layers"] = result.missing_editing_layers
        clip_info["recommended_next_fix"] = result.recommended_next_fix
        clip_info["publishable_gate"] = result.to_dict()

        # Also inject into editing_plan if present
        editing_plan = clip_info.get("editing_plan")
        if isinstance(editing_plan, dict):
            editing_plan["publishable_status"] = result.publishable_status.value
            editing_plan["publishable_score"] = result.publishable_score
            editing_plan["publishable_warnings"] = result.publishable_warnings
            editing_plan["upload_recommendation"] = result.upload_recommendation.value
            editing_plan["best_candidate"] = result.best_candidate
            editing_plan["discard_recommended"] = result.discard_recommended
            editing_plan["missing_editing_layers"] = result.missing_editing_layers
            editing_plan["recommended_next_fix"] = result.recommended_next_fix

    # Restore original order
    evaluated.sort(key=lambda x: x[0])
    return [ci for _, ci, _ in evaluated]
