"""
Thumbnail candidate generator — 3 types: expressive, sharp, representative.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

THUMB_CANDIDATES = int(os.getenv("THUMB_CANDIDATES", "3"))
THUMB_W = 1080
THUMB_H = 1920


async def _get_duration(path: Path) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", str(path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return float(json.loads(stdout)["format"]["duration"])
    except Exception:
        return 60.0


async def _extract_frame_as_thumbnail(
    clip_path: Path, offset: float, output_path: Path,
) -> bool:
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(offset),
            "-i", str(clip_path),
            "-frames:v", "1",
            "-vf", f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=decrease,"
                   f"pad={THUMB_W}:{THUMB_H}:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "2", str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return output_path.exists() and output_path.stat().st_size > 5000
    except Exception:
        return False


async def _find_expressive_frame(clip_path: Path, duration: float) -> float:
    """Sample 12 frames, return offset with highest visual energy."""
    sample_count = 12
    offsets = [duration * i / sample_count for i in range(1, sample_count)]
    best_offset = duration * 0.3
    best_score = 0.0

    for offset in offsets:
        tmp = Path(f"/tmp/viraclip_th_{os.getpid()}_{int(offset*10)}.jpg")
        try:
            cmd = [
                "ffmpeg", "-y", "-ss", str(offset),
                "-i", str(clip_path), "-frames:v", "1",
                "-vf", "scale=270:480", str(tmp),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if tmp.exists() and tmp.stat().st_size > 8000:
                score = tmp.stat().st_size / 1000.0
                if score > best_score:
                    best_score = score
                    best_offset = offset
        except Exception:
            pass
        finally:
            tmp.unlink(missing_ok=True)

    return best_offset


async def _find_sharpest_frame(clip_path: Path, duration: float) -> float:
    """Return frame at 25% of clip (heuristic for less motion)."""
    return duration * 0.25


async def generate_thumbnail_candidates(
    clip_path: Path,
    clip_id: str,
    output_dir: Path,
) -> list[dict]:
    """Generate 3 thumbnail candidates: expressive, sharp, representative."""
    duration = await _get_duration(clip_path)
    if duration < 0.5:
        return []

    expressive_offset = await _find_expressive_frame(clip_path, duration)
    sharp_offset = await _find_sharpest_frame(clip_path, duration)
    representative_offset = duration * 0.4

    candidates = [
        ("expressive", expressive_offset, "Más expresivo"),
        ("sharp", sharp_offset, "Más nítido"),
        ("representative", representative_offset, "Más representativo"),
    ]

    results = []
    for ctype, offset, label in candidates:
        thumb_path = output_dir / f"{clip_id}_thumb_{ctype}.jpg"
        ok = await _extract_frame_as_thumbnail(clip_path, offset, thumb_path)
        if ok:
            results.append({
                "type": ctype,
                "label": label,
                "path": str(thumb_path),
                "offset_s": round(offset, 2),
                "url": f"/clips/{clip_id}/thumbnails/{ctype}",
            })

    logger.info("[Thumb] Generated %d candidates for clip %s", len(results), clip_id)
    return results
