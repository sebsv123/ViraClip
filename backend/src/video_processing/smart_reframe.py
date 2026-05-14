"""
from src import gpu_utils
Smart Reframe — produce 1:1 (Instagram feed) and 16:9 (YouTube/LinkedIn)
variants from a 9:16 source clip using FFmpeg crop + face-tracking.

Strategy:
  - Detect subject X position via MediaPipe FaceMesh (first frame sample).
  - For 1:1: crop a square centred on face_x, pillar-box to fill gaps if needed.
  - For 16:9: letterbox the 9:16 with blurred background fill (YouTube standard).
  - CPU-only; no GPU required.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")


@dataclass
class ReframeResult:
    ratio: str           # "1:1" | "16:9"
    output_path: str
    width: int
    height: int
    face_x_ratio: float  # 0-1 normalised face position used for crop
    method: str          # "face_crop" | "centre_crop" | "letterbox"


async def _probe_dimensions(video_path: str) -> tuple[int, int]:
    """Return (width, height) of video using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        parts = stdout.decode().strip().split(",")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 1080, 1920   # assume 9:16 default


async def _detect_face_x_ratio(video_path: str) -> float:
    """
    Sample frame at 1s and detect face X centre using MediaPipe FaceMesh.
    Falls back to 0.5 (centred) if unavailable.
    """
    try:
        import mediapipe as mp
        import numpy as np

        # Extract single frame via ffmpeg to stdout
        cmd = [
            FFMPEG, "-ss", "1", "-i", video_path,
            "-vframes", "1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-vf", "scale=320:-1",
            "pipe:1",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        raw, _ = await proc.communicate()
        if not raw:
            return 0.5

        # Determine actual frame dimensions from raw bytes
        # We asked for scale=320:-1 so width=320, height=inferred
        frame_w = 320
        num_pixels = len(raw) // 3
        frame_h = num_pixels // frame_w if frame_w > 0 else 0
        if frame_h == 0:
            return 0.5

        frame = np.frombuffer(raw, dtype=np.uint8).reshape((frame_h, frame_w, 3))

        mp_face = mp.solutions.face_mesh
        with mp_face.FaceMesh(
            static_image_mode=True, max_num_faces=1, refine_landmarks=False
        ) as fm:
            result = fm.process(frame)
            if result.multi_face_landmarks:
                lm = result.multi_face_landmarks[0].landmark
                xs = [l.x for l in lm]
                return float(sum(xs) / len(xs))
    except Exception as e:
        logger.debug("Face detection for reframe failed: %s — using centre", e)
    return 0.5


async def reframe_to_square(
    video_path: str,
    output_path: str,
    face_x_ratio: float = 0.5,
    src_w: int = 1080,
    src_h: int = 1920,
) -> ReframeResult:
    """
    Produce a 1:1 square crop from a 9:16 source.
    Crops a `src_h × src_h` region centred on face_x.
    Since src_h > src_w for 9:16, we use src_w × src_w.
    """
    crop_size = src_w          # square side = source width
    # horizontal offset: face_x_ratio maps 0-1 to 0-0 (already full width)
    # For vertical: centre on face or use top third (face usually in top 40%)
    face_y = 0.35              # assume face in top-third area
    crop_y = max(0, min(int(src_h * face_y - crop_size // 2),
                        src_h - crop_size))

    vf = f"crop={crop_size}:{crop_size}:0:{crop_y},scale={crop_size}:{crop_size}"
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-vf", vf,
        *gpu_utils.ffmpeg_codec_flags("high"),
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("Square reframe failed: %s", stderr.decode()[-500:])
        return ReframeResult("1:1", video_path, src_w, src_w, face_x_ratio, "failed")

    return ReframeResult(
        ratio="1:1",
        output_path=output_path,
        width=crop_size,
        height=crop_size,
        face_x_ratio=face_x_ratio,
        method="face_crop",
    )


async def reframe_to_landscape(
    video_path: str,
    output_path: str,
    src_w: int = 1080,
    src_h: int = 1920,
) -> ReframeResult:
    """
    Produce a 16:9 letterbox variant: blur-fill background + centred 9:16 clip.
    Final resolution: 1920×1080.
    """
    out_w, out_h = 1920, 1080
    # Scale 9:16 source to fit vertically in 1080 → 607×1080 (portrait in landscape)
    scaled_w = int(out_h * src_w / src_h)
    pad_x = (out_w - scaled_w) // 2

    # Complex filter: blurred bg from scaled-to-fill + overlay scaled portrait
    vf = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},gblur=sigma=20,setsar=1[blurred];"
        f"[fg]scale={scaled_w}:{out_h}[portrait];"
        f"[blurred][portrait]overlay={pad_x}:0"
    )
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-filter_complex", vf,
        *gpu_utils.ffmpeg_codec_flags("high"),
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("Landscape reframe failed: %s", stderr.decode()[-500:])
        return ReframeResult("16:9", video_path, out_w, out_h, 0.5, "failed")

    return ReframeResult(
        ratio="16:9",
        output_path=output_path,
        width=out_w,
        height=out_h,
        face_x_ratio=0.5,
        method="letterbox",
    )


async def generate_all_reframes(
    video_path: str,
    output_dir: Optional[str] = None,
    ratios: Optional[list[str]] = None,
) -> list[ReframeResult]:
    """
    Generate all requested aspect-ratio variants.
    ratios: list of "1:1" | "16:9" (default: both)
    Returns list of ReframeResult (one per ratio).
    """
    if ratios is None:
        ratios = ["1:1", "16:9"]

    out_dir = Path(output_dir) if output_dir else Path(video_path).parent
    stem = Path(video_path).stem

    src_w, src_h = await _probe_dimensions(video_path)
    face_x = await _detect_face_x_ratio(video_path) if "1:1" in ratios else 0.5

    results: list[ReframeResult] = []
    tasks = []

    if "1:1" in ratios:
        out = str(out_dir / f"{stem}_1x1.mp4")
        tasks.append(reframe_to_square(video_path, out, face_x, src_w, src_h))

    if "16:9" in ratios:
        out = str(out_dir / f"{stem}_16x9.mp4")
        tasks.append(reframe_to_landscape(video_path, out, src_w, src_h))

    for coro in tasks:
        r = await coro
        results.append(r)

    return results
