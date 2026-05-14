"""
Aspect ratio variants for clips — renders 1:1 and 16:9 from the 9:16 master.
"""
import asyncio
import json
import logging
import os
from enum import Enum
from pathlib import Path

from src import gpu_utils

logger = logging.getLogger(__name__)


class AspectRatio(str, Enum):
    VERTICAL  = "9:16"
    SQUARE    = "1:1"
    LANDSCAPE = "16:9"


RATIO_SPECS = {
    AspectRatio.VERTICAL:  {"w": 1080, "h": 1920, "vf": "crop=ih*9/16:ih,scale=1080:1920"},
    AspectRatio.SQUARE:    {"w": 1080, "h": 1080, "vf": "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080"},
    AspectRatio.LANDSCAPE: {"w": 1920, "h": 1080, "vf": "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"},
}



async def render_aspect_variant(
    source_clip_path: Path,
    ratio: AspectRatio,
    output_dir: Path,
    clip_id: str,
) -> Path | None:
    """Generate aspect ratio variant from the 9:16 master clip."""
    spec = RATIO_SPECS[ratio]
    suffix = ratio.value.replace(":", "x")
    output_path = output_dir / f"{clip_id}_{suffix}.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(source_clip_path),
        "-vf", spec["vf"],
        *gpu_utils.ffmpeg_codec_flags("high"),
        "-crf", "23", "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120.0)
        if proc.returncode == 0 and output_path.exists():
            logger.info("[Variant] %s rendered: %s", ratio.value, output_path.name)
            return output_path
    except Exception as exc:
        logger.warning("[Variant] %s render failed: %s", ratio.value, exc)
    return None
