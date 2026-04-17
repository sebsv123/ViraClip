"""
ComfyUI Integration Service for ViraClip
Handles AI-powered video processing using ComfyUI backend
"""

import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import asyncio

from .comfyui.orchestrator import comfyui_orchestrator
from .video_service import VideoService as video_service
from ..core.logger import setup_logger as get_logger

logger = get_logger(__name__)


class ComfyUIIntegrationService:
    """
    Integrates ComfyUI AI workflows into ViraClip pipeline.
    Optimized for RTX 5070 8GB VRAM
    """
    
    def __init__(self):
        self.orchestrator = comfyui_orchestrator
        self.enabled = os.getenv("COMFYUI_ENABLED", "true").lower() == "true"
        self.uploads_path = Path(os.getenv("VIRA_UPLOADS", "./uploads"))
        self.outputs_path = Path(os.getenv("VIRA_OUTPUTS", "./outputs"))
    
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
            # Copy video to ComfyUI input directory
            comfy_input = f"/comfyui/input/{task_id}.mp4"
            local_input = self.uploads_path / f"{task_id}.mp4"
            
            if progress_callback:
                await progress_callback(10, f"Preparing {operation}...")
            
            # Ensure file is accessible to ComfyUI container
            if not local_input.exists():
                shutil.copy2(video_path, local_input)
            
            # Execute appropriate workflow
            if operation == "subtitles":
                result = await self.orchestrator.subtitles(
                    str(local_input), task_id
                )
            elif operation == "reframe_9_16":
                chunk_size = kwargs.get("chunk_size", 300)
                result = await self.orchestrator.reframe_9_16(
                    str(local_input), task_id, chunk_size
                )
            elif operation == "thumbnail":
                prompt = kwargs.get("prompt", "cinematic viral thumbnail")
                result = await self.orchestrator.thumbnail(
                    str(local_input), task_id, prompt
                )
            elif operation == "broll_transition":
                broll_path = kwargs.get("broll_path")
                transition_type = kwargs.get("transition_type", "fade")
                duration = kwargs.get("duration", 1.0)
                
                # Copy broll if provided
                if broll_path and Path(broll_path).exists():
                    broll_dest = self.uploads_path / f"{task_id}_broll.mp4"
                    shutil.copy2(broll_path, broll_dest)
                
                result = await self.orchestrator.add_broll_transition(
                    str(local_input),
                    str(broll_dest) if broll_path else str(local_input),
                    task_id,
                    transition_type,
                    duration
                )
            else:
                logger.error(f"Unknown operation: {operation}")
                return None
            
            if progress_callback:
                await progress_callback(90, f"{operation} complete")
            
            # Return path to result
            if result:
                output_file = self.outputs_path / f"{task_id}_{operation}.mp4"
                return output_file
            
            return None
            
        except Exception as e:
            logger.error(f"ComfyUI {operation} failed: {e}", exc_info=True)
            return None
    
    async def enhance_clip_with_ai(
        self,
        task_id: str,
        clip_path: Path,
        options: Dict[str, Any],
        progress_callback: Optional[Callable] = None
    ) -> Path:
        """
        Enhance a clip with AI features
        
        Options:
            - reframe_9_16: Convert to vertical format
            - enhance_thumbnail: Generate AI thumbnail
            - add_broll: Add B-roll transitions
        """
        current_path = clip_path
        
        if options.get("reframe_9_16"):
            if progress_callback:
                await progress_callback(30, "Reframing to 9:16...")
            
            result = await self.process_with_comfyui(
                task_id, current_path, "reframe_9_16",
                progress_callback
            )
            if result:
                current_path = result
        
        if options.get("enhance_thumbnail"):
            if progress_callback:
                await progress_callback(60, "Generating AI thumbnail...")
            
            await self.process_with_comfyui(
                f"{task_id}_thumb", current_path, "thumbnail",
                progress_callback,
                prompt=options.get("thumbnail_prompt", "cinematic viral thumbnail")
            )
        
        if options.get("add_broll"):
            if progress_callback:
                await progress_callback(80, "Adding B-roll transitions...")
            
            # This would integrate with existing B-roll logic
            pass
        
        return current_path
    
    async def health_check(self) -> bool:
        """Check if ComfyUI is available"""
        try:
            health = await self.orchestrator.health_check()
            return health.get("status") == "ok"
        except Exception as e:
            logger.warning(f"ComfyUI health check failed: {e}")
            return False


# Global instance
comfyui_integration = ComfyUIIntegrationService()
