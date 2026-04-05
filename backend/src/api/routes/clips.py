"""
Clip management routes — including user rating endpoint (B.6).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ...database import get_db
from ...repositories.clip_repository import ClipRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clips", tags=["clips"])


class RatingRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="User rating from 1 to 5")
    task_id: Optional[str] = Field(None, description="Parent task ID for dataset collection")


class ThumbsRequest(BaseModel):
    rating: str = Field(..., pattern="^(thumbs_up|thumbs_down|neutral)$")
    task_id: Optional[str] = Field(None, description="Parent task ID for dataset collection")
    feedback_text: Optional[str] = Field(None, max_length=500)


@router.post("/{clip_id}/rating", summary="Rate a generated clip (1–5 stars)")
async def rate_clip(
    clip_id: str,
    body: RatingRequest,
    db: AsyncSession = Depends(get_db),
):
    updated = await ClipRepository.update_clip_rating(db, clip_id, body.rating)
    if not updated:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Feed into dataset collector for LLM training (non-blocking)
    if body.task_id:
        try:
            from ...services.dataset_collector import get_dataset_collector
            from ...config import get_config
            collector = get_dataset_collector(get_config().dataset_dir)
            thumbs = "thumbs_up" if body.rating >= 4 else ("thumbs_down" if body.rating <= 2 else "neutral")
            await collector.add_user_feedback(
                task_id=body.task_id,
                clip_id=clip_id,
                rating=thumbs,
            )
        except Exception as e:
            logger.warning(f"Dataset collection failed (non-fatal): {e}")

    return {"clip_id": clip_id, "rating": body.rating}


@router.post("/{clip_id}/thumbs", summary="Thumbs up/down on a clip (feeds LLM training dataset)")
async def thumbs_clip(
    clip_id: str,
    body: ThumbsRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Quick thumbs rating — also records feedback in the LLM training dataset.
    Used to progressively improve local model quality via DSPy / fine-tuning.
    """
    # Map to numeric for DB storage
    numeric = {"thumbs_up": 5, "neutral": 3, "thumbs_down": 1}[body.rating]
    updated = await ClipRepository.update_clip_rating(db, clip_id, numeric)
    if not updated:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Feed into dataset collector
    if body.task_id:
        try:
            from ...services.dataset_collector import get_dataset_collector
            from ...config import get_config
            collector = get_dataset_collector(get_config().dataset_dir)
            await collector.add_user_feedback(
                task_id=body.task_id,
                clip_id=clip_id,
                rating=body.rating,
                feedback_text=body.feedback_text,
            )
            stats = await collector.get_stats()
            logger.info(
                f"Dataset: {stats['total_examples']} examples "
                f"(DSPy ready: {stats['ready_for_dspy']}, "
                f"FT ready: {stats['ready_for_finetuning']})"
            )
        except Exception as e:
            logger.warning(f"Dataset collection failed (non-fatal): {e}")

    return {"clip_id": clip_id, "rating": body.rating, "recorded_for_training": bool(body.task_id)}


@router.get("/{clip_id}", summary="Get a single clip by ID")
async def get_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    clip = await ClipRepository.get_clip_by_id(db, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip
