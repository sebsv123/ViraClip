"""OUTPUT-TIMELINE-24 — Canonical post-silence word remap + closure protection.

Single source of truth for re-timing words to the EXACT segments ffmpeg concatenates
after silence/dead-air compression, and for protecting the approved closing phrase from
being intersected by silence cuts. Segment-based (never total-duration approximation).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_EPS = 1e-3


def _norm_ranges(removed_ranges: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    out = []
    for r in removed_ranges or []:
        if isinstance(r, dict):
            s = float(r.get("start_s", r.get("start", 0.0)) or 0.0)
            e = float(r.get("end_s", r.get("end", s)) or s)
        else:
            s, e = float(r[0]), float(r[1])
        if e > s + _EPS:
            out.append((round(s, 3), round(e, 3)))
    return sorted(out, key=lambda x: x[0])


def _removed_before(t: float, ranges: List[Tuple[float, float]]) -> float:
    """Total removed duration strictly before time t (segment-based, not total)."""
    removed = 0.0
    for s, e in ranges:
        if e <= t:
            removed += (e - s)
        elif s < t < e:
            removed += (t - s)  # partial (word inside a removed range edge)
        else:
            break
    return round(removed, 3)


def _in_removed(start: float, end: float, ranges: List[Tuple[float, float]]) -> bool:
    """True if the word is substantially inside a removed range."""
    for s, e in ranges:
        ov = min(end, e) - max(start, s)
        dur = max(_EPS, end - start)
        if ov > 0 and ov >= 0.5 * dur:
            return True
    return False


def remap_words_after_silence_compression(
    words: Optional[Sequence[Dict[str, Any]]],
    removed_ranges: Sequence[Any],
    kept_segments: Optional[Sequence[Any]] = None,
    closure_range: Optional[Tuple[float, float]] = None,
) -> Dict[str, Any]:
    """Remap word timestamps onto the post-silence concat timeline."""
    words = list(words or [])
    ranges = _norm_ranges(removed_ranges)
    total_removed = round(sum(e - s for s, e in ranges), 3)
    logger.info("VPI_POST_SILENCE_REMAP_STARTED words=%d removed_ranges=%d removed_s=%.3f", len(words), len(ranges), total_removed)

    out_words: List[Dict[str, Any]] = []
    removed_count = 0
    last_end = 0.0
    for w in words:
        try:
            ws = float(w.get("start", 0.0) or 0.0)
            we = float(w.get("end", ws) or ws)
        except (TypeError, ValueError):
            continue
        if _in_removed(ws, we, ranges):
            removed_count += 1
            logger.info("VPI_POST_SILENCE_WORD_REMOVED word=%r start=%.3f end=%.3f", str(w.get("word") or w.get("text") or ""), ws, we)
            continue
        ns = round(ws - _removed_before(ws, ranges), 3)
        ne = round(we - _removed_before(we, ranges), 3)
        # monotonic + clamp tiny float errors
        ns = max(0.0, ns, last_end - _EPS if out_words else 0.0)
        ne = max(ns + _EPS, ne)
        nw = dict(w); nw["start"] = round(ns, 3); nw["end"] = round(ne, 3)
        out_words.append(nw)
        last_end = ne
    logger.info("VPI_POST_SILENCE_WORD_SHIFTED kept=%d removed=%d", len(out_words), removed_count)

    final_word_end = round(out_words[-1]["end"], 3) if out_words else 0.0
    expected_final_duration = None
    if kept_segments:
        try:
            expected_final_duration = round(sum(
                (float(s.get("end_s", s.get("end", 0.0))) - float(s.get("start_s", s.get("start", 0.0))))
                if isinstance(s, dict) else (float(s[1]) - float(s[0]))
                for s in kept_segments
            ), 3)
        except Exception:
            expected_final_duration = None

    closure_start = closure_end = None
    if closure_range:
        cs, ce = float(closure_range[0]), float(closure_range[1])
        closure_start = round(cs - _removed_before(cs, ranges), 3)
        closure_end = round(ce - _removed_before(ce, ranges), 3)
        logger.info("VPI_POST_SILENCE_CLOSURE_REMAPPED start=%.3f end=%.3f", closure_start, closure_end)

    monotonic = all(out_words[i]["start"] <= out_words[i + 1]["start"] + _EPS for i in range(len(out_words) - 1)) \
        and all(w["end"] >= w["start"] for w in out_words) and all(w["start"] >= -_EPS for w in out_words)

    logger.info("VPI_POST_SILENCE_REMAP_COMPLETE final_word_end=%.3f monotonic=%s", final_word_end, str(monotonic).lower())
    return {
        "words": out_words,
        "post_silence_words_count_before": len(words),
        "post_silence_words_count_after": len(out_words),
        "post_silence_removed_duration_s": total_removed,
        "post_silence_final_word_end_s": final_word_end,
        "post_silence_closure_start_s": closure_start,
        "post_silence_closure_end_s": closure_end,
        "post_silence_remap_monotonic": bool(monotonic),
        "post_silence_remap_source": "segment_offset_map",
        "post_silence_expected_final_duration_s": expected_final_duration,
    }


def protect_closure_in_cuts(
    cuts: Sequence[Dict[str, Any]],
    closure_range: Tuple[float, float],
    *,
    margin_s: float = 0.20,
) -> Dict[str, Any]:
    """Adjust/reject silence cuts that intersect the protected closure region."""
    cs = float(closure_range[0]) - margin_s
    ce = float(closure_range[1]) + margin_s
    logger.info("VPI_SILENCE_CLOSURE_PROTECTED range=%.3f-%.3f margin=%.2f", cs, ce, margin_s)
    adjusted = 0
    rejected = 0
    out: List[Dict[str, Any]] = []
    for c in cuts or []:
        s = float(c.get("start_s", c.get("start", 0.0)) or 0.0)
        e = float(c.get("end_s", c.get("end", s)) or s)
        if e <= cs or s >= ce:
            out.append(dict(c)); continue  # fully outside closure -> keep
        logger.info("VPI_SILENCE_CUT_CLOSURE_INTERSECTION cut=%.3f-%.3f closure=%.3f-%.3f", s, e, cs, ce)
        # cut starts before closure: shorten its end to closure start
        if s < cs < e <= ce:
            new = dict(c); new["end_s"] = round(cs, 3); new["start_s"] = round(s, 3)
            new["removed_s"] = round(max(0.0, cs - s), 3)
            if new["removed_s"] > 0.05:
                out.append(new); adjusted += 1
                logger.info("VPI_SILENCE_CUT_ADJUSTED_FOR_CLOSURE new_end=%.3f", cs)
            else:
                rejected += 1
                logger.info("VPI_SILENCE_CUT_REJECTED_FOR_CLOSURE cut=%.3f-%.3f", s, e)
            continue
        # cut ends after closure but starts inside, or fully spans closure -> reject
        rejected += 1
        logger.info("VPI_SILENCE_CUT_REJECTED_FOR_CLOSURE cut=%.3f-%.3f", s, e)
    return {
        "cuts": out,
        "closure_protected_range": [round(cs, 3), round(ce, 3)],
        "silence_cuts_adjusted_for_closure": adjusted,
        "silence_cuts_rejected_for_closure": rejected,
    }
