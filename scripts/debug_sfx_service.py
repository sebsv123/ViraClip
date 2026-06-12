#!/usr/bin/env python3
"""Debug local VPI SFX library discovery and event planning."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_sfx_service import build_sfx_design_plan, discover_sfx_assets  # noqa: E402

SFX_SEARCH_PATHS = (
    "assets/sfx",
    "assets/sounds",
    "assets/sounds/sfx",
    "assets/sounds/risers",
    "assets/sounds/booms",
    "assets/sounds/whooshes",
    "/app/assets/sfx",
    "/app/assets/sounds",
    "/app/assets/sounds/sfx",
    "/app/assets/sounds/risers",
    "/app/assets/sounds/booms",
    "/app/assets/sounds/whooshes",
)


def main() -> int:
    print("sfx_paths_checked:")
    for item in SFX_SEARCH_PATHS:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        print(f"- {path} exists={path.exists()}")
    assets = discover_sfx_assets()
    hook_plan = {
        "hook_type": "objection_hook",
        "hook_first3_score": 7,
        "kickframe_applied": True,
        "hook_motion_start_s": 0.5,
    }
    broll_events = [{"start_s": 4.2, "cue_type": "advisor_consultation"}]
    plan = build_sfx_design_plan(
        hook_plan=hook_plan,
        broll_events=broll_events,
        editorial_type="client_objection",
        clip_duration_s=18.0,
        assets=assets,
    )
    low = assets.get("low_riser") or []
    high = assets.get("high_riser") or []
    whooshes = assets.get("magic_whoosh") or []
    booms = assets.get("deep_boom") or []
    print(f"sfx_assets_found={sum(len(items) for items in assets.values())}")
    print(f"low_risers={len(low)}")
    print(f"high_risers={len(high)}")
    print(f"whooshes={len(whooshes)}")
    print(f"booms_impacts={len(booms)}")
    for kind, paths in assets.items():
        for asset in paths:
            print(f"- {kind}={asset}")
    events = plan.get("sfx_design_events") or []
    event_types = {str(event.get("type")) for event in events}
    print(f"planned_events={events}")
    print(f"dark_riser_combo_planned={'dark_riser_combo' in event_types}")
    print(f"magic_whoosh_planned={'magic_whoosh' in event_types}")
    print(f"deep_boom_planned={'deep_boom' in event_types}")
    if plan.get("sfx_design_missing_assets"):
        print(f"[sfx] skipped missing_types={','.join(plan['sfx_design_missing_assets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
