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
    # Viral editing features
    jump_cut: bool = True,
    jump_cut_min_silence: float = 0.3,
    zoom_on_cuts: bool = True,
    cut_zoom_factor: float = 1.08,
    denoise_audio: bool = False,
    contextual_overlays: bool = True,
    overlay_frequency: str = "adaptive",
    audio_ducking: bool = True,
    playback_speed: float = 1.0,
    dramatic_slowmo: bool = False,
    speed_ramp_enabled: bool = True,
    use_scene_detection: bool = True,
    force_fresh: bool = False,
    # ComfyUI AI features (Phase 10)
    use_comfyui_reframe: bool = False,
    use_comfyui_thumbnail: bool = False,
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
    from ..domains.autopilot.task_service import TaskService
    from ..workers.progress import ProgressTracker

    from src.core.log_context import set_task_id, clear_task_id
    set_task_id(str(task_id))
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
                jump_cut=jump_cut,
                jump_cut_min_silence=jump_cut_min_silence,
                zoom_on_cuts=zoom_on_cuts,
                cut_zoom_factor=cut_zoom_factor,
                denoise_audio=denoise_audio,
                contextual_overlays=contextual_overlays,
                overlay_frequency=overlay_frequency,
                audio_ducking=audio_ducking,
                playback_speed=playback_speed,
                dramatic_slowmo=dramatic_slowmo,
                speed_ramp_enabled=speed_ramp_enabled,
                use_scene_detection=use_scene_detection,
                force_fresh=force_fresh,
                use_comfyui_reframe=use_comfyui_reframe,
                use_comfyui_thumbnail=use_comfyui_thumbnail,
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

async def analyze_ab_test(
    ctx: Dict[str, Any],
    user_id: str,
    test_id: str,
) -> Dict[str, Any]:
    """
    ARQ background job: analyze A/B test results and determine winner.
    Enqueued automatically after test_duration_hours expires.
    """
    set_trace_id(f"abtest-{test_id}")
    logger.info(f"[ABTest] Analyzing test {test_id} for user {user_id}")
    try:
        from ..services.ab_testing_service import ABTestingService
        svc = ABTestingService()
        winner = await svc.analyze_test(user_id=user_id, test_id=test_id)
        logger.info(f"[ABTest] Test {test_id} winner: {winner.variant_id if winner else 'inconclusive'}")
        return {"status": "analyzed", "test_id": test_id, "winner": winner.variant_id if winner else None}
    except Exception as e:
        logger.error(f"[ABTest] analyze failed for {test_id}: {e}")
        raise


