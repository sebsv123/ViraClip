"""Video Ingestion API routes — download from public URLs via yt-dlp."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...api.middleware.rate_limit import ingest_rate_limit_dependency

router = APIRouter(prefix="/ingest", tags=["ingest"])

_DEFAULT_OUTPUT_DIR = os.environ.get("INGEST_OUTPUT_DIR", "/app/storage/ingested")


class IngestRequest(BaseModel):
    url: str
    max_height: int = 1080
    output_dir: Optional[str] = None


class BatchIngestRequest(BaseModel):
    urls: List[str]
    max_height: int = 1080
    max_concurrent: int = 3
    output_dir: Optional[str] = None


class IngestResponse(BaseModel):
    url: str
    local_path: Optional[str]
    platform: str
    title: str
    duration_seconds: float
    file_size_bytes: int
    success: bool
    error: Optional[str]


@router.get("/check")
def check_ytdlp():
    """Check whether yt-dlp is installed and available."""
    from ...services.video_ingestion_service import is_ytdlp_available
    available = is_ytdlp_available()
    return {"yt_dlp_available": available,
            "message": "yt-dlp ready" if available else "Install with: pip install yt-dlp"}


@router.get("/info")
async def get_video_info(url: str):
    """Fetch metadata for a URL without downloading."""
    from ...services.video_ingestion_service import get_video_info
    info = await get_video_info(url)
    if not info:
        raise HTTPException(status_code=400, detail="Could not fetch video metadata")
    return {
        "title": info.get("title", ""),
        "duration": info.get("duration"),
        "uploader": info.get("uploader", ""),
        "platform": info.get("extractor", ""),
        "thumbnail": info.get("thumbnail", ""),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
    }


@router.post("/url", response_model=IngestResponse)
async def ingest_url(body: IngestRequest, _rl=Depends(ingest_rate_limit_dependency)):
    """Download a video from a public URL (YouTube, TikTok, Instagram, Twitch, etc.)."""
    from ...services.video_ingestion_service import ingest_url as _ingest, is_ytdlp_available
    if not is_ytdlp_available():
        raise HTTPException(status_code=503, detail="yt-dlp not installed on server")

    output_dir = body.output_dir or _DEFAULT_OUTPUT_DIR
    result = await _ingest(body.url, output_dir=output_dir, max_height=body.max_height)
    return IngestResponse(
        url=result.url,
        local_path=result.local_path,
        platform=result.platform,
        title=result.title,
        duration_seconds=result.duration_seconds,
        file_size_bytes=result.file_size_bytes,
        success=result.success,
        error=result.error,
    )


@router.post("/batch")
async def ingest_batch(body: BatchIngestRequest, _rl=Depends(ingest_rate_limit_dependency)):
    """Download multiple URLs concurrently."""
    from ...services.video_ingestion_service import ingest_multiple, is_ytdlp_available
    if not is_ytdlp_available():
        raise HTTPException(status_code=503, detail="yt-dlp not installed on server")
    if len(body.urls) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 URLs per batch")

    output_dir = body.output_dir or _DEFAULT_OUTPUT_DIR
    results = await ingest_multiple(body.urls, output_dir=output_dir,
                                    max_concurrent=body.max_concurrent)
    return {
        "total": len(results),
        "succeeded": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "results": [
            {"url": r.url, "local_path": r.local_path, "platform": r.platform,
             "title": r.title, "success": r.success, "error": r.error}
            for r in results
        ],
    }


@router.get("/detect-platform")
def detect_platform(url: str):
    """Detect which platform a URL belongs to."""
    from ...services.video_ingestion_service import detect_platform as _detect
    return {"url": url, "platform": _detect(url)}
