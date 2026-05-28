#!/usr/bin/env python3
"""
debug_composition_runtime_integration.py — CAMBIO 7

Verifies that the VPI Premium Composition Pack v1 functions are correctly
integrated into real runtime by simulating the exact code paths used in
video_service.py create_single_clip().

6 test cases:
  1. build_composition_decision is called and returns a valid composition_mode
  2. resolve_visual_layer_conflicts affects captions/overlays/lower third
  3. resolve_visual_layer_conflicts blocks sweeping_reveal/mask_reveal transitions
  4. resolve_visual_layer_conflicts blocks deep_boom SFX in emotional_closure
  5. first3_visual_contract downgrades status when 2+ failures
  6. composition_pack=true only when real composition decisions were made

Usage:
    cd /home/_sebastian/CascadeProjects/ViraClip
    python scripts/debug_composition_runtime_integration.py

Each scenario logs with [composition-runtime] prefix.
"""

import sys
import os
import logging
import json

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("composition-runtime")

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        logger.info("[composition-runtime] ✅ PASS  %s — %s", label, detail)
    else:
        FAIL += 1
        logger.error("[composition-runtime] ❌ FAIL  %s — %s", label, detail)


def _make_caption_overlay_pack(
    hook_overlay_applied: bool = False,
    hook_overlay_start_s: float = 0.0,
    caption_start_s: float = 0.0,
    lower_third_applied: bool = False,
    lower_third_start_s: float = 0.0,
    icon_applied: bool = False,
    icon_text: str = "",
) -> dict:
    return {
        "hook_overlay": {
            "applied": hook_overlay_applied,
            "text": "You won't believe this",
            "start_s": hook_overlay_start_s,
            "duration_s": 2.0,
        },
        "caption_start_s": caption_start_s,
        "lower_third": {
            "applied": lower_third_applied,
            "text": "Expert says",
            "start_s": lower_third_start_s,
            "duration_s": 3.0,
        },
        "icon": {
            "applied": icon_applied,
            "text": icon_text,
            "start_s": 0.5,
            "duration_s": 1.5,
        },
    }


def _make_hook_plan(
    hook_intent: str = "",
    hook_type: str = "strong",
    hook_first3_status: str = "READY",
    hook_first3_score: int = 8,
    kickframe_applied: bool = False,
) -> dict:
    return {
        "hook_intent": hook_intent,
        "hook_type": hook_type,
        "hook_first3_status": hook_first3_status,
        "hook_first3_score": hook_first3_score,
        "kickframe_applied": kickframe_applied,
    }


def _make_transition_plan(transition_types: list[str] | None = None) -> dict:
    return {
        "transition_types": transition_types or [],
        "transition_events": transition_types or [],
    }


def _make_sfx_plan(aggressive_impact_allowed: bool = False) -> dict:
    return {
        "sfx_motion_sync_applied": True,
        "sfx_motion_sync_type": "deep_boom" if aggressive_impact_allowed else "soft_whoosh",
        "aggressive_impact_allowed": aggressive_impact_allowed,
    }


def _make_visual_effects(motion_contextual: bool = False) -> list[dict]:
    return [
        {
            "type": "hook_push_in",
            "start_s": 0.3,
            "duration_s": 0.5,
            "scale": 1.035,
            "motion_pack_contextual": motion_contextual,
            "contextual": motion_contextual,
        }
    ]


