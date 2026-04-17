"""
Platform Export Presets API — ViraClip

Endpoints for fetching platform-specific export presets, FFmpeg
encoding settings, video validation, and best-practice recommendations.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.platform_presets import (
    PlatformType,
    get_platform_presets,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform-presets", tags=["platform-presets"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ValidateRequest(BaseModel):
    video_path: str
    platform: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_platform(value: str) -> PlatformType:
    try:
        return PlatformType(value.lower().replace(" ", "_"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platform '{value}'. Valid: {[p.value for p in PlatformType]}",
        )


def _fmt_preset(preset) -> Dict[str, Any]:
    specs = preset.specs
    return {
        "platform": preset.platform.value,
        "name": preset.name,
        "description": preset.description,
        "specs": {
            "resolution": specs.resolution,
            "aspect_ratio": specs.aspect_ratio,
            "fps": specs.fps,
            "min_fps": specs.min_fps,
            "max_fps": specs.max_fps,
            "video_codec": specs.video_codec,
            "audio_codec": specs.audio_codec,
            "video_bitrate": specs.video_bitrate,
            "audio_bitrate": specs.audio_bitrate,
            "max_file_size_mb": specs.max_file_size_mb,
            "max_duration_sec": specs.max_duration_sec,
            "recommended_duration_sec": specs.recommended_duration_sec,
            "pixel_format": specs.pixel_format,
        },
        "safe_zones": preset.safe_zones,
        "caption_settings": preset.caption_settings,
        "audio_settings": preset.audio_settings,
        "thumbnail_specs": preset.thumbnail_specs,
        "hashtag_limit": preset.hashtag_limit,
        "caption_char_limit": preset.caption_char_limit,
        "best_upload_times": preset.best_upload_times,
        "engagement_tips": preset.engagement_tips,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
def list_presets():
    """List all 7 platform presets with their full configuration."""
    system = get_platform_presets()
    presets = [_fmt_preset(p) for p in system.PRESETS.values()]
    return {"count": len(presets), "presets": presets}


@router.get("/{platform}")
def get_preset(platform: str):
    """Get the full export preset for a specific platform."""
    platform_type = _parse_platform(platform)
    system = get_platform_presets()
    preset = system.get_preset(platform_type)
    return {"status": "success", "preset": _fmt_preset(preset)}


@router.get("/{platform}/ffmpeg")
def get_ffmpeg_settings(platform: str):
    """
    Get ready-to-use FFmpeg encoding settings for a platform.

    Returns `video_codec`, `audio_codec`, `video_bitrate`, `audio_bitrate`,
    `fps`, `resolution`, `pixel_format`, and an `extra_args` list.
    """
    platform_type = _parse_platform(platform)
    system = get_platform_presets()
    settings = system.get_ffmpeg_settings(platform_type)
    return {"status": "success", "platform": platform_type.value, "ffmpeg": settings}


@router.post("/validate")
def validate_video(body: ValidateRequest):
    """
    Validate whether a video file meets a platform's requirements.

    Returns a `valid` flag, list of `issues`, and `recommendations`
    along with the detected current specs (duration, size, resolution).
    Requires `ffprobe` to be available in the environment.
    """
    platform_type = _parse_platform(body.platform)
    system = get_platform_presets()
    result = system.validate_video_for_platform(Path(body.video_path), platform_type)
    return {"status": "success", "validation": result}


@router.get("/platforms/list")
def list_platforms():
    """List all supported platform identifiers."""
    return {"platforms": [p.value for p in PlatformType]}
