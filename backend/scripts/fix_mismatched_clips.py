#!/usr/bin/env python3
"""Scan /app/exports/clips/ for MP4s with mismatched video/audio durations
and re-encode them to the shorter stream duration.

Usage:
    docker compose exec backend python scripts/fix_mismatched_clips.py
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fix_mismatched_clips")

EXPORTS_DIR = Path("/app/exports/clips")
MAX_DIFF_SECONDS = 1.0  # tolerance before we consider streams mismatched


def get_stream_duration(path: Path) -> tuple[float, float]:
    """Return (video_duration, audio_duration) from ffprobe, or (0, 0) on error."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        v_dur = 0.0
        if data.get("streams"):
            v_dur = float(data["streams"][0].get("duration", 0))

        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        a_dur = 0.0
        if data.get("streams"):
            a_dur = float(data["streams"][0].get("duration", 0))

        return v_dur, a_dur
    except Exception as exc:
        logger.warning("  ffprobe failed for %s: %s", path.name, exc)
        return 0.0, 0.0


def fix_clip(path: Path, v_dur: float, a_dur: float) -> bool:
    """Re-encode clip to the shorter stream duration.

    Returns True if the clip was fixed, False otherwise.
    """
    real_dur = min(v_dur, a_dur)
    tmp_path = path.with_suffix(".fixed.mp4")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(path),
            "-t", str(real_dur),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(tmp_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
            logger.error("  FFmpeg failed for %s: %s", path.name, result.stderr[:200])
            tmp_path.unlink(missing_ok=True)
            return False

        # Replace original
        path.unlink()
        tmp_path.rename(path)
        logger.info(
            "FIXED: %s video=%.2fs audio=%.2fs → %.2fs",
            path.name, v_dur, a_dur, real_dur,
        )
        return True
    except subprocess.TimeoutExpired:
        logger.error("  Timeout fixing %s", path.name)
        tmp_path.unlink(missing_ok=True)
        return False
    except Exception as exc:
        logger.error("  Error fixing %s: %s", path.name, exc)
        tmp_path.unlink(missing_ok=True)
        return False


def main() -> int:
    if not EXPORTS_DIR.is_dir():
        logger.error("Exports directory not found: %s", EXPORTS_DIR)
        return 1

    mp4_files = sorted(EXPORTS_DIR.glob("*.mp4"))
    if not mp4_files:
        logger.info("No .mp4 files found in %s", EXPORTS_DIR)
        return 0

    fixed_count = 0
    ok_count = 0
    error_count = 0

    for path in mp4_files:
        v_dur, a_dur = get_stream_duration(path)

        if v_dur <= 0 or a_dur <= 0:
            logger.warning("SKIP: %s — could not probe streams", path.name)
            error_count += 1
            continue

        diff = abs(v_dur - a_dur)
        if diff > MAX_DIFF_SECONDS:
            if fix_clip(path, v_dur, a_dur):
                fixed_count += 1
            else:
                error_count += 1
        else:
            logger.info("OK: %s (v=%.2fs a=%.2fs diff=%.2fs)", path.name, v_dur, a_dur, diff)
            ok_count += 1

    logger.info(
        "Done: %d OK, %d fixed, %d errors — %d total files",
        ok_count, fixed_count, error_count, len(mp4_files),
    )
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
