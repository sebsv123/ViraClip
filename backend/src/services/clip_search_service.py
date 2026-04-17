"""
Clip Search Service — Phase 16

Full-text + score-based search across all clips.
Runs against the database via raw SQL — no external search engine required.
"""

import logging
from typing import List, Dict, Any, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def search_clips(
    db: AsyncSession,
    *,
    user_id: str,
    query: Optional[str] = None,
    niche: Optional[str] = None,
    hook_type: Optional[str] = None,
    min_virality: Optional[int] = None,
    max_virality: Optional[int] = None,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
    min_rating: Optional[int] = None,
    platform: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Search clips across all tasks owned by user_id.

    Supports:
    - Full-text search on transcript text, social title, reasoning
    - Score range filtering (virality_score, duration, user_rating)
    - Hook type filtering
    - Niche/platform tags (stored in clip.hook_type as a best-effort proxy)
    - Pagination via limit/offset

    Returns:
        {"clips": [...], "total": int, "limit": int, "offset": int}
    """
    conditions = ["t.user_id = :user_id"]
    params: Dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}

    if query:
        conditions.append(
            "(c.text ILIKE :q OR c.social_title ILIKE :q OR c.reasoning ILIKE :q)"
        )
        params["q"] = f"%{query}%"

    if hook_type:
        conditions.append("c.hook_type = :hook_type")
        params["hook_type"] = hook_type

    if min_virality is not None:
        conditions.append("COALESCE(c.virality_score, 0) >= :min_virality")
        params["min_virality"] = min_virality

    if max_virality is not None:
        conditions.append("COALESCE(c.virality_score, 0) <= :max_virality")
        params["max_virality"] = max_virality

    if min_duration is not None:
        conditions.append("c.duration >= :min_duration")
        params["min_duration"] = min_duration

    if max_duration is not None:
        conditions.append("c.duration <= :max_duration")
        params["max_duration"] = max_duration

    if min_rating is not None:
        conditions.append("c.user_rating >= :min_rating")
        params["min_rating"] = min_rating

    where = " AND ".join(conditions)

    count_sql = sa_text(f"""
        SELECT COUNT(*) FROM generated_clips c
        JOIN tasks t ON c.task_id = t.id
        WHERE {where}
    """)

    data_sql = sa_text(f"""
        SELECT
            c.id, c.task_id, c.filename, c.file_path,
            c.start_time, c.end_time, c.duration,
            c.text, c.relevance_score, c.reasoning, c.clip_order,
            c.virality_score, c.hook_score, c.engagement_score,
            c.value_score, c.shareability_score, c.hook_type,
            c.social_title, c.social_description, c.suggested_hashtags,
            c.thumbnail_filename, c.face_detected, c.hook_preview_score,
            c.user_rating, c.created_at,
            t.source_title AS task_title
        FROM generated_clips c
        JOIN tasks t ON c.task_id = t.id
        WHERE {where}
        ORDER BY COALESCE(c.virality_score, 0) DESC, c.created_at DESC
        LIMIT :limit OFFSET :offset
    """)

    try:
        total_row = await db.execute(count_sql, params)
        total = total_row.scalar() or 0

        result = await db.execute(data_sql, params)
        rows = result.fetchall()
    except Exception as exc:
        logger.warning("[clip_search] Query failed: %s", exc)
        return {"clips": [], "total": 0, "limit": limit, "offset": offset}

    clips = []
    for row in rows:
        d = row._asdict() if hasattr(row, "_asdict") else dict(row)
        thumb = d.get("thumbnail_filename")
        clips.append({
            "id": d["id"],
            "task_id": d["task_id"],
            "task_title": d.get("task_title", ""),
            "filename": d["filename"],
            "file_path": d["file_path"],
            "start_time": d["start_time"],
            "end_time": d["end_time"],
            "duration": d["duration"],
            "text": d.get("text") or "",
            "relevance_score": d.get("relevance_score") or 0,
            "reasoning": d.get("reasoning") or "",
            "clip_order": d.get("clip_order") or 0,
            "virality_score": d.get("virality_score") or 0,
            "hook_score": d.get("hook_score") or 0,
            "engagement_score": d.get("engagement_score") or 0,
            "value_score": d.get("value_score") or 0,
            "shareability_score": d.get("shareability_score") or 0,
            "hook_type": d.get("hook_type"),
            "social_title": d.get("social_title"),
            "social_description": d.get("social_description"),
            "suggested_hashtags": d.get("suggested_hashtags") or [],
            "thumbnail_url": f"/clips/{d['task_id']}/{thumb}" if thumb else None,
            "face_detected": d.get("face_detected"),
            "hook_preview_score": d.get("hook_preview_score") or 0,
            "user_rating": d.get("user_rating"),
            "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
            "video_url": f"/clips/{d['task_id']}/{d['filename']}",
        })

    return {"clips": clips, "total": total, "limit": limit, "offset": offset}


async def get_search_facets(
    db: AsyncSession,
    user_id: str,
) -> Dict[str, Any]:
    """
    Return facet counts for hook_type to power filter UI.
    """
    sql = sa_text("""
        SELECT c.hook_type, COUNT(*) AS cnt
        FROM generated_clips c
        JOIN tasks t ON c.task_id = t.id
        WHERE t.user_id = :user_id AND c.hook_type IS NOT NULL
        GROUP BY c.hook_type
        ORDER BY cnt DESC
    """)
    try:
        result = await db.execute(sql, {"user_id": user_id})
        rows = result.fetchall()
        return {"hook_types": [{"type": r.hook_type, "count": r.cnt} for r in rows]}
    except Exception as exc:
        logger.warning("[clip_search] Facets query failed: %s", exc)
        return {"hook_types": []}
