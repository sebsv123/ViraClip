#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import sys
import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_editorial_fluency_service import (  # noqa: E402
    _parse_transcript_lines,
    assess_editorial_fluency,
    build_edit_decision_list,
    build_fluency_edit_plan,
    expand_to_nearest_complete_idea,
    score_complete_idea,
)
from src.services.vpi_hook_engine import (  # noqa: E402
    assess_hook_fit,
    choose_hook_style,
    classify_hook_intent,
    find_better_hook_start,
    is_weak_hook_unresolved,
)
from src.services.vpi_publishable_gate import evaluate_clip_publishability  # noqa: E402
from src.services.vpi_retention_editing_service import (  # noqa: E402
    build_clean_take_candidates,
    build_delivery_contract,
    evaluate_content_quality,
    filter_content_quality_candidates,
)
from src.services.vpi_visual_effects_service import (  # noqa: E402
    assess_finish_safety,
    build_cinematic_finish_decision,
    build_cinematic_finish_filter_plan,
    build_kickframe_rhythm,
    get_hook_motion_profile,
    plan_visual_effects,
)
from src.services.caption_service import plan_caption_overlay_pack  # noqa: E402
from src.services.vpi_broll_intent import (  # noqa: E402
    build_broll_editorial_decision,
    match_broll_asset,
)
from src.services.vpi_sfx_service import (  # noqa: E402
    build_sfx_retention_decision,
    match_sfx_asset,
)

logger = logging.getLogger("offline_editorial_eval")

REPORT_DIR = ROOT / "reports" / "editorial_eval"
MD_REPORT = REPORT_DIR / "latest_editorial_eval.md"
JSON_REPORT = REPORT_DIR / "latest_editorial_eval.json"


def _case_result(case: str, passed: bool, reason: str, actual: Dict[str, Any], expected: Dict[str, Any], category: str) -> Dict[str, Any]:
    status = "PASS" if passed else "FAIL"
    logger.info("[offline-eval] case=%s status=%s reason=%s", case, status, reason)
    return {
        "case": case,
        "category": category,
        "status": status,
        "passed": passed,
        "reason": reason,
        "expected": expected,
        "actual": actual,
    }


def _timestamped(lines: List[Tuple[float, float, str]]) -> str:
    def fmt(seconds: float) -> str:
        return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"

    return "\n".join(f"[{fmt(start)} - {fmt(end)}] {text}" for start, end, text in lines)


def case_a_decesos_bts() -> Dict[str, Any]:
    transcript = _timestamped([
        (0, 1, "Claro."),
        (1, 2, "Papá."),
        (2, 4, "Ok chéverísima."),
        (4, 5, "Ya sí."),
        (49, 54, "Hoy vengo a hablarte del seguro de decesos."),
        (54, 58, "Este seguro no va de miedo. Va de alivio para la familia."),
        (58, 64, "Existe para facilitar un momento difícil."),
        (64, 71, "Para que la familia no tenga que gestionar más de la cuenta."),
    ])
    bts_quality = evaluate_content_quality({
        "text": "Claro. Papá. Ok chéverísima. Ya sí.",
        "start_time": "00:00",
        "end_time": "00:05",
        "bts_contamination_ratio": 1.0,
        "useful_content_ratio": 0.0,
    })
    pool = build_clean_take_candidates(transcript, transcript_duration_s=72.0, num_clips=1)
    candidates = list(pool.get("segments") or [])
    clean = candidates[0] if candidates else {}
    hook = classify_hook_intent(str(clean.get("text") or ""), editorial_type="myth_debunk")
    idea = score_complete_idea(str(clean.get("text") or ""))
    passed = (
        bts_quality.get("content_quality_label") == "reject"
        and bool(clean)
        and str(clean.get("start_time")) >= "00:49"
        and hook.get("intent") == "myth_flip"
        and float(idea.get("complete_idea_score") or 0.0) >= 0.75
    )
    return _case_result(
        "A_decesos_bts_initial",
        passed,
        "BTS rejected, clean take starts at useful content, myth hook detected",
        {
            "bts_label": bts_quality.get("content_quality_label"),
            "clean_start": clean.get("start_time"),
            "hook_intent": hook.get("intent"),
            "complete_idea_score": idea.get("complete_idea_score"),
        },
        {"bts_label": "reject", "clean_start_gte": "00:49", "hook_intent": "myth_flip", "complete_idea": True},
        "complete_idea",
    )


def case_b_repetition_correction() -> Dict[str, Any]:
    transcript = _timestamped([
        (0, 2, "A veces pensamos que proteger."),
        (2, 3, "Ok."),
        (3, 8, "A veces pensamos que proteger es solo cubrir lo económico."),
        (8, 14, "Pero proteger también es facilitar y dejar menos carga."),
    ])
    lines = _parse_transcript_lines(transcript)
    plan = build_fluency_edit_plan(lines)
    removed = " ".join(str(edit.get("original_text") or "") for edit in plan.edits)
    kept_text = " ".join(line["text"] for idx, line in enumerate(lines) if all(not (edit.get("start_s") == line["start"] and edit.get("end_s") == line["end"]) for edit in plan.edits))
    passed = (
        plan.fluency_score_after > plan.fluency_score_before
        and plan.fluency_edit_applied
        and "Ok" in removed
        and "A veces pensamos que proteger es solo cubrir lo económico" in kept_text
    )
    return _case_result(
        "B_repetition_correction",
        passed,
        "fragment and filler removed, complete version kept, fluency improves",
        {
            "score_before": plan.fluency_score_before,
            "score_after": plan.fluency_score_after,
            "edits": plan.edits,
            "kept_text": kept_text,
        },
        {"score_after_gt_before": True, "remove": ["fragment", "Ok"], "keep_complete_version": True},
        "fluency",
    )


