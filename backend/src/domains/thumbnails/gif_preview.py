"""
GIF preview generation for clips using FFmpeg palettegen.
"""
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def generate_clip_preview_gif(
    clip_path: Path,
    output_dir: Path,
    clip_id: str,
    duration: float = 3.0,
    start_offset: float = 2.0,
) -> Path | None:
    """
    Genera GIF animado de 3s del momento más destacado del clip.
    Dimensiones: 320px ancho, altura proporcional.
    Tamaño target: < 2MB.
    """
    gif_path = output_dir / f"{clip_id}_preview.gif"
    palette_path = output_dir / f"{clip_id}_palette.png"

    try:
        # Step 1: Generate optimal palette
        cmd_palette = [
            "ffmpeg", "-y",
            "-ss", str(start_offset),
            "-t", str(duration),
            "-i", str(clip_path),
            "-vf", "fps=10,scale=320:-1:flags=lanczos,palettegen=max_colors=64",
            str(palette_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd_palette,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            return None

        # Step 2: Generate GIF with palette
        cmd_gif = [
            "ffmpeg", "-y",
            "-ss", str(start_offset),
            "-t", str(duration),
            "-i", str(clip_path),
            "-i", str(palette_path),
            "-filter_complex",
            "fps=10,scale=320:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer",
            str(gif_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd_gif,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            return None

    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("[GIF] Preview failed for %s: %s", clip_id, exc)
        return None
    finally:
        palette_path.unlink(missing_ok=True)

    if not gif_path.exists():
        return None

    size_mb = gif_path.stat().st_size / 1024 / 1024
    logger.debug("[GIF] Generated preview: %s (%.1fMB)", gif_path.name, size_mb)
    return gif_path