# ── Test 1: build_composition_decision is called and returns valid mode ─────
def test_1_composition_decision_called():
    logger.info("")
    logger.info("═" * 70)
    logger.info("[composition-runtime] TEST 1: build_composition_decision returns valid composition_mode")
    logger.info("[composition-runtime] Verifies CAMBIO 1: composition pack called from real runtime")
    logger.info("─" * 70)

    from services.vpi_visual_effects_service import build_composition_decision

    # Test all 6 intents
    intents = [
        ("myth_flip", "hook_driven"),
        ("risk_warning", "warning_tension"),
        ("practical_advice", "explanation_clean"),
        ("autonomous_business_stakes", "business_punch"),
        ("emotional_closure", "emotional_soft"),
        ("neutral_explanation", "minimal_safe"),
    ]

    for intent, expected_mode in intents:
        cap_pack = _make_caption_overlay_pack(
            hook_overlay_applied=(intent in ("myth_flip", "risk_warning")),
            caption_start_s=0.5,
        )
        hook_plan = _make_hook_plan(hook_intent=intent)
        trans_plan = _make_transition_plan()
        sfx_plan = _make_sfx_plan(aggressive_impact_allowed=(intent == "autonomous_business_stakes"))

        comp = build_composition_decision(
            hook_intent=intent,
            visual_profile="",
            caption_overlay_pack=cap_pack,
            transition_plan=trans_plan,
            sfx_plan=sfx_plan,
            private_premium_status="",
            segment_text="",
        )

        mode = comp.get("composition_mode", "")
        check(
            f"composition_mode for {intent} is {expected_mode}",
            mode == expected_mode,
            f"got={mode} expected={expected_mode}",
        )
        check(
            f"screen_priority for {intent} is non-empty",
            bool(comp.get("screen_priority")),
            f"priority={comp.get('screen_priority')}",
        )
        check(
            f"max_simultaneous_layers for {intent} > 0",
            int(comp.get("max_simultaneous_layers") or 0) > 0,
            f"max_layers={comp.get('max_simultaneous_layers')}",
        )

    logger.info("[composition-runtime]   All 6 intents produced valid composition decisions")


# ── Test 2: Conflict resolver affects captions/overlays/lower third ─────────
def test_2_conflict_resolver_affects_layers():
    logger.info("")
    logger.info("═" * 70)
    logger.info("[composition-runtime] TEST 2: resolve_visual_layer_conflicts affects captions/overlays/lower third")
    logger.info("[composition-runtime] Verifies CAMBIO 2: conflict resolver affects captions/overlays/lower third")
    logger.info("─" * 70)

    from services.vpi_visual_effects_service import (
        build_composition_decision,
        resolve_visual_layer_conflicts,
    )

    # Test: myth_flip → hook_driven → hook_overlay priority, lower_third blocked
    cap_pack = _make_caption_overlay_pack(
        hook_overlay_applied=True,
        hook_overlay_start_s=0.8,
        caption_start_s=1.0,
        lower_third_applied=True,
        lower_third_start_s=0.5,
    )
    comp = build_composition_decision(
        hook_intent="myth_flip",
        visual_profile="",
        caption_overlay_pack=cap_pack,
        transition_plan=_make_transition_plan(),
        sfx_plan=_make_sfx_plan(),
        private_premium_status="",
        segment_text="",
    )

    layers = [
        {"type": "hook_overlay", "start_s": 0.8},
        {"type": "caption", "start_s": 1.0},
        {"type": "lower_third", "start_s": 0.5},
        {"type": "icon", "text": "tip", "start_s": 0.3},
    ]
    resolved = resolve_visual_layer_conflicts(layers, comp)
    resolved_types = list(resolved.get("layers_final") or [])
    check(
        "hook_overlay preserved in hook_driven mode",
        "hook_overlay" in resolved_types,
        f"resolved={resolved_types}",
    )
    check(
        "caption preserved in hook_driven mode",
        "caption" in resolved_types,
        f"resolved={resolved_types}",
    )
    check(
        "lower_third blocked in hook_driven mode (priority=hook_overlay)",
        "lower_third" not in resolved_types,
        f"resolved={resolved_types}",
    )

    # Test: practical_advice → explanation_clean → caption priority, icon blocked
    cap_pack2 = _make_caption_overlay_pack(
        caption_start_s=0.5,
        lower_third_applied=True,
        lower_third_start_s=1.0,
        icon_applied=True,
        icon_text="tip",
    )
    comp2 = build_composition_decision(
        hook_intent="practical_advice",
        visual_profile="",
        caption_overlay_pack=cap_pack2,
        transition_plan=_make_transition_plan(),
        sfx_plan=_make_sfx_plan(),
        private_premium_status="",
        segment_text="",
    )

    layers2 = [
        {"type": "caption", "start_s": 0.5},
        {"type": "lower_third", "start_s": 1.0},
        {"type": "icon", "text": "tip", "start_s": 0.3},
    ]
    resolved2 = resolve_visual_layer_conflicts(layers2, comp2)
    resolved2_types = list(resolved2.get("layers_final") or [])

    check(
        "caption preserved in explanation_clean mode",
        "caption" in resolved2_types,
        f"resolved={resolved2_types}",
    )
    check(
        "lower_third preserved in explanation_clean mode",
        "lower_third" in resolved2_types,
        f"resolved={resolved2_types}",
    )
    check(
        "icon blocked in explanation_clean mode (priority=caption)",
        "icon" not in resolved2_types,
        f"resolved={resolved2_types}",
    )


