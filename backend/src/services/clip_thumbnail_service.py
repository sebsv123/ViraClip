"""
Clip Thumbnail Service — Phase 20

Extracts a JPEG still frame from a clip at a given timestamp using FFmpeg.
Caches the thumbnail path in Redis (key: thumb:{clip_id}:{timestamp}).
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_THUMB_DIR = os.environ.get("THUMBNAIL_DIR", "/app/storage/thumbnails")
_THUMB_TTL = 60 * 60 * 24 * 7  # 7 days cache entry
_DEFAULT_QUALITY = 2  # FFmpeg -q:v scale (1=best, 31=worst)


async def extract_thumbnail(
    clip_path: str,
    clip_id: str,
    timestamp: float = 1.0,
    width: int = 480,
    quality: int = _DEFAULT_QUALITY,
) -> Optional[str]:
    """
    Extract a JPEG frame from `clip_path` at `timestamp` seconds.

    Returns the absolute path to the saved JPEG, or None on failure.
    Caches the path in Redis so repeated calls return immediately.
    """
    cache_key = f"thumb:{clip_id}:{timestamp:.2f}"

    cached = await _get_cached(cache_key)
    if cached and Path(cached).exists():
        logger.debug("[thumbnail] cache hit clip=%s ts=%.2f", clip_id, timestamp)
        return cached

    Path(_THUMB_DIR).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(_THUMB_DIR) / f"{clip_id}_{timestamp:.2f}.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", clip_path,
        "-vframes", "1",
        "-q:v", str(quality),
        "-vf", f"scale={width}:-1",
        out_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("[thumbnail] FFmpeg failed clip=%s: %s",
                           clip_id, stderr.decode(errors="replace")[:200])
            return None
        await _set_cached(cache_key, out_path)
        logger.debug("[thumbnail] extracted clip=%s → %s", clip_id, out_path)
        return out_path
    except Exception as exc:
        logger.warning("[thumbnail] extract_thumbnail failed: %s", exc)
        return None


async def delete_thumbnail(clip_id: str, timestamp: Optional[float] = None) -> int:
    """
    Delete thumbnail file(s) for a clip.
    If `timestamp` is given, delete only that specific frame.
    Returns the number of files removed.
    """
    thumb_dir = Path(_THUMB_DIR)
    pattern = f"{clip_id}_{timestamp:.2f}.jpg" if timestamp is not None else f"{clip_id}_*.jpg"
    removed = 0
    for f in thumb_dir.glob(pattern):
        try:
            f.unlink()
            removed += 1
        except Exception:
            pass
    return removed


async def _get_cached(key: str) -> Optional[str]:
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        val = await redis.get(f"cache:{key}")
        return val.decode() if isinstance(val, bytes) else val
    except Exception:
        return None


async def _set_cached(key: str, value: str) -> None:
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        await redis.setex(f"cache:{key}", _THUMB_TTL, value)
    except Exception:
        pass
