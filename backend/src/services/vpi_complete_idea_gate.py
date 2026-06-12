"""Pure helpers for the complete_idea render gate.

This module intentionally stays dependency-light so behavior regressions can
import it without pulling in the full video rendering stack.
"""

from __future__ import annotations

from typing import Any, Dict


def _is_rescued_editorial_warning_segment(segment: Dict[str, Any]) -> bool:
    """Return True for clips recovered from editorial-only fast-fail rescue."""
    if not isinstance(segment, dict):
        return False

    reason_blob = " ".join(
        str(value or "")
        for value in (
            segment.get("rescue_reason"),
            segment.get("_editorial_warning_reason"),
            segment.get("complete_idea_warning_reason"),
            segment.get("reason"),
            segment.get("stage"),
            segment.get("text"),
            segment.get("transcript_text"),
        )
    ).strip().lower()

    if any(marker in reason_blob for marker in ("meta_production_or_bts", "detrás de cámaras", "behind the scenes", "behind_the_scenes")):
        return False

    return any(
        (
            bool(segment.get("needs_review")),
            str(segment.get("qc_status") or "").strip().lower() == "needs_review",
            bool(segment.get("_editorial_warning")),
            bool(segment.get("recovered_from_pre_render_pool")),
            bool(segment.get("fast_fail_rescue")),
            bool(segment.get("_fast_fail_rescue")),
            "score_contract_degraded_before_fast_fail" in reason_blob,
            "score_contract_candidates_recovered" in reason_blob,
            "editorial_only_degraded_before_fast_fail" in reason_blob,
        )
    )


def _should_degrade_complete_idea_gate(segment: Dict[str, Any], stage: str, reason: str) -> bool:
    """Return True when a rescued editorial-warning clip should bypass complete_idea fatality."""
    return (
        str(stage or "").strip().lower() == "complete_idea"
        and str(reason or "").strip().lower() == "incomplete_thought"
        and _is_rescued_editorial_warning_segment(segment)
    )
