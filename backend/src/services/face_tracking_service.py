"""
SAM 2 Face Tracking Service (B.5)
Opt-in via SAM2_ENABLED=true environment variable.

Uses SAM 2 hiera_tiny (~38 MB) for smooth person/face trajectory tracking.
Falls back to existing MediaPipe-based tracker on any error.
"""
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_SAM2_MODELS_DIR = Path(os.environ.get("SAM2_MODELS_DIR", "/app/models/sam2"))
_SAM2_MODEL_URL = (
    "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
)
_SAM2_MODEL_FILE = _SAM2_MODELS_DIR / "sam2.1_hiera_tiny.pt"


def _ensure_model() -> Optional[Path]:
    """Download SAM 2 hiera_tiny model if not already cached. Returns path or None."""
    _SAM2_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _SAM2_MODELS_DIR / "sam2.1_hiera_tiny.pt"  # same as _SAM2_MODEL_FILE
    if model_path.exists():
        return model_path
    try:
        import urllib.request
        logger.info("📥 Downloading SAM 2 hiera_tiny model (~38 MB)...")
        urllib.request.urlretrieve(_SAM2_MODEL_URL, str(model_path))
        logger.info(f"✅ SAM 2 model cached: {model_path}")
        return model_path
    except Exception as e:
        logger.warning(f"SAM 2 model download failed: {e}")
        return None


def track_person_sam2(
    video_path: Path,
    start_time: float,
    end_time: float,
) -> List[Tuple[float, int, int]]:
    """
    Track the primary person/face in [start_time, end_time] using SAM 2.
    Returns a list of (t, cx, cy) tuples for dynamic cropping.
    Falls back to an empty list (→ centered crop) on any error.

    Only runs when SAM2_ENABLED=true in environment.
    """
    if os.environ.get("SAM2_ENABLED", "false").lower() != "true":
        return []

    try:
        from sam2.build_sam import build_sam2_video_predictor  # type: ignore
    except ImportError:
        logger.debug("sam2 package not installed — face tracking skipped")
        return []

    model_path = _ensure_model()
    if model_path is None:
        return []

    try:
        import cv2
        import numpy as np

        predictor = build_sam2_video_predictor("sam2_hiera_tiny.yaml", str(model_path))

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps)

        # Read first frame to find initial face point
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        ret, first_frame = cap.read()
        if not ret:
            cap.release()
            return []

        # Use MediaPipe to get initial face center for SAM 2 prompt
        init_cx, init_cy = _mediapipe_face_center(first_frame)
        if init_cx is None:
            # No face found — use frame center as fallback
            h, w = first_frame.shape[:2]
            init_cx, init_cy = w // 2, h // 3

        trajectory: List[Tuple[float, int, int]] = []

        with predictor.init_state(video_path=str(video_path)) as inference_state:
            predictor.add_new_points_or_box(
                inference_state,
                frame_idx=start_frame,
                obj_id=1,
                points=np.array([[init_cx, init_cy]], dtype=np.float32),
                labels=np.array([1], dtype=np.int32),
            )

            for frame_idx, object_ids, masks in predictor.propagate_in_video(
                inference_state,
                start_frame_idx=start_frame,
                max_frame_num_to_track=(end_frame - start_frame),
            ):
                t = frame_idx / fps
                if masks and len(masks) > 0:
                    mask = masks[0].squeeze()
                    ys, xs = np.where(mask > 0.5)
                    if len(xs) > 0:
                        cx = int(xs.mean())
                        cy = int(ys.mean())
                        trajectory.append((t, cx, cy))

        cap.release()
        logger.info(f"✅ SAM 2 trajectory: {len(trajectory)} points")
        return trajectory

    except Exception as e:
        logger.warning(f"SAM 2 tracking failed, using centered crop: {e}")
        return []


def _mediapipe_face_center(frame) -> Tuple[Optional[int], Optional[int]]:
    """
    Return (cx, cy) of the primary face using MediaPipe FaceMesh (478 landmarks).
    Uses nose-bridge landmark (idx 1) for a stable, accurate crop center.
    Falls back to basic FaceDetection bbox if FaceMesh fails.
    """
    try:
        import mediapipe as mp
        import cv2

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame.shape[:2]

        # Primary: FaceMesh — 478 landmarks, nose-bridge = index 1
        with mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        ) as face_mesh:
            results = face_mesh.process(rgb)
            if results.multi_face_landmarks:
                lm = results.multi_face_landmarks[0].landmark
                # Landmark 1 = nose bridge (glabella), stable across expressions
                nose = lm[1]
                cx = int(nose.x * w)
                cy = int(nose.y * h)
                return cx, cy
    except Exception:
        pass

    # Fallback: basic FaceDetection bbox center
    try:
        import mediapipe as mp
        import cv2

        mp_face = mp.solutions.face_detection
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame.shape[:2]
        with mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.4) as detector:
            results = detector.process(rgb)
            if results.detections:
                det = results.detections[0]
                bbox = det.location_data.relative_bounding_box
                cx = int((bbox.xmin + bbox.width / 2) * w)
                cy = int((bbox.ymin + bbox.height / 2) * h)
                return cx, cy
    except Exception:
        pass

    return None, None
