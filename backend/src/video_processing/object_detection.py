"""
YOLOv10-nano contextual object detection for B-Roll keyword extraction.
Downloads the 6MB nano model on first use (~once per container lifetime).
Falls back gracefully when ultralytics / torch are unavailable.

Usage:
    from .object_detection import detect_objects_in_video
    keywords = await detect_objects_in_video("clip.mp4", max_frames=5)
    # → ["person", "laptop", "book", ...]
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_YOLO_MODEL_DIR = Path(os.environ.get("YOLO_MODELS_DIR", "/app/models/yolo"))
_YOLO_MODEL_NAME = "yolov10n.pt"  # 6 MB nano model

# Objects commonly useful for B-Roll (filter out overly generic ones)
_SKIP_LABELS = {"person", "face", "hand", "body", "head"}

# Map COCO class names to better B-Roll search terms
_LABEL_TO_BROLL: dict = {
    "laptop": "computer work",
    "cell phone": "smartphone social media",
    "book": "reading study",
    "cup": "coffee morning",
    "car": "driving car",
    "dog": "dog pet",
    "cat": "cat pet",
    "food": "food eating",
    "pizza": "food pizza",
    "sports ball": "sport ball",
    "bicycle": "bicycle riding",
    "airplane": "airplane travel",
    "boat": "boat ocean",
    "tv": "television screen",
    "keyboard": "computer typing",
    "mouse": "computer mouse",
    "microphone": "podcast microphone",
    "chair": "office workspace",
    "desk": "office desk workspace",
    "plant": "nature plant",
    "bottle": "water bottle",
    "clock": "time clock",
    "money": "cash money finance",
    "phone": "phone call",
}


def _ensure_model() -> Optional[Path]:
    """Download YOLOv10n if not cached. Returns model path or None."""
    _YOLO_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _YOLO_MODEL_DIR / _YOLO_MODEL_NAME
    if model_path.exists() and model_path.stat().st_size > 1_000_000:
        return model_path
    try:
        import urllib.request
        url = f"https://github.com/THU-MIG/yolov10/releases/download/v1.1/{_YOLO_MODEL_NAME}"
        logger.info(f"📥 Downloading YOLOv10n (~6MB) from {url} ...")
        urllib.request.urlretrieve(url, str(model_path))
        logger.info(f"✅ YOLOv10n cached: {model_path}")
        return model_path
    except Exception as exc:
        logger.warning(f"[yolo] Model download failed: {exc}")
        return None


def detect_objects_in_frame(frame, model) -> List[str]:
    """Run YOLOv10 on a single BGR frame, return list of unique class names."""
    try:
        results = model(frame, verbose=False)
        labels: List[str] = []
        for r in results:
            for cls_id in r.boxes.cls.tolist():
                name = model.names[int(cls_id)].lower()
                if name not in _SKIP_LABELS:
                    labels.append(name)
        return list(set(labels))
    except Exception as exc:
        logger.debug(f"[yolo] Frame inference failed: {exc}")
        return []


async def detect_objects_in_video(
    video_path: str,
    max_frames: int = 6,
    conf_threshold: float = 0.35,
) -> List[str]:
    """
    Sample `max_frames` keyframes from the video and detect objects using YOLOv10n.
    Returns a deduplicated list of B-Roll search keywords.

    Falls back to [] when YOLO is disabled or unavailable.
    """
    if os.environ.get("YOLO_BROLL_ENABLED", "false").lower() != "true":
        return []

    def _run_detection() -> List[str]:
        try:
            import cv2
            from ultralytics import YOLO

            model_path = _ensure_model()
            if model_path is None:
                return []

            model = YOLO(str(model_path))
            model.conf = conf_threshold

            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            step = max(1, total_frames // max_frames)

            all_labels: List[str] = []
            for i in range(max_frames):
                frame_idx = i * step
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break
                all_labels.extend(detect_objects_in_frame(frame, model))

            cap.release()

            # Deduplicate + map to better search terms
            unique: List[str] = []
            seen: set = set()
            for lbl in all_labels:
                term = _LABEL_TO_BROLL.get(lbl, lbl)
                if term not in seen:
                    seen.add(term)
                    unique.append(term)

            logger.info(f"[yolo] Detected objects: {unique[:8]}")
            return unique[:8]

        except ImportError:
            logger.debug("[yolo] ultralytics not installed — skipping object detection")
            return []
        except Exception as exc:
            logger.debug(f"[yolo] Detection failed: {exc}")
            return []

    return await asyncio.get_event_loop().run_in_executor(None, _run_detection)
