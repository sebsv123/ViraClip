#!/usr/bin/env python3
"""Offline checks for VPI Editing Richness v3.5 scoring."""
from __future__ import annotations


def score_case(case: dict) -> dict:
    score = 0
    if case.get("hook_first3_perceptible"):
        score += 2
    if case.get("visual_effects_applied"):
        score += 2
    if case.get("silence_cut_useful"):
        score += 1
    if case.get("good_broll_phrase_fit"):
        score += 2
    if case.get("music_applied"):
        score += 1
    if case.get("sfx_applied"):
        score += 1
    if case.get("branding"):
        score += 1
    if case.get("captions_hook"):
        score += 1
    if case.get("speaker_focus_enhanced"):
        score += 1
    no_rich_assets = not case.get("good_broll_phrase_fit") and not case.get("music_applied") and not case.get("sfx_applied")
    if score <= 3:
        status = "too_plain"
    elif score <= 5:
        status = "acceptable"
    elif score <= 8:
        status = "good"
    else:
        status = "rich"
    warnings = []
    if no_rich_assets:
        warnings.append("visually_too_plain")
        if status in {"good", "rich"}:
            status = "acceptable"
    return {"score": score, "status": status, "warnings": warnings}


def main() -> int:
    cases = {
        "no_broll_emotional": {
            "hook_first3_perceptible": True,
            "visual_effects_applied": True,
            "silence_cut_useful": True,
            "captions_hook": True,
            "branding": True,
            "speaker_focus_enhanced": True,
        },
        "hook_first3_subtitle_only": {
            "hook_first3_perceptible": False,
            "visual_effects_applied": False,
            "silence_cut_useful": True,
            "captions_hook": True,
        },
        "rich_with_broll_music_sfx": {
            "hook_first3_perceptible": True,
            "visual_effects_applied": True,
            "silence_cut_useful": True,
            "good_broll_phrase_fit": True,
            "music_applied": True,
            "sfx_applied": True,
            "captions_hook": True,
            "branding": True,
        },
    }
    for name, case in cases.items():
        print(f"{name}: {score_case(case)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
