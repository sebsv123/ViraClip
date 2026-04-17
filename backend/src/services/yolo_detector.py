"""
yolo_detector.py
================
YOLOv10 visual grounding for contextual B-roll enhancement.

Extracts a keyframe from a clip and detects objects present in it so the
B-roll pipeline can:
  • skip keywords whose subject is already visible in the frame
  • prioritise B-roll for concepts mentioned in transcript but not seen visually

Model: yolov10n.pt  (6 MB nano model, ~50 ms/frame on CPU)
Guard: lazy-imported; gracefully returns empty set if ultralytics unavailable.
Env:   YOLO_ENABLED=false  — hard-disable (default: enabled)
       YOLO_MODEL=yolov10n  — override model variant
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

YOLO_ENABLED: bool = os.getenv("YOLO_ENABLED", "true").lower() != "false"
_YOLO_MODEL_NAME: str = os.getenv("YOLO_MODEL", "yolov10n.pt")
_CONF_THRESHOLD: float = float(os.getenv("YOLO_CONF", "0.35"))
_MAX_KEYFRAMES: int = 3  # number of frames to sample for detection

_model_cache: Optional[Any] = None


def _get_model() -> Optional[Any]:
    """Lazy-load YOLOv10 model; returns None if ultralytics not available."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    try:
        from ultralytics import YOLO
        _model_cache = YOLO(_YOLO_MODEL_NAME)
        logger.info("[YOLO] Model loaded: %s", _YOLO_MODEL_NAME)
        return _model_cache
    except Exception as exc:
        logger.warning("[YOLO] Could not load model (%s) — visual grounding disabled", exc)
        return None


async def extract_keyframe(video_path: Path, output_path: Path, timestamp: float = 0.5) -> bool:
    """
    Extract a single frame from *video_path* at *timestamp* seconds via FFmpeg.
    Returns True if the output file was created successfully.
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=15)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as exc:
        logger.debug("[YOLO] Frame extraction failed: %s", exc)
        return False


def detect_objects_in_frame(frame_path: Path) -> Set[str]:
    """
    Run YOLOv10 on *frame_path* and return a set of detected class names
    (lowercased) with confidence >= _CONF_THRESHOLD.
    """
    model = _get_model()
    if model is None:
        return set()
    try:
        results = model(str(frame_path), conf=_CONF_THRESHOLD, verbose=False)
        labels: Set[str] = set()
        for result in results:
            if result.boxes is None:
                continue
            for cls_id, conf in zip(result.boxes.cls, result.boxes.conf):
                if float(conf) >= _CONF_THRESHOLD:
                    name = result.names.get(int(cls_id), "")
                    if name:
                        labels.add(name.lower())
        return labels
    except Exception as exc:
        logger.debug("[YOLO] Detection failed: %s", exc)
        return set()


async def get_visual_context(
    video_path: Path,
    clip_duration: float,
    work_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Sample up to _MAX_KEYFRAMES from the clip, run YOLO on each,
    and return aggregated visual context.

    Returns:
        {
          "detected_labels": set[str],   # all unique labels across frames
          "frame_count": int,            # how many frames were sampled
        }
    """
    if not YOLO_ENABLED:
        return {"detected_labels": set(), "frame_count": 0}

    if not video_path.exists():
        return {"detected_labels": set(), "frame_count": 0}

    work = work_dir or video_path.parent
    all_labels: Set[str] = set()
    frames_ok = 0

    # Sample timestamps distributed across the clip
    n = min(_MAX_KEYFRAMES, max(1, int(clip_duration / 3)))
    timestamps = [clip_duration * (i + 1) / (n + 1) for i in range(n)]

    for i, ts in enumerate(timestamps):
        frame_path = work / f"_yolo_frame_{video_path.stem}_{i}.jpg"
        ok = await extract_keyframe(video_path, frame_path, timestamp=ts)
        if ok:
            labels = detect_objects_in_frame(frame_path)
            all_labels.update(labels)
            frames_ok += 1
            try:
                frame_path.unlink(missing_ok=True)
            except OSError:
                pass

    if all_labels:
        logger.info("[YOLO] Detected in %d frame(s): %s", frames_ok, sorted(all_labels))

    return {"detected_labels": all_labels, "frame_count": frames_ok}


def filter_keywords_with_yolo(
    transcript_keywords: List[str],
    detected_labels: Set[str],
) -> List[str]:
    """
    Remove keywords that are already visually present in the clip
    (i.e. no B-roll needed for what the viewer can already see).

    Matching is substring-based to handle synonyms:
      e.g. keyword "person" matches YOLO label "person" ✓
           keyword "beach" does NOT match "car" — kept ✓
    """
    if not detected_labels:
        return transcript_keywords

    filtered = []
    for kw in transcript_keywords:
        kw_lower = kw.lower()
        already_visible = any(
            kw_lower in label or label in kw_lower
            for label in detected_labels
        )
        if already_visible:
            logger.debug("[YOLO] Skipping keyword '%s' — already visible in frame", kw)
        else:
            filtered.append(kw)

    # Always keep at least one keyword to ensure B-roll can be found
    return filtered if filtered else transcript_keywords[:1]
