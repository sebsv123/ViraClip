#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_hook_engine import classify_hook_intent  # noqa: E402
from src.services.vpi_sfx_service import sync_sfx_with_motion  # noqa: E402
from src.services.vpi_transition_engine import plan_mask_reveal  # noqa: E402
from src.services.vpi_visual_effects_service import (  # noqa: E402
    build_kickframe_rhythm,
    get_hook_motion_profile,
    plan_visual_effects,
)


def _result(name: str, passed: bool, actual: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case": name,
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "actual": actual,
        "expected": expected,
    }


def _hook_case(text: str, editorial_type: str) -> Dict[str, Any]:
    intent = classify_hook_intent(text, editorial_type=editorial_type)
    profile = get_hook_motion_profile(str(intent.get("intent") or ""))
    rhythm = build_kickframe_rhythm(str(intent.get("intent") or ""), "hook_first3")
    sfx = sync_sfx_with_motion(
        str(intent.get("intent") or ""),
        str(profile.get("visual_profile") or ""),
        assets={
            "low_riser": [Path("low.wav")],
            "high_riser": [Path("high.wav")],
            "magic_whoosh": [Path("whoosh.wav")],
            "deep_boom": [Path("boom.wav")],
        },
    )
    events = plan_visual_effects(
        hook_plan={
            "hook_type": "content",
            "hook_intent": intent.get("intent"),
            "hook_first3_status": "strong",
            "hook_first3_score": 7,
        },
        duration_s=8.0,
    )
    return {
        "intent": intent,
        "profile": profile,
        "rhythm": rhythm,
        "sfx": sfx,
        "events": events,
    }


def main() -> int:
    cases: List[Dict[str, Any]] = []

    risk = _hook_case("La salud no siempre avisa.", "risk_warning")
    cases.append(_result(
        "risk_warning_motion",
        risk["intent"].get("intent") == "risk_warning"
        and risk["profile"].get("visual_profile") == "tension_push"
        and risk["rhythm"].get("first_kick_frames") == 5
        and risk["rhythm"].get("second_kick_frames") == 10
        and risk["sfx"].get("sfx_motion_sync_type") == "dark_riser"
        and risk["profile"].get("visual_profile") != "emotional_push_in",
        risk,
        {"visual_profile": "tension_push", "kickframes": "5->10", "sfx": "dark_riser", "not": "emotional_push_in"},
    ))

    myth = _hook_case("Este seguro no va de miedo. Va de alivio para la familia.", "myth_debunk")
    cases.append(_result(
        "myth_flip_motion",
        myth["intent"].get("intent") == "myth_flip"
        and myth["profile"].get("visual_profile") == "calm_reveal"
        and myth["sfx"].get("sfx_motion_sync_type") != "deep_boom",
        myth,
        {"visual_profile": "calm_reveal", "no_aggressive_boom": True},
    ))

    business = _hook_case("Si eres autónomo, tú no eres solo una persona. Eres el motor.", "autonomous")
    cases.append(_result(
        "autonomous_business_motion",
        business["intent"].get("intent") == "autonomous_business_stakes"
        and business["profile"].get("visual_profile") == "business_punch"
        and business["sfx"].get("sfx_motion_sync_type") == "deep_boom",
        business,
        {"visual_profile": "business_punch", "deep_boom_allowed": True},
    ))

    emotional = _hook_case("A veces la mejor ayuda es la que aparece cuando más falta hace.", "emotional")
    cases.append(_result(
        "emotional_closure_motion",
        emotional["intent"].get("intent") == "emotional_closure"
        and emotional["profile"].get("visual_profile") == "soft_cinematic_push"
        and emotional["sfx"].get("aggressive_impact_allowed") is False,
        emotional,
        {"visual_profile": "soft_cinematic_push", "no_aggressive_impact": True},
    ))

    mask = plan_mask_reveal({"reason": "hook"})
    cases.append(_result(
        "mask_reveal_no_bbox_fallback",
        mask.get("fallback") == "sweeping_reveal"
        and mask.get("fallback_used") is True
        and mask.get("transition_type") == "sweeping_reveal",
        mask,
        {"fallback": "sweeping_reveal", "no_failure": True},
    ))

    generic = _hook_case("Hoy vengo a explicar una idea sencilla sobre seguros.", "generic")
    cases.append(_result(
        "generic_basic_motion",
        generic["profile"].get("visual_profile") == "basic_clean_motion"
        and bool((generic["events"][0] or {}).get("premium_visual_effect")) is False,
        generic,
        {"visual_profile": "basic_clean_motion", "premium_visual_effect": False},
    ))

    failed = [case for case in cases if not case["passed"]]
    for case in cases:
        print(f"[debug-motion-pack] {case['case']}={case['status']}")
    print(json.dumps({"passed": len(cases) - len(failed), "failed": len(failed), "cases": cases}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
