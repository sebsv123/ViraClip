"""
Text-to-Video B-Roll Generation Service — Phase 3.1
=====================================================
Generates short portrait B-roll clips from text prompts using LTX-Video
(primary) or AnimateLCM (fast 4-step fallback).

Models:
  - LTX-Video 0.9.7  (Lightricks/LTX-Video)  ~5 GB VRAM, 720p, 2-8s
  - AnimateLCM        (wangfuyun/AnimateLCM)  ~4 GB VRAM, 512px, 4 steps
  - Wan2.2-1.3B       (Wan-AI/Wan2.2-T2V-1.3B) ~8 GB VRAM, 720p

Resolution mapping:
  480p → 480×848,  720p → 720×1280,  1080p → 1080×1920
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
T2V_MODEL       = os.environ.get("T2V_MODEL", "ltx-video")
T2V_RESOLUTION  = os.environ.get("T2V_RESOLUTION", "720p")
T2V_CACHE_DIR   = Path(os.environ.get("T2V_CACHE_DIR", "/app/models/t2v"))
TEMP_DIR        = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads"))

_RES_MAP = {
    "480p":  (480, 848),
    "720p":  (720, 1280),
    "1080p": (1080, 1920),
}

_LOADED: Dict[str, Any] = {}   # module-level model cache


def _get_device():
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _load_ltx_pipeline():
    """Load LTX-Video pipeline (lazy, cached)."""
    global _LOADED
    if "ltx" in _LOADED:
        return _LOADED["ltx"]

    logger.info("[T2V] Loading LTX-Video pipeline …")
    from diffusers import LTXPipeline
    import torch

    pipe = LTXPipeline.from_pretrained(
        "Lightricks/LTX-Video",
        torch_dtype=torch.float16,
        cache_dir=str(T2V_CACHE_DIR),
    )
    pipe.to(_get_device())
    pipe.enable_model_cpu_offload()
    _LOADED["ltx"] = pipe
    logger.info("[T2V] LTX-Video loaded.")
    return pipe


def _load_animatelcm_pipeline():
    """Load AnimateLCM pipeline (lazy, cached)."""
    global _LOADED
    if "animatelcm" in _LOADED:
        return _LOADED["animatelcm"]

    logger.info("[T2V] Loading AnimateLCM pipeline …")
    from diffusers import AnimateDiffPipeline, LCMScheduler, MotionAdapter
    import torch

    adapter = MotionAdapter.from_pretrained(
        "wangfuyun/AnimateLCM",
        torch_dtype=torch.float16,
        cache_dir=str(T2V_CACHE_DIR),
    )
    pipe = AnimateDiffPipeline.from_pretrained(
        "emilianJR/epiCRealism",
        motion_adapter=adapter,
        torch_dtype=torch.float16,
        cache_dir=str(T2V_CACHE_DIR),
    )
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config, beta_schedule="linear")
    pipe.load_lora_weights(
        "wangfuyun/AnimateLCM",
        weight_name="AnimateLCM_sd15_t2v_lora.safetensors",
        adapter_name="lcm-animation",
    )
    pipe.set_adapters(["lcm-animation"], [0.8])
    pipe.to(_get_device())
    pipe.enable_model_cpu_offload()
    _LOADED["animatelcm"] = pipe
    logger.info("[T2V] AnimateLCM loaded.")
    return pipe


def _frames_to_mp4(frames, output_path: Path, fps: int = 8) -> Path:
    """Write PIL image frames to MP4 via imageio."""
    import imageio.v3 as iio
    import numpy as np

    output_path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.stack([np.array(f) for f in frames])   # (T, H, W, 3)
    iio.imwrite(str(output_path), arr, fps=fps, codec="libx264",
                quality=None, output_params=["-preset", "fast", "-crf", "20"])
    return output_path


class T2VBrollService:
    """
    Generate portrait B-roll clips from text prompts.

    Priority chain:
      1. LTX-Video 0.9.7 (best quality)
      2. AnimateLCM      (fast 4-step fallback)
      3. Raise RuntimeError (caller falls back to Pexels/ComfyUI)
    """

    def __init__(self,
                 model: str = T2V_MODEL,
                 resolution: str = T2V_RESOLUTION):
        self.model      = model
        self.resolution = resolution
        self.device     = _get_device()
        self.out_dir    = TEMP_DIR / "broll_generated"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        duration: float = 4.0,
        resolution: Optional[str] = None,
        model: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a B-roll clip from *prompt*.

        Returns:
            {"clip_path": str, "duration": float, "model": str}
        """
        res   = resolution or self.resolution
        mdl   = model or self.model
        w, h  = _RES_MAP.get(res, (720, 1280))
        n_fps = 8
        n_frames = max(8, min(64, int(duration * n_fps)))

        if output_path is None:
            safe  = "".join(c if c.isalnum() else "_" for c in prompt[:40])
            output_path = str(self.out_dir / f"t2v_{safe}_{int(time.time())}.mp4")

        dest = Path(output_path)

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                self._generate_sync,
                prompt, n_frames, w, h, n_fps, dest, mdl,
            )
        except Exception as exc:
            logger.warning(f"[T2V] Primary model failed ({exc}), trying AnimateLCM fallback …")
            if mdl != "animatelcm":
                await loop.run_in_executor(
                    None,
                    self._generate_sync,
                    prompt, n_frames, 512, 512, n_fps, dest, "animatelcm",
                )
                mdl = "animatelcm"
            else:
                raise

        actual_duration = n_frames / n_fps
        logger.info(f"[T2V] ✓ Generated {dest.name} ({actual_duration:.1f}s, {mdl})")
        return {"clip_path": str(dest), "duration": actual_duration, "model": mdl}

    # ── Sync generation (runs in executor) ────────────────────────────────────

    def _generate_sync(
        self,
        prompt: str,
        n_frames: int,
        width: int,
        height: int,
        fps: int,
        dest: Path,
        model_name: str,
    ) -> None:
        full_prompt = (
            f"{prompt}, cinematic, professional quality, sharp focus, "
            f"portrait orientation, vibrant colors, high detail, 4K"
        )
        negative = (
            "blurry, low quality, pixelated, distorted, watermark, text, logo, "
            "black bars, letterbox, horizontal orientation"
        )

        if model_name in ("ltx-video", "ltx"):
            self._run_ltx(full_prompt, negative, n_frames, width, height, fps, dest)
        elif model_name in ("animatelcm", "animatediff"):
            self._run_animatelcm(full_prompt, n_frames, fps, dest)
        else:
            raise ValueError(f"Unknown T2V model: {model_name}")

    def _run_ltx(self, prompt, negative, n_frames, width, height, fps, dest):
        import torch
        pipe = _load_ltx_pipeline()
        with torch.inference_mode():
            output = pipe(
                prompt=prompt,
                negative_prompt=negative,
                width=width,
                height=height,
                num_frames=n_frames,
                num_inference_steps=25,
                guidance_scale=3.0,
            )
        _frames_to_mp4(output.frames[0], dest, fps=fps)

    def _run_animatelcm(self, prompt, n_frames, fps, dest):
        import torch
        pipe = _load_animatelcm_pipeline()
        with torch.inference_mode():
            output = pipe(
                prompt=prompt,
                num_frames=n_frames,
                guidance_scale=1.5,
                num_inference_steps=4,
                generator=torch.Generator().manual_seed(42),
            )
        _frames_to_mp4(output.frames[0], dest, fps=fps)

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def is_available() -> bool:
        """True if at least one T2V model can be loaded (GPU present + diffusers installed)."""
        try:
            import torch
            import diffusers  # noqa: F401
            return torch.cuda.is_available()
        except ImportError:
            return False
