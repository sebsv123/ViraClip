#!/usr/bin/env python3
"""Offline runtime debug for VPI Silence Runtime Integration.

Does not render media and does not launch tasks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.services.vpi_silence_editor import build_silence_edit_plan  # noqa: E402
from src.services.vpi_silence_editor import load_silence_rules  # noqa: E402


CASES = [
    {
        "id": "emotional_miedo",
        "editorial_type": "emotional_protection",
        "before": "No se trata de vivir con miedo",
        "after": "Se trata de vivir con cierta organizacion",
        "pause": 0.45,
        "expected_action": "preserve_and_emphasize",
    },
    {
        "id": "filler",
        "editorial_type": "coverage_explanation",
        "before": "eh",
        "after": "bueno pues",
        "pause": 0.85,
        "expected_action": "shorten",
    },
    {
        "id": "dependen",
        "editorial_type": "emotional_protection",
        "before": "personas que dependen de ti",
        "after": "Ya no estas pensando solo en ti",
        "pause": 0.55,
        "expected_action": "preserve",
    },
    {
        "id": "weak_intro",
        "editorial_type": "weak_intro",
        "before": "Hola soy Sebastian",
        "after": "en este momento les vengo a hablar",
        "pause": 0.70,
        "expected_action": "shorten",
    },
    {
        "id": "client_reality",
        "editorial_type": "client_objection",
        "before": "eso ya me lo mirare mas adelante",
        "after": "y la realidad es que proteger no siempre va de edad",
        "pause": 0.40,
        "expected_action": "preserve_and_emphasize",
    },
]


def fake_words(before: str, after: str, pause: float) -> list[dict]:
    words: list[dict] = []
    t = 0.3
    for token in before.split():
        words.append({"word": token, "start": round(t, 2), "end": round(t + 0.22, 2)})
        t += 0.34
    t = round(words[-1]["end"] + pause, 2)
    for token in after.split():
        words.append({"word": token, "start": round(t, 2), "end": round(t + 0.22, 2)})
        t += 0.34
    return words


def main() -> int:
    load_silence_rules()
    failures = []
    rows = []
    for case in CASES:
        words = fake_words(case["before"], case["after"], case["pause"])
        text = f"{case['before']} {case['after']}"
        plan = build_silence_edit_plan(
            word_timestamps=words,
            text=text,
            clip_duration=max(word["end"] for word in words) + 1.0,
            editorial_type=case["editorial_type"],
            hook_plan={"end_s": 4.0},
            broll_events=[],
            subtitle_terms=[],
            mode="safe_trim",
            enabled=True,
        ).to_dict()
        first = (plan.get("segments") or [{}])[0]
        actual = first.get("action")
        if actual != case["expected_action"]:
            failures.append({"id": case["id"], "expected": case["expected_action"], "actual": actual})
        rows.append({
            "id": case["id"],
            "segments_detected": plan["summary"]["total_segments_detected"],
            "pause_type": first.get("pause_type"),
            "action": actual,
            "target_duration_s": first.get("target_duration_s"),
            "cuts": plan.get("cuts", []),
            "offset_map": plan.get("offset_map", []),
            "total_removed_s": plan.get("total_removed_s"),
        })

    print("VPI Silence Runtime Debug")
    print(f"cases_ok: {len(CASES) - len(failures)}")
    print(f"cases_failed: {len(failures)}")
    for row in rows:
        print(
            f"- {row['id']}: {row['pause_type']} -> {row['action']} "
            f"target={row['target_duration_s']} cuts={len(row['cuts'])} removed={row['total_removed_s']}"
        )
    print(json.dumps({"rows": rows, "failures": failures}, indent=2, ensure_ascii=False))
    return 1 if failures else 0


def check_config_paths() -> int:
    """Check that config files can be found by the silence editor."""
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    log = _logging.getLogger("check_config_paths")
    log.info("=" * 50)
    log.info("Checking silence config paths...")
    log.info("=" * 50)
    from src.services.vpi_silence_editor import load_silence_rules
    bundle = load_silence_rules()
    log.info("  loaded: %s", bundle.get("loaded"))
    log.info("  config_dir: %s", bundle.get("config_dir", "N/A"))
    log.info("  warnings: %s", bundle.get("warnings", []))
    log.info("  rules keys: %s", list((bundle.get("rules") or {}).keys()))
    log.info("  context keys: %s", list((bundle.get("context") or {}).keys()))
    return 0 if bundle.get("loaded") else 1


if __name__ == "__main__":
    import sys as _sys
    if "--check-config-paths" in _sys.argv:
        raise SystemExit(check_config_paths())
    raise SystemExit(main())
