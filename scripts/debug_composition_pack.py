#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from services.vpi_visual_effects_service import (  # noqa: E402
    build_composition_decision,
    first3_visual_contract,
    resolve_visual_layer_conflicts,
)


PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"PASS {label}: {detail}")
    else:
        FAIL += 1
        print(f"FAIL {label}: {detail}")


def _decision(intent: str, **kwargs) -> dict:
    return build_composition_decision(
        hook_intent=intent,
        visual_profile=kwargs.get("visual_profile", ""),
        caption_overlay_pack=kwargs.get("caption_overlay_pack", {}),
        transition_plan=kwargs.get("transition_plan", {}),
        sfx_plan=kwargs.get("sfx_plan", {}),
        private_premium_status=kwargs.get("private_premium_status", ""),
        segment_text=kwargs.get("segment_text", ""),
    )


def test_risk_warning() -> None:
    comp = _decision(
        "risk_warning",
        caption_overlay_pack={"hook_overlay": {"applied": True, "start_s": 0.4}, "caption_start_s": 0.6},
        sfx_plan={"sfx_motion_sync_type": "dark_riser_combo"},
        segment_text="La salud no siempre avisa.",
    )
    resolved = resolve_visual_layer_conflicts(
        [
            {"type": "hook_overlay", "start_s": 0.4},
            {"type": "lower_third", "start_s": 0.6},
            {"type": "caption", "start_s": 0.6},
        ],
        comp,
    )
    final_types = resolved["layers_final"]
    check("risk_warning mode", comp["composition_mode"] == "warning_tension", str(comp))
    check("risk_warning max layers", comp["max_simultaneous_layers"] == 2, str(comp["max_simultaneous_layers"]))
    check("risk_warning lower_third blocked with hook", "lower_third" not in final_types, str(final_types))


def test_myth_flip() -> None:
    comp = _decision(
        "myth_flip",
        caption_overlay_pack={"hook_overlay": {"applied": True, "start_s": 0.5}, "caption_start_s": 0.7},
        transition_plan={"transition_types": ["sweeping_reveal"]},
        segment_text="Este seguro no va de miedo. Va de alivio para la familia.",
    )
    resolved = resolve_visual_layer_conflicts(
        [
            {"type": "sweeping_reveal", "start_s": 0.2},
            {"type": "caption", "start_s": 0.7},
        ],
        comp,
    )
    check("myth_flip mode", comp["composition_mode"] == "hook_driven", str(comp))
    check("myth_flip sweep allowed", "sweeping_reveal" in resolved["layers_final"], str(resolved))


def test_emotional_closure() -> None:
    comp = _decision(
        "emotional_closure",
        caption_overlay_pack={"caption_start_s": 1.0},
        sfx_plan={"aggressive_impact_allowed": True},
        segment_text="A veces la mejor ayuda es la que aparece cuando más falta hace.",
    )
    resolved = resolve_visual_layer_conflicts(
        [
            {"type": "deep_boom", "start_s": 0.5},
            {"type": "caption", "start_s": 1.0},
        ],
        comp,
    )
    check("emotional_closure mode", comp["composition_mode"] == "emotional_soft", str(comp))
    check("emotional_closure deep_boom blocked", "deep_boom" not in resolved["layers_final"], str(resolved))


def test_long_caption_icon_skip() -> None:
    comp = _decision(
        "practical_advice",
        caption_overlay_pack={"caption_start_s": 0.6},
        segment_text="Antes de mirar nombres o precios conviene mirar tu vida real.",
    )
    resolved = resolve_visual_layer_conflicts(
        [
            {
                "type": "icon",
                "text": "este caption es demasiado largo para convivir con un icono sobrio en pantalla",
                "start_s": 0.5,
            },
            {"type": "caption", "start_s": 0.6},
        ],
        comp,
    )
    check("long caption icon skipped", "icon" not in resolved["layers_final"], str(resolved))


def test_business_punch() -> None:
    comp = _decision(
        "autonomous_business_stakes",
        caption_overlay_pack={"caption_start_s": 0.4},
        sfx_plan={"aggressive_impact_allowed": True},
        segment_text="Si eres autónomo, tú no eres solo una persona. Eres el motor.",
    )
    resolved = resolve_visual_layer_conflicts(
        [
            {"type": "caption", "start_s": 0.4},
            {"type": "motion", "start_s": 0.2},
            {"type": "sfx", "start_s": 0.5},
        ],
        comp,
    )
    check("business_punch mode", comp["composition_mode"] == "business_punch", str(comp))
    check("business_punch allows 3 layers", len(resolved["allowed_layers"]) == 3, str(resolved))


def test_minimal_safe_contract() -> None:
    comp = _decision("neutral_explanation", caption_overlay_pack={"caption_start_s": 0.8})
    contract = first3_visual_contract(
        hook_plan={"hook_first3_score": 4},
        caption_overlay_pack={"caption_start_s": 0.8, "composition_allowed_layers": [{"type": "caption", "start_s": 0.8}]},
        composition_decision=comp,
        visual_effects=[{"type": "subtle_push_in", "start_s": 0.4, "contextual": False}],
        transition_plan={},
    )
    check("minimal_safe mode", comp["composition_mode"] == "minimal_safe", str(comp))
    check("minimal_safe review/fail on weak first3", contract["status"] in {"review", "fail"}, str(contract))


def main() -> int:
    test_risk_warning()
    test_myth_flip()
    test_emotional_closure()
    test_long_caption_icon_skip()
    test_business_punch()
    test_minimal_safe_contract()
    print(f"RESULTS {PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
