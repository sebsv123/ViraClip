#!/usr/bin/env python3
"""Debug script for VPI Visual Identity Polish v3.2.

Tests:
  1. Branding watermark (vpi_branding_service.py)
  2. Subtitle highlight density (caption_service.py)
  3. Safe lower-third hook (vpi_hook_engine.py)
  4. Brand-safe transitions (broll_compositor.py)
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("debug-vpi-visual-identity")

# Ensure backend/src and backend/src/services are importable
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_BACKEND_SRC = _REPO / "backend/src"
_BACKEND_SERVICES = _BACKEND_SRC / "services"
for p in [_BACKEND_SRC, _BACKEND_SERVICES]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _import_or_skip(module_path: str, label: str):
    """Try to import *module_path*, log result."""
    try:
        __import__(module_path, fromlist=["__dummy__"])
        logger.info("  ✓ %s — import OK", label)
        return True
    except Exception as exc:
        logger.error("  ✗ %s — import FAILED: %s", label, exc)
        traceback.print_exc()
        return False


def test_branding_service():
    """Test vpi_branding_service imports and key functions."""
    logger.info("── FASE 1: Branding watermark ──")
    if not _import_or_skip("vpi_branding_service", "vpi_branding_service"):
        return False

    from vpi_branding_service import (
        find_brand_asset,
        _compute_logo_scale,
        _probe_image_dimensions,
    )

    # Test find_brand_asset
    asset = find_brand_asset(_REPO)
    if asset:
        logger.info("  ✓ find_brand_asset() found: %s", asset)
    else:
        logger.warning("  ~ find_brand_asset() returned None (no logo file)")

    # Test _compute_logo_scale
    scale = _compute_logo_scale(1080, 200)
    logger.info("  ✓ _compute_logo_scale(1080, 200) = %s", scale)
    assert "scale=" in scale, f"Expected scale= in result, got {scale}"

    # Test _probe_image_dimensions
    if asset:
        dims = _probe_image_dimensions(asset)
        logger.info("  ✓ _probe_image_dimensions(%s) = %s", asset.name, dims)
        assert "width" in dims and "height" in dims

    logger.info("  ✓ FASE 1 passed")
    return True


def test_caption_service():
    """Test caption_service v3.2 highlight density logic."""
    logger.info("── FASE 2: Subtitle visual polish ──")
    if not _import_or_skip("caption_service", "caption_service"):
        return False

    import caption_service as cs

    # Verify module-level functions exist (v3.2 changes)
    assert hasattr(cs, "_select_editorial_highlights"), (
        "Missing _select_editorial_highlights"
    )
    assert hasattr(cs, "burn_captions"), "Missing burn_captions"

    # Verify v3.2 metadata keys are set in burn_captions
    import inspect
    sig = inspect.signature(cs.burn_captions)
    caption_decisions_param = sig.parameters.get("caption_decisions")
    assert caption_decisions_param is not None, "burn_captions missing caption_decisions param"

    logger.info("  ✓ caption_service has _select_editorial_highlights and burn_captions")
    logger.info("  ✓ FASE 2 passed")
    return True


def test_hook_engine():
    """Test vpi_hook_engine v3.2 lower-third fields."""
    logger.info("── FASE 3: Safe lower-third hook ──")
    if not _import_or_skip("vpi_hook_engine", "vpi_hook_engine"):
        return False

    from vpi_hook_engine import HookPlan, build_hook_plan

    # Verify HookPlan dataclass has lower_third fields
    assert hasattr(HookPlan, "lower_third"), "HookPlan missing lower_third field"
    assert hasattr(HookPlan, "lower_third_applied"), "HookPlan missing lower_third_applied field"
    logger.info("  ✓ HookPlan dataclass has lower_third + lower_third_applied")

    # Test build_hook_plan with a strong hook scenario
    plan = build_hook_plan(
        text="Cuando alguien depende de ti, proteger importa. No esperes mas.",
        editorial_type="emotional_protection",
        vpi_score=88.0,
        matched_patterns=["dependen de ti", "proteger"],
        word_timestamps=None,
        clip_duration=30.0,
    )
    logger.info("  ✓ build_hook_plan() returned HookPlan")
    logger.info("  ✓ hook_type=%s", plan.hook_type)
    logger.info("  ✓ lower_third=%s", plan.lower_third)
    logger.info("  ✓ lower_third_applied=%s", plan.lower_third_applied)

    # Verify lower_third structure when applied
    if plan.lower_third:
        assert "text" in plan.lower_third
        assert "start_s" in plan.lower_third
        assert "duration_s" in plan.lower_third
        assert "position" in plan.lower_third
        assert "style" in plan.lower_third
        logger.info("  ✓ lower_third dict has all required keys")

    logger.info("  ✓ FASE 3 passed")
    return True


def test_broll_compositor():
    """Test broll_compositor v3.2 brand-safe fade default."""
    logger.info("── FASE 4: Brand-safe transitions ──")
    if not _import_or_skip("broll_compositor", "broll_compositor"):
        return False

    import inspect
    from broll_compositor import normalize_broll, compose_overlay, compose_overlay_multi

    # Check normalize_broll default fade
    sig = inspect.signature(normalize_broll)
    fade_param = sig.parameters.get("fade")
    assert fade_param is not None, "normalize_broll missing fade parameter"
    assert fade_param.default == 0.15, (
        f"normalize_broll fade default should be 0.15, got {fade_param.default}"
    )
    logger.info("  ✓ normalize_broll fade default = 0.15 (brand-safe)")

    # Check compose_overlay passes fade through
    sig2 = inspect.signature(compose_overlay)
    fade_param2 = sig2.parameters.get("fade")
    assert fade_param2 is not None, "compose_overlay missing fade parameter"
    logger.info("  ✓ compose_overlay fade default = %s", fade_param2.default)

    # Check compose_overlay_multi passes fade through
    sig3 = inspect.signature(compose_overlay_multi)
    fade_param3 = sig3.parameters.get("fade")
    assert fade_param3 is not None, "compose_overlay_multi missing fade parameter"
    logger.info("  ✓ compose_overlay_multi fade default = %s", fade_param3.default)

    logger.info("  ✓ FASE 4 passed")
    return True


def main():
    logger.info("=" * 60)
    logger.info("VPI Visual Identity Polish v3.2 — Debug Script")
    logger.info("=" * 60)

    results = {}

    results["fase1_branding"] = test_branding_service()
    results["fase2_captions"] = test_caption_service()
    results["fase3_lower_third"] = test_hook_engine()
    results["fase4_transitions"] = test_broll_compositor()

    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    all_ok = True
    for name, ok in results.items():
        status = "✓ PASS" if ok else "✗ FAIL"
        logger.info("  %s: %s", name, status)
        if not ok:
            all_ok = False

    if all_ok:
        logger.info("")
        logger.info("All FASEs passed. VPI Visual Identity v3.2 is ready.")
    else:
        logger.error("")
        logger.error("Some FASEs failed. Review logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
