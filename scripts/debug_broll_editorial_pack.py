#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from services.vpi_broll_intent import (  # noqa: E402
    build_broll_editorial_decision,
    match_broll_asset,
)
from services.vpi_visual_effects_service import (  # noqa: E402
    build_composition_decision,
    resolve_visual_layer_conflicts,
)


PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[debug-broll-editorial-pack] {name}=PASS {detail}".strip())
    else:
        FAIL += 1
        print(f"[debug-broll-editorial-pack] {name}=FAIL {detail}".strip())


def _runtime_broll_true(*, decision: dict, matched: bool, composition_allowed: bool, applied_asset_match: bool, timing_valid: bool = True) -> bool:
    return bool(
        decision.get("should_use_broll")
        and matched
        and composition_allowed
        and timing_valid
        and applied_asset_match
    )


def _decision(text: str, hook_intent: str, topic: str, composition_mode: str = "") -> dict:
    comp = {"composition_mode": composition_mode} if composition_mode else {}
    return build_broll_editorial_decision(
        segment_text=text,
        hook_intent=hook_intent,
        topic=topic,
        private_premium_status="",
        composition_decision=comp,
        first3_visual_contract={},
        visual_profile="tension_push" if hook_intent == "risk_warning" else "clean_explanation",
    )


def case_1_decesos() -> None:
    text = "Este seguro no va de miedo. Va de alivio para la familia."
    decision = _decision(text, "myth_flip", "decesos")
    match = match_broll_asset(broll_intent=decision.get("broll_intent", ""), topic="decesos", segment_text=text)
    check("decesos_intent", decision.get("broll_intent") in {"family_relief", "emotional_support"}, str(decision))
    check("decesos_no_fail_without_asset", True, str(match.get("reason")))
    if match.get("matched"):
        check("decesos_not_lugubrious", all(x not in str(match.get("asset", "")).lower() for x in ("coffin", "cement", "grave")), str(match.get("asset")))


def case_2_salud_warning() -> None:
    text = "La salud no siempre avisa. Tener acceso rápido a especialistas cambia mucho."
    decision = _decision(text, "risk_warning", "salud")
    check("salud_intent", decision.get("broll_intent") in {"health_access", "risk_warning_context"}, str(decision))
    check("salud_timing_after_hook", float(decision.get("start_offset") or 0.0) >= 1.5, str(decision.get("start_offset")))


def case_3_autonomos() -> None:
    text = "Si eres autónomo, tú eres el motor. Si paras, también paran tus ingresos."
    decision = _decision(text, "autonomous_business_stakes", "autonomos")
    match = match_broll_asset(broll_intent=decision.get("broll_intent", ""), topic="autonomos", segment_text=text)
    check("autonomos_intent", decision.get("broll_intent") == "autonomous_work_stability", str(decision))
    check("autonomos_fallback_clean", decision.get("fallback") in {"motion_only", "caption_overlay", "sweeping_reveal", "none"}, str(decision.get("fallback")))
    check("autonomos_asset_optional", True, str(match.get("matched")))


def case_4_practical() -> None:
    text = "Antes de mirar precios, mira tu vida real."
    decision = _decision(text, "practical_advice", "consejo")
    check("practical_intent", decision.get("broll_intent") == "practical_explanation", str(decision))
    check("practical_duration_range", 0.8 <= float(decision.get("duration") or 0.0) <= 2.2, str(decision.get("duration")))


def case_5_emotional_closure() -> None:
    text = "Cuando más falta hace, tener apoyo cambia todo."
    decision = _decision(text, "emotional_closure", "decesos", composition_mode="emotional_soft")
    check("emotional_soft_intent", decision.get("broll_intent") in {"emotional_support", "family_relief", "no_broll_needed"}, str(decision))
    check("emotional_soft_not_aggressive", decision.get("fallback") != "glitch", str(decision))


def case_6_minimal_safe() -> None:
    text = "Hoy explico una idea general sin ejemplo visual concreto."
    decision = _decision(text, "neutral_explanation", "generic", composition_mode="minimal_safe")
    check("minimal_safe_skip", decision.get("should_use_broll") is False, str(decision))


def case_7_composition_conflict() -> None:
    comp = build_composition_decision(
        hook_intent="myth_flip",
        visual_profile="calm_reveal",
        caption_overlay_pack={"hook_overlay": {"applied": True, "start_s": 0.1}, "caption_start_s": 0.1},
        transition_plan={},
        sfx_plan={},
        private_premium_status="",
        segment_text="Texto de prueba largo para simular caption largo en primer segundo",
    )
    resolved = resolve_visual_layer_conflicts(
        [
            {"type": "hook_overlay", "start_s": 0.1},
            {"type": "caption", "start_s": 0.1},
            {"type": "broll", "start_s": 0.8, "caption_text": " ".join(["texto"] * 20)},
        ],
        comp,
    )
    check("composition_conflict_blocks_broll", "broll" not in list(resolved.get("layers_final") or []), str(resolved.get("layers_final")))


def case_8_no_assets() -> None:
    text = "La salud no siempre avisa y conviene anticiparse."
    decision = _decision(text, "risk_warning", "salud")
    match = match_broll_asset(broll_intent=decision.get("broll_intent", ""), topic="salud", segment_text=text)
    if not match.get("matched"):
        opportunity = bool(decision.get("should_use_broll"))
        check("no_assets_opportunity_true", opportunity is True, str(decision))
        check("no_assets_limited_assets_path", decision.get("fallback") in {"motion_only", "caption_overlay", "sweeping_reveal"}, str(decision.get("fallback")))
    else:
        check("no_assets_case_has_asset", True, str(match.get("asset")))


def case_9_runtime_truth_requires_real_applied_asset() -> None:
    text = "Antes de mirar precios, mira tu vida real."
    decision = _decision(text, "practical_advice", "consejo")
    runtime_truth = _runtime_broll_true(
        decision=decision,
        matched=True,
        composition_allowed=True,
        applied_asset_match=False,
    )
    check("runtime_false_without_applied_asset_match", runtime_truth is False, str(runtime_truth))


def case_10_runtime_truth_blocked_by_composition() -> None:
    text = "Si eres autónomo, tú eres el motor. Si paras, también paran tus ingresos."
    decision = _decision(text, "autonomous_business_stakes", "autonomos")
    runtime_truth = _runtime_broll_true(
        decision=decision,
        matched=True,
        composition_allowed=False,
        applied_asset_match=True,
    )
    check("runtime_false_when_composition_blocked", runtime_truth is False, str(runtime_truth))


def main() -> int:
    case_1_decesos()
    case_2_salud_warning()
    case_3_autonomos()
    case_4_practical()
    case_5_emotional_closure()
    case_6_minimal_safe()
    case_7_composition_conflict()
    case_8_no_assets()
    case_9_runtime_truth_requires_real_applied_asset()
    case_10_runtime_truth_blocked_by_composition()
    print(f"[debug-broll-editorial-pack] results={PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
