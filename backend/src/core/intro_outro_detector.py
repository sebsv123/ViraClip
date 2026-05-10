"""
Intro/outro detector — excludes intro/outro from scoring and segmentation.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

INTRO_MAX_S = float(os.getenv("INTRO_MAX_S", "60"))
OUTRO_MAX_S = float(os.getenv("OUTRO_MAX_S", "30"))
ENERGY_LOW_DB = float(os.getenv("INTRO_ENERGY_LOW_DB", "-25"))


async def _find_content_start(video_path: str) -> float:
    """Find where intro ends — first silence_end after low energy."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-t", str(INTRO_MAX_S),
        "-af", f"silencedetect=noise={ENERGY_LOW_DB}dB:d=2,astats=metadata=1:reset=1",
        "-f", "null", "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except asyncio.TimeoutError:
        return 0.0

    output = stderr.decode("utf-8", errors="replace")
    for line in output.splitlines():
        if "silence_end:" in line:
            try:
                end = float(line.split("silence_end:")[-1].split("|")[0].strip())
                if end <= INTRO_MAX_S:
                    return end
            except ValueError:
                pass
    return 0.0


async def _find_content_end(video_path: str, total_duration: float) -> float:
    """Find where outro starts — first silence in last OUTRO_MAX_S."""
    outro_start = max(0, total_duration - OUTRO_MAX_S)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(outro_start),
        "-i", video_path,
        "-af", f"silencedetect=noise={ENERGY_LOW_DB}dB:d=1.5",
        "-f", "null", "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except asyncio.TimeoutError:
        return total_duration

    output = stderr.decode("utf-8", errors="replace")
    for line in output.splitlines():
        if "silence_start:" in line:
            try:
                rel_start = float(line.split("silence_start:")[-1].strip())
                abs_start = outro_start + rel_start
                if abs_start > total_duration * 0.7:
                    return abs_start
            except ValueError:
                pass
    return total_duration


async def detect_intro_outro(
    video_path: str,
    total_duration_s: float,
) -> dict:
    """Detect intro and outro. Returns content boundaries."""
    try:
        intro_end_s = await _find_content_start(video_path)
        outro_start_s = await _find_content_end(video_path, total_duration_s)

        # Sanity: no more than 20% of video
        if intro_end_s > total_duration_s * 0.2:
            intro_end_s = 0.0
        if outro_start_s < total_duration_s * 0.8:
            outro_start_s = total_duration_s

        if intro_end_s > 0:
            logger.info("[IntroOutro] Intro: 0–%.1fs", intro_end_s)
        if outro_start_s < total_duration_s:
            logger.info("[IntroOutro] Outro: %.1f–%.1fs", outro_start_s, total_duration_s)

        return {
            "intro_end_s": intro_end_s,
            "outro_start_s": outro_start_s,
            "content_start_s": intro_end_s,
            "content_end_s": outro_start_s,
            "excluded_s": intro_end_s + (total_duration_s - outro_start_s),
        }
    except Exception as exc:
        logger.warning("[IntroOutro] Failed: %s", exc)
        return {
            "intro_end_s": 0.0, "outro_start_s": total_duration_s,
            "content_start_s": 0.0, "content_end_s": total_duration_s,
            "excluded_s": 0.0,
        }
