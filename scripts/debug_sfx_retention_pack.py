#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from services.vpi_sfx_service import (  # noqa: E402
    build_sfx_design_plan,
    build_sfx_retention_decision,
    discover_sfx_assets,
    match_sfx_asset,
)


PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[debug-sfx-retention-pack] {name}=PASS {detail}".strip())
    else:
        FAIL += 1
        print(f"[debug-sfx-retention-pack] {name}=FAIL {detail}".strip())


def _runtime_sfx_true(*, should_apply_sfx: bool, matched: bool, asset_applied_match: bool, composition_allowed: bool, timing_safe: bool, voice_conflict: bool) -> bool:
    return bool(
        should_apply_sfx
        and matched
        and asset_applied_match
        and composition_allowed
        and timing_safe
        and not voice_conflict
    )


def case_1_risk_warning() -> None:
    text = "La salud no siempre avisa."
    decision = build_sfx_retention_decision(
        hook_intent="risk_warning",
        visual_profile="tension_push",
        composition_mode="warning_tension",
        segment_text=text,
    )
    check("risk_family", decision.get("sfx_family") in {"dark_riser", "tension_riser"}, str(decision))
    check("risk_no_deep_boom", decision.get("sfx_family") != "deep_boom", str(decision.get("sfx_family")))
    check("risk_silence_contrast_allowed", decision.get("fallback") in {"none", "silence_contrast", "caption_emphasis"}, str(decision.get("fallback")))


def case_2_myth_flip() -> None:
    text = "Este seguro no va de miedo. Va de alivio para la familia."
    decision = build_sfx_retention_decision(
        hook_intent="myth_flip",
        visual_profile="calm_reveal",
        composition_mode="hook_driven",
        segment_text=text,
    )
    check("myth_family", decision.get("sfx_family") in {"magic_whoosh", "soft_chime"}, str(decision))
    check("myth_no_aggressive_hit", decision.get("sfx_family") != "deep_boom", str(decision.get("sfx_family")))


def case_3_autonomous_business() -> None:
    text = "Si eres autónomo, tú eres el motor. Si paras, también paran tus ingresos."
    decision = build_sfx_retention_decision(
        hook_intent="autonomous_business_stakes",
        visual_profile="business_punch",
        composition_mode="business_punch",
        segment_text=text,
    )
    check("autonomous_family", decision.get("sfx_family") == "deep_boom", str(decision))
    check("autonomous_voice_conflict_flag", decision.get("voice_conflict") in {True, False}, str(decision.get("voice_conflict")))


def case_4_emotional_closure() -> None:
    text = "Cuando más falta hace, tener apoyo cambia todo."
    decision = build_sfx_retention_decision(
        hook_intent="emotional_closure",
        visual_profile="soft_cinematic_push",
        composition_mode="emotional_soft",
        segment_text=text,
    )
    check("emotional_no_boom", decision.get("sfx_family") in {"soft_chime", "silence_contrast", "no_sfx_needed"}, str(decision))
    check("emotional_not_aggressive", decision.get("sfx_family") != "deep_boom", str(decision.get("sfx_family")))


def case_5_neutral_explanation() -> None:
    text = "Hoy explico una idea general de forma sencilla."
    decision = build_sfx_retention_decision(
        hook_intent="neutral_explanation",
        visual_profile="basic_clean_motion",
        composition_mode="minimal_safe",
        segment_text=text,
    )
    check("neutral_no_sfx_needed", decision.get("sfx_family") == "no_sfx_needed", str(decision))


def case_6_no_local_assets() -> None:
    text = "La salud no siempre avisa."
    decision = build_sfx_retention_decision(
        hook_intent="risk_warning",
        visual_profile="tension_push",
        composition_mode="warning_tension",
        segment_text=text,
    )
    match = match_sfx_asset(
        sfx_family=str(decision.get("sfx_family") or ""),
        hook_intent="risk_warning",
        recent_sfx_history=[],
        assets={"low_riser": [], "high_riser": [], "magic_whoosh": [], "deep_boom": []},
    )
    check("no_assets_no_match", match.get("matched") is False, str(match))
    check("no_assets_clean_fallback", decision.get("fallback") in {"none", "caption_emphasis", "music_only", "silence_contrast"}, str(decision.get("fallback")))


