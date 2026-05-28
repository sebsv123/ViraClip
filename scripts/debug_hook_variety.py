#!/usr/bin/env python3
"""Offline checks for VPI hook variety and first-4s contract."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.services.vpi_hook_engine import build_hook_plan  # noqa: E402


def _words(text: str):
    out = []
    t = 0.0
    for word in text.split():
        out.append({"word": word, "start": t, "end": t + 0.22})
        t += 0.28
    return out


CASES = [
    {
        "name": "emotional clip",
        "editorial_type": "emotional_protection",
        "text": "No se trata de vivir con miedo se trata de proteger a las personas que dependen de ti",
        "expect": lambda p: p.hook_family == "emotional_open" and p.hook_first_4s_score >= 2 and p.broll_delay_until_s >= 4.2,
    },
    {
        "name": "objection clip",
        "editorial_type": "client_objection",
        "text": "El seguro de vida no es solo para personas mayores la realidad es que va de responsabilidad",
        "expect": lambda p: p.hook_family == "objection_breaker" and p.hook_first_4s_score >= 2,
    },
    {
        "name": "weak intro",
        "editorial_type": "weak_intro",
        "text": "Hola soy Sebastian en este momento les vengo a hablar de seguros",
        "expect": lambda p: p.low_publish_priority and p.hook_type == "weak_intro",
    },
]


def main() -> int:
    failures = 0
    for case in CASES:
        plan = build_hook_plan(
            text=case["text"],
            editorial_type=case["editorial_type"],
            vpi_score=80,
            matched_patterns=[case["editorial_type"]],
            word_timestamps=_words(case["text"]),
            clip_duration=18.0,
            editing_plan={},
            theme={"central_topic": "life_insurance_family_protection"},
        )
        ok = bool(case["expect"](plan))
        failures += 0 if ok else 1
        print(
            f"- {'OK' if ok else 'FAIL'} {case['name']}: "
            f"family={plan.hook_family} strategy={plan.hook_opening_strategy} "
            f"first4={plan.hook_first_4s_score} signals={','.join(plan.hook_first_4s_signals)} "
            f"broll_delay={plan.broll_delay_until_s:.1f} low_priority={plan.low_publish_priority}"
        )
    print(f"summary: ok={len(CASES) - failures} fail={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
