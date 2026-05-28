#!/usr/bin/env python3
"""Offline validator for VPI silence editing rules.

This script intentionally does not import ViraClip runtime modules.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "configs" / "vpi_silence_editing_rules.json"
CONTEXT_PATH = ROOT / "configs" / "vpi_silence_context_rules.json"
TESTS_PATH = ROOT / "configs" / "vpi_silence_test_cases.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def contains_any(text: str, keywords: list[str]) -> bool:
    normalized = normalize(text)
    return any(normalize(keyword) in normalized for keyword in keywords)


def clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)


def decide_pause_action(case: dict[str, Any], rules: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    before = str(case.get("before_text") or "")
    after = str(case.get("after_text") or "")
    editorial_type = str(case.get("editorial_type") or "")
    duration = float(case.get("pause_duration_s") or 0.0)
    hook_window = bool(case.get("hook_window"))
    broll_nearby = bool(case.get("broll_nearby"))
    subtitle_nearby = bool(case.get("subtitle_nearby"))

    global_rules = rules["global"]
    before_keywords = context["before_keywords"]
    after_keywords = context["after_keywords"]
    fillers = context["filler_before_keywords"]
    cta_after = context["cta_after_keywords"]
    examples = context["between_examples_keywords"]

    before_filler = contains_any(before, fillers)
    before_strong = contains_any(before, before_keywords)
    after_strong = contains_any(after, after_keywords)
    after_cta = contains_any(after, cta_after)
    between_examples = contains_any(before, examples) and contains_any(after, examples)

    if before_filler and broll_nearby and duration >= 0.6:
        return decision("awkward_pause", "cover_with_broll", 0.25, "post_filler_broll_cover")
    if before_filler:
        return decision("awkward_pause", "shorten", 0.15, "post_filler")
    if editorial_type == "weak_intro" and duration >= 0.45:
        return decision("dead_air", "shorten", 0.18, "weak_intro_cleanup")
    if broll_nearby and not hook_window and 0.25 <= duration <= 0.7:
        return decision("transition_pause", "use_as_transition", clamp(duration, 0.25, 0.35), "broll_transition")
    if subtitle_nearby and duration <= 0.5:
        return decision("subtitle_breath_pause", "avoid_cut", duration, "subtitle_breath")
    if after_cta and duration <= global_rules["max_preserved_pause_s"]:
        return decision("cta_pause", "preserve", duration, "cta_human_close")
    if normalize(before).endswith("antes de") or normalize(before) in {"antes de"}:
        return decision("breath_pause", "avoid_cut", duration, "inside_syntax")
    if editorial_type == "risk_warning" and (before_strong or after_strong) and duration > 0.7:
        return decision("dramatic_pause", "shorten", 0.5, "risk_tension_too_long")
    if editorial_type in {"risk_warning", "myth_debunk"} and after_strong and duration >= 0.35:
        return decision("dramatic_pause", "preserve_and_emphasize", clamp(duration, 0.35, 0.45), "controlled_reveal")
    if editorial_type == "emotional_protection" and before_strong and hook_window and duration <= 0.6:
        return decision("emphasis_pause", "preserve_and_emphasize", clamp(duration, 0.35, 0.45), "emotional_hook_contrast")
    if editorial_type == "client_objection" and contains_any(before, ["no es solo"]) and duration <= 0.35:
        return decision("let_it_land_pause", "preserve", duration, "hook_phrase_lands")
    if after_strong and (hook_window or duration >= 0.2):
        return decision("emphasis_pause", "preserve_and_emphasize", clamp(duration, 0.25, 0.45), "before_strong_phrase")
    if before_strong and duration <= 0.65:
        target = clamp(duration, 0.3, 0.55) if duration >= 0.35 else duration
        return decision("let_it_land_pause", "preserve", target, "after_strong_phrase")
    if between_examples and duration <= 0.4:
        return decision("transition_pause", "preserve", duration, "list_rhythm")
    if duration >= global_rules["dead_air_cut_threshold_s"]:
        if editorial_type == "coverage_explanation":
            return decision("thinking_pause", "shorten", 0.25, "long_thinking_explanation")
        return decision("dead_air", "cut", 0.0, "long_dead_air")
    if normalize(before).endswith("antes de") or normalize(before) in {"antes de", "porque"}:
        return decision("breath_pause", "avoid_cut", duration, "inside_syntax")
    if duration <= global_rules["micro_pause_keep_range_s"][1]:
        return decision("breath_pause", "preserve", duration, "micro_breath")
    return decision("thinking_pause", "shorten", 0.25, "default_shortening")


def decision(pause_type: str, action: str, target: float, reason: str) -> dict[str, Any]:
    return {
        "pause_type": pause_type,
        "action": action,
        "target_duration_s": round(float(target), 2),
        "reason": reason
    }


def main() -> int:
    rules = load_json(RULES_PATH)
    context = load_json(CONTEXT_PATH)
    tests = load_json(TESTS_PATH)
    cases = tests.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("vpi_silence_test_cases.json must contain non-empty cases list")

    failures: list[dict[str, Any]] = []
    actions: Counter[str] = Counter()
    pause_types: Counter[str] = Counter()

    for case in cases:
        result = decide_pause_action(case, rules, context)
        actions[result["action"]] += 1
        pause_types[result["pause_type"]] += 1
        if result["action"] != case.get("expected_action"):
            failures.append({
                "id": case.get("id"),
                "expected_action": case.get("expected_action"),
                "actual_action": result["action"],
                "expected_pause_type": case.get("expected_pause_type"),
                "actual_pause_type": result["pause_type"],
                "reason": result["reason"]
            })

    ok = len(cases) - len(failures)
    print("VPI Silence Rules Debug")
    print(f"cases_ok: {ok}")
    print(f"cases_failed: {len(failures)}")
    print(f"action_distribution: {dict(sorted(actions.items()))}")
    print(f"pause_type_distribution: {dict(sorted(pause_types.items()))}")
    print("examples:")
    for case in cases[:5]:
        result = decide_pause_action(case, rules, context)
        print(f"- {case['id']}: {result['pause_type']} -> {result['action']} ({result['target_duration_s']}s)")
    if failures:
        print("failures:")
        for failure in failures:
            print(json.dumps(failure, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
