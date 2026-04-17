"""
Clip Chapters, Caption Variants & User Activity Log API Routes — Phase 24

Chapters:
  POST   /clips/{id}/chapters               → add a chapter
  GET    /clips/{id}/chapters               → list all chapters
  DELETE /clips/{id}/chapters/{chapter_id}  → remove a chapter
  DELETE /clips/{id}/chapters               → clear all chapters
  GET    /clips/{id}/chapters/at/{ts}       → chapter at timestamp

Caption Variants:
  GET    /clips/{id}/caption-variants       → get or generate variants
  DELETE /clips/{id}/caption-variants       → evict cache

Activity Log:
  POST   /activity/{user_id}               → log an action
  GET    /activity/{user_id}               → list recent actions
  GET    /activity/{user_id}/stats         → action frequency stats
  DELETE /activity/{user_id}              → clear log
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["chapters-captions-activity"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

class ChapterCreate(BaseModel):
    title: str
    start_time: float
    end_time: Optional[float] = None
    description: str = ""


class CaptionVariantsRequest(BaseModel):
    title: str
    keywords: Optional[List[str]] = None
    force: bool = False


class ActivityLogRequest(BaseModel):
    action: str
    resource_type: str = ""
    resource_id: str = ""
    metadata: Optional[Dict] = None


# ── Chapters ──────────────────────────────────────────────────────────────────

@router.post("/clips/{clip_id}/chapters")
async def add_chapter(clip_id: str, body: ChapterCreate):
    from src.services.clip_chapter_service import add_chapter as svc
    try:
        return await svc(clip_id, body.title, body.start_time,
                         body.end_time, body.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/clips/{clip_id}/chapters")
async def get_chapters(clip_id: str):
    from src.services.clip_chapter_service import get_chapters as svc
    chapters = await svc(clip_id)
    return {"clip_id": clip_id, "count": len(chapters), "chapters": chapters}


@router.delete("/clips/{clip_id}/chapters/{chapter_id}")
async def remove_chapter(clip_id: str, chapter_id: str):
    from src.services.clip_chapter_service import remove_chapter as svc
    removed = await svc(clip_id, chapter_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {"removed": True, "chapter_id": chapter_id}


@router.delete("/clips/{clip_id}/chapters")
async def clear_chapters(clip_id: str):
    from src.services.clip_chapter_service import clear_chapters as svc
    count = await svc(clip_id)
    return {"cleared": count, "clip_id": clip_id}


@router.get("/clips/{clip_id}/chapters/at/{ts}")
async def chapter_at_time(clip_id: str, ts: float):
    from src.services.clip_chapter_service import get_chapter_at_time
    chapter = await get_chapter_at_time(clip_id, ts)
    if chapter is None:
        raise HTTPException(status_code=404, detail="No chapter at that timestamp")
    return chapter


# ── Caption Variants ──────────────────────────────────────────────────────────

@router.get("/clips/{clip_id}/caption-variants")
async def get_caption_variants(
    clip_id: str,
    title: str = Query(...),
    force: bool = Query(False),
):
    from src.services.caption_variant_service import get_or_generate_variants
    return await get_or_generate_variants(clip_id, title, force=force)


@router.delete("/clips/{clip_id}/caption-variants")
async def clear_caption_variants(clip_id: str):
    from src.services.caption_variant_service import clear_variants
    await clear_variants(clip_id)
    return {"cleared": True, "clip_id": clip_id}


# ── Activity Log ──────────────────────────────────────────────────────────────

@router.post("/activity/{user_id}")
async def log_action(user_id: str, body: ActivityLogRequest):
    from src.services.user_activity_log_service import log_action as svc
    return await svc(user_id, body.action, body.resource_type,
                     body.resource_id, body.metadata)


@router.get("/activity/{user_id}")
async def get_activity_log(
    user_id: str,
    limit: int = Query(50, ge=1, le=1000),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
):
    from src.services.user_activity_log_service import get_activity_log as svc
    records = await svc(user_id, limit=limit,
                        action_filter=action,
                        resource_type_filter=resource_type)
    return {"user_id": user_id, "count": len(records), "records": records}


@router.get("/activity/{user_id}/stats")
async def activity_stats(user_id: str):
    from src.services.user_activity_log_service import get_activity_stats
    return await get_activity_stats(user_id)


@router.delete("/activity/{user_id}")
async def clear_activity_log(user_id: str):
    from src.services.user_activity_log_service import clear_activity_log as svc
    await svc(user_id)
    return {"cleared": True, "user_id": user_id}