def case_c_salud_hook() -> Dict[str, Any]:
    text = "Tener un seguro de salud no es un postureo. Es organización. Para mucha gente un seguro de salud no es lujo, es orden."
    intent = classify_hook_intent(text, editorial_type="myth_debunk")
    style = choose_hook_style(str(intent.get("intent") or ""), text=text, editorial_type="myth_debunk")
    fit = assess_hook_fit(text, editorial_type="myth_debunk", hook_type="content")
    passed = (
        intent.get("intent") in {"myth_flip", "practical_advice"}
        and style.get("style") in {"calm_reveal", "clean_explanation"}
        and fit.get("hook_fit_acceptable") is True
    )
    return _case_result(
        "C_salud_hook_strong",
        passed,
        "health hook classified as contextual and acceptable",
        {"intent": intent, "style": style.get("style"), "fit": fit},
        {"intent_in": ["myth_flip", "practical_advice"], "style_in": ["calm_reveal", "clean_explanation"], "hook_acceptable": True},
        "hook_fit",
    )


def case_d_salud_warning() -> Dict[str, Any]:
    text = "La salud no siempre avisa. Muchas personas empiezan a valorar ciertas decisiones justo cuando ya les hubiera gustado tenerlas pensadas."
    intent = classify_hook_intent(text, editorial_type="risk_warning")
    style = choose_hook_style(str(intent.get("intent") or ""), text=text, editorial_type="risk_warning")
    fit = assess_hook_fit(text, editorial_type="risk_warning", hook_type="content")
    edl = build_edit_decision_list(
        _parse_transcript_lines(_timestamped([
            (0, 2, "La salud no siempre avisa."),
            (2, 8, "Muchas personas empiezan a valorar ciertas decisiones justo cuando ya les hubiera gustado tenerlas pensadas."),
        ])),
        silence_plan={"silence_intervals": [{"start_s": 1.9, "end_s": 2.3}]},
        duration_s=8.0,
    )
    useful_pause_kept = not any(
        decision.action == "cut" and decision.start_s <= 1.9 and decision.end_s >= 2.3
        for decision in edl.decisions
    )
    passed = intent.get("intent") == "risk_warning" and style.get("style") == "tension_pause_subtle" and useful_pause_kept
    return _case_result(
        "D_salud_warning",
        passed,
        "risk warning maps to tension style and preserves useful short pause",
        {"intent": intent.get("intent"), "style": style.get("style"), "pause_kept": useful_pause_kept, "fit": fit},
        {"intent": "risk_warning", "style": "tension_pause_subtle", "pause_kept": True},
        "hook_fit",
    )


def case_e_autonomos() -> Dict[str, Any]:
    text = "Si eres autónomo, tú no eres solo una persona. Eres el motor. Cuando todo depende de ti, protegerte ya no es un capricho. Es una estrategia."
    intent = classify_hook_intent(text, editorial_type="autonomous")
    fit = assess_hook_fit(text, editorial_type="autonomous", hook_type="content")
    idea = score_complete_idea(text)
    passed = (
        intent.get("intent") == "autonomous_business_stakes"
        and float(idea.get("complete_idea_score") or 0.0) >= 0.75
        and fit.get("hook_fit_acceptable") is True
    )
    return _case_result(
        "E_autonomos_business",
        passed,
        "autonomos intent, complete idea and strong hook",
        {"intent": intent, "complete_idea": idea, "fit": fit},
        {"intent": "autonomous_business_stakes", "complete_idea": True, "hook_acceptable": True},
        "hook_fit",
    )


def case_f_incomplete_boundary() -> Dict[str, Any]:
    transcript = _timestamped([
        (0, 3, "Cuando algo ocurre..."),
        (3, 9, "lo que más se agradece es tener claridad, acceso y sensación de respaldo."),
        (9, 13, "Por eso conviene mirar tu vida real antes de decidir."),
    ])
    lines = _parse_transcript_lines(transcript)
    before = score_complete_idea("Cuando algo ocurre...")
    expansion = expand_to_nearest_complete_idea(0.0, 3.0, lines)
    passed = (
        float(before.get("complete_idea_score") or 1.0) < 0.75
        and expansion.get("expanded_end_s") is not None
        and float(expansion.get("adjusted_end_s") or 0.0) > 3.0
    )
    return _case_result(
        "F_incomplete_boundary",
        passed,
        "incomplete phrase expands to include closure",
        {"before": before, "expansion": expansion},
        {"before_incomplete": True, "expanded_end": True},
        "complete_idea",
    )


