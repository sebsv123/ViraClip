"""Task service — orchestrates task creation and processing workflow.

This file used to be a 1572-line monolith. It is now a thin facade:

- :mod:`._processor_mixin`  — heavy `process_task` orchestrator + completion email
- :mod:`._queries_mixin`    — read-only metadata operations (`get_*`, `delete_*`, `update_settings`, `regenerate`)
- :mod:`._editor_mixin`     — clip editing operations (`trim_clip`, `split_clip`, `merge_clips`, `update_clip_captions`)

Public API of `TaskService` is preserved; existing call sites work unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Config, get_config
from ...domains.video.video_service import VideoService
from ...repositories.cache_repository import CacheRepository
from ...repositories.clip_repository import ClipRepository
from ...repositories.source_repository import SourceRepository
from ...repositories.task_repository import TaskRepository
from ._editor_mixin import _EditorMixin
from ._helpers import build_hook_title as _build_hook_title  # noqa: F401  (re-exported for backwards compatibility)
from ._processor_mixin import _ProcessorMixin
from ._queries_mixin import _QueriesMixin

logger = logging.getLogger(__name__)


class TaskService(_ProcessorMixin, _QueriesMixin, _EditorMixin):
    """Service for task workflow orchestration.

    Methods are split across three mixins for maintainability. The public API
    is unchanged from the pre-refactor monolith.
    """

    def __init__(self, db: AsyncSession, config: Config | None = None):
        self.db = db
        self.task_repo = TaskRepository()
        self.source_repo = SourceRepository()
        self.clip_repo = ClipRepository()
        self.cache_repo = CacheRepository()
        self.video_service = VideoService()
        self.config = config or get_config()

    @staticmethod
    def _build_cache_key(
        url: str,
        source_type: str,
        processing_mode: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate cache key with config hash to auto-invalidate when settings change.

        When min_duration, prompt, or model changes, the hash changes → cache miss → fresh analysis.
        """
        cfg = config or get_config()

        config_params = {
            "min_duration": getattr(cfg, "min_clip_duration", 5),
            "max_duration": getattr(cfg, "max_clip_duration", 45),
            "prompt_version": "v3",  # Bump when LLM prompts in ai.py change
            "llm_model": getattr(cfg, "llm", "ollama:qwen2.5:7b"),
        }

        config_hash = hashlib.md5(
            json.dumps(config_params, sort_keys=True).encode()
        ).hexdigest()[:8]

        payload = f"{source_type}|{processing_mode}|{url.strip()}"
        url_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        return f"{url_hash}:{config_hash}"

    def _is_stale_queued_task(self, task: Dict[str, Any]) -> bool:
        """Detect queued tasks that have likely stalled due to worker issues."""
        if task.get("status") != "queued":
            return False

        created_at = task.get("created_at")
        updated_at = task.get("updated_at") or created_at

        if not created_at or not updated_at:
            return False

        # Always compare in UTC to avoid timezone-naive vs timezone-aware issues.
        now_utc = datetime.now(timezone.utc)
        if getattr(updated_at, "tzinfo", None) is not None:
            updated_utc = updated_at.astimezone(timezone.utc)
        else:
            # Assume naive datetimes are UTC (DB convention)
            updated_utc = updated_at.replace(tzinfo=timezone.utc)

        age_seconds = (now_utc - updated_utc).total_seconds()
        return age_seconds >= self.config.queued_task_timeout_seconds

    async def create_task_with_source(
        self,
        user_id: str,
        url: str,
        title: Optional[str] = None,
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        include_broll: bool = False,
        processing_mode: str = "fast",
        target_language: str = "eng",
        auto_center_face: bool = False,
        eye_contact_correction: bool = False,
        split_screen: bool = False,
        url_secondary: Optional[str] = None,
        batch_id: Optional[str] = None,
        force_fresh: bool = False,
    ) -> str:
        """Create a new task with its associated source. Returns task ID."""
        if not await self.task_repo.user_exists(self.db, user_id):
            raise ValueError(f"User {user_id} not found")

        source_type = self.video_service.determine_source_type(url)

        if not title:
            if source_type == "youtube":
                title = await self.video_service.get_video_title(url)
            else:
                title = "Uploaded Video"

        source_id = await self.source_repo.create_source(
            self.db, source_type=source_type, title=title, url=url
        )

        task_id = await self.task_repo.create_task(
            self.db,
            user_id=user_id,
            source_id=source_id,
            status="queued",
            font_family=font_family,
            font_size=font_size,
            font_color=font_color,
            caption_template=caption_template,
            include_broll=include_broll,
            processing_mode=processing_mode,
            target_language=target_language,
            auto_center_face=auto_center_face,
            eye_contact_correction=eye_contact_correction,
            split_screen=split_screen,
            batch_id=batch_id,
        )

        logger.info(f"Created task {task_id} for user {user_id}")
        return task_id

    async def create_task(
        self,
        user_id: str,
        source: str,
        font_family: str = "TikTokSans-Regular",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        caption_template: str = "default",
        include_broll: bool = False,
        processing_mode: str = "fast",
        output_format: str = "vertical",
        add_subtitles: bool = True,
        target_language: str = "eng",
        auto_center_face: bool = False,
        eye_contact_correction: bool = False,
        split_screen: bool = False,
        target_platform: str = "all",
        batch_id: Optional[str] = None,
    ) -> str:
        """P3.4: Thin wrapper around `create_task_with_source` for batch usage."""
        return await self.create_task_with_source(
            user_id=user_id,
            url=source,
            font_family=font_family,
            font_size=font_size,
            font_color=font_color,
            caption_template=caption_template,
            include_broll=include_broll,
            processing_mode=processing_mode,
            target_language=target_language,
            auto_center_face=auto_center_face,
            eye_contact_correction=eye_contact_correction,
            split_screen=split_screen,
            batch_id=batch_id,
        )

    @staticmethod
    def _seconds_to_mmss(seconds: float) -> str:
        """Format seconds as MM:SS."""
        total = max(0, int(round(seconds)))
        minutes = total // 60
        secs = total % 60
        return f"{minutes:02d}:{secs:02d}"
