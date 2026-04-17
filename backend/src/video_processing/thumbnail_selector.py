"""
Thumbnail auto-selection: extracts candidate frames from a clip and scores
them using Laplacian variance (sharpness) and MediaPipe face presence.

Optionally queries Qwen3-VL via Ollama for richer scoring when available.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CANDIDATES = 8   # frames sampled per clip
_THUMB_W    = 1080
_THUMB_H    = 1920


def _score_frame(frame) -> float:
    """
    Heuristic frame quality score:
      - Laplacian variance  (sharpness, 0-∞, higher = sharper)
      - Face bonus          (+50 if face detected via MediaPipe)
      - Brightness penalty  (-20 if too dark / too bright)
    """
    try:
        import cv2
        import numpy as np

        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Brightness check
        mean_lum = float(gray.mean())
        if mean_lum < 40 or mean_lum > 220:
            score -= 20.0

        # Face detection bonus
        try:
            import mediapipe as mp
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame.shape[:2]
            with mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.4
            ) as det:
                if det.process(rgb).detections:
                    score += 50.0
        except Exception:
            pass

        return max(0.0, score)
    except Exception:
        return 0.0


async def select_best_thumbnail(
    video_path: str,
    output_path: str,
    n_candidates: int = _CANDIDATES,
) -> Optional[str]:
    """
    Extract *n_candidates* frames, pick the sharpest with a face, save as JPEG.
    Returns *output_path* on success, None on failure.
    """
    def _run() -> Optional[str]:
        try:
            import cv2

            cap = cv2.VideoCapture(video_path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0

            # Skip first 5% and last 5% (usually fade in/out)
            skip_start = int(total * 0.05)
            skip_end   = int(total * 0.95)
            usable      = max(1, skip_end - skip_start)
            step        = max(1, usable // n_candidates)

            best_frame = None
            best_score = -1.0

            for i in range(n_candidates):
                idx = skip_start + i * step
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if not ret:
                    continue
                s = _score_frame(frame)
                if s > best_score:
                    best_score = s
                    best_frame = frame

            cap.release()

            if best_frame is None:
                return None

            # Resize to 1080x1920 (or keep as-is if already portrait)
            h, w = best_frame.shape[:2]
            if w != _THUMB_W or h != _THUMB_H:
                best_frame = cv2.resize(best_frame, (_THUMB_W, _THUMB_H))

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), best_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            logger.info(f"🖼 Thumbnail saved (score={best_score:.1f}): {out.name}")
            return str(out)

        except Exception as exc:
            logger.debug(f"[thumb] Selection failed: {exc}")
            return None

    return await asyncio.get_event_loop().run_in_executor(None, _run)
