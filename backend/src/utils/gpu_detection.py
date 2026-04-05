"""
GPU detection and optimal encoding settings.

Detects available GPU and provides optimal ffmpeg/MoviePy encoding settings.
Supports NVIDIA NVENC, AMD VCE, Intel Quick Sync.
"""

import logging
import subprocess
from typing import Dict, Any, Optional, Tuple
from enum import Enum

try:
    import torch
except ImportError:
    torch = None  # type: ignore

logger = logging.getLogger(__name__)


class GPUType(Enum):
    """Available GPU acceleration types."""
    NVIDIA_NVENC = "nvidia_nvenc"
    AMD_VCE = "amd_vce"
    INTEL_QSV = "intel_qsv"
    CPU_ONLY = "cpu_only"


# Cached detection result (detect once per process)
_gpu_cache: Optional[Tuple[GPUType, Dict[str, Any]]] = None


def detect_gpu() -> Tuple[GPUType, Dict[str, Any]]:
    """
    Detect available GPU and return optimal encoding settings.
    
    Returns:
        (GPUType, encoding_settings_dict)
        
    Detection order:
        1. NVIDIA (NVENC) - check torch.cuda or nvidia-smi
        2. AMD (VCE) - check ffmpeg encoders
        3. Intel (Quick Sync) - check ffmpeg encoders
        4. CPU fallback
    """
    global _gpu_cache
    if _gpu_cache is not None:
        return _gpu_cache
    
    # Try NVIDIA first (most common for ML/video work)
    gpu_type, settings = _detect_nvidia()
    if gpu_type != GPUType.CPU_ONLY:
        _gpu_cache = (gpu_type, settings)
        logger.info(f"✓ GPU detected: {gpu_type.value}")
        return _gpu_cache
    
    # Try AMD
    gpu_type, settings = _detect_amd()
    if gpu_type != GPUType.CPU_ONLY:
        _gpu_cache = (gpu_type, settings)
        logger.info(f"✓ GPU detected: {gpu_type.value}")
        return _gpu_cache
    
    # Try Intel
    gpu_type, settings = _detect_intel()
    if gpu_type != GPUType.CPU_ONLY:
        _gpu_cache = (gpu_type, settings)
        logger.info(f"✓ GPU detected: {gpu_type.value}")
        return _gpu_cache
    
    # CPU fallback
    logger.info("⚠️ No GPU detected, using CPU encoding (slower)")
    _gpu_cache = (GPUType.CPU_ONLY, _get_cpu_settings())
    return _gpu_cache


def _detect_nvidia() -> Tuple[GPUType, Dict[str, Any]]:
    """Detect NVIDIA GPU via PyTorch or nvidia-smi."""
    # Method 1: Check if PyTorch sees CUDA
    try:
        if torch is None:
            raise ImportError("torch not installed")
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            logger.info(f"NVIDIA GPU: {device_name}")
            return (GPUType.NVIDIA_NVENC, _get_nvenc_settings())
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"PyTorch CUDA check failed: {e}")
    
    # Method 2: Check nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            gpu_name = result.stdout.strip().split('\n')[0]
            logger.info(f"NVIDIA GPU (nvidia-smi): {gpu_name}")
            return (GPUType.NVIDIA_NVENC, _get_nvenc_settings())
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"nvidia-smi check failed: {e}")
    
    return (GPUType.CPU_ONLY, {})


def _detect_amd() -> Tuple[GPUType, Dict[str, Any]]:
    """Detect AMD GPU via ffmpeg encoder availability."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "h264_amf" in result.stdout or "hevc_amf" in result.stdout:
            logger.info("AMD GPU detected (AMF encoder available)")
            return (GPUType.AMD_VCE, _get_amd_settings())
    except Exception as e:
        logger.debug(f"AMD detection failed: {e}")
    
    return (GPUType.CPU_ONLY, {})


def _detect_intel() -> Tuple[GPUType, Dict[str, Any]]:
    """Detect Intel GPU via ffmpeg encoder availability + functional test."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "h264_qsv" not in result.stdout and "hevc_qsv" not in result.stdout:
            return (GPUType.CPU_ONLY, {})
        # Encoder appears in list — now verify it actually works at runtime
        # (requires Intel Media SDK / VAAPI drivers; not just compiled-in support)
        test = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "nullsrc=s=64x64:d=1",
                "-c:v", "h264_qsv",
                "-f", "null", "-"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        if test.returncode != 0:
            logger.debug(f"h264_qsv functional test failed: {test.stderr[-200:]}")
            return (GPUType.CPU_ONLY, {})
        logger.info("Intel GPU detected (Quick Sync available)")
        return (GPUType.INTEL_QSV, _get_intel_settings())
    except Exception as e:
        logger.debug(f"Intel detection failed: {e}")
    
    return (GPUType.CPU_ONLY, {})


def _get_nvenc_settings() -> Dict[str, Any]:
    """
    NVIDIA NVENC encoding settings for MoviePy.
    
    NVENC is 3-5x faster than libx264 on supported GPUs.
    Quality: preset p4-p7 (p4=fastest, p7=best quality)
    """
    return {
        "codec": "h264_nvenc",
        "preset": "p4",  # Fast preset, good quality
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        # NVENC-specific params
        "ffmpeg_params": [
            "-rc:v", "vbr",  # Variable bitrate
            "-cq:v", "23",   # Constant quality (lower = better, 23 is good default)
            "-b:v", "5M",    # Max bitrate
            "-profile:v", "high",
        ]
    }


def _get_amd_settings() -> Dict[str, Any]:
    """AMD VCE encoding settings."""
    return {
        "codec": "h264_amf",
        "preset": "speed",  # AMD presets: speed, balanced, quality
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "ffmpeg_params": [
            "-rc", "vbr_peak",
            "-qp_i", "23",
            "-qp_p", "23",
            "-quality", "speed",
        ]
    }


def _get_intel_settings() -> Dict[str, Any]:
    """Intel Quick Sync encoding settings."""
    return {
        "codec": "h264_qsv",
        "preset": "fast",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "ffmpeg_params": [
            "-global_quality", "23",
        ]
    }


def _get_cpu_settings() -> Dict[str, Any]:
    """CPU-only encoding settings (libx264)."""
    return {
        "codec": "libx264",
        "preset": "medium",  # medium = good balance
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "ffmpeg_params": [
            "-crf", "23",  # Constant Rate Factor (18-28, lower=better)
            "-profile:v", "high",
            "-movflags", "+faststart",
        ]
    }


def get_optimal_render_concurrency() -> int:
    """
    Return optimal number of concurrent renders based on GPU.
    
    Returns:
        Recommended semaphore limit for parallel rendering
        
    Logic:
        - NVIDIA GPU: 4-6 concurrent (NVENC has multiple streams)
        - AMD/Intel: 3-4 concurrent
        - CPU only: 2 concurrent (avoid overload)
    """
    gpu_type, _ = detect_gpu()
    
    if gpu_type == GPUType.NVIDIA_NVENC:
        return 4  # NVENC can handle multiple streams well
    elif gpu_type in (GPUType.AMD_VCE, GPUType.INTEL_QSV):
        return 3  # Conservative for AMD/Intel
    else:
        return 2  # CPU fallback, don't overload
