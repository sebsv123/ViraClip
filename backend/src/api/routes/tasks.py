"""
Task API routes using refactored architecture.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
import logging
from typing import Dict, Any
import inspect
import re
import time
from pathlib import Path
import shutil
import uuid

from ...database import get_db
from ...database import AsyncSessionLocal
from ...domains.autopilot.task_service import TaskService
from ...domains.billing.billing_service import BillingService, BillingLimitExceeded
from ...auth_headers import get_signed_user_id, USER_ID_HEADER
from ...workers.job_queue import JobQueue
from ...workers.progress import ProgressTracker
from ...config import get_config
from ...font_registry import is_font_accessible
from ...utils.async_helpers import run_in_thread
from ...repositories.clip_repository import ClipRepository
from ...repositories.clip_suggestion_repository import ClipSuggestionRepository
from ...api.middleware.rate_limit import task_rate_limit_dependency
import redis.asyncio as aioredis
from ...clip_editor import export_with_preset, EXPORT_PRESETS

from src import gpu_utils

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


def _normalize_font_size(value: Any, default: int = 24) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(12, min(72, parsed))


def _normalize_font_color(value: Any, default: str = "#FFFFFF") -> str:
    if isinstance(value, str) and re.match(r"^#[0-9A-Fa-f]{6}$", value):
        return value.upper()
    return default


def _normalize_font_family(value: Any, default: str = "TikTokSans-Regular") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _get_user_id_from_headers(request: Request) -> str:
    """Get user ID. Monetization on: signed auth (same as create_task/billing_summary). Off: user_id or x-viraclip-user-id."""
    config = get_config()
    if config.monetization_enabled:
        return get_signed_user_id(request, config)
    user_id = request.headers.get("user_id") or request.headers.get(USER_ID_HEADER)
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")
    return user_id


async def _require_task_owner(
    request: Request, task_service: TaskService, db: AsyncSession, task_id: str
):
    """Ensure authenticated user owns the task."""
    user_id = _get_user_id_from_headers(request)

    task = await task_service.task_repo.get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this task")

    return task


@router.get("/")
async def list_tasks(
    request: Request, db: AsyncSession = Depends(get_db), limit: int = 50
):
    """
    Get all tasks for the authenticated user.
    In SELF_HOST mode, returns ALL tasks regardless of user_id.
    """
    config = get_config()
    user_id = _get_user_id_from_headers(request)

    try:
        task_service = TaskService(db)
        tasks = await task_service.get_user_tasks(
            user_id, limit, self_host=config.self_host
        )

        return {"tasks": tasks, "total": len(tasks)}

    except Exception as e:
        logger.error(f"Error retrieving user tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving tasks: {str(e)}")


# Timeout for create_task handler — prevents hanging indefinitely if
# Redis, DB, or any downstream dependency blocks.
_CREATE_TASK_TIMEOUT = 25.0


@router.post("", dependencies=[Depends(task_rate_limit_dependency)])
@router.post("/", dependencies=[Depends(task_rate_limit_dependency)])
async def create_task(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Create a new task and enqueue it for processing.
    Returns task_id immediately.
    """
    try:
        data = await asyncio.wait_for(
            request.json(),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=400, detail="Request body read timed out")
    # FIX 2: Normalize: accept both {"source": {"url": ...}} and {"youtube_url": ...}
    if "youtube_url" in data and "source" not in data:
        data["source"] = {"url": data["youtube_url"]}
    if "url" in data and "source" not in data:
        data["source"] = {"url": data["url"]}

    raw_source = data.get("source")
    config = get_config()
    if config.monetization_enabled:
        user_id = get_signed_user_id(request, config)
    else:
        user_id = request.headers.get("user_id") or request.headers.get(USER_ID_HEADER)
    # FIX 5: Add user_id bypass for local tests without auth
    if not user_id:
        if not config.monetization_enabled:
            user_id = "local-test-user"
        else:
            raise HTTPException(status_code=401, detail="User authentication required")

    # Get font options
    font_options = data.get("font_options", {})
    font_family = _normalize_font_family(
        font_options.get("font_family", "TikTokSans-Regular")
    )
    font_size = _normalize_font_size(font_options.get("font_size", 24))
    font_color = _normalize_font_color(font_options.get("font_color", "#FFFFFF"))
    caption_template = data.get("caption_template", "default")
    include_broll = data.get("include_broll", False)
    processing_mode = data.get("processing_mode", config.default_processing_mode)
    
    # Viral editing features
    jump_cut = bool(data.get("jump_cut", False))
    jump_cut_min_silence = float(data.get("jump_cut_min_silence", 0.3))
    zoom_on_cuts = bool(data.get("zoom_on_cuts", True))
    cut_zoom_factor = float(data.get("cut_zoom_factor", 1.08))
    denoise_audio = bool(data.get("denoise_audio", False))
    
    # NEW: Contextual overlays
    contextual_overlays = bool(data.get("contextual_overlays", True))
    overlay_frequency = data.get("overlay_frequency", "adaptive")
    if overlay_frequency not in {"low", "medium", "high", "very_high", "adaptive"}:
        overlay_frequency = "adaptive"
    
    # NEW: Audio ducking
    audio_ducking = bool(data.get("audio_ducking", True))
    
    # NEW: Speed control
    playback_speed = float(data.get("playback_speed", 1.0))
    if not (0.5 <= playback_speed <= 2.0):
        playback_speed = 1.0
    dramatic_slowmo = bool(data.get("dramatic_slowmo", False))
    speed_ramp_enabled = bool(data.get("speed_ramp_enabled", True))
    
    # NEW: Scene detection
    use_scene_detection = bool(data.get("use_scene_detection", True))
    
    # NEW: Force fresh - skip cache for testing improvements
    force_fresh = bool(data.get("force_fresh", False))
    
    # NEW: Viral template (overrides individual settings if provided)
    viral_template = data.get("viral_template")
    if viral_template:
        from ...domains.virality.viral_templates import get_viral_template_service
        template_params = get_viral_template_service().get_template_config(viral_template)
        if template_params:
            # Apply template overrides
            jump_cut = template_params.get("jump_cut", jump_cut)
            jump_cut_min_silence = template_params.get("jump_cut_min_silence", jump_cut_min_silence)
            zoom_on_cuts = template_params.get("zoom_on_cuts", zoom_on_cuts)
            cut_zoom_factor = template_params.get("zoom_factor", cut_zoom_factor)
            denoise_audio = template_params.get("denoise_audio", denoise_audio)
            contextual_overlays = template_params.get("overlay_enabled", contextual_overlays)
            overlay_frequency = template_params.get("overlay_frequency", overlay_frequency)
            audio_ducking = template_params.get("audio_ducking", audio_ducking)
    if processing_mode not in {"fast", "balanced", "quality", "elite"}:
        processing_mode = config.default_processing_mode
    output_format = data.get("output_format", "vertical")
    if output_format not in {"vertical", "original"}:
        output_format = "vertical"
    add_subtitles = data.get("add_subtitles", True)
    if not isinstance(add_subtitles, bool):
        add_subtitles = True
    target_language = data.get("target_language", "eng")
    auto_center_face = data.get("auto_center_face", False)
    eye_contact_correction = data.get("eye_contact_correction", False)
    split_screen = data.get("split_screen", False)
    target_platform = data.get("target_platform", "all")
    if target_platform not in {"tiktok", "reels", "shorts", "all"}:
        target_platform = "all"
    generate_ab_variants = bool(data.get("generate_ab_variants", False))  # P3.5
    num_clips = max(3, min(10, int(data.get("num_clips", 6))))
    
    # ComfyUI AI features (Phase 10)
    use_comfyui_reframe = bool(data.get("use_comfyui_reframe", False))
    use_comfyui_thumbnail = bool(data.get("use_comfyui_thumbnail", False))
    if not raw_source or not raw_source.get("url"):
        raise HTTPException(status_code=400, detail="Source URL is required")

    try:
        billing_service = BillingService(db)
        await billing_service.assert_can_create_task(user_id)

        task_service = TaskService(db)

        # ── Idempotency check: prevent duplicate submissions ──────────────
        # BUG 4 fix: if the same user already has a task for the same URL
        # that is still queued or processing, return the existing task_id
        # instead of creating a duplicate.
        existing_task = await task_service.task_repo.find_task_by_user_and_url(
            db, user_id, raw_source["url"]
        )
        if existing_task and existing_task.get("status") in ("queued", "processing"):
            logger.info(
                f"Idempotency hit: user {user_id} already has task "
                f"{existing_task['id']} for URL {raw_source['url'][:60]} "
                f"(status={existing_task['status']}) — returning existing task"
            )
            return {
                "task_id": existing_task["id"],
                "message": "Task already exists and is being processed",
                "duplicate": True,
            }

        # Create task
        task_id = await task_service.create_task_with_source(
            user_id=user_id,
            url=raw_source["url"],
            title=raw_source.get("title"),
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
            force_fresh=force_fresh,
        )

        # Get source type for worker
        source_type = task_service.video_service.determine_source_type(
            raw_source["url"]
        )

        # Enqueue job for worker.
        # Note: generate_ab_variants and target_platform are NOT stored in the task
        # record — they are passed directly as job arguments so the worker can act on
        # them at render time.  task_service.process_task() uses generate_ab_variants
        # to optionally render a B-variant clip for each segment (P3.5).
        logger.info("[ENQUEUE] Attempting to enqueue task %s (mode=%s, source=%s)", task_id, processing_mode, source_type)
        queue_adapter = getattr(request.app.state, "queue_adapter", JobQueue)
        try:
            job_id = await queue_adapter.enqueue_processing_job(
                "process_video_task",
                processing_mode,
                task_id,
                raw_source["url"],
                source_type,
                user_id,
                font_family,
                font_size,
                font_color,
                caption_template,
                processing_mode,
                output_format,
                add_subtitles,
                target_language,
                auto_center_face,
                eye_contact_correction,
                include_broll,
                split_screen,
            )
            logger.info("[ENQUEUE] ✅ Success: task %s → job %s (queue=%s)", task_id, job_id, processing_mode)
        except Exception as exc:
            logger.error("[ENQUEUE] ❌ Failed to enqueue task %s: %s", task_id, exc)
            raise

        # Save source metadata for resume/retries in environments without sources.url column
        # Use the existing JobQueue pool (ArqRedis) instead of creating a new connection
        try:
            pool = await JobQueue.get_pool()
            await pool.set(
                f"task_source:{task_id}",
                json.dumps({
                    "url": raw_source["url"],
                    "source_type": source_type,
                    "output_format": output_format,
                    "add_subtitles": add_subtitles,
                    "force_fresh": force_fresh,
                }),
                ex=60 * 60 * 24 * 7,
            )
        except Exception as e:
            logger.warning(f"Failed to save task source metadata to Redis: {e}")
            # Non-fatal: task will still work without this cache entry

        logger.info(f"Task {task_id} created and job {job_id} enqueued")

        return {
            "task_id": task_id,
            "job_id": job_id,
            "message": "Task created and queued for processing",
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BillingLimitExceeded as e:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "SUBSCRIPTION_REQUIRED",
                "message": "Active subscription required to create tasks.",
                "billing": e.summary,
            },
        )
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating task: {str(e)}")


