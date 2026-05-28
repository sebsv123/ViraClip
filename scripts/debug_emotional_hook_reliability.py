#!/usr/bin/env python3
"""Offline checks for emotional hook reliability metadata logic."""
from __future__ import annotations

import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.services.vpi_hook_engine import build_hook_plan  # noqa: E402
from src.services.smart_reframe_service import SmartReframeService  # noqa: E402


def _words(text: str):
    out = []
    t = 0.0
    for word in text.split():
        out.append({"word": word, "start": t, "end": t + 0.22})
        t += 0.28
    return out


def _contract_ok(plan: dict, clip_duration: float = 18.0) -> bool:
    if plan.get("hook_type") != "emotional_hook" or clip_duration <= 10.0:
        return bool(plan.get("hook_contract_satisfied"))
    speaker_focus_strong = "silence_cut_before_2s" in (plan.get("hook_first_4s_signals") or [])
    return bool(plan.get("hook_motion_rendered") or plan.get("rendered") or speaker_focus_strong)


def main() -> int:
    failures = 0
    text = "No se trata de vivir con miedo se trata de proteger a las personas que dependen de ti"
    plan = build_hook_plan(
        text=text,
        editorial_type="emotional_protection",
        vpi_score=88,
        matched_patterns=["emotional_protection"],
        word_timestamps=_words(text),
        clip_duration=18.0,
        editing_plan={},
        theme={"central_topic": "life_insurance_family_protection"},
    ).to_dict()
    print(
        f"- emotional plan: hook_type={plan.get('hook_type')} "
        f"motion={plan.get('hook_motion_strength')} start={plan.get('hook_motion_start_s')} "
        f"dur={plan.get('hook_motion_duration_s')}"
    )
    if not plan.get("zoom_event") or plan.get("hook_motion_strength") != "subtle":
        failures += 1

    svc = SmartReframeService()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        input_path = Path("/tmp/vpi_emotional_hook_input.mp4")
        output_path = Path("/tmp/vpi_emotional_hook_fallback.mp4")
        subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=24:d=3",
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-shortest", "-c:v", "libx264", "-c:a", "aac", str(input_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        fallback = svc.apply_static_hook_push_in(
            input_path,
            output_path,
            {"start_s": 0.1, "duration_s": 9.0, "scale": 2.0, "hook": True},
        )
        print(f"- dynamic forced fail fallback: rendered={fallback.get('rendered')} method={fallback.get('method')}")
        if not fallback.get("rendered"):
            failures += 1
    else:
        print("- dynamic forced fail fallback: skipped ffmpeg_not_found")

    subtitle_only = dict(plan)
    subtitle_only["rendered"] = False
    subtitle_only["hook_motion_rendered"] = False
    subtitle_only["hook_visual_signal_types"] = ["subtitle_highlight"]
    subtitle_only["hook_contract_satisfied"] = _contract_ok(subtitle_only, 18.0)
    print(f"- subtitle only contract: satisfied={subtitle_only['hook_contract_satisfied']}")
    if subtitle_only["hook_contract_satisfied"]:
        failures += 1

    speaker_focus = dict(subtitle_only)
    speaker_focus["hook_first_4s_signals"] = ["subtitle_hook", "silence_cut_before_2s"]
    speaker_focus["hook_contract_satisfied"] = _contract_ok(speaker_focus, 18.0)
    print(f"- speaker focus strong contract: satisfied={speaker_focus['hook_contract_satisfied']}")
    if not speaker_focus["hook_contract_satisfied"]:
        failures += 1

    remapped_event = dict(plan.get("zoom_event") or {})
    remapped_event["start_s"] = max(0.4, float(remapped_event.get("start_s", 0.8)) - 0.2)
    timing_ok = 0.4 <= float(remapped_event["start_s"]) <= 0.8
    print(f"- silence remap timing: start={remapped_event['start_s']} ok={timing_ok}")
    if not timing_ok:
        failures += 1

    print(f"summary: ok={5 - failures} fail={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
