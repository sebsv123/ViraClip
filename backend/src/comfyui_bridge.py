"""
ComfyUI Bridge for LTX-Video Integration

Lightweight bridge connecting ViraClip to ComfyUI for LTX-Video I2V generation.
"""

import os
import json
import base64
import asyncio
import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COMFYUI_ENABLED: bool = os.environ.get("COMFYUI_ENABLED", "true").lower() == "true"


class ComfyUIBridge:
    """
    Bridge to ComfyUI API for LTX-Video intro generation.

    Public methods:
        is_available() -> bool
        generate_ltxv_intro(first_frame_path, theme, output_path, timeout) -> bool
        close() -> None
    """

    def __init__(self):
        self.host = os.environ.get("COMFYUI_HOST", "localhost")
        self.port = int(os.environ.get("COMFYUI_PORT", "8188"))
        self.base_url = f"http://{self.host}:{self.port}"
        self.client = httpx.AsyncClient(timeout=10.0)
        logger.debug("[ComfyUIBridge] Initialized with base_url=%s", self.base_url)

    async def is_available(self) -> bool:
        """Check if ComfyUI is reachable via /system_stats endpoint."""
        try:
            resp = await self.client.get(
                f"{self.base_url}/system_stats",
                timeout=3.0,
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("[ComfyUIBridge] is_available failed: %s", exc)
            return False

    async def generate_ltxv_intro(
        self,
        first_frame_path: Path,
        theme: str,
        output_path: Path,
        timeout: float = 90.0,
    ) -> bool:
        """
        Generate LTX-Video intro from a single frame using ComfyUI workflow.

        Args:
            first_frame_path: Path to the first frame image (PNG/JPG)
            theme: Theme description for the prompt
            output_path: Where to save the generated video
            timeout: Max time to wait for generation

        Returns:
            True if video was generated and saved successfully
        """
        try:
            # Read and encode image to base64
            image_data = first_frame_path.read_bytes()
            image_b64 = base64.b64encode(image_data).decode("utf-8")

            # Build LTX-Video I2V workflow
            workflow = {
                "1": {
                    "class_type": "LTXVLoader",
                    "inputs": {"model": "ltx-video-2b-v0.9.5.safetensors"},
                },
                "2": {
                    "class_type": "LoadImage",
                    "inputs": {"image": image_b64},
                },
                "3": {
                    "class_type": "LTXVConditioning",
                    "inputs": {
                        "positive": f"cinematic {theme} short intro, vertical 9:16, dynamic motion",
                        "negative": "static, blur, low quality",
                        "image": ["2", 0],
                        "frame_rate": 24,
                        "length": 33,
                    },
                },
                "4": {
                    "class_type": "KSampler",
                    "inputs": {
                        "model": ["1", 0],
                        "positive": ["3", 0],
                        "negative": ["3", 1],
                        "latent_image": ["3", 2],
                        "seed": 42,
                        "steps": 20,
                        "cfg": 3.0,
                        "sampler_name": "euler",
                        "scheduler": "sgm_uniform",
                        "denoise": 0.85,
                    },
                },
                "5": {
                    "class_type": "VHS_VideoCombine",
                    "inputs": {
                        "images": ["4", 0],
                        "frame_rate": 24,
                        "loop_count": 0,
                        "filename_prefix": "ltxv_intro",
                        "format": "video/h264-mp4",
                        "save_output": True,
                    },
                },
            }

            # Queue the workflow
            payload = {"prompt": workflow, "client_id": self._generate_client_id()}
            resp = await self.client.post(
                f"{self.base_url}/prompt",
                json=payload,
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.error("[ComfyUIBridge] Failed to queue prompt: %s", resp.text)
                return False

            data = resp.json()
            prompt_id = data.get("prompt_id", "")
            if not prompt_id:
                logger.error("[ComfyUIBridge] No prompt_id in response")
                return False

            logger.info("[ComfyUIBridge] Queued LTXV intro generation: %s", prompt_id)

            # Poll for completion
            video_filename = await self._poll_for_video(prompt_id, timeout)
            if not video_filename:
                logger.error("[ComfyUIBridge] No video output after polling")
                return False

            # Download the video
            return await self._download_video(video_filename, output_path)

        except Exception as exc:
            logger.error("[ComfyUIBridge] generate_ltxv_intro failed: %s", exc)
            return False

    async def close(self) -> None:
        """Close the httpx client."""
        await self.client.aclose()
        logger.debug("[ComfyUIBridge] Client closed")

    # ── Internal helpers ───────────────────────────────────────────────────

    def _generate_client_id(self) -> str:
        """Generate unique client ID for ComfyUI session."""
        import uuid
        return str(uuid.uuid4())

    async def _poll_for_video(self, prompt_id: str, timeout: float) -> str:
        """Poll /history/{prompt_id} until video is ready or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        poll_interval = 2.0

        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await self.client.get(
                    f"{self.base_url}/history/{prompt_id}",
                    timeout=5.0,
                )
                if resp.status_code != 200:
                    await asyncio.sleep(poll_interval)
                    continue

                data = resp.json()
                entry = data.get(prompt_id, {})
                if not entry:
                    await asyncio.sleep(poll_interval)
                    continue

                # Check for error status
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    logger.error("[ComfyUIBridge] Workflow execution error")
                    return ""

                # Look for video output in node 5 (VHS_VideoCombine)
                outputs = entry.get("outputs", {})
                node_5_output = outputs.get("5", {})
                if node_5_output:
                    videos = node_5_output.get("videos", [])
                    if videos:
                        filename = videos[0].get("filename", "")
                        if filename:
                            logger.info("[ComfyUIBridge] Video ready: %s", filename)
                            return filename

                # Check other nodes for video output
                for node_id, node_output in outputs.items():
                    if not isinstance(node_output, dict):
                        continue
                    for key, value in node_output.items():
                        if isinstance(value, list) and value:
                            for item in value:
                                if isinstance(item, dict):
                                    fname = item.get("filename", "")
                                    if fname and fname.endswith(".mp4"):
                                        logger.info("[ComfyUIBridge] Video found in node %s: %s", node_id, fname)
                                        return fname

            except Exception as exc:
                logger.debug("[ComfyUIBridge] Poll error: %s", exc)

            await asyncio.sleep(poll_interval)

        logger.error("[ComfyUIBridge] Polling timeout after %.0fs", timeout)
        return ""

    async def _download_video(self, filename: str, output_path: Path) -> bool:
        """Download video from ComfyUI /view endpoint."""
        try:
            url = f"{self.base_url}/view?filename={filename}&type=output"
            resp = await self.client.get(url, timeout=30.0)

            if resp.status_code != 200:
                logger.error("[ComfyUIBridge] Download failed: HTTP %s", resp.status_code)
                return False

            output_path.write_bytes(resp.content)

            if output_path.exists() and output_path.stat().st_size > 0:
                logger.info("[ComfyUIBridge] ✓ Video saved to %s (%d bytes)", output_path, output_path.stat().st_size)
                return True

            logger.error("[ComfyUIBridge] Output file empty or missing")
            return False

        except Exception as exc:
            logger.error("[ComfyUIBridge] Download error: %s", exc)
            return False


# Module-level helper functions for backward compatibility
_bridge_instance: Optional[ComfyUIBridge] = None

async def is_available() -> bool:
    """Check if ComfyUI is available (module-level helper)."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = ComfyUIBridge()
    return await _bridge_instance.is_available()


async def generate_broll(prompt: str, duration: float = 3.0, output_path: Optional[Path] = None) -> Optional[str]:
    """
    Generate B-roll using ComfyUI (module-level helper).
    Note: This is a simplified placeholder. For LTX-Video generation,
    use ComfyUIBridge.generate_ltxv_intro() directly.
    """
    logger.warning("[comfyui_bridge] generate_broll() is deprecated, use ComfyUIBridge.generate_ltxv_intro()")
    return None

