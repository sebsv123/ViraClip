"""
arq worker task for video voice translation.

Follows the same patterns as the main ``process_video_task`` in tasks.py.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def translate_video_task(
    ctx: Dict[str, Any],
    job_id: str,
    video_path: str,
    target_language: str,
    preserve_background_music: bool = True,
) -> Dict[str, Any]:
    """
    arq background task: translate the speech in a video to *target_language*.

    Parameters
    ----------
    ctx:
        arq context (provides Redis connection).
    job_id:
        Unique identifier for this translation job (stored in Redis).
    video_path:
        Absolute path on disk to the source video file.
    target_language:
        ISO-639-1 code for the target language (e.g. "es", "fr").
    preserve_background_music:
        Whether to attempt background-music preservation.

    Returns
    -------
    dict
        ``{"status": "completed", "output_video_url": "...", ...}``
    """
    from ..config import Config
    from ..translation.pipeline import (
        STEP_DONE,
        translate_video_audio,
    )

    redis = ctx["redis"]
    config = Config()

    async def _report(step: str, percent: int) -> None:
        payload = {"status": "processing", "step": step, "percent": percent}
        await redis.set(
            f"translation_job:{job_id}",
            __import__("json").dumps(payload),
            ex=3600,
        )

    await _report("Starting", 0)

    try:
        src_path = Path(video_path)
        if not src_path.exists():
            raise FileNotFoundError(f"Source video not found: {video_path}")

        clips_dir = Path(config.temp_dir) / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        out_filename = f"translated_{job_id}.mp4"
        out_path = clips_dir / out_filename

        def _sync_progress(step: str, percent: int) -> None:
            """
            Thread-safe progress reporter.

            ``translate_video_audio`` runs synchronously.  We use
            ``run_coroutine_threadsafe`` with the running event loop so the
            Redis write happens on the correct loop without blocking the
            caller.
            """
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(_report(step, percent), loop)
            except Exception:
                pass

        translate_video_audio(
            video_path=src_path,
            target_language=target_language,
            output_path=out_path,
            preserve_background_music=preserve_background_music,
            progress_callback=_sync_progress,
        )

        output_url = f"/clips/{out_filename}"
        result = {
            "status": "completed",
            "output_video_url": output_url,
            "job_id": job_id,
        }
        await redis.set(
            f"translation_job:{job_id}",
            __import__("json").dumps(result),
            ex=86400,  # keep result for 24 h
        )
        logger.info("Translation job %s completed → %s", job_id, out_path)
        return result

    except Exception as exc:
        error_payload = {
            "status": "error",
            "error": str(exc),
            "job_id": job_id,
        }
        await redis.set(
            f"translation_job:{job_id}",
            __import__("json").dumps(error_payload),
            ex=3600,
        )
        logger.error("Translation job %s failed: %s", job_id, exc, exc_info=True)
        raise
