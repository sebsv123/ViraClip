"""
Smart Auto Editor API — ViraClip

AI-powered editing endpoint: analyzes transcript + word timings,
generates an FFmpeg edit script and applies text-pop overlays.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.smart_auto_editor import get_smart_auto_editor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auto-editor", tags=["auto-editor"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class EditRulesConfig(BaseModel):
    hook_zoom_enabled: bool = True
    hook_zoom_intensity: float = 1.15
    min_silence_sec: float = 0.3
    jump_cut_enabled: bool = True
    speed_ramp_enabled: bool = True
    text_pop_enabled: bool = True
    color_boost_enabled: bool = True


class AnalyzeAndEditRequest(BaseModel):
    transcript: str
    word_timings: List[Dict[str, Any]]      # [{"word": str, "start": float, "end": float}]
    video_path: Optional[str] = None
    rules: Optional[EditRulesConfig] = None


class ApplyTextPopsRequest(BaseModel):
    clip_path: str
    output_path: str
    decisions: List[Dict[str, Any]]       # edit decisions with type=TEXT_POP
    hook_offset: float = 0.0


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/analyze")
async def analyze_and_edit(body: AnalyzeAndEditRequest):
    """
    Analyze transcript and word timings, then generate an intelligent edit plan.

    Returns cut points, silence segments to remove, zoom-punch moments,
    pacing score, and an FFmpeg filter script.
    """
    if not body.transcript.strip():
        raise HTTPException(status_code=400, detail="transcript must not be empty")
    if not body.word_timings:
        raise HTTPException(status_code=400, detail="word_timings must not be empty")

    editor = get_smart_auto_editor()
    try:
        result = await editor.analyze_and_edit(
            body.transcript,
            body.word_timings,
            Path(body.video_path) if body.video_path else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "edit_plan": result}


@router.post("/text-pops")
async def apply_text_pops(body: ApplyTextPopsRequest):
    """
    Overlay animated text-pop captions on a clip.

    Returns the output path on success.
    """
    if not body.decisions:
        raise HTTPException(status_code=400, detail="decisions must not be empty")
    editor = get_smart_auto_editor()
    try:
        output = await editor.apply_text_pops(
            Path(body.clip_path),
            Path(body.output_path),
            body.decisions,
            body.hook_offset,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "output_path": str(output)}


@router.get("/default-rules")
def default_rules():
    """Return the default auto-editor rule configuration."""
    from ...services.smart_auto_editor import ViralEditRules
    rules = ViralEditRules()
    return {
        "hook_zoom_enabled": rules.hook_zoom_enabled,
        "hook_zoom_intensity": rules.hook_zoom_intensity,
        "silence_threshold_db": rules.silence_threshold_db,
        "min_silence_sec": rules.min_silence_sec,
        "max_silence_sec": rules.max_silence_sec,
        "jump_cut_enabled": rules.jump_cut_enabled,
        "speed_ramp_enabled": rules.speed_ramp_enabled,
        "text_pop_enabled": rules.text_pop_enabled,
        "color_boost_enabled": rules.color_boost_enabled,
    }