def case_g_fake_rich() -> Dict[str, Any]:
    text = "Y también esto puede estar bien."
    clip_info = {
        "text": text,
        "vpi_score": 80,
        "virality_score": 80,
        "editing_richness_score": 8,
        "editing_richness_status": "rich",
        "editing_richness_warnings": [],
        "hook_plan": {
            "hook_type": "content",
            "hook_first3_status": "weak",
            "hook_first3_score": 3,
            "hook_first3_final_verified": False,
            "hook_first3_missing": ["hook_subtitle_before_1_5s", "rhythm"],
        },
        "visual_effects": {
            "visual_effects_applied": True,
            "visual_effects_final_verified": True,
            "visual_effect_quality": "basic_motion",
            "visual_effects_events": [{"type": "subtle_push_in"}],
        },
        "output_qc": {"duration_s": 30.0, "highlights": 0, "broll": 0},
        "music": {"music_applied": True, "music_final_verified": True, "tracks_found": 1},
        "sfx": {"sfx_applied": False, "sfx_assets_found": 0},
        "transitions": {"transitions_applied": False, "transition_events": []},
        "silence_edit_plan": {"rendered": False, "total_removed_s": 0.0},
    }
    result = evaluate_clip_publishability(clip_info, {"text": text, "editorial_type": "generic", "vpi_score": 80, "virality_score": 80}).to_dict()
    status = str(result.get("publishable_status") or "")
    recommendation = str(result.get("upload_recommendation") or "")
    passed = status != "ready_to_upload" and "rich" not in recommendation.lower()
    return _case_result(
        "G_fake_rich_blocked",
        passed,
        "weak hook/basic motion/no highlights cannot become ready rich",
        {"publishable_status": status, "upload_recommendation": recommendation, "warnings": result.get("editorial_fluency_warnings")},
        {"not_ready": True, "not_rich": True},
        "quality_gate",
    )


def case_i_negative_mid_sentence() -> Dict[str, Any]:
    text = "Para muchas familias esto importa porque"
    idea = score_complete_idea(text)
    passed = float(idea.get("complete_idea_score") or 1.0) < 0.75 and bool(idea.get("ends_badly"))
    return _case_result(
        "I_negative_mid_sentence",
        passed,
        "phrase ending mid-thought is incomplete",
        {"complete_idea": idea},
        {"complete_idea_lt": 0.75, "ends_badly": True},
        "complete_idea",
    )


def case_j_negative_generic_weak_hook() -> Dict[str, Any]:
    text = "Y también esto es una cosa que está ahí."
    intent = classify_hook_intent(text, editorial_type="generic")
    fit = assess_hook_fit(text, editorial_type="generic", hook_type="content")
    hook_plan = {
        "hook_type": "content",
        "hook_first3_score": 3,
        "hook_first3_status": "weak",
        "hook_first3_missing": ["hook_subtitle_before_1_5s", "rhythm"],
    }
    unresolved = is_weak_hook_unresolved(hook_plan, hook_fit_result=fit)
    adjustment = find_better_hook_start(text, _parse_transcript_lines(_timestamped([
        (0, 2, "Y también esto es una cosa que está ahí."),
        (2, 6, "Tener un seguro de salud no es un postureo. Es organización."),
    ])))
    passed = (
        intent.get("intent") == "neutral_explanation"
        and fit.get("hook_fit_acceptable") is False
        and unresolved is True
        and adjustment.get("adjusted_start") is True
    )
    return _case_result(
        "J_negative_generic_weak_hook",
        passed,
        "generic weak hook is unresolved and nearby stronger start is detected",
        {"intent": intent, "fit": fit, "unresolved": unresolved, "start_adjustment": adjustment},
        {"intent": "neutral_explanation", "hook_fit_acceptable": False, "unresolved": True, "adjusted_start": True},
        "hook_fit",
    )


def case_k_negative_repetition_guard() -> Dict[str, Any]:
    transcript = _timestamped([
        (0, 3, "La salud no siempre avisa."),
        (3, 6, "La salud no siempre avisa."),
        (6, 12, "Tiene una costumbre rebelde y por eso conviene tener claridad."),
    ])
    plan = build_fluency_edit_plan(_parse_transcript_lines(transcript))
    repeated_edits = [edit for edit in plan.edits if edit.get("type") == "remove_repetition"]
    passed = plan.fluency_edit_applied and len(repeated_edits) >= 1
    return _case_result(
        "K_negative_repetition_guard",
        passed,
        "repeated take must produce a cleanup edit",
        {"edits": plan.edits, "score_before": plan.fluency_score_before, "score_after": plan.fluency_score_after},
        {"remove_repetition_edits_gte": 1},
        "fluency",
    )


