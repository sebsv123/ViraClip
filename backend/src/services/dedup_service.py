"""
Deduplication Service — Phase 18

Detects whether a source video has already been processed by hashing its
content (SHA-256) and checking a Redis set per user.

Flow:
    1. Compute SHA-256 of the file bytes (or the first 4 MB for large files).
    2. Check Redis key  dedup:{user_id}:{hash}  (SETNX-like).
    3. If already set → duplicate.
    4. If not set     → store with 30-day TTL, return clear.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

_DEDUP_TTL = 60 * 60 * 24 * 30   # 30 days
_SAMPLE_BYTES = 4 * 1024 * 1024   # 4 MB sample for very large files


def compute_file_hash(path: Union[str, Path], sample_bytes: int = _SAMPLE_BYTES) -> str:
    """
    Return the SHA-256 hex digest for a file.
    For files larger than `sample_bytes`, only the first `sample_bytes` are
    hashed (fast enough for dedup; not cryptographically exhaustive).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with p.open("rb") as fh:
        data = fh.read(sample_bytes)
    return hashlib.sha256(data).hexdigest()


def compute_bytes_hash(data: bytes) -> str:
    """Return SHA-256 hex digest for raw bytes."""
    return hashlib.sha256(data).hexdigest()


async def is_duplicate(user_id: str, file_hash: str) -> bool:
    """
    Return True if `file_hash` has already been registered for `user_id`.
    Fails open on Redis errors (returns False → allow processing).
    """
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        key = f"dedup:{user_id}:{file_hash}"
        exists = await redis.exists(key)
        return bool(exists)
    except Exception as exc:
        logger.warning("[dedup] is_duplicate check failed: %s", exc)
        return False


async def register_hash(user_id: str, file_hash: str, task_id: Optional[str] = None) -> None:
    """
    Mark a hash as seen for `user_id`.
    Optionally stores `task_id` as the value for traceability.
    """
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        key = f"dedup:{user_id}:{file_hash}"
        value = task_id or "1"
        await redis.setex(key, _DEDUP_TTL, value)
        logger.debug("[dedup] Registered hash=%s user=%s task=%s", file_hash[:16], user_id, task_id)
    except Exception as exc:
        logger.warning("[dedup] register_hash failed: %s", exc)


async def get_original_task(user_id: str, file_hash: str) -> Optional[str]:
    """
    Return the task_id stored when the hash was first registered,
    or None if not found / no task_id was stored.
    """
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        key = f"dedup:{user_id}:{file_hash}"
        val = await redis.get(key)
        if val and val != b"1":
            return val.decode() if isinstance(val, bytes) else val
    except Exception as exc:
        logger.warning("[dedup] get_original_task failed: %s", exc)
    return None


async def clear_hash(user_id: str, file_hash: str) -> bool:
    """Remove a previously registered hash (e.g. if the task was deleted)."""
    try:
        from src.workers.job_queue import JobQueue
        redis = await JobQueue.get_pool()
        key = f"dedup:{user_id}:{file_hash}"
        deleted = await redis.delete(key)
        return bool(deleted)
    except Exception as exc:
        logger.warning("[dedup] clear_hash failed: %s", exc)
        return False
