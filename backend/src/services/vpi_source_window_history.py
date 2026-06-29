"""OUTPUT-SELECTION-52B — cross-task same-source delivered-window anti-repeat.

Deterministic, local-only helpers that let a new task on an already-used source
avoid re-delivering a window that a previous task already served.

Design constraints (BLOQUE OUTPUT-SELECTION-52B):
- No randomness, no thresholds lowered, no external embeddings.
- History is sourced exclusively from delivered clips already persisted in the
  `generated_clips` table (a row exists there only for a clip that was actually
  delivered — QC-GATE-52A hard-skips rejected clips before insertion). No new
  parallel memory architecture.
- Pure functions here; the DB query lives in ClipRepository and the integration
  point lives in task_service (after same-task dedupe, before the quality gate).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

from ..video_processing.utils import parse_timestamp_to_seconds

try:  # canonical YouTube id extraction already exists in the codebase
    from ..youtube_utils import get_youtube_video_id
except Exception:  # pragma: no cover - defensive
    get_youtube_video_id = None  # type: ignore


# ── FASE 5 thresholds (fixed, never lowered) ────────────────────────────────
TEMPORAL_OVERLAP_THRESHOLD = 0.70          # rule A: intersection / min(durations)
NEAR_EQUAL_START_DELTA = 2.0               # rule B: |start_delta| seconds
NEAR_EQUAL_END_DELTA = 3.0                 # rule B: |end_delta| seconds
TRANSCRIPT_SIMILARITY_THRESHOLD = 0.90     # rule C: token similarity

HISTORY_MAX_WINDOWS = 20                   # FASE 3: at most last 20 delivered windows


# ── FASE 1: canonical source identity ───────────────────────────────────────
def canonical_source_id(
    url: Optional[str],
    *,
    physical_hash: Optional[str] = None,
) -> tuple[str, str]:
    """Return (canonical_source_id, canonical_source_type).

    YouTube URLs that differ only in tracking/query params (si, t, feature, ...)
    collapse to the same `youtube:<video_id>`. Local uploads use the physical
    video hash, never the filename. Anything else falls back to a normalized URL
    string so behaviour stays deterministic.
    """
    raw = (url or "").strip()
    video_id = None
    if get_youtube_video_id is not None and raw:
        try:
            video_id = get_youtube_video_id(raw)
        except Exception:
            video_id = None
    if video_id:
        return f"youtube:{video_id}", "youtube"
    if physical_hash:
        return f"upload:{physical_hash}", "upload"
    norm = re.sub(r"\s+", "", raw.lower())
    return f"url:{norm}", "url"


def youtube_video_id_for(url: Optional[str]) -> Optional[str]:
    """Best-effort YouTube id, used to narrow the history DB query."""
    raw = (url or "").strip()
    if not raw or get_youtube_video_id is None:
        return None
    try:
        return get_youtube_video_id(raw)
    except Exception:
        return None


# ── FASE 4: deterministic transcript normalization + fingerprint ────────────
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_transcript(text: Optional[str]) -> str:
    """Lowercase, strip punctuation, collapse whitespace, keep all words."""
    t = (text or "").lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def transcript_fingerprint(normalized_transcript: str) -> str:
    return hashlib.sha1(normalized_transcript.encode("utf-8")).hexdigest()[:16]


def window_fingerprint(start_s: float, end_s: float, transcript: Optional[str]) -> str:
    """Deterministic fingerprint of a window. NOT the MP4 SHA — content identity."""
    norm = normalize_transcript(transcript)
    key = f"{round(float(start_s), 1)}|{round(float(end_s), 1)}|{norm}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def transcript_similarity(norm_a: str, norm_b: str) -> float:
    """Jaccard token similarity over normalized transcripts (deterministic)."""
    ta = norm_a.split()
    tb = norm_b.split()
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return len(sa & sb) / union


# ── FASE 5: duplicate decision ──────────────────────────────────────────────
def temporal_overlap_ratio(cs: float, ce: float, ps: float, pe: float) -> float:
    inter = max(0.0, min(ce, pe) - max(cs, ps))
    cd = max(0.0, ce - cs)
    pd = max(0.0, pe - ps)
    denom = min(cd, pd)
    if denom <= 0:
        return 0.0
    return inter / denom


def _window_from_seg(seg: Dict[str, Any]) -> Dict[str, Any]:
    start_s = float(parse_timestamp_to_seconds(seg.get("start_time")))
    end_s = float(parse_timestamp_to_seconds(seg.get("end_time")))
    text = seg.get("text") or seg.get("transcript") or ""
    norm = normalize_transcript(text)
    return {
        "start_s": start_s,
        "end_s": end_s,
        "transcript_norm": norm,
        "fingerprint": window_fingerprint(start_s, end_s, text),
    }


def evaluate_candidate_against_history(
    candidate_seg: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return duplicate metadata if `candidate_seg` repeats any delivered window.

    `history` items are normalized windows (see build_delivered_window_history).
    Returns None when the candidate is a genuinely new window.
    """
    cand = _window_from_seg(candidate_seg)
    cs, ce = cand["start_s"], cand["end_s"]
    for prev in history:
        ps, pe = prev["start_s"], prev["end_s"]
        overlap = temporal_overlap_ratio(cs, ce, ps, pe)
        sim = transcript_similarity(cand["transcript_norm"], prev["transcript_norm"])
        reasons: List[str] = []
        if overlap >= TEMPORAL_OVERLAP_THRESHOLD:
            reasons.append("temporal_overlap")
        if abs(cs - ps) <= NEAR_EQUAL_START_DELTA and abs(ce - pe) <= NEAR_EQUAL_END_DELTA:
            reasons.append("near_equal_window")
        if sim >= TRANSCRIPT_SIMILARITY_THRESHOLD:
            reasons.append("transcript_similarity")
        if cand["fingerprint"] and cand["fingerprint"] == prev.get("fingerprint"):
            reasons.append("same_fingerprint")
        if reasons:
            return {
                "reasons": reasons,
                "previous_task_id": prev.get("task_id"),
                "previous_clip_order": prev.get("clip_order"),
                "previous_window": prev.get("source_window"),
                "current_window": f"{cs:.2f}-{ce:.2f}",
                "temporal_overlap_ratio": round(overlap, 4),
                "transcript_similarity": round(sim, 4),
            }
    return None