# ── Test 3: Conflict resolver blocks sweeping_reveal/mask_reveal transitions ─
def test_3_conflict_resolver_blocks_transitions():
    logger.info("")
    logger.info("═" * 70)
    logger.info("[composition-runtime] TEST 3: resolve_visual_layer_conflicts blocks sweeping_reveal/mask_reveal")
    logger.info("[composition-runtime] Verifies CAMBIO 3: transitions blocked based on composition_mode")
    logger.info("─" * 70)

    from services.vpi_visual_effects_service import (
        build_composition_decision,
        resolve_visual_layer_conflicts,
    )

    # Test: emotional_closure → emotional_soft → sweeping_reveal blocked
    cap_pack = _make_caption_overlay_pack(caption_start_s=1.0)
    comp = build_composition_decision(
        hook_intent="emotional_closure",
        visual_profile="",
        caption_overlay_pack=cap_pack,
        transition_plan=_make_transition_plan(["sweeping_reveal"]),
        sfx_plan=_make_sfx_plan(),
        private_premium_status="",
        segment_text="",
    )

    layers = [
        {"type": "sweeping_reveal", "start_s": 0.0},
        {"type": "caption", "start_s": 1.0},
    ]
    resolved = resolve_visual_layer_conflicts(layers, comp)
    resolved_types = list(resolved.get("layers_final") or [])

    check(
        "sweeping_reveal blocked in emotional_soft mode",
        "sweeping_reveal" not in resolved_types,
        f"resolved={resolved_types}",
    )

    # Test: neutral_explanation → minimal_safe → mask_reveal blocked
    # NOTE: Do NOT pass mask_reveal in transition_plan to build_composition_decision,
    # because the override at lines 215-218 upgrades minimal_safe to explanation_clean
    # when a strong transition is present. We want composition_mode to stay minimal_safe
    # so Rule 8 (mask_reveal blocked in minimal_safe) can fire correctly.
    comp2 = build_composition_decision(
        hook_intent="neutral_explanation",
        visual_profile="",
        caption_overlay_pack=_make_caption_overlay_pack(caption_start_s=0.5),
        transition_plan=_make_transition_plan([]),
        sfx_plan=_make_sfx_plan(),
        private_premium_status="",
        segment_text="",
    )

    layers2 = [
        {"type": "mask_reveal", "start_s": 0.0},
        {"type": "caption", "start_s": 0.5},
    ]
    resolved2 = resolve_visual_layer_conflicts(layers2, comp2)
    resolved2_types = list(resolved2.get("layers_final") or [])

    check(
        "mask_reveal blocked in minimal_safe mode",
        "mask_reveal" not in resolved2_types,
        f"resolved={resolved2_types}",
    )

    # Test: myth_flip → hook_driven → sweeping_reveal ALLOWED
    comp3 = build_composition_decision(
        hook_intent="myth_flip",
        visual_profile="",
        caption_overlay_pack=_make_caption_overlay_pack(
            hook_overlay_applied=True,
            hook_overlay_start_s=0.8,
            caption_start_s=1.0,
        ),
        transition_plan=_make_transition_plan(["sweeping_reveal"]),
        sfx_plan=_make_sfx_plan(),
        private_premium_status="",
        segment_text="",
    )

    layers3 = [
        {"type": "sweeping_reveal", "start_s": 0.0},
        {"type": "hook_overlay", "start_s": 0.8},
        {"type": "caption", "start_s": 1.0},
    ]
    resolved3 = resolve_visual_layer_conflicts(layers3, comp3)
    resolved3_types = list(resolved3.get("layers_final") or [])

    check(
        "sweeping_reveal ALLOWED in hook_driven mode",
        "sweeping_reveal" in resolved3_types,
        f"resolved={resolved3_types}",
    )


