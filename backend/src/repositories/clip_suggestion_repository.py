"""Repository for `clip_suggestions` rows.

Each row represents one editorial suggestion produced by the analyzers for a
clip (caption template, B-roll cue, hook reorder, polish toggle, ...). The
user approves or rejects each row individually before the final render.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


_VALID_STATUSES = {"pending", "approved", "rejected"}
_VALID_CATEGORIES = {"timing", "captions", "media", "polish"}


class ClipSuggestionRepository:
    """CRUD for editorial suggestions attached to a clip."""

    # ------------------------------------------------------------------ create
    @staticmethod
    async def create_suggestion(
        db: AsyncSession,
        *,
        clip_id: str,
        kind: str,
        category: str,
        payload: Optional[Dict[str, Any]] = None,
        label: Optional[str] = None,
        score: Optional[float] = None,
        sort_order: int = 0,
        status: str = "pending",
    ) -> str:
        if category not in _VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. Allowed: {_VALID_CATEGORIES}"
            )
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Allowed: {_VALID_STATUSES}"
            )

        result = await db.execute(
            sa_text(
                """
                INSERT INTO clip_suggestions
                    (clip_id, kind, category, payload, status,
                     label, score, sort_order, created_at, updated_at)
                VALUES
                    (:clip_id, :kind, :category, CAST(:payload AS JSONB), :status,
                     :label, :score, :sort_order, NOW(), NOW())
                RETURNING id
                """
            ),
            {
                "clip_id": clip_id,
                "kind": kind,
                "category": category,
                "payload": json.dumps(payload or {}),
                "status": status,
                "label": label,
                "score": score,
                "sort_order": sort_order,
            },
        )
        row_id = result.scalar()
        if not row_id:
            raise RuntimeError("Failed to create clip_suggestion: no ID returned")
        return str(row_id)

    @staticmethod
    async def bulk_create(
        db: AsyncSession,
        clip_id: str,
        suggestions: List[Dict[str, Any]],
    ) -> List[str]:
        ids: List[str] = []
        for sug in suggestions:
            ids.append(
                await ClipSuggestionRepository.create_suggestion(
                    db,
                    clip_id=clip_id,
                    kind=sug["kind"],
                    category=sug["category"],
                    payload=sug.get("payload"),
                    label=sug.get("label"),
                    score=sug.get("score"),
                    sort_order=int(sug.get("sort_order", 0)),
                    status=sug.get("status", "pending"),
                )
            )
        return ids

    # -------------------------------------------------------------------- read
    @staticmethod
    async def list_by_clip(
        db: AsyncSession, clip_id: str
    ) -> List[Dict[str, Any]]:
        result = await db.execute(
            sa_text(
                """
                SELECT id, clip_id, kind, category, payload, status,
                       label, score, sort_order, created_at, updated_at
                FROM clip_suggestions
                WHERE clip_id = :clip_id
                ORDER BY category, sort_order, created_at
                """
            ),
            {"clip_id": clip_id},
        )
        rows = result.mappings().all()
        return [
            {
                "id": str(r["id"]),
                "clip_id": str(r["clip_id"]),
                "kind": r["kind"],
                "category": r["category"],
                "payload": r["payload"] or {},
                "status": r["status"],
                "label": r["label"],
                "score": r["score"],
                "sort_order": r["sort_order"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]

    @staticmethod
    async def get_by_id(
        db: AsyncSession, suggestion_id: str
    ) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            sa_text(
                """
                SELECT id, clip_id, kind, category, payload, status,
                       label, score, sort_order, created_at, updated_at
                FROM clip_suggestions
                WHERE id = :id
                """
            ),
            {"id": suggestion_id},
        )
        row = result.mappings().first()
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "clip_id": str(row["clip_id"]),
            "kind": row["kind"],
            "category": row["category"],
            "payload": row["payload"] or {},
            "status": row["status"],
            "label": row["label"],
            "score": row["score"],
            "sort_order": row["sort_order"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    @staticmethod
    async def list_approved(
        db: AsyncSession, clip_id: str
    ) -> List[Dict[str, Any]]:
        rows = await ClipSuggestionRepository.list_by_clip(db, clip_id)
        return [r for r in rows if r["status"] == "approved"]

    # ------------------------------------------------------------------ update
    @staticmethod
    async def update_status(
        db: AsyncSession,
        suggestion_id: str,
        status: str,
        payload_override: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Allowed: {_VALID_STATUSES}"
            )

        if payload_override is not None:
            result = await db.execute(
                sa_text(
                    """
                    UPDATE clip_suggestions
                    SET status = :status,
                        payload = CAST(:payload AS JSONB),
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "id": suggestion_id,
                    "status": status,
                    "payload": json.dumps(payload_override),
                },
            )
        else:
            result = await db.execute(
                sa_text(
                    """
                    UPDATE clip_suggestions
                    SET status = :status, updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"id": suggestion_id, "status": status},
            )
        return (result.rowcount or 0) > 0

    @staticmethod
    async def update_payload(
        db: AsyncSession,
        suggestion_id: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Update the payload JSONB of a suggestion (for granular item editing)."""
        result = await db.execute(
            sa_text(
                """
                UPDATE clip_suggestions
                SET payload = CAST(:payload AS JSONB),
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {
                "id": suggestion_id,
                "payload": json.dumps(payload),
            },
        )
        return (result.rowcount or 0) > 0

    @staticmethod
    async def reset_clip(db: AsyncSession, clip_id: str) -> int:
        """Mark every suggestion of the clip as 'pending'. Returns row count."""
        result = await db.execute(
            sa_text(
                """
                UPDATE clip_suggestions
                SET status = 'pending', updated_at = NOW()
                WHERE clip_id = :clip_id
                """
            ),
            {"clip_id": clip_id},
        )
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------ delete
    @staticmethod
    async def delete_by_clip(db: AsyncSession, clip_id: str) -> int:
        result = await db.execute(
            sa_text(
                "DELETE FROM clip_suggestions WHERE clip_id = :clip_id"
            ),
            {"clip_id": clip_id},
        )
        return int(result.rowcount or 0)
