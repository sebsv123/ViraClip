"""
GPU detection and optimal encoding settings — delegates to gpu_utils.py.

This module is kept for backward compatibility. All GPU detection logic
now lives in gpu_utils.py (the single source of truth). This module
re-exports the relevant functions and settings from gpu_utils.py.
"""

import logging
from typing import Dict, Any, Tuple
from enum import Enum

from gpu_utils import (
    cuda_available,
    nvenc_available,
    gpu_name,
    get_video_encoder,
    get_ffmpeg_video_codec_args,
    ffmpeg_codec_flags,
)

logger = logging.getLogger(__name__)


class GPUType(Enum):
    """Available GPU acceleration types."""
    NVIDIA_NVENC = "nvidia_nvenc"
    AMD_VCE = "amd_vce"
    INTEL_QSV = "intel_qsv"
    CPU_ONLY = "cpu_only"


def detect_gpu() -> Tuple[GPUType, Dict[str, Any]]:
    """
    Detect available GPU and return optimal encoding settings.
    
    Delegates to gpu_utils.get_ffmpeg_video_codec_args() for the actual
    detection. Returns a (GPUType, settings_dict) tuple for backward
    compatibility with callers that expect this signature.
    """
    enc = get_ffmpeg_video_codec_args("high")
    codec = enc["codec"]

    if codec == "h264_nvenc":
        logger.info("✓ GPU detected: nvidia_nvenc (via gpu_utils)")
        return (GPUType.NVIDIA_NVENC, {
            "codec": "h264_nvenc",
            "preset": enc.get("preset", "p4"),
            "audio_codec": "aac",
            "audio_bitrate": "192k",
            "ffmpeg_params": enc.get("extra_args", []),
        })
    elif codec in ("h264_amf", "hevc_amf"):
        logger.info("✓ GPU detected: amd_vce (via gpu_utils)")
        return (GPUType.AMD_VCE, enc)
    elif codec in ("h264_qsv", "hevc_qsv"):
        logger.info("✓ GPU detected: intel_qsv (via gpu_utils)")
        return (GPUType.INTEL_QSV, enc)
    else:
        logger.info("⚠️ No GPU detected, using CPU encoding (slower)")
        return (GPUType.CPU_ONLY, {
            "codec": get_video_encoder(),
            "preset": "medium",
            "audio_codec": "aac",
            "audio_bitrate": "192k",
            "ffmpeg_params": [
                "-crf", "23",
                "-profile:v", "high",
                "-movflags", "+faststart",
            ],
        })


def get_optimal_render_concurrency() -> int:
    """
    Return optimal number of concurrent renders based on GPU.
    
    Delegates to gpu_utils for detection.
    """
    gpu_type, _ = detect_gpu()
    
    if gpu_type == GPUType.NVIDIA_NVENC:
        return 4  # NVENC can handle multiple streams well
    elif gpu_type in (GPUType.AMD_VCE, GPUType.INTEL_QSV):
        return 3  # Conservative for AMD/Intel
    else:
        return 2  # CPU fallback, don't overload
