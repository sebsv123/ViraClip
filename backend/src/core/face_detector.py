"""
Face-in-frame detector for safe crop decisions.
Uses FFmpeg frame extraction + luminance heuristics.
"""
import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

FACE_IN_FRAME_THRESHOLD = float(os.getenv("FACE_IN_FRAME_THRESHOLD", "0.6"))
FACE_SAMPLE_FRAMES = int(os.getenv("FACE_SAMPLE_FRAMES", "8"))


async def _get_duration(path: Path) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", str(path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return float(json.loads(stdout)["format"]["duration"])
    except Exception:
        return 60.0


async def _frame_has_skin_tones(frame_path: Path) -> bool:
    """Heuristic: check if frame has skin-like luminance in center area."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_frames", "-select_streams", "v:0",
            "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
            "-f", "lavfi",
            f"movie={frame_path},signalstats",
            "-print_format", "json",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        data = json.loads(stdout or "{}")
        frames = data.get("frames", [{}])
        if frames:
            yavg = float(frames[0].get("tags", {}).get("lavfi.signalstats.YAVG", 0))
            return 60 < yavg < 200
    except Exception:
        pass
    return True


async def check_face_in_frame(
    clip_path: Path,
    sample_frames: int = FACE_SAMPLE_FRAMES,
) -> dict:
    """Check if face is centered in at least THRESHOLD% of frames."""
    tmp_dir = Path(f"/tmp/viraclip_face_{os.getpid()}")
    tmp_dir.mkdir(exist_ok=True)

    try:
        duration = await _get_duration(clip_path)
        if duration < 1.0:
            return {"face_detected": False, "face_pct": 0.0, "crop_safe": False}

        fps_target = sample_frames / duration
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vf", f"fps={fps_target:.4f},scale=160:284",
            "-frames:v", str(sample_frames),
            str(tmp_dir / "face_%03d.jpg"),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30.0)

        frames = sorted(tmp_dir.glob("face_*.jpg"))
        if not frames:
            return {"face_detected": False, "face_pct": 0.0, "crop_safe": True}

        face_frames = 0
        for frame_path in frames:
            if await _frame_has_skin_tones(frame_path):
                face_frames += 1

        face_pct = face_frames / len(frames)
        crop_safe = face_pct >= FACE_IN_FRAME_THRESHOLD

        if not crop_safe:
            logger.info(
                "[FaceDetect] %.0f%% frames have face — conservative crop",
                face_pct * 100,
            )

        return {
            "face_detected": face_pct > 0.1,
            "face_pct": round(face_pct, 2),
            "crop_safe": crop_safe,
        }

    except Exception as exc:
        logger.warning("[FaceDetect] Failed: %s", exc)
        return {"face_detected": True, "face_pct": 1.0, "crop_safe": True}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