def case_l_negative_bts_mixed() -> Dict[str, Any]:
    segment = {
        "text": "Ok, dale de nuevo. Hoy vengo a hablarte del seguro de decesos. Ya sí. Este seguro no va de miedo.",
        "start_time": "00:00",
        "end_time": "00:24",
        "bts_contamination_ratio": 0.40,
        "useful_content_ratio": 0.60,
    }
    quality = evaluate_content_quality(segment)
    passed = quality.get("content_quality_label") == "reject" and quality.get("content_quality_reason") == "bts_contamination_too_high"
    return _case_result(
        "L_negative_bts_mixed",
        passed,
        "mixed BTS/content window is rejected instead of accepted whole",
        {"quality": quality},
        {"label": "reject", "reason": "bts_contamination_too_high"},
        "quality_gate",
    )


def case_m_positive_decesos_emotional() -> Dict[str, Any]:
    text = "A veces la mejor ayuda no es la más visible. Es la que aparece cuando más falta hace para dar tranquilidad a la familia."
    fluency = assess_editorial_fluency(text=text, editorial_type="emotional", duration_s=12.0)
    fit = assess_hook_fit(text, editorial_type="emotional", hook_type="content")
    passed = (
        fluency.get("complete_idea_score", 0.0) >= 0.75
        and fit.get("hook_fit_acceptable") is True
        and fit.get("style") == "soft_cinematic_push"
    )
    return _case_result(
        "M_positive_decesos_emotional",
        passed,
        "emotional decesos/family closure is complete and uses soft hook style",
        {"fluency": fluency, "fit": fit},
        {"complete_idea": True, "hook_fit_acceptable": True, "style": "soft_cinematic_push"},
        "hook_fit",
    )


def case_n_positive_practical_advice() -> Dict[str, Any]:
    text = "Antes de mirar nombres o precios, conviene mirar tu vida real. La clave es decidir qué tranquilidad estás buscando."
    intent = classify_hook_intent(text, editorial_type="advice")
    fit = assess_hook_fit(text, editorial_type="advice", hook_type="content")
    idea = score_complete_idea(text)
    passed = (
        intent.get("intent") == "practical_advice"
        and fit.get("style") == "clean_explanation"
        and fit.get("hook_fit_acceptable") is True
        and float(idea.get("complete_idea_score") or 0.0) >= 0.75
    )
    return _case_result(
        "N_positive_practical_advice",
        passed,
        "practical advice maps to clean explanation and complete idea",
        {"intent": intent, "fit": fit, "complete_idea": idea},
        {"intent": "practical_advice", "style": "clean_explanation", "complete_idea": True},
        "hook_fit",
    )


def case_o_negative_fake_rich_basic_motion() -> Dict[str, Any]:
    clip_info = {
        "text": "Esto es una cosa más que también puede pasar.",
        "vpi_score": 75,
        "virality_score": 75,
        "editing_richness_score": 9,
        "editing_richness_status": "rich",
        "hook_plan": {
            "hook_type": "content",
            "hook_first3_status": "weak",
            "hook_first3_score": 2,
            "hook_first3_final_verified": False,
            "hook_first3_missing": ["hook_subtitle_before_1_5s", "rhythm"],
        },
        "visual_effects": {
            "visual_effects_applied": True,
            "visual_effects_final_verified": True,
            "visual_effect_quality": "basic_motion",
            "visual_effects_events": [{"type": "subtle_push_in"}],
        },
        "output_qc": {"duration_s": 28.0, "highlights": 0, "broll": 0},
        "music": {"music_applied": True, "music_final_verified": True, "tracks_found": 1},
        "sfx": {"sfx_applied": False, "sfx_assets_found": 0},
        "transitions": {"transitions_applied": False, "transition_events": []},
        "silence_edit_plan": {"rendered": False, "total_removed_s": 0.0},
    }
    result = evaluate_clip_publishability(clip_info, {"text": clip_info["text"], "editorial_type": "generic"}).to_dict()
    passed = result.get("publishable_status") != "ready_to_upload"
    return _case_result(
        "O_negative_fake_rich_basic_motion",
        passed,
        "basic_motion alone cannot rescue weak hook/no highlights/no broll",
        {"publishable": result},
        {"publishable_status_not": "ready_to_upload"},
        "quality_gate",
    )