@router.post("/batch-start")
async def batch_start(request: Request, db: AsyncSession = Depends(get_db)):
    """
    P3.4: Batch processing — submit multiple YouTube URLs / uploaded file paths
    in one request.  Each source is queued as a separate task.  Returns a
    batch_id (UUID) and the list of created task_ids for status polling.

    Body:
    {
        "sources": ["https://youtube.com/...", "https://youtube.com/..."],
        // All other fields are identical to POST /tasks/ and apply to every task
        "caption_template": "default",
        "target_platform": "tiktok",
        ...
    }

    Returns:
    {
        "batch_id": "uuid",
        "task_ids": [...],
        "queued": N,
        "skipped": M  // sources that failed validation
    }
    """
    import uuid as _uuid
    from ...repositories.task_repository import TaskRepository

    config = get_config()
    if config.monetization_enabled:
        user_id = get_signed_user_id(request, config)
    else:
        user_id = request.headers.get("user_id") or request.headers.get(USER_ID_HEADER)
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")

    data = await request.json()
    sources = data.get("sources", [])
    if not sources or not isinstance(sources, list):
        raise HTTPException(status_code=400, detail="'sources' must be a non-empty list of URLs/paths")
    if len(sources) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 sources per batch")

    # Shared settings for all tasks in the batch
    font_options = data.get("font_options", {})
    shared_settings = {
        "font_family": _normalize_font_family(font_options.get("font_family", "TikTokSans-Regular")),
        "font_size": _normalize_font_size(font_options.get("font_size", 24)),
        "font_color": _normalize_font_color(font_options.get("font_color", "#FFFFFF")),
        "caption_template": data.get("caption_template", "default"),
        "include_broll": data.get("include_broll", False),
        "processing_mode": data.get("processing_mode", config.default_processing_mode),
        "output_format": data.get("output_format", "vertical"),
        "add_subtitles": data.get("add_subtitles", True),
        "target_language": data.get("target_language", "eng"),
        "auto_center_face": data.get("auto_center_face", False),
        "eye_contact_correction": data.get("eye_contact_correction", False),
        "split_screen": data.get("split_screen", False),
        "target_platform": data.get("target_platform", "all"),
    }

    batch_id = str(_uuid.uuid4())
    task_ids = []
    skipped = 0

    job_queue = JobQueue()
    task_service = TaskService(db)

    billing_service = BillingService(db)

    for source_url in sources:
        source_url = str(source_url).strip()
        if not source_url:
            skipped += 1
            continue
        try:
            # Enforce billing limits per task — same as single-task endpoint
            await billing_service.assert_can_create_task(user_id)

            task_id = await task_service.create_task(
                user_id=user_id,
                source=source_url,
                batch_id=batch_id,
                **shared_settings,
            )

            # Determine source type for worker arguments
            source_type = task_service.video_service.determine_source_type(source_url)

            # Use enqueue_processing_job (enqueue_task does not exist on JobQueue)
            await job_queue.enqueue_processing_job(
                "process_video_task",
                shared_settings["processing_mode"],
                task_id,
                source_url,
                source_type,
                user_id,
                shared_settings["font_family"],
                shared_settings["font_size"],
                shared_settings["font_color"],
                shared_settings["caption_template"],
                shared_settings["processing_mode"],
                shared_settings["output_format"],
                shared_settings["add_subtitles"],
                shared_settings["target_language"],
                shared_settings["auto_center_face"],
                shared_settings["eye_contact_correction"],
                shared_settings["include_broll"],
                shared_settings["split_screen"],
                shared_settings["target_platform"],
            )
            task_ids.append(task_id)
            logger.info(f"Batch {batch_id}: queued task {task_id} for {source_url[:60]}")
        except BillingLimitExceeded as e:
            logger.warning(f"Batch {batch_id}: billing limit reached after {len(task_ids)} tasks — {e}")
            skipped += len(sources) - len(task_ids) - skipped  # count all remaining as skipped
            break
        except Exception as e:
            logger.warning(f"Batch {batch_id}: skipped '{source_url[:60]}' — {e}")
            skipped += 1

    if not task_ids:
        raise HTTPException(status_code=400, detail="All provided sources failed validation")

    return {
        "batch_id": batch_id,
        "task_ids": task_ids,
        "queued": len(task_ids),
        "skipped": skipped,
    }


