"""
Smart Compression Service — Phase 27

Adaptive bitrate recommendation based on content analysis.
Uses clip metadata (motion complexity, duration, quality score) to
recommend optimal CRF (Constant Rate Factor) and bitrate for re-encoding.

Key schema (read-only): clip_meta:{clip_id} → HASH
Recommendation stored in: compression_profile:{clip_id}
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_KEY_PROFILE = "compression_profile"

# CRF scale: 0-51 (lower = higher quality, larger file)
_CRF_FAST = 28    # Talking head, low motion
_CRF_BALANCED = 23  # Default
_CRF_HIGH_QUALITY = 18  # High motion, high detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pkey(clip_id: str) -> str:
    return f"{_KEY_PROFILE}:{clip_id}"


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


def analyze_content_complexity(
    motion_score: Optional[float] = None,
    detail_score: Optional[float] = None,
    duration: Optional[float] = None,
) -> str:
    """
    Classify content complexity: low | medium | high
    Based on motion and detail scores (0-100 scale).
    """
    if motion_score is None:
        motion_score = 50.0
    if detail_score is None:
        detail_score = 50.0

    avg = (motion_score + detail_score) / 2
    if avg < 35:
        return "low"
    elif avg < 70:
        return "medium"
    return "high"


def recommend_compression(
    complexity: str,
    target_size_mb: Optional[float] = None,
    duration: Optional[float] = None,
) -> Dict:
    """
    Recommend CRF and bitrate based on content complexity.
    Optional: target file size constraint (in MB).
    """
    if complexity == "low":
        base_crf = _CRF_FAST
        base_bitrate_kbps = 1500
    elif complexity == "high":
        base_crf = _CRF_HIGH_QUALITY
        base_bitrate_kbps = 5000
    else:
        base_crf = _CRF_BALANCED
        base_bitrate_kbps = 3000

    if target_size_mb and duration and duration > 0:
        target_bits = target_size_mb * 8 * 1024 * 1024
        target_bitrate = int(target_bits / duration / 1000)  # kbps
        if target_bitrate < base_bitrate_kbps:
            base_bitrate_kbps = target_bitrate
            base_crf = min(base_crf + 3, 35)

    return {
        "crf": base_crf,
        "video_bitrate_kbps": base_bitrate_kbps,
        "audio_bitrate_kbps": 128,
        "preset": "medium",
        "complexity": complexity,
    }


async def get_compression_profile(
    clip_id: str,
    motion_score: Optional[float] = None,
    detail_score: Optional[float] = None,
    duration: Optional[float] = None,
    target_size_mb: Optional[float] = None,
    force: bool = False,
) -> Dict:
    """
    Return cached compression profile or compute and cache new one.
    """
    if not force:
        try:
            r = await _redis()
            cached = await r.get(_pkey(clip_id))
            if cached:
                data = json.loads(cached.decode() if isinstance(cached, bytes) else cached)
                data["cached"] = True
                return data
        except Exception:
            pass

    complexity = analyze_content_complexity(motion_score, detail_score, duration)
    rec = recommend_compression(complexity, target_size_mb, duration)
    result = {
        "clip_id": clip_id,
        "complexity": complexity,
        "recommendation": rec,
        "generated_at": _now(),
        "cached": False,
    }
    try:
        r = await _redis()
        await r.setex(_pkey(clip_id), 60 * 60 * 24, json.dumps(result))
    except Exception:
        pass
    return result


async def clear_compression_profile(clip_id: str) -> None:
    """Clear cached compression profile."""
    try:
        r = await _redis()
        await r.delete(_pkey(clip_id))
    except Exception as exc:
        logger.warning("[compression] clear failed clip=%s: %s", clip_id, exc)


def build_ffmpeg_args(profile: Dict, input_path: str, output_path: str) -> list:
    """
    Build FFmpeg command arguments from compression profile.
    Returns list of arguments for subprocess.
    """
    rec = profile.get("recommendation", {})
    crf = rec.get("crf", _CRF_BALANCED)
    video_br = rec.get("video_bitrate_kbps", 3000)
    audio_br = rec.get("audio_bitrate_kbps", 128)
    preset = rec.get("preset", "medium")

    return [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-b:v", f"{video_br}k",
        "-c:a", "aac",
        "-b:a", f"{audio_br}k",
        "-movflags", "+faststart",
        output_path,
    ]
