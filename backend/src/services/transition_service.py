"""Transition Service - Viral video transitions (glitch, swipe, blur, flash, morph)"""
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TransitionType(str, Enum):
    GLITCH = "glitch"
    SWIPE_LEFT = "swipe_left"
    BLUR = "blur"
    FLASH_WHITE = "flash_white"
    MORPH = "morph"


@dataclass
class TransitionResult:
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None


class TransitionService:
    async def apply_glitch(self, clip: Path, output: Path) -> TransitionResult:
        """RGB channel shift glitch."""
        filter_complex = (
            "[0:v]split=3[r][g][b];[r]lutrgb=r=val:g=0:b=0[red];"
            "[g]lutrgb=r=0:g=val:b=0[green];[b]lutrgb=r=0:g=0:b=val[blue];"
            "[red]crop=iw-4:ih:2:0[r_shift];[green]crop=iw-4:ih:0:0[g_shift];"
            "[blue]crop=iw-4:ih:4:0[b_shift];[r_shift][g_shift]blend=all_mode=addition[rg];"
            "[rg][b_shift]blend=all_mode=addition,scale=1080:1920"
        )
        return await self._run_ffmpeg(clip, output, filter_complex)
    
    async def apply_blur(self, clip: Path, output: Path) -> TransitionResult:
        """Motion blur effect."""
        filter_complex = "[0:v]split=2[a][b];[b]boxblur=lr=10:lp=1[blurred];[a][blurred]blend=all_expr='if(lte(N,30),A,B)'"
        return await self._run_ffmpeg(clip, output, filter_complex)
    
    async def apply_flash(self, clip: Path, output: Path, color: str = "white") -> TransitionResult:
        """Flash transition."""
        filter_complex = f"color=c={color}:s=1080x1920:d=0.1[flash];[flash][0:v]concat=n=2:v=1:a=0[v]"
        cmd = ["ffmpeg", "-y", "-i", str(clip), "-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a", str(output)]
        proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=300.0)
        return TransitionResult(success=proc.returncode == 0, output_path=str(output))
    
    async def apply_swipe_left(self, clip: Path, output: Path) -> TransitionResult:
        """Horizontal slide-in from right (30 frame ramp)."""
        filter_complex = (
            "[0:v]split=2[base][slide];"
            "[slide]crop=iw/4:ih:3*iw/4:0,scale=iw*4:ih[sliver];"
            "[base][sliver]overlay=x='if(lte(n,30), W-n*W/30, 0)':y=0[v]"
        )
        return await self._run_ffmpeg(clip, output, filter_complex)

    async def apply_morph(self, clip_a: Path, clip_b: Path, output: Path) -> TransitionResult:
        """RAFT optical flow morph."""
        try:
            from ..video_processing.optical_flow_transitions import apply_optical_flow_transition
            result = await apply_optical_flow_transition(clip_a, clip_b, output)
            return TransitionResult(success=bool(result), output_path=str(output))
        except:
            return TransitionResult(success=False, error="RAFT unavailable")
    
    async def _run_ffmpeg(self, clip: Path, output: Path, filter_complex: str) -> TransitionResult:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(clip),
               "-filter_complex", filter_complex, "-c:a", "copy", str(output)]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await asyncio.wait_for(proc.wait(), timeout=300.0)
        return TransitionResult(success=proc.returncode == 0 and output.exists(), output_path=str(output))


def get_transition_service() -> TransitionService:
    return TransitionService()