def _private_gate_clip(text: str, **overrides: Any) -> Dict[str, Any]:
    clip_info: Dict[str, Any] = {
        "text": text,
        "vpi_score": 82,
        "virality_score": 78,
        "editing_richness_score": 6,
        "editing_richness_status": "good",
        "hook_plan": {
            "hook_type": "content",
            "hook_first3_status": "strong",
            "hook_first3_score": 6,
            "hook_first3_final_verified": True,
            "hook_first3_missing": [],
        },
        "visual_effects": {
            "visual_effects_applied": True,
            "visual_effects_final_verified": True,
            "visual_effect_quality": "basic_motion",
            "visual_effects_events": [{"type": "subtle_push_in", "visual_effect_classification": "basic_motion"}],
        },
        "output_qc": {"duration_s": 30.0, "highlights": 1, "broll": 0},
        "caption_source": "offline_eval",
        "words": [{"word": word} for word in text.split()],
        "brand_treatment": {"rendered": True},
        "music": {"music_applied": True, "music_final_verified": True, "tracks_found": 1},
        "sfx": {"sfx_applied": False, "sfx_assets_found": 0},
        "transitions": {"transitions_applied": False, "transition_events": []},
        "silence_edit_plan": {"rendered": True, "total_removed_s": 0.4},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(clip_info.get(key), dict):
            merged = dict(clip_info[key])
            merged.update(value)
            clip_info[key] = merged
        else:
            clip_info[key] = value
    return evaluate_clip_publishability(clip_info, {"text": text, "editorial_type": overrides.get("editorial_type", "advice")}).to_dict()


def case_p_private_strong_limited_assets() -> Dict[str, Any]:
    text = "Antes de mirar nombres o precios, conviene mirar tu vida real. La clave es decidir qué tranquilidad estás buscando."
    result = _private_gate_clip(text, editorial_type="advice")
    status = result.get("private_premium_status")
    passed = status in {"PRIVATE_PREMIUM_READY", "PRIVATE_PREMIUM_LIMITED_ASSETS"}
    return _case_result(
        "P_private_strong_without_broll",
        passed,
        "strong editorial clip without broll remains private-premium usable",
        {"private_premium_status": status, "result": result},
        {"status_in": ["PRIVATE_PREMIUM_READY", "PRIVATE_PREMIUM_LIMITED_ASSETS"]},
        "quality_gate",
    )


def case_q_private_effects_incomplete_blocked() -> Dict[str, Any]:
    text = "Cuando algo ocurre porque"
    result = _private_gate_clip(
        text,
        visual_effects={
            "visual_effect_quality": "premium_visual_effect",
            "visual_effects_events": [{"type": "punch_zoom", "visual_effect_classification": "premium_visual_effect"}],
        },
        transitions={"transitions_applied": True, "transition_contextual": True, "transition_events": [{"contextual": True}]},
        sfx={"sfx_applied": True, "sfx_contextual": True, "sfx_design_events": [{"contextual": True}]},
    )
    passed = result.get("private_premium_status") == "DO_NOT_UPLOAD"
    return _case_result(
        "Q_private_effects_incomplete_blocked",
        passed,
        "many effects cannot rescue incomplete idea",
        {"private_premium_status": result.get("private_premium_status"), "result": result},
        {"private_premium_status": "DO_NOT_UPLOAD"},
        "quality_gate",
    )


def case_r_private_weak_hook_review() -> Dict[str, Any]:
    text = "Hoy vengo a hablarte del seguro de decesos. Existe para facilitar un momento difícil y para dar tranquilidad a la familia."
    result = _private_gate_clip(
        text,
        hook_plan={
            "hook_first3_status": "weak",
            "hook_first3_score": 3,
            "hook_first3_final_verified": False,
            "hook_first3_missing": ["hook_subtitle_before_1_5s", "rhythm"],
        },
        editorial_type="neutral",
    )
    passed = result.get("private_premium_status") == "PRIVATE_PREMIUM_REVIEW"
    return _case_result(
        "R_private_weak_hook_review",
        passed,
        "good content with weak unresolved hook goes to private premium review",
        {"private_premium_status": result.get("private_premium_status"), "result": result},
        {"private_premium_status": "PRIVATE_PREMIUM_REVIEW"},
        "quality_gate",
    )


def case_s_private_bts_effects_blocked() -> Dict[str, Any]:
    text = "Ok, dale de nuevo. Claro. Ya sí. Papá."
    result = _private_gate_clip(
        text,
        visual_effects={
            "visual_effect_quality": "premium_visual_effect",
            "visual_effects_events": [{"type": "punch_zoom", "visual_effect_classification": "premium_visual_effect"}],
        },
        transitions={"transitions_applied": True, "transition_contextual": True, "transition_events": [{"contextual": True}]},
        sfx={"sfx_applied": True, "sfx_contextual": True, "sfx_design_events": [{"contextual": True}]},
    )
    passed = result.get("private_premium_status") == "DO_NOT_UPLOAD"
    return _case_result(
        "S_private_bts_effects_blocked",
        passed,
        "BTS remains blocked even with SFX/VFX/transitions",
        {"private_premium_status": result.get("private_premium_status"), "result": result},
        {"private_premium_status": "DO_NOT_UPLOAD"},
        "quality_gate",
    )


def case_t_motion_pack_risk_warning() -> Dict[str, Any]:
    text = "La salud no siempre avisa."
    intent = classify_hook_intent(text, editorial_type="risk_warning")
    profile = get_hook_motion_profile(str(intent.get("intent") or ""))
    rhythm = build_kickframe_rhythm(str(intent.get("intent") or ""), "hook_first3")
    events = plan_visual_effects(
        hook_plan={
            "hook_type": "content",
            "hook_intent": intent.get("intent"),
            "hook_first3_status": "strong",
            "hook_first3_score": 7,
        },
        duration_s=8.0,
    )
    passed = (
        intent.get("intent") == "risk_warning"
        and profile.get("visual_profile") == "tension_push"
        and rhythm.get("first_kick_frames") == 5
        and rhythm.get("second_kick_frames") == 10
        and (events[0] or {}).get("visual_profile") == "tension_push"
    )
    return _case_result(
        "T_motion_pack_risk_warning",
        passed,
        "risk warning receives tension push and 5->10 kickframe rhythm",
        {"intent": intent, "profile": profile, "rhythm": rhythm, "events": events},
        {"intent": "risk_warning", "visual_profile": "tension_push", "kickframes": "5->10"},
        "motion_pack",
    )


def case_u_motion_pack_generic_basic() -> Dict[str, Any]:
    text = "Hoy vengo a explicar una idea sencilla sobre seguros."
    intent = classify_hook_intent(text, editorial_type="generic")
    profile = get_hook_motion_profile(str(intent.get("intent") or ""))
    events = plan_visual_effects(
        hook_plan={
            "hook_type": "content",
            "hook_intent": intent.get("intent"),
            "hook_first3_status": "strong",
            "hook_first3_score": 7,
        },
        duration_s=8.0,
    )
    passed = (
        profile.get("visual_profile") == "basic_clean_motion"
        and bool((events[0] or {}).get("premium_visual_effect")) is False
    )
    return _case_result(
        "U_motion_pack_generic_basic",
        passed,
        "generic explanation stays basic motion and does not inflate premium visual effect",
        {"intent": intent, "profile": profile, "events": events},
        {"visual_profile": "basic_clean_motion", "premium_visual_effect": False},
        "motion_pack",
    )


def case_v_caption_overlay_pack() -> Dict[str, Any]:
    text = "Este seguro no va de miedo. Va de alivio para la familia."
    intent = classify_hook_intent(text, editorial_type="myth_debunk")
    words = [{"word": word, "text": word, "start": i * 0.25, "end": i * 0.25 + 0.2, "score": 0.7} for i, word in enumerate(text.split())]
    plan = plan_caption_overlay_pack(
        text,
        hook_intent=str(intent.get("intent") or ""),
        editorial_type="decesos",
        words=words,
        local_icon_assets=[],
    )
    passed = (
        plan.get("caption_overlay_pack") is True
        and "keyword_emphasis" in (plan.get("caption_overlay_actions") or [])
        and (plan.get("hook_overlay") or {}).get("applied") is True
    )
    return _case_result(
        "V_caption_overlay_pack_decesos",
        passed,
        "caption overlay pack applies restrained keyword emphasis and hook overlay",
        {"intent": intent, "plan": plan},
        {"caption_overlay_pack": True, "actions_include": ["keyword_emphasis", "hook_overlay"]},
        "caption_overlay",
    )


def case_w_broll_editorial_pack() -> Dict[str, Any]:
    text = "Este seguro no va de miedo. Va de alivio para la familia."
    decision = build_broll_editorial_decision(
        segment_text=text,
        hook_intent="myth_flip",
        topic="decesos",
        private_premium_status="",
        composition_decision={"composition_mode": "hook_driven"},
        first3_visual_contract={},
        visual_profile="calm_reveal",
    )
    match = match_broll_asset(
        broll_intent=str(decision.get("broll_intent") or ""),
        topic="decesos",
        segment_text=text,
    )
    match_safe = dict(match)
    if isinstance(match_safe.get("asset_path"), Path):
        match_safe["asset_path"] = str(match_safe.get("asset_path"))
    if match.get("matched"):
        passed = decision.get("should_use_broll") is True and "coffin" not in str(match.get("asset", "")).lower()
        reason = "editorial broll intent mapped and local asset matched without lugubrious cue"
    else:
        passed = (
            decision.get("should_use_broll") is True
            and decision.get("fallback") in {"motion_only", "caption_overlay", "sweeping_reveal"}
        )
        reason = "editorial opportunity detected and fallback selected when no local asset"
    return _case_result(
        "W_broll_editorial_pack",
        passed,
        reason,
        {"decision": decision, "asset_match": match_safe},
        {"intent_in": ["family_relief", "emotional_support"], "fallback_if_no_asset": True},
        "broll_pack",
    )


def case_x_sfx_retention_pack() -> Dict[str, Any]:
    text = "La salud no siempre avisa. Tener acceso rápido a especialistas cambia mucho."
    decision = build_sfx_retention_decision(
        hook_intent="risk_warning",
        visual_profile="tension_push",
        composition_mode="warning_tension",
        broll_editorial_decision={"should_use_broll": True},
        segment_text=text,
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"status": "pass"},
    )
    match = match_sfx_asset(
        sfx_family=str(decision.get("sfx_family") or ""),
        hook_intent="risk_warning",
        recent_sfx_history=[],
        task_id="offline_eval_sfx",
    )
    match_safe = dict(match)
    if isinstance(match_safe.get("asset_path"), Path):
        match_safe["asset_path"] = str(match_safe.get("asset_path"))
    passed = bool(
        decision.get("sfx_family") in {"dark_riser", "tension_riser"}
        and decision.get("should_apply_sfx") is True
        and decision.get("sfx_family") != "deep_boom"
        and (
            (match.get("matched") is True)
            or (decision.get("fallback") in {"silence_contrast", "caption_emphasis", "music_only"})
        )
    )
    return _case_result(
        "X_sfx_retention_pack",
        passed,
        "risk warning maps to non-aggressive contextual SFX with local-asset-or-clean-fallback behavior",
        {"decision": decision, "match": match_safe},
        {"family_in": ["dark_riser", "tension_riser"], "not": "deep_boom", "local_or_clean_fallback": True},
        "sfx_pack",
    )