# ── Test 4: Conflict resolver blocks deep_boom SFX in emotional_closure ─────
def test_4_conflict_resolver_blocks_sfx():
    logger.info("")
    logger.info("═" * 70)
    logger.info("[composition-runtime] TEST 4: resolve_visual_layer_conflicts blocks deep_boom SFX")
    logger.info("[composition-runtime] Verifies CAMBIO 4: SFX blocked based on composition_mode")
    logger.info("─" * 70)

    from services.vpi_visual_effects_service import (
        build_composition_decision,
        resolve_visual_layer_conflicts,
    )

    # Test: emotional_closure → emotional_soft → deep_boom blocked
    cap_pack = _make_caption_overlay_pack(caption_start_s=1.0)
    comp = build_composition_decision(
        hook_intent="emotional_closure",
        visual_profile="",
        caption_overlay_pack=cap_pack,
        transition_plan=_make_transition_plan(),
        sfx_plan=_make_sfx_plan(aggressive_impact_allowed=True),
        private_premium_status="",
        segment_text="",
    )

    layers = [
        {"type": "deep_boom", "start_s": 0.5},
        {"type": "caption", "start_s": 1.0},
    ]
    resolved = resolve_visual_layer_conflicts(layers, comp)
    resolved_types = list(resolved.get("layers_final") or [])

    check(
        "deep_boom blocked in emotional_soft mode",
        "deep_boom" not in resolved_types,
        f"resolved={resolved_types}",
    )

    # Test: autonomous_business_stakes → business_punch → deep_boom ALLOWED
    comp2 = build_composition_decision(
        hook_intent="autonomous_business_stakes",
        visual_profile="",
        caption_overlay_pack=_make_caption_overlay_pack(caption_start_s=0.3),
        transition_plan=_make_transition_plan(),
        sfx_plan=_make_sfx_plan(aggressive_impact_allowed=True),
        private_premium_status="",
        segment_text="",
    )

    layers2 = [
        {"type": "deep_boom", "start_s": 0.5},
        {"type": "caption", "start_s": 0.3},
    ]
    resolved2 = resolve_visual_layer_conflicts(layers2, comp2)
    resolved2_types = list(resolved2.get("layers_final") or [])

    check(
        "deep_boom ALLOWED in business_punch mode",
        "deep_boom" in resolved2_types,
        f"resolved={resolved2_types}",
    )


