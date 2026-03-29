from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin_auth import require_admin_user
from ...config import get_config
from ...database import get_db
from ...utils.cleanup import cleanup_old_clips, cleanup_old_downloads

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def admin_health(
    request: Request, db: AsyncSession = Depends(get_db)
):
    await require_admin_user(request, db, get_config())
    return {"status": "ok"}


@router.post("/cleanup")
async def run_cleanup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    retention_hours: float = 48.0,
):
    """
    Manually trigger disk cleanup of old clips and downloaded videos.
    Removes files older than `retention_hours` (default 48h).
    Requires admin authentication.
    """
    await require_admin_user(request, db, get_config())
    cfg = get_config()

    clips_dir = Path(cfg.temp_dir) / "clips"
    downloads_dir = Path(cfg.temp_dir) / "uploads"

    clips_deleted, clips_freed = cleanup_old_clips(clips_dir, retention_hours)
    dl_deleted, dl_freed = cleanup_old_downloads(downloads_dir, retention_hours)

    total_freed_mb = (clips_freed + dl_freed) / (1024 * 1024)
    logger.info(
        f"Admin cleanup complete: {clips_deleted + dl_deleted} files, "
        f"{total_freed_mb:.1f}MB freed"
    )
    return {
        "status": "ok",
        "clips_deleted": clips_deleted,
        "clips_freed_mb": round(clips_freed / (1024 * 1024), 2),
        "downloads_deleted": dl_deleted,
        "downloads_freed_mb": round(dl_freed / (1024 * 1024), 2),
        "total_freed_mb": round(total_freed_mb, 2),
        "retention_hours": retention_hours,
    }
