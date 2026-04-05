"""
Clip repository - handles all database operations for generated clips.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sa_text
from typing import List, Dict, Any, Optional
import json
import logging

logger = logging.getLogger(__name__)


class ClipRepository:
    """Repository for clip-related database operations."""

    @staticmethod
    async def create_clip(
        db: AsyncSession,
        task_id: str,
        filename: str,
        file_path: str,
        start_time: str,
        end_time: str,
        duration: float,
        text: str,
        relevance_score: float,
        reasoning: str,
        clip_order: int,
        virality_score: int = 0,
        hook_score: int = 0,
        engagement_score: int = 0,
        value_score: int = 0,
        shareability_score: int = 0,
        hook_type: Optional[str] = None,
        translated_text: Optional[str] = None,
        multi_angle_metadata: Optional[Dict[str, Any]] = None,
        # P3: social copy fields
        social_title: Optional[str] = None,
        social_description: Optional[str] = None,
        suggested_hashtags: Optional[List[str]] = None,
        # P4: thumbnail
        thumbnail_filename: Optional[str] = None,
        # B-3: face detection flag
        face_detected: Optional[bool] = None,
        # P2.4: hook preview score
        hook_preview_score: int = 0,
    ) -> str:
        """Create a new clip record and return its ID."""
        try:
            result = await db.execute(
                sa_text("""
                    INSERT INTO generated_clips
                    (task_id, filename, file_path, start_time, end_time, duration,
                     text, relevance_score, reasoning, clip_order,
                     virality_score, hook_score, engagement_score, value_score, shareability_score, hook_type,
                     translated_text,
                     multi_angle_metadata,
                     social_title, social_description, suggested_hashtags,
                     thumbnail_filename, face_detected,
                     hook_preview_score,
                     created_at)
                    VALUES
                    (:task_id, :filename, :file_path, :start_time, :end_time, :duration,
                     :text, :relevance_score, :reasoning, :clip_order,
                     :virality_score, :hook_score, :engagement_score, :value_score, :shareability_score, :hook_type,
                     :translated_text,
                     :multi_angle_metadata,
                     :social_title, :social_description, :suggested_hashtags,
                     :thumbnail_filename, :face_detected,
                     :hook_preview_score,
                     NOW())
                    RETURNING id
                """),
                {
                    "task_id": task_id,
                    "filename": filename,
                    "file_path": file_path,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "text": text,
                    "relevance_score": relevance_score,
                    "reasoning": reasoning,
                    "clip_order": clip_order,
                    "virality_score": virality_score,
                    "hook_score": hook_score,
                    "engagement_score": engagement_score,
                    "value_score": value_score,
                    "shareability_score": shareability_score,
                    "hook_type": hook_type,
                    "translated_text": translated_text,
                    "multi_angle_metadata": multi_angle_metadata,
                    "social_title": social_title,
                    "social_description": social_description,
                    "suggested_hashtags": suggested_hashtags,
                    "thumbnail_filename": thumbnail_filename,
                    "face_detected": face_detected,
                    "hook_preview_score": hook_preview_score,
                },
            )
        except Exception:
            await db.rollback()
            result = await db.execute(
                sa_text("""
                    INSERT INTO generated_clips
                    (task_id, filename, file_path, start_time, end_time, duration,
                     text, relevance_score, reasoning, clip_order, created_at)
                    VALUES
                    (:task_id, :filename, :file_path, :start_time, :end_time, :duration,
                     :text, :relevance_score, :reasoning, :clip_order, NOW())
                    RETURNING id
                """),
                {
                    "task_id": task_id,
                    "filename": filename,
                    "file_path": file_path,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "text": text,
                    "relevance_score": relevance_score,
                    "reasoning": reasoning,
                    "clip_order": clip_order,
                },
            )
        clip_id = result.scalar()
        if not clip_id:
            raise RuntimeError("Failed to create clip: no ID returned")
        logger.debug(f"Created clip {clip_id} for task {task_id}")
        return str(clip_id)

    @staticmethod
    async def get_clips_by_task(db: AsyncSession, task_id: str) -> List[Dict[str, Any]]:
        """Get all clips for a specific task, ordered by clip_order."""
        try:
            result = await db.execute(
                sa_text("""
                    SELECT id, filename, file_path, start_time, end_time, duration,
                           text, relevance_score, reasoning, clip_order, created_at,
                           virality_score, hook_score, engagement_score, value_score, shareability_score, hook_type,
                           translated_text,
                           social_title, social_description, suggested_hashtags,
                           thumbnail_filename, face_detected, hook_preview_score,
                           user_rating, creative_meta_json
                    FROM generated_clips
                    WHERE task_id = :task_id
                    ORDER BY clip_order ASC
                """),
                {"task_id": task_id},
            )
        except Exception:
            await db.rollback()
            result = await db.execute(
                sa_text("""
                    SELECT id, filename, file_path, start_time, end_time, duration,
                           text, relevance_score, reasoning, clip_order, created_at
                    FROM generated_clips
                    WHERE task_id = :task_id
                    ORDER BY clip_order ASC
                """),
                {"task_id": task_id},
            )

        clips = []
        for row in result.fetchall():
            row_dict = row._asdict() if hasattr(row, "_asdict") else dict(row)
            thumb = row_dict.get("thumbnail_filename")
            clips.append(
                {
                    "id": row_dict["id"],
                    "filename": row_dict["filename"],
                    "file_path": row_dict["file_path"],
                    "start_time": row_dict["start_time"],
                    "end_time": row_dict["end_time"],
                    "duration": row_dict["duration"],
                    "text": row_dict["text"],
                    "relevance_score": row_dict["relevance_score"],
                    "reasoning": row_dict["reasoning"],
                    "clip_order": row_dict["clip_order"],
                    "created_at": row_dict["created_at"].isoformat(),
                    "video_url": f"/clips/{task_id}/{row_dict['filename']}",
                    "virality_score": row_dict.get("virality_score") or 0,
                    "hook_score": row_dict.get("hook_score") or 0,
                    "engagement_score": row_dict.get("engagement_score") or 0,
                    "value_score": row_dict.get("value_score") or 0,
                    "shareability_score": row_dict.get("shareability_score") or 0,
                    "hook_type": row_dict.get("hook_type"),
                    "translated_text": row_dict.get("translated_text"),
                    "social_title": row_dict.get("social_title"),
                    "social_description": row_dict.get("social_description"),
                    "suggested_hashtags": row_dict.get("suggested_hashtags") or [],
                    "thumbnail_filename": thumb,
                    "thumbnail_url": f"/clips/{task_id}/{thumb}" if thumb else None,
                    "face_detected": row_dict.get("face_detected"),
                    "hook_preview_score": row_dict.get("hook_preview_score") or 0,
                    "user_rating": row_dict.get("user_rating"),
                    **ClipRepository._unpack_creative_meta(row_dict.get("creative_meta_json")),
                }
            )

        return clips

    @staticmethod
    def _unpack_creative_meta(json_str: Optional[str]) -> Dict[str, Any]:
        """Parse creative_meta_json and return its keys, or empty defaults."""
        if not json_str:
            return {}
        try:
            return json.loads(json_str)
        except Exception:
            return {}

    @staticmethod
    async def update_creative_meta(db: AsyncSession, clip_id: str, creative_meta: Dict[str, Any]) -> None:
        """Persist creative pipeline metadata for a clip."""
        try:
            await db.execute(
                sa_text("""
                    UPDATE generated_clips
                    SET creative_meta_json = :json
                    WHERE id = :clip_id
                """),
                {"json": json.dumps(creative_meta), "clip_id": clip_id},
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.warning("Failed to persist creative_meta for clip %s: %s", clip_id, exc)

    @staticmethod
    async def get_clips_count(db: AsyncSession, task_id: str) -> int:
        """Get the count of clips for a task."""
        result = await db.execute(
            sa_text(
                "SELECT COUNT(*) as count FROM generated_clips WHERE task_id = :task_id"
            ),
            {"task_id": task_id},
        )
        return result.scalar()

    @staticmethod
    async def delete_clips_by_task(db: AsyncSession, task_id: str) -> int:
        """Delete all clips for a task. Returns count of deleted clips."""
        result = await db.execute(
            sa_text("DELETE FROM generated_clips WHERE task_id = :task_id"),
            {"task_id": task_id},
        )
        await db.commit()
        deleted_count = result.rowcount
        logger.info(f"Deleted {deleted_count} clips for task {task_id}")
        return deleted_count

    @staticmethod
    async def delete_clip(db: AsyncSession, clip_id: str) -> None:
        """Delete a single clip by ID."""
        await db.execute(
            sa_text("DELETE FROM generated_clips WHERE id = :clip_id"),
            {"clip_id": clip_id},
        )
        await db.commit()
        logger.info(f"Deleted clip {clip_id}")

    @staticmethod
    async def get_clip_by_id(
        db: AsyncSession, clip_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get one clip by ID."""
        try:
            result = await db.execute(
                sa_text(
                    """
                    SELECT id, task_id, filename, file_path, start_time, end_time, duration,
                           text, relevance_score, reasoning, clip_order,
                           virality_score, hook_score, engagement_score, value_score, shareability_score, hook_type,
                           translated_text,
                           social_title, social_description, suggested_hashtags,
                           thumbnail_filename, face_detected, hook_preview_score,
                           user_rating, created_at
                    FROM generated_clips
                    WHERE id = :clip_id
                    """
                ),
                {"clip_id": clip_id},
            )
        except Exception:
            await db.rollback()
            result = await db.execute(
                sa_text(
                    """
                    SELECT id, task_id, filename, file_path, start_time, end_time, duration,
                           text, relevance_score, reasoning, clip_order, created_at
                    FROM generated_clips
                    WHERE id = :clip_id
                    """
                ),
                {"clip_id": clip_id},
            )
        row = result.fetchone()
        if not row:
            return None

        row_dict = row._asdict() if hasattr(row, "_asdict") else dict(row)
        thumb = row_dict.get("thumbnail_filename")
        return {
            "id": row_dict["id"],
            "task_id": row_dict["task_id"],
            "filename": row_dict["filename"],
            "file_path": row_dict["file_path"],
            "start_time": row_dict["start_time"],
            "end_time": row_dict["end_time"],
            "duration": row_dict["duration"],
            "text": row_dict["text"],
            "relevance_score": row_dict["relevance_score"],
            "reasoning": row_dict["reasoning"],
            "clip_order": row_dict["clip_order"],
            "virality_score": row_dict.get("virality_score") or 0,
            "hook_score": row_dict.get("hook_score") or 0,
            "engagement_score": row_dict.get("engagement_score") or 0,
            "value_score": row_dict.get("value_score") or 0,
            "shareability_score": row_dict.get("shareability_score") or 0,
            "hook_type": row_dict.get("hook_type"),
            "translated_text": row_dict.get("translated_text"),
            "social_title": row_dict.get("social_title"),
            "social_description": row_dict.get("social_description"),
            "suggested_hashtags": row_dict.get("suggested_hashtags") or [],
            "thumbnail_filename": thumb,
            "thumbnail_url": f"/clips/{row_dict['task_id']}/{thumb}" if thumb else None,
            "face_detected": row_dict.get("face_detected"),
            "hook_preview_score": row_dict.get("hook_preview_score") or 0,
            "user_rating": row_dict.get("user_rating"),
            "created_at": row_dict["created_at"].isoformat(),
            "video_url": f"/clips/{row_dict['task_id']}/{row_dict['filename']}",
        }

    @staticmethod
    async def update_clip(
        db: AsyncSession,
        clip_id: str,
        filename: str,
        file_path: str,
        start_time: str,
        end_time: str,
        duration: float,
        text: str,
    ) -> None:
        """Update core clip metadata and file path."""
        await db.execute(
            sa_text(
                """
                UPDATE generated_clips
                SET filename = :filename,
                    file_path = :file_path,
                    start_time = :start_time,
                    end_time = :end_time,
                    duration = :duration,
                    text = :text,
                    updated_at = NOW()
                WHERE id = :clip_id
                """
            ),
            {
                "clip_id": clip_id,
                "filename": filename,
                "file_path": file_path,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "text": text,
            },
        )
        await db.commit()

    @staticmethod
    async def update_clip_rating(
        db: AsyncSession, clip_id: str, rating: int
    ) -> bool:
        """Persist a user rating (1-5) for a clip. Returns True if row was updated."""
        result = await db.execute(
            sa_text(
                """
                UPDATE generated_clips
                SET user_rating = :rating, updated_at = NOW()
                WHERE id = :clip_id
                """
            ),
            {"rating": rating, "clip_id": clip_id},
        )
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def get_rated_clips(db: AsyncSession) -> List[Dict[str, Any]]:
        """Return all clips that have a user_rating (for training data export)."""
        result = await db.execute(
            sa_text(
                """
                SELECT id, task_id, text, virality_score, user_rating,
                       hook_type, duration, reasoning
                FROM generated_clips
                WHERE user_rating IS NOT NULL
                ORDER BY user_rating DESC, created_at DESC
                """
            )
        )
        rows = result.fetchall()
        return [dict(r._mapping) for r in rows]

    @staticmethod
    async def reorder_task_clips(db: AsyncSession, task_id: str) -> None:
        """Normalize clip_order sequence after edits."""
        result = await db.execute(
            sa_text(
                "SELECT id FROM generated_clips WHERE task_id = :task_id ORDER BY clip_order ASC, created_at ASC"
            ),
            {"task_id": task_id},
        )
        clip_ids = [row.id for row in result.fetchall()]
        for idx, cid in enumerate(clip_ids, start=1):
            await db.execute(
                sa_text(
                    "UPDATE generated_clips SET clip_order = :clip_order, updated_at = NOW() WHERE id = :clip_id"
                ),
                {"clip_order": idx, "clip_id": cid},
            )
        await db.commit()
