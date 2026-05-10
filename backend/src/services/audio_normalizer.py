"""
Audio loudness measurement and normalization (EBU R128).
"""
import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_LUFS = float(os.getenv("AUDIO_TARGET_LUFS", "-14"))
MUTE_THRESHOLD = float(os.getenv("AUDIO_MUTE_THRESHOLD_DB", "-40"))


async def measure_audio_loudness(clip_path: Path) -> dict:
    """Measure loudness using FFmpeg loudnorm (EBU R128)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError:
        return {"is_muted": False, "needs_normalization": False}

    output = stderr.decode("utf-8", errors="replace")
    try:
        json_start = output.rfind("{")
        json_end = output.rfind("}") + 1
        if json_start >= 0:
            data = json.loads(output[json_start:json_end])
            input_i = float(data.get("input_i", -99))
            input_tp = float(data.get("input_tp", -99))
            is_muted = input_i < MUTE_THRESHOLD
            needs_norm = abs(input_i - TARGET_LUFS) > 3.0 and not is_muted
            return {
                "integrated_lufs": input_i,
                "true_peak_db": input_tp,
                "is_muted": is_muted,
                "needs_normalization": needs_norm,
                "loudnorm_data": data,
            }
    except Exception:
        pass
    return {"is_muted": False, "needs_normalization": False}


async def normalize_audio(
    clip_path: Path,
    output_path: Path,
    loudnorm_data: dict | None = None,
) -> bool:
    """Normalize audio to TARGET_LUFS using two-pass loudnorm."""
    try:
        if loudnorm_data:
            measured = (
                f"measured_I={loudnorm_data.get('input_i', -23)}:"
                f"measured_TP={loudnorm_data.get('input_tp', -2)}:"
                f"measured_LRA={loudnorm_data.get('input_lra', 7)}:"
                f"measured_thresh={loudnorm_data.get('input_thresh', -33)}"
            )
            af = f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:{measured}:linear=true:print_format=none"
        else:
            af = f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:print_format=none"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-af", af,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120.0)
        ok = output_path.exists() and output_path.stat().st_size > 0
        if ok:
            logger.info("[Audio] Normalized %s → %s LUFS", clip_path.name, TARGET_LUFS)
        return ok
    except Exception as exc:
        logger.warning("[Audio] Normalization failed: %s", exc)
        return False
