"""
Speed Control Service - Wire smart_auto_editor.py speed ramp functions

Applies playback speed control and dramatic slow-mo to clips.
Uses existing ViralEditRules for speed ramping.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class SpeedControlService:
    """Apply speed control effects to video clips."""
    
    def __init__(self):
        self.enabled = True
    
    async def apply_speed_control(
        self,
        clip_path: Path,
        output_path: Path,
        playback_speed: float = 1.0,
        dramatic_slowmo: bool = False,
        hook_start: float = 0.0,
        hook_end: float = 3.0
    ) -> bool:
        """
        Apply global playback speed or dramatic slow-mo to clip.
        
        Args:
            clip_path: Input video
            output_path: Output video
            playback_speed: Global speed multiplier (0.5-2.0)
            dramatic_slowmo: Apply slow-mo to hook (first 3s)
            hook_start: Hook start time
            hook_end: Hook end time
            
        Returns:
            True if successful
        """
        if not clip_path.exists():
            return False
        
        try:
            if dramatic_slowmo and hook_end > hook_start:
                # Apply slow-mo to hook section only
                return await self._apply_hook_slowmo(
                    clip_path, output_path, hook_start, hook_end
                )
            elif playback_speed != 1.0:
                # Apply global speed change
                return await self._apply_global_speed(
                    clip_path, output_path, playback_speed
                )
            else:
                # No speed change needed
                return False
        
        except Exception as e:
            logger.error(f"Speed control error: {e}")
            return False
    
    async def _apply_global_speed(
        self,
        clip_path: Path,
        output_path: Path,
        speed: float
    ) -> bool:
        """Apply global playback speed using FFmpeg setpts."""
        try:
            # Calculate PTS multiplier (inverse of speed)
            pts_multiplier = 1.0 / speed
            
            # Audio tempo filter (preserve pitch)
            atempo_value = speed
            
            # FFmpeg may require chaining atempo for values >2.0 or <0.5
            atempo_filters = []
            if atempo_value > 2.0:
                # Chain multiple atempo filters
                while atempo_value > 2.0:
                    atempo_filters.append("atempo=2.0")
                    atempo_value /= 2.0
                atempo_filters.append(f"atempo={atempo_value}")
            elif atempo_value < 0.5:
                while atempo_value < 0.5:
                    atempo_filters.append("atempo=0.5")
                    atempo_value *= 2.0
                atempo_filters.append(f"atempo={atempo_value}")
            else:
                atempo_filters.append(f"atempo={atempo_value}")
            
            atempo_chain = ",".join(atempo_filters)
            
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(clip_path),
                "-filter:v", f"setpts={pts_multiplier}*PTS",
                "-filter:a", atempo_chain,
                str(output_path)
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await asyncio.wait_for(proc.communicate(), timeout=300.0)
            
            success = proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
            if success:
                logger.info(f"✓ Global speed applied: {speed}x")
            return success
        
        except asyncio.TimeoutError:
            logger.error("Speed control timeout")
            return False
        except Exception as e:
            logger.error(f"Global speed error: {e}")
            return False
    
    async def _apply_hook_slowmo(
        self,
        clip_path: Path,
        output_path: Path,
        hook_start: float,
        hook_end: float,
        slowmo_factor: float = 0.75
    ) -> bool:
        """Apply slow-mo to hook section (first 3 seconds)."""
        try:
            # Get video duration
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(clip_path)
            ]
            
            probe_proc = await asyncio.create_subprocess_exec(
                *probe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, _ = await probe_proc.communicate()
            total_duration = float(stdout.decode().strip())
            
            # Split video into 3 parts: before hook, hook (slow), after hook
            # This is complex, so for simplicity, apply slow-mo to entire first section
            
            # Simplified: just slow down first N seconds
            slowmo_duration = min(hook_end, 3.0)
            
            # Use setpts with segment filtering
            pts_multiplier = 1.0 / slowmo_factor
            
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(clip_path),
                "-filter_complex",
                f"[0:v]select='lt(t,{slowmo_duration})',setpts={pts_multiplier}*PTS[v_slow];"
                f"[0:v]select='gte(t,{slowmo_duration})',setpts=PTS-STARTPTS[v_normal];"
                f"[v_slow][v_normal]concat=n=2:v=1[v]",
                "-map", "[v]",
                "-map", "0:a",
                str(output_path)
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await asyncio.wait_for(proc.communicate(), timeout=300.0)
            
            success = proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
            if success:
                logger.info(f"✓ Hook slow-mo applied: {slowmo_factor}x for {slowmo_duration}s")
            return success
        
        except Exception as e:
            logger.error(f"Hook slow-mo error: {e}")
            return False


# Singleton
_speed_service: Optional[SpeedControlService] = None


def get_speed_control_service() -> SpeedControlService:
    """Get or create singleton speed control service."""
    global _speed_service
    if _speed_service is None:
        _speed_service = SpeedControlService()
    return _speed_service
