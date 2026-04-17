"""
Watermark, Transcript Search & Share Link API Routes — Phase 25

Watermark:
  GET    /watermark/{user_id}          → get config
  PUT    /watermark/{user_id}          → update config
  DELETE /watermark/{user_id}          → reset config
  POST   /watermark/{user_id}/apply    → apply to clip (input/output paths)

Transcript Search:
  POST   /transcripts/{user_id}/{clip_id}  → index a transcript
  GET    /transcripts/{user_id}/{clip_id}  → get stored transcript
  DELETE /transcripts/{user_id}/{clip_id}  → delete from index
  GET    /transcripts/{user_id}/search     → search with query param
  GET    /transcripts/{user_id}/clips      → list indexed clip ids

Share Links:
  POST   /share/{clip_id}              → create share link
  GET    /share/{clip_id}              → list active links
  GET    /share/resolve/{token}        → resolve + increment views
  DELETE /share/{clip_id}/{token}      → revoke link
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["watermark-search-share"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

class WatermarkConfigUpdate(BaseModel):
    text: Optional[str] = None
    position: Optional[str] = None
    opacity: Optional[float] = None
    font_size: Optional[int] = None
    color: Optional[str] = None
    enabled: Optional[bool] = None


class WatermarkApplyRequest(BaseModel):
    input_path: str
    output_path: str


class TranscriptIndexRequest(BaseModel):
    transcript: str


class ShareLinkCreate(BaseModel):
    user_id: str
    ttl_seconds: int = 604800  # 7 days


# ── Watermark ──────────────────────────────────────────────────────────────────

@router.get("/watermark/{user_id}")
async def get_watermark_config(user_id: str):
    from src.services.clip_watermark_service import get_watermark_config
    return await get_watermark_config(user_id)


@router.put("/watermark/{user_id}")
async def update_watermark_config(user_id: str, body: WatermarkConfigUpdate):
    from src.services.clip_watermark_service import set_watermark_config
    try:
        return await set_watermark_config(
            user_id,
            text=body.text,
            position=body.position,
            opacity=body.opacity,
            font_size=body.font_size,
            color=body.color,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/watermark/{user_id}")
async def reset_watermark_config(user_id: str):
    from src.services.clip_watermark_service import delete_watermark_config
    await delete_watermark_config(user_id)
    return {"reset": True, "user_id": user_id}


@router.post("/watermark/{user_id}/apply")
async def apply_watermark(user_id: str, body: WatermarkApplyRequest):
    from src.services.clip_watermark_service import apply_watermark as svc
    success = await svc(user_id, body.input_path, body.output_path)
    return {"success": success, "output_path": body.output_path}


# ── Transcript Search ─────────────────────────────────────────────────────────

@router.get("/transcripts/{user_id}/search")
async def search_transcripts(
    user_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    case_sensitive: bool = Query(False),
):
    from src.services.transcript_search_service import search_transcripts as svc
    results = await svc(user_id, q, limit=limit, case_sensitive=case_sensitive)
    return {"user_id": user_id, "query": q, "count": len(results), "results": results}


@router.get("/transcripts/{user_id}/clips")
async def list_indexed_clips(user_id: str):
    from src.services.transcript_search_service import list_indexed_clips as svc
    clips = await svc(user_id)
    return {"user_id": user_id, "count": len(clips), "clip_ids": clips}


@router.post("/transcripts/{user_id}/{clip_id}")
async def index_transcript(user_id: str, clip_id: str, body: TranscriptIndexRequest):
    from src.services.transcript_search_service import index_transcript as svc
    await svc(user_id, clip_id, body.transcript)
    return {"indexed": True, "clip_id": clip_id}


@router.get("/transcripts/{user_id}/{clip_id}")
async def get_transcript(user_id: str, clip_id: str):
    from src.services.transcript_search_service import get_transcript as svc
    text = await svc(user_id, clip_id)
    if text is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return {"clip_id": clip_id, "transcript": text}


@router.delete("/transcripts/{user_id}/{clip_id}")
async def delete_transcript(user_id: str, clip_id: str):
    from src.services.transcript_search_service import delete_transcript as svc
    deleted = await svc(user_id, clip_id)
    return {"deleted": deleted, "clip_id": clip_id}


# ── Share Links ───────────────────────────────────────────────────────────────

@router.post("/share/{clip_id}")
async def create_share_link(clip_id: str, body: ShareLinkCreate):
    from src.services.clip_share_link_service import create_share_link as svc
    try:
        return await svc(clip_id, body.user_id, body.ttl_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/share/{clip_id}")
async def list_share_links(clip_id: str):
    from src.services.clip_share_link_service import list_share_links as svc
    links = await svc(clip_id)
    return {"clip_id": clip_id, "count": len(links), "links": links}


@router.get("/share/resolve/{token}")
async def resolve_share_link(token: str):
    from src.services.clip_share_link_service import resolve_share_link as svc
    result = await svc(token)
    if result is None:
        raise HTTPException(status_code=404, detail="Share link not found or expired")
    return result


@router.delete("/share/{clip_id}/{token}")
async def revoke_share_link(clip_id: str, token: str):
    from src.services.clip_share_link_service import revoke_share_link as svc
    revoked = await svc(clip_id, token)
    if not revoked:
        raise HTTPException(status_code=404, detail="Share link not found")
    return {"revoked": True, "token": token}
