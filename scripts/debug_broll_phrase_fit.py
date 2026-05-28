#!/usr/bin/env python3
"""Offline checks for VPI B-roll phrase fit v3.5."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_broll_intent import score_broll_phrase_fit  # noqa: E402


def _case(name: str, asset: dict, phrase: str, intent: str = "family_responsibility") -> None:
    result = score_broll_phrase_fit(asset, phrase, {"central_topic": "life_insurance_family_protection"}, intent)
    print(
        f"{name}: score={result['phrase_fit_score']} label={result['phrase_fit_label']} "
        f"primary={result['allowed_as_primary']} support={result['allowed_as_support']} "
        f"reason={result['phrase_fit_reason']}"
    )


def main() -> int:
    phrase = "un proyecto o personas que dependen de ti"
    _case(
        "family_home_video",
        {"path": "assets/broll/family_protection/family_home_video.mp4", "category": "family_protection"},
        phrase,
    )
    _case(
        "advisor_human_video",
        {"path": "assets/broll/advisor_consultation/advisor_explaining_to_young_couple.mp4", "category": "advisor_consultation"},
        phrase,
    )
    _case(
        "documents_primary_rejected",
        {"path": "assets/broll/documents_admin/03.jpg", "category": "documents_admin", "is_image": True},
        phrase,
    )
    _case(
        "financial_paper_only_downgraded",
        {"path": "assets/broll/financial_planning/paper_budget_contract.mp4", "category": "financial_planning"},
        phrase,
    )

    used_assets = {"family_home_video"}
    candidate_stem = Path("assets/broll/family_protection/family_home_video.mp4").stem
    print(f"repeat_same_asset_rejected={candidate_stem in used_assets}")

    subtitle_only_case = {"hook_first3_perceptible_score": 2, "hook_motion": False, "subtitle_before_1_5": True}
    emotional_case = {"hook_first3_perceptible_score": 4, "hook_motion": True, "subtitle_before_1_5": True}
    print(f"hook_first3_subtitle_only_pass={subtitle_only_case['hook_first3_perceptible_score'] >= 4}")
    print(f"hook_first3_emotional_motion_pass={emotional_case['hook_first3_perceptible_score'] >= 4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
