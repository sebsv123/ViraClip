"""
Gate 2 — Post-render clip quality validation.
Runs after parallel rendering, before B-rolls and export.
Validates that rendered clips meet minimum viral quality criteria.
"""
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Thresholds
MIN_CLIPS_REQUIRED = 1
MIN_CLIP_DURATION_S = 5.0
MAX_CLIP_DURATION_S = 90.0
MIN_VIRAL_SCORE = 0.35        # score mínimo que Groq asignó al segmento
MIN_HOOK_RATIO = 0.0          # al menos 0 hooks explícitos (flexible por ahora)
MIN_TOTAL_DURATION_S = 10.0   # duración total mínima de todos los clips


def _get_clip_duration(clip: dict) -> float:
    """Extract duration from clip metadata."""
    # Intentar varios campos posibles
    for key in ("duration", "clip_duration", "length"):
        val = clip.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    
    # Calcular desde start/end si están disponibles
    start = clip.get("start_time") or clip.get("start", 0)
    end = clip.get("end_time") or clip.get("end", 0)
    try:
        return float(end) - float(start)
    except (TypeError, ValueError):
        return 0.0


def _get_viral_score(clip: dict, segment: dict) -> float:
    """Get viral/composite score from clip or matching segment."""
    for key in ("viral_score", "composite_score", "score", "virality_score"):
        val = clip.get(key) or segment.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return 0.5  # default neutro si no hay score


def check_clips_quality(clips: List[dict], segments: List[dict]) -> dict:
    """
    Validate rendered clips meet quality criteria.
    
    Args:
        clips: List of successfully rendered clip dicts
        segments: Original segments from Groq scoring (for viral scores)
    
    Returns:
        dict with passed, reason, recommendation, summary, best_score
    """
    if not clips:
        return {
            "passed": False,
            "reason": "No clips were rendered successfully",
            "recommendation": "Check FFmpeg logs and retry. Verify source video quality.",
            "summary": "0 clips rendered",
            "best_score": 0.0,
        }

    if len(clips) < MIN_CLIPS_REQUIRED:
        return {
            "passed": False,
            "reason": f"Only {len(clips)} clip(s) rendered, minimum is {MIN_CLIPS_REQUIRED}",
            "recommendation": "Lower the minimum clips threshold or provide longer content",
            "summary": f"{len(clips)} clips",
            "best_score": 0.0,
        }

    # Construir lookup de segmentos por índice
    seg_by_index = {i: s for i, s in enumerate(segments)}

    issues = []
    valid_clips = []
    scores = []
    total_duration = 0.0

    for i, clip in enumerate(clips):
        segment = seg_by_index.get(i, {})
        duration = _get_clip_duration(clip)
        viral_score = _get_viral_score(clip, segment)
        scores.append(viral_score)
        total_duration += duration

        clip_issues = []

        if duration < MIN_CLIP_DURATION_S:
            clip_issues.append(f"too short ({duration:.1f}s < {MIN_CLIP_DURATION_S}s)")
        if duration > MAX_CLIP_DURATION_S:
            clip_issues.append(f"too long ({duration:.1f}s > {MAX_CLIP_DURATION_S}s)")
        if viral_score < MIN_VIRAL_SCORE:
            clip_issues.append(f"low viral score ({viral_score:.2f} < {MIN_VIRAL_SCORE})")

        if clip_issues:
            issues.append(f"Clip {i+1}: {', '.join(clip_issues)}")
        else:
            valid_clips.append(clip)

    best_score = max(scores) if scores else 0.0
    avg_score = sum(scores) / len(scores) if scores else 0.0

    # Fallo si ningún clip es válido
    if not valid_clips:
        return {
            "passed": False,
            "reason": f"All {len(clips)} clips failed quality checks: {'; '.join(issues[:3])}",
            "recommendation": "Adjust segment selection criteria or source video",
            "summary": f"0/{len(clips)} clips valid",
            "best_score": best_score,
        }

    # Fallo si duración total muy corta
    if total_duration < MIN_TOTAL_DURATION_S:
        return {
            "passed": False,
            "reason": f"Total clip duration too short ({total_duration:.1f}s < {MIN_TOTAL_DURATION_S}s)",
            "recommendation": "Select longer segments or increase number of clips",
            "summary": f"total duration {total_duration:.1f}s",
            "best_score": best_score,
        }

    # Log advertencias si algunos clips fallaron pero no todos
    if issues:
        logger.warning(f"[Gate 2] {len(issues)} clip(s) with issues (non-blocking): {issues}")

    return {
        "passed": True,
        "reason": "Clips meet quality criteria",
        "recommendation": "",
        "summary": f"{len(valid_clips)}/{len(clips)} clips valid, avg_score={avg_score:.2f}, total={total_duration:.0f}s",
        "best_score": best_score,
    }
