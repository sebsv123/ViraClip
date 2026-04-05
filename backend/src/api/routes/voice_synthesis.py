"""
Voice Synthesis API — ViraClip

Endpoints for text-to-speech synthesis, voice cloning, narration
generation, and video narration mixing.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.voice_synthesis import (
    SynthesisProvider,
    VoiceStyle,
    get_voice_synthesis_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SynthesizeRequest(BaseModel):
    voice_id: str
    text: str
    style: str = "natural"
    speed: float = 1.0
    pitch: float = 1.0
    emotion: str = "neutral"
    provider: str = "elevenlabs"


class NarrationRequest(BaseModel):
    video_script: str
    voice_id: str
    style: str = "natural"
    segments: Optional[List[Dict[str, Any]]] = None


class MixRequest(BaseModel):
    video_path: str
    job_ids: List[str]          # completed synthesis job IDs
    output_path: str
    ducking_level: float = 0.3


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_style(value: str) -> VoiceStyle:
    try:
        return VoiceStyle(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown style '{value}'. Valid: {[s.value for s in VoiceStyle]}",
        )


def _parse_provider(value: str) -> SynthesisProvider:
    try:
        return SynthesisProvider(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{value}'. Valid: {[p.value for p in SynthesisProvider]}",
        )


def _fmt_job(job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "voice_id": job.voice_id,
        "text_preview": job.text[:80] + ("…" if len(job.text) > 80 else ""),
        "style": job.style.value,
        "speed": job.speed,
        "pitch": job.pitch,
        "emotion": job.emotion,
        "status": job.status,
        "output_path": str(job.output_path) if job.output_path else None,
        "duration": job.duration,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _fmt_profile(p) -> Dict[str, Any]:
    return {
        "voice_id": p.voice_id,
        "name": p.name,
        "description": p.description,
        "age": p.age,
        "gender": p.gender,
        "accent": p.accent,
        "language": p.language,
        "cloned": p.cloned,
        "created_at": p.created_at,
        "usage_count": p.usage_count,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/voices")
def list_voices(cloned_only: bool = False):
    """List all available voice profiles, sorted by usage count."""
    svc = get_voice_synthesis_service()
    profiles = svc.get_voice_profiles(cloned_only=cloned_only)
    return {"count": len(profiles), "voices": [_fmt_profile(p) for p in profiles]}


@router.post("/synthesize")
async def synthesize(body: SynthesizeRequest):
    """
    Synthesize speech from text using the specified voice.

    Returns a completed (or failed) `SynthesisJob` with `output_path`
    pointing to the generated WAV file.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    if not (0.5 <= body.speed <= 2.0):
        raise HTTPException(status_code=400, detail="speed must be between 0.5 and 2.0")
    if not (0.8 <= body.pitch <= 1.2):
        raise HTTPException(status_code=400, detail="pitch must be between 0.8 and 1.2")

    style = _parse_style(body.style)
    provider = _parse_provider(body.provider)
    svc = get_voice_synthesis_service()

    try:
        job = await svc.synthesize_speech(
            voice_id=body.voice_id,
            text=body.text,
            style=style,
            speed=body.speed,
            pitch=body.pitch,
            emotion=body.emotion,
            provider=provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "job": _fmt_job(job)}


@router.post("/narration")
async def generate_narration(body: NarrationRequest):
    """
    Generate narration for an entire video script.

    Pass optional `segments` — list of `{text, start_time, end_time}` —
    for time-aligned narration. Without segments the script is auto-split
    into ~500-char chunks. Returns the list of synthesis jobs.
    """
    if not body.video_script.strip():
        raise HTTPException(status_code=400, detail="video_script must not be empty")

    style = _parse_style(body.style)
    svc = get_voice_synthesis_service()

    try:
        jobs = await svc.generate_narration(
            video_script=body.video_script,
            voice_id=body.voice_id,
            style=style,
            segments=body.segments,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "job_count": len(jobs),
        "jobs": [_fmt_job(j) for j in jobs],
    }


@router.post("/mix")
async def mix_narration(body: MixRequest):
    """
    Mix completed narration jobs with a source video.

    `ducking_level` (0-1) sets how much the original audio is attenuated
    under the narration (0 = silent background, 1 = full background level).
    Returns the path of the output mixed video.
    """
    if not body.job_ids:
        raise HTTPException(status_code=400, detail="job_ids must not be empty")
    if not (0.0 <= body.ducking_level <= 1.0):
        raise HTTPException(status_code=400, detail="ducking_level must be 0.0 – 1.0")

    svc = get_voice_synthesis_service()

    # Resolve job objects
    jobs = []
    for jid in body.job_ids:
        job = svc.get_job_status(jid)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job '{jid}' not found")
        jobs.append(job)

    try:
        output = await svc.mix_with_video(
            Path(body.video_path), jobs, Path(body.output_path), body.ducking_level
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "output_path": str(output)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Get the status and result of a synthesis job."""
    svc = get_voice_synthesis_service()
    job = svc.get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "success", "job": _fmt_job(job)}


@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Delete a cloned voice. Default voices cannot be deleted."""
    svc = get_voice_synthesis_service()
    try:
        deleted = await svc.delete_voice(voice_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Voice '{voice_id}' not found")
    return {"status": "deleted", "voice_id": voice_id}


@router.get("/stats")
def get_stats():
    """Voice synthesis service statistics."""
    svc = get_voice_synthesis_service()
    return {"status": "success", "stats": svc.get_stats()}


@router.get("/styles")
def list_styles():
    """List all voice style presets."""
    return {"styles": [s.value for s in VoiceStyle]}


@router.get("/providers")
def list_providers():
    """List all supported TTS providers."""
    return {"providers": [p.value for p in SynthesisProvider]}