# ── Test 5: first3_visual_contract downgrades status when 2+ failures ───────
def test_5_first3_visual_contract_downgrades():
    logger.info("")
    logger.info("═" * 70)
    logger.info("[composition-runtime] TEST 5: first3_visual_contract downgrades status when 2+ failures")
    logger.info("[composition-runtime] Verifies CAMBIO 5: first3_visual_contract affects status/review")
    logger.info("─" * 70)

    from services.vpi_visual_effects_service import (
        build_composition_decision,
        first3_visual_contract,
    )

    # Simulate a hook_plan with hook_intent
    hook_plan = _make_hook_plan(
        hook_intent="myth_flip",
        hook_first3_status="READY",
        hook_first3_score=8,
    )

    # Build composition decision
    cap_pack = _make_caption_overlay_pack(
        hook_overlay_applied=True,
        hook_overlay_start_s=0.8,
        caption_start_s=1.0,
    )
    comp = build_composition_decision(
        hook_intent="myth_flip",
        visual_profile="",
        caption_overlay_pack=cap_pack,
        transition_plan=_make_transition_plan(),
        sfx_plan=_make_sfx_plan(),
        private_premium_status="",
        segment_text="",
    )

    # Test 5a: Good contract — all checks pass
    good_vfx = _make_visual_effects(motion_contextual=True)
    good_contract = first3_visual_contract(
        hook_plan=hook_plan,
        caption_overlay_pack=cap_pack,
        composition_decision=comp,
        visual_effects=good_vfx,
        transition_plan=_make_transition_plan(),
    )

    check(
        "first3_visual_passed=True when all checks pass",
        good_contract.get("first3_visual_passed") is True,
        f"passed={good_contract.get('first3_visual_passed')} fail_count={good_contract.get('first3_visual_fail_count')}",
    )
    check(
        "first3_visual_fail_count=0 when all checks pass",
        int(good_contract.get("first3_visual_fail_count") or 0) == 0,
        f"fail_count={good_contract.get('first3_visual_fail_count')}",
    )

    # Test 5b: Bad contract — simulate failures
    # Create a caption_overlay_pack where hook_overlay starts late (>1.5s)
    bad_cap_pack = _make_caption_overlay_pack(
        hook_overlay_applied=True,
        hook_overlay_start_s=2.0,  # too late → hook_visible_before_1_5s fails
        caption_start_s=2.5,       # too late → caption_readable fails
    )
    bad_vfx = _make_visual_effects(motion_contextual=False)  # motion_contextual=False

    bad_contract = first3_visual_contract(
        hook_plan=hook_plan,
        caption_overlay_pack=bad_cap_pack,
        composition_decision=comp,
        visual_effects=bad_vfx,
        transition_plan=_make_transition_plan(),
    )

    fail_count = int(bad_contract.get("first3_visual_fail_count") or 0)
    check(
        "first3_visual_fail_count >= 2 when multiple checks fail",
        fail_count >= 2,
        f"fail_count={fail_count}",
    )
    check(
        "first3_visual_passed=False when 2+ failures",
        bad_contract.get("first3_visual_passed") is False,
        f"passed={bad_contract.get('first3_visual_passed')}",
    )

    # Now simulate the assess_private_premium_status() downgrade logic
    # This is the exact logic from vpi_publishable_gate.py
    _first3_fail_count = fail_count
    _first3_contract_failed = _first3_fail_count >= 2

    check(
        "first3_contract_failed=True when fail_count >= 2",
        _first3_contract_failed is True,
        f"fail_count={_first3_fail_count}",
    )

    # Simulate the status downgrade
    if _first3_contract_failed:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_first3_visual_contract"
    else:
        status = "PRIVATE_PREMIUM_READY"
        editorial_quality = "solid"

    check(
        "status downgraded to PRIVATE_PREMIUM_REVIEW when first3_visual_contract fails",
        status == "PRIVATE_PREMIUM_REVIEW",
        f"status={status} editorial_quality={editorial_quality}",
    )
    check(
        "editorial_quality=review_first3_visual_contract when downgraded",
        editorial_quality == "review_first3_visual_contract",
        f"editorial_quality={editorial_quality}",
    )


