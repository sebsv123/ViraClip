"""
Overlay Renderer — Contextual Overlay System
FFmpeg-based rendering: full-screen overlay with speaker in corner bubble.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


class OverlayStyle(str, Enum):
    FULL_SCREEN_BUBBLE = "full_screen_bubble"
    SPLIT_SCREEN = "split_screen"
    PICTURE_IN_PICTURE = "picture_in_picture"


@dataclass
class OverlayEvent:
    overlay_path: str
    start_time: float
    end_time: float
    keyword: str
    style: OverlayStyle = OverlayStyle.FULL_SCREEN_BUBBLE
    is_video: bool = False


@dataclass
class OverlayResult:
    success: bool
    output_path: Optional[str] = None
    overlays_applied: int = 0
    error: Optional[str] = None


class OverlayRenderer:
    """Renders contextual overlays with speaker in corner bubble (viral TikTok style)."""
    
    async def render_overlays(
        self,
        base_video: Path,
        overlay_events: List[OverlayEvent],
        output_path: Path,
        style: OverlayStyle = OverlayStyle.FULL_SCREEN_BUBBLE
    ) -> OverlayResult:
        if not overlay_events:
            return OverlayResult(success=False, error="No overlay events")
        
        sorted_events = sorted(overlay_events, key=lambda e: e.start_time)
        
        try:
            # Build FFmpeg command
            inputs = ["-i", str(base_video)]
            for event in sorted_events:
                inputs.extend(["-i", event.overlay_path])
            
            # Build filter: full-screen overlay with 25% corner bubble
            filter_parts = ["[0:v]split=2[base][speaker]"]
            
            # Speaker bubble (270x480 = 25% with border)
            filter_parts.append(
                "[speaker]scale=270:480,pad=278:488:4:4:color=white[bubble]"
            )
            
            # Process overlays
            current = "base"
            for i, event in enumerate(sorted_events):
                overlay_idx = i + 1
                
                # Scale overlay to full screen
                scale_filter = f"[{overlay_idx}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[ov{i}]"
                filter_parts.append(scale_filter)
                
                # Apply overlay with timing
                enable = f"between(t,{event.start_time:.3f},{event.end_time:.3f})"
                next_name = f"tmp{i}" if i < len(sorted_events) - 1 else "overlaid"
                overlay_filter = f"[{current}][ov{i}]overlay=0:0:enable='{enable}'[{next_name}]"
                filter_parts.append(overlay_filter)
                current = next_name
            
            # Add speaker bubble to bottom-right
            filter_parts.append(f"[{current}][bubble]overlay=W-w-20:H-h-20")
            
            filter_complex = ";".join(filter_parts)
            
            cmd = [
                _get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                *inputs,
                "-filter_complex", filter_complex,
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_path)
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await asyncio.wait_for(proc.communicate(), timeout=600.0)
            
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"Overlays applied: {len(sorted_events)}")
                return OverlayResult(
                    success=True,
                    output_path=str(output_path),
                    overlays_applied=len(sorted_events)
                )
            else:
                return OverlayResult(success=False, error="FFmpeg failed")
        
        except asyncio.TimeoutError:
            return OverlayResult(success=False, error="Timeout")
        except Exception as e:
            logger.error(f"Overlay render error: {e}")
            return OverlayResult(success=False, error=str(e))


def get_overlay_renderer() -> OverlayRenderer:
    return OverlayRenderer()
