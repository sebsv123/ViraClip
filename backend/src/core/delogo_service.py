"""
Automatic watermark removal using FFmpeg delogo filter.
"""
import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

KNOWN_WATERMARKS = {
    "tiktok_br": {
        "x": 780, "y": 1780, "w": 280, "h": 120,
        "description": "TikTok @username bottom-right",
    },
    "tiktok_bc": {
        "x": 420, "y": 1820, "w": 240, "h": 80,
        "description": "TikTok center-bottom logo",
    },
    "instagram_br": {
        "x": 900, "y": 1840, "w": 160, "h": 60,
        "description": "Instagram Reels bottom-right",
    },
    "youtube_br": {
        "x": 900, "y": 30, "w": 160, "h": 40,
        "description": "YouTube top-right logo",
    },
}

DELOGO_ENABLED = os.getenv("DELOGO_ENABLED", "false").lower() == "true"
DELOGO_TARGETS = [t.strip() for t in os.getenv("DELOGO_TARGETS", "tiktok_br,tiktok_bc").split(",")]


def _gpu_available() -> bool:
    return bool(os.getenv("CUDA_VISIBLE_DEVICES", ""))


async def build_delogo_filter(targets: list[str]) -> str | None:
    """Build FFmpeg delogo filter string for given targets."""
    filters = []
    for target in targets:
        wm = KNOWN_WATERMARKS.get(target)
        if wm:
            filters.append(
                f"delogo=x={wm['x']}:y={wm['y']}:w={wm['w']}:h={wm['h']}:show=0"
            )
    return ",".join(filters) if filters else None


async def remove_watermarks(
    input_path: Path,
    output_path: Path,
    targets: list[str] | None = None,
) -> bool:
    """Apply delogo filter to remove known watermarks."""
    if not DELOGO_ENABLED:
        return False

    effective_targets = targets or DELOGO_TARGETS
    vf = await build_delogo_filter(effective_targets)
    if not vf:
        logger.warning("[Delogo] No valid targets: %s", effective_targets)
        return False

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "h264_nvenc" if _gpu_available() else "libx264",
        "-crf", "20", "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=180.0)
        ok = proc.returncode == 0 and output_path.exists()
        if ok:
            logger.info("[Delogo] Removed %s from %s", effective_targets, input_path.name)
        return ok
    except Exception as exc:
        logger.warning("[Delogo] Failed: %s", exc)
        return False


async def _zone_has_non_black_content(
    video_path: Path, x: int, y: int, w: int, h: int,
) -> bool:
    """Check if a zone in the first frame has visible content."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-frames:v", "1",
            "-vf", f"crop={w}:{h}:{x}:{y}",
            "-f", "rawvideo", "-pix_fmt", "gray",
            "pipe:1",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        if stdout:
            avg = sum(stdout) / len(stdout)
            return avg > 30
    except Exception:
        pass
    return False


async def auto_detect_and_remove(input_path: Path, output_path: Path) -> dict:
    """Auto-detect watermarks and remove them."""
    detected = []
    for target_name, coords in KNOWN_WATERMARKS.items():
        has_content = await _zone_has_non_black_content(
            input_path, coords["x"], coords["y"], coords["w"], coords["h"],
        )
        if has_content:
            detected.append(target_name)
            logger.info("[Delogo] Detected: %s", target_name)

    if not detected:
        return {"detected": [], "removed": False}

    ok = await remove_watermarks(input_path, output_path, detected)
    return {"detected": detected, "removed": ok}