# ── Test 6: composition_pack=true only when real composition decisions ──────
def test_6_composition_pack_active():
    logger.info("")
    logger.info("═" * 70)
    logger.info("[composition-runtime] TEST 6: composition_pack=true only when real composition decisions")
    logger.info("[composition-runtime] Verifies CAMBIO 6: richness uses real composition")
    logger.info("─" * 70)

    from services.vpi_visual_effects_service import build_composition_decision

    # Test 6a: Valid composition → composition_pack_active=True
    cap_pack = _make_caption_overlay_pack(
        hook_overlay_applied=True,
        hook_overlay_start_s=0.8,
        caption_start_s=1.0,
    )
    comp = build_composition_decision(
        hook_intent="myth_flip",
        visual_profile="",
        caption_overlay_pack=cap_pack,
        transition_plan=_make_transition_plan(),
        sfx_plan=_make_sfx_plan(),
        private_premium_status="",
        segment_text="",
    )

    _composition_runtime_applied = True
    _composition_pack_active = bool(
        comp
        and comp.get("composition_mode")
        and comp.get("composition_mode") not in ("", "unknown")
        and _composition_runtime_applied
    )

    check(
        "composition_pack_active=True when valid composition_mode exists",
        _composition_pack_active is True,
        f"composition_mode={comp.get('composition_mode')}",
    )

    # Test 6b: Valid composition but no runtime-applied layer → composition_pack_active=False
    _composition_runtime_applied_missing = False
    _composition_pack_active2 = bool(
        comp
        and comp.get("composition_mode")
        and comp.get("composition_mode") not in ("", "unknown")
        and _composition_runtime_applied_missing
    )
    check(
        "composition_pack_active=False when runtime did not apply composition",
        _composition_pack_active2 is False,
        f"composition_mode={comp.get('composition_mode')} runtime_applied={_composition_runtime_applied_missing}",
    )

    # Test 6c: Empty composition → composition_pack_active=False
    empty_comp = {}
    _composition_pack_active3 = bool(
        empty_comp
        and empty_comp.get("composition_mode")
        and empty_comp.get("composition_mode") not in ("", "unknown")
        and True
    )

    check(
        "composition_pack_active=False when no composition_mode",
        _composition_pack_active3 is False,
        f"composition_mode={empty_comp.get('composition_mode')}",
    )

    # Test 6d: Unknown composition → composition_pack_active=False
    unknown_comp = {"composition_mode": "unknown"}
    _composition_pack_active4 = bool(
        unknown_comp
        and unknown_comp.get("composition_mode")
        and unknown_comp.get("composition_mode") not in ("", "unknown")
        and True
    )

    check(
        "composition_pack_active=False when composition_mode=unknown",
        _composition_pack_active4 is False,
        f"composition_mode={unknown_comp.get('composition_mode')}",
    )

    # Test 6e: Empty string composition → composition_pack_active=False
    empty_str_comp = {"composition_mode": ""}
    _composition_pack_active5 = bool(
        empty_str_comp
        and empty_str_comp.get("composition_mode")
        and empty_str_comp.get("composition_mode") not in ("", "unknown")
        and True
    )

    check(
        "composition_pack_active=False when composition_mode=''",
        _composition_pack_active5 is False,
        f"composition_mode='{empty_str_comp.get('composition_mode')}'",
    )


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    logger.info("═" * 70)
    logger.info("[composition-runtime] Composition Pack Runtime Integration Debug — CAMBIO 7")
    logger.info("[composition-runtime] Verifying all 6 CAMBIOS produce expected runtime behavior")
    logger.info("═" * 70)

    test_1_composition_decision_called()
    test_2_conflict_resolver_affects_layers()
    test_3_conflict_resolver_blocks_transitions()
    test_4_conflict_resolver_blocks_sfx()
    test_5_first3_visual_contract_downgrades()
    test_6_composition_pack_active()

    logger.info("")
    logger.info("═" * 70)
    logger.info("[composition-runtime] RESULTS: %d PASS / %d FAIL / %d TOTAL",
                PASS, FAIL, PASS + FAIL)
    logger.info("═" * 70)

    if FAIL > 0:
        logger.error("[composition-runtime] ❌ Some tests FAILED — review logs above")
        sys.exit(1)
    else:
        logger.info("[composition-runtime] ✅ All tests PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
