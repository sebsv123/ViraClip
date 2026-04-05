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
    num_clips: int = 6,
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
                num_clips=num_clips,
                progress_callback=update_progress,
                should_cancel=should_cancel,
                clip_ready_callback=clip_ready_callback,
            )

            logger.info(f"Task {task_id} completed successfully")
            return result

        except Exception as e:
            from ..workers.retry_policy import (
                should_retry_task,
                get_max_attempts_for_error,
                format_error_for_storage
            )
            from ..exceptions import ViraClipException
            
            # Get current attempt
            job_try = int(ctx.get("job_try", 1))
            max_tries = get_max_attempts_for_error(e)
            
            # Format error for storage
            error_details = format_error_for_storage(e, task_id, stage="worker")
            
            # Log error with context
            if isinstance(e, ViraClipException):
                logger.error(
                    f"Task {task_id} failed [{e.error_code.value}]: {e.message}",
                    extra={"error_context": e.context, "retryable": e.retryable}
                )
            else:
                logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            
            # Update task with error details
            from ..repositories.task_repository import TaskRepository
            task_repo = TaskRepository()
            try:
                await task_repo.update_task_error(
                    db,
                    task_id,
                    error_code=error_details["error_code"],
                    error_message=error_details["error_message"]
                )
                await db.commit()
            except Exception as db_err:
                logger.warning(f"Failed to update task error in DB: {db_err}")
            
            # Determine if we should retry
            should_retry, delay = should_retry_task(e, job_try, max_tries)
            
            if not should_retry or job_try >= max_tries:
                # Task failed permanently
                try:
                    payload = {
                        "task_id": task_id,
                        "error_code": error_details["error_code"],
                        "error": error_details["error_message"],
                        "tries": job_try,
                        "context": error_details.get("context", {}),
                    }
                    await ctx["redis"].set(
                        f"dead_letter:{task_id}", json.dumps(payload)
                    )
                    await ctx["redis"].sadd("tasks:dead_letter", task_id)
                    
                    error_msg = f"Task failed permanently: {error_details['error_message']}"
                    await progress.error(error_msg)
                    
                    logger.error(
                        f"Task {task_id} moved to dead letter queue after {job_try} attempts"
                    )
                except Exception:
                    logger.exception("Failed to persist dead-letter payload")
            else:
                # Task will be retried
                logger.info(
                    f"Task {task_id} will be retried (attempt {job_try + 1}/{max_tries})"
                    + (f" after {delay}s delay" if delay else "")
                )
            
            # Re-raise so arq handles retry
            raise

async def worker_startup(ctx: Dict[str, Any]) -> None:
    """
    Run cleanup on worker startup to remove old files.
    """
    import asyncio
    from pathlib import Path
    from ..config import get_config
    from ..utils.resource_manager import cleanup_temp_files, detect_hardware_capabilities
    from ..utils.cleanup import cleanup_old_clips, cleanup_old_downloads

    logger.info("Worker starting up...")

    # ── Whisper model warm-up ────────────────────────────────────────────────
    # Pre-load the Whisper model so the first real task doesn't stall waiting
    # for weights to download or for CTranslate2 to compile the graph.
    async def _warm_whisper():
        try:
            from ..config import get_config as _cfg
            _c = _cfg()
            from faster_whisper import WhisperModel
            _model_size = getattr(_c, "whisper_model_size", "small") or "small"
            _device = getattr(_c, "whisper_device", "cpu") or "cpu"
            _compute = getattr(_c, "whisper_compute_type", "int8") or "int8"
            logger.info(
                "🔄 Whisper warm-up: loading model=%s device=%s compute=%s ...",
                _model_size, _device, _compute,
            )
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: WhisperModel(_model_size, device=_device, compute_type=_compute),
            )
            logger.info("✅ Whisper model loaded and ready")
        except Exception as _we:
            logger.warning("Whisper warm-up skipped: %s", _we)

    asyncio.create_task(_warm_whisper())

    # Detect hardware and log capabilities
    hw_caps = detect_hardware_capabilities()

    cfg = get_config()
    clips_dir = Path(cfg.temp_dir) / "uploads" / "clips"
    downloads_dir = Path(cfg.temp_dir) / "uploads"
    
    # Aggressive temp cleanup to free disk space
    temp_base = Path(cfg.temp_dir)
    cleanup_temp_files(temp_base / "segments", max_age_hours=12)
    cleanup_temp_files(temp_base / "uploads", max_age_hours=24)

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
    # Phase 5.2: dedicated CPU queue (GPU tasks go to viraclip_gpu_tasks)
    queue_name = "viraclip_cpu_tasks"

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
    
    # Periodic tasks (Phase 5.3: Model retraining — Sundays at 2 AM)
    @staticmethod
    def _build_cron_jobs():
        from arq import cron
        from ..services.feedback_loop_service import periodic_model_retraining
        return [cron(periodic_model_retraining, hour=2, minute=0, day_of_week=0)]

    cron_jobs = _build_cron_jobs.__func__(None) if False else []  # activated below


# Activate cron jobs after class definition to avoid forward-reference issues
try:
    from arq import cron
    from .feedback_cron import periodic_model_retraining  # re-exported shim
    from .data_pipeline_cron import fetch_trending_data, retrain_scorer_monthly
    WorkerSettings.cron_jobs = [
        # Phase 5.3: weekly virality scorer retrain (Sunday 02:00 UTC)
        cron(periodic_model_retraining, hour=2, minute=0, day_of_week=0),
        # Phase 7.5: daily trending data fetch (03:00 UTC every day)
        cron(fetch_trending_data, hour=3, minute=0),
        # Phase 7.5: monthly full scorer retrain (1st of month, 04:00 UTC)
        cron(retrain_scorer_monthly, hour=4, minute=0, day=1),
    ]
except Exception:  # pragma: no cover
    pass  # cron stays empty if import fails (test environments)
