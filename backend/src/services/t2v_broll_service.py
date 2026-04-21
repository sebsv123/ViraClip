"""
Text-to-Video B-Roll Generation Service — Phase 3.1 (Replicate Edition)
========================================================================
Generates short portrait B-roll clips from text prompts via Replicate API.

GPU constraint: 4 GB VRAM — no local diffusion models are viable.
All T2V generation is therefore routed through Replicate's hosted endpoints.

Models available via Replicate (zero local VRAM):
  - thudm/cogvideox-5b          — best quality, ~30s per clip
  - wan-ai/wan2.1-t2v-720p      — fast, 720p portrait
  - ali-vilab/i2vgen-xl         — image-to-video (I2V)

Configuration:
  REPLICATE_API_TOKEN — required (get from replicate.com)
  T2V_ENABLED         — must be "true" to activate (default: false)
  T2V_MODEL           — "cogvideox" | "wan21" | "i2vgen" (default: cogvideox)
  T2V_RESOLUTION      — "480p" | "720p" | "1080p" (default: 720p)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
T2V_MODEL       = os.environ.get("T2V_MODEL", "cogvideox")
T2V_RESOLUTION  = os.environ.get("T2V_RESOLUTION", "720p")
TEMP_DIR        = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads"))
REPLICATE_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
T2V_ENABLED     = os.environ.get("T2V_ENABLED", "false").lower() == "true"

_REPLICATE_BASE = "https://api.replicate.com/v1"
_POLL_INTERVAL  = 3.0     # seconds between status polls
_MAX_WAIT_S     = 300     # max wait for generation to complete

_MODEL_VERSIONS: dict[str, str] = {
    "cogvideox": "thudm/cogvideox-5b",
    "wan21":     "wan-ai/wan2.1-t2v-720p",
    "i2vgen":    "ali-vilab/i2vgen-xl",
}

_RES_MAP = {
    "480p":  (480, 848),
    "720p":  (720, 1280),
    "1080p": (1080, 1920),
}


class T2VBrollService:
    """
    Generate portrait B-roll clips from text prompts via Replicate API.

    Disabled by default (T2V_ENABLED=false). No local model loading occurs.
    Requires REPLICATE_API_TOKEN env var when enabled.
    """

    def __init__(self,
                 model: str = T2V_MODEL,
                 resolution: str = T2V_RESOLUTION):
        self.model      = model
        self.resolution = resolution
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
        Generate a B-roll clip from *prompt* via Replicate.

        Returns:
            {"clip_path": str, "duration": float, "model": str}

        Raises RuntimeError if T2V is disabled or REPLICATE_API_TOKEN not set.
        """
        from ..config import get_config
        cfg = get_config()
        if not cfg.replicate_enabled:
            logger.debug("[T2V] Replicate disabled (no API token)")
            return {"clip_path": None, "duration": 0.0, "model": self.model}
        if not T2V_ENABLED:
            raise RuntimeError("T2V disabled — set T2V_ENABLED=true to enable")
        if not REPLICATE_TOKEN:
            raise RuntimeError("REPLICATE_API_TOKEN not set")

        mdl = model or self.model
        res = resolution or self.resolution
        w, h = _RES_MAP.get(res, (720, 1280))

        if output_path is None:
            safe = "".join(c if c.isalnum() else "_" for c in prompt[:40])
            output_path = str(self.out_dir / f"t2v_{safe}_{int(time.time())}.mp4")

        full_prompt = (
            f"Cinematic 4K vertical footage of {prompt}, "
            f"smooth camera motion, professional quality, portrait orientation, "
            f"vibrant colors, no text, no watermarks"
        )

        model_id = _MODEL_VERSIONS.get(mdl, _MODEL_VERSIONS["cogvideox"])
        clip_path = await self._generate_via_replicate(
            prompt=full_prompt,
            model_id=model_id,
            output_path=Path(output_path),
            width=w,
            height=h,
            duration=duration,
        )

        actual_duration = duration
        logger.info("[T2V] ✓ Replicate generated %s (%.1fs, %s)", clip_path.name, actual_duration, mdl)
        return {"clip_path": str(clip_path), "duration": actual_duration, "model": f"replicate/{mdl}"}

    # ── Replicate API ─────────────────────────────────────────────────────────

    async def _generate_via_replicate(
        self,
        prompt: str,
        model_id: str,
        output_path: Path,
        width: int,
        height: int,
        duration: float,
    ) -> Path:
        """POST to Replicate, poll until done, download output video."""
        headers = {
            "Authorization": f"Bearer {REPLICATE_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "version": model_id,
            "input": {
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_frames": max(8, int(duration * 8)),
                "num_inference_steps": 30,
                "guidance_scale": 6.0,
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            # Create prediction
            resp = await client.post(
                f"{_REPLICATE_BASE}/predictions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            prediction = resp.json()
            pred_id = prediction["id"]
            logger.info("[T2V] Replicate prediction created: %s", pred_id)

            # Poll for completion
            poll_url = f"{_REPLICATE_BASE}/predictions/{pred_id}"
            deadline = time.monotonic() + _MAX_WAIT_S
            while time.monotonic() < deadline:
                await asyncio.sleep(_POLL_INTERVAL)
                poll_resp = await client.get(poll_url, headers=headers)
                poll_resp.raise_for_status()
                data = poll_resp.json()
                status = data.get("status")
                logger.debug("[T2V] Replicate status: %s", status)
                if status == "succeeded":
                    output = data.get("output")
                    video_url = output if isinstance(output, str) else (output[0] if output else None)
                    if not video_url:
                        raise RuntimeError("Replicate returned no output URL")
                    # Download the video
                    dl_resp = await client.get(video_url)
                    dl_resp.raise_for_status()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(dl_resp.content)
                    return output_path
                if status in ("failed", "canceled"):
                    err = data.get("error", "unknown error")
                    raise RuntimeError(f"Replicate prediction {status}: {err}")

            raise RuntimeError(f"Replicate generation timed out after {_MAX_WAIT_S}s")

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def is_available() -> bool:
        """True if Replicate API is configured and T2V is enabled."""
        return T2V_ENABLED and bool(REPLICATE_TOKEN)