def case_y_cinematic_finish_pack() -> Dict[str, Any]:
    risk_text = "La salud no siempre avisa."
    risk_decision = build_cinematic_finish_decision(
        hook_intent="risk_warning",
        composition_mode="warning_tension",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        caption_overlay_pack={"caption_overlay_pack": True},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=True,
        segment_text=risk_text,
    )
    risk_plan = build_cinematic_finish_filter_plan(risk_decision)
    risk_safety = assess_finish_safety(
        risk_plan,
        caption_overlay_pack={"caption_overlay_pack": True},
        first3_visual_contract_data={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        composition_decision={"screen_priority": "face"},
    )
    noop_decision = build_cinematic_finish_decision(
        hook_intent="neutral_explanation",
        composition_mode="minimal_safe",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"status": "pass"},
        caption_overlay_pack={},
        motion_pack_applied=False,
        broll_applied=False,
        sfx_retention_pack=False,
        segment_text="Explicación neutra y breve.",
    )
    noop_plan = build_cinematic_finish_filter_plan(noop_decision)
    blocked_decision = build_cinematic_finish_decision(
        hook_intent="myth_flip",
        composition_mode="hook_driven",
        private_premium_status="DO_NOT_UPLOAD",
        first3_visual_contract={"status": "review"},
        caption_overlay_pack={"caption_overlay_pack": True},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=False,
        segment_text="Este seguro no va de miedo.",
    )
    passed = bool(
        risk_decision.get("should_apply_finish")
        and risk_decision.get("finish_profile") == "warning_subtle_tension"
        and float(risk_decision.get("contrast_value") or 1.0) <= 1.08
        and risk_safety.get("status") in {"pass", "adjusted"}
        and not bool(noop_plan.get("apply"))
        and not bool(blocked_decision.get("should_apply_finish"))
    )
    return _case_result(
        "Y_cinematic_finish_pack",
        passed,
        "finish pack maps contextual profiles and keeps noop/blocked cases honest",
        {
            "risk_decision": risk_decision,
            "risk_plan": risk_plan,
            "risk_safety": risk_safety,
            "noop_decision": noop_decision,
            "noop_plan": noop_plan,
            "blocked_decision": blocked_decision,
        },
        {
            "risk_profile": "warning_subtle_tension",
            "risk_safety": ["pass", "adjusted"],
            "noop_apply": False,
            "do_not_upload_should_apply": False,
        },
        "finish_pack",
    )


