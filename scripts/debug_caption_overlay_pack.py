#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.caption_service import plan_caption_overlay_pack  # noqa: E402
from src.services.vpi_hook_engine import classify_hook_intent  # noqa: E402


def _words(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    t = 0.0
    for word in text.split():
        out.append({"word": word, "text": word, "start": t, "end": t + 0.22, "score": 0.7})
        t += 0.24
    return out


def _case(name: str, passed: bool, actual: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case": name,
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "actual": actual,
        "expected": expected,
    }


def main() -> int:
    cases: List[Dict[str, Any]] = []

    text = "Este seguro no va de miedo. Va de alivio para la familia."
    intent = classify_hook_intent(text, editorial_type="myth_debunk")
    plan = plan_caption_overlay_pack(text, hook_intent=str(intent.get("intent")), editorial_type="decesos", words=_words(text), local_icon_assets=[])
    cases.append(_case(
        "decesos_myth_flip",
        "alivio" in plan.get("keyword_emphasis_terms", [])
        and "familia" in plan.get("keyword_emphasis_terms", [])
        and (plan.get("hook_overlay") or {}).get("applied") is True
        and "miedo" in str((plan.get("hook_overlay") or {}).get("text") or "").lower(),
        {"intent": intent, "plan": plan},
        {"keywords": ["alivio", "familia"], "hook_overlay_contains": "miedo", "sensitive_respected": True},
    ))

    text = "La salud no siempre avisa."
    intent = classify_hook_intent(text, editorial_type="risk_warning")
    plan = plan_caption_overlay_pack(text, hook_intent=str(intent.get("intent")), editorial_type="salud", words=_words(text), local_icon_assets=[])
    cases.append(_case(
        "salud_warning",
        intent.get("intent") == "risk_warning"
        and (plan.get("hook_overlay") or {}).get("applied") is True
        and (plan.get("caption_icon") or {}).get("applied") is False,
        {"intent": intent, "plan": plan},
        {"intent": "risk_warning", "hook_overlay": True, "no_aggressive_icon": True},
    ))

    text = "Si eres autónomo, tú no eres solo una persona. Eres el motor."
    intent = classify_hook_intent(text, editorial_type="autonomous")
    plan = plan_caption_overlay_pack(text, hook_intent=str(intent.get("intent")), editorial_type="autonomos", words=_words(text), local_icon_assets=[])
    terms = plan.get("keyword_emphasis_terms", [])
    cases.append(_case(
        "autonomo_keywords_icon_optional",
        any("aut" in str(term).lower() for term in terms)
        and "motor" in terms
        and (plan.get("caption_icon") or {}).get("reason") in {"no_local_asset", "too_many_elements"},
        {"intent": intent, "plan": plan},
        {"keywords": ["autónomo", "motor"], "icon": "optional_or_clean_skip"},
    ))

    text = " ".join(["Esta es una explicación larga"] * 8)
    plan = plan_caption_overlay_pack(text, hook_intent="practical_advice", editorial_type="salud", words=_words(text), local_icon_assets=[])
    density_actions = [item.get("action") for item in plan.get("density_guard_actions", [])]
    cases.append(_case(
        "long_subtitle_density_guard",
        "skip_overlay" in density_actions and "skip_icon" in density_actions,
        {"plan": plan},
        {"density_guard": ["skip_overlay", "skip_icon"]},
    ))

    text = "Si eres autónomo, tú eres el motor."
    plan = plan_caption_overlay_pack(text, hook_intent="autonomous_business_stakes", editorial_type="autonomos", words=_words(text), local_icon_assets=[])
    cases.append(_case(
        "no_local_icons_clean_skip",
        (plan.get("caption_icon") or {}).get("applied") is False
        and (plan.get("caption_icon") or {}).get("reason") in {"no_local_asset", "too_many_elements"},
        {"plan": plan},
        {"icon_skip": "no_local_asset_or_density"},
    ))

    text = "Hoy vamos a explicar una idea sencilla."
    plan = plan_caption_overlay_pack(text, hook_intent="neutral_explanation", editorial_type="generic", words=_words(text), local_icon_assets=[], enable_lower_third=False)
    cases.append(_case(
        "normal_subtitles_only",
        plan.get("caption_overlay_pack") is False,
        {"plan": plan},
        {"caption_overlay_pack": False},
    ))

    failed = [case for case in cases if not case["passed"]]
    for case in cases:
        print(f"[debug-caption-overlay-pack] {case['case']}={case['status']}")
    print(json.dumps({"passed": len(cases) - len(failed), "failed": len(failed), "cases": cases}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