# ── FASE 3: build normalized history from raw delivered-clip rows ───────────
def build_delivered_window_history(
    rows: List[Dict[str, Any]],
    target_canonical_id: str,
    *,
    limit: int = HISTORY_MAX_WINDOWS,
) -> List[Dict[str, Any]]:
    """Filter raw delivered-clip rows to the target canonical source and
    normalize each into a comparable window. Rows are expected newest-first.
    """
    history: List[Dict[str, Any]] = []
    seen_windows: set[tuple[float, float]] = set()
    for row in rows:
        src_url = row.get("source_url") or row.get("url")
        canon, _ = canonical_source_id(src_url)
        if canon != target_canonical_id:
            continue
        start_s = float(parse_timestamp_to_seconds(row.get("start_time")))
        end_s = float(parse_timestamp_to_seconds(row.get("end_time")))
        # Keep the last `limit` DISTINCT delivered windows. The same window can
        # be delivered many times across tasks; collapsing exact repeats stops
        # them from crowding out older distinct windows within the 20 budget
        # (so every previously-served window stays covered).
        window_key = (round(start_s, 1), round(end_s, 1))
        if window_key in seen_windows:
            continue
        seen_windows.add(window_key)
        text = row.get("text") or ""
        norm = normalize_transcript(text)
        history.append(
            {
                "task_id": row.get("task_id"),
                "clip_order": row.get("clip_order"),
                "start_s": start_s,
                "end_s": end_s,
                "source_window": f"{row.get('start_time')}-{row.get('end_time')}",
                "transcript_norm": norm,
                "fingerprint": window_fingerprint(start_s, end_s, text),
            }
        )
        if len(history) >= limit:
            break
    return history
