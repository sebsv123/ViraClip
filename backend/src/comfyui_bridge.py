"""
ViraClip-ComfyUI API Bridge
============================
Integrates ViraClip FastAPI backend with ComfyUI's workflow execution system.

Key public API:
    bridge = ComfyUIBridge()
    ok     = await bridge.is_available()
    result = await bridge.enhance_video("/path/to/clip.mp4", "/path/to/enhanced.mp4")
    broll  = await bridge.generate_broll("tech innovation startup", "/path/to/broll.mp4", duration=2.0)
"""

import os
import json
import copy
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
import aiohttp
import uuid

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
COMFYUI_ENABLED  = os.environ.get("COMFYUI_ENABLED", "false").lower() not in ("false", "0", "no")
COMFYUI_HOST     = os.environ.get("COMFYUI_HOST", "comfyui")
COMFYUI_PORT     = int(os.environ.get("COMFYUI_PORT", "8188"))
COMFYUI_API_URL  = os.environ.get("COMFYUI_API_URL", f"http://{COMFYUI_HOST}:{COMFYUI_PORT}")
COMFYUI_TIMEOUT  = float(os.environ.get("COMFYUI_TIMEOUT", "600"))

# Workflow JSON directory — mounted at /app/comfy_workflows inside worker containers
_LOCAL_WORKFLOWS = Path(__file__).parent.parent / "comfy_workflows"
WORKFLOWS_DIR = Path(os.environ.get("WORKFLOWS_DIR", str(_LOCAL_WORKFLOWS)))


