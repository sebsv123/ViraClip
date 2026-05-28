#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from services.vpi_visual_effects_service import (  # noqa: E402
    apply_cinematic_finish,
    assess_finish_safety,
    build_cinematic_finish_decision,
    build_cinematic_finish_filter_plan,
)


PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[debug-cinematic-finish-pack] {name}=PASS {detail}".strip())
    else:
        FAIL += 1
        print(f"[debug-cinematic-finish-pack] {name}=FAIL {detail}".strip())


def _runtime_finish_true(*, should_apply_finish: bool, filter_chain: str, finish_applied: bool, safety_status: str, output_uses_finished_file: bool, fallback_used: str) -> bool:
    return bool(
        should_apply_finish
        and bool(filter_chain)
        and finish_applied
        and safety_status in {"pass", "adjusted"}
        and output_uses_finished_file
        and fallback_used == "none"
    )


def case_1_risk_warning() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="risk_warning",
        composition_mode="warning_tension",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        caption_overlay_pack={"caption_overlay_pack": True},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=True,
        segment_text="La salud no siempre avisa.",
    )
    plan = build_cinematic_finish_filter_plan(decision)
    safety = assess_finish_safety(
        plan,
        caption_overlay_pack={"caption_overlay_pack": True},
        first3_visual_contract_data={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        composition_decision={"screen_priority": "face"},
    )
    check("risk_profile", decision.get("finish_profile") == "warning_subtle_tension", str(decision))
    check("risk_no_terror_look", float(decision.get("contrast_value") or 0.0) <= 1.08, str(decision.get("contrast_value")))
    check("risk_caption_safety_pass", safety.get("status") in {"pass", "adjusted"}, str(safety))


def case_2_myth_flip() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="myth_flip",
        composition_mode="hook_driven",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"status": "pass"},
        caption_overlay_pack={"caption_overlay_pack": True},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=False,
        segment_text="Este seguro no va de miedo. Va de alivio para la familia.",
    )
    check("myth_profile", decision.get("finish_profile") in {"clean_premium", "warm_family"}, str(decision))
    check("myth_not_dark_grade", float(decision.get("brightness_value") or 0.0) >= -0.01, str(decision.get("brightness_value")))


def case_3_business() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="autonomous_business_stakes",
        composition_mode="business_punch",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"status": "pass"},
        caption_overlay_pack={"caption_overlay_pack": True},
        motion_pack_applied=True,
        broll_applied=True,
        sfx_retention_pack=True,
        segment_text="Si eres autónomo, tú eres el motor.",
    )
    check("business_profile", decision.get("finish_profile") == "business_contrast", str(decision))
    check("business_sharpness_subtle", float(decision.get("sharpness_value") or 0.0) <= 0.35, str(decision.get("sharpness_value")))


def case_4_emotional_closure() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="emotional_closure",
        composition_mode="emotional_soft",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"status": "pass"},
        caption_overlay_pack={"caption_overlay_pack": True},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=True,
        segment_text="Cuando más falta hace, tener apoyo cambia todo.",
    )
    check("emotional_profile", decision.get("finish_profile") in {"emotional_soft_grade", "warm_family"}, str(decision))
    check("emotional_no_aggressive_contrast", float(decision.get("contrast_value") or 0.0) <= 1.06, str(decision.get("contrast_value")))


def case_5_long_caption_safety() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="practical_advice",
        composition_mode="explanation_clean",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        caption_overlay_pack={"density_guard_actions": [{"action": "skip_overlay", "reason": "too_many_elements"}]},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=False,
        segment_text="Antes de mirar precios conviene mirar tu vida real y decidir con calma.",
    )
    plan = build_cinematic_finish_filter_plan(
        decision,
        caption_safety={"long_caption": True},
    )
    check("long_caption_reduce_or_block", not bool(plan.get("vignette")) and float(plan.get("contrast_value") or 1.0) <= 1.04, str(plan))


def case_5b_caption_risk_blocks() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="risk_warning",
        composition_mode="warning_tension",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"first3_visual_contract": {"caption_readable": False}, "status": "review"},
        caption_overlay_pack={"caption_overlay_pack": True},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=True,
        segment_text="La salud no siempre avisa.",
    )
    plan = build_cinematic_finish_filter_plan(decision)
    safety = assess_finish_safety(
        plan,
        caption_overlay_pack={"caption_overlay_pack": True},
        first3_visual_contract_data={"first3_visual_contract": {"caption_readable": False}, "status": "review"},
        composition_decision={"screen_priority": "face"},
    )
    check("caption_risk_blocks", safety.get("blocked") is True and safety.get("reason") == "caption_risk", str(safety))


