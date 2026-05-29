#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from services.vpi_asset_library_service import build_asset_index  # noqa: E402
from services.vpi_broll_intent import build_broll_editorial_decision, match_broll_asset  # noqa: E402
from services.vpi_sfx_service import build_sfx_retention_decision, match_sfx_asset  # noqa: E402
from services.caption_service import plan_caption_overlay_pack  # noqa: E402
from services.vpi_music_service import discover_music_tracks, select_music_track  # noqa: E402


def _pick_font(index: dict) -> str:
    fonts = list((index.get("verified") or {}).get("fonts") or [])
    if not fonts:
        return ""
    preferred = next((f for f in fonts if "caption_primary" in list(f.get("tags") or [])), fonts[0])
    return str(preferred.get("path") or "")


def _pick_icon(plan: dict) -> str:
    icon = dict(plan.get("caption_icon") or {})
    return str(icon.get("asset") or "") if icon.get("applied") else ""


def main() -> int:
    index = build_asset_index()
    segments = [
        {
            "text": "esto mucha gente no lo sabe sobre el seguro de salud",
            "editorial_type": "salud",
            "hook_intent": "risk_warning",
            "composition_mode": "warning_tension",
        },
        {
            "text": "si eres autónomo y mañana no puedes trabajar",
            "editorial_type": "autonomos",
            "hook_intent": "autonomous_business_stakes",
            "composition_mode": "business_punch",
        },
        {
            "text": "la tranquilidad para ti y los tuyos",
            "editorial_type": "decesos",
            "hook_intent": "emotional_closure",
            "composition_mode": "emotional_soft",
        },
    ]

    selected_broll = ""
    selected_sfx = ""
    selected_bgm = ""
    selected_icon = ""
    selected_font = _pick_font(index)

    for seg in segments:
        if not selected_broll:
            decision = build_broll_editorial_decision(
                segment_text=seg["text"],
                hook_intent=seg["hook_intent"],
                topic=seg["editorial_type"],
                private_premium_status="PRIVATE_PREMIUM_READY",
                composition_decision={"mode": seg["composition_mode"]},
                first3_visual_contract={"status": "pass"},
                visual_profile="",
            )
            match = match_broll_asset(
                broll_intent=str(decision.get("broll_intent") or ""),
                topic=seg["editorial_type"],
                segment_text=seg["text"],
            )
            if match.get("matched"):
                selected_broll = str(match.get("asset") or "")

        if not selected_sfx:
            sfx_decision = build_sfx_retention_decision(
                hook_intent=seg["hook_intent"],
                visual_profile="",
                composition_mode=seg["composition_mode"],
                broll_editorial_decision={},
                segment_text=seg["text"],
                private_premium_status="PRIVATE_PREMIUM_READY",
                first3_visual_contract={"status": "pass"},
            )
            sfx_match = match_sfx_asset(
                sfx_family=str(sfx_decision.get("sfx_family") or ""),
                hook_intent=seg["hook_intent"],
                task_id="debug_asset_runtime_selection",
            )
            if sfx_match.get("matched"):
                selected_sfx = str(sfx_match.get("asset") or "")

        if not selected_icon:
            caption_plan = plan_caption_overlay_pack(
                "salud especialistas tranquilidad",
                hook_intent="neutral_explanation",
                editorial_type="salud",
                words=[{"word": "salud", "start": 0.0, "end": 0.3}, {"word": "tranquilidad", "start": 0.3, "end": 0.6}],
                subtitle_already_strong=True,
                enable_lower_third=True,
                composition_decision={"mode": "minimal_safe"},
            )
            selected_icon = _pick_icon(caption_plan)

        if not selected_bgm:
            tracks = discover_music_tracks()
            track, _mood = select_music_track(seg["editorial_type"], tracks)
            if track:
                selected_bgm = str(track)

    ok = all([selected_broll, selected_sfx, selected_bgm, selected_icon, selected_font])
    print(f"ASSET_RUNTIME_SELECTION={'PASS' if ok else 'FAIL'}")
    print(f"selected_broll={selected_broll or 'none'}")
    print(f"selected_sfx={selected_sfx or 'none'}")
    print(f"selected_bgm={selected_bgm or 'none'}")
    print(f"selected_icon={selected_icon or 'none'}")
    print(f"selected_font={selected_font or 'none'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
