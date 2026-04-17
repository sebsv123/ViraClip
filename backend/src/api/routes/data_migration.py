"""
Data Migration API — ViraClip

GDPR-compliant user data export and import: create export/import jobs,
poll job status, and retrieve download links.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.data_migration import DataType, ExportFormat, get_migration_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data-migration", tags=["data-migration"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateExportRequest(BaseModel):
    user_id: str
    data_types: List[str]           # DataType values
    export_format: str = "zip"      # ExportFormat value


class CreateImportRequest(BaseModel):
    user_id: str
    source_file: str                # file path on server


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_data_types(values: List[str]) -> List[DataType]:
    valid = {t.value for t in DataType}
    bad = [v for v in values if v not in valid]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown data_types: {bad}. Valid: {sorted(valid)}",
        )
    return [DataType(v) for v in values]


def _parse_format(value: str) -> ExportFormat:
    try:
        return ExportFormat(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format '{value}'. Valid: {[f.value for f in ExportFormat]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/exports")
async def create_export(body: CreateExportRequest):
    """
    Create a data export job for a user.

    `data_types`: list of `clips` | `projects` | `analytics` | `settings` | `templates`
    `export_format`: `zip` | `json` | `csv`
    """
    if not body.data_types:
        raise HTTPException(status_code=400, detail="data_types must not be empty")
    types = _parse_data_types(body.data_types)
    fmt = _parse_format(body.export_format)
    svc = get_migration_service()
    try:
        job = await svc.create_export(body.user_id, types, fmt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "created",
        "job": {
            "job_id": job.job_id,
            "user_id": job.user_id,
            "status": job.status,
            "data_types": [dt.value for dt in job.data_types],
            "format": job.format.value,
        },
    }


@router.get("/exports/{job_id}")
def export_status(job_id: str):
    """Get the status of an export job."""
    svc = get_migration_service()
    status = svc.get_export_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Export job '{job_id}' not found")
    return {"status": "success", "job": status}


@router.post("/imports")
async def create_import(body: CreateImportRequest):
    """
    Create a data import job for a user from a previously uploaded file.
    """
    from pathlib import Path
    svc = get_migration_service()
    try:
        job = await svc.create_import(body.user_id, Path(body.source_file))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "created",
        "job": {
            "job_id": job.job_id,
            "user_id": job.user_id,
            "status": job.status,
            "source_file": str(job.source_file),
        },
    }


@router.get("/imports/{job_id}")
def import_status(job_id: str):
    """Get the status of an import job."""
    svc = get_migration_service()
    status = svc.get_import_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Import job '{job_id}' not found")
    return {"status": "success", "job": status}


@router.get("/data-types")
def list_data_types():
    """List all supported data types for export/import."""
    return {"data_types": [t.value for t in DataType]}


@router.get("/export-formats")
def list_export_formats():
    """List all supported export formats."""
    return {"formats": [f.value for f in ExportFormat]}