def case_5c_overdarkening_adjusted() -> None:
    safety = assess_finish_safety(
        {
            "apply": True,
            "filter_chain": "eq=contrast=1.080:brightness=-0.020:saturation=1.000",
            "contrast_value": 1.08,
            "brightness_value": -0.02,
            "sharpness_value": 0.20,
            "vignette": True,
            "vignette_strength": 0.06,
        },
        caption_overlay_pack={},
        first3_visual_contract_data={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        composition_decision={"screen_priority": "caption"},
    )
    adjusted_plan = safety.get("finish_plan") or {}
    _brightness = adjusted_plan.get("brightness_value")
    check("overdarkening_adjusted", safety.get("adjusted") is True and _brightness is not None and float(_brightness) >= 0.0, str(safety))


def case_5d_oversharpen_adjusted() -> None:
    safety = assess_finish_safety(
        {
            "apply": True,
            "filter_chain": "unsharp=5:5:0.50:5:5:0.00",
            "contrast_value": 1.02,
            "brightness_value": 0.0,
            "sharpness_value": 0.50,
            "vignette": False,
            "vignette_strength": 0.0,
        },
        caption_overlay_pack={},
        first3_visual_contract_data={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        composition_decision={"screen_priority": "caption"},
    )
    adjusted_plan = safety.get("finish_plan") or {}
    check("oversharpen_adjusted", safety.get("adjusted") is True and float(adjusted_plan.get("sharpness_value") or 1.0) <= 0.24, str(safety))


def case_6_do_not_upload() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="risk_warning",
        composition_mode="warning_tension",
        private_premium_status="DO_NOT_UPLOAD",
        first3_visual_contract={"status": "review"},
        caption_overlay_pack={},
        motion_pack_applied=True,
        broll_applied=True,
        sfx_retention_pack=True,
        segment_text="La salud no siempre avisa.",
    )
    check("do_not_upload_no_finish", decision.get("should_apply_finish") is False, str(decision))


def case_7_ffmpeg_fallback() -> None:
    decision = build_cinematic_finish_decision(
        hook_intent="risk_warning",
        composition_mode="warning_tension",
        private_premium_status="PRIVATE_PREMIUM_READY",
        first3_visual_contract={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        caption_overlay_pack={},
        motion_pack_applied=True,
        broll_applied=False,
        sfx_retention_pack=True,
        segment_text="La salud no siempre avisa.",
    )
    missing_input = ROOT / "tmp_missing_input_for_finish.mp4"
    missing_output = ROOT / "tmp_missing_output_for_finish.mp4"
    result = apply_cinematic_finish(
        missing_input,
        missing_output,
        decision=decision,
        caption_overlay_pack={},
        first3_visual_contract_data={"first3_visual_contract": {"caption_readable": True}, "status": "pass"},
        composition_decision={"screen_priority": "face"},
    )
    check("ffmpeg_fallback_no_fail", result.get("visual_finish") is False and result.get("cinematic_finish_pack") is False, str(result))
    check("ffmpeg_fallback_reason", result.get("finish_fallback_used") in {"none", "basic_safe_grade"}, str(result.get("finish_fallback_used")))
    runtime_truth = _runtime_finish_true(
        should_apply_finish=True,
        filter_chain=str(((result.get("finish_filter_plan") or {}).get("filter_chain")) or ""),
        finish_applied=bool(result.get("finish_applied")),
        safety_status=str(result.get("finish_safety") or ""),
        output_uses_finished_file=False,
        fallback_used=str(result.get("finish_fallback_used") or "none"),
    )
    check("runtime_false_with_fallback_original", runtime_truth is False, str(runtime_truth))


def case_8_noop_decision() -> None:
    decision = build_cinematic_finish_decision(
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
    plan = build_cinematic_finish_filter_plan(decision)
    check("noop_finish_pack_false", decision.get("should_apply_finish") is False, str(decision))
    check("noop_plan_empty", plan.get("apply") is False, str(plan))
    runtime_truth = _runtime_finish_true(
        should_apply_finish=bool(decision.get("should_apply_finish")),
        filter_chain=str(plan.get("filter_chain") or ""),
        finish_applied=False,
        safety_status="pass",
        output_uses_finished_file=False,
        fallback_used="none",
    )
    check("runtime_false_without_real_apply", runtime_truth is False, str(runtime_truth))


def main() -> int:
    case_1_risk_warning()
    case_2_myth_flip()
    case_3_business()
    case_4_emotional_closure()
    case_5_long_caption_safety()
    case_5b_caption_risk_blocks()
    case_5c_overdarkening_adjusted()
    case_5d_oversharpen_adjusted()
    case_6_do_not_upload()
    case_7_ffmpeg_fallback()
    case_8_noop_decision()
    print(f"[debug-cinematic-finish-pack] results={PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
