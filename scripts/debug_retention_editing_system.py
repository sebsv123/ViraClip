#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_publishable_gate import evaluate_clip_publishability  # noqa: E402
from src.services.vpi_retention_editing_service import build_retention_editing_plan, retention_plan_metadata  # noqa: E402
from src.services.vpi_silence_editor import build_silence_edit_plan  # noqa: E402


def _words() -> list[dict]:
    return [
        {"word": "No", "start": 0.0, "end": 0.2},
        {"word": "es", "start": 0.22, "end": 0.35},
        {"word": "solo", "start": 0.36, "end": 0.55},
        {"word": "responsabilidad", "start": 0.90, "end": 1.4},
        {"word": "depende", "start": 2.4, "end": 2.8},
        {"word": "de", "start": 2.82, "end": 2.94},
        {"word": "ti", "start": 2.96, "end": 3.1},
        {"word": "cuidado", "start": 4.2, "end": 4.7},
    ]


def main() -> int:
    text = "No es solo responsabilidad depende de ti cuidado"
    silence = build_silence_edit_plan(
        word_timestamps=_words(),
        text=text,
        clip_duration=8.0,
        editorial_type="risk_warning",
        mode="metadata",
    )
    assert silence.summary["tension_silences_preserved"] >= 1
    dead = build_silence_edit_plan(
        word_timestamps=[
            {"word": "hola", "start": 0.0, "end": 0.2},
            {"word": "seguimos", "start": 1.4, "end": 1.8},
        ],
        text="hola seguimos",
        clip_duration=4.0,
        editorial_type="generic",
        mode="safe_trim",
    )
    assert dead.summary["removed_dead_pauses"]
    plan = build_retention_editing_plan(
        clip_index=1,
        clip_duration_s=18.0,
        editorial_type="risk_warning",
        text=text,
        hook_plan={"hook_type": "risk_hook", "hook_first3_score": 7, "hook_first3_perceptible": True},
        silence_plan=silence.to_dict(),
    )
    meta = retention_plan_metadata(plan)
    assert meta["retention_plan"]

    subtitle_only = evaluate_clip_publishability({
        "hook_plan": {"hook_type": "risk_hook", "hook_first3_score": 5, "hook_first3_status": "weak", "hook_contract_satisfied": True},
        "music": {"music_tracks_found": 1, "music_applied": False},
        "editing_richness_status": "too_plain",
        "words": _words(),
        "brand_treatment": {"applied": True},
        "vpi_score": 90,
        "virality_score": 85,
    })
    assert subtitle_only.publishable_status.value != "ready_to_upload"

    strong = evaluate_clip_publishability({
        "hook_plan": {"hook_type": "risk_hook", "hook_first3_score": 8, "hook_first3_status": "strong", "hook_first3_perceptible": True, "hook_contract_satisfied": True},
        "music": {"music_tracks_found": 1, "music_applied": True, "music_final_verified": True},
        "sfx": {"sfx_design_applied": True, "sfx_applied": True},
        "visual_effects": {"visual_effects_applied": True, "frame_rhythm_applied": True},
        "silence_edit_plan": {"enabled": True, "summary": {"pattern_interruption_opportunities": 1}},
        "editing_plan": {"caption_visual_support_plan": {"enabled": True}},
        "editorial_broll": [{"reason": "semantic clarity", "semantic_score": 0.8, "transition_type": "short_fade"}],
        "editing_richness_score": 8,
        "editing_richness_status": "good",
        "words": _words(),
        "brand_treatment": {"applied": True},
        "output_qc": {"passed": True, "overall_score": 95},
        "vpi_score": 95,
        "virality_score": 90,
    })
    assert strong.retention_quality_status == "strong"
    print("hook_subtitle_only_fails=true")
    print("silence_preserve_and_cut=true")
    print("retention_gate_strong=true")
    print(f"retention_score={plan.retention_score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
