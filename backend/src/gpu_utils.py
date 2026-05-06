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
    """True if nvenc_h264 is listed AND actually works (runtime encode test).
    Falls back to hevc_nvenc if h264_nvenc/nvenc_h264 fails."""
    # Step 1: Check if any NVENC encoder is listed
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        has_nvenc = "nvenc_h264" in result.stdout or "h264_nvenc" in result.stdout
        if not has_nvenc:
            logger.warning("[GPU] No NVENC encoder found in ffmpeg encoders list")
            return False
    except Exception as e:
        logger.warning(f"[GPU] ffmpeg encoder list check failed: {e}")
        return False

    # Step 2: Runtime test with color source (more reliable than nullsrc)
    import tempfile, os
    test_out = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_out = f.name
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:s=256x256:r=1",
                "-t", "1",
                "-c:v", "nvenc_h264", "-pix_fmt", "yuv420p", test_out,
            ],
            capture_output=True, timeout=15,
        )
        if r.returncode == 0:
            try:
                os.unlink(test_out)
            except Exception:
                pass
            logger.info("[GPU] nvenc_h264 runtime test PASSED")
            return True

        # Log failure reason
        stderr = r.stderr.decode(errors="replace") if r.stderr else ""
        logger.warning(f"[GPU] nvenc_h264 runtime test FAILED: {stderr[:200]}")

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


def get_ffmpeg_video_codec_args(quality: str = "high") -> Dict[str, Any]:
    """
    Return FFmpeg video encoding arguments optimised for available hardware.

    GPU path  : nvenc_h264 — 5-8x faster than libx264 on NVIDIA GPU.
    CPU path  : libx264 ultrafast — safe fallback.

    Returns a dict with keys: codec, preset, extra_args (list of extra ffmpeg flags).
    """
    use_nvenc = nvenc_available() and cuda_available()

    if use_nvenc:
        logger.info(f"[GPU] Using nvenc_h264 encoder ({gpu_name()})")
        if quality == "high":
            return {
                "codec": "nvenc_h264",
                "preset": "p4",          # nvenc preset: p1(fast)..p7(slow), p4=balanced
                "extra_args": [
                    "-tune", "hq",
                    "-rc", "vbr",
                    "-cq", "23",
                    "-b:v", "0",
                    "-maxrate", "8M",
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
                "codec": "nvenc_h264",
                "preset": "p4",
                "extra_args": [
                    "-tune", "hq",
                    "-rc", "vbr",
                    "-cq", "23",
                    "-b:v", "0",
                    "-maxrate", "8M",
                    "-bufsize", "16M",
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "high",
                    "-level", "4.1",
                    "-b:a", "192k",
                    "-ar", "48000",
                ],
            }
    else:
        logger.info("[GPU] nvenc_h264 unavailable — using libx264 CPU encoder")
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
    e.g. [..., "-c:v", "nvenc_h264", "-preset", "p4", "-rc", "vbr", "-cq", "23", ...]
    """
    enc = get_ffmpeg_video_codec_args(quality)
    flags = ["-c:v", enc["codec"], "-preset", enc["preset"]] + enc["extra_args"]
    return flags
