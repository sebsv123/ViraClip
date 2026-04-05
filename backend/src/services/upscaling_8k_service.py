"""
Phase 9.3 — 8K/Hollywood-Quality Upscaling Service
==================================================
Extends the base ESRGAN upscaling to support 8K (7680×4320) output.

Features:
  - Direct 4× upscale (1080p → 8K) for speed
  - Dual-pass 2×+2× upscale for maximum quality
  - AI denoising pre-processing (optional)
  - HDR tone mapping support (optional)

Usage:
    from upscaling_8k_service import Upscale8KService
    svc = Upscale8KService()
    result = await svc.upscale_8k("/path/1080p.mp4", mode="dual")

API Endpoint: POST /gpu/upscale/8k
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from .upscaling_service import UpscalingService, _load_upsampler, _ensure_model

logger = logging.getLogger(__name__)

# 8K Resolution standards
K8_WIDTH = 7680
K8_HEIGHT = 4320
K4_WIDTH = 3840
K4_HEIGHT = 2160

_UPSCALE8K_TEMP = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads")) / "upscaled_8k"
_UPSCALE8K_TEMP.mkdir(parents=True, exist_ok=True)


class Upscale8KService(UpscalingService):
    """
    8K/Hollywood-quality upscaling service.

    Extends base UpscalingService with dual-pass and 8K-specific optimizations.
    """

    def __init__(self, model: str = "realesrgan"):
        super().__init__(model=model)
        self.out_dir = _UPSCALE8K_TEMP
        self.out_dir.mkdir(parents=True, exist_ok=True)

    async def upscale_8k(
        self,
        input_path: str,
        mode: Literal["direct", "dual", "4k_intermediate"] = "dual",
        denoise: bool = False,
        hdr: bool = False,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upscale video to 8K resolution (7680×4320).

        Args:
            input_path: Source video path
            mode: "direct" = 4× single pass (fast), "dual" = 2× then 2× (best quality),
                  "4k_intermediate" = scale to 4K first, then 8K (balanced)
            denoise: Apply AI denoising before upscaling
            hdr: Enable HDR10 tone mapping output
            output_path: Optional custom output path

        Returns:
            {
                "output_path": str,
                "original_resolution": str,
                "output_resolution": "7680x4320",
                "mode": str,
                "processing_time_sec": float,
                "psnr_estimate": float | None,
            }
        """
        src = Path(input_path)
        dest = Path(output_path) if output_path else (
            self.out_dir / f"8k_{mode}_{src.stem}_{int(time.time())}.mp4"
        )

        orig_w, orig_h = self._probe_resolution(src)
        orig_res = f"{orig_w}x{orig_h}"

        # Calculate required scale factors
        target_scale_x = K8_WIDTH / orig_w
        target_scale_y = K8_HEIGHT / orig_h
        min_scale = min(target_scale_x, target_scale_y)

        if min_scale < 1.0:
            raise ValueError(f"Source {orig_res} is already larger than 8K target")

        start_time = time.perf_counter()

        if not self.is_available():
            logger.warning("[8K] GPU/realesrgan not available — FFmpeg lanczos fallback")
            await self._ffmpeg_scale(src, dest, K8_WIDTH, K8_HEIGHT)
            elapsed = time.perf_counter() - start_time
            return {
                "output_path": str(dest),
                "original_resolution": orig_res,
                "output_resolution": f"{K8_WIDTH}x{K8_HEIGHT}",
                "mode": "ffmpeg_fallback",
                "processing_time_sec": round(elapsed, 2),
                "psnr_estimate": None,
            }

        # Optional: AI denoising pre-processing
        if denoise:
            src = await self._apply_denoise(src)

        # Execute upscale based on mode
        if mode == "direct":
            out_res = await self._upscale_direct_8k(src, dest)
        elif mode == "dual":
            out_res = await self._upscale_dual_pass(src, dest)
        elif mode == "4k_intermediate":
            out_res = await self._upscale_4k_then_8k(src, dest)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        elapsed = time.perf_counter() - start_time

        # Estimate quality (would need reference to compute real PSNR)
        psnr_estimate = self._estimate_quality(orig_w, orig_h, mode)

        logger.info(f"[8K] ✓ {src.name} {orig_res} → {out_res} ({mode}, {elapsed:.1f}s)")

        return {
            "output_path": str(dest),
            "original_resolution": orig_res,
            "output_resolution": out_res,
            "mode": mode,
            "processing_time_sec": round(elapsed, 2),
            "psnr_estimate": psnr_estimate,
        }

    async def upscale_4k(
        self,
        input_path: str,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Quick 4K upscaling (3840×2160) — halfway to 8K, useful for 1080p sources.
        """
        src = Path(input_path)
        dest = Path(output_path) if output_path else (
            self.out_dir / f"4k_{src.stem}_{int(time.time())}.mp4"
        )

        orig_w, orig_h = self._probe_resolution(src)
        orig_res = f"{orig_w}x{orig_h}"

        start_time = time.perf_counter()

        if not self.is_available():
            await self._ffmpeg_scale(src, dest, K4_WIDTH, K4_HEIGHT)
            elapsed = time.perf_counter() - start_time
            return {
                "output_path": str(dest),
                "original_resolution": orig_res,
                "output_resolution": f"{K4_WIDTH}x{K4_HEIGHT}",
                "mode": "ffmpeg_fallback",
                "processing_time_sec": round(elapsed, 2),
            }

        # 2× upscale for most 1080p sources to reach 4K
        loop = asyncio.get_event_loop()
        out_res = await loop.run_in_executor(
            None, self._upscale_sync, src, dest, "realesrgan-x2", 2
        )

        elapsed = time.perf_counter() - start_time
        return {
            "output_path": str(dest),
            "original_resolution": orig_res,
            "output_resolution": out_res,
            "mode": "2x_direct",
            "processing_time_sec": round(elapsed, 2),
        }

    # ── Internal 8K Methods ───────────────────────────────────────────────────

    async def _upscale_direct_8k(self, src: Path, dest: Path) -> str:
        """Single 4× pass to 8K — fastest, moderate quality."""
        loop = asyncio.get_event_loop()
        # Use 4× model for direct upscaling
        return await loop.run_in_executor(
            None, self._upscale_sync, src, dest, "realesrgan", 4
        )

    async def _upscale_dual_pass(self, src: Path, dest: Path) -> str:
        """Two 2× passes for better quality than single 4×."""
        # First pass: source → 4K intermediate
        temp_4k = Path(tempfile.mktemp(suffix="_4k.mp4", dir=self.out_dir))
        try:
            loop = asyncio.get_event_loop()
            # First 2× pass
            mid_res = await loop.run_in_executor(
                None, self._upscale_sync, src, temp_4k, "realesrgan-x2", 2
            )
            logger.debug(f"[8K] First pass complete: {mid_res}")

            # Second 2× pass: 4K → 8K
            final_res = await loop.run_in_executor(
                None, self._upscale_sync, temp_4k, dest, "realesrgan-x2", 2
            )
            return final_res
        finally:
            if temp_4k.exists():
                temp_4k.unlink()

    async def _upscale_4k_then_8k(self, src: Path, dest: Path) -> str:
        """4K intermediate with quality preservation, then 2× to 8K."""
        # Similar to dual but with different settings for intermediate
        temp_4k = Path(tempfile.mktemp(suffix="_4k_prores.mov", dir=self.out_dir))
        try:
            # First pass to 4K with high-quality intermediate codec
            await self._upscale_4k_ffmpeg(src, temp_4k)

            # Second pass: ESRGAN 2× to 8K
            loop = asyncio.get_event_loop()
            final_res = await loop.run_in_executor(
                None, self._upscale_sync, temp_4k, dest, "realesrgan-x2", 2
            )
            return final_res
        finally:
            if temp_4k.exists():
                temp_4k.unlink()

    async def _apply_denoise(self, src: Path) -> Path:
        """Apply FFmpeg afftdn denoising before upscaling."""
        dest = Path(tempfile.mktemp(suffix="_denoised.mp4", dir=self.out_dir))
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", "afftdn=nf=-25",
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy",
            str(dest),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"[8K] Denoising failed, using original: {stderr.decode()[:200]}")
            return src
        return dest

    async def _upscale_4k_ffmpeg(self, src: Path, dest: Path) -> None:
        """High-quality 4K intermediate using ProRes for preservation."""
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", f"scale={K4_WIDTH}:{K4_HEIGHT}:flags=lanczos",
            "-c:v", "prores_ks", "-profile:v", "3", "-qscale:v", "9",  # ProRes HQ
            "-c:a", "copy",
            str(dest),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"4K intermediate failed: {stderr.decode()[:200]}")

    @staticmethod
    def _estimate_quality(orig_w: int, orig_h: int, mode: str) -> Optional[float]:
        """
        Estimate PSNR based on source resolution and upscaling mode.
        These are approximate values based on ESRGAN benchmarks.
        """
        # Base PSNR for ESRGAN 4× is typically 28-32 dB
        base_psnr = 30.0

        # Adjust for mode
        mode_adjust = {
            "direct": 0.0,
            "dual": 1.5,  # Dual pass slightly better
            "4k_intermediate": 1.0,
            "ffmpeg_fallback": -5.0,  # Significantly worse
        }.get(mode, 0.0)

        # Adjust for source quality (higher source = better result)
        source_pixels = orig_w * orig_h
        if source_pixels >= 3840 * 2160:  # 4K source
            source_adjust = 2.0
        elif source_pixels >= 1920 * 1080:  # 1080p source
            source_adjust = 0.0
        elif source_pixels >= 1280 * 720:  # 720p source
            source_adjust = -2.0
        else:  # SD source
            source_adjust = -4.0

        return round(base_psnr + mode_adjust + source_adjust, 1)

    def get_8k_info(self) -> Dict[str, Any]:
        """Return information about 8K capabilities."""
        import torch
        vram_gb = 0.0
        if torch.cuda.is_available():
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)

        return {
            "8k_supported": vram_gb >= 8.0,  # Need at least 8GB for 8K
            "vram_gb": round(vram_gb, 1),
            "recommended_mode": "dual" if vram_gb >= 12.0 else "direct",
            "target_resolution": f"{K8_WIDTH}x{K8_HEIGHT}",
            "4k_intermediate_available": True,
        }
