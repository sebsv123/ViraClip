"""Suggestion Learner — learns from user approve/reject decisions."""

from __future__ import annotations
import logging
from typing import Dict, List
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def record_decision(db: AsyncSession, *, user_id: str, kind: str, category: str, approved: bool) -> None:
    try:
        await db.execute(
            sa_text("INSERT INTO suggestion_feedback (user_id, kind, category, approved, created_at) VALUES (:uid, :kind, :cat, :app, NOW())"),
            {"uid": user_id, "kind": kind, "cat": category, "app": approved},
        )
        await db.commit()
    except Exception as e:
        logger.debug("[learner] record failed: %s", e)


async def get_user_preferences(db: AsyncSession, user_id: str) -> Dict[str, float]:
    try:
        result = await db.execute(
            sa_text("SELECT kind, COUNT(*) FILTER (WHERE approved)::float/NULLIF(COUNT(*),0) AS rate FROM suggestion_feedback WHERE user_id=:uid GROUP BY kind"),
            {"uid": user_id},
        )
        return {r["kind"]: float(r["rate"]) for r in result.mappings().all()}
    except Exception as e:
        logger.debug("[learner] prefs failed: %s", e)
        return {}


async def adjust_scores(suggestions: List[Dict], prefs: Dict[str, float]) -> List[Dict]:
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        kind = s.get("kind", "")
        if kind in prefs:
            rate = prefs[kind]
            base = s.get("score") or 0.5
            s["score"] = round(base * 0.6 + rate * 0.4, 2)
            s["label"] = (s.get("label") or kind) + (" ★" if rate > 0.7 else "")
    return suggestions
