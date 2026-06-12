"""
Clip repository - handles all database operations for generated clips.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sa_text
from typing import List, Dict, Any, Optional
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ClipRepository:
    """Repository for clip-related database operations."""

    _DURABLE_OUTPUT_ROOT = Path("/app/outputs/generated")

    @staticmethod
    def _resolve_existing_generated_clip_path(
        task_id: str,
        file_path: Optional[str],
        filename: str,
        clip_order: Optional[int] = None,
    ) -> Optional[Path]:
        """Resolve the on-disk clip path, preferring durable outputs."""
        task_dir = ClipRepository._DURABLE_OUTPUT_ROOT / task_id
        resolved_name = Path(file_path).name if file_path else filename
        candidate_paths: List[Path] = []

        if file_path:
            candidate = Path(file_path)
            if candidate.exists():
                return candidate
            candidate_paths.append(candidate)
            try:
                rel = candidate.relative_to(ClipRepository._DURABLE_OUTPUT_ROOT)
                candidate_paths.append(ClipRepository._DURABLE_OUTPUT_ROOT / rel)
            except Exception:
                pass

        if resolved_name:
            candidate_paths.append(task_dir / resolved_name)

        if clip_order is not None:
            try:
                clip_idx = int(clip_order)
            except Exception:
                clip_idx = None
            if clip_idx is not None:
                suffixes: List[str] = []
                if file_path:
                    suffixes.append(Path(file_path).suffix)
                if filename:
                    suffixes.append(Path(filename).suffix)
                suffixes.extend([".mp4", ".mov", ".webm", ""])
                stems = [f"clip_{clip_idx:02d}", f"clip_{clip_idx}"]
                for stem in stems:
                    for suffix in suffixes:
                        candidate_paths.append(task_dir / f"{stem}{suffix}")
                    try:
                        candidate_paths.extend(sorted(task_dir.glob(f"{stem}*")))
                    except Exception:
                        pass

        seen: set[str] = set()
        for candidate in candidate_paths:
            try:
                candidate_str = str(candidate.resolve())
            except Exception:
                candidate_str = str(candidate)
            if candidate_str in seen:
                continue
            seen.add(candidate_str)
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _resolve_clip_video_url(
        task_id: str,
        file_path: Optional[str],
        filename: str,
        clip_order: Optional[int] = None,
    ) -> str:
        """Resolve a browser-playable URL for both temp and durable clip paths."""
        resolved_path = ClipRepository._resolve_existing_generated_clip_path(
            task_id=task_id,
            file_path=file_path,
            filename=filename,
            clip_order=clip_order,
        )
        if resolved_path:
            try:
                rel = resolved_path.relative_to(ClipRepository._DURABLE_OUTPUT_ROOT)
                public_url = f"/generated/{rel.as_posix()}"
                logger.info(
                    "CLIP_PLAYBACK_URL_READY task_id=%s clip_order=%s filename=%s url=%s file_exists=%s",
                    task_id,
                    clip_order,
                    resolved_path.name,
                    public_url,
                    resolved_path.exists(),
                )
                return public_url
            except Exception:
                pass

        resolved_name = Path(file_path).name if file_path else filename
        return f"/clips/{task_id}/{resolved_name}"

    @staticmethod
    def build_generated_public_url(task_id: str, output_path: str, clip_order: Optional[int] = None) -> str:
        """Build a public URL for a generated clip without guessing the filename."""
        return ClipRepository._resolve_clip_video_url(
            task_id=task_id,
            file_path=output_path,
            filename=Path(output_path).name,
            clip_order=clip_order,
        )

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
        # Phase 10: viral polish
        cta_overlay_applied: bool = False,
        emoji_overlays_applied: bool = False,
        variants_json: Optional[str] = None,
    ) -> str:
        """Create a new clip record and return its ID."""
        # Serialize complex types for PostgreSQL compatibility
        _multi_angle_metadata_str = json.dumps(multi_angle_metadata) if multi_angle_metadata is not None else None
        _suggested_hashtags_arr = "{" + ",".join(f'"{h}"' for h in suggested_hashtags) + "}" if suggested_hashtags else None

        try:
            result = await db.execute(
                sa_text("""
                    INSERT INTO generated_clips
                    (id, task_id, filename, file_path, start_time, end_time, duration,
                     text, relevance_score, reasoning, clip_order,
                     virality_score, hook_score, engagement_score, value_score, shareability_score, hook_type,
                     translated_text,
                     multi_angle_metadata,
                     social_title, social_description, suggested_hashtags,
                     thumbnail_filename, face_detected,
                     hook_preview_score,
                     cta_overlay_applied, emoji_overlays_applied, variants_json,
                     created_at)
                    VALUES
                    (:id, :task_id, :filename, :file_path, :start_time, :end_time, :duration,
                     :text, :relevance_score, :reasoning, :clip_order,
                     :virality_score, :hook_score, :engagement_score, :value_score, :shareability_score, :hook_type,
                     :translated_text,
                     :multi_angle_metadata,
                     :social_title, :social_description, :suggested_hashtags,
                     :thumbnail_filename, :face_detected,
                     :hook_preview_score,
                     :cta_overlay_applied, :emoji_overlays_applied, :variants_json,
                     NOW())
                    RETURNING id
                """),
                {
                    "id": str(__import__('uuid').uuid4()),
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
                    "multi_angle_metadata": _multi_angle_metadata_str,
                    "social_title": social_title,
                    "social_description": social_description,
                    "suggested_hashtags": _suggested_hashtags_arr,
                    "thumbnail_filename": thumbnail_filename,
                    "face_detected": face_detected,
                    "hook_preview_score": hook_preview_score,
                    "cta_overlay_applied": cta_overlay_applied,
                    "emoji_overlays_applied": emoji_overlays_applied,
                    "variants_json": variants_json,
                },
            )
            clip_id = result.scalar()
            if not clip_id:
                raise RuntimeError("Failed to create clip: no ID returned")
            logger.info(f"CLIP_INSERT_SUCCESS clip_id={clip_id} task_id={task_id} clip_order={clip_order}")
            return str(clip_id)
        except Exception as exc:
            logger.error(f"CLIP_INSERT_FAILED task_id={task_id} clip_order={clip_order} error={exc}", exc_info=True)
            await db.rollback()
            logger.warning(f"CLIP_INSERT_FALLBACK task_id={task_id} clip_order={clip_order} — retrying with minimal insert")
            try:
                result = await db.execute(
                    sa_text("""
                        INSERT INTO generated_clips
                        (id, task_id, filename, file_path, start_time, end_time, duration,
                         text, relevance_score, reasoning, clip_order, created_at)
                        VALUES
                        (:id, :task_id, :filename, :file_path, :start_time, :end_time, :duration,
                         :text, :relevance_score, :reasoning, :clip_order, NOW())
                        RETURNING id
                    """),
                    {
                        "id": str(__import__('uuid').uuid4()),
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
                    raise RuntimeError("Failed to create clip (fallback): no ID returned")
                logger.warning(f"CLIP_INSERT_FALLBACK_SUCCESS clip_id={clip_id} task_id={task_id} clip_order={clip_order}")
                return str(clip_id)
            except Exception as fallback_exc:
                logger.error(f"CLIP_INSERT_FALLBACK_FAILED task_id={task_id} clip_order={clip_order} error={fallback_exc}", exc_info=True)
                raise

    @staticmethod
    def _derive_qc_contract(row_dict: Dict[str, Any]) -> Dict[str, Any]:
        creative_meta = ClipRepository._unpack_creative_meta(row_dict.get("creative_meta_json"))
        if isinstance(creative_meta.get("qc_status"), str):
            return {
                "qc_status": creative_meta.get("qc_status"),
                "qc_reasons": creative_meta.get("qc_reasons") or [],
                "qc_warnings": creative_meta.get("qc_warnings") or [],
            }
        variants = ClipRepository._parse_variants(row_dict.get("variants_json"))
        daily = variants.get("daily_publishing", {}) if isinstance(variants, dict) else {}
        strict_ok = bool(daily.get("strict_publishable"))
        reasons = list(daily.get("strict_publishable_reasons") or [])
        return {
            "qc_status": "ready" if strict_ok else "needs_review",
            "qc_reasons": reasons,
            "qc_warnings": reasons,
        }

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
                           user_rating, creative_meta_json,
                           cta_overlay_applied, emoji_overlays_applied, variants_json
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
            qc_contract = ClipRepository._derive_qc_contract(row_dict)
            video_url = ClipRepository._resolve_clip_video_url(
                task_id=task_id,
                file_path=row_dict.get("file_path"),
                filename=row_dict["filename"],
                clip_order=row_dict.get("clip_order"),
            )
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
                    "video_url": video_url,
                    "public_url": video_url,
                    "clip_url": video_url,
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
                    "cta_overlay_applied": bool(row_dict.get("cta_overlay_applied", False)),
                    "emoji_overlays_applied": bool(row_dict.get("emoji_overlays_applied", False)),
                    "variants": ClipRepository._parse_variants(row_dict.get("variants_json")),
                    "qc_status": qc_contract.get("qc_status"),
                    "qc_reasons": qc_contract.get("qc_reasons"),
                    "qc_warnings": qc_contract.get("qc_warnings"),
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
    def _parse_variants(json_str: Optional[str]) -> List[Dict[str, Any]]:
        """Deserialize variants_json to a list of variant dicts."""
        if not json_str:
            return []
        try:
            return json.loads(json_str)
        except Exception:
            return []

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
    async def count_path_reuse_in_other_tasks(
        db: AsyncSession,
        *,
        task_id: str,
        file_path: str,
    ) -> int:
        """Count how many clips from other tasks already use the same output file path."""
        if not file_path:
            return 0
        result = await db.execute(
            sa_text(
                """
                SELECT COUNT(*) AS count
                FROM generated_clips
                WHERE file_path = :file_path
                  AND task_id <> :task_id
                """
            ),
            {"file_path": file_path, "task_id": task_id},
        )
        return int(result.scalar() or 0)

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
                           user_rating, created_at,
                           cta_overlay_applied, emoji_overlays_applied, variants_json
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
        qc_contract = ClipRepository._derive_qc_contract(row_dict)
        video_url = ClipRepository._resolve_clip_video_url(
            task_id=row_dict["task_id"],
            file_path=row_dict.get("file_path"),
            filename=row_dict["filename"],
            clip_order=row_dict.get("clip_order"),
        )
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
            "cta_overlay_applied": bool(row_dict.get("cta_overlay_applied", False)),
            "emoji_overlays_applied": bool(row_dict.get("emoji_overlays_applied", False)),
            "variants_json": row_dict.get("variants_json"),
            "variants": ClipRepository._parse_variants(row_dict.get("variants_json")),
            "qc_status": qc_contract.get("qc_status"),
            "qc_reasons": qc_contract.get("qc_reasons"),
            "qc_warnings": qc_contract.get("qc_warnings"),
            "created_at": row_dict["created_at"].isoformat(),
            "video_url": video_url,
            "public_url": video_url,
            "clip_url": video_url,
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
