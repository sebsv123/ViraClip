"""
Impact Zoom Service — applies smooth zoom-in/out at emotional peak timestamps.

Uses FFmpeg zoompan with sin() easing for natural ease-in/out.
Max 2 zooms per clip. Falls back silently if FFmpeg fails.
"""
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ImpactZoomService:
    """Applies impact zoom at emotional peak timestamps."""

    def __init__(self, fps: int = 25):
        self.fps = fps

    async def apply(
        self,
        clip_path: Path,
        peak_timestamps: list[float],
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Apply zoom-in/out at peak timestamps using sin() easing.

        Args:
            clip_path: Input video path
            peak_timestamps: Seconds where emotional peaks occur
            output_path: Output path (default: clip_path parent / zoom_{name})

        Returns:
            Path to processed clip (or original if no peaks / FFmpeg fails)
        """
        if not peak_timestamps:
            logger.debug("[ImpactZoom] No peak timestamps, skipping")
            return clip_path

        # Max 2 zooms
        peaks = peak_timestamps[:2]
        out = output_path or clip_path.parent / f"zoom_{clip_path.name}"

        # Build zoompan expression with sin() easing for each peak
        zoom_expr_parts = []
        for ts in peaks:
            frame_in = int(ts * self.fps) - 3
            frame_out = int(ts * self.fps) + 12
            zoom_expr_parts.append(
                f"if(between(on,{frame_in},{frame_out}),"
                f"1+0.08*sin(PI*(on-{frame_in})/({frame_out}-{frame_in})),1)"
            )

        # Combine: if none active, zoom=1
        combined = ",".join(zoom_expr_parts)
        zoompan = (
            f"zoompan=z='{combined}':"
            f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s=1080x1920:fps={self.fps}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vf", zoompan,
            "-c:a", "copy",
            str(out),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode == 0 and out.exists():
                logger.info(
                    "[ImpactZoom] Applied %d zoom(s) at peaks=%s → %s",
                    len(peaks), [f"{t:.1f}s" for t in peaks], out.name,
                )
                return out
            else:
                logger.warning(
                    "[ImpactZoom] FFmpeg failed (rc=%d): %s",
                    result.returncode, result.stderr.decode()[:200],
                )
        except Exception as e:
            logger.warning("[ImpactZoom] Error: %s", e)

        return clip_path
