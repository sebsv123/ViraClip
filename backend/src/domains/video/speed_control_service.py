"""
Speed Control Service

Applies playback speed control and dramatic slow-mo to clips using FFmpeg.
"""

import asyncio
import logging
from pathlib import Path
from src import gpu_utils

logger = logging.getLogger(__name__)


class SpeedControlService:
    """Apply speed control effects to video clips via FFmpeg."""

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
            clip_path: Input video path
            output_path: Output video path
            playback_speed: Global speed multiplier (0.5-2.0)
            dramatic_slowmo: Apply dramatic slow-mo to hook section
            hook_start: Hook section start time (seconds)
            hook_end: Hook section end time (seconds)

        Returns:
            True if output file exists and has size > 0
        """
        if not clip_path.exists():
            logger.error(f"Input clip not found: {clip_path}")
            return False

        try:
            if dramatic_slowmo and hook_end > hook_start:
                # Apply dramatic slow-mo to hook section
                # setpts=2.5*PTS (slow by 2.5x), atempo=0.4 (audio slowdown)
                return await self._apply_dramatic_slowmo(
                    clip_path, output_path, hook_start, hook_end
                )
            elif playback_speed != 1.0:
                # Apply global speed change
                return await self._apply_global_speed(
                    clip_path, output_path, playback_speed
                )
            else:
                # No speed change needed - copy input to output
                import shutil
                shutil.copy2(clip_path, output_path)
                return output_path.exists() and output_path.stat().st_size > 0

        except Exception as e:
            logger.error(f"[SpeedControl] Error: {e}")
            return False

    async def _apply_dramatic_slowmo(
        self,
        clip_path: Path,
        output_path: Path,
        hook_start: float,
        hook_end: float
    ) -> bool:
        """
        Apply dramatic slow-mo to hook section.
        Uses setpts=2.5*PTS for video slow-down and atempo=0.4 for audio.
        Two-pass approach: slow-mo hook + normal speed rest.
        """
        try:
            hook_duration = hook_end - hook_start
            
            # Two-pass filter:
            # 1. Select hook section and apply 2.5x slow-mo
            # 2. Select rest and keep normal speed
            # 3. Concatenate both parts
            # setpts=2.5*PTS = slow video by 2.5x
            # atempo=0.4 = slow audio to match (0.4x speed = 2.5x longer)
            
            filter_complex = (
                f"[0:v]trim=start={hook_start}:end={hook_end},setpts=2.5*PTS[v_slow];"
                f"[0:a]atrim=start={hook_start}:end={hook_end},asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=48000,atempo=0.4[a_slow];"
                f"[0:v]trim=start={hook_end},setpts=PTS-STARTPTS[v_rest];"
                f"[0:a]atrim=start={hook_end},asetpts=PTS-STARTPTS[a_rest];"
                f"[v_slow][v_rest]concat=n=2:v=1:a=0[outv];"
                f"[a_slow][a_rest]concat=n=2:v=0:a=1[outa]"
            )

            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(clip_path),
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-map", "[outa]",
                *gpu_utils.ffmpeg_codec_flags("medium"),
                "-c:a", "aac", "-b:a", "128k",
                str(output_path)
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)

            if proc.returncode != 0:
                logger.error(f"[SpeedControl] FFmpeg error: {stderr.decode()[:500]}")
                return False

            success = output_path.exists() and output_path.stat().st_size > 0
            if success:
                logger.info(f"[SpeedControl] Dramatic slow-mo applied: hook {hook_start}-{hook_end}s at 0.4x speed")
            return success

        except asyncio.TimeoutError:
            logger.error("[SpeedControl] Timeout waiting for FFmpeg")
            return False
        except Exception as e:
            logger.error(f"[SpeedControl] Dramatic slow-mo error: {e}")
            return False

    async def _apply_global_speed(
        self,
        clip_path: Path,
        output_path: Path,
        playback_speed: float
    ) -> bool:
        """Apply global playback speed using FFmpeg setpts and atempo."""
        try:
            # Calculate PTS multiplier (inverse of speed)
            pts_multiplier = 1.0 / playback_speed

            # Build atempo chain (FFmpeg requires chaining for values outside 0.5-2.0)
            atempo_filters = self._build_atempo_chain(playback_speed)

            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(clip_path),
                "-filter:v", f"setpts={pts_multiplier}*PTS",
                "-filter:a", atempo_filters,
                *gpu_utils.ffmpeg_codec_flags("medium"),
                "-c:a", "aac", "-b:a", "128k",
                str(output_path)
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)

            if proc.returncode != 0:
                logger.error(f"[SpeedControl] FFmpeg error: {stderr.decode()[:500]}")
                return False

            success = output_path.exists() and output_path.stat().st_size > 0
            if success:
                logger.info(f"[SpeedControl] Global speed applied: {playback_speed}x")
            return success

        except asyncio.TimeoutError:
            logger.error("[SpeedControl] Timeout waiting for FFmpeg")
            return False
        except Exception as e:
            logger.error(f"[SpeedControl] Global speed error: {e}")
            return False

    def _build_atempo_chain(self, speed: float) -> str:
        """Build atempo filter chain for given playback speed."""
        # FFmpeg atempo only accepts 0.5 to 2.0
        # For values outside this range, we need to chain multiple atempo filters
        
        filters = []
        remaining = speed
        
        while remaining > 2.0:
            filters.append("atempo=2.0")
            remaining /= 2.0
        
        while remaining < 0.5:
            filters.append("atempo=0.5")
            remaining *= 2.0
        
        filters.append(f"atempo={remaining:.4f}")
        
        return ",".join(filters)


# ── Singleton ─────────────────────────────────────────────────────────────────

_speed_service: "SpeedControlService | None" = None


def get_speed_control_service() -> SpeedControlService:
    """Get or create singleton speed control service."""
    global _speed_service
    if _speed_service is None:
        _speed_service = SpeedControlService()
    return _speed_service
