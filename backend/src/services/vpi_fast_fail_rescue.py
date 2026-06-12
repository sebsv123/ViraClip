"""Pure helper for recovering editorial-only candidates before FAST_FAIL_EDITING_ZERO.

This module deliberately avoids importing the broader service stack so it can
be imported by regression scripts in lightweight host and container contexts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

EDITORIAL_ONLY_MARKERS = (
    "lower_requirements",
    "weak_hook",
    "incomplete_idea",
    "low_editorial_score",
    "hook_score",
    "editorial_score",
    "virality_score",
    "complete_idea_score",
    "renderability_score",
    "final_contract_score",
    "no_strong_hook",
    "weak_virality",
    "complete_idea_uncertain",
    "weak_dialogue",
    "editorial_only",
)

TECHNICAL_MARKERS = (
    "bts",
    "meta_production",
    "invalid_timestamp",
    "missing_source",
    "no_transcript",
    "duration_too_short",
    "cannot_extract",
    "pre_render_qc_error",
    "pre_render_qc_failed",
)


def _parse_timestamp_to_seconds(value: str) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        if ":" not in raw:
            return float(raw)
        parts = raw.split(":")
        total = 0.0
        for idx, part in enumerate(reversed(parts)):
            total += float(part) * (60 ** idx)
        return total
    except Exception:
        return 0.0


def _normalize_fast_fail_reason(raw: Any) -> str:
    if isinstance(raw, dict):
        reason = raw.get("reason")
        if reason is None:
            return ""
        return _normalize_fast_fail_reason(reason)
    if isinstance(raw, (list, tuple, set)):
        parts = [_normalize_fast_fail_reason(item) for item in raw]
        return " ".join(part for part in parts if part).strip().lower()
    return str(raw or "").strip().lower()


def is_editorial_only_fast_fail_reason(reason: Any, stage: Any = "") -> bool:
    normalized_reason = _normalize_fast_fail_reason(reason)
    normalized_stage = str(stage or "").strip().lower()

    # 1. Hard technical blockers in reason text always win.
    HARD_TECHNICAL = (
        "bts",
        "meta_production",
        "invalid_timestamp",
        "missing_source",
        "source_missing",
        "file_missing",
        "no_transcript",
        "duration_too_short",
        "cannot_extract",
        "ffmpeg",
        "corrupt",
        "decode",
        "no_video_stream",
    )
    if any(marker in normalized_reason for marker in HARD_TECHNICAL):
        return False

    # 2. Score/editorial-only evidence in reason text -> editorial even if
    #    stage is pre_render_qc_failed/pre_render_qc_error.
    SCORE_EDITORIAL_MARKERS = (
        "fast_fail_editing_zero:",
        "complete_idea_score",
        "renderability_score",
        "final_contract_score",
        "hook_score",
        "editorial_score",
        "virality_score",
        "lower_requirements",
        "< min=",
        "score=",
        "weak_hook",
        "incomplete_idea",
        "complete_idea_uncertain",
    )
    if any(marker in normalized_reason for marker in SCORE_EDITORIAL_MARKERS):
        return True

    # 3. Editorial-only markers from the broader list.
    if any(marker in normalized_reason for marker in EDITORIAL_ONLY_MARKERS):
        return True

    # 4. Stage-based technical check - only reached if reason text has no
    #    score/editorial evidence. pre_render_qc_failed alone is NOT enough
    #    to classify as technical when the reason is score-threshold/editorial.
    if any(marker in normalized_stage for marker in TECHNICAL_MARKERS):
        return False

    # 5. Fallback: empty reason is treated as editorial (allow recovery).
    return not normalized_reason


def segment_duration_seconds(segment: Dict[str, Any]) -> float:
    try:
        start = float(_parse_timestamp_to_seconds(str(segment.get("start_time") or 0)))
        end = float(_parse_timestamp_to_seconds(str(segment.get("end_time") or 0)))
        return max(0.0, end - start)
    except Exception:
        return 0.0


def recover_editorial_only_candidates_before_fast_fail(
    *,
    task_id: str,
    segments_to_render: List[Dict[str, Any]],
    rejected_segments: List[Dict[str, Any]],
    pre_render_pool: List[Dict[str, Any]],
    num_clips: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    recovered: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    editorial_only_count = 0
    technical_count = 0
    pool_fallback_used = False
    sample_reasons: List[str] = []
    sample_keys: List[str] = []

    def _segment_key(segment: Dict[str, Any]) -> str:
        return "|".join(
            [
                str(segment.get("segment_key") or segment.get("clip_index") or segment.get("candidate_index") or ""),
                str(segment.get("start_time") or ""),
                str(segment.get("end_time") or ""),
                str(segment.get("text") or segment.get("transcript_text") or ""),
            ]
        )

    pre_render_lookup: Dict[str, Dict[str, Any]] = {}
    for seg in pre_render_pool:
        if isinstance(seg, dict):
            pre_render_lookup[_segment_key(seg)] = seg

    def _usable_pool_candidates() -> List[Dict[str, Any]]:
        usable: List[Dict[str, Any]] = []
        for seg in pre_render_pool:
            if not isinstance(seg, dict):
                continue
            if str(seg.get("bts_contamination_ratio") or "").strip():
                try:
                    if float(seg.get("bts_contamination_ratio") or 0.0) >= 0.4:
                        continue
                except Exception:
                    continue
            text = str(seg.get("text") or seg.get("transcript_text") or "").strip()
            if not text:
                continue
            duration_s = segment_duration_seconds(seg)
            if duration_s and duration_s < 8.0:
                continue
            if duration_s and duration_s > 90.0:
                continue
            if not seg.get("start_time") or not seg.get("end_time"):
                continue
            usable.append(seg)
        return usable

    for item in rejected_segments:
        if not isinstance(item, dict):
            continue
        reason = item.get("reason")
        stage = item.get("stage")
        if not is_editorial_only_fast_fail_reason(reason, stage):
            technical_count += 1
            continue
        editorial_only_count += 1
        if len(sample_reasons) < 5:
            sample_reasons.append(str(reason or "editorial_only"))

        item_key = _segment_key(item)
        candidate = pre_render_lookup.get(item_key)
        if candidate is None:
            for seg in pre_render_pool:
                if not isinstance(seg, dict):
                    continue
                if str(seg.get("start_time") or "") == str(item.get("start_time") or "") and str(seg.get("end_time") or "") == str(item.get("end_time") or ""):
                    candidate = seg
                    break

        if candidate is None:
            pool_fallback_used = True
            for pool_candidate in _usable_pool_candidates():
                pool_key = _segment_key(pool_candidate)
                if pool_key in seen_keys:
                    continue
                candidate = dict(pool_candidate)
                candidate_key = pool_key
                break
            else:
                candidate = None
                candidate_key = ""
        else:
            candidate = dict(candidate)
            candidate_key = _segment_key(candidate)

        if candidate is None:
            continue
        if candidate_key in seen_keys:
            continue
        if str(candidate.get("bts_contamination_ratio") or "").strip():
            try:
                if float(candidate.get("bts_contamination_ratio") or 0.0) >= 0.4:
                    continue
            except Exception:
                pass
        text = str(candidate.get("text") or candidate.get("transcript_text") or "").strip()
        if not text and candidate in pre_render_pool:
            text = str(item.get("text") or item.get("transcript_text") or "").strip()
        if not text:
            if candidate in pre_render_pool:
                text = str(candidate.get("text") or candidate.get("transcript_text") or "").strip()
        if not text:
            continue
        duration_s = segment_duration_seconds(candidate)
        if duration_s and duration_s < 8.0:
            continue
        if duration_s and duration_s > 90.0:
            continue
        if not candidate.get("source_path") and not candidate.get("source_file") and not candidate.get("source_url"):
            if candidate not in pre_render_pool:
                continue
        candidate["_editorial_warning"] = True
        candidate["_editorial_warning_reason"] = str(reason or "score_contract_degraded_before_fast_fail")
        candidate["needs_review"] = True
        candidate["qc_status"] = "needs_review"
        candidate["rescue_reason"] = "score_contract_degraded_before_fast_fail"
        candidate["editorial_only_degraded"] = True
        # Propagate source_path from rejected item if candidate lacks it
        if not candidate.get("source_path") and item.get("source_path"):
            candidate["source_path"] = item["source_path"]
        # Ensure transcript_text is set (copy from text if missing)
        if not candidate.get("transcript_text") and candidate.get("text"):
            candidate["transcript_text"] = candidate["text"]
        if not candidate.get("transcript_text") and item.get("transcript_text"):
            candidate["transcript_text"] = item["transcript_text"]
        if not candidate.get("transcript_text") and item.get("text"):
            candidate["transcript_text"] = item["text"]
        # Mark as contract-approved so the hook_fit stage does not reject
        # rescued segments with "no_candidate_or_transcript".
        candidate["contract_approved"] = True
        candidate.setdefault("hook_support", {})["executable"] = True
        candidate.setdefault("visual_support", {})["executable"] = True
        candidate["complete_idea_pass"] = True
        candidate["contract_would_runtime_reject"] = False
        recovered.append(candidate)
        seen_keys.add(candidate_key)
        if len(sample_keys) < 5:
            sample_keys.append(candidate_key)
        if len(recovered) >= num_clips:
            break

    metadata = {
        "editorial_only_count": editorial_only_count,
        "technical_count": technical_count,
        "sample_reasons": sample_reasons,
        "sample_keys": sample_keys,
        "recovered_count": len(recovered),
        "pool_fallback_used": pool_fallback_used,
    }
    return recovered, metadata


def _apply_fast_fail_rescue_to_render_input(
    *,
    task_id: str,
    render_input: List[Dict[str, Any]],
    rejected_segments: List[Dict[str, Any]],
    pre_render_pool: List[Dict[str, Any]],
    num_clips: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Recover editorial-only failures and return the renderable input list.

    This is the actual handoff point between the zero-clip rescue and the
    render loop. It preserves the render input contract used by TaskService:
    the returned list is the one that must be rendered and persisted.
    """

    render_input_before = [seg for seg in (render_input or []) if isinstance(seg, dict)]
    recovered_segments: List[Dict[str, Any]] = list(render_input_before)
    recovery_meta: Dict[str, Any] = {
        "render_input_count_before": len(render_input_before),
        "render_input_count_after": len(render_input_before),
        "should_fast_fail": len(render_input_before) == 0,
        "rescue_applied": False,
        "task_id": task_id,
    }

    if render_input_before:
        return recovered_segments[:num_clips], recovery_meta

    recovered_segments, inner_meta = recover_editorial_only_candidates_before_fast_fail(
        task_id=task_id,
        segments_to_render=render_input_before,
        rejected_segments=rejected_segments,
        pre_render_pool=pre_render_pool,
        num_clips=num_clips,
    )
    recovered_segments = list(recovered_segments[:num_clips])
    recovery_meta.update(inner_meta)
    recovery_meta["render_input_count_after"] = len(recovered_segments)
    recovery_meta["should_fast_fail"] = len(recovered_segments) == 0
    recovery_meta["rescue_applied"] = len(recovered_segments) > 0
    return recovered_segments, recovery_meta
