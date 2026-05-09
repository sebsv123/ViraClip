"""
Video type classifier — analyzes frames to determine content type.
Runs in preflight, parallel with language and aspect ratio detection.
"""
import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

VIDEO_TYPES = {
    "talking_head":    "Persona hablando a cámara — crop facial agresivo OK",
    "podcast_camera":  "Podcast con cámara — múltiples personas, cortes suaves",
    "screen_recording": "Grabación de pantalla — sin crop, subtítulos abajo",
    "broll_heavy":     "Predomina B-roll — mínimos subtítulos en talking head",
}

VIDEO_TYPE_PRESETS = {
    "talking_head": {
        "crop_style":        "face_centered",
        "zoom_intensity":    0.15,
        "caption_position":  "bottom_third",
        "broll_enabled":     True,
        "jump_cuts_enabled": True,
    },
    "podcast_camera": {
        "crop_style":        "wide_safe",
        "zoom_intensity":    0.05,
        "caption_position":  "bottom_fifth",
        "broll_enabled":     False,
        "jump_cuts_enabled": False,
    },
    "screen_recording": {
        "crop_style":        "no_crop",
        "zoom_intensity":    0.0,
        "caption_position":  "bottom_overlay",
        "broll_enabled":     False,
        "jump_cuts_enabled": False,
    },
    "broll_heavy": {
        "crop_style":        "smart_crop",
        "zoom_intensity":    0.08,
        "caption_position":  "center_safe",
        "broll_enabled":     False,
        "jump_cuts_enabled": True,
    },
}


async def classify_video_type(video_path: str) -> tuple[str, float]:
    """
    Clasifica el tipo de video analizando frames.
    Retorna (video_type, confidence).
    """
    tmp_dir = Path(f"/tmp/viraclip_classify_{os.getpid()}")
    try:
        tmp_dir.mkdir(exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", "fps=0.5,scale=320:-1",
            "-frames:v", "5",
            str(tmp_dir / "frame_%03d.jpg"),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=20.0)

        frames = list(tmp_dir.glob("frame_*.jpg"))
        if not frames:
            return "talking_head", 0.5

        scores = {t: 0.0 for t in VIDEO_TYPES}
        for frame_path in frames[:5]:
            try:
                cmd_stats = [
                    "ffprobe", "-v", "quiet",
                    "-show_frames", "-select_streams", "v",
                    "-read_intervals", "%+#1",
                    "-print_format", "json",
                    str(frame_path),
                ]
                proc2 = await asyncio.create_subprocess_exec(
                    *cmd_stats,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc2.communicate(), timeout=5.0)
                data = json.loads(stdout or "{}")
                frames_info = data.get("frames", [{}])
                if frames_info:
                    f = frames_info[0]
                    w = f.get("width", 0)
                    h = f.get("height", 0)
                    if w and h and (w / h) > 2.0:
                        scores["screen_recording"] += 0.3
            except Exception:
                pass

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]
        if best_score < 0.3:
            return "talking_head", 0.5
        return best_type, min(best_score, 1.0)

    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("[Classifier] Failed: %s", exc)
        return "talking_head", 0.5
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
