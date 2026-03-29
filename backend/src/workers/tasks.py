"""
Worker tasks - background jobs processed by arq workers.
"""

import logging
from typing import Dict, Any, Optional
import json

from ..observability import configure_logging, set_trace_id

configure_logging()

logger = logging.getLogger(__name__)


async def process_video_task(
    ctx: Dict[str, Any],
    task_id: str,
    url: str,
    source_type: str,
    user_id: str,
    font_family: str = "TikTokSans-Regular",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    processing_mode: str = "fast",
    output_format: str = "vertical",
    add_subtitles: bool = True,
    target_language: str = "eng",
    auto_center_face: bool = False,
    eye_contact_correction: bool = False,
    include_broll: bool = False,
    split_screen: bool = False,
    target_platform: str = "all",
    url_secondary: Optional[str] = None,
    generate_ab_variants: bool = False,   # P3.5
) -> Dict[str, Any]:
    """
    Background worker task to process a video.

    Args:
        ctx: arq context (provides Redis connection and other utilities)
        task_id: Task ID to update
        url: Video URL or file path
        source_type: "youtube" or "upload"
        user_id: User ID who created the task
        font_family: Font family for subtitles
        font_size: Font size for subtitles
        font_color: Font color for subtitles

    Returns:
        Dict with processing results
    """
    from ..database import AsyncSessionLocal
    from ..services.task_service import TaskService
    from ..workers.progress import ProgressTracker

    set_trace_id(f"task-{task_id}")
    logger.info(f"Worker processing task {task_id}")

    # Create progress tracker
    progress = ProgressTracker(ctx["redis"], task_id)

    async with AsyncSessionLocal() as db:
        task_service = TaskService(db)

        try:
            # Progress callback
            async def update_progress(
                percent: int, message: str, status: str = "processing"
            ):
                await progress.update(percent, message, status)
                logger.info(f"Task {task_id}: {percent}% - {message}")

            async def should_cancel() -> bool:
                cancelled = await ctx["redis"].get(f"task_cancel:{task_id}")
                return bool(cancelled)

            async def clip_ready_callback(
                clip_index: int, total_clips: int, clip_data: dict
            ):
                await progress.clip_ready(clip_index, total_clips, clip_data)

            # Process the video
            result = await task_service.process_task(
                task_id=task_id,
                url=url,
                source_type=source_type,
                font_family=font_family,
                font_size=font_size,
                font_color=font_color,
                caption_template=caption_template,
                processing_mode=processing_mode,
                output_format=output_format,
                add_subtitles=add_subtitles,
                target_language=target_language,
                auto_center_face=auto_center_face,
                eye_contact_correction=eye_contact_correction,
                include_broll=include_broll,
                split_screen=split_screen,
                target_platform=target_platform,
                url_secondary=url_secondary,
                generate_ab_variants=generate_ab_variants,
                progress_callback=update_progress,
                should_cancel=should_cancel,
                clip_ready_callback=clip_ready_callback,
            )

            logger.info(f"Task {task_id} completed successfully")
            return result

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            try:
                job_try = int(ctx.get("job_try", 1))
                max_tries = int(getattr(WorkerSettings, "max_tries", 3))
                if job_try >= max_tries:
                    payload = {
                        "task_id": task_id,
                        "error": str(e),
                        "tries": job_try,
                    }
                    await ctx["redis"].set(
                        f"dead_letter:{task_id}", json.dumps(payload)
                    )
                    await ctx["redis"].sadd("tasks:dead_letter", task_id)
                    await progress.error("Task failed permanently after retries")
            except Exception:
                logger.exception("Failed to persist dead-letter payload")
            # Error will be caught by arq and task status will be updated
            raise

async def worker_startup(ctx: Dict[str, Any]) -> None:
    """
    Called once per worker process on startup.
    Performs lightweight housekeeping: prune stale clip files so the disk
    doesn't fill up across multiple processing runs.
    """
    from pathlib import Path
    from ..config import Config
    from ..utils.cleanup import cleanup_old_clips, cleanup_old_downloads

    cfg = Config()
    clips_dir = Path(cfg.temp_dir) / "clips"
    downloads_dir = Path(cfg.temp_dir) / "uploads"

    # B-7 fix: collect filenames referenced by active/queued tasks so we never
    # delete their output files even if they exceed the retention window.
    protected_filenames: set = set()
    try:
        import asyncpg
        db_url = cfg.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """
                SELECT gc.filename
                FROM generated_clips gc
                JOIN tasks t ON gc.task_id = t.id
                WHERE t.status IN ('queued', 'processing')
                """
            )
            protected_filenames = {row["filename"] for row in rows}
            if protected_filenames:
                logger.info(f"[startup cleanup] protecting {len(protected_filenames)} file(s) from active tasks")
        finally:
            await conn.close()
    except Exception as _dbe:
        logger.warning(f"[startup cleanup] could not fetch active task files ({_dbe}) — proceeding without protection")

    # Keep clips for 48 h, downloaded source videos for 24 h
    clips_deleted, clips_freed = cleanup_old_clips(clips_dir, retention_hours=48, protected_filenames=protected_filenames)
    dl_deleted, dl_freed = cleanup_old_downloads(downloads_dir, retention_hours=24)
    logger.info(
        f"[startup cleanup] clips={clips_deleted} files freed, "
        f"downloads={dl_deleted} files freed "
        f"({(clips_freed + dl_freed) // (1024 * 1024):.1f}MB total)"
    )


# Worker configuration for arq
class WorkerSettings:
    """Configuration for arq worker."""

    from ..config import Config
    from arq.connections import RedisSettings

    config = Config()

    # Functions to run
    functions = [process_video_task]
    queue_name = "viraclip_tasks"

    # Redis settings from environment
    redis_settings = RedisSettings(
        host=config.redis_host, port=config.redis_port, password=config.redis_password, database=0
    )

    # Retry settings
    max_tries = 3  # Retry failed jobs up to 3 times
    job_timeout = 3600  # 1 hour timeout for video processing

    # Worker pool settings
    # 1 job per worker process keeps max concurrent renders at 3 workers × 1 job × semaphore(2) = 6
    # Previously max_jobs=2 allowed 3×2×2=12 simultaneous renders on a single machine, saturating CPU/GPU
    max_jobs = 1

    # Startup/shutdown hooks
    on_startup = worker_startup
    cron_jobs = []
