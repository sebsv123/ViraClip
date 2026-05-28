#!/usr/bin/env python3
"""Offline checks for VPI B-roll phrase relevance gate."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.services.vpi_broll_intent import assess_broll_relevance  # noqa: E402


CASES = [
    {
        "name": "documents rejected for emotional family phrase",
        "phrase": "personas que dependen de ti familia protegida emotional family responsibility",
        "category": "documents_admin",
        "intent_type": "family_responsibility",
        "expected": False,
    },
    {
        "name": "advisor accepted for responsibility",
        "phrase": "esto va de responsabilidad asesor familiar family responsibility",
        "category": "advisor_consultation",
        "intent_type": "family_responsibility",
        "expected": True,
    },
    {
        "name": "documents accepted only for coverage",
        "phrase": "antes de contratar una póliza documentos de cobertura coverage explanation",
        "category": "documents_admin",
        "intent_type": "coverage_explanation",
        "expected": True,
    },
    {
        "name": "generic office rejected for family phrase",
        "phrase": "tu pareja o tus hijos dependen de ti oficina generica family responsibility",
        "category": "generic_office",
        "intent_type": "family_responsibility",
        "expected": False,
    },
]


def main() -> int:
    failures = 0
    for case in CASES:
        ok, score, reason = assess_broll_relevance(
            phrase=case["phrase"],
            category=case["category"],
            intent_type=case["intent_type"],
            central_topic="life_insurance_family_protection",
        )
        passed = ok == case["expected"]
        failures += 0 if passed else 1
        print(
            f"- {'OK' if passed else 'FAIL'} {case['name']}: "
            f"{'accepted' if ok else 'rejected'} score={score:.1f} reason={reason}"
        )
    print(f"summary: ok={len(CASES) - failures} fail={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
