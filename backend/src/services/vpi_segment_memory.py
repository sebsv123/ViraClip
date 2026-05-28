"""
VPI Segment Memory v1.9 — Cross-run Diversity for Clip Selection
==================================================================

Prevents ViraClip from selecting the exact same segments every time
the same source video is processed.  Maintains a lightweight JSON
memory file and applies diversity penalties during ranking.

Problem:
  The scoring pipeline is deterministic — same video always produces
  the same top-N segments.  This is suspicious for daily use and
  reduces content variety.

Solution:
  A post-ranking diversity layer that penalizes recently-selected
  segments without destroying quality.  Memory is persisted to a
  local JSON file.

Flags (read from env, never modify .env):
  VIRACLIP_SEGMENT_DIVERSITY     (default: true in Beta Clean)
  VIRACLIP_SEGMENT_DIVERSITY_STRENGTH (default: medium)
  VIRACLIP_SEGMENT_MEMORY_PATH   (default: auto-detect)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MEMORY_PATH = "assets/.vpi_segment_memory.json"
FALLBACK_MEMORY_PATH = "/app/temp/vpi_segment_memory.json"

# Penalty values (applied to final_rank_score)
PENALTY_OVERLAP_24H = 35
PENALTY_OVERLAP_7D = 15
PENALTY_SAME_THEME_KEY = 15
PENALTY_EXACT_HASH = 45
PENALTY_SAME_TIME_WINDOW = 40
PENALTY_INTRA_THEME_KEY = 15
PENALTY_INTRA_TIMELINE_CLOSE = 20
MAX_TOTAL_PENALTY = 55

# Overlap threshold for "same segment"
OVERLAP_THRESHOLD = 0.70

# Strength multipliers
STRENGTH_MULTIPLIERS = {
    "low": 0.5,
    "medium": 1.0,
    "high": 1.5,
    "aggressive": 2.0,
}


# ══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SegmentMemoryEntry:
    """A single entry in the segment memory."""
    source_video_hash: str = ""
    source_video_id: str = ""
    task_id: str = ""
    segment_start: float = 0.0
    segment_end: float = 0.0
    duration: float = 0.0
    transcript_hash: str = ""
    editorial_type: str = ""
    duplicate_theme_key: str = ""
    final_rank_score: float = 0.0
    selected_at: str = ""  # ISO timestamp


@dataclass
class DiversityPenalty:
    """Penalty applied to a segment for diversity."""
    penalty: float = 0.0
    reasons: List[str] = field(default_factory=list)
    recently_used: bool = False
    segment_signature: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _is_beta_clean() -> bool:
    return os.environ.get("VIRACLIP_BETA_CLEAN", "").lower() in ("1", "true", "yes")


def diversity_enabled() -> bool:
    """Check if segment diversity is enabled.

    In Beta Clean mode, defaults to True unless explicitly disabled.
    Outside Beta Clean, defaults to False.
    """
    explicit = os.environ.get("VIRACLIP_SEGMENT_DIVERSITY")
    if explicit is not None:
        return explicit.lower() in ("1", "true", "yes", "on")
    return _is_beta_clean()


def diversity_strength() -> float:
    """Get the diversity strength multiplier."""
    raw = os.environ.get("VIRACLIP_SEGMENT_DIVERSITY_STRENGTH", "medium").lower().strip()
    return STRENGTH_MULTIPLIERS.get(raw, 1.0)


def _resolve_memory_path() -> Path:
    """Resolve the memory file path."""
    env_path = os.environ.get("VIRACLIP_SEGMENT_MEMORY_PATH")
    if env_path:
        return Path(env_path)

    # Try default path
    default = Path(DEFAULT_MEMORY_PATH)
    if default.parent.exists():
        return default

    # Fallback
    fallback = Path(FALLBACK_MEMORY_PATH)
    fallback.parent.mkdir(parents=True, exist_ok=True)
    return fallback


def compute_segment_signature(segment: Dict[str, Any]) -> str:
    """Compute a deterministic signature for a segment.

    Uses start_time, end_time, and transcript_hash to identify
    the same segment across runs.
    """
    start = segment.get("start_time", "00:00")
    end = segment.get("end_time", "00:00")
    text = segment.get("text", "")
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return f"{start}-{end}_{text_hash}"


def compute_transcript_hash(text: str) -> str:
    """Compute a hash of the transcript text."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def compute_source_video_hash(video_path: Optional[str]) -> str:
    """Compute a hash for the source video path."""
    if not video_path:
        return "unknown"
    return hashlib.md5(video_path.encode("utf-8")).hexdigest()[:16]


