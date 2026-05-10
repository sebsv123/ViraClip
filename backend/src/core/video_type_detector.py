"""
Video type auto-detection and crop profile selection.
Analyzes motion, skin zones, and speech density.
"""
import asyncio
import json
import logging
import os
import shutil
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoType(str, Enum):
    SINGLE_SPEAKER = "single_speaker"
    MULTI_SPEAKER = "multi_speaker"
    SCREEN_CONTENT = "screen_content"
    LIVE_EVENT = "live_event"
    UNKNOWN = "unknown"


class CropProfile(str, Enum):
    FACE_CENTERED = "face_centered"
    MULTI_FACE = "multi_face"
    SAFE_WIDE = "safe_wide"
    LETTERBOX = "letterbox"


CROP_PROFILE_FOR_TYPE = {
    VideoType.SINGLE_SPEAKER: CropProfile.FACE_CENTERED,
    VideoType.MULTI_SPEAKER: CropProfile.MULTI_FACE,
    VideoType.SCREEN_CONTENT: CropProfile.LETTERBOX,
    VideoType.LIVE_EVENT: CropProfile.SAFE_WIDE,
    VideoType.UNKNOWN: CropProfile.SAFE_WIDE,
}

CROP_FILTERS = {
    CropProfile.FACE_CENTERED: "crop=ih*9/16:ih,scale=1080:1920",
    CropProfile.MULTI_FACE: (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    ),
    CropProfile.SAFE_WIDE: (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    ),
    CropProfile.LETTERBOX: (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
    ),
}

MOTION_SAMPLE_FRAMES = int(os.getenv("MOTION_SAMPLE_FRAMES", "12"))
SKIN_ZONE_THRESHOLD = float(os.getenv("SKIN_ZONE_THRESHOLD", "0.15"))


async def _analyze_motion(video_path: str, duration_s: float) -> float:
    """Motion score 0.0-1.0 based on I-frame ratio."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_frames", "-select_streams", "v:0",
            "-read_intervals", f"0%+{min(30, duration_s):.0f}",
            "-show_entries", "frame=pict_type,pkt_pts_time",
            "-print_format", "json", video_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        data = json.loads(stdout or "{}")
        frames = data.get("frames", [])
        if not frames:
            return 0.5
        i_count = sum(1 for f in frames if f.get("pict_type") == "I")
        total = len(frames)
        if total == 0:
            return 0.5
        i_ratio = i_count / total
        return max(0.0, min(1.0, 1.0 - i_ratio * 5))
    except Exception:
        return 0.5


async def _count_skin_zones_in_frame(frame_path: Path) -> int:
    """Count vertical zones with skin-like content."""
    try:
        zones = {"left": (0, 107), "center": (107, 213), "right": (213, 320)}
        skin_zones = 0
        for zone_name, (x_start, x_end) in zones.items():
            w = x_end - x_start
            tmp = Path(f"/tmp/viraclip_zone_{os.getpid()}_{zone_name}.jpg")
            cmd = [
                "ffmpeg", "-y", "-i", str(frame_path),
                "-vf", f"crop={w}:ih:{x_start}:0",
                "-frames:v", "1", str(tmp),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if tmp.exists():
                has_content = tmp.stat().st_size > int(w * 240 * SKIN_ZONE_THRESHOLD)
                if has_content:
                    skin_zones += 1
                tmp.unlink(missing_ok=True)
        return skin_zones
    except Exception:
        return 1


async def _analyze_skin_distribution(video_path: str, duration_s: float) -> int:
    """Analyze how many distinct skin zones exist."""
    tmp_dir = Path(f"/tmp/viraclip_type_{os.getpid()}")
    tmp_dir.mkdir(exist_ok=True)
    try:
        step = duration_s / 6
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps=1/{step:.1f},scale=320:-1",
            "-frames:v", "6", str(tmp_dir / "frame_%03d.jpg"),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=20.0)
        frames = sorted(tmp_dir.glob("frame_*.jpg"))
        if not frames:
            return 0
        skin_counts = []
        for f in frames:
            count = await _count_skin_zones_in_frame(f)
            skin_counts.append(count)
        from statistics import median
        return int(median(skin_counts)) if skin_counts else 0
    except Exception:
        return 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _analyze_speech_density(video_path: str) -> float:
    """Speech density 0.0-1.0 using silencedetect."""
    try:
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-t", "60",
            "-af", "silencedetect=noise=-35dB:d=0.5",
            "-f", "null", "-",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        output = stderr.decode("utf-8", errors="replace")
        silent_duration = 0.0
        for line in output.splitlines():
            if "silence_duration:" in line:
                try:
                    d = float(line.split("silence_duration:")[-1].strip())
                    silent_duration += d
                except ValueError:
                    pass
        return max(0.0, min(1.0, 1.0 - silent_duration / 60))
    except Exception:
        return 0.5


def _classify_type(motion: float, skin_zones: int, speech: float) -> VideoType:
    if motion < 0.15 and skin_zones == 0:
        return VideoType.SCREEN_CONTENT
    if motion > 0.7:
        return VideoType.LIVE_EVENT
    if skin_zones >= 2 and speech > 0.4:
        return VideoType.MULTI_SPEAKER
    if skin_zones >= 1 and speech > 0.3:
        return VideoType.SINGLE_SPEAKER
    return VideoType.UNKNOWN


def _compute_confidence(motion: float, skin_zones: int, speech: float) -> float:
    consistent = (
        (motion < 0.2 and skin_zones <= 1) or
        (skin_zones >= 2 and speech > 0.5) or
        (motion < 0.1 and skin_zones == 0)
    )
    return 0.85 if consistent else 0.55


async def detect_video_type(video_path: str, duration_s: float) -> dict:
    """Detect video type and return crop profile + filter."""
    try:
        motion_score = await _analyze_motion(video_path, duration_s)
        skin_zones = await _analyze_skin_distribution(video_path, duration_s)
        speech_density = await _analyze_speech_density(video_path)

        video_type = _classify_type(motion_score, skin_zones, speech_density)
        crop_profile = CROP_PROFILE_FOR_TYPE[video_type]
        crop_filter = CROP_FILTERS[crop_profile]

        logger.info(
            "[VideoType] %s → %s (motion=%.2f, skin=%d, speech=%.2f)",
            video_type, crop_profile, motion_score, skin_zones, speech_density,
        )
        return {
            "video_type": video_type,
            "crop_profile": crop_profile,
            "crop_filter": crop_filter,
            "confidence": _compute_confidence(motion_score, skin_zones, speech_density),
            "analysis": {
                "motion_score": round(motion_score, 2),
                "skin_zones": skin_zones,
                "speech_density": round(speech_density, 2),
            },
        }
    except Exception as exc:
        logger.warning("[VideoType] Failed: %s", exc)
        return {
            "video_type": VideoType.UNKNOWN,
            "crop_profile": CropProfile.SAFE_WIDE,
            "crop_filter": CROP_FILTERS[CropProfile.SAFE_WIDE],
            "confidence": 0.0,
        }
