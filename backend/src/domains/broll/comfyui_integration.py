"""
ComfyUI Integration Service for ViraClip
Handles AI-powered video processing using ComfyUI backend

Updated: 2026-04-23 - Lazy imports for CI compatibility
"""

import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import asyncio
import logging

logger = logging.getLogger(__name__)

# Lazy imports - se cargan dentro de los métodos para evitar errores en CI
_comfyui_orchestrator = None
_video_service = None

def _get_orchestrator():
    """Lazy load orchestrator to avoid import errors in CI."""
    global _comfyui_orchestrator
    if _comfyui_orchestrator is None:
        from .comfyui.orchestrator import comfyui_orchestrator
        _comfyui_orchestrator = comfyui_orchestrator
    return _comfyui_orchestrator


class ComfyUIIntegrationService:
    """
    Integrates ComfyUI AI workflows into ViraClip pipeline.
    Optimized for RTX 5070 8GB VRAM
    """
    
    def __init__(self):
        self.enabled = os.getenv("COMFYUI_ENABLED", "true").lower() == "true"
        # Shared `uploads` volume: worker=/app/temp/uploads/broll -> comfyui=/comfyui/input
        self.uploads_path = Path(
            os.getenv("VIRA_UPLOADS", os.getenv("COMFYUI_SHARED_INPUT_DIR", "/app/temp/uploads/broll"))
        )
        self.uploads_path.mkdir(parents=True, exist_ok=True)
        self.outputs_path = Path(os.getenv("VIRA_OUTPUTS", "/app/temp/uploads/comfy_out"))
        self.outputs_path.mkdir(parents=True, exist_ok=True)
    
    async def process_with_comfyui(
        self,
        task_id: str,
        video_path: Path,
        operation: str,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> Optional[Path]:
        """
        Process video using ComfyUI
        
        Args:
            task_id: Unique task identifier
            video_path: Path to input video
            operation: One of: subtitles, reframe_9_16, thumbnail, broll_transition
            progress_callback: Optional callback for progress updates
            **kwargs: Additional parameters for specific operations
        
        Returns:
            Path to output file or None if failed
        """
        if not self.enabled:
            logger.info(f"ComfyUI disabled, skipping {operation}")
            return None
        
        try:
            # Copy video to ComfyUI input directory (solo si hay input video)
            local_input = self.uploads_path / f"{task_id}.mp4"

            if progress_callback:
                await progress_callback(10, f"Preparing {operation}...")

            # Operaciones text-to-video (ej. broll_generate) no necesitan input.
            if video_path is not None and not local_input.exists():
                shutil.copy2(video_path, local_input)
            
            # Execute appropriate workflow with lazy-loaded orchestrator
            orchestrator = _get_orchestrator()
            
            if operation == "broll_generate":
                # Generate a pure B-roll clip from a text prompt (LTX-Video).
                # No input video needed, no concatenation. Returns path of the
                # synthetic clip so the caller can insert it wherever it wants.
                prompt = kwargs.get("prompt") or "cinematic B-roll footage, smooth motion"
                duration_s = float(kwargs.get("duration", 3.0))
                width = int(kwargs.get("width", 768))
                height = int(kwargs.get("height", 512))
                result = await orchestrator.generate_broll_with_ltx(
                    prompt=prompt,
                    task_id=task_id,
                    duration_seconds=duration_s,
                    width=width,
                    height=height,
                )
            elif operation == "subtitles":
                result = await orchestrator.subtitles(
                    str(local_input), task_id
                )
            elif operation == "reframe_9_16":
                chunk_size = kwargs.get("chunk_size", 300)
                result = await orchestrator.reframe_9_16(
                    str(local_input), task_id, chunk_size
                )
            elif operation == "thumbnail":
                prompt = kwargs.get("prompt", "cinematic viral thumbnail")
                result = await orchestrator.thumbnail(
                    str(local_input), task_id, prompt
                )
            elif operation == "broll_transition":
                broll_path = kwargs.get("broll_path")
                transition_type = kwargs.get("transition_type", "fade")
                duration = kwargs.get("duration", 1.0)
                
                # Copy broll if provided
                broll_dest = None
                if broll_path and Path(broll_path).exists():
                    broll_dest = self.uploads_path / f"{task_id}_broll.mp4"
                    shutil.copy2(broll_path, broll_dest)
                
                result = await orchestrator.add_broll_transition(
                    main_clip=str(local_input),
                    task_id=task_id,
                    broll_clip=str(broll_dest) if broll_dest else str(local_input),
                    transition_type=transition_type,
                    duration=duration,
                )
            else:
                logger.error(f"Unknown operation: {operation}")
                return None
            
            if progress_callback:
                await progress_callback(90, f"{operation} complete")

            # El orchestrator ya devuelve un path local descargado vía /view.
            # Lo propagamos tal cual; fabricar otro path aquí era un bug que
            # hacía que `Path(result).exists()` fallase siempre en el caller.
            if result:
                result_path = Path(result)
                if result_path.exists():
                    return result_path
                logger.warning(
                    f"[ComfyUI] operation={operation} returned path that "
                    f"does not exist: {result}"
                )
                return None

            return None
            
        except Exception as e:
            logger.error(f"ComfyUI {operation} failed: {e}", exc_info=True)
            return None
    
    async def health_check(self) -> bool:
        """Check if ComfyUI is available"""
        try:
            orchestrator = _get_orchestrator()
            health = await orchestrator.health_check()
            return health.get("status") == "ok"
        except Exception as e:
            logger.warning(f"ComfyUI health check failed: {e}")
            return False


# Global instance
comfyui_integration = ComfyUIIntegrationService()