def _parse_timestamp(ts: str) -> float:
    """Parse a timestamp string (MM:SS or HH:MM:SS) to seconds."""
    try:
        parts = ts.strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(ts)
    except (ValueError, IndexError):
        return 0.0


def _compute_overlap(
    seg_start: float, seg_end: float,
    mem_start: float, mem_end: float,
) -> float:
    """Compute overlap ratio between two segments.

    Returns a value between 0.0 (no overlap) and 1.0 (identical).
    """
    if seg_end <= seg_start or mem_end <= mem_start:
        return 0.0

    intersection_start = max(seg_start, mem_start)
    intersection_end = min(seg_end, mem_end)
    intersection = max(0.0, intersection_end - intersection_start)

    seg_duration = seg_end - seg_start
    mem_duration = mem_end - mem_start
    union = max(seg_duration, mem_duration)

    if union <= 0:
        return 0.0

    return intersection / union


# ══════════════════════════════════════════════════════════════════════════════
# Memory I/O
# ══════════════════════════════════════════════════════════════════════════════

def load_segment_memory() -> List[Dict[str, Any]]:
    """Load segment memory from disk.

    Returns a list of memory entry dicts.
    Never raises — returns empty list on failure.
    """
    path = _resolve_memory_path()
    if not path.exists():
        logger.info("[segment-memory] path=%s loaded=false entries=0", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            logger.info("[segment-memory] path=%s loaded=true entries=%d", path, len(data))
            return data
        logger.info("[segment-memory] path=%s loaded=false entries=0", path)
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[segment-memory] load failed: %s", e)
        return []


def save_segment_memory(memory: List[Dict[str, Any]]) -> bool:
    """Save segment memory to disk.

    Returns True on success, False on failure.
    """
    path = _resolve_memory_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep only last 500 entries to prevent unbounded growth
        trimmed = memory[-500:]
        path.write_text(json.dumps(trimmed, indent=2, default=str), encoding="utf-8")
        logger.info("[segment-memory] path=%s saved=true entries=%d", path, len(trimmed))
        return True
    except OSError as e:
        logger.warning("[segment-memory] save failed: %s", e)
        return False


def remember_selected_segments(
    segments: List[Dict[str, Any]],
    task_id: str,
    source_video_path: Optional[str] = None,
    source_video_id: str = "",
) -> bool:
    """Record selected segments in memory.

    Call this AFTER clips have been successfully rendered.
    """
    if not segments:
        return False

    memory = load_segment_memory()
    now = datetime.utcnow().isoformat() + "Z"
    video_hash = compute_source_video_hash(source_video_path)

    for seg in segments:
        start = _parse_timestamp(seg.get("start_time", "00:00"))
        end = _parse_timestamp(seg.get("end_time", "00:00"))
        text = seg.get("text", "")
        entry = {
            "source_video_hash": video_hash,
            "source_video_id": source_video_id,
            "task_id": task_id,
            "segment_start": round(start, 2),
            "segment_end": round(end, 2),
            "duration": round(end - start, 2),
            "transcript_hash": compute_transcript_hash(text),
            "editorial_type": seg.get("editorial_type", ""),
            "duplicate_theme_key": seg.get("duplicate_theme_key", ""),
            "final_rank_score": seg.get("final_rank_score", 0.0),
            "selected_at": now,
        }
        memory.append(entry)

    ok = save_segment_memory(memory)
    logger.info("[segment-memory] remembered count=%d task=%s saved=%s", len(segments), task_id, str(ok).lower())
    return ok


def get_recent_segment_penalty(
    segment: Dict[str, Any],
    memory: List[Dict[str, Any]],
    source_video_hash: str,
    strength: float = 1.0,
) -> DiversityPenalty:
    """Compute diversity penalty for a segment based on memory.

    Args:
        segment: The candidate segment dict.
        memory: The loaded segment memory list.
        source_video_hash: Hash of the source video path.
        strength: Multiplier for penalties (from diversity_strength()).

    Returns:
        DiversityPenalty with penalty score and reasons.
    """
    result = DiversityPenalty()
    now = datetime.now(timezone.utc)

    seg_start = _parse_timestamp(segment.get("start_time", "00:00"))
    seg_end = _parse_timestamp(segment.get("end_time", "00:00"))
    seg_text = segment.get("text", "")
    seg_hash = compute_transcript_hash(seg_text)
    seg_theme_key = segment.get("duplicate_theme_key", "")
    seg_signature = compute_segment_signature(segment)
    result.segment_signature = seg_signature

    for entry in memory:
        # Only compare against same source video
        if entry.get("source_video_hash", "") != source_video_hash:
            continue

        mem_start = float(entry.get("segment_start", 0))
        mem_end = float(entry.get("segment_end", 0))
        mem_hash = entry.get("transcript_hash", "")
        mem_theme_key = entry.get("duplicate_theme_key", "")
        selected_at_str = entry.get("selected_at", "")

        # Parse timestamp
        try:
            selected_at = datetime.fromisoformat(selected_at_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            selected_at = now - timedelta(days=30)  # Old entry, low penalty
        if selected_at.tzinfo is None:
            selected_at = selected_at.replace(tzinfo=timezone.utc)

        age_hours = (now - selected_at).total_seconds() / 3600

        # ── Exact transcript hash match ──────────────────────────────────
        if seg_hash and seg_hash == mem_hash and age_hours <= 24:
            result.penalty += PENALTY_EXACT_HASH * strength
            result.reasons.append("exact_transcript_hash_24h:-45")
            result.recently_used = True

        # ── Overlap-based match ──────────────────────────────────────────
        overlap = _compute_overlap(seg_start, seg_end, mem_start, mem_end)
        if overlap >= OVERLAP_THRESHOLD:
            if age_hours <= 24:
                result.penalty += PENALTY_OVERLAP_24H * strength
                result.reasons.append(f"overlap_{overlap:.0%}_within_24h:-35")
                result.recently_used = True
            elif age_hours <= 168:  # 7 days
                result.penalty += PENALTY_OVERLAP_7D * strength
                result.reasons.append(f"overlap_{overlap:.0%}_within_7d:-15")
                result.recently_used = True

        if abs(seg_start - mem_start) <= 2.0 and abs(seg_end - mem_end) <= 2.0 and age_hours <= 24:
            result.penalty += PENALTY_SAME_TIME_WINDOW * strength
            result.reasons.append("same_start_end_2s_24h:-40")
            result.recently_used = True

        # ── Same duplicate_theme_key ─────────────────────────────────────
        if seg_theme_key and seg_theme_key == mem_theme_key and age_hours <= 168:
            result.penalty += PENALTY_SAME_THEME_KEY * strength
            result.reasons.append(f"same_theme_key_{seg_theme_key}:-15")
            result.recently_used = True

    # Cap total penalty
    result.penalty = min(result.penalty, MAX_TOTAL_PENALTY * strength)

    return result


def _score_for(seg: Dict[str, Any]) -> float:
    try:
        return float(seg.get("final_rank_score", seg.get("score_after_diversity", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _editorial_variety_bonus(seg: Dict[str, Any], selected_types: set[str]) -> float:
    editorial_type = str(seg.get("editorial_type") or "")
    family = {
        "emotional_protection": "emotional",
        "client_objection": "objection",
        "myth_debunk": "objection",
        "coverage_explanation": "explanation",
        "actionable_advice": "explanation",
        "risk_warning": "risk",
    }.get(editorial_type, editorial_type)
    return 8.0 if family and family not in selected_types else 0.0


def _apply_intra_task_diversity(segments: List[Dict[str, Any]], num_clips: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if len(segments) <= 1 or num_clips <= 1:
        return segments, []
    remaining = [dict(seg) for seg in segments]
    selected: List[Dict[str, Any]] = []
    logs: List[Dict[str, Any]] = []
    selected_theme_keys: set[str] = set()
    selected_types: set[str] = set()
    selected_windows: List[Tuple[float, float, str]] = []

    while remaining and len(selected) < min(num_clips, len(segments)):
        best_idx = 0
        best_score = -1e9
        best_penalty = 0.0
        best_reasons: List[str] = []
        for idx, seg in enumerate(remaining):
            base = float(seg.get("adjusted_rank_score", seg.get("final_rank_score", 0.0)) or 0.0)
            penalty = 0.0
            reasons: List[str] = []
            theme_key = str(seg.get("duplicate_theme_key") or "")
            start = _parse_timestamp(seg.get("start_time", "0"))
            end = _parse_timestamp(seg.get("end_time", "0"))
            if theme_key and theme_key in selected_theme_keys:
                penalty += PENALTY_INTRA_THEME_KEY
                reasons.append("same_theme_key")
                logger.info("[segment-diversity] intra_task_penalty reason=same_theme_key key=%s", theme_key)
            for selected_start, selected_end, selected_theme in selected_windows:
                too_close = abs(start - selected_start) < 20.0 or _compute_overlap(start, end, selected_start, selected_end) > 0.35
                if too_close and (not theme_key or not selected_theme or theme_key == selected_theme):
                    penalty += PENALTY_INTRA_TIMELINE_CLOSE
                    reasons.append("timeline_too_close")
                    logger.info("[segment-diversity] intra_task_penalty reason=timeline_too_close start=%.2f", start)
                    break
            score = base - penalty + _editorial_variety_bonus(seg, selected_types)
            if score > best_score:
                best_idx = idx
                best_score = score
                best_penalty = penalty
                best_reasons = reasons

        chosen = remaining.pop(best_idx)
        if best_penalty:
            chosen["diversity_penalty"] = round(float(chosen.get("diversity_penalty", 0.0) or 0.0) + best_penalty, 1)
            chosen["diversity_reasons"] = list(chosen.get("diversity_reasons") or []) + [f"intra_task:{reason}" for reason in best_reasons]
            chosen["score_after_diversity"] = round(max(0.0, float(chosen.get("score_after_diversity", chosen.get("final_rank_score", 0.0)) or 0.0) - best_penalty), 2)
            chosen["adjusted_rank_score"] = chosen["score_after_diversity"]
            logs.append({
                "signature": compute_segment_signature(chosen),
                "penalty": round(best_penalty, 1),
                "reasons": best_reasons,
            })
        selected.append(chosen)
        theme_key = str(chosen.get("duplicate_theme_key") or "")
        if theme_key:
            selected_theme_keys.add(theme_key)
        editorial_type = str(chosen.get("editorial_type") or "")
        if editorial_type in {"client_objection", "myth_debunk"}:
            selected_types.add("objection")
        elif editorial_type in {"coverage_explanation", "actionable_advice"}:
            selected_types.add("explanation")
        elif editorial_type:
            selected_types.add(editorial_type)
        selected_windows.append((_parse_timestamp(chosen.get("start_time", "0")), _parse_timestamp(chosen.get("end_time", "0")), theme_key))

    selected.extend(remaining)
    return selected, logs


def adjust_segments_for_diversity(
    segments: List[Dict[str, Any]],
    source_video_path: Optional[str],
    num_clips: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply diversity penalties and re-rank segments.

    This is the main entry point for the diversity layer.

    Args:
        segments: List of candidate segment dicts (already ranked).
        source_video_path: Path to the source video file.
        num_clips: Number of clips to select.

    Returns:
        Tuple of (adjusted_segments, diversity_metadata).
    """
    metadata: Dict[str, Any] = {
        "diversity_enabled": diversity_enabled(),
        "diversity_strength": diversity_strength(),
        "diversity_applied": False,
        "repeated_segments_avoided": 0,
        "memory_path": str(_resolve_memory_path()),
        "memory_entries_before": 0,
        "memory_entries_after": 0,
        "repeated_segments_allowed_reason": None,
        "penalties": [],
    }

    if not diversity_enabled() or not segments:
        return segments, metadata

    strength = diversity_strength()
    video_hash = compute_source_video_hash(source_video_path)
    memory = load_segment_memory()
    metadata["memory_entries_before"] = len(memory)
    metadata["memory_entries_after"] = len(memory)
    logger.info(
        "[segment-diversity] enabled=true candidates=%d clips=%d source_hash=%s",
        len(segments),
        num_clips,
        video_hash,
    )
    logger.info(
        "[segment-diversity] before top=%s",
        " | ".join(f"{seg.get('start_time')}-{seg.get('end_time')}:{_score_for(seg):.1f}" for seg in segments[:5]),
    )

    if not memory:
        logger.info("[segment-diversity] memory empty — no penalties applied")
        adjusted, intra_logs = _apply_intra_task_diversity(segments, num_clips)
        if intra_logs:
            metadata["penalties"].extend(intra_logs)
            metadata["diversity_applied"] = True
            metadata["repeated_segments_avoided"] = len(intra_logs)
        logger.info(
            "[segment-diversity] after top=%s",
            " | ".join(f"{seg.get('start_time')}-{seg.get('end_time')}:{seg.get('adjusted_rank_score', _score_for(seg)):.1f}" for seg in adjusted[:5]),
        )
        return adjusted, metadata

    # ── Quality guard: if we have very few candidates, skip diversity ──
    if len(segments) <= num_clips:
        logger.info(
            "[segment-diversity] only %d candidates for %d clips — skipping diversity",
            len(segments), num_clips,
        )
        for seg in segments:
            original_score = _score_for(seg)
            seg.setdefault("score_before_diversity", round(original_score, 2))
            seg.setdefault("score_after_diversity", round(original_score, 2))
            seg.setdefault("diversity_penalty", 0.0)
            seg.setdefault("diversity_reasons", ["few_candidates_quality_guard"])
            seg.setdefault("recently_used", False)
            seg.setdefault("memory_match", None)
        metadata["repeated_segments_allowed_reason"] = "few_candidates_quality_guard"
        return segments, metadata

    # ── Compute penalties ──────────────────────────────────────────────
    top_score = segments[0].get("final_rank_score", 0.0) if segments else 0.0
    second_score = segments[1].get("final_rank_score", 0.0) if len(segments) > 1 else 0.0
    score_gap = top_score - second_score

    adjusted = []
    for seg in segments:
        penalty = get_recent_segment_penalty(seg, memory, video_hash, strength)

        # ── Quality preservation: if top segment has huge lead, protect it ──
        # If this is the top segment and its score is >20 points above the
        # second candidate, don't penalize it enough to lose the top spot.
        if seg is segments[0] and score_gap > 25:
            logger.info(
                "[segment-diversity] top segment protected (gap=%.1f > 25)",
                score_gap,
            )
            penalty.penalty = 0.0
            penalty.reasons.append("quality_gap_protected")
            metadata["repeated_segments_allowed_reason"] = "quality_gap_protected"

        original_score = seg.get("final_rank_score", 0.0)
        adjusted_score = max(0.0, original_score - penalty.penalty)

        seg["diversity_penalty"] = round(penalty.penalty, 1)
        seg["diversity_reasons"] = penalty.reasons
        seg["recently_used"] = penalty.recently_used
        seg["memory_match"] = {
            "segment_signature": penalty.segment_signature,
            "matched": bool(penalty.reasons),
            "reasons": penalty.reasons,
        }
        seg["segment_signature"] = penalty.segment_signature
        seg["score_before_diversity"] = round(original_score, 2)
        seg["score_after_diversity"] = round(adjusted_score, 2)
        seg["adjusted_rank_score"] = adjusted_score

        adjusted.append(seg)

        if penalty.penalty > 0:
            metadata["penalties"].append({
                "signature": penalty.segment_signature,
                "penalty": round(penalty.penalty, 1),
                "reasons": penalty.reasons,
                "score_before": round(original_score, 2),
                "score_after": round(adjusted_score, 2),
            })
            logger.info(
                "[segment-diversity] segment=%s penalty=%.1f reasons=%s",
                penalty.segment_signature,
                penalty.penalty,
                penalty.reasons,
            )

    # ── Re-rank by adjusted score ──────────────────────────────────────
    adjusted.sort(key=lambda x: x.get("adjusted_rank_score", 0.0), reverse=True)
    adjusted, intra_logs = _apply_intra_task_diversity(adjusted, num_clips)
    if intra_logs:
        metadata["penalties"].extend(intra_logs)

    # Count how many segments changed position
    original_order = [compute_segment_signature(s) for s in segments]
    new_order = [compute_segment_signature(s) for s in adjusted]
    changes = sum(1 for a, b in zip(original_order, new_order) if a != b)
    metadata["diversity_applied"] = changes > 0 or bool(intra_logs) or bool(metadata["penalties"])
    metadata["repeated_segments_avoided"] = changes + len(intra_logs)
    logger.info(
        "[segment-diversity] after top=%s",
        " | ".join(f"{seg.get('start_time')}-{seg.get('end_time')}:{seg.get('adjusted_rank_score', _score_for(seg)):.1f}" for seg in adjusted[:5]),
    )

    logger.info(
        "[segment-diversity] applied=%s changes=%d penalties=%d",
        metadata["diversity_applied"],
        changes,
        len(metadata["penalties"]),
    )

    return adjusted, metadata
