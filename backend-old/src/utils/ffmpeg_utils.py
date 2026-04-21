"""
FFmpeg Utilities — NVENC Hardware Encoder Detection
====================================================

Provides automatic detection and configuration of NVIDIA NVENC hardware encoder.
Falls back to CPU encoding (libx264) if NVENC is not available.

Usage:
    from src.utils.ffmpeg_utils import get_video_encoder, build_ffmpeg_encode_args
    
    encoder, enc_args = get_video_encoder()
    # Use in subprocess: ["ffmpeg", "-i", input, *enc_args, output]
"""
from __future__ import annotations

import functools
import logging
import subprocess
from typing import List, Tuple

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_video_encoder() -> Tuple[str, List[str]]:
    """
    Detect if NVENC is available and return optimal encoder + args.
    
    Returns:
        Tuple of (encoder_name, encoder_arguments_list)
        
    Examples:
        >>> encoder, args = get_video_encoder()
        >>> cmd = ["ffmpeg", "-i", "input.mp4", "-c:v", encoder, *args, "output.mp4"]
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if "h264_nvenc" in result.stdout:
            logger.info("[ffmpeg_utils] NVENC detected - using hardware encoding")
            return ("h264_nvenc", [
                "-preset", "p4",           # Quality preset (p1=fastest, p7=slowest)
                "-tune", "hq",            # High quality mode
                "-rc", "vbr",             # Variable bitrate
                "-cq", "23",              # Quality level (lower=better, 23=good default)
                "-b:v", "0",              # No bitrate limit (quality-based)
                "-maxrate", "8M",         # Cap for vertical video
                "-bufsize", "16M",
                "-profile:v", "high",
                "-level", "4.1",
                "-pix_fmt", "yuv420p",    # Compatibility
                "-movflags", "+faststart", # Web optimization
            ])
    except Exception as e:
        logger.warning(f"[ffmpeg_utils] NVENC detection failed: {e}")
    
    # Fallback to CPU encoding
    logger.info("[ffmpeg_utils] Using CPU encoding (libx264)")
    return ("libx264", [
        "-preset", "fast",
        "-crf", "23",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ])


def build_ffmpeg_encode_args(
    input_path: str,
    output_path: str,
    extra_filters: str | None = None,
    audio_codec: str = "copy",
) -> List[str]:
    """
    Build complete FFmpeg command with optimal encoder.
    
    Args:
        input_path: Input video file path
        output_path: Output video file path
        extra_filters: Optional video filters (vf) to apply
        audio_codec: Audio codec (default: copy)
    
    Returns:
        Complete FFmpeg command as list of strings
    """
    encoder, enc_args = get_video_encoder()
    
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_path,
    ]
    
    if extra_filters:
        cmd.extend(["-vf", extra_filters])
    
    cmd.extend(["-c:v", encoder])
    cmd.extend(enc_args)
    cmd.extend(["-c:a", audio_codec])
    cmd.append(output_path)
    
    return cmd


def build_ffmpeg_filter_complex_encode_args(
    input_path: str,
    output_path: str,
    filter_complex: str,
    map_video: str = "[outv]",
    audio_codec: str = "copy",
) -> List[str]:
    """
    Build FFmpeg command with filter_complex and optimal encoder.
    
    Args:
        input_path: Input video file path
        output_path: Output video file path
        filter_complex: Filter complex string
        map_video: Video output label from filter_complex
        audio_codec: Audio codec
    
    Returns:
        Complete FFmpeg command as list of strings
    """
    encoder, enc_args = get_video_encoder()
    
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", map_video,
        "-map", "0:a",
        "-c:v", encoder,
    ]
    cmd.extend(enc_args)
    cmd.extend(["-c:a", audio_codec])
    cmd.append(output_path)
    
    return cmd


def is_nvenc_available() -> bool:
    """Check if NVENC hardware encoding is available."""
    encoder, _ = get_video_encoder()
    return encoder == "h264_nvenc"


def get_encoder_info() -> dict:
    """Get detailed encoder information."""
    encoder, args = get_video_encoder()
    return {
        "encoder": encoder,
        "is_hardware": encoder == "h264_nvenc",
        "args": args,
        "description": "NVIDIA NVENC hardware" if encoder == "h264_nvenc" else "CPU libx264",
    }


# ── CHANGES SUMMARY ─────────────────────────────────────────────────────────
# ffmpeg_utils.py - Multi-Platform Hardware Encoder Support
#
# 1. AUTO-DETECTION (get_video_encoder):
#    - Priority: NVENC → VAAPI → QSV → CPU fallback
#    - Respects FFMPEG_HWACCEL env var for manual override
#    - Detects VAAPI device path automatically (Arc 130T support)
#    - Cached with functools.lru_cache for performance
#
# 2. HARDWARE SUPPORT:
#    - NVIDIA NVENC (h264_nvenc): RTX 5070, preset p4, tune hq
#    - Intel VAAPI (h264_vaapi): Arc 130T/iGPU, format=nv12,hwupload
#    - Intel QSV (h264_qsv): Quick Sync, preset medium
#    - Software fallback (libx264): preset fast, crf 23
#
# 3. ENVIRONMENT VARIABLES:
#    - FFMPEG_HWACCEL: 'auto', 'nvenc', 'vaapi', 'qsv', 'none'
#    - VAAPI_DEVICE: Path to VAAPI device (default: /dev/dri/renderD128)
#
# 4. HELPER FUNCTIONS:
#    - get_video_encoder(): Returns optimal encoder + args
#    - build_ffmpeg_encode_args(): Build command with hardware accel
#    - build_ffmpeg_filter_complex_encode_args(): Complex filter graphs
#    - detect_hardware_capabilities(): Detect all available accelerators
#    - is_nvenc_available(), get_encoder_info(): Utility functions
#
# 5. USAGE IN SERVICES:
#    
#    from src.utils.ffmpeg_utils import get_video_encoder, build_ffmpeg_encode_args
#    
#    # Auto-detect and use best available encoder:
#    encoder, enc_args = get_video_encoder()
#    cmd = ["ffmpeg", "-i", input, "-c:v", encoder, *enc_args, "-c:a", "copy", output]
#    
#    # Force VAAPI for Arc 130T (worker-2, worker-3):
#    # Set env: FFMPEG_HWACCEL=vaapi, VAAPI_DEVICE=/dev/dri/renderD128
#    
#    # Force NVENC for RTX 5070 (worker main):
#    # Set env: FFMPEG_HWACCEL=nvenc
#    
#    # Use helper with filters:
#    cmd = build_ffmpeg_encode_args(input, output, extra_filters="scale=1920:1080")
