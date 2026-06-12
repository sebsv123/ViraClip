"""
Scene Analysis - V4 Elite visual rhythm scoring.
Uses PySceneDetect for cut detection and visual rhythm analysis.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    """Return ffmpeg binary path, preferring system ffmpeg with NVENC."""
    from src.utils.gpu_utils import get_ffmpeg_exe
    return get_ffmpeg_exe()




def analyze_clip_rhythm(video_path: Path) -> dict:
    """
    Detecta ritmo visual de un clip: número de escenas, duración media, ritmo.
    Clips con 3-8 cortes en 30s tienen el ritmo óptimo para retención.
    
    Returns dict with: scene_count, avg_scene_duration, rhythm_score (0-100), edit_pace
    """
    try:
        from scenedetect import detect, AdaptiveDetector
    except ImportError:
        logger.debug("scenedetect not installed, skipping rhythm analysis")
        return {"scene_count": 0, "avg_scene_duration": 0.0, "rhythm_score": 50, "edit_pace": "unknown"}

    try:
        scenes = detect(str(video_path), AdaptiveDetector())
        num_scenes = len(scenes)

        if not scenes:
            return {"scene_count": 0, "avg_scene_duration": 0.0, "rhythm_score": 40, "edit_pace": "static"}

        durations = [(end - start).get_seconds() for start, end in scenes]
        avg_duration = sum(durations) / len(durations)

        # Ritmo óptimo: 2-4 segundos por escena → máximo score
        # < 1s: demasiado rápido (mareo), > 8s: demasiado lento (aburrido)
        if 2.0 <= avg_duration <= 4.0:
            rhythm_score = 100
        elif 1.0 <= avg_duration < 2.0 or 4.0 < avg_duration <= 6.0:
            rhythm_score = 75
        elif avg_duration < 1.0:
            rhythm_score = max(30, int(100 - (1.0 - avg_duration) * 70))
        else:
            rhythm_score = max(20, int(100 - (avg_duration - 6.0) * 12))

        if avg_duration < 1.5:
            edit_pace = "very_fast"
        elif avg_duration < 3.0:
            edit_pace = "fast"
        elif avg_duration < 6.0:
            edit_pace = "medium"
        else:
            edit_pace = "slow"

        logger.debug(f"Scene analysis: {num_scenes} scenes, avg {avg_duration:.2f}s, rhythm={rhythm_score}")

        return {
            "scene_count": num_scenes,
            "avg_scene_duration": round(avg_duration, 2),
            "rhythm_score": rhythm_score,
            "edit_pace": edit_pace,
        }

    except Exception as e:
        logger.warning(f"Scene analysis failed for {video_path.name}: {e}")
        return {"scene_count": 0, "avg_scene_duration": 0.0, "rhythm_score": 50, "edit_pace": "unknown"}


def detect_loop_potential(video_path: Path, threshold: float = 0.85) -> dict:
    """
    Detecta si el clip tiene potencial para loop infinito (TikTok looping).
    Compara el último frame con el primero — si son similares, el loop es natural.
    
    Returns dict with: loop_score (0-100), can_loop (bool)
    """
    try:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(str(video_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames < 30:
            cap.release()
            return {"loop_score": 0, "can_loop": False}

        # Leer primer frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret1, first_frame = cap.read()

        # Leer último frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
        ret2, last_frame = cap.read()
        cap.release()

        if not ret1 or not ret2:
            return {"loop_score": 0, "can_loop": False}

        # Calcular similitud histograma (rápido, sin GPU)
        first_gray = cv2.cvtColor(cv2.resize(first_frame, (64, 64)), cv2.COLOR_BGR2GRAY)
        last_gray = cv2.cvtColor(cv2.resize(last_frame, (64, 64)), cv2.COLOR_BGR2GRAY)

        first_hist = cv2.calcHist([first_gray], [0], None, [64], [0, 256])
        last_hist = cv2.calcHist([last_gray], [0], None, [64], [0, 256])

        similarity = cv2.compareHist(first_hist, last_hist, cv2.HISTCMP_CORREL)
        loop_score = int(max(0, min(100, similarity * 100)))
        can_loop = similarity >= threshold

        return {"loop_score": loop_score, "can_loop": can_loop}

    except Exception as e:
        logger.warning(f"Loop detection failed: {e}")
        return {"loop_score": 0, "can_loop": False}


def extract_representative_frames(
    video_path: Path,
    n_frames: int = 10,
    output_dir: Optional[Path] = None
) -> list[Path]:
    """
    Extrae N frames representativos del clip para análisis visual con Kimi-K2.5 / Qwen3-VL.
    Distribuye frames uniformemente a lo largo del clip.
    """
    try:
        import subprocess
        import uuid

        if output_dir is None:
            output_dir = Path("/tmp") / f"frames_{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # ffmpeg: extraer N frames distribuidos uniformemente
        cmd = [
            _get_ffmpeg_exe(), "-y",
            "-i", str(video_path),
            "-vf", f"select='not(mod(n,{max(1, int(30 / n_frames))}))',scale=640:-1",
            "-vframes", str(n_frames),
            "-q:v", "3",
            str(output_dir / "frame_%03d.jpg")
        ]

        import subprocess
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            logger.warning(f"Frame extraction failed: {result.stderr.decode()[:200]}")
            return []

        frames = sorted(output_dir.glob("frame_*.jpg"))
        logger.debug(f"Extracted {len(frames)} frames from {video_path.name}")
        return frames[:n_frames]

    except Exception as e:
        logger.warning(f"Frame extraction failed: {e}")
        return []
