"""
Hook Reorder — Phase 9.12 Creative Engine

"Hook-flash" technique: when the strongest hook moment is NOT in the first 3s,
prepend a 1-second flash of it to the beginning of the clip so viewers are
immediately engaged.

This follows the pattern used by top TikTok creators:
  [hook flash ~1s] + [original clip in full]

The original clip is left completely intact — the hook moment still appears
at its natural position.  Total duration increases by ~1s.
"""

import asyncio
import logging
from pathlib import Path
from src import gpu_utils

logger = logging.getLogger(__name__)

FLASH_DURATION_S = 1.0       # length of the prepended hook flash
FLASH_PRE_PAD_S  = 0.25      # seconds before the hook word to include
HOOK_WINDOW_S    = 3.0       # hooks inside this window are already optimized


async def prepend_hook_flash(
    clip_path: Path,
    hook_start: float,
    hook_end: float,
    output_path: Path,
) -> "Path | None":
    """
    Prepend a short hook flash to the beginning of a rendered clip.

    Extracts [hook_start - FLASH_PRE_PAD_S : hook_start + FLASH_DURATION_S]
    and concatenates it before the original clip.

    Args:
        clip_path:    Rendered 9:16 clip.
        hook_start:   Start timestamp of the hook word (relative to clip, seconds).
        hook_end:     End timestamp of the hook word.
        output_path:  Destination path for the reordered clip.

    Returns:
        output_path on success, None on error or when reorder is not needed.
    """
    # Safety: hook_start must be beyond the optimized window
    if hook_start <= HOOK_WINDOW_S:
        return None

    flash_start = max(0.0, hook_start - FLASH_PRE_PAD_S)
    flash_end   = flash_start + FLASH_DURATION_S

    # If flash window extends past hook_end, that is fine — we want context
    filter_complex = (
        # Flash segment (video)
        f"[0:v]trim=start={flash_start:.3f}:end={flash_end:.3f},"
        f"setpts=PTS-STARTPTS[vflash];"
        # Flash segment (audio)
        f"[0:a]atrim=start={flash_start:.3f}:end={flash_end:.3f},"
        f"asetpts=PTS-STARTPTS[aflash];"
        # Full original (video)
        f"[0:v]setpts=PTS-STARTPTS[vfull];"
        # Full original (audio)
        f"[0:a]asetpts=PTS-STARTPTS[afull];"
        # Concatenate: flash + full
        f"[vflash][aflash][vfull][afull]concat=n=2:v=1:a=1[vout][aout]"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
            "-i", str(clip_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            *gpu_utils.ffmpeg_codec_flags("high"),
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=300.0)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        output_path.unlink(missing_ok=True)
        return None
    except (asyncio.TimeoutError, Exception) as exc:
        logger.debug("prepend_hook_flash failed: %s", exc)
        output_path.unlink(missing_ok=True)
        return None