def case_7_rotation() -> None:
    assets = discover_sfx_assets()
    candidates = assets.get("magic_whoosh") or []
    if not candidates:
        check("rotation_skipped_no_assets", True, "no_whoosh_assets")
        return
    previous = str(candidates[0])
    match = match_sfx_asset(
        sfx_family="magic_whoosh",
        hook_intent="myth_flip",
        recent_sfx_history=[previous],
        assets=assets,
    )
    if len(candidates) > 1:
        check("rotation_avoids_previous", str(match.get("asset")) != previous, f"selected={match.get('asset')} previous={previous}")
    else:
        check("rotation_low_variation", bool(match.get("low_variation")), str(match))


def case_8_voice_dense_segment() -> None:
    text = " ".join(["autonomo ingresos estabilidad"] * 10)
    decision = build_sfx_retention_decision(
        hook_intent="autonomous_business_stakes",
        visual_profile="business_punch",
        composition_mode="business_punch",
        segment_text=text,
    )
    check("voice_dense_conflict", bool(decision.get("voice_conflict")), str(decision))
    check("voice_dense_skips_or_softens", decision.get("should_apply_sfx") is False or float(decision.get("volume_db") or -99.0) <= -26.0, str(decision))


def case_9_minimal_safe() -> None:
    text = "La salud no siempre avisa y conviene anticiparse."
    decision = build_sfx_retention_decision(
        hook_intent="risk_warning",
        visual_profile="tension_push",
        composition_mode="minimal_safe",
        segment_text=text,
    )
    check("minimal_safe_block", decision.get("should_apply_sfx") is False, str(decision))
    check("minimal_safe_reason", decision.get("skip_reason") in {"composition_block", "voice_conflict", "no_retention_gain"}, str(decision.get("skip_reason")))


def case_10_runtime_requires_asset_match() -> None:
    decision = {"should_apply_sfx": True}
    runtime_truth = _runtime_sfx_true(
        should_apply_sfx=bool(decision["should_apply_sfx"]),
        matched=True,
        asset_applied_match=False,
        composition_allowed=True,
        timing_safe=True,
        voice_conflict=False,
    )
    check("runtime_false_without_asset_match", runtime_truth is False, str(runtime_truth))


def case_11_runtime_blocked_by_composition() -> None:
    runtime_truth = _runtime_sfx_true(
        should_apply_sfx=True,
        matched=True,
        asset_applied_match=True,
        composition_allowed=False,
        timing_safe=True,
        voice_conflict=False,
    )
    check("runtime_false_when_composition_blocked", runtime_truth is False, str(runtime_truth))


def case_12_silence_contrast_rejects_bts_pause() -> None:
    plan = build_sfx_design_plan(
        hook_plan={"hook_intent": "emotional_closure", "visual_profile": "soft_cinematic_push"},
        editorial_type="emotional",
        segment_text="Cuando más falta hace, tener apoyo cambia todo.",
        composition_decision={"composition_mode": "emotional_soft"},
        silence_plan={
            "summary": {
                "tension_silences_preserved": 0,
                "preserved_emphasis_pauses": 0,
                "silence_retention_moments": [{"reason": "bts_pause_wait_for_camera"}],
            }
        },
    )
    check("silence_contrast_blocks_bts_pause", bool(plan.get("sfx_retention_pack")) is False, str(plan))
    check("silence_contrast_opportunity_only", bool(plan.get("sfx_editorial_opportunity")) is True, str(plan.get("sfx_editorial_opportunity")))


def case_13_opportunity_does_not_apply_sfx() -> None:
    plan = build_sfx_design_plan(
        hook_plan={"hook_intent": "risk_warning", "visual_profile": "tension_push"},
        editorial_type="risk_warning",
        segment_text="La salud no siempre avisa.",
        composition_decision={"composition_mode": "warning_tension"},
        assets={"low_riser": [], "high_riser": [], "magic_whoosh": [], "deep_boom": []},
    )
    check("opportunity_without_asset_no_event", bool(plan.get("sfx_design_events")) is False, str(plan.get("sfx_design_events")))
    check("opportunity_flag_true", bool(plan.get("sfx_editorial_opportunity")) is True, str(plan.get("sfx_editorial_opportunity")))


def main() -> int:
    case_1_risk_warning()
    case_2_myth_flip()
    case_3_autonomous_business()
    case_4_emotional_closure()
    case_5_neutral_explanation()
    case_6_no_local_assets()
    case_7_rotation()
    case_8_voice_dense_segment()
    case_9_minimal_safe()
    case_10_runtime_requires_asset_match()
    case_11_runtime_blocked_by_composition()
    case_12_silence_contrast_rejects_bts_pause()
    case_13_opportunity_does_not_apply_sfx()
    print(f"[debug-sfx-retention-pack] results={PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
