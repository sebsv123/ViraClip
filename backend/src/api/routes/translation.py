"""
REST endpoints for the local voice translation feature.

Routes
------
GET  /api/translation/languages          – list supported languages
POST /api/translation/translate-video    – queue a translation job
GET  /api/translation/status/{job_id}    – poll job status
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ...models import TranslationRequest, TranslationResponse
from ...translation.translator import SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/translation", tags=["translation"])

# Language metadata (code → display details)
_LANGUAGE_META: list[dict[str, str]] = [
    {"code": "es", "name": "Español",   "flag": "🇪🇸"},
    {"code": "en", "name": "English",   "flag": "🇬🇧"},
    {"code": "fr", "name": "Français",  "flag": "🇫🇷"},
    {"code": "de", "name": "Deutsch",   "flag": "🇩🇪"},
    {"code": "pt", "name": "Português", "flag": "🇵🇹"},
    {"code": "it", "name": "Italiano",  "flag": "🇮🇹"},
    {"code": "ja", "name": "日本語",     "flag": "🇯🇵"},
]


@router.get("/languages")
async def list_languages() -> Dict[str, Any]:
    """Return all supported target languages with display name and flag."""
    return {"languages": _LANGUAGE_META}


@router.post("/translate-video", response_model=TranslationResponse, status_code=202)
async def translate_video(request: Request, body: TranslationRequest) -> TranslationResponse:
    """
    Enqueue a video voice-translation job.

    The translation runs asynchronously in an arq worker.  Use the returned
    ``task_id`` to poll ``GET /api/translation/status/{task_id}``.
    """
    job_id = str(uuid.uuid4())

    try:
        pool = await request.app.state.queue_adapter.get_pool()
        await pool.enqueue_job(
            "translate_video_task",
            job_id,
            body.video_path,
            body.target_language,
            body.preserve_background_music,
        )
    except Exception as exc:
        logger.error("Failed to enqueue translation job: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Could not enqueue translation job: {exc}",
        ) from exc

    # Initialise status key in Redis so polls are immediately valid
    try:
        pool = await request.app.state.queue_adapter.get_pool()
        await pool.set(
            f"translation_job:{job_id}",
            json.dumps({"status": "queued", "percent": 0}),
            ex=3600,
        )
    except Exception as exc:
        logger.warning("Could not write initial Redis status: %s", exc)

    return TranslationResponse(task_id=job_id, status="queued")


@router.get("/status/{job_id}", response_model=TranslationResponse)
async def get_translation_status(request: Request, job_id: str) -> TranslationResponse:
    """Return the current status of a translation job."""
    try:
        pool = await request.app.state.queue_adapter.get_pool()
        raw = await pool.get(f"translation_job:{job_id}")
    except Exception as exc:
        logger.error("Redis error while fetching job status: %s", exc)
        raise HTTPException(status_code=503, detail="Could not reach job store") from exc

    if raw is None:
        raise HTTPException(status_code=404, detail=f"No translation job found: {job_id}")

    try:
        payload: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Malformed job status in store")

    return TranslationResponse(
        task_id=job_id,
        status=payload.get("status", "unknown"),
        output_video_url=payload.get("output_video_url"),
        error=payload.get("error"),
        source_language_detected=payload.get("source_language_detected"),
    )