async def process_scheduled_job(
    ctx: Dict[str, Any],
    job_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """
    ARQ worker function: execute a scheduled automation job.
    Delegates to AutoSchedulerService.process_scheduled_job().
    """
    set_trace_id(f"schedule-{job_id}")
    logger.info(f"[Scheduler] Running job {job_id} for user {user_id}")
    try:
        from ..domains.publishing.auto_scheduler import AutoSchedulerService
        svc = AutoSchedulerService()
        await svc.process_scheduled_job(job_id=job_id, user_id=user_id)
        return {"status": "completed", "job_id": job_id}
    except Exception as e:
        logger.error(f"[Scheduler] Job {job_id} failed: {e}")
        raise



def _log_llm_routing_status():
    """Log which LLM provider is active at worker startup."""
    import os
    deepseek_key = bool(os.getenv("DEEPSEEK_API_KEY"))
    groq_key = bool(os.getenv("GROQ_API_KEY"))
    if deepseek_key:
        logger.info("🔷 LLM primario: DeepSeek V3 (DEEPSEEK_API_KEY configurada)")
    elif groq_key:
        logger.warning("☁️  LLM primario: Groq (DEEPSEEK_API_KEY no configurada — modo fallback)")
    else:
        logger.error("❌ Sin LLM configurado — GROQ_API_KEY y DEEPSEEK_API_KEY ausentes")


async def worker_startup(ctx: Dict[str, Any]) -> None:

    # Log LLM routing status at startup
    _log_llm_routing_status()
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
            import os
            from faster_whisper import WhisperModel
            _model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")
            _device = os.environ.get("WHISPER_DEVICE", "cuda")
            _compute = os.environ.get("WHISPER_COMPUTE_TYPE", "float16")
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
    clips_dir = Path(cfg.temp_dir) / "clips"
    downloads_dir = Path(cfg.temp_dir)
    
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


async def cleanup_stale_tasks(ctx: dict) -> None:
    """
    Marca como FAILED las tasks que llevan más de
    TASK_STALE_TIMEOUT_MINUTES en estado PROCESSING.
    Previene tasks zombie cuando un worker crashea.
    """
    import os
    from datetime import datetime, timedelta

    timeout_min = int(os.getenv("TASK_STALE_TIMEOUT_MINUTES", "45"))
    cutoff = datetime.utcnow() - timedelta(minutes=timeout_min)

    try:
        from ..database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    UPDATE tasks
                    SET status = 'failed',
                        error_code = 'WORKER_TIMEOUT',
                        updated_at = NOW()
                    WHERE status = 'processing'
                      AND updated_at < :cutoff
                    RETURNING id
                """),
                {"cutoff": cutoff},
            )
            await db.commit()
            stale = result.fetchall()
            if stale:
                logger.warning(
                    "[Cleanup] %d stale task(s) marked as failed: %s",
                    len(stale),
                    [str(r[0]) for r in stale],
                )
            else:
                logger.debug("[Cleanup] No stale tasks found")
    except Exception as exc:
        logger.error("[Cleanup] Failed to run stale task cleanup: %s", exc)


# Worker configuration for arq
class WorkerSettings:
    """Configuration for arq worker."""

    from ..config import Config
    from arq.connections import RedisSettings

    config = Config()

    # Functions to run
    functions = [process_video_task, analyze_ab_test, process_scheduled_job]
    # Phase 5.2: dedicated CPU queue (GPU tasks go to viraclip_gpu_tasks)
    queue_name = "viraclip_cpu_tasks"

    # Redis settings from environment
    redis_settings = RedisSettings(
        host=config.redis_host, port=config.redis_port, password=config.redis_password, database=0
    )

    # Retry settings
    max_tries = 3  # Retry failed jobs up to 3 times
    job_timeout = 14400  # 4 hour timeout for video processing (ComfyUI B-roll generation)

    # Worker pool settings
    # 1 job per worker process keeps max concurrent renders at 3 workers × 1 job × semaphore(2) = 6
    # Previously max_jobs=2 allowed 3×2×2=12 simultaneous renders on a single machine, saturating CPU/GPU
    max_jobs = 1

    # Startup/shutdown hooks
    on_startup = worker_startup
    
    # Periodic tasks — built dynamically below via _safe_cron()
    cron_jobs = []


# Activate cron jobs after class definition to avoid forward-reference issues
def _safe_cron(func, name, **kwargs):
    """Safely create a cron job with individual error handling."""
    try:
        from arq import cron
        job = cron(func, **kwargs)
        logger.debug(f"[Scheduler] Registered cron job: {name}")
        return job
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning(
            f"[Scheduler] Failed to register cron job '{name}': {e} — skipping"
        )
        return None


try:
    from .feedback_cron import periodic_model_retraining  # re-exported shim
    from .data_pipeline_cron import fetch_trending_data, retrain_scorer_monthly
    from ..services.self_healing_agent import run_healing_cycle
    
    _cron_jobs = []
    
    # Self-healing agent every 30s
    _job = _safe_cron(
        run_healing_cycle,
        "cron:self_healing",
        second={0, 30},
        timeout=25,
    )
    if _job:
        _cron_jobs.append(_job)
    
    # Stale task cleanup every 10 minutes
    _job = _safe_cron(
        cleanup_stale_tasks,
        "cleanup_stale_tasks",
        minute={0, 10, 20, 30, 40, 50},
    )
    if _job:
        _cron_jobs.append(_job)
    
    # Phase 5.3: weekly virality scorer retrain (Sunday 02:00 UTC)
    # NOTE: arq's cron() does NOT support day_of_week — use weekday parameter instead
    _job = _safe_cron(
        periodic_model_retraining, 
        "periodic_model_retraining",
        hour=2, minute=0, weekday=6  # 6 = Sunday in arq's cron weekday (0=Mon, 6=Sun)
    )
    if _job:
        _cron_jobs.append(_job)
    
    # Phase 7.5: daily trending data fetch (03:00 UTC every day)
    _job = _safe_cron(
        fetch_trending_data,
        "fetch_trending_data",
        hour=3, minute=0
    )
    if _job:
        _cron_jobs.append(_job)
    
    # Phase 7.5: monthly full scorer retrain (1st of month, 04:00 UTC)
    _job = _safe_cron(
        retrain_scorer_monthly,
        "retrain_scorer_monthly",
        hour=4, minute=0, day=1
    )
    if _job:
        _cron_jobs.append(_job)
    
    WorkerSettings.cron_jobs = _cron_jobs
    
    if _cron_jobs:
        import logging as _log
        _log.getLogger(__name__).info(
            f"[WorkerSettings] Successfully registered {len(_cron_jobs)} cron jobs"
        )
    
except Exception as _cron_err:
    import logging as _log
    _log.getLogger(__name__).warning(
        "[WorkerSettings] cron_jobs setup failed: %s — "
        "feedback loop and analytics import will NOT run. "
        "Check imports: feedback_loop_service, data_pipeline_cron",
        _cron_err
    )
    WorkerSettings.cron_jobs = []


# ============================================================================
# Suggestion Studio Worker Tasks (Phase 6)
# ============================================================================

async def preview_clip_with_suggestions_task(
    ctx: Dict[str, Any],
    clip_id: str,
    task_id: str,
) -> Dict[str, Any]:
    """Generate a low-res preview applying only approved suggestions.

    Called by the Suggestion Studio when user toggles suggestions and wants
    to see the result without waiting for full render. Writes the preview to
    a temp location and updates Redis so the SSE endpoint can notify client.
    """
    from ..database import AsyncSessionLocal
    from ..domains.autopilot.suggestion_applicator import (
        apply_suggestions,
        ApplicatorError,
    )
    from ..workers.progress import ProgressTracker

    set_trace_id(f"preview-{clip_id}")
    logger.info(f"[Worker] Starting preview for clip {clip_id}")

    progress = ProgressTracker(ctx["redis"], f"clip_preview:{clip_id}")
    await progress.update(0, "Initializing preview render...", "processing")

    async with AsyncSessionLocal() as db:
        try:
            await progress.update(10, "Loading suggestions...", "processing")
            result = await apply_suggestions(
                db,
                clip_id=clip_id,
                preview=True,
            )

            if result["success"]:
                await progress.update(100, "Preview ready", "completed")
                # Store preview path in Redis for the API to pick up
                await ctx["redis"].setex(
                    f"clip_preview:{clip_id}:path",
                    3600,  # 1 hour TTL
                    result["new_path"],
                )
                await ctx["redis"].setex(
                    f"clip_preview:{clip_id}:meta",
                    3600,
                    json.dumps({
                        "skipped_stages": result["skipped_stages"],
                        "is_preview": True,
                    }),
                )
                logger.info(f"[Worker] Preview complete: {result['new_path']}")
            else:
                await progress.update(100, f"Preview failed: {result['error']}", "failed")
                await ctx["redis"].setex(
                    f"clip_preview:{clip_id}:error",
                    3600,
                    result["error"],
                )

            return result

        except ApplicatorError as e:
            logger.error(f"[Worker] Preview applicator error: {e}")
            await progress.update(100, str(e), "failed")
            return {"success": False, "error": str(e), "clip_id": clip_id}
        except Exception as e:
            logger.exception(f"[Worker] Preview failed for clip {clip_id}")
            await progress.update(100, f"Internal error: {e}", "failed")
            return {"success": False, "error": str(e), "clip_id": clip_id}


async def finalize_clip_with_suggestions_task(
    ctx: Dict[str, Any],
    clip_id: str,
    task_id: str,
) -> Dict[str, Any]:
    """Generate final quality clip applying only approved suggestions.

    Called by the Suggestion Studio when user clicks "Finalize". Replaces
    the original clip file and updates the clip status to 'final'.
    """
    from ..database import AsyncSessionLocal
    from ..domains.autopilot.suggestion_applicator import (
        apply_suggestions,
        ApplicatorError,
    )
    from ..repositories.clip_repository import ClipRepository
    from ..workers.progress import ProgressTracker
    from pathlib import Path
    import shutil

    set_trace_id(f"finalize-{clip_id}")
    logger.info(f"[Worker] Starting finalize for clip {clip_id}")

    progress = ProgressTracker(ctx["redis"], f"clip_finalize:{clip_id}")
    await progress.update(0, "Initializing final render...", "processing")

    async with AsyncSessionLocal() as db:
        try:
            await progress.update(10, "Loading suggestions...", "processing")

            # Get original clip info
            clip = await ClipRepository.get_clip_by_id(db, clip_id)
            if not clip:
                raise ApplicatorError(f"Clip {clip_id} not found")

            original_path = Path(clip.get("file_path", ""))
            output_dir = original_path.parent if original_path.exists() else Path("/tmp")

            result = await apply_suggestions(
                db,
                clip_id=clip_id,
                preview=False,
                output_dir=output_dir,
            )

            if result["success"]:
                new_path = Path(result["new_path"])

                # Backup original (optional - keep for recovery)
                backup_path = original_path.with_suffix(".original" + original_path.suffix)
                if original_path.exists():
                    shutil.copy2(str(original_path), str(backup_path))

                # Replace original with new render
                if new_path.exists():
                    shutil.move(str(new_path), str(original_path))

                # Update clip status to 'final'
                await ClipRepository.set_status(db, clip_id, "final")
                await db.commit()

                await progress.update(100, "Final render complete", "completed")
                await ctx["redis"].setex(
                    f"clip_finalize:{clip_id}:meta",
                    3600,
                    json.dumps({
                        "skipped_stages": result["skipped_stages"],
                        "is_final": True,
                        "backup_path": str(backup_path) if backup_path.exists() else None,
                    }),
                )
                logger.info(f"[Worker] Finalize complete for clip {clip_id}")
            else:
                await progress.update(100, f"Finalize failed: {result['error']}", "failed")
                await ctx["redis"].setex(
                    f"clip_finalize:{clip_id}:error",
                    3600,
                    result["error"],
                )

            return result

        except ApplicatorError as e:
            logger.error(f"[Worker] Finalize applicator error: {e}")
            await progress.update(100, str(e), "failed")
            return {"success": False, "error": str(e), "clip_id": clip_id}
        except Exception as e:
            logger.exception(f"[Worker] Finalize failed for clip {clip_id}")
            await progress.update(100, f"Internal error: {e}", "failed")
            return {"success": False, "error": str(e), "clip_id": clip_id}
