#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from services.vpi_publishable_gate import build_final_qc_report  # noqa: E402


PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[debug-final-qc-pack] {name}=PASS {detail}".strip())
    else:
        FAIL += 1
        print(f"[debug-final-qc-pack] {name}=FAIL {detail}".strip())


def _base(**overrides):
    data = {
        "private_premium_status": "PRIVATE_PREMIUM_READY",
        "editing_richness": {
            "broll": False,
            "sfx": False,
            "visual_finish": False,
            "cinematic_finish_pack": False,
            "shot_rhythm_pack": False,
            "caption_overlay_pack": True,
            "composition_pack": True,
            "composition_quality": "good",
            "composition_runtime_applied": True,
            "layer_overload": False,
        },
        "composition_decision": {"composition_quality": "good", "layer_overload": False, "runtime_connected": True, "composition_pack": True},
        "first3_visual_contract": {"first3_visual_contract": {"hook_visible_before_1_5s": True, "caption_readable": True, "no_layer_overload": True, "motion_contextual": True}},
        "caption_overlay_pack": {"caption_overlay_actions": ["keyword_emphasis"]},
        "motion_pack": {"visual_effects_applied": True, "visual_effects_events": [{"motion_pack_contextual": True}]},
        "broll_metadata": {"broll_asset_applied_match": True},
        "sfx_metadata": {"sfx_asset_applied_match": True, "voice_conflict": False},
        "cinematic_finish": {"visual_finish": True, "finish_applied": True},
        "shot_rhythm": {"applied": True, "microcuts": [{"start_s": 1.1}], "pacing_score_before": 0.60, "pacing_score_after_estimate": 0.70},
        "audio_metadata": {"voice_buried": False, "music_too_loud": False},
        "subtitle_metadata": {"captions_rendered": True, "hook_first3_score": 6},
        "segment_text": "Texto editorial sólido y completo.",
    }
    data.update(overrides)
    return data


def main() -> int:
    c1 = build_final_qc_report(**_base())
    check("strong_clip_upload", c1["final_qc_status"] == "PASS" and c1["upload_recommendation"] == "UPLOAD", str(c1))

    c2 = build_final_qc_report(**_base(private_premium_status="PRIVATE_PREMIUM_LIMITED_ASSETS"))
    check("limited_assets_not_fail", c2["final_qc_status"] in {"PASS", "REVIEW"}, str(c2["final_qc_status"]))

    c3 = build_final_qc_report(**_base(editing_richness={"broll": True}, broll_metadata={"broll_asset_applied_match": False}))
    check("fake_broll_penalized", c3["final_qc_status"] in {"REVIEW", "FAIL"} and c3["premium_truth_score"] < 1.0, str(c3))

    c4 = build_final_qc_report(**_base(editing_richness={"sfx": True}, sfx_metadata={"sfx_asset_applied_match": False}))
    check("fake_sfx_penalized", c4["final_qc_status"] in {"REVIEW", "FAIL"} and c4["premium_truth_score"] < 1.0, str(c4))

    c5 = build_final_qc_report(**_base(editing_richness={"visual_finish": True}, cinematic_finish={"visual_finish": True, "finish_applied": False}))
    check("finish_fake_blocked", c5["final_qc_status"] in {"REVIEW", "FAIL"}, str(c5))

    c6 = build_final_qc_report(**_base(editing_richness={"shot_rhythm_pack": True}, shot_rhythm={"applied": False, "microcuts": []}))
    check("rhythm_metadata_only_penalized", c6["final_qc_status"] in {"REVIEW", "FAIL"}, str(c6))

    c7 = build_final_qc_report(**_base(caption_overlay_pack={"caption_overlay_actions": ["keyword_emphasis", "hook_overlay", "icon", "lower_third"], "layer_overload": True}))
    check("caption_overload_review", c7["final_qc_status"] in {"REVIEW", "FAIL"}, str(c7))

    c8 = build_final_qc_report(**_base(private_premium_status="DO_NOT_UPLOAD", segment_text="Ok, dale de nuevo. Cuando ocurre porque"))
    check("bts_or_incomplete_do_not_upload", c8["upload_recommendation"] == "DO_NOT_UPLOAD", str(c8))

    c9 = build_final_qc_report(**_base(editing_richness={"broll": False}))
    check("no_broll_not_fail", c9["final_qc_status"] in {"PASS", "REVIEW"}, str(c9["final_qc_status"]))

    c10 = build_final_qc_report(**_base(composition_decision={"composition_quality": "poor", "layer_overload": True}))
    check("layer_overload_penalized", c10["final_qc_status"] in {"REVIEW", "FAIL"}, str(c10["final_qc_status"]))

    c11 = build_final_qc_report(**_base(editing_richness={"caption_overlay_pack": True}, caption_overlay_pack={"caption_overlay_actions": []}))
    check("fake_caption_pack_penalized", c11["final_qc_status"] in {"REVIEW", "FAIL"}, str(c11))

    c12 = build_final_qc_report(
        **_base(
            private_premium_status="PRIVATE_PREMIUM_LIMITED_ASSETS",
            editing_richness={"broll": False, "broll_editorial_opportunity": True},
            broll_metadata={"broll_asset_applied_match": False},
        )
    )
    check("limited_assets_honest_not_fail", c12["final_qc_status"] in {"PASS", "REVIEW"} and c12["upload_recommendation"] != "DO_NOT_UPLOAD", str(c12))

    c13 = build_final_qc_report(
        **_base(
            editing_richness={"composition_pack": True, "composition_runtime_applied": False},
            composition_decision={"composition_quality": "good", "layer_overload": False, "runtime_connected": False, "composition_pack": False},
            first3_visual_contract={"first3_visual_contract": {"hook_visible_before_1_5s": False, "caption_readable": True, "no_layer_overload": True, "motion_contextual": False}, "status": "review"},
        )
    )
    check("fake_composition_pack_penalized", c13["final_qc_status"] in {"REVIEW", "FAIL"}, str(c13))

    c14 = build_final_qc_report(
        **_base(
            editing_richness={"motion_pack": True},
            motion_pack={"visual_effects_applied": True, "visual_effects_events": [{"motion_pack_contextual": False}]},
        )
    )
    check("fake_motion_pack_penalized", c14["final_qc_status"] in {"REVIEW", "FAIL"}, str(c14))

    c15_base = build_final_qc_report(**_base())
    c15_opp = build_final_qc_report(
        **_base(
            editing_richness={"broll": False, "sfx": False, "broll_editorial_opportunity": True, "sfx_editorial_opportunity": True},
            broll_metadata={"broll_asset_applied_match": False},
            sfx_metadata={"sfx_asset_applied_match": False, "voice_conflict": False},
        )
    )
    check("opportunity_does_not_improve_truth", c15_opp["premium_truth_score"] <= c15_base["premium_truth_score"], f"base={c15_base['premium_truth_score']} opp={c15_opp['premium_truth_score']}")

    print(f"[debug-final-qc-pack] results={PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
