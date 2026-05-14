"""
gpu_utils.py — Central GPU capability detection for ViraClip.

Import this module anywhere to get encoding settings and CUDA availability.
Results are cached at module load time — detection runs only once per process.

Startup assertion: on first import, eagerly probes NVENC and CUDA and logs
the results at INFO level. This ensures any GPU issues are surfaced early
(in container logs) rather than silently failing mid-render.
"""
import logging
import os
import subprocess
from functools import lru_cache
from typing import Dict, Any, List

# Use a hardcoded logger name so it's always "gpu_utils" regardless of how
# this module is imported (e.g. "gpu_utils" vs "src.gpu_utils").
logger = logging.getLogger("gpu_utils")


# ── Startup assertion: eager probe at module load time ──────────────────────
# This runs once when gpu_utils is first imported anywhere in the process.
# It eagerly calls the cached detection functions so that:
#   - NVENC availability is verified immediately (not lazily on first render)
#   - CUDA availability is verified immediately
#   - Any GPU issues are surfaced in container logs at startup
# The results are cached by @lru_cache, so subsequent calls are free.
def _startup_gpu_probe() -> None:
    """Eagerly probe GPU capabilities at module load time and log results."""
    _cuda = cuda_available()
    _nvenc = nvenc_available()
    _gpu = gpu_name()

    if _cuda:
        logger.info("[GPU STARTUP] ✅ CUDA available — GPU: %s", _gpu)
    else:
        logger.info("[GPU STARTUP] ⚠️  CUDA not detected — falling back to CPU")

    if _nvenc:
        logger.info("[GPU STARTUP] ✅ NVENC available — hardware encoding enabled")
    else:
        logger.info("[GPU STARTUP] ⚠️  NVENC not available — using libx264 CPU encoder")

    if _cuda and _nvenc:
        logger.info("[GPU STARTUP] ✅ Full GPU acceleration ready")
    elif _cuda and not _nvenc:
        logger.warning("[GPU STARTUP] ⚠️  CUDA available but NVENC missing — GPU compute only, no hardware encoding")
    else:
        logger.info("[GPU STARTUP] ℹ️  Running in CPU-only mode")



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
    """True if h264_nvenc is listed AND actually works (runtime encode test).
    Falls back to hevc_nvenc if h264_nvenc fails."""
    # Step 1: Check if any NVENC encoder is listed
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        has_nvenc = "h264_nvenc" in result.stdout
        if not has_nvenc:
            logger.warning("[GPU] No NVENC encoder found in ffmpeg encoders list")
            return False
    except Exception as e:
        logger.warning(f"[GPU] ffmpeg encoder list check failed: {e}")
        return False

    # Step 2: Runtime test with color source (more reliable than nullsrc)
    import tempfile
    test_out = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_out = f.name
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:s=256x256:r=1",
                "-t", "1",
                "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", test_out,
            ],
            capture_output=True, timeout=15,
        )
        if r.returncode == 0:
            try:
                os.unlink(test_out)
            except Exception:
                pass
            logger.info("[GPU] h264_nvenc runtime test PASSED")
            return True

        # Log failure reason
        stderr = r.stderr.decode(errors="replace") if r.stderr else ""
        logger.warning(f"[GPU] h264_nvenc runtime test FAILED: {stderr[:200]}")

        # Step 3: Try hevc_nvenc as fallback
        logger.info("[GPU] Trying hevc_nvenc as fallback...")
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_out = f.name
        r2 = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:s=256x256:r=1",
                "-t", "1",
                "-c:v", "hevc_nvenc", "-pix_fmt", "yuv420p", test_out,
            ],
            capture_output=True, timeout=15,
        )
        if r2.returncode == 0:
            try:
                os.unlink(test_out)
            except Exception:
                pass
            logger.info("[GPU] hevc_nvenc runtime test PASSED (using as fallback)")
            return True

        stderr2 = r2.stderr.decode(errors="replace") if r2.stderr else ""
        logger.warning(f"[GPU] hevc_nvenc also FAILED: {stderr2[:200]}")
        return False
    except Exception as e:
        logger.warning(f"[GPU] NVENC runtime test error: {e}")
        return False
    finally:
        if test_out and os.path.exists(test_out):
            try:
                os.unlink(test_out)
            except Exception:
                pass


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


def get_video_encoder() -> str:
    """
    Return the best available video encoder name.
    
    Returns "h264_nvenc" if NVENC is available, otherwise "libx264".
    This is the canonical function to call when building ffmpeg commands.
    """
    if nvenc_available() and cuda_available():
        logger.info(f"[GPU] Using h264_nvenc encoder ({gpu_name()})")
        return "h264_nvenc"
    logger.info("[GPU] h264_nvenc unavailable — using libx264 CPU encoder")
    return "libx264"


def get_encoder_params() -> List[str]:
    """
    Return optimal encoder parameters for the active video encoder.
    
    Returns a flat list of ffmpeg flags suitable for appending to a command.
    For NVENC: ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "23", "-b:v", "0"]
    For libx264: ["-preset", "ultrafast", "-crf", "22"]
    """
    if get_video_encoder() == "h264_nvenc":
        return ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "23", "-b:v", "0"]
    else:
        return ["-preset", "ultrafast", "-crf", "22"]


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
                    "-tune", "hq",
                    "-b:v", "10M",
                    "-maxrate", "12M",
                    "-bufsize", "16M",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "high",
                    "-level", "4.1",
                    "-b:a", "192k",
                    "-ar", "48000",
                ],
            }
        else:  # medium
            return {
            "codec": "h264_nvenc",
            "preset": "p4",
                "extra_args": [
                    "-tune", "hq",
                    "-b:v", "8M",
                    "-maxrate", "10M",
                    "-bufsize", "16M",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "high",
                    "-level", "4.1",
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
    e.g. [..., "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", ...]
    """
    enc = get_ffmpeg_video_codec_args(quality)
    flags = ["-c:v", enc["codec"], "-preset", enc["preset"]] + enc["extra_args"]
    return flags


# Run the startup probe immediately on import (after all function definitions)
_startup_gpu_probe()
