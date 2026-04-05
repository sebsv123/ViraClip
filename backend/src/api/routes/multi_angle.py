"""
Multi-Angle API — ViraClip

Endpoints for synchronizing dual-camera footage, computing aligned
timestamps across angles, and generating camera-switching plans.
"""

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.multi_angle_service import MultiAngleService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/multi-angle", tags=["multi-angle"])

# Singleton
_service: MultiAngleService | None = None


def _get_service() -> MultiAngleService:
    global _service
    if _service is None:
        _service = MultiAngleService()
    return _service


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SyncRequest(BaseModel):
    primary_path: str
    secondary_path: str


class AlignTimestampsRequest(BaseModel):
    primary_start: float
    primary_end: float
    offset: float           # seconds; positive = secondary starts AFTER primary


class SwitchingPlanRequest(BaseModel):
    duration: float         # total video duration in seconds
    interval: float = 3.3   # seconds between angle switches


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/sync")
async def synchronize_sources(body: SyncRequest):
    """
    Calculate the temporal offset between a primary and secondary camera angle.
    Uses cross-correlation of the audio tracks to find the sync point.

    Returns `offset_seconds` — add this to secondary timestamps to align with primary.
    """
    from pathlib import Path

    primary = Path(body.primary_path)
    secondary = Path(body.secondary_path)

    svc = _get_service()
    try:
        result = await svc.synchronize_sources(primary, secondary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("sync_ready"):
        raise HTTPException(
            status_code=422,
            detail=result.get("error", "Sync failed — check that both files have audio tracks"),
        )
    return {"status": "synced", **result}


@router.post("/align-timestamps")
def align_timestamps(body: AlignTimestampsRequest):
    """
    Map a primary-video time range to the equivalent range in the secondary angle,
    given the offset calculated by `/multi-angle/sync`.
    """
    svc = _get_service()
    sec_start, sec_end = svc.get_aligned_timestamps(
        body.primary_start, body.primary_end, body.offset
    )
    return {
        "primary_start": body.primary_start,
        "primary_end": body.primary_end,
        "offset": body.offset,
        "secondary_start": round(sec_start, 3),
        "secondary_end": round(sec_end, 3),
    }


@router.post("/switching-plan")
def generate_switching_plan(body: SwitchingPlanRequest):
    """
    Generate a rhythmic camera-switching schedule for a multi-angle edit.

    Returns a list of segments, each with `start`, `end`, and `angle` (0=primary, 1=secondary).
    `interval` controls the cut frequency (default: every 3.3 s).
    """
    if body.duration <= 0:
        raise HTTPException(status_code=400, detail="duration must be > 0")
    if body.interval <= 0:
        raise HTTPException(status_code=400, detail="interval must be > 0")

    svc = _get_service()
    plan = svc.generate_camera_switching_plan(body.duration, body.interval)

    return {
        "status": "success",
        "total_duration": body.duration,
        "interval": body.interval,
        "total_segments": len(plan),
        "plan": plan,
    }
