"""
Face detection and tracking utilities.
Handles face detection, trajectory tracking, and active speaker identification.
"""

from typing import List, Tuple, Any, Optional
import logging
import numpy as np

logger = logging.getLogger(__name__)

# Imports lazy-loaded to avoid heavy dependencies at module load time
cv2 = None
mp = None


def _import_cv2():
    """Lazy import cv2."""
    global cv2
    if cv2 is None:
        import cv2 as _cv2
        cv2 = _cv2
    return cv2


def _import_mediapipe():
    """Lazy import mediapipe."""
    global mp
    if mp is None:
        try:
            import mediapipe as _mp
            mp = _mp
        except ImportError:
            mp = None
    return mp


def detect_optimal_crop_region(
    video_clip: Any, 
    start_time: float, 
    end_time: float,
    target_aspect_ratio: float = 9/16
) -> Optional[Tuple[int, int, int, int]]:
    """
    Detect optimal crop region for vertical video format.
    Returns (x, y, width, height) or None for center crop.
    """
    try:
        faces = detect_faces_in_clip(video_clip, start_time, end_time)
        if not faces:
            return None
        
        # Find best face (largest, most central)
        best_face = max(faces, key=lambda f: f[2])  # largest area
        face_x, face_y, face_area, confidence = best_face
        
        # Calculate crop region centered on face
        clip_w, clip_h = video_clip.size
        crop_width = int(clip_h * target_aspect_ratio)
        crop_height = clip_h
        
        # Center crop on face x position
        x = max(0, min(face_x - crop_width//2, clip_w - crop_width))
        y = 0
        
        return (x, y, crop_width, crop_height)
    except Exception as e:
        logger.warning(f"Face-based crop failed: {e}")
        return None


def detect_active_speaker(
    video_clip: Any, start_time: float, end_time: float
) -> Optional[Tuple[int, int]]:
    """Detect the active speaker position."""
    faces = detect_faces_in_clip(video_clip, start_time, end_time)
    if faces:
        best = max(faces, key=lambda f: f[3])  # highest confidence
        return (best[0], best[1])
    return None

def detect_faces_in_clip(
    video_clip: Any, start_time: float, end_time: float
) -> List[Tuple[int, int, int, float]]:
    """
    Improved face detection using multiple methods and temporal consistency.
    Returns list of (x, y, area, confidence) tuples.
    """
    cv2 = _import_cv2()
    face_centers = []

    try:
        mp = _import_mediapipe()
        mp_face_detection = None
        if mp is not None:
            try:
                mp_face_detection = mp.solutions.face_detection.FaceDetection(
                    model_selection=0,
                    min_detection_confidence=0.5,
                )
                logger.info("Using MediaPipe face detector")
            except Exception as e:
                logger.warning(f"MediaPipe face detector failed to initialize: {e}")

        haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        # Try to load DNN face detector
        dnn_net = None
        try:
            prototxt_path = cv2.data.haarcascades.replace(
                "haarcascades", "opencv_face_detector.pbtxt"
            )
            model_path = cv2.data.haarcascades.replace(
                "haarcascades", "opencv_face_detector_uint8.pb"
            )
            import os
            if os.path.exists(prototxt_path) and os.path.exists(model_path):
                dnn_net = cv2.dnn.readNetFromTensorflow(model_path, prototxt_path)
                logger.info("OpenCV DNN face detector loaded as backup")
        except Exception:
            pass

        # Sample frames
        duration = end_time - start_time
        sample_interval = min(0.5, duration / 10)
        sample_times = []
        current_time = start_time
        while current_time < end_time:
            sample_times.append(current_time)
            current_time += sample_interval

        if duration > 1.0:
            middle_time = start_time + duration / 2
            if middle_time not in sample_times:
                sample_times.append(middle_time)

        sample_times = [t for t in sample_times if t < end_time]
        logger.info(f"Sampling {len(sample_times)} frames for face detection")

        for sample_time in sample_times:
            try:
                frame = video_clip.get_frame(sample_time)
                height, width = frame.shape[:2]
                detected_faces = []

                # Try MediaPipe first
                if mp_face_detection is not None:
                    try:
                        results = mp_face_detection.process(frame)
                        if results.detections:
                            for detection in results.detections:
                                bbox = detection.location_data.relative_bounding_box
                                confidence = detection.score[0]
                                x = int(bbox.xmin * width)
                                y = int(bbox.ymin * height)
                                w = int(bbox.width * width)
                                h = int(bbox.height * height)
                                if w > 30 and h > 30:
                                    detected_faces.append((x, y, w, h, confidence))
                    except Exception as e:
                        logger.debug(f"MediaPipe detection failed: {e}")

                # Try DNN detector
                if not detected_faces and dnn_net is not None:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        blob = cv2.dnn.blobFromImage(
                            frame_bgr, 1.0, (300, 300), [104, 117, 123]
                        )
                        dnn_net.setInput(blob)
                        detections = dnn_net.forward()
                        for i in range(detections.shape[2]):
                            confidence = detections[0, 0, i, 2]
                            if confidence > 0.5:
                                x1 = int(detections[0, 0, i, 3] * width)
                                y1 = int(detections[0, 0, i, 4] * height)
                                x2 = int(detections[0, 0, i, 5] * width)
                                y2 = int(detections[0, 0, i, 6] * height)
                                w, h = x2 - x1, y2 - y1
                                if w > 30 and h > 30:
                                    detected_faces.append((x1, y1, w, h, confidence))
                    except Exception as e:
                        logger.debug(f"DNN detection failed: {e}")

                # Haar cascade fallback
                if not detected_faces:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                        faces = haar_cascade.detectMultiScale(
                            gray,
                            scaleFactor=1.05,
                            minNeighbors=3,
                            minSize=(50, 50),
                            maxSize=(int(width * 0.8), int(height * 0.8)),
                            flags=cv2.CASCADE_SCALE_IMAGE,
                        )
                        for x, y, w, h in faces:
                            face_area = w * h
                            relative_size = face_area / (width * height)
                            confidence = min(0.9, 0.3 + relative_size * 2)
                            detected_faces.append((x, y, w, h, confidence))
                    except Exception as e:
                        logger.debug(f"Haar cascade detection failed: {e}")

                for x, y, w, h, confidence in detected_faces:
                    face_center_x = x + w // 2
                    face_center_y = y + h // 2
                    face_area = w * h
                    frame_area = width * height
                    relative_area = face_area / frame_area
                    if 0.005 < relative_area < 0.3:
                        face_centers.append(
                            (face_center_x, face_center_y, face_area, confidence)
                        )

            except Exception as e:
                logger.debug(f"Error detecting faces at {sample_time}s: {e}")
                continue

        if mp_face_detection is not None:
            try:
                mp_face_detection.close()
            except Exception:
                pass

        if len(face_centers) > 2:
            face_centers = filter_face_outliers(face_centers)

        logger.info(f"Detected {len(face_centers)} reliable face centers")
        return face_centers

    except Exception as e:
        logger.error(f"Error in face detection: {e}")
        return []


def filter_face_outliers(
    face_centers: List[Tuple[int, int, int, float]],
) -> List[Tuple[int, int, int, float]]:
    """Remove face detections that are outliers (likely false positives)."""
    if len(face_centers) < 3:
        return face_centers

    try:
        x_positions = [x for x, y, area, conf in face_centers]
        y_positions = [y for x, y, area, conf in face_centers]

        median_x = np.median(x_positions)
        median_y = np.median(y_positions)
        std_x = np.std(x_positions)
        std_y = np.std(y_positions)

        filtered_faces = []
        for face in face_centers:
            x, y, area, conf = face
            if abs(x - median_x) <= 2 * std_x and abs(y - median_y) <= 2 * std_y:
                filtered_faces.append(face)

        logger.info(
            f"Filtered {len(face_centers)} -> {len(filtered_faces)} faces (removed outliers)"
        )
        return filtered_faces if filtered_faces else face_centers

    except Exception as e:
        logger.warning(f"Error filtering face outliers: {e}")
        return face_centers


def detect_face_trajectory(
    video_clip: Any,
    start_time: float,
    end_time: float,
    sample_interval: float = 1.0,
) -> List[Tuple[float, int, int]]:
    """
    Detect face center positions over time to build a movement trajectory.
    Returns a list of (relative_time, cx, cy) tuples.
    """
    cv2 = _import_cv2()
    trajectory: List[Tuple[float, int, int]] = []
    duration = end_time - start_time
    if duration <= 0:
        return trajectory

    try:
        mp = _import_mediapipe()
        mp_face_detection = None
        if mp is not None:
            try:
                mp_face_detection = mp.solutions.face_detection.FaceDetection(
                    model_selection=0, min_detection_confidence=0.5
                )
            except Exception:
                pass

        haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        actual_interval = min(sample_interval, duration / max(4, int(duration)))
        sample_times = []
        t = start_time
        while t < end_time:
            sample_times.append(t)
            t += actual_interval

        for abs_t in sample_times:
            try:
                frame = video_clip.get_frame(abs_t)
                height, width = frame.shape[:2]
                faces_found = []

                if mp_face_detection is not None:
                    try:
                        results = mp_face_detection.process(frame)
                        if results.detections:
                            for det in results.detections:
                                bbox = det.location_data.relative_bounding_box
                                x = int(bbox.xmin * width)
                                y = int(bbox.ymin * height)
                                w = int(bbox.width * width)
                                h = int(bbox.height * height)
                                if w > 30 and h > 30:
                                    faces_found.append((x, y, w, h, det.score[0]))
                    except Exception:
                        pass

                if not faces_found:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                        faces = haar_cascade.detectMultiScale(
                            gray, scaleFactor=1.05, minNeighbors=3,
                            minSize=(40, 40), maxSize=(int(width * 0.7), int(height * 0.7))
                        )
                        for x, y, w, h in faces:
                            area = w * h
                            conf = min(0.9, 0.3 + (area / (width * height)) * 2)
                            faces_found.append((x, y, w, h, conf))
                    except Exception:
                        pass

                if faces_found:
                    primary = max(faces_found, key=lambda f: f[2] * f[3] * f[4])
                    x, y, w, h, _ = primary
                    cx, cy = x + w // 2, y + h // 2
                    rel_t = abs_t - start_time
                    trajectory.append((rel_t, cx, cy))
                else:
                    if trajectory:
                        last_t, last_cx, last_cy = trajectory[-1]
                        rel_t = abs_t - start_time
                        trajectory.append((rel_t, last_cx, last_cy))

            except Exception as e:
                logger.debug(f"Trajectory sample failed at t={abs_t:.2f}: {e}")
                continue

        if mp_face_detection is not None:
            try:
                mp_face_detection.close()
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Face trajectory detection failed: {e}")

    logger.info(f"Face trajectory: {len(trajectory)} samples over {duration:.1f}s")
    return trajectory


def _mouth_openness(landmarks, img_w: int, img_h: int) -> float:
    """
    Estimate mouth openness from FaceMesh landmarks.
    Uses upper lip (13) and lower lip (14) vertical distance.
    """
    try:
        upper = landmarks[13]
        lower = landmarks[14]
        dy = abs((lower.y - upper.y) * img_h)
        return float(dy)
    except Exception:
        return 0.0


def detect_active_speaker_trajectory(
    video_clip: Any,
    start_time: float,
    end_time: float,
    sample_interval: float = 0.5,
) -> List[Tuple[float, int, int]]:
    """
    Multi-speaker aware face trajectory.
    Identifies active speaker using mouth openness detection.
    """
    cv2 = _import_cv2()
    trajectory: List[Tuple[float, int, int]] = []
    duration = end_time - start_time
    if duration <= 0:
        return trajectory

    try:
        mp = _import_mediapipe()
        mp_face_detection = None
        mp_face_mesh = None
        if mp is not None:
            try:
                mp_face_detection = mp.solutions.face_detection.FaceDetection(
                    model_selection=0, min_detection_confidence=0.5
                )
                mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=True,
                    max_num_faces=4,
                    refine_landmarks=True,
                    min_detection_confidence=0.5,
                )
            except Exception:
                pass

        haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        actual_interval = min(sample_interval, duration / max(4, int(duration)))
        sample_times = []
        t = start_time
        while t < end_time:
            sample_times.append(t)
            t += actual_interval

        for abs_t in sample_times:
            try:
                frame = video_clip.get_frame(abs_t)
                height, width = frame.shape[:2]
                rel_t = abs_t - start_time

                all_faces = []

                if mp_face_detection is not None:
                    try:
                        results = mp_face_detection.process(frame)
                        if results.detections:
                            for det in results.detections:
                                bbox = det.location_data.relative_bounding_box
                                x = int(bbox.xmin * width)
                                y = int(bbox.ymin * height)
                                w = int(bbox.width * width)
                                h = int(bbox.height * height)
                                if w > 30 and h > 30:
                                    all_faces.append((x, y, w, h, float(det.score[0])))
                    except Exception:
                        pass

                if not all_faces:
                    try:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                        faces = haar_cascade.detectMultiScale(
                            gray, scaleFactor=1.05, minNeighbors=3,
                            minSize=(40, 40), maxSize=(int(width * 0.7), int(height * 0.7))
                        )
                        for x, y, w, h in faces:
                            area = w * h
                            conf = min(0.9, 0.3 + (area / (width * height)) * 2)
                            all_faces.append((x, y, w, h, conf))
                    except Exception:
                        pass

                if not all_faces:
                    if trajectory:
                        _, last_cx, last_cy = trajectory[-1]
                        trajectory.append((rel_t, last_cx, last_cy))
                    continue

                if len(all_faces) == 1:
                    x, y, w, h, _ = all_faces[0]
                    trajectory.append((rel_t, x + w // 2, y + h // 2))
                    continue

                # Multi-face: identify active speaker by mouth openness
                active_face = None
                if mp_face_mesh is not None:
                    best_openness = -1.0
                    for x, y, w, h, _conf in all_faces:
                        pad = int(min(w, h) * 0.1)
                        x1, y1 = max(0, x - pad), max(0, y - pad)
                        x2, y2 = min(width, x + w + pad), min(height, y + h + pad)
                        roi = frame[y1:y2, x1:x2]
                        if roi.size == 0:
                            continue
                        try:
                            mesh_result = mp_face_mesh.process(roi)
                            if mesh_result.multi_face_landmarks:
                                for face_landmarks in mesh_result.multi_face_landmarks:
                                    openness = _mouth_openness(face_landmarks.landmark, w, h)
                                    if openness > best_openness:
                                        best_openness = openness
                                        active_face = (x, y, w, h)
                        except Exception:
                            continue

                if active_face:
                    x, y, w, h = active_face
                    trajectory.append((rel_t, x + w // 2, y + h // 2))
                else:
                    # Fallback: largest face
                    primary = max(all_faces, key=lambda f: f[2] * f[3])
                    x, y, w, h, _ = primary
                    trajectory.append((rel_t, x + w // 2, y + h // 2))

            except Exception as e:
                logger.debug(f"Active speaker detection failed at t={abs_t:.2f}: {e}")
                continue

    except Exception as e:
        logger.warning(f"Active speaker trajectory detection failed: {e}")

    return trajectory
