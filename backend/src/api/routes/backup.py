"""
Backup & Recovery API — ViraClip

Endpoints for creating backups, listing history, restoring, cleanup,
and disaster-recovery readiness checks.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.backup_recovery import (
    get_backup_manager,
    get_disaster_recovery,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backup", tags=["backup"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateBackupRequest(BaseModel):
    name: str
    source_paths: List[str]
    compress: bool = True


class RestoreRequest(BaseModel):
    backup_id: str
    restore_path: Optional[str] = None


class RecoveryRequest(BaseModel):
    backup_id: str
    components: Optional[List[str]] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_record(r) -> Dict[str, Any]:
    return {
        "backup_id": r.backup_id,
        "name": r.name,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "size_bytes": r.size_bytes,
        "file_count": r.file_count,
        "status": r.status,
        "error_message": r.error_message,
        "location": str(r.location),
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("")
async def create_backup(body: CreateBackupRequest):
    """
    Create a new backup from the specified source paths.
    Pass `compress=true` (default) to create a `.tar.gz` archive.
    Returns the backup record including status, size, and location.
    """
    if not body.source_paths:
        raise HTTPException(status_code=400, detail="source_paths must not be empty")

    mgr = get_backup_manager()
    try:
        record = await mgr.create_backup(
            body.name,
            [Path(p) for p in body.source_paths],
            body.compress,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "created", "backup": _fmt_record(record)}


@router.get("")
def list_backups(name: Optional[str] = None):
    """List all backups, newest first. Filter by `name` if provided."""
    mgr = get_backup_manager()
    records = mgr.list_backups(name)
    return {"count": len(records), "backups": [_fmt_record(r) for r in records]}


@router.post("/restore")
async def restore_backup(body: RestoreRequest):
    """
    Restore a backup to the specified `restore_path`
    (defaults to `/app/restore/<timestamp>`).
    """
    mgr = get_backup_manager()
    restore_path = Path(body.restore_path) if body.restore_path else None
    try:
        success = await mgr.restore_backup(body.backup_id, restore_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail=f"Backup '{body.backup_id}' not found")
    return {"status": "restored", "backup_id": body.backup_id}


@router.delete("/cleanup")
def cleanup_old_backups(retention_days: int = 30):
    """Remove backups older than `retention_days` days. Returns count removed."""
    if retention_days < 1:
        raise HTTPException(status_code=400, detail="retention_days must be >= 1")
    mgr = get_backup_manager()
    removed = mgr.cleanup_old_backups(retention_days)
    return {"status": "cleaned", "removed_count": removed, "retention_days": retention_days}


@router.get("/status")
def backup_status():
    """Overall backup system health: total, successful, failed, last backup."""
    mgr = get_backup_manager()
    return {"status": "success", "backup_status": mgr.get_backup_status()}


@router.post("/disaster-recovery")
async def perform_recovery(body: RecoveryRequest):
    """
    Perform full or partial disaster recovery from a backup.

    `components` (optional list) selects which subsystems to recover:
    `database`, `uploads`, `clips`, `config`. Omit for all.
    """
    dr = get_disaster_recovery()
    try:
        results = await dr.perform_recovery(body.backup_id, body.components)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "recovery_complete", "results": results}


@router.get("/disaster-recovery/status")
def recovery_readiness():
    """Check disaster recovery readiness (recent backups, components available)."""
    dr = get_disaster_recovery()
    return {"status": "success", "recovery_status": dr.get_recovery_status()}
