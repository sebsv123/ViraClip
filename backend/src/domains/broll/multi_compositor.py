"""Multi-overlay compositor with position support.

Handles composition of multiple B-roll items with custom positions,
opacities, and scales in a single FFmpeg pass.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Any

from .broll_compositor import normalize_broll, probe_dimensions, _build_overlay_alpha_expr
from .broll_compositor import _get_ffmpeg_exe, _gpu_codec, _FFMPEG_TIMEOUT
import subprocess

logger = logging.getLogger(__name__)


async def compose_multi_with_positions(
    main_path: Path,
    broll_pairs: List[Dict[str, Any]],
    output_path: Path,
    fade: float = 0.6,
    transition_type: str = "dissolve",
    width: int = 1080,
    height: int = 1920,
) -> bool:
    """Compose multiple B-roll overlays with position support.

    Args:
        main_path: Path to main video
        broll_pairs: List of dicts with keys:
            - path: str - path to B-roll video
            - timestamp: float - when to start overlay
            - duration: float - how long to show
            - position: str - "fullscreen", "corner", "split", "center"
            - opacity: float - 0.0 to 1.0
            - scale: float - scale factor
            - x, y: int - optional explicit coordinates
        output_path: Where to save result
        fade: Fade duration
        transition_type: "dissolve" or other
        width, height: Target dimensions

    Returns True on success.
    """
    if not broll_pairs:
        return False

    # Normalize all B-roll videos first
    normalized = []
    for pair in broll_pairs:
        path = Path(pair["path"])
        if not path.exists():
            logger.warning("[MultiCompositor] B-roll not found: %s", path)
            continue

        norm = normalize_broll(path, width, height, duration=pair.get("duration", 3.0), fade=fade)
        if norm:
            normalized.append({
                "norm_path": norm,
                "pair": pair,
            })

    if not normalized:
        logger.error("[MultiCompositor] No valid B-roll to compose")
        return False

    # Build FFmpeg command with filter_complex
    inputs = ["-i", str(main_path)]
    for n in normalized:
        inputs.extend(["-i", str(n["norm_path"])])

    # Build filter complex
    filter_parts = []
    last_label = "[0:v]"

    for idx, n in enumerate(normalized):
        pair = n["pair"]
        timestamp = pair.get("timestamp", 0)
        duration = pair.get("duration", 3.0)
        position = pair.get("position", "fullscreen")
        opacity = pair.get("opacity", 1.0)
        scale = pair.get("scale", 1.0)

        end_ts = timestamp + duration
        alpha_expr = _build_overlay_alpha_expr(timestamp, end_ts, fade)

        # Calculate position coordinates
        x, y = _calculate_position(position, width, height, scale, pair.get("x"), pair.get("y"))

        # Scale filter if needed
        scale_filter = ""
        if scale != 1.0:
            new_w = int(width * scale)
            new_h = int(height * scale)
            scale_filter = f"scale={new_w}:{new_h}:force_original_aspect_ratio=decrease,"

        # Alpha/opacity filter
        alpha_filter = ""
        if opacity < 1.0:
            alpha_filter = f"format=rgba,colorchannelmixer=aa={opacity:.2f},"

        # Build overlay filter for this B-roll
        input_label = f"[{idx + 1}:v]"
        mid_label = f"[bv{idx}]"
        out_label = f"[out{idx}]" if idx < len(normalized) - 1 else "[final]"

        # Chain: previous output + this B-roll -> new output
        filter_parts.append(
            f"{input_label}{scale_filter}{alpha_filter}setpts=PTS-STARTPTS+{timestamp:.3f}/TB{mid_label};"
            f"{last_label}{mid_label}overlay={x}:{y}:enable='between(t\\,{timestamp:.3f}\\,{end_ts:.3f})'"
        )

        if transition_type == "dissolve":
            filter_parts[-1] += f":alpha='{alpha_expr}'"

        filter_parts[-1] += out_label
        last_label = out_label

    filter_complex = "".join(filter_parts)

    cmd = [
        _get_ffmpeg_exe(), "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[final]",
        "-map", "0:a?",
        *_gpu_codec("high"),
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)

        # Cleanup temp files
        for n in normalized:
            n["norm_path"].unlink(missing_ok=True)

        if result.returncode != 0:
            logger.error("[MultiCompositor] FFmpeg failed: %s", result.stderr.decode()[-400:])
            return False

        return output_path.exists() and output_path.stat().st_size > 0

    except subprocess.TimeoutExpired:
        logger.error("[MultiCompositor] Timeout")
        for n in normalized:
            n["norm_path"].unlink(missing_ok=True)
        return False
    except Exception as exc:
        logger.error("[MultiCompositor] Exception: %s", exc)
        for n in normalized:
            n["norm_path"].unlink(missing_ok=True)
        return False


def _calculate_position(
    position: str,
    width: int,
    height: int,
    scale: float = 1.0,
    explicit_x: int = None,
    explicit_y: int = None,
) -> tuple[int, int]:
    """Calculate x, y coordinates for overlay position."""
    if explicit_x is not None and explicit_y is not None:
        return explicit_x, explicit_y

    # Calculate scaled dimensions
    scaled_w = int(width * scale)
    scaled_h = int(height * scale)

    if position == "fullscreen" or position == "full":
        # Center (but fullscreen usually fills, so 0,0 with scale=1)
        x = (width - scaled_w) // 2
        y = (height - scaled_h) // 2
    elif position == "corner" or position == "top-right":
        x = width - scaled_w - 20  # 20px margin
        y = 20
    elif position == "top-left":
        x = 20
        y = 20
    elif position == "bottom-right":
        x = width - scaled_w - 20
        y = height - scaled_h - 20
    elif position == "bottom-left":
        x = 20
        y = height - scaled_h - 20
    elif position == "center":
        x = (width - scaled_w) // 2
        y = (height - scaled_h) // 2
    elif position == "split":
        # Side by side - place at right half
        x = width // 2
        y = (height - scaled_h) // 2
    else:
        # Default center
        x = (width - scaled_w) // 2
        y = (height - scaled_h) // 2

    return max(0, x), max(0, y)
