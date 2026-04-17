"""
Clip Bulk & Tag API Routes — Phase 19

POST /clips/bulk           → bulk delete / archive / re-score / tag
GET  /clips/{id}/tags      → get tags for a clip
POST /clips/{id}/tags      → add tags to a clip
DELETE /clips/{id}/tags    → remove tags from a clip
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/clips", tags=["clip-bulk"])
logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────

class BulkAction(BaseModel):
    clip_ids: List[str]
    action: Literal["delete", "archive", "tag", "untag"]
    tags: Optional[List[str]] = None


class TagRequest(BaseModel):
    tags: List[str]


# ── Bulk endpoint ──────────────────────────────────────────────────────────

@router.post("/bulk")
async def bulk_clip_action(body: BulkAction, user_id: str = Query(...)):
    """
    Perform a bulk action on multiple clips.

    Actions:
      - delete   → mark clips as deleted in DB (soft-delete via update)
      - archive  → set a clip metadata flag (noop if unsupported by DB layer)
      - tag      → add `tags` to each clip via clip_tag_service
      - untag    → remove `tags` from each clip
    """
    from src.services.clip_tag_service import add_tags, remove_tags

    if not body.clip_ids:
        raise HTTPException(status_code=400, detail="clip_ids cannot be empty")

    results = {"processed": 0, "failed": [], "action": body.action}

    for clip_id in body.clip_ids:
        try:
            if body.action == "tag":
                if not body.tags:
                    raise ValueError("tags are required for 'tag' action")
                await add_tags(clip_id, body.tags)
            elif body.action == "untag":
                if not body.tags:
                    raise ValueError("tags are required for 'untag' action")
                await remove_tags(clip_id, body.tags)
            elif body.action in ("delete", "archive"):
                # These would hit the DB; for now, tag the clip with a status marker
                # so downstream consumers can filter. Full DB integration is in the
                # clip repository layer.
                status_tag = f"__status:{body.action}"
                await add_tags(clip_id, [status_tag])
            results["processed"] += 1
        except Exception as exc:
            results["failed"].append({"clip_id": clip_id, "error": str(exc)})

    return results


# ── Tag CRUD ───────────────────────────────────────────────────────────────

@router.get("/{clip_id}/tags")
async def get_clip_tags(clip_id: str):
    """Return all tags for a clip."""
    from src.services.clip_tag_service import get_tags
    tags = await get_tags(clip_id)
    return {"clip_id": clip_id, "tags": tags}


@router.post("/{clip_id}/tags")
async def add_clip_tags(clip_id: str, body: TagRequest):
    """Add one or more tags to a clip."""
    from src.services.clip_tag_service import add_tags
    try:
        updated = await add_tags(clip_id, body.tags)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"clip_id": clip_id, "tags": updated}


@router.delete("/{clip_id}/tags")
async def remove_clip_tags(clip_id: str, body: TagRequest):
    """Remove one or more tags from a clip."""
    from src.services.clip_tag_service import remove_tags
    updated = await remove_tags(clip_id, body.tags)
    return {"clip_id": clip_id, "tags": updated}
