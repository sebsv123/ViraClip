"""
Audio Denoiser — voice isolation + noise reduction using FFmpeg filters.

Uses FFmpeg's afftdn (Adaptive FFT Denoiser) and highpass/lowpass filters
to clean speech before captioning. Optionally applies loudness normalization.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


@dataclass
class DenoiseResult:
    output_path: str
    noise_reduction_applied: bool
    voice_isolation_applied: bool
    loudnorm_applied: bool
    original_lufs: Optional[float] = None
    output_lufs: Optional[float] = None
    error: Optional[str] = None


async def _measure_lufs(audio_path: str) -> Optional[float]:
    """Measure integrated loudness (LUFS) via FFmpeg loudnorm."""
    cmd = [
        _get_ffmpeg_exe(), "-v", "quiet",
        "-i", audio_path,
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        import json, re
        m = re.search(r'\{[^{}]+\}', stderr.decode(), re.DOTALL)
        if m:
            data = json.loads(m.group())
            return float(data.get("input_i", -99))
    except Exception:
        pass
    return None


async def denoise_audio(
    input_path: str,
    output_path: str,
    noise_reduction: bool = True,
    voice_isolation: bool = True,
    loudnorm_target_lufs: float = -14.0,
    apply_loudnorm: bool = True,
) -> DenoiseResult:
    """
    Denoise audio track from a video file and produce a cleaned video.

    Applies:
    - afftdn: adaptive FFT denoiser (removes broadband noise)
    - highpass=f=80: remove low-frequency rumble
    - lowpass=f=8000: remove high-frequency hiss  
    - loudnorm: EBU R128 integrated loudness normalization

    Args:
        input_path: Source video or audio file
        output_path: Destination file (video if input is video)
        noise_reduction: Apply afftdn + high/lowpass filters
        voice_isolation: Apply bandpass optimised for speech (80-8000 Hz)
        loudnorm_target_lufs: Target LUFS for normalization
        apply_loudnorm: Whether to normalize loudness
    """
    original_lufs = await _measure_lufs(input_path)

    filters: list[str] = []

    if noise_reduction:
        # afftdn: adaptive FFT-based noise reduction
        filters.append("afftdn=nf=-25:nt=w:om=o")

    if voice_isolation:
        # Focus on speech frequency range
        filters.append("highpass=f=80")
        filters.append("lowpass=f=8000")
        # Light dynamic compression for voice clarity
        filters.append("acompressor=threshold=-18dB:ratio=3:attack=5:release=50")

    if apply_loudnorm:
        filters.append(
            f"loudnorm=I={loudnorm_target_lufs}:TP=-1.5:LRA=11:print_format=none"
        )

    if not filters:
        # Nothing to apply — copy
        import shutil
        shutil.copy2(input_path, output_path)
        return DenoiseResult(
            output_path=output_path,
            noise_reduction_applied=False,
            voice_isolation_applied=False,
            loudnorm_applied=False,
            original_lufs=original_lufs,
        )

    filter_str = ",".join(filters)

    # Detect if input has video stream
    probe_cmd = [
        _get_ffmpeg_exe(), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    has_video = stdout.decode().strip() == "video"

    if has_video:
        cmd = [
            _get_ffmpeg_exe(), "-y", "-i", input_path,
            "-af", filter_str,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]
    else:
        cmd = [
            _get_ffmpeg_exe(), "-y", "-i", input_path,
            "-af", filter_str,
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode()[-400:]
            logger.error("[denoiser] FFmpeg error: %s", err)
            return DenoiseResult(
                output_path=output_path,
                noise_reduction_applied=False,
                voice_isolation_applied=False,
                loudnorm_applied=False,
                original_lufs=original_lufs,
                error=err,
            )
    except Exception as exc:
        return DenoiseResult(
            output_path=output_path,
            noise_reduction_applied=False,
            voice_isolation_applied=False,
            loudnorm_applied=False,
            original_lufs=original_lufs,
            error=str(exc),
        )

    output_lufs = await _measure_lufs(output_path)
    logger.info(
        "[denoiser] %s → cleaned (%.1f → %.1f LUFS, nr=%s vi=%s)",
        Path(input_path).name,
        original_lufs or -99, output_lufs or -99,
        noise_reduction, voice_isolation,
    )

    return DenoiseResult(
        output_path=output_path,
        noise_reduction_applied=noise_reduction,
        voice_isolation_applied=voice_isolation,
        loudnorm_applied=apply_loudnorm,
        original_lufs=original_lufs,
        output_lufs=output_lufs,
    )
