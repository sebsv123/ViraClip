"""
SFX Mixer — applies sound effects to video clips via FFmpeg adelay + amix.
"""
import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


async def apply_sfx(
    input_video: str,
    sfx_plan: List[Dict],
    output_path: str,
) -> str:
    """
    Apply sound effects to a video clip using FFmpeg filter_complex.

    Each SFX is delayed (adelay), volume-adjusted, and mixed (amix)
    with the original audio. Falls back to input_video on any error.
    """
    if not sfx_plan:
        return input_video

    # Filter out SFX without valid local paths
    valid_sfx = [s for s in sfx_plan if s.get("local_path") and Path(s["local_path"]).exists()]
    if not valid_sfx:
        logger.info("[SFX-Mixer] No valid SFX files to apply")
        return input_video

    inputs = ["-i", input_video]
    filter_parts: List[str] = []
    mix_labels: List[str] = ["[0:a]"]

    for i, sfx in enumerate(valid_sfx):
        sfx_path = sfx["local_path"]
        delay_ms = int(sfx.get("time_offset", 0) * 1000)
        vol_db = sfx.get("volume_db", -18)
        fade_ms = sfx.get("fade_out_ms", 300)
        duration = sfx.get("duration", 1.0)

        inputs += ["-i", sfx_path]
        label = f"[sfx{i}]"

        # adelay + volume + afade out
        filter_parts.append(
            f"[{i+1}:a]adelay={delay_ms}|{delay_ms},"
            f"volume={vol_db}dB,"
            f"afade=t=out:st={sfx['time_offset']+duration-0.3}:d={fade_ms/1000}"
            f"{label}"
        )
        mix_labels.append(label)

    n_inputs = len(mix_labels)
    mix_labels_str = "".join(mix_labels)
    filter_complex = (
        ";".join(filter_parts) + ";"
        f"{mix_labels_str}amix=inputs={n_inputs}:"
        f"duration=first:dropout_transition=0,"
        f"aresample=async=1000[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode == 0 and Path(output_path).exists():
            logger.info(f"[SFX-Mixer] ✅ {len(valid_sfx)} SFX applied → {Path(output_path).name}")
            return output_path
        else:
            logger.error(f"[SFX-Mixer] FFmpeg error: {stderr.decode()[:300]}")
            return input_video

    except asyncio.TimeoutError:
        logger.error("[SFX-Mixer] Timeout")
        return input_video
    except Exception as e:
        logger.error(f"[SFX-Mixer] Error: {e}")
        return input_video
