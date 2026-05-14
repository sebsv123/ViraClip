"""
ESRGAN Video Upscaling Service — Phase 3.3
==========================================
Upscales video frames with Real-ESRGAN (2× or 4×) then reassembles via FFmpeg.
Falls back to FFmpeg bilinear when GPU/model unavailable.

Models:
  realesrgan   → RealESRGAN_x4plus (4× upscale, photorealistic)
  realesrgan-x2→ RealESRGAN_x2plus (2× upscale, faster)
  anime4k      → RealESRGAN_x4plus_anime_6B (anime/cartoon style)
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src import gpu_utils

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
UPSCALING_MODEL   = os.environ.get("UPSCALING_MODEL", "realesrgan")
UPSCALING_SCALE   = int(os.environ.get("UPSCALING_SCALE", "2"))
MODELS_DIR        = Path(os.environ.get("UPSCALING_MODELS_DIR", "/app/models/esrgan"))
TEMP_DIR          = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads"))

_MODEL_URLS = {
    "realesrgan":    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "realesrgan-x2": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    "anime4k":       "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
}

_MODEL_SCALE = {
    "realesrgan":    4,
    "realesrgan-x2": 2,
    "anime4k":       4,
}

_LOADED: Dict[str, Any] = {}


def _ensure_model(model_name: str) -> Path:
    """Download model weights if not present, return local path."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    url   = _MODEL_URLS[model_name]
    fname = url.split("/")[-1]
    dest  = MODELS_DIR / fname
    if not dest.exists():
        logger.info(f"[ESRGAN] Downloading {fname} …")
        import urllib.request
        urllib.request.urlretrieve(url, dest)
        logger.info(f"[ESRGAN] Model saved → {dest}")
    return dest


def _load_upsampler(model_name: str):
    """Load RealESRGANer (lazy, cached)."""
    global _LOADED
    if model_name in _LOADED:
        return _LOADED[model_name]

    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    model_path = _ensure_model(model_name)
    scale      = _MODEL_SCALE[model_name]

    if model_name == "anime4k":
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                        num_block=6, num_grow_ch=32, scale=scale)
    else:
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                        num_block=23, num_grow_ch=32, scale=scale)

    import torch
    upsampler = RealESRGANer(
        scale=scale,
        model_path=str(model_path),
        model=model,
        tile=400,
        tile_pad=10,
        pre_pad=0,
        half=torch.cuda.is_available(),
    )
    _LOADED[model_name] = upsampler
    logger.info(f"[ESRGAN] {model_name} loaded (scale={scale}×)")
    return upsampler


class UpscalingService:
    """
    Upscale a video clip using Real-ESRGAN.

    Usage:
        svc    = UpscalingService()
        result = await svc.upscale("/path/clip.mp4", scale_factor=2)
        # → {"output_path": ..., "original_resolution": "720x1280",
        #    "output_resolution": "1440x2560"}
    """

    def __init__(self, model: str = UPSCALING_MODEL):
        self.model   = model
        self.out_dir = TEMP_DIR / "upscaled"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def upscale(
        self,
        input_path: str,
        scale_factor: int = UPSCALING_SCALE,
        model: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upscale every frame of *input_path* by *scale_factor*.

        Returns:
            {"output_path": str, "original_resolution": str, "output_resolution": str}
        """
        src  = Path(input_path)
        mdl  = model or self.model
        dest = Path(output_path) if output_path else (
            self.out_dir / f"up{scale_factor}x_{src.stem}_{int(time.time())}.mp4"
        )

        orig_w, orig_h = self._probe_resolution(src)
        orig_res = f"{orig_w}x{orig_h}"

        if not self.is_available():
            logger.warning("[ESRGAN] GPU/realesrgan not available — FFmpeg bilinear fallback")
            await self._ffmpeg_scale(src, dest, orig_w * scale_factor, orig_h * scale_factor)
            return {"output_path": str(dest),
                    "original_resolution": orig_res,
                    "output_resolution": f"{orig_w * scale_factor}x{orig_h * scale_factor}"}

        loop = asyncio.get_event_loop()
        out_res = await loop.run_in_executor(
            None, self._upscale_sync, src, dest, mdl, scale_factor
        )

        logger.info(f"[ESRGAN] ✓ {src.name} {orig_res} → {out_res}")
        return {"output_path": str(dest),
                "original_resolution": orig_res,
                "output_resolution": out_res}

    @staticmethod
    def is_available() -> bool:
        """True if realesrgan + basicsr importable and GPU present."""
        try:
            import torch
            import realesrgan   # noqa: F401
            import basicsr      # noqa: F401
            return torch.cuda.is_available()
        except ImportError:
            return False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _upscale_sync(
        self,
        src: Path,
        dest: Path,
        model_name: str,
        scale: int,
    ) -> str:
        import cv2
        import numpy as np

        upsampler = _load_upsampler(model_name)
        fps, audio_src = self._probe_fps(src), src

        frames_dir = Path(tempfile.mkdtemp(prefix="esrgan_frames_"))
        out_frames_dir = Path(tempfile.mkdtemp(prefix="esrgan_out_"))

        try:
            # 1. Extract frames
            subprocess.run([
                "ffmpeg", "-y", "-i", str(src),
                str(frames_dir / "frame_%06d.png"),
            ], check=True, capture_output=True)

            frame_files = sorted(frames_dir.glob("*.png"))
            if not frame_files:
                raise RuntimeError("No frames extracted from video")

            out_w = out_h = 0
            for ff in frame_files:
                img = cv2.imread(str(ff), cv2.IMREAD_COLOR)
                output, _ = upsampler.enhance(img, outscale=scale)
                out_h, out_w = output.shape[:2]
                cv2.imwrite(str(out_frames_dir / ff.name), output)

            # 2. Reassemble video
            subprocess.run([
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", str(out_frames_dir / "frame_%06d.png"),
                "-i", str(audio_src),
                "-map", "0:v", "-map", "1:a",
                *gpu_utils.ffmpeg_codec_flags("high"),
                "-c:a", "copy",
                "-shortest",
                str(dest),
            ], check=True, capture_output=True)

            return f"{out_w}x{out_h}"
        finally:
            import shutil
            shutil.rmtree(frames_dir, ignore_errors=True)
            shutil.rmtree(out_frames_dir, ignore_errors=True)

    @staticmethod
    async def _ffmpeg_scale(src: Path, dest: Path, w: int, h: int) -> None:
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", f"scale={w}:{h}:flags=lanczos",
            *gpu_utils.ffmpeg_codec_flags("high"), "-c:a", "copy",
            str(dest),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()

    @staticmethod
    def _probe_resolution(path: Path) -> Tuple[int, int]:
        try:
            import json
            out = subprocess.check_output(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-select_streams", "v:0", str(path)],
                stderr=subprocess.DEVNULL,
            )
            s = json.loads(out)["streams"][0]
            return int(s["width"]), int(s["height"])
        except Exception:
            return 720, 1280

    @staticmethod
    def _probe_fps(path: Path) -> float:
        try:
            import json
            out = subprocess.check_output(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-select_streams", "v:0", str(path)],
                stderr=subprocess.DEVNULL,
            )
            s = json.loads(out)["streams"][0]
            num, den = s.get("avg_frame_rate", "30/1").split("/")
            return int(num) / max(int(den), 1)
        except Exception:
            return 30.0
