"""Stable internal premium runtime contract for Beta Clean VPI."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

VIRACLIP_PREMIUM_EDITING_DEFAULT = True
PREMIUM_LAYERS_REQUESTED = [
    "retention_plan",
    "premium_transitions",
    "visual_effects",
    "music",
    "sfx_design",
    "frame_rhythm",
    "broll_transitions",
    "caption_visual_support",
    "retention_quality_gate",
]


def premium_runtime_contract() -> Dict[str, Any]:
    enabled = bool(VIRACLIP_PREMIUM_EDITING_DEFAULT)
    return {
        "premium_runtime_enabled": enabled,
        "premium_layers_requested": list(PREMIUM_LAYERS_REQUESTED) if enabled else [],
        "retention": enabled,
        "transitions": enabled,
        "sfx": enabled,
        "music": enabled,
        "vfx": enabled,
        "frame_rhythm": enabled,
    }


def verify_final_filename_contract(
    final_path: Path,
    *,
    music: Optional[Dict[str, Any]] = None,
    sfx: Optional[Dict[str, Any]] = None,
    transitions: Optional[Dict[str, Any]] = None,
    visual_effects: Optional[Dict[str, Any]] = None,
    broll_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    name = final_path.name
    broll_count = len(broll_events or [])
    broll_final_verified = any(
        bool((item or {}).get("broll_final_verified"))
        or bool((item or {}).get("broll_transition_applied"))
        or bool((item or {}).get("broll_ken_burns_applied"))
        or bool((item or {}).get("asset_path"))
        or bool((item or {}).get("asset_url"))
        for item in (broll_events or [])
    )
    broll_actual = bool(broll_count > 0 and broll_final_verified and ("broll_" in name or broll_count > 0))
    checks = {
        "music": bool((music or {}).get("music_applied") and "music_" in name),
        "sfx": bool((sfx or {}).get("sfx_applied") and "sfx_" in name),
        "trans": bool((transitions or {}).get("transitions_applied") and "trans_" in name),
        "vfx": bool((visual_effects or {}).get("visual_effects_applied") and "vfx_" in name),
        "broll": broll_actual,
    }
    warnings: List[str] = []
    if (music or {}).get("music_applied") != ("music_" in name):
        warnings.append("music_marker_missing_or_false_positive")
    if (sfx or {}).get("sfx_applied") != ("sfx_" in name):
        warnings.append("sfx_marker_missing_or_false_positive")
    if (transitions or {}).get("transitions_applied") != ("trans_" in name):
        warnings.append("trans_marker_missing_or_false_positive")
    if (visual_effects or {}).get("visual_effects_applied") != ("vfx_" in name):
        warnings.append("vfx_marker_missing_or_false_positive")
    if "broll_" in name and not broll_actual:
        warnings.append("broll_marker_false_positive")
    elif broll_count > 0 and not broll_actual:
        warnings.append("broll_planned_not_final_verified")
    return {
        "final_contract_ok": not warnings,
        "final_contract": checks,
        "final_contract_warnings": warnings,
    }
