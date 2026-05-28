#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_publishable_gate import evaluate_clip_publishability  # noqa: E402
from src.services.vpi_transition_engine import apply_transition, choose_transition_type, plan_transition_events  # noqa: E402


def _first(plan):
    assert plan.events
    return plan.events[0]


def main() -> int:
    match_plan = plan_transition_events({
        "semantic_continuity": True,
        "related_events": [{"event": "followthrough"}],
        "reason": "speaker to broll continuity",
        "bbox": {"x": 0.32, "y": 0.2, "w": 0.35, "h": 0.4},
    })
    assert [event.duration_frames for event in match_plan.events[:2]] == [5, 10]
    match_result = apply_transition(Path("/tmp/nonexistent_match.mp4"), None, Path("/tmp/simulated_match.mp4"), _first(match_plan))
    assert match_result.applied is True

    glitch_plan = plan_transition_events({
        "editorial_type": "myth_debunk",
        "reason": "esto no es asi mito contraste",
    })
    assert _first(glitch_plan).transition_type == "glitch_clean"
    assert 5 <= _first(glitch_plan).duration_frames <= 10
    emotional_glitch = plan_transition_events({
        "transition_type": "glitch_clean",
        "editorial_type": "emotional_protection",
        "reason": "warm protection",
    })
    assert not emotional_glitch.enabled

    shape_plan = plan_transition_events({
        "transition_type": "shape_morph_beta",
        "shape_morph_viable": True,
        "shape_from": "riesgo",
        "shape_to": "escudo",
    })
    assert _first(shape_plan).transition_type == "shape_morph_beta"
    assert _first(shape_plan).metadata["shape_morph_beta"] is True
    shape_fallback = plan_transition_events({
        "transition_type": "shape_morph_beta",
        "shape_morph_viable": False,
        "bbox": {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.45},
    })
    assert _first(shape_fallback).transition_type == "mask_reveal"

    mask_plan = plan_transition_events({
        "transition_type": "mask_reveal",
        "bbox": {"x": 0.25, "y": 0.22, "w": 0.5, "h": 0.42},
        "direction": "center_out",
    })
    assert _first(mask_plan).target_bbox
    assert _first(mask_plan).metadata["mask_reveal_opacity_keyframes"][0]["opacity"] == 0.0
    mask_fallback = plan_transition_events({"transition_type": "clean_cut"})
    assert not mask_fallback.enabled

    sweep_plan = plan_transition_events({
        "narrative_event": "block_change",
        "important_broll": True,
        "related_events": [{"event": "settle"}],
    })
    assert _first(sweep_plan).transition_type == "sweeping_object_reveal"
    assert _first(sweep_plan).metadata["sweeping_reveal_mask_used"] is True
    assert [event.duration_frames for event in sweep_plan.events[:2]] == [5, 10]

    assert choose_transition_type({"editorial_type": "myth_debunk", "reason": "desmentido no es asi"}) == "glitch_clean"
    assert choose_transition_type({"concept_shift": "risk_to_protection"}) in {"shape_morph_beta", "mask_reveal"}
    assert choose_transition_type({"narrative_event": "block_change"}) == "sweeping_object_reveal"
    assert choose_transition_type({"semantic_continuity": True}) == "match_cut"

    qc = evaluate_clip_publishability({
        "hook_plan": {
            "hook_type": "risk_hook",
            "hook_first3_score": 8,
            "hook_first3_status": "strong",
            "hook_first3_perceptible": True,
            "hook_contract_satisfied": True,
        },
        "music": {"music_tracks_found": 1, "music_applied": True, "music_final_verified": True},
        "sfx": {"sfx_design_applied": True, "sfx_applied": True},
        "visual_effects": {"visual_effects_applied": True, "frame_rhythm_applied": True},
        "transitions": {"transition_events": [_first(sweep_plan).to_dict()], "final_output_uses_transition": False},
        "silence_edit_plan": {"enabled": True, "summary": {"pattern_interruption_opportunities": 1}},
        "editing_richness_score": 9,
        "editing_richness_status": "good",
        "words": [{"word": "test"}],
        "brand_treatment": {"applied": True},
        "output_qc": {"passed": True, "overall_score": 95},
        "vpi_score": 95,
        "virality_score": 90,
    })
    assert "transition_planned_not_in_final" in qc.publishable_warnings

    print("match_cut_frames_5_10=true")
    print("match_cut_simulated_applied=true")
    print("glitch_clean_editorial_guard=true")
    print("shape_morph_beta_and_fallback=true")
    print("mask_reveal_bbox_and_opacity=true")
    print("sweeping_object_reveal_frames_5_10=true")
    print("selector_rules=true")
    print("transition_qc_planned_not_final_warning=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
