"""
Clip Feedback, Score Override & Export History API Routes — Phase 23

Score Overrides:
  PUT    /clips/{id}/score-override       → set manual score
  GET    /clips/{id}/score-override       → get override
  DELETE /clips/{id}/score-override       → remove override
  GET    /clips/{id}/effective-score      → resolve with computed score

Feedback:
  POST   /clips/{id}/feedback/thumbs      → submit thumbs_up/thumbs_down
  POST   /clips/{id}/feedback/rating      → submit 1-5 star rating
  GET    /clips/{id}/feedback             → aggregate stats
  GET    /clips/{id}/feedback/{user_id}   → per-user feedback

Export History:
  POST   /exports/{user_id}              → record an export
  GET    /exports/{user_id}              → list exports
  GET    /exports/{user_id}/stats        → export stats
  PATCH  /exports/{user_id}/{export_id}  → update status
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["clip-feedback-score"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

class ScoreOverrideRequest(BaseModel):
    score: float
    author: str = ""
    reason: str = ""
    original_score: Optional[float] = None


class EffectiveScoreRequest(BaseModel):
    computed_score: float = 0.0


class ThumbsRequest(BaseModel):
    user_id: str
    vote: str


class RatingRequest(BaseModel):
    user_id: str
    rating: int


class ExportRecordRequest(BaseModel):
    clip_ids: List[str]
    format: str = "zip"
    status: str = "pending"
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None


class ExportStatusUpdate(BaseModel):
    status: str
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None


# ── Score Overrides ───────────────────────────────────────────────────────────

@router.put("/clips/{clip_id}/score-override")
async def set_score_override(clip_id: str, body: ScoreOverrideRequest):
    from src.services.clip_score_override_service import set_score_override as svc
    try:
        result = await svc(clip_id, body.score, body.author,
                           body.reason, body.original_score)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/clips/{clip_id}/score-override")
async def get_score_override(clip_id: str):
    from src.services.clip_score_override_service import get_score_override as svc
    result = await svc(clip_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No score override found")
    return result


@router.delete("/clips/{clip_id}/score-override")
async def delete_score_override(clip_id: str):
    from src.services.clip_score_override_service import delete_score_override as svc
    deleted = await svc(clip_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No score override found")
    return {"deleted": True, "clip_id": clip_id}


@router.get("/clips/{clip_id}/effective-score")
async def effective_score(
    clip_id: str,
    computed_score: float = Query(0.0),
):
    from src.services.clip_score_override_service import resolve_score
    return await resolve_score(clip_id, computed_score)


# ── Feedback ──────────────────────────────────────────────────────────────────

@router.post("/clips/{clip_id}/feedback/thumbs")
async def submit_thumbs(clip_id: str, body: ThumbsRequest):
    from src.services.feedback_aggregation_service import submit_thumbs as svc
    try:
        return await svc(clip_id, body.user_id, body.vote)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/clips/{clip_id}/feedback/rating")
async def submit_rating(clip_id: str, body: RatingRequest):
    from src.services.feedback_aggregation_service import submit_rating as svc
    try:
        return await svc(clip_id, body.user_id, body.rating)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/clips/{clip_id}/feedback")
async def get_feedback(clip_id: str):
    from src.services.feedback_aggregation_service import get_feedback_stats
    return await get_feedback_stats(clip_id)


@router.get("/clips/{clip_id}/feedback/{user_id}")
async def get_user_feedback(clip_id: str, user_id: str):
    from src.services.feedback_aggregation_service import get_user_feedback as svc
    return await svc(clip_id, user_id)


# ── Export History ────────────────────────────────────────────────────────────

@router.post("/exports/{user_id}")
async def record_export(user_id: str, body: ExportRecordRequest):
    from src.services.clip_export_history_service import record_export as svc
    return await svc(user_id, body.clip_ids, body.format,
                     body.status, body.file_path, body.file_size_bytes)


@router.get("/exports/{user_id}")
async def get_export_history(
    user_id: str,
    limit: int = Query(20, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    from src.services.clip_export_history_service import get_export_history as svc
    records = await svc(user_id, limit=limit, status_filter=status)
    return {"user_id": user_id, "count": len(records), "exports": records}


@router.get("/exports/{user_id}/stats")
async def export_stats(user_id: str):
    from src.services.clip_export_history_service import get_export_stats
    return await get_export_stats(user_id)


@router.patch("/exports/{user_id}/{export_id}")
async def update_export_status(user_id: str, export_id: str, body: ExportStatusUpdate):
    from src.services.clip_export_history_service import update_export_status as svc
    updated = await svc(user_id, export_id, body.status,
                        body.file_path, body.file_size_bytes)
    if not updated:
        raise HTTPException(status_code=404, detail="Export record not found")
    return {"updated": True, "export_id": export_id, "status": body.status}
