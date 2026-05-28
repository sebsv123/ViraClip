#!/usr/bin/env python3
"""Debug local VPI SFX library discovery and event planning."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_sfx_service import discover_sfx_assets, plan_sfx_events, sfx_search_paths  # noqa: E402


def main() -> int:
    print("sfx_paths_checked:")
    for path in sfx_search_paths():
        print(f"- {path} exists={path.exists()}")
    assets = discover_sfx_assets()
    hook_plan = {
        "hook_type": "objection_breaker",
        "kickframe_applied": True,
        "hook_motion_start_s": 0.5,
    }
    broll_events = [{"start_s": 4.2, "cue_type": "advisor_consultation"}]
    events = plan_sfx_events(hook_plan=hook_plan, broll_events=broll_events, editorial_type="client_objection")
    print(f"sfx_assets={len(assets)}")
    for asset in assets:
        print(f"- sfx={asset}")
    print(f"planned_events={events}")
    if not assets:
        print("[sfx] skipped reason=missing_sfx_worker_assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