@dataclass
class WorkflowResult:
    """Result from a single ComfyUI workflow execution."""
    prompt_id: str
    status: str          # "pending" | "running" | "completed" | "error"
    outputs: Dict[str, Any]
    execution_time: Optional[float] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ComfyUIBridge:
    """
    Production bridge between ViraClip workers and a running ComfyUI instance.

    Public high-level methods
    ─────────────────────────
    is_available()                    → bool
    enhance_video(src, dst)           → Path | None
    generate_broll(prompt, dst, dur)  → Path | None
    execute_workflow(name, inputs)    → WorkflowResult
    """

    def __init__(self, base_url: str = COMFYUI_API_URL):
        self.base_url = base_url.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

    # ── Session management ────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=COMFYUI_TIMEOUT),
            )
        return self.session

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # ── Availability check ────────────────────────────────────────────────────

    async def is_available(self, timeout: float = 5.0) -> bool:
        """Return True if ComfyUI is reachable and healthy."""
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/system_stats",
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ── File upload / download ────────────────────────────────────────────────

    async def upload_file(self, local_path: Path, subfolder: str = "input") -> str:
        """
        Upload a file to ComfyUI's /upload/image endpoint.
        Returns the filename as ComfyUI stored it (used as node input value).
        """
        session = await self._get_session()
        data = aiohttp.FormData()
        data.add_field(
            "image",
            open(str(local_path), "rb"),
            filename=local_path.name,
            content_type="application/octet-stream",
        )
        data.add_field("subfolder", subfolder)
        data.add_field("type", "input")
        async with session.post(f"{self.base_url}/upload/image", data=data) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"Upload failed: {resp.status} {await resp.text()}")
            result = await resp.json()
            return result.get("name", local_path.name)

    async def download_output(self, filename: str, dest: Path, subfolder: str = "output") -> bool:
        """Download an output file from ComfyUI and save to *dest*."""
        url = f"{self.base_url}/view?filename={filename}&subfolder={subfolder}&type=output"
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                dest.write_bytes(await resp.read())
                return True
        except Exception as exc:
            logger.debug(f"[ComfyUI] download_output error: {exc}")
            return False

    # ── High-level pipeline methods ───────────────────────────────────────────

    async def enhance_video(
        self,
        video_path: Path,
        output_path: Path,
        timeout: float = 600.0,
    ) -> Optional[Path]:
        """
        Run Real-ESRGAN x2 upscaling + face-aware sharpening on a clip.
        Returns output_path on success, None if ComfyUI is unavailable.
        """
        if not await self.is_available():
            logger.debug("[ComfyUI] enhance_video skipped — ComfyUI not available")
            return None
        try:
            remote_name = await self.upload_file(video_path)
            result = await self.execute_workflow(
                "enhance_video",
                {"__INPUT_VIDEO__": remote_name},
                timeout=timeout,
            )
            if result.status != "completed":
                logger.warning(f"[ComfyUI] enhance_video workflow error: {result.error_message}")
                return None

            out_file = self._first_video_output(result.outputs)
            if not out_file:
                logger.warning("[ComfyUI] enhance_video: no video in outputs")
                return None

            ok = await self.download_output(out_file, output_path)
            if ok and output_path.exists() and output_path.stat().st_size > 10_000:
                logger.info(f"[ComfyUI] ✓ Video enhanced → {output_path.name}")
                return output_path
            return None
        except Exception as exc:
            logger.warning(f"[ComfyUI] enhance_video failed: {exc}")
            return None

    async def generate_broll(
        self,
        prompt: str,
        output_path: Path,
        duration: float = 2.0,
        timeout: float = 300.0,
    ) -> Optional[Path]:
        """
        Generate B-Roll video from a text prompt via AnimateDiff.
        Returns output_path on success, None if ComfyUI is unavailable.
        """
        if not await self.is_available():
            logger.debug("[ComfyUI] generate_broll skipped — ComfyUI not available")
            return None
        try:
            n_frames = max(8, min(32, int(duration * 8)))  # ~8fps
            full_prompt = (
                f"{prompt}, cinematic, professional, high quality, "
                f"sharp focus, vibrant colors, 4k, portrait orientation"
            )
            result = await self.execute_workflow(
                "generate_broll",
                {
                    "__POSITIVE_PROMPT__": full_prompt,
                    "__N_FRAMES__": n_frames,
                },
                timeout=timeout,
            )
            if result.status != "completed":
                logger.warning(f"[ComfyUI] generate_broll workflow error: {result.error_message}")
                return None

            out_file = self._first_video_output(result.outputs)
            if not out_file:
                return None

            ok = await self.download_output(out_file, output_path)
            if ok and output_path.exists() and output_path.stat().st_size > 5_000:
                logger.info(f"[ComfyUI] ✓ B-Roll generated ({prompt[:40]}) → {output_path.name}")
                return output_path
            return None
        except Exception as exc:
            logger.warning(f"[ComfyUI] generate_broll failed: {exc}")
            return None

    # ── Generic workflow execution ────────────────────────────────────────────

    async def execute_workflow(
        self,
        workflow_name: str,
        inputs: Dict[str, Any],
        wait_for_completion: bool = True,
        timeout: float = COMFYUI_TIMEOUT,
    ) -> WorkflowResult:
        """Load a workflow JSON, inject placeholder values, queue it and poll to completion."""
        try:
            wf = self._load_workflow(workflow_name)
            if wf is None:
                return WorkflowResult("", "error", {}, error_message=f"Workflow not found: {workflow_name}")
            wf = self._inject_inputs(wf, inputs)
            prompt_id = await self._queue_prompt(wf)
            if not wait_for_completion:
                return WorkflowResult(prompt_id, "pending", {})
            return await self._wait_for_completion(prompt_id, timeout)
        except Exception as exc:
            logger.error(f"[ComfyUI] execute_workflow '{workflow_name}' failed: {exc}")
            return WorkflowResult("", "error", {}, error_message=str(exc))
    
    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_workflow(self, name: str) -> Optional[Dict[str, Any]]:
        """Load a workflow JSON file from WORKFLOWS_DIR (try .json suffix automatically)."""
        for candidate in [
            WORKFLOWS_DIR / f"{name}.json",
            WORKFLOWS_DIR / name,
            Path(name) if Path(name).is_absolute() else None,
        ]:
            if candidate and candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.error(f"[ComfyUI] Failed to parse {candidate}: {exc}")
        logger.error(f"[ComfyUI] Workflow not found: {name} (looked in {WORKFLOWS_DIR})")
        return None

    def _inject_inputs(self, workflow: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Walk the ComfyUI API-format workflow dict (node_id → node) and replace
        placeholder strings like __KEY__ with values from *inputs*.
        Also patches EmptyLatentImage batch_size when __N_FRAMES__ is provided.
        """
        wf = copy.deepcopy(workflow)
        n_frames = inputs.get("__N_FRAMES__")
        for node_id, node in wf.items():
            if not isinstance(node, dict):
                continue
            node_inputs = node.get("inputs", {})
            if not isinstance(node_inputs, dict):
                continue
            for k, v in list(node_inputs.items()):
                if isinstance(v, str):
                    for placeholder, replacement in inputs.items():
                        if placeholder in v:
                            node_inputs[k] = v.replace(placeholder, str(replacement))
            if n_frames and node.get("class_type") == "EmptyLatentImage":
                node_inputs["batch_size"] = int(n_frames)
        return wf

    async def _queue_prompt(self, workflow: Dict[str, Any]) -> str:
        """POST workflow to /prompt and return the prompt_id."""
        session = await self._get_session()
        payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
        async with session.post(f"{self.base_url}/prompt", json=payload) as resp:
            if resp.status != 200:
                raise RuntimeError(f"queue_prompt failed {resp.status}: {await resp.text()}")
            data = await resp.json()
            pid = data.get("prompt_id", "")
            logger.debug(f"[ComfyUI] Queued prompt {pid}")
            return pid

    async def _wait_for_completion(self, prompt_id: str, timeout: float) -> WorkflowResult:
        """Poll /history/{id} until the prompt completes or times out."""
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        while True:
            elapsed = loop.time() - t0
            if elapsed > timeout:
                return WorkflowResult(prompt_id, "error", {}, error_message=f"Timeout after {timeout:.0f}s")
            session = await self._get_session()
            try:
                async with session.get(f"{self.base_url}/history/{prompt_id}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        entry = data.get(prompt_id, {})
                        if entry:
                            status_str = entry.get("status", {}).get("status_str", "")
                            if status_str == "error":
                                return WorkflowResult(prompt_id, "error", {}, error_message="ComfyUI execution error")
                            outputs = entry.get("outputs", {})
                            if outputs:
                                return WorkflowResult(prompt_id, "completed", outputs, execution_time=elapsed)
            except Exception as exc:
                logger.debug(f"[ComfyUI] poll error: {exc}")
            await asyncio.sleep(2.0)

    def _first_video_output(self, outputs: Dict[str, Any]) -> Optional[str]:
        """Find the first .mp4 filename in ComfyUI output dict."""
        for node_outputs in outputs.values():
            if not isinstance(node_outputs, dict):
                continue
            for file_list in node_outputs.values():
                if not isinstance(file_list, list):
                    continue
                for item in file_list:
                    fname = item.get("filename", "") if isinstance(item, dict) else str(item)
                    if fname.endswith(".mp4") or fname.endswith(".webm"):
                        return fname
        return None

    async def get_system_stats(self) -> Dict[str, Any]:
        """Return GPU VRAM + queue info from ComfyUI /system_stats."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/system_stats") as resp:
                return await resp.json() if resp.status == 200 else {}
        except Exception:
            return {}

