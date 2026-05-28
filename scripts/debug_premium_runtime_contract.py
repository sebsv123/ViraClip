#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_premium_runtime import (  # noqa: E402
    PREMIUM_LAYERS_REQUESTED,
    VIRACLIP_PREMIUM_EDITING_DEFAULT,
    premium_runtime_contract,
    verify_final_filename_contract,
)
from src.services.vpi_publishable_gate import evaluate_clip_publishability  # noqa: E402


def _strong_clip(**overrides):
    clip = {
        "filename": "mastered_sfx_music_brand_trans_vfx_sub_broll_reframe_silence_clip_01.mp4",
        "hook_plan": {
            "hook_type": "risk_hook",
            "hook_first3_status": "strong",
            "hook_first3_score": 7,
            "hook_first3_final_verified": True,
            "hook_first3_perceptible": True,
            "hook_contract_satisfied": True,
        },
        "music": {"music_tracks_found": 1, "music_applied": True, "music_final_verified": True},
        "sfx": {
            "sfx_applied": True,
            "sfx_final_verified": True,
            "sfx_design_applied": True,
            "sfx_assets_available": {"low_risers": 1, "high_risers": 1, "whooshes": 1, "booms": 5},
        },
        "visual_effects": {
            "visual_effects_applied": True,
            "visual_effects_final_verified": True,
            "frame_rhythm_applied": True,
            "frame_rhythm_events": [{"group": "hook_transition", "frames": 5, "next_frames": 10}],
        },
        "transitions": {
            "transition_events": [{"transition_type": "sweeping_object_reveal"}],
            "transitions_applied": True,
            "final_output_uses_transition": True,
        },
        "silence_edit_plan": {"enabled": True, "summary": {"pattern_interruption_opportunities": 1}},
        "editorial_broll": [{
            "reason": "semantic clarity",
            "semantic_score": 0.8,
            "broll_transition_applied": True,
            "broll_is_image": True,
            "broll_ken_burns_applied": True,
        }],
        "editing_plan": {"caption_visual_support_plan": {"enabled": False}},
        "editing_richness_score": 10,
        "editing_richness_status": "strong",
        "words": [{"word": "test"}],
        "brand_treatment": {"applied": True},
        "output_qc": {"passed": True, "overall_score": 95},
        "vpi_score": 95,
        "virality_score": 90,
        "editorial_type": "risk_warning",
    }
    clip.update(overrides)
    return clip


def main() -> int:
    runtime = premium_runtime_contract(beta_clean=True)
    assert VIRACLIP_PREMIUM_EDITING_DEFAULT is True
    assert runtime["premium_runtime_enabled"] is True
    for layer in (
        "retention_plan",
        "premium_transitions",
        "visual_effects",
        "music",
        "sfx_design",
        "frame_rhythm",
        "broll_transitions",
        "retention_quality_gate",
    ):
        assert layer in PREMIUM_LAYERS_REQUESTED

    contract = verify_final_filename_contract(
        Path("mastered_sfx_music_brand_trans_vfx_sub_broll_reframe_silence_clip_01.mp4"),
        music={"music_applied": True},
        sfx={"sfx_applied": True},
        transitions={"transitions_applied": True},
        visual_effects={"visual_effects_applied": True},
        broll_events=[{"asset": "x"}],
    )
    assert contract["final_contract_ok"] is True

    no_music = _strong_clip(music={"music_tracks_found": 1, "music_applied": True, "music_final_verified": False})
    assert evaluate_clip_publishability(no_music).publishable_status.value != "ready_to_upload"

    no_sfx_assets = _strong_clip(sfx={
        "sfx_applied": False,
        "sfx_final_verified": False,
        "sfx_warning": "sfx_missing_worker_assets",
        "sfx_assets_available": {"low_risers": 0, "high_risers": 0, "whooshes": 0, "booms": 0},
    })
    assert evaluate_clip_publishability(no_sfx_assets).retention_quality_status != "strong"

    no_transition = _strong_clip(transitions={
        "transition_events": [{"transition_type": "sweeping_object_reveal"}],
        "transitions_applied": False,
        "final_output_uses_transition": False,
    })
    assert "transition_planned_not_in_final" in evaluate_clip_publishability(no_transition).publishable_warnings

    no_vfx = _strong_clip(visual_effects={"visual_effects_applied": True, "visual_effects_final_verified": False})
    assert evaluate_clip_publishability(no_vfx).publishable_status.value != "ready_to_upload"

    weak_hook = _strong_clip(hook_plan={
        "hook_type": "risk_hook",
        "hook_first3_status": "acceptable",
        "hook_first3_score": 5,
        "hook_first3_final_verified": True,
        "hook_contract_satisfied": True,
    })
    assert evaluate_clip_publishability(weak_hook).publishable_status.value != "ready_to_upload"

    dry_broll = _strong_clip(editorial_broll=[{
        "reason": "semantic clarity",
        "semantic_score": 0.8,
        "broll_transition_applied": False,
        "broll_is_image": True,
        "broll_ken_burns_applied": False,
    }])
    gate = evaluate_clip_publishability(dry_broll)
    assert "static_broll_without_kenburns" in gate.publishable_warnings
    assert gate.publishable_status.value != "ready_to_upload"

    plain = {
        "hook_plan": {"hook_type": "risk_hook", "hook_first3_status": "weak", "hook_first3_score": 2},
        "music": {"music_tracks_found": 1, "music_applied": False, "music_final_verified": False},
        "visual_effects": {"visual_effects_applied": False},
        "transitions": {"transition_events": [{"transition_type": "match_cut"}], "final_output_uses_transition": False},
        "editing_richness_status": "too_plain",
        "words": [{"word": "test"}],
        "vpi_score": 95,
        "virality_score": 90,
    }
    assert evaluate_clip_publishability(plain).publishable_status.value != "ready_to_upload"

    print("premium_runtime_enabled=true")
    print("pipeline_order_contract=true")
    print("music_required_if_tracks_found=true")
    print("sfx_missing_assets_blocks_strong=true")
    print("transition_required_if_planned=true")
    print("vfx_required_if_non_weak=true")
    print("hook_first3_strong_required=true")
    print("filename_contract=true")
    print("retention_gate_blocks_plain_outputs=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
