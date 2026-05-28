#!/usr/bin/env python3
"""Offline smoke test for VPI B-roll hard guard rules."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.services.vpi_broll_intent import is_broll_asset_forbidden  # noqa: E402


BASE_CONTEXT: Dict[str, Any] = {
    "central_topic": "life_insurance_family_protection",
    "theme_topic": "life_insurance_family_protection",
    "intent_type": "family_responsibility",
    "task_seen_asset_ids": {"pexels:dup-provider"},
    "task_seen_provider_video_ids": {"dup-provider"},
    "task_seen_visual_fingerprints": {"family_protection:family_home:repeated"},
    "task_seen_filename_stems": {"repeated"},
    "strict_fingerprint_repeat": True,
}


CASES = [
    {
        "name": "tea cup video",
        "asset": {"path": "/app/assets/broll/emotional_reassurance/02.mp4", "category": "emotional_reassurance"},
        "context": {"category": "emotional_reassurance", "query": "calm family tea cup at home"},
        "expected_forbidden": True,
    },
    {
        "name": "meditation",
        "asset": {"path": "/tmp/meditation_family_wellness.mp4", "category": "family_protection"},
        "context": {"category": "family_protection", "query": "meditation wellness relaxation"},
        "expected_forbidden": True,
    },
    {
        "name": "documents repeated",
        "asset": {"path": "/app/assets/broll/documents_admin/repeated.mp4", "category": "documents_admin"},
        "context": {
            "category": "documents_admin",
            "documents_already_used": True,
            "visual_fingerprint": "documents_admin:documents_closeup:repeated",
        },
        "expected_forbidden": True,
    },
    {
        "name": "advisor consultation",
        "asset": {"path": "/tmp/financial_advisor_family_documents.mp4", "category": "advisor_consultation"},
        "context": {"category": "advisor_consultation", "query": "financial advisor explaining contract to young couple"},
        "expected_forbidden": False,
    },
    {
        "name": "family planning",
        "asset": {"path": "/tmp/family_financial_planning_home.mp4", "category": "family_protection"},
        "context": {"category": "family_protection", "query": "family financial planning at home"},
        "expected_forbidden": False,
    },
    {
        "name": "duplicate provider id",
        "asset": {"path": "/tmp/provider_duplicate.mp4", "category": "advisor_consultation"},
        "context": {
            "category": "advisor_consultation",
            "asset_id": "pexels:dup-provider",
            "provider_video_id": "dup-provider",
        },
        "expected_forbidden": True,
    },
]


def run() -> int:
    failures = 0
    distribution: Counter[str] = Counter()
    print("VPI B-roll Hard Guard Debug")
    for case in CASES:
        context = dict(BASE_CONTEXT)
        context.update(case.get("context") or {})
        forbidden, reasons = is_broll_asset_forbidden(case["asset"], context)
        distribution["forbidden" if forbidden else "accepted"] += 1
        ok = forbidden == case["expected_forbidden"]
        if not ok:
            failures += 1
        status = "OK" if ok else "FAIL"
        verdict = "rejected" if forbidden else "accepted"
        print(f"- {status} {case['name']}: {verdict} reasons={','.join(reasons) or '-'}")

    print(f"summary: ok={len(CASES) - failures} fail={failures} distribution={dict(distribution)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
