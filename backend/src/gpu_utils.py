"""
gpu_utils.py — Central GPU capability detection for ViraClip.

Import this module anywhere to get encoding settings and CUDA availability.
Results are cached at module load time — detection runs only once per process.
"""
import logging
import subprocess
from functools import lru_cache
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def cuda_available() -> bool:
    """True if PyTorch detects a CUDA-capable GPU."""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """True if FFmpeg in PATH supports h264_nvenc encoder."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        return "h264_nvenc" in result.stdout
    except Exception:
        return False


@lru_cache(maxsize=1)
def gpu_name() -> str:
    """Return GPU name string, or 'CPU' if none detected."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return "CPU"


@lru_cache(maxsize=1)
def onnx_providers() -> List[str]:
    """Return best available ONNX Runtime execution providers."""
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
    Return FFmpeg video encoding arguments optimised for available hardware.

    GPU path  : h264_nvenc — 5-8x faster than libx264 on NVIDIA GPU.
    CPU path  : libx264 ultrafast — safe fallback.

    Returns a dict with keys: codec, preset, extra_args (list of extra ffmpeg flags).
    """
    use_nvenc = nvenc_available() and cuda_available()

    if use_nvenc:
        logger.info(f"[GPU] Using h264_nvenc encoder ({gpu_name()})")
        if quality == "high":
            return {
                "codec": "h264_nvenc",
                "preset": "p4",          # nvenc preset: p1(fast)..p7(slow), p4=balanced
                "extra_args": [
                    "-rc", "vbr",
                    "-cq", "22",          # constant quality, equivalent to CRF 22
                    "-b:v", "0",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.0",
                    "-b:a", "256k",
                    "-ar", "48000",
                ],
            }
        else:  # medium
            return {
                "codec": "h264_nvenc",
                "preset": "p3",
                "extra_args": [
                    "-rc", "vbr",
                    "-cq", "24",
                    "-b:v", "0",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.0",
                    "-b:a", "192k",
                    "-ar", "48000",
                ],
            }
    else:
        logger.info("[GPU] h264_nvenc unavailable — using libx264 CPU encoder")
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
    Convenience: return flat list of FFmpeg flags for use in subprocess calls.
    e.g. [..., "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "22", ...]
    """
    enc = get_ffmpeg_video_codec_args(quality)
    flags = ["-c:v", enc["codec"], "-preset", enc["preset"]] + enc["extra_args"]
    return flags
