#!/usr/bin/env python3
"""Quick static check for VPI B-roll intent/theme/no-broll decisions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_broll_intent import detect_clip_theme, detect_intent  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="")
    parser.add_argument("--editorial-type", default="")
    parser.add_argument("--suggested-broll-cue-type", default="")
    parser.add_argument("--vpi-score", type=float, default=None)
    args = parser.parse_args()

    theme = detect_clip_theme(
        args.text,
        editorial_type=args.editorial_type or None,
        suggested_broll_cue_type=args.suggested_broll_cue_type or None,
        vpi_score=args.vpi_score,
    )
    intent = detect_intent(
        args.text,
        editorial_type=args.editorial_type or None,
        suggested_broll_cue_type=args.suggested_broll_cue_type or None,
        vpi_score=args.vpi_score,
        segment_duration=30,
    )
    print(
        json.dumps(
            {
                "intent_type": intent.intent_type,
                "max_overlays": intent.max_overlays,
                "hard_stop_no_broll": intent.intent_type == "weak_intro" and intent.max_overlays == 0,
                "preferred_categories": intent.preferred_categories,
                "theme": {
                    "domain": theme.domain,
                    "central_topic": theme.central_topic,
                    "preferred_visual_mix": theme.preferred_visual_mix,
                    "avoid_visual_overuse": theme.avoid_visual_overuse,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
