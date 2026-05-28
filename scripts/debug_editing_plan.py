#!/usr/bin/env python3
"""Static debug for VPI Daily Publishing editing plans.

This script does not render media and does not launch tasks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.services.vpi_broll_intent import detect_clip_theme  # noqa: E402
from src.services.editorial_broll_planner import EditorialBrollPlanner  # noqa: E402
from src.services.vpi_editing_plan import assess_visual_density, build_editing_plan  # noqa: E402
from src.services.vpi_hook_engine import build_hook_plan  # noqa: E402


CLIPS = [
    {
        "clip": 1,
        "text": "Cuando tienes pareja, hijos o personas que dependen de ti, protegerlos no va de miedo, va de organizacion y responsabilidad.",
        "editorial_type": "emotional_protection",
        "vpi_score": 91,
        "matched_patterns": ["family_dependency", "responsibility"],
        "suggested_broll_cue_type": "family_responsibility",
        "duration": 24.0,
    },
    {
        "clip": 2,
        "text": "El seguro de vida no es solo para personas mayores. La realidad es que la edad y la responsabilidad llegan antes de lo que solemos mirar mas adelante.",
        "editorial_type": "client_objection",
        "vpi_score": 88,
        "matched_patterns": ["myth_debunk_age", "client_objection"],
        "suggested_broll_cue_type": "myth_debunk_age",
        "duration": 22.0,
    },
    {
        "clip": 3,
        "text": "Hola soy Sebastian Valentin y hoy quiero hablar de seguros de vida de forma clara.",
        "editorial_type": "weak_intro",
        "vpi_score": 58,
        "matched_patterns": ["weak_intro"],
        "suggested_broll_cue_type": "weak_intro",
        "duration": 16.0,
    },
]


def _fake_word_timestamps(text: str) -> list[dict]:
    words = []
    for idx, token in enumerate(re.findall(r"\w+", text, flags=re.UNICODE)):
        start = round(0.55 + idx * 0.42, 2)
        words.append({"word": token, "start": start, "end": round(start + 0.32, 2)})
    return words


def main() -> int:
    rows = []
    planner = EditorialBrollPlanner()
    for item in CLIPS:
        words = _fake_word_timestamps(item["text"])
        theme = detect_clip_theme(
            item["text"],
            editorial_type=item["editorial_type"],
            matched_patterns=item["matched_patterns"],
            suggested_broll_cue_type=item["suggested_broll_cue_type"],
            vpi_score=item["vpi_score"],
        )
        broll_cues = [
            cue for cue in planner.plan(
                item["text"],
                clip_duration=item["duration"],
                word_timestamps=words,
                suggested_broll_cue_type=item["suggested_broll_cue_type"],
            )
            if cue.decision == "approve"
        ]
        plan = build_editing_plan(
            text=item["text"],
            editorial_type=item["editorial_type"],
            vpi_score=item["vpi_score"],
            matched_patterns=item["matched_patterns"],
            clip_duration=item["duration"],
            word_timestamps=words,
            theme=theme,
            has_broll=bool(broll_cues),
        ).to_dict()
        hook_plan = build_hook_plan(
            text=item["text"],
            editorial_type=item["editorial_type"],
            vpi_score=item["vpi_score"],
            matched_patterns=item["matched_patterns"],
            word_timestamps=words,
            clip_duration=item["duration"],
            editing_plan=plan,
            theme=theme,
        ).to_dict()
        broll_events = [] if hook_plan["hook_type"] == "weak_intro" else [
            {
                "start_s": max(float(cue.start_s or 0.0), float(hook_plan["broll_delay_until_s"] or 0.0)),
                "duration_s": cue.duration_s,
                "cue_type": cue.cue_type,
                "intent_type": cue.intent_type,
            }
            for cue in broll_cues
        ]
        density = assess_visual_density(
            editing_plan=plan,
            broll_events=broll_events,
            subtitle_highlight_count=len(plan["highlighted_terms"]),
            watermark_applied=True,
        )
        zoom_expected = bool(hook_plan.get("zoom_event"))
        overlay_expected = bool(hook_plan.get("hook_headline_overlay"))
        kickframe_expected = bool(hook_plan.get("kickframe_event"))
        subtitle_hook_expected = bool(hook_plan.get("emphasis_words"))
        hook_contract_satisfied = bool(
            hook_plan.get("hook_contract_satisfied")
            or hook_plan.get("hook_type") == "weak_intro"
            or zoom_expected
            or overlay_expected
            or kickframe_expected
            or subtitle_hook_expected
        )
        editing_activity_score = 0
        if zoom_expected or overlay_expected or kickframe_expected or subtitle_hook_expected:
            editing_activity_score += 2
        if zoom_expected:
            editing_activity_score += 2
        if broll_events:
            editing_activity_score += 2
        editing_activity_score += 1  # captions expected
        editing_activity_score += 1  # branding expected
        hook_end = 4.5 if item["editorial_type"] == "emotional_protection" else 3.2
        timeline = [
            {
                "range": f"0.0-{hook_plan['end_s']:.1f}",
                "event": f"hook_window_{hook_plan['hook_type']}",
                "headline": hook_plan["headline_text"],
            },
            {"range": f"0.0-{hook_end:.1f}", "event": "speaker_hook"},
            {"range": "full", "event": "watermark_top_right"},
        ]
        for cue in broll_events:
            timeline.append({
                "range": f"{float(cue['start_s'] or 0):.1f}-{float((cue['start_s'] or 0) + cue['duration_s']):.1f}",
                "event": f"broll_{cue['cue_type']}",
            })
        for zoom in plan["smart_zoom_events"]:
            timeline.append({
                "range": f"{float(zoom['start_s']):.1f}-{float(zoom['start_s']) + float(zoom['duration_s']):.1f}",
                "event": f"smart_zoom_{zoom.get('reason', 'emphasis')}",
            })
        if hook_plan.get("zoom_event"):
            zoom = hook_plan["zoom_event"]
            timeline.append({
                "range": f"{float(zoom['start_s']):.1f}-{float(zoom['start_s']) + float(zoom['duration_s']):.1f}",
                "event": f"hook_zoom_{hook_plan['visual_treatment']}",
            })
        timeline.append({
            "range": f"0.0-{hook_plan['broll_delay_until_s']:.1f}",
            "event": "broll_delay",
        })
        for term in plan["highlighted_terms"][:4]:
            timeline.append({"range": "caption_line", "event": f"highlight_{term}"})
        rows.append(
            {
                "clip": item["clip"],
                "theme": getattr(theme, "central_topic", "unknown"),
                "editing_plan": {
                    "hook_strategy": plan["hook_strategy"],
                    "pacing_strategy": plan["pacing_strategy"],
                    "reframe_strategy": plan["reframe_strategy"],
                    "subtitle_strategy": plan["subtitle_strategy"],
                    "broll_strategy": plan["broll_strategy"],
                    "brand_treatment": plan["brand_treatment"],
                    "cta_strategy": plan["cta_strategy"],
                    "visual_density": plan["visual_density"],
                    "publishable_score": plan["publishable_score"],
                },
                "visual_timeline": timeline,
                "hook_plan": {
                    "enabled": hook_plan["enabled"],
                    "hook_type": hook_plan["hook_type"],
                    "hook_family": hook_plan.get("hook_family"),
                    "hook_opening_strategy": hook_plan.get("hook_opening_strategy"),
                    "headline_text": hook_plan["headline_text"],
                    "headline_source": hook_plan.get("headline_source"),
                    "headline_score": hook_plan.get("headline_score"),
                    "headline_reasons": hook_plan.get("headline_reasons", []),
                    "subtitle_hook_text": hook_plan["subtitle_hook_text"],
                    "visual_treatment": hook_plan["visual_treatment"],
                    "zoom_event": hook_plan["zoom_event"],
                    "hook_headline_overlay": hook_plan.get("hook_headline_overlay"),
                    "overlay_rendered_expected": bool(hook_plan.get("hook_headline_overlay")),
                    "kickframe_event": hook_plan.get("kickframe_event"),
                    "kickframe_expected": kickframe_expected,
                    "emphasis_words": hook_plan["emphasis_words"],
                    "subtitle_hook_expected": subtitle_hook_expected,
                    "hook_contract_satisfied": hook_contract_satisfied,
                    "hook_visual_signal_count": hook_plan.get("hook_visual_signal_count"),
                    "hook_visual_signal_types": hook_plan.get("hook_visual_signal_types", []),
                    "hook_first_4s_score": hook_plan.get("hook_first_4s_score"),
                    "hook_first_4s_signals": hook_plan.get("hook_first_4s_signals", []),
                    "hook_variety_reason": hook_plan.get("hook_variety_reason"),
                    "low_publish_priority": hook_plan.get("low_publish_priority"),
                    "broll_delay_until_s": hook_plan["broll_delay_until_s"],
                    "density_score": hook_plan["density_score"],
                    "density_actions": hook_plan["density_actions"],
                    "hook_quality": hook_plan.get("hook_quality"),
                    "warnings": hook_plan["warnings"],
                },
                "editing_activity_score": editing_activity_score,
                "broll_events": broll_events,
                "smart_zoom_events": plan["smart_zoom_events"],
                "highlighted_terms": plan["highlighted_terms"],
                "visual_density": {
                    "score": density["visual_density_score"],
                    "warnings": density["visual_density_warnings"],
                    "actions": density["visual_density_actions"],
                },
                "publishable_status_expected": "usable_with_warnings",
                "warnings_expected": [
                    "qc_requires_rendered_file",
                    "smart_zoom_real_if_ffmpeg_ok" if plan["smart_zoom_events"] else "smart_zoom_skipped",
                    "cta_metadata_only" if plan["cta_strategy"] != "none" else "cta_none",
                ],
            }
        )
    for row in rows:
        hook = row["hook_plan"]
        overlay = hook.get("hook_headline_overlay") or {}
        zoom = hook.get("zoom_event") or {}
        print(f"Clip {row['clip']}:")
        print(f"0.0-4.0 hook window")
        print(f"hook_type: {hook.get('hook_type')}")
        print(f"hook_family: {hook.get('hook_family')}")
        print(f"strategy: {hook.get('hook_opening_strategy')}")
        print(f"headline: \"{hook.get('headline_text')}\"")
        print(f"source: {hook.get('headline_source')}")
        print(f"headline_score: {hook.get('headline_score')}")
        if overlay:
            ov_start = float(overlay.get("start_s", 0.0) or 0.0)
            ov_end = ov_start + float(overlay.get("duration_s", 0.0) or 0.0)
            print(f"overlay: yes {ov_start:.2f}-{ov_end:.2f}")
        else:
            print("overlay: no")
        print(f"kickframe: {'yes' if hook.get('kickframe_event') else 'no'}")
        if zoom:
            zoom_end = float(zoom.get("start_s", 0.0) or 0.0) + float(zoom.get("duration_s", 0.0) or 0.0)
            print(f"punch: {float(zoom.get('start_s', 0.0) or 0.0):.2f}-{zoom_end:.2f}")
        else:
            print("punch: no")
        print(f"subtitle_hook: {'yes' if hook.get('subtitle_hook_expected') else 'no'}")
        print(f"hook_contract_satisfied: {str(bool(hook.get('hook_contract_satisfied'))).lower()}")
        print(f"first4_score: {hook.get('hook_first_4s_score')} signals={','.join(hook.get('hook_first_4s_signals') or []) or '-'}")
        print(f"low_publish_priority: {str(bool(hook.get('low_publish_priority'))).lower()}")
        print(f"editing_activity_score: {row.get('editing_activity_score')}")
        print(f"broll_delay: {float(hook.get('broll_delay_until_s') or 0.0):.1f}")
        print(f"density_score: {hook.get('density_score')}")
        print(f"hook_quality: {hook.get('hook_quality')}")
        print()
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
