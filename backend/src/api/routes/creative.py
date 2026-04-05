"""
Creative Analytics API — Phase 9.13

Exposes creative engine metadata for tasks and individual clips.

Endpoints:
  GET /creative/{task_id}           — full creative report for all clips in a task
  GET /creative/{task_id}/clip/{n}  — report for clip N (1-indexed)
  GET /creative/{task_id}/summary   — aggregate stats across all clips
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.task_manager import get_task_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/creative", tags=["creative-analytics"])

# ── Response models ───────────────────────────────────────────────────────────

_CREATIVE_KEYS = (
    "creative_enhanced",
    "timeline_events",
    "viral_score",
    "hook_score",
    "pacing_score",
    "emotion_score",
    "improvements",
    "preset_used",
    "hook_reorder_applied",
    "hook_already_optimized",
    "hook_reorder_suggested",
    "hook_text",
    "broll_overlays",
    "zoom_punch_applied",
    "color_grade_applied",
    "sfx_injected",
    "loudnorm_applied",
    "qa_passed",
    "qa_issues",
)


class ClipCreativeReport(BaseModel):
    clip_id: int
    filename: str
    creative_enhanced: bool
    timeline_events: int
    viral_score: Optional[float]
    hook_score: Optional[float]
    pacing_score: Optional[float]
    emotion_score: Optional[float]
    improvements: List[str]
    preset_used: Optional[str]
    hook_reorder_applied: bool
    hook_already_optimized: Optional[bool]
    hook_reorder_suggested: Optional[bool]
    hook_text: Optional[str]
    broll_overlays: int
    zoom_punch_applied: bool
    color_grade_applied: bool
    sfx_injected: int
    loudnorm_applied: bool
    qa_passed: Optional[bool]
    qa_issues: List[str]


class CreativeSummary(BaseModel):
    task_id: str
    total_clips: int
    enhanced_clips: int
    avg_viral_score: Optional[float]
    avg_hook_score: Optional[float]
    clips_with_broll: int
    clips_with_zoom_punch: int
    clips_with_loudnorm: int
    clips_hook_reordered: int
    clips_qa_passed: int
    top_improvements: List[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_clips(task_id: str) -> List[Dict[str, Any]]:
    """Pull clip list from task_manager state, raise 404 if missing."""
    task = get_task_status(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    result = task.get("result") or {}

    # coordinator returns {"clips": [...], ...} or a list directly
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        clips = result.get("clips") or result.get("clip_results") or []
        return clips if isinstance(clips, list) else []
    return []


def _clip_to_report(clip: Dict[str, Any]) -> ClipCreativeReport:
    return ClipCreativeReport(
        clip_id=clip.get("clip_id", 0),
        filename=clip.get("filename", ""),
        creative_enhanced=clip.get("creative_enhanced", False),
        timeline_events=clip.get("timeline_events", 0),
        viral_score=clip.get("viral_score"),
        hook_score=clip.get("hook_score"),
        pacing_score=clip.get("pacing_score"),
        emotion_score=clip.get("emotion_score"),
        improvements=clip.get("improvements") or [],
        preset_used=clip.get("preset_used"),
        hook_reorder_applied=clip.get("hook_reorder_applied", False),
        hook_already_optimized=clip.get("hook_already_optimized"),
        hook_reorder_suggested=clip.get("hook_reorder_suggested"),
        hook_text=clip.get("hook_text"),
        broll_overlays=clip.get("broll_overlays", 0),
        zoom_punch_applied=clip.get("zoom_punch_applied", False),
        color_grade_applied=clip.get("color_grade_applied", False),
        sfx_injected=clip.get("sfx_injected", 0),
        loudnorm_applied=clip.get("loudnorm_applied", False),
        qa_passed=clip.get("qa_passed"),
        qa_issues=clip.get("qa_issues") or [],
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{task_id}", response_model=List[ClipCreativeReport])
async def get_task_creative_report(task_id: str):
    """Return creative engine metadata for every clip in a task."""
    clips = _extract_clips(task_id)
    return [_clip_to_report(c) for c in clips]


@router.get("/{task_id}/clip/{clip_number}", response_model=ClipCreativeReport)
async def get_clip_creative_report(task_id: str, clip_number: int):
    """Return creative engine metadata for a single clip (1-indexed)."""
    clips = _extract_clips(task_id)
    if clip_number < 1 or clip_number > len(clips):
        raise HTTPException(
            status_code=404,
            detail=f"Clip {clip_number} not found in task '{task_id}' ({len(clips)} clips total)",
        )
    return _clip_to_report(clips[clip_number - 1])


@router.get("/{task_id}/summary", response_model=CreativeSummary)
async def get_task_creative_summary(task_id: str):
    """Return aggregate creative engine statistics across all clips in a task."""
    clips = _extract_clips(task_id)

    if not clips:
        return CreativeSummary(
            task_id=task_id,
            total_clips=0,
            enhanced_clips=0,
            avg_viral_score=None,
            avg_hook_score=None,
            clips_with_broll=0,
            clips_with_zoom_punch=0,
            clips_with_loudnorm=0,
            clips_hook_reordered=0,
            clips_qa_passed=0,
            top_improvements=[],
        )

    viral_scores = [c["viral_score"] for c in clips if c.get("viral_score") is not None]
    hook_scores  = [c["hook_score"]  for c in clips if c.get("hook_score")  is not None]

    # Aggregate improvement suggestions (de-duped, most common first)
    from collections import Counter
    improvement_counter: Counter = Counter()
    for c in clips:
        for imp in (c.get("improvements") or []):
            improvement_counter[imp] += 1
    top_improvements = [imp for imp, _ in improvement_counter.most_common(5)]

    return CreativeSummary(
        task_id=task_id,
        total_clips=len(clips),
        enhanced_clips=sum(1 for c in clips if c.get("creative_enhanced")),
        avg_viral_score=round(sum(viral_scores) / len(viral_scores), 1) if viral_scores else None,
        avg_hook_score=round(sum(hook_scores) / len(hook_scores), 1) if hook_scores else None,
        clips_with_broll=sum(1 for c in clips if (c.get("broll_overlays") or 0) > 0),
        clips_with_zoom_punch=sum(1 for c in clips if c.get("zoom_punch_applied")),
        clips_with_loudnorm=sum(1 for c in clips if c.get("loudnorm_applied")),
        clips_hook_reordered=sum(1 for c in clips if c.get("hook_reorder_applied")),
        clips_qa_passed=sum(1 for c in clips if c.get("qa_passed") is True),
        top_improvements=top_improvements,
    )
