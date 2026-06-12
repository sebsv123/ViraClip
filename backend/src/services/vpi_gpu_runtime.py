from __future__ import annotations

"""Narrow GPU/NVENC runtime selection helpers for ViraClip FFmpeg paths."""

import logging
import os
from typing import Any, Dict, List

from ..utils.gpu_utils import is_ffmpeg_nvenc_runtime_available, is_torch_cuda_available

logger = logging.getLogger(__name__)


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "true" if default else "false")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def select_ffmpeg_video_encoder(
    *,
    stage: str,
    quality: str = "high",
    prefer_nvenc: bool = True,
) -> Dict[str, Any]:
    """Return a narrow FFmpeg encoder selection contract.

    The helper is intentionally small: it decides whether the caller should use
    h264_nvenc or fall back to libx264, and emits structured diagnostics that
    distinguish availability from actual use.
    """
    nvenc_enabled = _env_true("VIRACLIP_ENABLE_NVENC", default=False)
    cuda_enabled = _env_true("VIRACLIP_ENABLE_TORCH_CUDA", default=False)
    nvenc_available = False
    cuda_available = False
    try:
        nvenc_available = is_ffmpeg_nvenc_runtime_available()
    except Exception as exc:  # pragma: no cover - diagnostic only
        logger.debug("[gpu-runtime] nvenc probe failed stage=%s reason=%s", stage, exc)
    try:
        cuda_available = is_torch_cuda_available()
    except Exception as exc:  # pragma: no cover - diagnostic only
        logger.debug("[gpu-runtime] cuda probe failed stage=%s reason=%s", stage, exc)

    nvenc_used = bool(prefer_nvenc and nvenc_enabled and nvenc_available)
    encoder = "h264_nvenc" if nvenc_used else "libx264"
    preset = "p4" if nvenc_used else "fast"
    extra_args: List[str]
    if nvenc_used:
        extra_args = ["-rc", "constqp", "-qp", "20", "-profile:v", "high"]
    else:
        extra_args = ["-crf", "20" if quality == "high" else "22"]

    gpu_available = bool(nvenc_available or cuda_available)
    cuda_used = False
    reason = "nvenc_enabled_and_runtime_available" if nvenc_used else (
        "nvenc_disabled" if not nvenc_enabled else
        "nvenc_runtime_unavailable" if not nvenc_available else
        "cpu_fallback"
    )

    logger.info(
        "FFMPEG_ENCODER_SELECTED stage=%s encoder=%s nvenc_available=%s nvenc_enabled=%s cuda_available=%s",
        stage,
        encoder,
        str(nvenc_available).lower(),
        str(nvenc_enabled).lower(),
        str(cuda_available).lower(),
    )
    logger.info(
        "FFMPEG_GPU_PATH_USED stage=%s used_nvenc=%s used_cuda=%s reason=%s",
        stage,
        str(nvenc_used).lower(),
        str(cuda_used).lower(),
        reason,
    )

    return {
        "stage": stage,
        "encoder": encoder,
        "preset": preset,
        "extra_args": extra_args,
        "gpu_available": gpu_available,
        "gpu_used": bool(nvenc_used or cuda_used),
        "nvenc_available": nvenc_available,
        "nvenc_enabled": nvenc_enabled,
        "nvenc_used": nvenc_used,
        "cuda_available": cuda_available,
        "cuda_enabled": cuda_enabled,
        "cuda_used": cuda_used,
        "reason": reason,
    }
