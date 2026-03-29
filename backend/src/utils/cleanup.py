"""
Disk cleanup utility for temp clips and downloaded videos.

Prevents disk exhaustion over time by removing files older than a
configurable retention window. Safe to call from a scheduled job or
admin endpoint; never deletes files created in the last `min_age_hours`.
"""

import logging
import os
import time
from pathlib import Path
from typing import Tuple, Set, Optional

logger = logging.getLogger(__name__)

# Default: keep files for 48 hours before eligible for cleanup
DEFAULT_RETENTION_HOURS = 48


def cleanup_old_clips(
    clips_dir: Path,
    retention_hours: float = DEFAULT_RETENTION_HOURS,
    protected_filenames: Optional[Set[str]] = None,
) -> Tuple[int, int]:
    """
    Remove clip .mp4 files older than `retention_hours` from `clips_dir`.

    Recursively scans for *.mp4 files (handles flat and per-task subdirs).
    Skips files/directories it cannot access.

    B-7 fix: `protected_filenames` is a set of basenames that must NOT be
    deleted even if they exceed the retention window.  Pass filenames of clips
    belonging to active/queued tasks so long-running jobs don't lose their
    output files mid-processing.

    Returns:
        (deleted_count, freed_bytes) — number of files removed and bytes freed.
    """
    if not clips_dir.exists():
        logger.info(f"Cleanup: clips_dir {clips_dir} does not exist, skipping")
        return 0, 0

    _protected = protected_filenames or set()
    cutoff = time.time() - (retention_hours * 3600)
    deleted = 0
    freed = 0
    skipped_protected = 0

    for mp4_file in clips_dir.rglob("*.mp4"):
        try:
            # B-7 fix: never delete files referenced by active tasks
            if mp4_file.name in _protected:
                skipped_protected += 1
                logger.debug(f"Cleanup skipping protected file: {mp4_file.name}")
                continue

            stat = mp4_file.stat()
            if stat.st_mtime < cutoff:
                size = stat.st_size
                mp4_file.unlink()
                deleted += 1
                freed += size
                logger.debug(f"Deleted old clip: {mp4_file.name} ({size // 1024}KB)")
        except FileNotFoundError:
            pass  # Already gone — race condition, not an error
        except Exception as e:
            logger.warning(f"Could not delete {mp4_file}: {e}")

    if skipped_protected:
        logger.info(f"Cleanup: protected {skipped_protected} file(s) referenced by active tasks")

    if deleted:
        logger.info(
            f"🗑️ Cleanup: removed {deleted} clip(s), freed {freed // (1024 * 1024):.1f}MB "
            f"(retention={retention_hours}h)"
        )
    else:
        logger.debug(f"Cleanup: no clips older than {retention_hours}h found")

    # Also clean up stale temp-audio files left by interrupted renders
    temp_audio_deleted = 0
    for tmp_audio in clips_dir.rglob("temp-audio-*.m4a"):
        try:
            stat = tmp_audio.stat()
            if stat.st_mtime < cutoff:
                freed += stat.st_size
                tmp_audio.unlink()
                temp_audio_deleted += 1
        except Exception:
            pass

    if temp_audio_deleted:
        logger.info(f"🗑️ Cleanup: also removed {temp_audio_deleted} stale temp-audio file(s)")

    return deleted, freed


def cleanup_old_downloads(
    downloads_dir: Path,
    retention_hours: float = DEFAULT_RETENTION_HOURS,
) -> Tuple[int, int]:
    """
    Remove downloaded video files older than `retention_hours`.
    Only removes .mp4, .webm, .mkv files (not transcripts or uploads).

    Returns:
        (deleted_count, freed_bytes)
    """
    if not downloads_dir.exists():
        return 0, 0

    cutoff = time.time() - (retention_hours * 3600)
    deleted = 0
    freed = 0
    video_exts = {".mp4", ".webm", ".mkv", ".mov"}

    for f in downloads_dir.iterdir():
        try:
            if f.suffix.lower() not in video_exts:
                continue
            stat = f.stat()
            if stat.st_mtime < cutoff:
                freed += stat.st_size
                f.unlink()
                deleted += 1
                logger.debug(f"Deleted old download: {f.name} ({stat.st_size // (1024*1024):.1f}MB)")
        except Exception as e:
            logger.warning(f"Could not delete download {f}: {e}")

    if deleted:
        logger.info(
            f"🗑️ Download cleanup: removed {deleted} file(s), "
            f"freed {freed // (1024 * 1024):.1f}MB"
        )
    return deleted, freed
