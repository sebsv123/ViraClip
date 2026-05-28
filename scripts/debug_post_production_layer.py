#!/usr/bin/env python3
"""Offline checks for VPI Post-Production Layer v3.6 planning."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_publishable_gate import evaluate_clip_publishability  # noqa: E402
from src.services.vpi_visual_effects_service import plan_visual_effects  # noqa: E402


def first3_score(case: dict) -> dict:
    score = 0
    signals: list[str] = []
    if case.get("motion"):
        score += 2
        signals.append("visible_hook_motion")
    if case.get("subtitle"):
        score += 2
        signals.append("hook_subtitle_before_1_5s")
    if case.get("rhythm"):
        score += 1
        signals.append("silence_cut_before_3s")
    if case.get("sound"):
        score += 1
        signals.append("sound_layer")
    if case.get("emphasis"):
        score += 1
        signals.append("visual_emphasis")
    missing = [name for name in ("motion", "subtitle", "rhythm", "sound", "emphasis") if not case.get(name)]
    return {"score": score, "perceptible": score >= 4, "signals": signals, "missing": missing}


def main() -> int:
    no_broll_events = plan_visual_effects(
        hook_plan={"hook_type": "emotional_hook", "rendered": True, "hook_motion_rendered": True},
        no_broll=True,
        editorial_type="emotional_protection",
        duration_s=30.0,
    )
    print(f"no_broll_visual_effects_applied={bool(no_broll_events)} events={no_broll_events}")
    print(f"speaker_focus_real_effects={bool(no_broll_events)}")

    emotional = first3_score({"motion": True, "subtitle": True, "rhythm": False, "sound": False, "emphasis": False})
    objection = first3_score({"motion": True, "subtitle": True, "rhythm": True, "sound": False, "emphasis": False})
    print(f"emotional_first3={emotional}")
    print(f"objection_first3={objection}")

    plain_clip = {
        "hook_plan": {
            "hook_type": "emotional_hook",
            "hook_first3_perceptible": False,
            "hook_first3_perceptible_score": 2,
            "hook_contract_satisfied": True,
        },
        "editing_richness_score": 2,
        "editing_richness_status": "too_plain",
        "editing_richness_warnings": ["visually_too_plain"],
        "output_qc": {"passed": True, "overall_score": 90},
        "brand_treatment": {"applied": True},
        "words": [{"word": "test"}],
        "editorial_type": "emotional_protection",
        "vpi_score": 80,
        "virality_score": 75,
    }
    gate = evaluate_clip_publishability(plain_clip)
    print(f"plain_clip_publishable={gate.publishable_status.value} ready={gate.publishable_status.value == 'ready_to_upload'} warnings={gate.publishable_warnings}")

    music_required = {
        **plain_clip,
        "hook_plan": {
            "hook_type": "risk_hook",
            "hook_first3_perceptible": True,
            "hook_first3_perceptible_score": 7,
            "hook_first3_score": 7,
            "hook_first3_status": "strong",
            "hook_contract_satisfied": True,
        },
        "music": {"music_tracks_found": 1, "music_applied": False},
        "visual_effects": {"visual_effects_applied": True},
        "sfx": {"sfx_design_applied": True, "sfx_applied": True},
        "editing_richness_status": "good",
        "editing_richness_warnings": [],
    }
    music_gate = evaluate_clip_publishability(music_required)
    assert music_gate.publishable_status.value != "ready_to_upload"
    print("music_tracks_found_requires_final_verified=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