LONG_TRANSCRIPT = """
[00:03 - 00:04] Claro.
[00:06 - 00:07] Papá.
[00:11 - 00:13] Ok chéverísima.
[00:16 - 00:17] Ya sí.
[00:49 - 00:51] Hoy vengo a hablarte del Seguro de Decesos.
[00:51 - 00:54] Este seguro no va de miedo.
[00:54 - 00:57] Va de alivio para la familia.
[00:57 - 01:03] Existe para facilitar un momento difícil y para que la familia no tenga que gestionar más de la cuenta.
[01:03 - 01:12] Deja de sonar triste y empieza a sonar responsable. Por eso merece una explicación serena.
[01:56 - 01:57] Dale de nuevo con eso.
[05:07 - 05:10] Tener un seguro de salud no es un postureo. Es organización.
[05:11 - 05:18] Para mucha gente un seguro de salud no es lujo, es orden y claridad.
[05:23 - 05:32] Va de poder revisar algo sin eternizarlo y de tener orientación, especialistas y pruebas.
[05:41 - 05:49] Antes de mirar nombres o precios conviene mirar tu vida real y qué tranquilidad estás buscando.
[06:53 - 07:03] Cuando algo ocurre lo que más se agradece es claridad y respaldo.
[07:03 - 07:13] Un seguro de salud bien entendido es una herramienta de tranquilidad para cuidar tiempos, opciones y acompañamiento.
[08:27 - 08:31] Si eres autónomo tú no eres solo una persona. Eres el motor.
[08:32 - 08:35] Cuando todo depende de ti protegerte ya no es un capricho. Es una estrategia.
[08:35 - 08:44] Eres quien factura, quien responde, quien organiza y sostiene.
[08:44 - 08:51] Protegerse deja de ser un lujo y empieza a ser sentido común.
[09:04 - 09:14] Cuando depende de ti, proteger tu estabilidad es proteger mucho más que tu bolsillo.
[11:47 - 11:48] Ok, gracias.
"""


