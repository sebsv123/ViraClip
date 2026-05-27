"""
gpu_utils.py — DEPRECATED wrapper.  Use ``src.utils.gpu_utils`` instead.

This module re-exports everything from the canonical ``src.utils.gpu_utils``
and adds backward-compatible aliases for functions that were removed during
the consolidation.

DEPRECATED — will be removed in a future release.
"""
import logging
import os
import subprocess
import warnings
from functools import lru_cache
from typing import Any, Dict, List

from src.utils.gpu_utils import (
    gpu_device_name,
    is_ffmpeg_nvenc_runtime_available,
    is_torch_cuda_available,
    log_gpu_status,
)

logger = logging.getLogger(__name__)

warnings.warn(
    "src.gpu_utils is deprecated; use src.utils.gpu_utils instead.",
    DeprecationWarning,
    stacklevel=2,
)


# ── Re-exported aliases ─────────────────────────────────────────────────────────

def _env_true(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def cuda_available() -> bool:
    """DEPRECATED — use ``src.utils.gpu_utils.is_torch_cuda_available``."""
    return is_torch_cuda_available()


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """DEPRECATED — check ``VIRACLIP_ENABLE_NVENC`` + runtime probe directly."""
    if _env_true("VIRACLIP_BETA_CLEAN", "false"):
        return False
    if not _env_true("VIRACLIP_ENABLE_NVENC", "false"):
        return False
    return is_ffmpeg_nvenc_runtime_available()


def gpu_name() -> str:
    """DEPRECATED — use ``gpu_device_name``."""
    return gpu_device_name()


@lru_cache(maxsize=1)
def onnx_providers() -> List[str]:
    """DEPRECATED — ONNX provider selection is now handled by the caller."""
    providers: List[str] = []
    if cuda_available():
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()
            if "CUDAExecutionProvider" in available:
                providers.append("CUDAExecutionProvider")
                logger.info("[GPU] ONNX using CUDAExecutionProvider")
        except Exception:
            pass
    providers.append("CPUExecutionProvider")
    return providers


def get_ffmpeg_video_codec_args(quality: str = "high") -> Dict[str, Any]:
    """
    DEPRECATED — encoding args are now selected by the caller based on flags.
    """
    use_nvenc = nvenc_available()

    if use_nvenc:
        logger.info("[gpu] using h264_nvenc encoder (%s)", gpu_name())
        if quality == "high":
            return {
                "codec": "h264_nvenc",
                "preset": "p4",
                "extra_args": [
                    "-qp", "22",
                    "-b:v", "0",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.0",
                    "-b:a", "256k",
                    "-ar", "48000",
                ],
            }
        else:
            return {
                "codec": "h264_nvenc",
                "preset": "p3",
                "extra_args": [
                    "-qp", "24",
                    "-b:v", "0",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.0",
                    "-b:a", "192k",
                    "-ar", "48000",
                ],
            }
    else:
        logger.info("[gpu] using libx264 encoder")
        if quality == "high":
            return {
                "codec": "libx264",
                "preset": "ultrafast",
                "extra_args": [
                    "-crf", "22",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.0",
                    "-b:a", "256k",
                    "-ar", "48000",
                ],
            }
        else:
            return {
                "codec": "libx264",
                "preset": "ultrafast",
                "extra_args": [
                    "-crf", "24",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.0",
                    "-b:a", "192k",
                    "-ar", "48000",
                ],
            }


def ffmpeg_codec_flags(quality: str = "high") -> List[str]:
    """
    DEPRECATED — convenience wrapper around ``get_ffmpeg_video_codec_args``.
    """
    enc = get_ffmpeg_video_codec_args(quality)
    flags = ["-c:v", enc["codec"], "-preset", enc["preset"]] + enc["extra_args"]
    return flags
