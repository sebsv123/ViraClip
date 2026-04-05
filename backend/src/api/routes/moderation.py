"""
Content Moderation API — ViraClip

Endpoints for AI-powered safety checks on text, video metadata,
transcripts, and full clip validation before publishing.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.content_moderation import (
    ContentModerationService,
    get_moderation_service,
    get_safety_filter,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/moderation", tags=["moderation"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ModerateTextRequest(BaseModel):
    text: str
    content_id: str
    user_id: Optional[str] = None


class ModerateMetadataRequest(BaseModel):
    video_id: str
    title: str = ""
    description: str = ""
    tags: List[str] = []


class ModerateTranscriptRequest(BaseModel):
    transcript: str
    task_id: str


class ValidateClipRequest(BaseModel):
    clip_id: str
    title: str = ""
    description: str = ""
    tags: List[str] = []
    transcript: str = ""


class BatchModerateRequest(BaseModel):
    items: List[Dict[str, Any]]   # each: {id, text, user_id?}


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/text")
async def moderate_text(body: ModerateTextRequest):
    """
    Moderate a piece of text against hate speech, harassment, violence,
    sexual content, spam, self-harm, and other policy violations.

    Returns: `is_safe`, `category`, `confidence`, `flagged_keywords`,
    `suggested_action` (`allow | warn | flag_for_review | block`), and
    `review_required`.
    """
    svc = get_moderation_service()
    result = await svc.moderate_text(body.text, body.content_id, body.user_id)
    return {
        "status": "success",
        "content_id": result.content_id,
        "is_safe": result.is_safe,
        "category": result.category.value,
        "confidence": round(result.confidence, 3),
        "flagged_keywords": result.flagged_keywords,
        "reason": result.reason,
        "suggested_action": result.suggested_action,
        "review_required": result.review_required,
    }


@router.post("/metadata")
async def moderate_metadata(body: ModerateMetadataRequest):
    """
    Moderate all video metadata fields (title, description, tags) in one call.
    Returns aggregate safety result with per-field violation breakdown.
    """
    svc = get_moderation_service()
    result = await svc.moderate_video_metadata(
        title=body.title,
        description=body.description,
        tags=body.tags,
        video_id=body.video_id,
    )
    return {"status": "success", "video_id": body.video_id, **result}


@router.post("/transcript")
async def moderate_transcript(body: ModerateTranscriptRequest):
    """
    Moderate a full video transcript by splitting it into segments and
    checking each one. Returns only the segments with violations.
    """
    svc = get_moderation_service()
    violations = await svc.moderate_transcript(body.transcript, body.task_id)
    return {
        "status": "success",
        "task_id": body.task_id,
        "is_clean": len(violations) == 0,
        "violation_count": len(violations),
        "violations": violations,
    }


@router.post("/clip/validate")
async def validate_clip(body: ValidateClipRequest):
    """
    Full pre-publish validation: checks transcript + metadata.
    Returns `allowed` (bool) and a reason string if blocked.
    """
    safety = get_safety_filter()
    clip_info = {
        "clip_id": body.clip_id,
        "title": body.title,
        "description": body.description,
        "tags": body.tags,
    }
    is_allowed, reason = await safety.filter_clip_content(clip_info, body.transcript)
    return {
        "status": "success",
        "clip_id": body.clip_id,
        "allowed": is_allowed,
        "reason": reason,
    }


@router.get("/score/{content_id}")
def get_safety_score(content_id: str):
    """
    Get the aggregate safety score (0–100) for a content item.
    100 = fully safe; lower = more violations detected historically.
    """
    svc = get_moderation_service()
    score = svc.get_safety_score(content_id)
    return {"status": "success", "content_id": content_id, "safety_score": round(score, 1)}


@router.post("/batch")
async def batch_moderate(body: BatchModerateRequest):
    """
    Moderate multiple text items in one request.
    Each item must have `id` and `text` keys; `user_id` is optional.
    """
    if not body.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    svc = get_moderation_service()
    results = await svc.batch_moderate(body.items)
    return {
        "status": "success",
        "count": len(results),
        "results": [
            {
                "content_id": r.content_id,
                "is_safe": r.is_safe,
                "category": r.category.value,
                "confidence": round(r.confidence, 3),
                "suggested_action": r.suggested_action,
            }
            for r in results
        ],
    }


@router.get("/categories")
def list_categories():
    """List all content violation categories recognised by the moderation engine."""
    from ...services.content_moderation import ContentCategory
    return {"categories": [c.value for c in ContentCategory]}