def case_h_long_delivery() -> Dict[str, Any]:
    pool = build_clean_take_candidates(LONG_TRANSCRIPT, transcript_duration_s=712.0, num_clips=3)
    accepted, rejected = filter_content_quality_candidates(list(pool.get("segments") or []), requested=3)
    selected: List[Dict[str, Any]] = []
    for topic in ("decesos", "salud", "autonomos"):
        match = next((item for item in accepted if item.get("clean_take_topic") == topic), None)
        if match:
            selected.append(match)
    contract = build_delivery_contract(requested=3, delivered=len(selected), rejected_reasons=rejected)
    topics = [str(item.get("clean_take_topic")) for item in selected]
    passed = len(selected) == 3 and topics == ["decesos", "salud", "autonomos"] and all(float(item.get("bts_contamination_ratio", 1.0)) <= 0.2 for item in selected)
    return _case_result(
        "H_long_transcript_delivery",
        passed,
        "simulates 3 topic-diverse clean takes without BTS filler",
        {
            "generated_before_filter": pool.get("generated_before_filter"),
            "accepted": len(accepted),
            "selected_topics": topics,
            "contract": contract,
        },
        {"requested": 3, "delivered": 3, "topics": ["decesos", "salud", "autonomos"], "no_bts_filler": True},
        "delivery",
    )


def build_scorecard(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rate(categories: set[str]) -> float:
        subset = [item for item in results if item["category"] in categories]
        if not subset:
            return 1.0
        return round(sum(1 for item in subset if item["passed"]) / len(subset), 3)

    complete = rate({"complete_idea"})
    fluency = rate({"fluency"})
    hook = rate({"hook_fit"})
    gate = rate({"quality_gate"})
    motion = rate({"motion_pack"})
    caption_overlay = rate({"caption_overlay"})
    broll_pack = rate({"broll_pack"})
    delivery = all(item["passed"] for item in results if item["category"] == "delivery")
    sfx_pack = rate({"sfx_pack"})
    finish_pack = rate({"finish_pack"})
    overall = round((complete + fluency + hook + gate + motion + caption_overlay + broll_pack + sfx_pack + finish_pack + (1.0 if delivery else 0.0)) / 10.0, 3)
    status = "READY_FOR_RENDER" if overall >= 0.85 else ("NEEDS_MINOR_FIXES" if overall >= 0.70 else "NOT_READY")
    logger.info("[offline-eval] score=%.3f status=%s", overall, status)
    return {
        "total_cases": len(results),
        "passed_cases": sum(1 for item in results if item["passed"]),
        "failed_cases": sum(1 for item in results if not item["passed"]),
        "complete_idea_pass_rate": complete,
        "fluency_pass_rate": fluency,
        "hook_fit_pass_rate": hook,
        "quality_gate_pass_rate": gate,
        "motion_pack_pass_rate": motion,
        "caption_overlay_pass_rate": caption_overlay,
        "broll_pack_pass_rate": broll_pack,
        "sfx_pack_pass_rate": sfx_pack,
        "finish_pack_pass_rate": finish_pack,
        "delivery_simulation_pass": delivery,
        "overall_editorial_readiness_score": overall,
        "status": status,
    }


def write_reports(results: List[Dict[str, Any]], scorecard: Dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scorecard": scorecard,
        "results": results,
    }
    JSON_REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# VPI Editorial Offline Evaluation",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Status: `{scorecard['status']}`",
        f"- Overall score: `{scorecard['overall_editorial_readiness_score']}`",
        "",
        "## Scorecard",
        "",
    ]
    for key, value in scorecard.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Cases", ""])
    for item in results:
        lines.append(f"- `{item['case']}`: `{item['status']}` - {item['reason']}")
    MD_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _payload(results: List[Dict[str, Any]], scorecard: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scorecard": scorecard,
        "results": results,
    }


def _configure_logging(json_only: bool) -> None:
    if json_only:
        logging.disable(logging.CRITICAL)
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate VPI editorial logic offline without rendering video.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any case fails.")
    parser.add_argument("--json-only", action="store_true", help="Print machine-readable JSON only, with no log noise.")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    _configure_logging(bool(args.json_only))
    cases = [
        case_a_decesos_bts,
        case_b_repetition_correction,
        case_c_salud_hook,
        case_d_salud_warning,
        case_e_autonomos,
        case_f_incomplete_boundary,
        case_g_fake_rich,
        case_h_long_delivery,
        case_i_negative_mid_sentence,
        case_j_negative_generic_weak_hook,
        case_k_negative_repetition_guard,
        case_l_negative_bts_mixed,
        case_m_positive_decesos_emotional,
        case_n_positive_practical_advice,
        case_o_negative_fake_rich_basic_motion,
        case_p_private_strong_limited_assets,
        case_q_private_effects_incomplete_blocked,
        case_r_private_weak_hook_review,
        case_s_private_bts_effects_blocked,
        case_t_motion_pack_risk_warning,
        case_u_motion_pack_generic_basic,
        case_v_caption_overlay_pack,
        case_w_broll_editorial_pack,
        case_x_sfx_retention_pack,
        case_y_cinematic_finish_pack,
    ]
    results = [case() for case in cases]
    scorecard = build_scorecard(results)
    write_reports(results, scorecard)
    payload = _payload(results, scorecard)
    if args.json_only:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(scorecard, ensure_ascii=False, indent=2))
        print(f"EDITORIAL_EVAL_STATUS={scorecard['status']}")
    any_failed = any(not item["passed"] for item in results)
    if args.strict and any_failed:
        return 1
    return 0 if not any_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
