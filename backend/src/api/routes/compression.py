"""
Video Compression API — ViraClip

Endpoints for compressing clips, getting preset recommendations,
batch compression, and viewing compression statistics.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.video_compression import (
    CompressionPreset,
    VideoCodec,
    get_compression_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compression", tags=["compression"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CompressRequest(BaseModel):
    input_path: str
    output_path: str
    preset: str = "balanced"    # CompressionPreset value
    target_size_mb: Optional[float] = None


class RecommendRequest(BaseModel):
    video_path: str
    target_size_mb: Optional[float] = None


class BatchCompressRequest(BaseModel):
    jobs: List[CompressRequest]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_preset(value: str) -> CompressionPreset:
    try:
        return CompressionPreset(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{value}'. Valid: {[p.value for p in CompressionPreset]}",
        )


def _fmt_result(r) -> Dict[str, Any]:
    return {
        "success": r.success,
        "input_path": str(r.input_path),
        "output_path": str(r.output_path),
        "input_size_mb": r.input_size_mb,
        "output_size_mb": r.output_size_mb,
        "compression_ratio": r.compression_ratio,
        "space_saved_mb": r.space_saved_mb,
        "quality_score": r.quality_score,
        "duration_seconds": r.duration_seconds,
        "error_message": r.error_message,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/compress")
async def compress_clip(body: CompressRequest):
    """
    Compress a video clip using the specified preset.

    `preset`: `ultra` | `high` | `balanced` | `compact` | `aggressive`
    Optional `target_size_mb` overrides the preset's default target.
    Returns compression ratio, space saved, and quality score.
    """
    preset = _parse_preset(body.preset)
    svc = get_compression_service()
    try:
        result = await svc.compress_clip(
            Path(body.input_path),
            Path(body.output_path),
            preset,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "compressed", "result": _fmt_result(result)}


@router.post("/recommend")
def recommend_preset(body: RecommendRequest):
    """
    Get the recommended compression preset for a video.

    Pass `target_size_mb` to find the best preset that fits within
    the size budget. Returns the preset name and its profile config.
    """
    svc = get_compression_service()
    try:
        preset = svc.recommend_preset(Path(body.video_path), body.target_size_mb)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    profile = svc.PRESET_CONFIGS.get(preset)
    return {
        "recommended_preset": preset.value,
        "profile": {
            "codec": profile.codec.value,
            "crf": profile.crf,
            "bitrate": profile.bitrate,
            "max_file_size_mb": profile.max_file_size_mb,
            "target_quality_score": profile.target_quality_score,
            "preserve_resolution": profile.preserve_resolution,
            "audio_codec": profile.audio_codec,
            "audio_bitrate": profile.audio_bitrate,
        } if profile else None,
    }


@router.get("/stats")
def compression_stats():
    """Get cumulative compression statistics across all jobs."""
    svc = get_compression_service()
    return {"status": "success", "stats": svc.get_compression_stats()}


@router.get("/presets")
def list_presets():
    """List all compression presets and their profiles."""
    svc = get_compression_service()
    presets = []
    for p in CompressionPreset:
        profile = svc.PRESET_CONFIGS.get(p)
        presets.append({
            "preset": p.value,
            "crf": profile.crf if profile else None,
            "target_quality_score": profile.target_quality_score if profile else None,
            "codec": profile.codec.value if profile else None,
        })
    return {"presets": presets}


@router.get("/codecs")
def list_codecs():
    """List all supported video codecs."""
    return {"codecs": [c.value for c in VideoCodec]}
