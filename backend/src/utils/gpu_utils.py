"""
gpu_utils.py — GPU capability detection layer for ViraClip.

Provides safe, flag-gated GPU detection functions:
  - is_torch_cuda_available()   → real PyTorch CUDA tensor test
  - is_ffmpeg_nvenc_runtime_available() → real FFmpeg NVENC encode test
  - get_gpu_status()            → combined status dict

All results are cached at module load time.  GPU is NEVER used unless the
corresponding VIRACLIP_ENABLE_* flag is explicitly set to true in the
environment.  This is a *detection-only* layer — consumers must check both
availability AND the enable flag before using GPU.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from functools import lru_cache
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_NVENC_PROBE_FILE = "/tmp/viraclip_nvenc_probe.mp4"
_NVENC_PROBE_TIMEOUT = 10  # seconds


# ── Torch CUDA detection ───────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def is_torch_cuda_available() -> bool:
    """
    Return True only if PyTorch can *actually* create a small tensor on CUDA.

    Steps:
      1. import torch
      2. torch.cuda.is_available()
      3. torch.cuda.device_count() > 0
      4. Create a small tensor on cuda and copy it back

    Returns False (with a logged reason) on any failure.
    """
    try:
        import torch
    except ImportError as exc:
        logger.debug("[gpu] torch not installed: %s", exc)
        return False

    if not torch.cuda.is_available():
        logger.debug("[gpu] torch.cuda.is_available() returned False")
        return False

    if torch.cuda.device_count() == 0:
        logger.debug("[gpu] torch.cuda.device_count() == 0")
        return False

    # Real tensor test — catches driver-level failures
    try:
        t = torch.zeros((2, 3), device="cuda")
        _ = t.cpu()  # force a round-trip
        del t
    except Exception as exc:
        logger.debug("[gpu] torch CUDA tensor test failed: %s", exc)
        return False

    return True


# ── FFmpeg NVENC runtime detection ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def is_ffmpeg_nvenc_runtime_available() -> bool:
    """
    Return True only if FFmpeg can *actually* encode a short test clip with
    h264_nvenc at runtime.

    This is NOT a static check (``ffmpeg -encoders``).  It runs a real encode:

        ffmpeg -hide_banner -y -f lavfi -i testsrc2=size=320x180:rate=15 \\
               -t 0.5 -c:v h264_nvenc -preset p4 -pix_fmt yuv420p \\
               -f mp4 /tmp/viraclip_nvenc_probe.mp4

    If the output file is created and has a non-zero size, NVENC works.
    Otherwise returns False.
    """
    probe_path = _NVENC_PROBE_FILE

    try:
        # Remove any leftover probe file
        if os.path.exists(probe_path):
            os.unlink(probe_path)

        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-y",
                "-f", "lavfi",
                "-i", "testsrc2=size=320x180:rate=15",
                "-t", "0.5",
                "-c:v", "h264_nvenc",
                "-preset", "p4",
                "-pix_fmt", "yuv420p",
                "-f", "mp4",
                probe_path,
            ],
            capture_output=True,
            timeout=_NVENC_PROBE_TIMEOUT,
        )

        if result.returncode != 0:
            stderr_tail = result.stderr.decode("utf-8", errors="replace")[-300:]
            logger.debug("[gpu] NVENC runtime probe failed (exit %d): %s",
                         result.returncode, stderr_tail)
            return False

        if not os.path.exists(probe_path):
            logger.debug("[gpu] NVENC runtime probe: no output file created")
            return False

        if os.path.getsize(probe_path) == 0:
            logger.debug("[gpu] NVENC runtime probe: output file is empty")
            return False

        return True

    except subprocess.TimeoutExpired:
        logger.debug("[gpu] NVENC runtime probe timed out after %ds",
                     _NVENC_PROBE_TIMEOUT)
        return False
    except FileNotFoundError:
        logger.debug("[gpu] ffmpeg not found in PATH")
        return False
    except Exception as exc:
        logger.debug("[gpu] NVENC runtime probe exception: %s", exc)
        return False
    finally:
        # Clean up probe file
        try:
            if os.path.exists(probe_path):
                os.unlink(probe_path)
        except Exception:
            pass


# ── GPU device name ────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def gpu_device_name() -> str:
    """Return GPU name string, or 'CPU' if none detected."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split("\n")[0].strip()
    except Exception:
        pass
    return "CPU"


# ── Combined status ────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_gpu_status() -> Dict[str, Any]:
    """
    Return a dict with the full GPU capability status.

    Returns:
        {
            "torch_cuda": bool,
            "nvenc_runtime": bool,
            "device_name": str,
            "reason": str,       # human-readable summary
        }
    """
    torch_cuda = is_torch_cuda_available()
    nvenc_runtime = is_ffmpeg_nvenc_runtime_available()
    device = gpu_device_name()

    reasons: list[str] = []
    if torch_cuda:
        reasons.append("torch cuda available")
    else:
        reasons.append("torch cuda unavailable")
    if nvenc_runtime:
        reasons.append("ffmpeg nvenc runtime available")
    else:
        reasons.append("ffmpeg nvenc runtime unavailable")

    return {
        "torch_cuda": torch_cuda,
        "nvenc_runtime": nvenc_runtime,
        "device_name": device,
        "reason": "; ".join(reasons),
    }


# ── Startup probe (called once at worker/backend startup) ──────────────────────

def log_gpu_status() -> None:
    """
    Log GPU detection results at startup.

    Respects VIRACLIP_GPU_PROBE_ON_START — only logs if the flag is true
    (default: false, to avoid log noise in production).
    """
    probe_on_start = os.environ.get("VIRACLIP_GPU_PROBE_ON_START", "false").lower() in (
        "1", "true", "yes"
    )
    if not probe_on_start:
        return

    status = get_gpu_status()

    if status["torch_cuda"]:
        logger.info(
            '[gpu] torch cuda available=true device="%s"',
            status["device_name"],
        )
    else:
        logger.info("[gpu] torch cuda available=false")

    if status["nvenc_runtime"]:
        logger.info("[gpu] ffmpeg nvenc runtime available=true")
    else:
        logger.info("[gpu] ffmpeg nvenc runtime available=false")

    # Check if GPU is available but disabled by flags
    enable_torch_cuda = os.environ.get("VIRACLIP_ENABLE_TORCH_CUDA", "false").lower() in (
        "1", "true", "yes"
    )
    enable_nvenc = os.environ.get("VIRACLIP_ENABLE_NVENC", "false").lower() in (
        "1", "true", "yes"
    )

    if status["torch_cuda"] and not enable_torch_cuda:
        logger.info("[gpu] torch cuda available but disabled by VIRACLIP_ENABLE_TORCH_CUDA=false")
    if status["nvenc_runtime"] and not enable_nvenc:
        logger.info("[gpu] nvenc available but disabled by VIRACLIP_ENABLE_NVENC=false")
    if (status["torch_cuda"] or status["nvenc_runtime"]) and not (enable_torch_cuda or enable_nvenc):
        logger.info("[gpu] gpu available but disabled by flags")
def get_ffmpeg_exe() -> str:
    """Return the system ffmpeg binary path, falling back to imageio_ffmpeg.

    The system ffmpeg (from apt) includes NVENC support on NVIDIA GPU
    containers.  The imageio_ffmpeg bundled binary does not include NVENC,
    which forces CPU-only encoding (libx264) and makes rendering 3-5x slower.
    """
    import shutil
    system_ffmpeg = shutil.which('ffmpeg')
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return 'ffmpeg'



