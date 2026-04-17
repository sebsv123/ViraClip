"""
Export API Routes — Phase 16

POST /export/tasks/{task_id}/zip  → download all clips as a ZIP archive
GET  /export/tasks/{task_id}/zip/info → preflight: file count + estimated size
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.repositories.clip_repository import ClipRepository
from src.repositories.task_repository import TaskRepository
from src.services.export_service import build_task_zip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/export", tags=["export"])


@router.get("/tasks/{task_id}/zip/info")
async def export_zip_info(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Preflight check: returns clip count and whether all files are on disk.
    """
    task = await TaskRepository.get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    clips = await ClipRepository.get_clips_by_task(db, task_id)
    total = len(clips)
    missing = sum(1 for c in clips if not Path(c.get("file_path", "")).exists())

    return {
        "task_id": task_id,
        "total_clips": total,
        "missing_files": missing,
        "ready": missing == 0 and total > 0,
    }


@router.post("/tasks/{task_id}/zip")
async def export_task_zip(
    task_id: str,
    include_metadata: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """
    Build and stream a ZIP archive containing all rendered clip files.
    Returns 404 if task not found, 422 if no clips exist.
    """
    task = await TaskRepository.get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    clips = await ClipRepository.get_clips_by_task(db, task_id)
    if not clips:
        raise HTTPException(status_code=422, detail="No clips found for this task")

    task_title = task.get("source_title") or task_id
    try:
        buf = await build_task_zip(
            clips=clips,
            task_title=task_title,
            include_metadata=include_metadata,
        )
    except Exception as exc:
        logger.error("[export] ZIP build failed for task %s: %s", task_id, exc)
        raise HTTPException(status_code=500, detail="ZIP build failed")

    filename = f"viraclip_{task_id[:8]}.zip"
    return StreamingResponse(
        content=buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
