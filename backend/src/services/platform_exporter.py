"""
Platform export engine with adaptive bitrate and profile validation.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

from src import gpu_utils

from ..core.platform_profiles import get_profile

logger = logging.getLogger(__name__)



async def _get_clip_duration(clip_path: Path) -> dict:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", str(clip_path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        data = json.loads(stdout)
        return {"duration": float(data["format"]["duration"])}
    except Exception:
        return {"duration": 30.0}


async def export_for_platform(
    clip_path: Path,
    platform: str,
    output_dir: Path,
    clip_id: str,
    use_gpu: bool = True,
) -> dict:
    """Re-export clip with optimal parameters for target platform."""
    profile = get_profile(platform)
    suffix = platform.lower()
    out_path = output_dir / f"{clip_id}_{suffix}.mp4"

    encoder = gpu_utils.get_video_encoder()
    preset = "p4" if encoder == "h264_nvenc" else "medium"

    clip_info = await _get_clip_duration(clip_path)
    duration_s = clip_info.get("duration", 30.0)

    # Adaptive bitrate
    estimated_mb = (
        (int(profile.video_bitrate[:-1]) + int(profile.audio_bitrate[:-1])) / 8
        * duration_s / 1024
    )
    video_bitrate = profile.video_bitrate
    if estimated_mb > profile.max_size_mb * 0.9:
        target_total_kbps = int(profile.max_size_mb * 0.9 * 8 * 1024 / duration_s)
        audio_kbps = int(profile.audio_bitrate[:-1])
        video_kbps = max(1000, target_total_kbps - audio_kbps)
        video_bitrate = f"{video_kbps}k"
        logger.info(
            "[Export] Adaptive bitrate: %s → %s (%.1fMB > %.1fMB limit)",
            profile.video_bitrate, video_bitrate, estimated_mb, profile.max_size_mb,
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-vf", f"scale={profile.width}:{profile.height}:"
               f"force_original_aspect_ratio=decrease,"
               f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,"
               f"fps={profile.fps}",
        "-c:v", encoder, "-preset", preset,
        "-b:v", video_bitrate,
        "-maxrate", video_bitrate,
        "-bufsize", f"{int(video_bitrate[:-1]) * 2}k",
        "-c:a", "aac", "-b:a", profile.audio_bitrate,
        "-ar", str(profile.audio_rate),
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
    except asyncio.TimeoutError:
        logger.error("[Export] Timeout for %s", platform)
        return {"success": False, "error": "timeout"}

    if proc.returncode != 0:
        return {"success": False, "error": stderr.decode()[-300:]}

    final_mb = out_path.stat().st_size / 1024 / 1024
    return {
        "success": True,
        "path": str(out_path),
        "size_mb": round(final_mb, 2),
        "platform": platform,
        "profile": profile.name,
        "within_limit": final_mb <= profile.max_size_mb,
    }
