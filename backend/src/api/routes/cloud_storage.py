"""
Cloud Storage API — ViraClip

Multi-cloud upload/download, presigned URLs, storage class management
and usage statistics across AWS S3, GCS, and Azure Blob.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.cloud_storage import (
    CloudProvider,
    StorageClass,
    get_cloud_storage,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cloud-storage", tags=["cloud-storage"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class UploadRequest(BaseModel):
    local_path: str
    file_key: str
    provider: Optional[str] = None      # CloudProvider value
    storage_class: str = "standard"
    public: bool = False
    metadata: Optional[Dict[str, str]] = None


class DownloadRequest(BaseModel):
    file_key: str
    local_path: str
    provider: Optional[str] = None


class PresignedUrlRequest(BaseModel):
    file_key: str
    expiration: int = 3600              # seconds


class StorageClassRequest(BaseModel):
    file_key: str
    new_class: str                      # StorageClass value
    provider: Optional[str] = None


class DeleteRequest(BaseModel):
    file_key: str
    provider: Optional[str] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_provider(value: Optional[str]) -> Optional[CloudProvider]:
    if value is None:
        return None
    try:
        return CloudProvider(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{value}'. Valid: {[p.value for p in CloudProvider]}",
        )


def _parse_storage_class(value: str) -> StorageClass:
    try:
        return StorageClass(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown storage_class '{value}'. Valid: {[c.value for c in StorageClass]}",
        )


def _fmt_result(r) -> Dict[str, Any]:
    return {
        "success": r.success,
        "file_key": r.file_key if hasattr(r, "file_key") else None,
        "public_url": r.public_url,
        "size_mb": round(r.size_bytes / (1024 * 1024), 3) if r.size_bytes else None,
        "storage_class": r.storage_class.value if r.storage_class else None,
        "upload_time_ms": r.upload_time_ms,
        "error_message": r.error_message,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/upload")
async def upload_file(body: UploadRequest):
    """
    Upload a file to cloud storage.

    `provider`: `aws_s3` | `gcs` | `azure` (uses default if omitted)
    `storage_class`: `standard` | `intelligent_tiering` | `glacier` | `coldline`
    """
    provider = _parse_provider(body.provider)
    storage_class = _parse_storage_class(body.storage_class)
    mgr = get_cloud_storage()
    try:
        result = await mgr.upload_file(
            Path(body.local_path), body.file_key, provider,
            storage_class, body.public, body.metadata,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error_message or "Upload failed")
    return {"status": "uploaded", "result": _fmt_result(result)}


@router.post("/download")
async def download_file(body: DownloadRequest):
    """Download a file from cloud storage to a local path."""
    provider = _parse_provider(body.provider)
    mgr = get_cloud_storage()
    try:
        success = await mgr.download_file(body.file_key, Path(body.local_path), provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail=f"File '{body.file_key}' not found")
    return {"status": "downloaded", "file_key": body.file_key, "local_path": body.local_path}


@router.post("/presigned-url")
async def generate_presigned_url(body: PresignedUrlRequest):
    """
    Generate a time-limited presigned URL for direct file access.

    `expiration` is in seconds (default 3600 = 1 hour).
    """
    if body.expiration < 1:
        raise HTTPException(status_code=400, detail="expiration must be >= 1 second")
    mgr = get_cloud_storage()
    try:
        url = await mgr.generate_presigned_url(body.file_key, body.expiration)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if url is None:
        raise HTTPException(status_code=404, detail=f"File '{body.file_key}' not found")
    return {"file_key": body.file_key, "url": url, "expiration_seconds": body.expiration}


@router.delete("/files")
async def delete_file(body: DeleteRequest):
    """Delete a file from cloud storage."""
    provider = _parse_provider(body.provider)
    mgr = get_cloud_storage()
    try:
        success = await mgr.delete_file(body.file_key, provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail=f"File '{body.file_key}' not found")
    return {"status": "deleted", "file_key": body.file_key}


@router.get("/files")
async def list_files(prefix: str = "", provider: Optional[str] = None):
    """
    List files in cloud storage, optionally filtered by `prefix`.
    """
    prov = _parse_provider(provider)
    mgr = get_cloud_storage()
    try:
        files = await mgr.list_files(prefix, prov)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "count": len(files),
        "files": [
            {
                "key": f.key,
                "size_mb": round(f.size_bytes / (1024 * 1024), 3),
                "last_modified": str(f.last_modified),
                "storage_class": f.storage_class.value,
                "public_url": f.public_url,
            }
            for f in files
        ],
    }


@router.patch("/storage-class")
async def change_storage_class(body: StorageClassRequest):
    """
    Move a file to a different storage class (e.g. archive to Glacier/Coldline).
    """
    new_class = _parse_storage_class(body.new_class)
    provider = _parse_provider(body.provider)
    mgr = get_cloud_storage()
    try:
        success = await mgr.move_to_storage_class(body.file_key, new_class, provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail=f"File '{body.file_key}' not found")
    return {"status": "moved", "file_key": body.file_key, "new_class": body.new_class}


@router.get("/stats")
def usage_stats():
    """Get cloud storage usage statistics."""
    mgr = get_cloud_storage()
    return {"status": "success", "stats": mgr.get_usage_stats()}


@router.get("/providers")
def list_providers():
    """List supported cloud providers and storage classes."""
    return {
        "providers": [p.value for p in CloudProvider],
        "storage_classes": [c.value for c in StorageClass],
    }
