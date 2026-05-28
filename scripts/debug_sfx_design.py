#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_sfx_service import build_sfx_design_plan  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="viraclip_sfx_debug_") as tmp:
        base = Path(tmp)
        assets = {
            "low_riser": [base / "dark_low_riser.wav"],
            "high_riser": [base / "bright_high_rise.wav"],
            "magic_whoosh": [base / "magic_whoosh.wav"],
            "deep_boom": [base / "deep_boom_01.wav", base / "deep_boom_02.wav"],
        }
        plan1 = build_sfx_design_plan(
            hook_plan={"hook_type": "risk_hook", "hook_first3_score": 7},
            broll_events=[{"start_s": 4.0, "reason": "key visual"}],
            editorial_type="risk_warning",
            clip_duration_s=18.0,
            task_id="debug",
            assets=assets,
        )
        plan2 = build_sfx_design_plan(
            hook_plan={"hook_type": "risk_hook", "hook_first3_score": 7},
            editorial_type="risk_warning",
            clip_duration_s=18.0,
            task_id="debug",
            assets=assets,
            used_deep_boom_assets=[str(assets["deep_boom"][0])],
        )
    events1 = plan1["sfx_design_events"]
    assert any(event["type"] == "dark_riser_combo" for event in events1)
    assert any(event["type"] == "magic_whoosh" for event in events1)
    assert any(event["type"] == "deep_boom" for event in events1)
    first_boom = next(event for event in events1 if event["type"] == "deep_boom")
    second_boom = next(event for event in plan2["sfx_design_events"] if event["type"] == "deep_boom")
    assert first_boom["deep_boom_asset"] != second_boom["deep_boom_asset"]
    print("sfx_dark_riser_combo_planned=true")
    print("sfx_magic_whoosh_planned=true")
    print("sfx_deep_boom_repetition_guard=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