@router.get("/batch/{batch_id}/status")
async def batch_status(batch_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """
    P3.4: Return the status of all tasks belonging to a batch.
    """
    from sqlalchemy import text as sa_text
    config = get_config()
    if config.monetization_enabled:
        user_id = get_signed_user_id(request, config)
    else:
        user_id = request.headers.get("user_id") or request.headers.get(USER_ID_HEADER)
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")

    try:
        result = await db.execute(
            sa_text(
                "SELECT id, status, progress, progress_message, clips_count, created_at, updated_at "
                "FROM tasks WHERE batch_id = :batch_id AND user_id = :user_id ORDER BY created_at ASC"
            ),
            {"batch_id": batch_id, "user_id": user_id},
        )
        rows = result.fetchall()
        tasks = [
            {
                "task_id": row.id,
                "status": row.status,
                "progress": row.progress or 0,
                "progress_message": row.progress_message,
                "clips_count": row.clips_count or 0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        failed = sum(1 for t in tasks if t["status"] in ("error", "cancelled"))
        return {
            "batch_id": batch_id,
            "total": total,
            "completed": completed,
            "failed": failed,
            "processing": total - completed - failed,
            "tasks": tasks,
        }
    except Exception as e:
        logger.error(f"Error fetching batch status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing/summary")
async def get_billing_summary(request: Request, db: AsyncSession = Depends(get_db)):
    """Get monetization status and current usage for authenticated user."""
    config = get_config()
    if config.monetization_enabled:
        user_id = get_signed_user_id(request, config)
    else:
        user_id = request.headers.get("user_id") or request.headers.get(USER_ID_HEADER)
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")

    try:
        billing_service = BillingService(db)
        summary = await billing_service.get_usage_summary(user_id)
        return summary
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving billing summary: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving billing summary: {str(e)}",
        )


@router.get("/{task_id}")
async def get_task(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Get task details."""
    try:
        task_service = TaskService(db)
        # Relaxed ownership check for dev - just verify task exists
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task = await task_service.get_task_with_clips(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        return task

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving task: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving task: {str(e)}")


@router.get("/{task_id}/clips")
async def get_task_clips(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Get all clips for a task."""
    try:
        task_service = TaskService(db)
        # Relaxed ownership check for dev - just verify task exists
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task = await task_service.get_task_with_clips(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        return {
            "task_id": task_id,
            "clips": task.get("clips", []),
            "total_clips": len(task.get("clips", [])),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving clips: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving clips: {str(e)}")


@router.get("/{task_id}/progress")
async def get_task_progress_sse(task_id: str, request: Request):
    """
    SSE endpoint for real-time progress updates.
    Streams progress updates as Server-Sent Events.
    In SELF_HOST mode, skips user_id ownership check.
    """

    config = get_config()
    user_id = _get_user_id_from_headers(request)

    async with AsyncSessionLocal() as local_db:
        task_service = TaskService(local_db)
        task = await task_service.task_repo.get_task_by_id(local_db, task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not config.self_host and task.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this task")

    async def event_generator():
        """Generate SSE events for task progress."""
        # Send initial task status
        yield {
            "event": "status",
            "data": json.dumps(
                {
                    "task_id": task_id,
                    "status": task.get("status"),
                    "progress": task.get("progress", 0),
                    "message": task.get("progress_message", ""),
                }
            ),
        }

        # If task is already completed or error, close connection
        if task.get("status") in ["completed", "error"]:
            yield {"event": "close", "data": json.dumps({"status": task.get("status")})}
            return

        # Connect to Redis for real-time updates
        runtime_config = get_config()
        redis_client = aioredis.Redis(
            host=runtime_config.redis_host,
            port=runtime_config.redis_port,
            password=runtime_config.redis_password,
            decode_responses=True,
        )

        try:
            # Subscribe to progress updates
            async for progress_data in ProgressTracker.subscribe_to_progress(
                redis_client, task_id
            ):
                # Abort early if client already closed the connection (avoids keeping
                # the Redis pub/sub channel open after the browser tab is closed).
                if await request.is_disconnected():
                    logger.info(f"SSE client disconnected for task {task_id}, closing stream")
                    break

                from src.core.feature_flags import FEATURE_FLAGS
                degraded = [k for k, v in FEATURE_FLAGS.get_all().items() if not v]
                progress_data["degraded_features"] = degraded
                progress_data["degraded_message"] = (
                    f"{len(degraded)} features desactivadas por incompatibilidad de dependencias. "
                    "Los clips se generarán en modo degradado."
                ) if degraded else None
                from src.core.feature_flags import FEATURE_FLAGS
                degraded = [k for k, v in FEATURE_FLAGS.get_all().items() if not v]
                progress_data["degraded_features"] = degraded
                progress_data["degraded_message"] = (
                    f"{len(degraded)} features desactivadas por incompatibilidad de dependencias. "
                    "Los clips se generarán en modo degradado."
                ) if degraded else None
                event_type = progress_data.get("event_type", "progress")
                yield {"event": event_type, "data": json.dumps(progress_data)}

                # Close connection if task is done
                if progress_data.get("status") in ["completed", "error"]:
                    yield {
                        "event": "close",
                        "data": json.dumps({"status": progress_data.get("status")}),
                    }
                    break

        finally:
            await redis_client.aclose()

    return EventSourceResponse(event_generator())


@router.patch("/{task_id}")
async def update_task(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Update task details (title)."""
    try:
        data = await request.json()
        title = data.get("title")

        if not title:
            raise HTTPException(status_code=400, detail="Title is required")

        task_service = TaskService(db)

        task = await _require_task_owner(request, task_service, db, task_id)

        # Update source title
        await task_service.source_repo.update_source_title(db, task["source_id"], title)

        return {"message": "Task updated successfully", "task_id": task_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating task: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating task: {str(e)}")


@router.delete("/{task_id}")
async def delete_task(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Delete a task and all its associated clips."""
    try:
        user_id = _get_user_id_from_headers(request)
        task_service = TaskService(db)

        # Get task to verify ownership
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if task["user_id"] != user_id:
            raise HTTPException(
                status_code=403, detail="Not authorized to delete this task"
            )

        # Delete clips and task
        await task_service.delete_task(task_id)

        return {"message": "Task deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting task: {str(e)}")


@router.get("/{task_id}/clips/{clip_id}/suggestions")
async def list_clip_suggestions(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """List editorial suggestions for a clip, grouped by category."""
    try:
        task_service = TaskService(db)
        # Verify task exists (relaxed ownership check for dev - matches clips endpoint)
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        clip = await ClipRepository.get_clip_by_id(db, clip_id)
        if not clip or str(clip.get("task_id")) != str(task_id):
            raise HTTPException(status_code=404, detail="Clip not found")

        rows = await ClipSuggestionRepository.list_by_clip(db, clip_id)

        # FIX: If no suggestions exist, try to regenerate them
        if not rows:
            logger.info(f"[suggestions] No suggestions found for clip {clip_id}, attempting to regenerate")
            try:
                from ...domains.autopilot.suggestion_seeder import seed_suggestions_for_clip

                # Try to get render context for richer suggestions
                ctx = await ClipRepository.get_render_context(db, clip_id)
                if ctx:
                    segment = ctx.get("segment", {})
                    clip_info = ctx.get("clip_info", clip)
                else:
                    # Build segment/clip_info from clip DB row
                    segment = {
                        "start_time": str(clip.get("start_time", 0)),
                        "end_time": str(clip.get("end_time", 0)),
                        "text": clip.get("text", ""),
                        "virality_score": clip.get("virality_score", 50),
                        "hook_score": clip.get("hook_score", 50),
                    }
                    clip_info = {
                        "duration": clip.get("duration", 30),
                        "preset_used": clip.get("preset_used", "default"),
                        "broll_overlays": clip.get("broll_overlays", 0),
                        "zoom_punch_applied": clip.get("zoom_punch_applied", False),
                        "color_grade_applied": clip.get("color_grade_applied", False),
                        "loudnorm_applied": clip.get("loudnorm_applied", False),
                        "hook_reorder_applied": clip.get("hook_reorder_applied", False),
                        "sfx_injected": clip.get("sfx_injected", 0),
                        "contextual_overlays": clip.get("contextual_overlays", 0),
                        "qa_passed": clip.get("qa_passed", True),
                        "qa_issues": clip.get("qa_issues", []) or [],
                        "creative_enhanced": clip.get("creative_enhanced", False),
                    }

                count = await seed_suggestions_for_clip(
                    db,
                    clip_id=clip_id,
                    segment=segment,
                    clip_info=clip_info,
                )
                if count > 0:
                    logger.info(f"[suggestions] Regenerated {count} suggestions for clip {clip_id}")
                    rows = await ClipSuggestionRepository.list_by_clip(db, clip_id)
                else:
                    logger.warning(f"[suggestions] Regeneration returned 0 suggestions for clip {clip_id}")
            except Exception as regen_e:
                logger.error(f"[suggestions] Failed to regenerate for clip {clip_id}: {regen_e}", exc_info=True)

        grouped: Dict[str, list] = {"timing": [], "captions": [], "media": [], "polish": []}
        for row in rows:
            grouped.setdefault(row["category"], []).append(row)

        # Learning: adjust scores based on user preferences
        try:
            from ...domains.autopilot.suggestion_learner import get_user_preferences, adjust_scores
            user_id = _get_user_id_from_headers(request)
            prefs = await get_user_preferences(db, user_id)
            if prefs:
                rows = await adjust_scores(rows, prefs)
                # Rebuild grouped with adjusted scores
                grouped = {"timing": [], "captions": [], "media": [], "polish": []}
                for row in rows:
                    grouped.setdefault(row["category"], []).append(row)
        except Exception as _adj_e:
            logger.debug("[learner] score adjustment skipped: %s", _adj_e)

        return {
            "clip_id": clip_id,
            "clip_status": clip.get("status", "final"),
            "suggestions": rows,
            "grouped": grouped,
            "total": len(rows),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing suggestions: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error listing suggestions: {str(e)}"
        )


@router.patch("/{task_id}/clips/{clip_id}/suggestions/{suggestion_id}")
async def update_clip_suggestion(
    task_id: str,
    clip_id: str,
    suggestion_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Approve / reject a single suggestion (and optionally override its payload)."""
    try:
        task_service = TaskService(db)
        # Verify task exists (relaxed ownership check for dev)
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        clip = await ClipRepository.get_clip_by_id(db, clip_id)
        if not clip or str(clip.get("task_id")) != str(task_id):
            raise HTTPException(status_code=404, detail="Clip not found")

        existing = await ClipSuggestionRepository.get_by_id(db, suggestion_id)
        if not existing or existing["clip_id"] != clip_id:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        body = await request.json()
        new_status = body.get("status")
        if new_status not in {"pending", "approved", "rejected", "ready_for_review"}:
            raise HTTPException(
                status_code=400,
                detail="status must be one of: pending, approved, rejected",
            )

        payload_override = body.get("payload")
        if payload_override is not None and not isinstance(payload_override, dict):
            raise HTTPException(
                status_code=400, detail="payload must be a JSON object"
            )

        ok = await ClipSuggestionRepository.update_status(
            db, suggestion_id, new_status, payload_override=payload_override
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        await db.commit()

        # Learning: record decision for future suggestion improvement
        if new_status in ("approved", "rejected"):
            try:
                from ...domains.autopilot.suggestion_learner import record_decision
                user_id = _get_user_id_from_headers(request)
                await record_decision(
                    db,
                    user_id=user_id,
                    kind=existing["kind"],
                    category=existing["category"],
                    approved=(new_status == "approved"),
                )
            except Exception as _learn_e:
                logger.debug("[learner] decision recording skipped: %s", _learn_e)

        updated = await ClipSuggestionRepository.get_by_id(db, suggestion_id)
        return {"suggestion": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating suggestion: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error updating suggestion: {str(e)}"
        )


@router.patch("/{task_id}/clips/{clip_id}/suggestions/{suggestion_id}/items")
async def update_suggestion_items(
    task_id: str,
    clip_id: str,
    suggestion_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Granular editing: update items within a suggestion (e.g., B-roll cues, caption lines)."""
    try:
        task_service = TaskService(db)
        # Verify task exists (relaxed ownership check for dev)
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        clip = await ClipRepository.get_clip_by_id(db, clip_id)
        if not clip or str(clip.get("task_id")) != str(task_id):
            raise HTTPException(status_code=404, detail="Clip not found")

        # Get current suggestion
        suggestion = await ClipSuggestionRepository.get_by_id(db, suggestion_id)
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        payload = await request.json()
        operation = payload.get("operation", "replace")
        new_items = payload.get("items", [])
        current_payload = suggestion.get("payload", {}) or {}
        current_items = current_payload.get("items", [])

        if operation == "replace":
            current_payload["items"] = new_items
        elif operation == "add":
            current_items.extend(new_items)
            current_payload["items"] = current_items
        elif operation == "remove":
            remove_ids = {item.get("id") for item in new_items}
            current_payload["items"] = [
                i for i in current_items if i.get("id") not in remove_ids
            ]
        elif operation == "update":
            for update_item in new_items:
                item_id = update_item.get("id")
                for idx, existing in enumerate(current_items):
                    if existing.get("id") == item_id:
                        current_items[idx] = {**existing, **update_item}
                        break
            current_payload["items"] = current_items
        else:
            raise HTTPException(status_code=400, detail=f"Unknown operation: {operation}")

        # Update in DB
        await ClipSuggestionRepository.update_payload(db, suggestion_id, current_payload)
        await db.commit()

        updated = await ClipSuggestionRepository.get_by_id(db, suggestion_id)
        return {"suggestion": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating suggestion items: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error updating suggestion items: {str(e)}"
        )


@router.post("/{task_id}/clips/{clip_id}/suggestions/reset")
async def reset_clip_suggestions(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Delete all suggestions for a clip and regenerate them."""
    try:
        task_service = TaskService(db)
        # Verify task exists (relaxed ownership check for dev)
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        clip = await ClipRepository.get_clip_by_id(db, clip_id)
        if not clip or str(clip.get("task_id")) != str(task_id):
            raise HTTPException(status_code=404, detail="Clip not found")

        affected = await ClipSuggestionRepository.reset_clip(db, clip_id)
        await db.commit()
        return {"clip_id": clip_id, "reset": affected}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting suggestions: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error resetting suggestions: {str(e)}"
        )


@router.post("/{task_id}/clips/{clip_id}/preview")
async def preview_clip_with_suggestions(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Enqueue a low-res preview applying only the currently-approved suggestions.

    Returns immediately with a job_id; client should poll or use SSE to track progress.
    """
    from ...workers.job_queue import JobQueue

    task_service = TaskService(db)
    await _require_task_owner(request, task_service, db, task_id)

    clip = await ClipRepository.get_clip_by_id(db, clip_id)
    if not clip or str(clip.get("task_id")) != str(task_id):
        raise HTTPException(status_code=404, detail="Clip not found")

    # Check if already processing
    redis = await JobQueue.get_pool()
    existing = await redis.get(f"clip_preview:{clip_id}:path")
    if existing:
        return {
            "clip_id": clip_id,
            "status": "ready",
            "preview_url": f"/clips/preview/{clip_id}",
        }

    # Enqueue preview worker job
    job = await JobQueue.enqueue_processing_job(
        "preview_clip_with_suggestions_task",
        "fast",  # queue name
        clip_id,
        task_id,
    )

    return {
        "clip_id": clip_id,
        "status": "processing",
        "job_id": str(job.job_id) if job else None,
    }


@router.post("/{task_id}/clips/{clip_id}/finalize")
async def finalize_clip_with_suggestions(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Enqueue final render applying only approved suggestions, marks clip ``final``.

    Returns immediately with a job_id; original clip is replaced on success.
    """
    from ...workers.job_queue import JobQueue

    task_service = TaskService(db)
    await _require_task_owner(request, task_service, db, task_id)

    clip = await ClipRepository.get_clip_by_id(db, clip_id)
    if not clip or str(clip.get("task_id")) != str(task_id):
        raise HTTPException(status_code=404, detail="Clip not found")

    # Check if already final
    if clip.get("status") == "final":
        return {
            "clip_id": clip_id,
            "status": "final",
            "message": "Clip is already finalized",
        }

    # Check if already processing
    redis = await JobQueue.get_pool()
    existing_job = await redis.get(f"clip_finalize:{clip_id}:meta")
    if existing_job:
        return {
            "clip_id": clip_id,
            "status": "processing",
            "message": "Finalize already in progress",
        }

    # Enqueue finalize worker job
    job = await JobQueue.enqueue_processing_job(
        "finalize_clip_with_suggestions_task",
        "standard",  # queue name
        clip_id,
        task_id,
    )

    return {
        "clip_id": clip_id,
        "status": "processing",
        "job_id": str(job.job_id) if job else None,
    }


@router.delete("/{task_id}/clips/{clip_id}")
async def delete_clip(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Delete a specific clip."""
    try:
        user_id = _get_user_id_from_headers(request)
        task_service = TaskService(db)

        # Verify task ownership
        task = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if task["user_id"] != user_id:
            raise HTTPException(
                status_code=403, detail="Not authorized to delete this clip"
            )

        # Delete the clip
        await task_service.clip_repo.delete_clip(db, clip_id)

        return {"message": "Clip deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting clip: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting clip: {str(e)}")


@router.patch("/{task_id}/clips/{clip_id}")
async def trim_clip(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Trim clip boundaries and regenerate clip file."""
    try:
        payload = await request.json()
        start_offset = float(payload.get("start_offset", 0))
        end_offset = float(payload.get("end_offset", 0))

        if start_offset < 0 or end_offset < 0:
            raise HTTPException(status_code=400, detail="Offsets must be non-negative")

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        updated_clip = await task_service.trim_clip(
            task_id, clip_id, start_offset, end_offset
        )
        return {"clip": updated_clip}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error trimming clip: {e}")
        raise HTTPException(status_code=500, detail=f"Error trimming clip: {str(e)}")


@router.post("/{task_id}/clips/{clip_id}/ai-broll")
async def generate_ai_broll(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Generate AI B-roll using LTX-Video text-to-video model.
    
    Requires LTXV_ENABLED=true and COMFYUI_ENABLED=true in environment.
    """
    import os
    
    # Check if LTX is enabled
    ltx_enabled = os.getenv("LTXV_ENABLED", "false").lower() == "true" or os.getenv("BROLL_USE_LTX", "false").lower() == "true"
    comfy_enabled = os.getenv("COMFYUI_ENABLED", "false").lower() == "true"
    
    if not (ltx_enabled and comfy_enabled):
        raise HTTPException(
            status_code=503,
            detail="LTX Video generation not available. Configure LTXV_ENABLED=true and COMFYUI_ENABLED=true"
        )
    
    try:
        payload = await request.json()
        prompt = payload.get("prompt", "cinematic B-roll footage")
        duration = float(payload.get("duration", 3.0))
        model = payload.get("model", "ltx-video")
        
        # Validate inputs
        if not prompt or len(prompt) < 3:
            raise HTTPException(status_code=400, detail="Prompt must be at least 3 characters")
        if duration < 2 or duration > 10:
            raise HTTPException(status_code=400, detail="Duration must be between 2-10 seconds")
        
        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        
        # Get the clip to ensure it exists
        from ...repositories.clip_repository import ClipRepository
        clip = await ClipRepository.get_by_id(db, clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        if clip.task_id != task_id:
            raise HTTPException(status_code=403, detail="Clip does not belong to this task")
        
        # Import the GPU task dispatcher
        from ...workers.gpu_tasks import generate_broll_t2v
        from ...core.config import get_config
        
        config = get_config()
        
        # Generate a unique job ID
        import uuid
        job_id = f"ltx_broll_{task_id}_{clip_id}_{uuid.uuid4().hex[:8]}"
        
        # Determine output path
        broll_dir = Path(config.UPLOADS_DIR or "/app/temp/uploads") / "ai_broll"
        broll_dir.mkdir(parents=True, exist_ok=True)
        safe_prompt = "".join(c if c.isalnum() else "_" for c in prompt[:30])
        output_path = str(broll_dir / f"{job_id}_{safe_prompt}.mp4")
        
        # Dispatch the GPU job
        # Note: In a production system, this would be queued via ARQ to a GPU worker
        # For now, we return the job_id so the frontend can poll
        
        logger.info(f"[AI B-roll] Starting LTX generation for clip {clip_id}: {prompt[:50]}...")
        
        # Check if we're in a context where we can dispatch GPU jobs
        try:
            # Try to dispatch to GPU worker if available
            import arq.connections
            from ...core.config import get_config
            config = get_config()
            pool = await arq.connections.create_pool(
                arq.connections.RedisSettings(
                    host=config.redis_host,
                    port=config.redis_port,
                    password=config.redis_password or None
                )
            )
            job = await pool.enqueue_job(
                "generate_broll_t2v",
                {
                    "task_id": task_id,
                    "prompt": prompt,
                    "duration_seconds": duration,
                    "resolution": "720p",
                    "model": model,
                    "clip_index": 0,
                    "output_path": output_path,
                },
                _job_id=job_id,
            )
            await pool.aclose()
            logger.info(f"[AI B-roll] Enqueued GPU job {job_id}")
            return {
                "job_id": job_id,
                "status": "queued",
                "prompt": prompt,
                "duration": duration,
                "estimated_time": "60-120 seconds"
            }
        except Exception as dispatch_e:
            logger.warning(f"[AI B-roll] GPU dispatch failed: {dispatch_e}")
            # Return a fallback that tells the frontend to try alternative methods
            return {
                "job_id": job_id,
                "status": "failed",
                "error": "GPU worker unavailable. LTX requires ComfyUI + GPU worker setup.",
                "fallback": "Use stock video search instead"
            }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AI B-roll] Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI B-roll generation error: {str(e)}")


@router.post("/{task_id}/clips/{clip_id}/split")
async def split_clip(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Split a clip into two clips."""
    try:
        payload = await request.json()
        split_time = float(payload.get("split_time", 0))
        if split_time <= 0:
            raise HTTPException(
                status_code=400, detail="split_time must be greater than zero"
            )

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        result = await task_service.split_clip(task_id, clip_id, split_time)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error splitting clip: {e}")
        raise HTTPException(status_code=500, detail=f"Error splitting clip: {str(e)}")


@router.post("/{task_id}/clips/merge")
async def merge_clips(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Merge multiple clips into one clip."""
    try:
        payload = await request.json()
        clip_ids = payload.get("clip_ids") or []
        if not isinstance(clip_ids, list):
            raise HTTPException(status_code=400, detail="clip_ids must be an array")

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        result = await task_service.merge_clips(task_id, clip_ids)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error merging clips: {e}")
        raise HTTPException(status_code=500, detail=f"Error merging clips: {str(e)}")


@router.post("/{task_id}/compile")
async def compile_clips_into_reel(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Compile all clips for a task into a single highlights reel with transitions.
    Returns the path to the compiled video file.
    """
    try:
        from ..video_processing import get_available_transitions, apply_transition_effect
        from moviepy import VideoFileClip, concatenate_videoclips
        import random

        user_id = _get_user_id_from_headers(request)
        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)

        clip_repo = ClipRepository()

        # Get all clips sorted by order
        clips = await clip_repo.get_clips_by_task(db, task_id)
        if not clips:
            raise HTTPException(status_code=404, detail="No clips found for this task")

        # Filter to only existing video files
        valid_clips = [c for c in clips if c.get("file_path") and Path(c["file_path"]).exists()]
        if len(valid_clips) < 1:
            raise HTTPException(status_code=404, detail="No renderable clip files found")

        if len(valid_clips) == 1:
            # Single clip — return it directly as "compilation"
            clip = valid_clips[0]
            return {
                "compiled_path": clip["file_path"],
                "compiled_url": f"/clips/{clip['filename']}",
                "clip_count": 1,
                "message": "Single clip returned as compilation",
            }

        # Get available transitions
        transition_files = get_available_transitions()

        # Output path for compilation
        config = get_config()
        clips_dir = Path(config.temp_dir) / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        compilation_filename = f"reel_{task_id[:8]}_{int(time.time())}.mp4"
        compilation_path = clips_dir / compilation_filename

        # Compile: apply transitions between each consecutive pair
        # Start with first clip, then apply transition to merge each next clip
        current_path = Path(valid_clips[0]["file_path"])

        for i, clip_info in enumerate(valid_clips[1:], 1):
            next_path = Path(clip_info["file_path"])
            temp_output = clips_dir / f"reel_tmp_{task_id[:8]}_{i}.mp4"

            # Pick a random transition if available, otherwise just concatenate
            success = False
            if transition_files:
                transition_path = Path(random.choice(transition_files))
                success = await run_in_thread(
                    apply_transition_effect,
                    current_path, next_path, transition_path, temp_output
                )

            if success and temp_output.exists():
                # Clean up previous temp file if not the original first clip
                if i > 1 and current_path.name.startswith("reel_tmp_"):
                    try:
                        current_path.unlink()
                    except Exception:
                        pass
                current_path = temp_output
            else:
                # Fallback: concatenate without transition
                try:
                    clip_a = None
                    clip_b = None
                    merged = None
                    try:
                        clip_a = VideoFileClip(str(current_path))
                        clip_b = VideoFileClip(str(next_path))
                        merged = concatenate_videoclips([clip_a, clip_b], method="compose")
                        merged.write_videofile(
                            str(temp_output),
                            codec=gpu_utils.get_video_encoder(),
                            audio_codec="aac",
                            preset="veryfast",
                            logger=None,
                        )
                        if i > 1 and current_path.name.startswith("reel_tmp_"):
                            try:
                                current_path.unlink()
                            except Exception:
                                pass
                        current_path = temp_output
                    finally:
                        for clip in [clip_a, clip_b, merged]:
                            if clip is not None:
                                try:
                                    clip.close()
                                except Exception:
                                    pass
                except Exception as concat_e:
                    logger.error(f"Concat failed at clip {i}: {concat_e}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to concatenate clips at position {i}: {str(concat_e)}"
                    )

        # Move final result to compilation path
        if current_path != compilation_path:
            shutil.move(str(current_path), str(compilation_path))

        if not compilation_path.exists():
            raise HTTPException(status_code=500, detail="Compilation failed — output file not created")

        return {
            "compiled_path": str(compilation_path),
            "compiled_url": f"/clips/{compilation_filename}",
            "clip_count": len(valid_clips),
            "message": f"Compiled {len(valid_clips)} clips into highlights reel",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error compiling clips: {e}")
        raise HTTPException(status_code=500, detail=f"Error compiling clips: {str(e)}")


@router.patch("/{task_id}/clips/{clip_id}/captions")
async def update_clip_captions(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Update clip caption text, timing style and highlighted words."""
    try:
        payload = await request.json()
        caption_text = str(payload.get("caption_text", "")).strip()
        position = str(payload.get("position", "bottom"))
        highlight_words = payload.get("highlight_words") or []
        if not isinstance(highlight_words, list):
            raise HTTPException(
                status_code=400, detail="highlight_words must be an array"
            )

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        updated_clip = await task_service.update_clip_captions(
            task_id,
            clip_id,
            caption_text,
            position,
            [str(word) for word in highlight_words],
        )
        return {"clip": updated_clip}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating captions: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error updating captions: {str(e)}"
        )


@router.post("/{task_id}/clips/{clip_id}/refine")
async def refine_clip_with_ai(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """
    P3.1: AI Chat — natural-language clip refinement.

    Body: { "instruction": "Cut the first 2 seconds" }

    The LLM parses the instruction into one of the supported edit actions
    (trim, split, caption_update, template_change, hook_title) and executes it
    using the existing TaskService methods.  Returns the updated clip or a list
    of clips if a split was performed.
    """
    try:
        payload = await request.json()
        instruction = str(payload.get("instruction", "")).strip()
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction is required")

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)

        # Fetch current clip for context
        clip = await ClipRepository.get_clip_by_id(db, clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")

        clip_duration = float(clip.get("duration", 0))
        current_text = str(clip.get("text", ""))

        # Parse instruction with LLM
        from ...ai import parse_clip_edit_instruction
        action = await parse_clip_edit_instruction(
            instruction, clip_duration=clip_duration, current_text=current_text
        )

        logger.info(
            f"AI refine clip {clip_id}: instruction='{instruction}' "
            f"action={action.action} reasoning={action.reasoning}"
        )

        if action.action == "trim":
            start_off = action.trim_start or 0.0
            end_off = action.trim_end or 0.0
            if start_off <= 0 and end_off <= 0:
                return {
                    "action": "noop",
                    "message": "Could not determine trim amount from instruction",
                    "reasoning": action.reasoning,
                }
            updated = await task_service.trim_clip(task_id, clip_id, start_off, end_off)
            return {"action": "trim", "clip": updated, "reasoning": action.reasoning}

        elif action.action == "split":
            split_at = action.split_at
            if not split_at or split_at <= 0 or split_at >= clip_duration:
                return {
                    "action": "noop",
                    "message": f"Split timestamp {split_at}s is out of clip range (0–{clip_duration:.1f}s)",
                    "reasoning": action.reasoning,
                }
            result = await task_service.split_clip(task_id, clip_id, split_at)
            return {"action": "split", "clips": result, "reasoning": action.reasoning}

        elif action.action == "caption_update":
            if not action.new_caption:
                return {"action": "noop", "message": "No new caption provided", "reasoning": action.reasoning}
            updated = await task_service.update_clip_captions(
                task_id, clip_id, action.new_caption, "bottom", []
            )
            return {"action": "caption_update", "clip": updated, "reasoning": action.reasoning}

        elif action.action == "template_change":
            # template_change is a settings-level action — we store it on the task
            # and return guidance; full re-render would require re-processing the clip
            return {
                "action": "template_change",
                "new_template": action.new_template,
                "reasoning": action.reasoning,
                "message": (
                    f"To apply template '{action.new_template}', use the Caption Template "
                    "selector in the settings panel and click 'Apply to All Clips'."
                ),
            }

        elif action.action == "hook_title":
            if not action.new_hook_title:
                return {"action": "noop", "message": "No hook title provided", "reasoning": action.reasoning}
            # Store hook title as a caption update with the hook prepended
            combined = f"{action.new_hook_title} | {current_text}" if current_text else action.new_hook_title
            updated = await task_service.update_clip_captions(
                task_id, clip_id, combined, "bottom", [action.new_hook_title]
            )
            return {"action": "hook_title", "clip": updated, "hook_title": action.new_hook_title, "reasoning": action.reasoning}

        else:  # noop
            return {
                "action": "noop",
                "message": "No edit performed — instruction was not actionable",
                "reasoning": action.reasoning,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in AI clip refinement: {e}")
        raise HTTPException(status_code=500, detail=f"AI refinement error: {str(e)}")


@router.post("/{task_id}/clips/{clip_id}/regenerate")
async def regenerate_clip(
    task_id: str, clip_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Regenerate a clip using strategy C: same range first, then full-video fallback."""
    try:
        payload = await request.json()
        start_offset = float(payload.get("start_offset", 0))
        end_offset = float(payload.get("end_offset", 0))
        reject_reason = payload.get("reject_reason")
        reject_reason_text = str(reject_reason).strip() if reject_reason else None

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        result = await task_service.regenerate_clip_with_strategy_c(
            task_id, clip_id, start_offset, end_offset, reject_reason=reject_reason_text
        )
        return {
            "clip": result.get("clip", {}),
            "strategy": result.get("strategy", "same_range"),
            "fallback_used": bool(result.get("fallback_used", False)),
            "reject_reason": reject_reason_text,
            "message": "Clip regenerated successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating clip: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error regenerating clip: {str(e)}"
        )


@router.post("/{task_id}/settings")
async def apply_task_settings(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Update task-level styling settings and optionally apply to all existing clips."""
    try:
        payload = await request.json()
        font_family = _normalize_font_family(
            payload.get("font_family", "TikTokSans-Regular")
        )
        font_size = _normalize_font_size(payload.get("font_size", 24))
        font_color = _normalize_font_color(payload.get("font_color", "#FFFFFF"))
        caption_template = payload.get("caption_template", "default")
        include_broll = bool(payload.get("include_broll", False))
        apply_to_existing = bool(payload.get("apply_to_existing", False))

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        task_record = await task_service.task_repo.get_task_by_id(db, task_id)
        if not task_record:
            raise HTTPException(status_code=404, detail="Task not found")
        if not is_font_accessible(font_family, task_record["user_id"]):
            raise HTTPException(
                status_code=400, detail="Selected font is not available"
            )
        task = await task_service.update_task_settings(
            task_id,
            font_family,
            font_size,
            font_color,
            caption_template,
            include_broll,
            apply_to_existing,
        )
        return {"task": task, "message": "Task settings updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating task settings: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error updating task settings: {str(e)}"
        )


@router.get("/{task_id}/clips/{clip_id}/export")
async def export_clip(
    task_id: str,
    clip_id: str,
    request: Request,
    preset: str = "tiktok",
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Export clip with a social platform preset.

    Args:
        force: If True, bypass the export quality gate (requires explicit approval).
    """
    try:
        config = get_config()
        preset_name = preset.lower().strip()
        if preset_name not in EXPORT_PRESETS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid preset. Use one of: {', '.join(EXPORT_PRESETS.keys())}",
            )

        task_service = TaskService(db)
        await _require_task_owner(request, task_service, db, task_id)
        clip = await task_service.clip_repo.get_clip_by_id(db, clip_id)
        if not clip or clip.get("task_id") != task_id:
            raise HTTPException(status_code=404, detail="Clip not found")

        # ── Export Gate: block weak clips from being published ──────────────
        from ...domains.validation.export_gate import check_export_readiness
        gate_result = check_export_readiness(
            clip_data={
                "hook_score": clip.get("hook_score", 0),
                "virality_score": clip.get("virality_score", 0),
                "hook_type": clip.get("hook_type", ""),
                "words": clip.get("words", []),
                "duration": clip.get("duration", 30),
                "broll_count": clip.get("broll_count", 0),
                "loudnorm_applied": clip.get("loudnorm_applied", False),
                "audio_ducking_applied": clip.get("audio_ducking_applied", False),
                "has_cta": clip.get("has_cta", False),
                "closing_score": clip.get("closing_score", 0),
                "is_insurance_content": clip.get("is_insurance_content", False),
                "insurance_keywords_kept": clip.get("insurance_keywords_kept", []),
            },
            force=force,
        )

        if not gate_result.passed:
            logger.warning(
                "[ExportGate] ❌ Export blocked for clip %s — %d dimension(s) failed: %s",
                clip_id, len(gate_result.blocked_by), gate_result.blocked_by,
            )
            raise HTTPException(
                status_code=412,  # Precondition Failed
                detail={
                    "error": "Export blocked by quality gate",
                    "export_allowed": False,
                    "gate_result": gate_result.to_dict(),
                    "fix": "Fix the failing dimensions or use ?force=true to override.",
                },
            )

        from pathlib import Path

        output_path = export_with_preset(
            Path(clip["file_path"]),
            Path(config.temp_dir) / "exports",
            preset_name,
        )

        download_name = f"{Path(clip['filename']).stem}_{preset_name}.mp4"
        return FileResponse(
            path=str(output_path), media_type="video/mp4", filename=download_name
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting clip: {e}")
        raise HTTPException(status_code=500, detail=f"Error exporting clip: {str(e)}")


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Cancel an active queued or processing task."""
    try:
        config = get_config()
        task_service = TaskService(db)
        task = await _require_task_owner(request, task_service, db, task_id)

        if task.get("status") in ["completed", "error", "cancelled"]:
            return {"message": f"Task already in terminal state: {task.get('status')}"}

        redis_client = aioredis.Redis(
            host=config.redis_host, port=config.redis_port, password=config.redis_password, decode_responses=True
        )
        try:
            await redis_client.setex(f"task_cancel:{task_id}", 3600, "1")
        finally:
            await redis_client.aclose()

        await task_service.task_repo.update_task_status(
            db,
            task_id,
            "cancelled",
            progress=0,
            progress_message="Cancelled by user",
        )

        return {"message": "Task cancellation requested"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task: {e}")
        raise HTTPException(status_code=500, detail=f"Error cancelling task: {str(e)}")


@router.get("/metrics/performance")
async def get_performance_metrics(db: AsyncSession = Depends(get_db)):
    """Get aggregate processing performance metrics by mode."""
    try:
        task_service = TaskService(db)
        return await task_service.get_performance_metrics()
    except Exception as e:
        logger.error(f"Error loading performance metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Error loading metrics: {str(e)}")


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Resume a cancelled or errored task by enqueueing a new worker job."""
    try:
        config = get_config()
        task_service = TaskService(db)
        task = await _require_task_owner(request, task_service, db, task_id)

        if task.get("status") not in ["cancelled", "error", "queued"]:
            raise HTTPException(
                status_code=400,
                detail="Only cancelled/error/queued tasks can be resumed",
            )

        source_url = task.get("source_url")
        source_type = task.get("source_type")
        output_format = "vertical"
        add_subtitles = True

        redis_client = aioredis.Redis(
            host=config.redis_host, port=config.redis_port, password=config.redis_password, decode_responses=True
        )
        try:
            source_payload = await redis_client.get(f"task_source:{task_id}")
            if source_payload:
                parsed = json.loads(source_payload)
                if not source_url:
                    source_url = parsed.get("url")
                if not source_type:
                    source_type = parsed.get("source_type")
                of = parsed.get("output_format", output_format)
                if of in ("vertical", "original"):
                    output_format = of
                asub = parsed.get("add_subtitles", add_subtitles)
                if isinstance(asub, bool):
                    add_subtitles = asub
        finally:
            await redis_client.aclose()

        if not source_url or not source_type:
            raise HTTPException(status_code=400, detail="Task source URL is missing")

        redis_client = aioredis.Redis(
            host=config.redis_host, port=config.redis_port, password=config.redis_password, decode_responses=True
        )
        try:
            await redis_client.delete(f"task_cancel:{task_id}")
        finally:
            await redis_client.aclose()

        await task_service.task_repo.update_task_status(
            db,
            task_id,
            "queued",
            progress=0,
            progress_message="Re-queued by user",
        )

        processing_mode = task.get("processing_mode") or config.default_processing_mode

        job_id = await JobQueue.enqueue_processing_job(
            "process_video_task",
            processing_mode,
            task_id,
            source_url,
            source_type,
            task["user_id"],
            task.get("font_family") or "TikTokSans-Regular",
            task.get("font_size") or 24,
            task.get("font_color") or "#FFFFFF",
            task.get("caption_template") or "default",
            processing_mode,
            output_format,
            add_subtitles,
        )

        return {"message": "Task resumed", "job_id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming task: {e}")
        raise HTTPException(status_code=500, detail=f"Error resuming task: {str(e)}")


@router.get("/dead-letter/list")
async def list_dead_letter_tasks():
    """List tasks that exhausted retries and landed in dead-letter store."""
    config = get_config()
    redis_client = aioredis.Redis(
        host=config.redis_host, port=config.redis_port, password=config.redis_password, decode_responses=True
    )
    try:
        ids_result = redis_client.smembers("tasks:dead_letter")
        ids = await ids_result if inspect.isawaitable(ids_result) else ids_result
        items = []
        safe_ids = list(ids or [])
        for task_id in sorted(safe_ids):
            payload = await redis_client.get(f"dead_letter:{task_id}")
            if payload:
                try:
                    items.append(json.loads(payload))
                except json.JSONDecodeError:
                    items.append({"task_id": task_id, "raw": payload})

        return {"total": len(items), "tasks": items}
    finally:
        await redis_client.aclose()


@router.get("/{task_id}/progress")
async def stream_task_progress(task_id: str, request: Request):
    """
    SSE endpoint for real-time task progress updates.
    
    Client usage:
        const evtSource = new EventSource(`/tasks/${taskId}/progress`);
        evtSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(data.progress, data.message);
        };
    """
    config = get_config()
    redis_client = aioredis.from_url(
        f"redis://{config.redis_host}:{config.redis_port}",
        password=config.redis_password,
        decode_responses=True,
    )

    async def event_generator():
        try:
            # Send initial state from Redis cache
            tracker = ProgressTracker(redis_client, task_id)
            initial = await tracker.get()
            if initial:
                yield {"data": json.dumps(initial)}

            # Subscribe to real-time updates
            async for update in ProgressTracker.subscribe_to_progress(redis_client, task_id):
                yield {"data": json.dumps(update)}
                # Stop streaming when task completes or errors
                if update.get("status") in {"completed", "error"}:
                    break
        except asyncio.CancelledError:
            logger.debug(f"SSE stream cancelled for task {task_id}")
        finally:
            await redis_client.aclose()

    return EventSourceResponse(event_generator())


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Retry a failed task by re-enqueuing it in ARQ.
    
    Only tasks with status 'error' can be retried.
    Resets the task status to 'pending' and pushes it back to the queue.
    """
    from ...repositories.task_repository import TaskRepository
    from ...config import get_config
    import arq.connections
    import arq.jobs
    
    task_repo = TaskRepository()
    
    # Verify task exists and is in error state
    task = await task_repo.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Ownership check
    user_id = _get_user_id_from_headers(request)
    if task.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if task.status != "error":
        raise HTTPException(
            status_code=400,
            detail=f"Task status is '{task.status}', only 'error' tasks can be retried"
        )
    
    # Reset task to pending
    await task_repo.update_task_status(
        db, task_id, "pending",
        progress=0,
        progress_message="Retrying...",
    )
    
    # Re-enqueue in ARQ
    config = get_config()
    try:
        pool = await arq.connections.create_pool(
            arq.connections.RedisSettings(
                host=config.redis_host,
                port=config.redis_port,
                password=config.redis_password or None,
            )
        )
        job = await arq.jobs.Job.enqueue(
            pool,
            "process_task",
            _job_id=task_id,
            _queue="arq:queue",
            task_id=task_id,
            url=task.url,
            source_type=task.source_type,
        )
        await pool.aclose()
        logger.info(f"Task {task_id} re-enqueued for retry (job={job.job_id})")
    except Exception as e:
        logger.error(f"Failed to re-enqueue task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue retry: {e}")
    
    return {"status": "ok", "message": f"Task {task_id} re-enqueued for retry"}


@router.get("/debug/queue-status")
async def debug_queue_status():
    """Debug: check ARQ queue state in Redis."""
    import arq.connections
    from ...config import get_config
    config = get_config()
    try:
        pool = await arq.connections.create_pool(
            arq.connections.RedisSettings(
                host=config.redis_host,
                port=config.redis_port,
                password=config.redis_password or None
            )
        )
        queue_len = await pool.zcard("arq:queue")
        in_progress = await pool.zcard("arq:in-progress")
        await pool.aclose()
        return {
            "arq_queue_length": queue_len,
            "arq_in_progress": in_progress,
            "redis_host": config.redis_host,
            "redis_port": config.redis_port,
        }
    except Exception as e:
        return {"error": str(e)}
