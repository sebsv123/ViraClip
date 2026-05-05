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
    """True if a CUDA-capable GPU is available.
    
    Uses ctranslate2 as primary check (works even when torch is CPU-only build),
    then falls back to nvidia-smi subprocess detection.
    torch.cuda.is_available() is NOT used — it returns False when torch is
    installed as a CPU-only wheel, which is unrelated to actual GPU presence.
    """
    # Primary: ctranslate2 (used by faster-whisper) — reliable on Windows
    try:
        import ctranslate2
        types = ctranslate2.get_supported_compute_types("cuda")
        if len(types) > 1:  # more than just float32 means real CUDA support
            logger.info("[GPU] CUDA available via ctranslate2")
            return True
    except Exception:
        pass
    # Fallback: nvidia-smi
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            logger.info("[GPU] CUDA available via nvidia-smi: %s", r.stdout.strip())
            return True
    except Exception:
        pass
    return False


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """True if h264_nvenc is listed AND actually works (runtime encode test)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        if "h264_nvenc" not in result.stdout:
            return False
    except Exception:
        return False
    # Runtime test: actually encode 3 frames to /dev/null
    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_out = f.name
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:size=64x64:duration=0.1:rate=30",
                "-c:v", "h264_nvenc", "-frames:v", "3", test_out,
            ],
            capture_output=True, timeout=15,
        )
        ok = r.returncode == 0
        try:
            os.unlink(test_out)
        except Exception:
            pass
        if not ok:
            logger.warning("[GPU] h264_nvenc runtime test FAILED — falling back to libx264")
        return ok
    except Exception:
        return False


def clear_nvenc_cache() -> None:
    """Invalidate nvenc_available() cache so next call re-probes the GPU."""
    nvenc_available.cache_clear()


@lru_cache(maxsize=1)
def gpu_name() -> str:
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
                    "-qp", "22",          # constant QP mode - máxima compatibilidad
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
