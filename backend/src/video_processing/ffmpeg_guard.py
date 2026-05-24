"""
FFmpeg Guard — validate segment parameters before executing any FFmpeg command.

Pattern: validate at the boundary, never trust the caller has done it.
"""

import logging
import subprocess
from pathlib import Path

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


def get_duration(source_path: str) -> float:
    """Return file duration in seconds via ffmpeg -i. Returns 0.0 on failure."""
    try:
        import re
        result = subprocess.run(
            [
                _get_ffmpeg_exe(), "-i", source_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Parse duration from stderr: "Duration: 00:01:23.45"
        stderr = result.stderr
        match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            return hours * 3600 + minutes * 60 + seconds
        else:
            # Fallback: try ffprobe when ffmpeg -i returns Duration: N/A
            try:
                import shutil
                if shutil.which("ffprobe"):
                    _fp = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                         "-of", "csv=p=0", source_path],
                        capture_output=True, text=True, timeout=15
                    )
                    if _fp.returncode == 0 and _fp.stdout.strip():
                        return float(_fp.stdout.strip())
            except Exception:
                pass
            logger.warning(f"[FFMPEG_GUARD] Could not parse duration from ffmpeg output for {source_path}")
            return 0.0
    except Exception as e:
        logger.warning(f"[FFMPEG_GUARD] get_duration error for {source_path}: {e}")
        return 0.0


def validate_segment_call(
    source_path: str,
    ss: float,
    to: float,
    context: str = "",
) -> None:
    """
    Raise ValueError immediately if FFmpeg parameters are incoherent.
    Call this before building any FFmpeg command that uses -ss / -to / -t.

    Args:
        source_path: Input file path.
        ss:          Seek start in seconds (absolute within source_path).
        to:          End position in seconds (absolute within source_path).
        context:     Free-form label for error messages (e.g. "clip_3_audio").

    Raises:
        ValueError: If parameters are unsafe or incoherent.
    """
    prefix = f"[FFMPEG_GUARD] {context} — " if context else "[FFMPEG_GUARD] "

    if not Path(source_path).exists():
        raise FileNotFoundError(
            f"{prefix}Archivo no encontrado: {source_path}. "
            f"¿Está siendo escrito por FFmpeg o aún no se creó?"
        )

    if ss < 0:
        raise ValueError(f"{prefix}ss negativo: {ss:.2f}s")

    if to <= ss:
        raise ValueError(
            f"{prefix}to ({to:.2f}s) <= ss ({ss:.2f}s) — duración 0 o negativa"
        )

    segment_duration = to - ss
    if segment_duration < 0.5:
        raise ValueError(
            f"{prefix}segmento demasiado corto: {segment_duration:.2f}s (mínimo 0.5s)"
        )

    source_duration = get_duration(source_path)
    if source_duration > 0:
        if ss > source_duration:
            raise ValueError(
                f"{prefix}ss={ss:.1f}s supera duración del archivo "
                f"({source_duration:.1f}s). "
                f"¿Coordenadas absolutas aplicadas a archivo pre-extraído?"
            )
        if to > source_duration + 0.5:
            logger.warning(
                f"{prefix}to={to:.1f}s supera duración ({source_duration:.1f}s) — "
                f"FFmpeg truncará automáticamente"
            )
