"""
ComfyUI Bridge for LTX-Video Integration

Lightweight bridge connecting ViraClip to ComfyUI for LTX-Video I2V generation.
"""

import os
import json
import base64
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COMFYUI_ENABLED: bool = os.environ.get("COMFYUI_ENABLED", "false").lower() == "true"
COMFYUI_TIMEOUT: float = float(os.environ.get("COMFYUI_TIMEOUT", "90.0"))
COMFYUI_OUTPUT_DIR: str = os.environ.get("COMFYUI_LOCAL_OUTPUT_DIR", "/app/temp/uploads/comfy_out")


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
        """Check if ComfyUI is reachable via /system_stats endpoint with 3s timeout."""
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
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Generate LTX-Video intro from a single frame using ComfyUI workflow.

        Args:
            first_frame_path: Path to the first frame image (PNG/JPG)
            theme: Theme description for the prompt
            output_path: Where to save the generated video
            timeout: Max time to wait for generation (default: COMFYUI_TIMEOUT env var or 90s)

        Returns:
            True if video was generated and saved successfully
        """
        _timeout = timeout or COMFYUI_TIMEOUT
        _temp_files: list[Path] = []
        try:
            # Read and encode image to base64
            image_data = first_frame_path.read_bytes()
            image_b64 = base64.b64encode(image_data).decode("utf-8")

            workflow = {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "ltxv-2b-0.9.8-distilled-fp8.safetensors"},
                },
                "2": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "clip": ["1", 1],
                        "text": f"cinematic {theme} short intro, vertical 9:16, dynamic motion, high quality",
                    },
                },
                "3": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "clip": ["1", 1],
                        "text": "static, blur, low quality, watermark, text",
                    },
                },
                "4": {
                    "class_type": "LoadImage",
                    "inputs": {"image": image_b64},
                },
                "5": {
                    "class_type": "LTXVAddLatentGuide",
                    "inputs": {
                        "positive": ["2", 0],
                        "negative": ["3", 0],
                        "vae": ["1", 2],
                        "image": ["4", 0],
                        "latent": ["6", 0],
                        "guiding_latent": ["6", 0],
                        "strength": 1.0,
                        "latent_idx": 0,
                    },
                },
                "6": {
                    "class_type": "EmptyLTXVLatentVideo",
                    "inputs": {
                        "width": 576,
                        "height": 1024,
                        "length": 33,
                        "batch_size": 1,
                    },
                },
                "7": {
                    "class_type": "BasicGuider",
                    "inputs": {
                        "model": ["1", 0],
                        "conditioning": ["5", 0],
                    },
                },
                "8": {
                    "class_type": "KSamplerSelect",
                    "inputs": {"sampler_name": "euler"},
                },
                "9": {
                    "class_type": "BasicScheduler",
                    "inputs": {
                        "model": ["1", 0],
                        "scheduler": "sgm_uniform",
                        "steps": 20,
                        "denoise": 0.85,
                    },
                },
                "10": {
                    "class_type": "RandomNoise",
                    "inputs": {"noise_seed": 42},
                },
                "11": {
                    "class_type": "SamplerCustomAdvanced",
                    "inputs": {
                        "noise": ["10", 0],
                        "guider": ["7", 0],
                        "sampler": ["8", 0],
                        "sigmas": ["9", 0],
                        "latent_image": ["5", 2],
                    },
                },
                "12": {
                    "class_type": "VAEDecode",
                    "inputs": {
                        "vae": ["1", 2],
                        "samples": ["11", 0],
                    },
                },
                "13": {
                    "class_type": "VHS_VideoCombine",
                    "inputs": {
                        "images": ["12", 0],
                        "frame_rate": 24,
                        "loop_count": 0,
                        "filename_prefix": "ltxv_intro",
                        "format": "video/h264-mp4",
                        "pix_fmt": "yuv420p",
                        "save_output": True,
                        "pingpong": False,
                    },
                },
            }

            # Queue the workflow with timeout
            payload = {"prompt": workflow, "client_id": self._generate_client_id()}
            resp = await asyncio.wait_for(
                self.client.post(
                    f"{self.base_url}/prompt",
                    json=payload,
                    timeout=10.0,
                ),
                timeout=_timeout,
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

            # Poll for completion with asyncio.wait_for
            video_filename = await asyncio.wait_for(
                self._poll_for_video(prompt_id, _timeout),
                timeout=_timeout,
            )
            if not video_filename:
                logger.error("[ComfyUIBridge] No video output after polling")
                return False

            # Download the video
            return await self._download_video(video_filename, output_path)

        except asyncio.TimeoutError:
            logger.error("[ComfyUIBridge] Generation timed out after %.0fs", _timeout)
            return False
        except Exception as exc:
            logger.error("[ComfyUIBridge] generate_ltxv_intro failed: %s", exc)
            return False
        finally:
            # Clean up ComfyUI temp output files to prevent disk accumulation
            self._cleanup_temp_files()

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

                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    logger.error("[ComfyUIBridge] Workflow execution error")
                    return ""

                outputs = entry.get("outputs", {})
                node_13_output = outputs.get("13", {})
                if node_13_output:
                    videos = node_13_output.get("videos", [])
                    if videos:
                        filename = videos[0].get("filename", "")
                        if filename:
                            logger.info("[ComfyUIBridge] Video ready: %s", filename)
                            return filename

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

    def _cleanup_temp_files(self) -> None:
        """Clean up ComfyUI output files older than 1 hour to prevent disk accumulation."""
        try:
            _output_dir = Path(COMFYUI_OUTPUT_DIR)
            if not _output_dir.exists():
                return
            _cutoff = asyncio.get_event_loop().time() - 3600
            _removed = 0
            for f in _output_dir.iterdir():
                if f.is_file() and f.stat().st_mtime < _cutoff:
                    f.unlink(missing_ok=True)
                    _removed += 1
            if _removed > 0:
                logger.debug("[ComfyUIBridge] Cleaned up %d old temp files from %s", _removed, _output_dir)
        except Exception as _cln_e:
            logger.debug("[ComfyUIBridge] Temp cleanup skipped: %s", _cln_e)


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
    logger.error("[comfyui_bridge] generate_broll() is DEPRECATED and non-operational — use ComfyUIBridge.generate_ltxv_intro() instead. Called with prompt='%s', duration=%.1f", prompt, duration)
    import warnings
    warnings.warn(
        "generate_broll() is deprecated and non-operational. Use ComfyUIBridge.generate_ltxv_intro() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return None
