"""
Clip Watermark Service — Phase 25

Manages per-user watermark configuration stored in Redis and applies
watermarks to clip video files via FFmpeg drawtext/overlay filter.

Key schema:
  watermark_config:{user_id}  → HASH: text, position, opacity, font_size, color, enabled

Positions: top-left, top-right, bottom-left, bottom-right, center
"""

import asyncio
import logging
import os
import tempfile
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "watermark_config"

_VALID_POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right", "center"}

_POSITION_COORDS = {
    "top-left":     "x=20:y=20",
    "top-right":    "x=w-tw-20:y=20",
    "bottom-left":  "x=20:y=h-th-20",
    "bottom-right": "x=w-tw-20:y=h-th-20",
    "center":       "x=(w-tw)/2:y=(h-th)/2",
}

_DEFAULTS = {
    "text": "ViraClip",
    "position": "bottom-right",
    "opacity": "0.5",
    "font_size": "24",
    "color": "white",
    "enabled": "true",
}


def _key(user_id: str) -> str:
    return f"{_KEY_PREFIX}:{user_id}"


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def set_watermark_config(
    user_id: str,
    text: Optional[str] = None,
    position: Optional[str] = None,
    opacity: Optional[float] = None,
    font_size: Optional[int] = None,
    color: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Dict:
    """Update watermark configuration for a user. Only provided fields are changed."""
    if position is not None and position not in _VALID_POSITIONS:
        raise ValueError(f"position must be one of {_VALID_POSITIONS}")
    if opacity is not None and not (0.0 <= opacity <= 1.0):
        raise ValueError("opacity must be between 0.0 and 1.0")

    r = await _redis()
    existing = await _get_config_raw(user_id)
    config = {**_DEFAULTS, **existing}

    if text is not None:
        config["text"] = text
    if position is not None:
        config["position"] = position
    if opacity is not None:
        config["opacity"] = str(opacity)
    if font_size is not None:
        config["font_size"] = str(font_size)
    if color is not None:
        config["color"] = color
    if enabled is not None:
        config["enabled"] = "true" if enabled else "false"

    await r.hset(_key(user_id), mapping=config)
    return _parse_config(config)


async def get_watermark_config(user_id: str) -> Dict:
    """Return watermark config for a user (merged with defaults)."""
    raw = await _get_config_raw(user_id)
    return _parse_config({**_DEFAULTS, **raw})


async def delete_watermark_config(user_id: str) -> bool:
    """Reset watermark config for a user."""
    try:
        r = await _redis()
        deleted = await r.delete(_key(user_id))
        return bool(deleted)
    except Exception as exc:
        logger.warning("[watermark] delete failed user=%s: %s", user_id, exc)
        return False


async def apply_watermark(user_id: str, input_path: str, output_path: str) -> bool:
    """
    Apply the user's watermark to a video file using FFmpeg drawtext.
    Returns True on success, False on failure.
    """
    config = await get_watermark_config(user_id)
    if not config.get("enabled"):
        return False

    coords = _POSITION_COORDS.get(config["position"], _POSITION_COORDS["bottom-right"])
    safe_text = config["text"].replace("'", "\\'").replace(":", "\\:")
    opacity = config["opacity"]
    font_size = config["font_size"]
    color = config["color"]

    vf = (
        f"drawtext=text='{safe_text}':"
        f"{coords}:"
        f"fontsize={font_size}:"
        f"fontcolor={color}@{opacity}"
    )

    cmd = ["ffmpeg", "-y", "-i", input_path, "-vf", vf,
           "-c:a", "copy", output_path]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except Exception as exc:
        logger.warning("[watermark] ffmpeg failed: %s", exc)
        return False


async def _get_config_raw(user_id: str) -> Dict:
    try:
        r = await _redis()
        raw = await r.hgetall(_key(user_id))
        return {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
    except Exception:
        return {}


def _parse_config(data: Dict) -> Dict:
    return {
        "text": data.get("text", _DEFAULTS["text"]),
        "position": data.get("position", _DEFAULTS["position"]),
        "opacity": float(data.get("opacity", _DEFAULTS["opacity"])),
        "font_size": int(data.get("font_size", _DEFAULTS["font_size"])),
        "color": data.get("color", _DEFAULTS["color"]),
        "enabled": data.get("enabled", "true") == "true",
    }
