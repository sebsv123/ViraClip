#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_visual_effects_service import build_frame_rhythm_events, plan_premium_transition  # noqa: E402


def main() -> int:
    rhythm = build_frame_rhythm_events([{"event": "caption_emphasis"}, {"event": "transition_reveal"}])
    frames = [event["frames"] for event in rhythm["frame_rhythm_events"][:2]]
    assert frames == [5, 10]
    sweep = plan_premium_transition(event_type="idea_shift")
    mask = plan_premium_transition(event_type="object_focus", bbox={"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.5})
    fallback = plan_premium_transition(event_type="object_focus")
    assert sweep["transition_type"] == "sweeping_reveal"
    assert mask["transition_type"] == "mask_reveal_bbox"
    assert fallback["transition_type"] == "clean_cut"
    print("frame_rhythm_5_to_10=true")
    print("transition_sweeping_reveal=true")
    print("transition_mask_requires_bbox=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
