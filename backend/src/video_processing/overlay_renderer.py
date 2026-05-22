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

from .. import gpu_utils
from ..domains.broll.broll_config import (
    MIN_OVERLAY_DURATION_S,
    FADE_DURATION_S,
    MIN_GAP_BETWEEN_OVERLAYS_S,
)

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
    NONE = "none"
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
    
    # ── Overlay quality guards (from canonical broll_config) ────────────────
    _MIN_OVERLAY_DUR = MIN_OVERLAY_DURATION_S
    _FADE_DUR = FADE_DURATION_S
    _MIN_GAP = MIN_GAP_BETWEEN_OVERLAYS_S
    
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
        
        # ── Guard 1: Filter by minimum duration ────────────────────────────
        # Reject any overlay shorter than MIN_OVERLAY_DURATION_S (2.5s).
        # Also reject overlays shorter than 2 * FADE_DURATION_S (0.8s) because
        # fade-in and fade-out would overlap, producing a visible flash.
        _MIN_FADE_WINDOW = 2.0 * self._FADE_DUR
        sorted_events = [
            e for e in sorted_events
            if (e.end_time - e.start_time) >= max(self._MIN_OVERLAY_DUR, _MIN_FADE_WINDOW)
        ]
        if not sorted_events:
            return OverlayResult(success=False, error="All overlays below minimum duration")
        
        # ── Guard 2: Resolve overlapping overlays by truncation ────────────
        # Instead of dropping overlapping events, truncate the later event's
        # start to the previous event's end + _MIN_GAP. This preserves as many
        # overlays as possible while preventing visual overlap.
        resolved = []
        _last_end = -999.0
        for e in sorted_events:
            if e.start_time >= _last_end + self._MIN_GAP:
                # No overlap — keep as-is
                resolved.append(e)
                _last_end = e.end_time
            elif e.end_time > _last_end + self._MIN_GAP:
                # Overlap — truncate start to _last_end + _MIN_GAP
                truncated = OverlayEvent(
                    overlay_path=e.overlay_path,
                    start_time=_last_end + self._MIN_GAP,
                    end_time=e.end_time,
                    keyword=e.keyword,
                    style=e.style,
                    is_video=e.is_video,
                )
                # Only keep if truncated event still meets minimum duration
                if (truncated.end_time - truncated.start_time) >= self._MIN_OVERLAY_DUR:
                    resolved.append(truncated)
                    _last_end = truncated.end_time
                    logger.debug("[Overlay] Truncated '%s' from %.2f→%.2f to avoid overlap",
                                 e.keyword, e.start_time, truncated.start_time)
                else:
                    logger.debug("[Overlay] Dropped '%s' — truncated duration below minimum (%.2fs)",
                                 e.keyword, e.end_time - truncated.start_time)
            # else: completely contained within previous — drop silently
        sorted_events = resolved
        if not sorted_events:
            return OverlayResult(success=False, error="All overlays filtered by overlap prevention")
        
        try:
            # Build FFmpeg command
            inputs = ["-i", str(base_video)]
            for event in sorted_events:
                inputs.extend(["-i", event.overlay_path])
            
            # Build filter: full-screen overlay with 25% corner bubble
            # Only add the speaker bubble when style is explicitly PICTURE_IN_PICTURE
            if style == OverlayStyle.PICTURE_IN_PICTURE:
                filter_parts = ["[0:v]split=2[base][speaker]"]
                
                # Speaker bubble (270x480 = 25% with border)
                filter_parts.append(
                    "[speaker]scale=270:480,pad=278:488:4:4:color=white[bubble]"
                )
            else:
                filter_parts = ["[0:v]null[base]"]
            
            # Process overlays with proper PTS alignment and fade transitions
            current = "base"
            for i, event in enumerate(sorted_events):
                overlay_idx = i + 1
                dur = event.end_time - event.start_time
                # Clamp fade_out_st to 0 to prevent negative values when dur < _FADE_DUR
                fade_out_st = max(0.0, dur - self._FADE_DUR)
                
                # Scale + PTS alignment + fade in/out (prevents flickering and PTS misalignment)
                # Uses format=rgba for proper alpha computation, then yuva420p for overlay
                scale_filter = (
                    f"[{overlay_idx}:v]"
                    f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"setpts=PTS-STARTPTS+{event.start_time:.3f}/TB,"
                    f"format=rgba,"
                    f"fade=t=in:st=0:d={self._FADE_DUR:.3f}:alpha=1,"
                    f"fade=t=out:st={fade_out_st:.3f}:d={self._FADE_DUR:.3f}:alpha=1,"
                    f"format=yuva420p[ov{i}]"
                )
                filter_parts.append(scale_filter)
                
                # Apply overlay with timeline editing
                # Use explicit format=yuva420p (not format=auto) for reliable alpha compositing
                # Add eof_action=pass so the filtergraph doesn't terminate when an overlay stream ends
                next_name = f"tmp{i}" if i < len(sorted_events) - 1 else "overlaid"
                overlay_filter = (
                    f"[{current}][ov{i}]"
                    f"overlay=0:0:format=yuva420p:"
                    f"eof_action=pass:"
                    f"enable='between(t,{event.start_time:.3f},{event.end_time:.3f})'"
                    f"[{next_name}]"
                )
                filter_parts.append(overlay_filter)
                current = next_name
            
            # Add speaker bubble to bottom-right (only for PICTURE_IN_PICTURE style)
            if style == OverlayStyle.PICTURE_IN_PICTURE:
                filter_parts.append(f"[{current}][bubble]overlay=W-w-20:H-h-20")

            
            filter_complex = ";".join(filter_parts)
            
            cmd = [
                _get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "[overlaid]",
                "-map", "0:a",
                *gpu_utils.ffmpeg_codec_flags("medium"),
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_path)
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)
            
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"Overlays applied: {len(sorted_events)}")
                return OverlayResult(
                    success=True,
                    output_path=str(output_path),
                    overlays_applied=len(sorted_events)
                )
            else:
                stderr_str = (stderr or b"").decode("utf-8", errors="replace")[-2000:]
                logger.error(f"[OVERLAY_DEBUG] cmd: {' '.join(str(x) for x in cmd)}")
                logger.error(f"[OVERLAY_DEBUG] stderr: {stderr_str}")
                # Surface filtergraph errors instead of silently continuing
                _error_detail = stderr_str[:500] if stderr_str else "unknown error"
                return OverlayResult(success=False, error=f"FFmpeg failed: {_error_detail}")
        
        except asyncio.TimeoutError:
            return OverlayResult(success=False, error="Timeout")
        except Exception as e:
            logger.error(f"Overlay render error: {e}")
            return OverlayResult(success=False, error=str(e))


def get_overlay_renderer() -> OverlayRenderer:
    return OverlayRenderer()
