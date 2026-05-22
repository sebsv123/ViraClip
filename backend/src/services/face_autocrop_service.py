"""
Face Auto-Crop Service — stable face-tracking vertical crop for 9:16 output.

Replaces the shaky impact zoom with a smooth, face-tracking auto-crop that
follows the speaker's face/torso across the frame. Uses OpenCV Haar cascades
for lightweight face detection and a moving-average trajectory smoother to
eliminate jitter.

Strategy:
  1. Extract frames at low resolution (540×960) for fast detection.
  2. Detect face ROI (face + upper torso) frame by frame using OpenCV.
  3. Smooth the crop-box trajectory with a configurable moving-average window.
  4. Calculate a 9:16 rectangle (1080×1920 output) that keeps the ROI in frame.
  5. Generate an FFmpeg crop filter with time-varying x(t):y(t) expressions.
  6. Fallback: center crop on upper third when no face is detected.

Design constraints:
  - Output is always 1080×1920, setsar=1.
  - Never blocks the pipeline if OpenCV/MediaPipe fails — falls back to fixed crop.
  - Tracking must be fast enough for multi-minute clips (low-res extraction).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
TARGET_ASPECT = OUTPUT_WIDTH / OUTPUT_HEIGHT  # 9:16 → 0.5625

# Detection resolution (low-res for speed)
DETECT_WIDTH = 540
DETECT_HEIGHT = 960

# Trajectory smoothing window (frames). 8-12 recommended.
# Higher = smoother but more lag; lower = more responsive but jittery.
SMOOTHING_WINDOW = int(os.environ.get("FACE_AUTOCROP_SMOOTHING", "10"))

# Minimum face size as fraction of detection frame area
MIN_FACE_SIZE = float(os.environ.get("FACE_AUTOCROP_MIN_FACE", "0.02"))

# Optional light zoom when face is small (≤ 1.05x)
LIGHT_ZOOM_THRESHOLD = float(os.environ.get("FACE_AUTOCROP_ZOOM_THRESHOLD", "0.08"))
LIGHT_ZOOM_FACTOR = float(os.environ.get("FACE_AUTOCROP_ZOOM_FACTOR", "1.05"))

# Face margin expansion factor (like TwitchClip2Vertical's 30% margin)
# Expands the face bounding box by this fraction to avoid tight cropping
FACE_MARGIN = float(os.environ.get("FACE_AUTOCROP_MARGIN", "0.30"))

# Frame sampling rate: 1 = every frame, 2 = every 2nd frame, etc.
# Higher values = faster detection but less accurate tracking
SAMPLE_RATE = int(os.environ.get("FACE_AUTOCROP_SAMPLE_RATE", "1"))

# Face detector backend: "auto" (try retinaface first, fallback to haar),
# "haar" (OpenCV Haar cascades only), "retinaface" (RetinaFace only)
DETECTOR_BACKEND = os.environ.get("FACE_AUTOCROP_DETECTOR", "auto").strip().lower()

# Advanced tracking mode: "basic" (default) or "advanced"
# Advanced mode uses Kalman filter smoothing + upper-body-aware crop
FACE_AUTOCROP_MODE = os.environ.get("FACE_AUTOCROP_MODE", "basic").strip().lower()

# Kalman filter parameters (advanced mode)
KALMAN_PROCESS_NOISE = float(os.environ.get("FACE_AUTOCROP_KALMAN_PROCESS_NOISE", "1e-4"))
KALMAN_MEASUREMENT_NOISE = float(os.environ.get("FACE_AUTOCROP_KALMAN_MEASUREMENT_NOISE", "1e-2"))

# Upper-body-aware crop parameters (advanced mode)
UPPER_BODY_ENABLED = os.environ.get("FACE_AUTOCROP_UPPER_BODY", "true").strip().lower() == "true"
UPPER_THIRD_BIAS = float(os.environ.get("FACE_AUTOCROP_UPPER_THIRD_BIAS", "0.15"))
CHIN_PADDING = float(os.environ.get("FACE_AUTOCROP_CHIN_PADDING", "0.10"))
FOREHEAD_PADDING = float(os.environ.get("FACE_AUTOCROP_FOREHEAD_PADDING", "0.08"))

# Fallback: crop the upper third of the frame (typical talking-head position)
FALLBACK_CROP_Y_RATIO = 0.20  # Start crop at 20% from top


class FaceAutocropService:
    """Stable face-tracking auto-crop for 9:16 vertical output.

    Usage:
        svc = FaceAutocropService()
        result = await svc.process(clip_path, output_path)
        # result["path"] → Path to cropped video
    """

    def __init__(
        self,
        smoothing_window: int = SMOOTHING_WINDOW,
        min_face_size: float = MIN_FACE_SIZE,
        light_zoom_threshold: float = LIGHT_ZOOM_THRESHOLD,
        light_zoom_factor: float = LIGHT_ZOOM_FACTOR,
        face_margin: float = FACE_MARGIN,
        sample_rate: int = SAMPLE_RATE,
        detector_backend: str = DETECTOR_BACKEND,
        mode: str = FACE_AUTOCROP_MODE,
        kalman_process_noise: float = KALMAN_PROCESS_NOISE,
        kalman_measurement_noise: float = KALMAN_MEASUREMENT_NOISE,
        upper_body_enabled: bool = UPPER_BODY_ENABLED,
        upper_third_bias: float = UPPER_THIRD_BIAS,
        chin_padding: float = CHIN_PADDING,
        forehead_padding: float = FOREHEAD_PADDING,
    ):
        self.smoothing_window = smoothing_window
        self.min_face_size = min_face_size
        self.light_zoom_threshold = light_zoom_threshold
        self.light_zoom_factor = light_zoom_factor
        self.face_margin = face_margin
        self.sample_rate = sample_rate
        self.detector_backend = detector_backend
        self.mode = mode
        self.kalman_process_noise = kalman_process_noise
        self.kalman_measurement_noise = kalman_measurement_noise
        self.upper_body_enabled = upper_body_enabled
        self.upper_third_bias = upper_third_bias
        self.chin_padding = chin_padding
        self.forehead_padding = forehead_padding

        # MediaPipe availability flag (protobuf compatibility check)
        self._mediapipe_available: bool = True
        try:
            import mediapipe as mp  # noqa: F401
        except AttributeError as e:
            if "SymbolDatabase" in str(e):
                logger.warning(
                    "[FaceAutocrop] MediaPipe protobuf conflict: %s. "
                    "Falling back to OpenCV Haar cascades.", e
                )
                self._mediapipe_available = False
            else:
                raise

        # Lazy-loaded OpenCV cascade classifier
        self._face_cascade: Any = None
        self._profile_cascade: Any = None
        self._upper_body_cascade: Any = None

        # Lazy-loaded RetinaFace detector
        self._retinaface_detector: Any = None

        # Kalman filter state (advanced mode)
        self._kalman: Any = None
        self._kalman_initialized: bool = False

    # ── Public API ──────────────────────────────────────────────────────────

    async def autocrop_to_vertical(
        self,
        input_path: Path,
        output_path: Path,
    ) -> Path:
        """Primary public API: apply face-tracking auto-crop and return output path.

        This is the recommended entry point for the pipeline. It wraps process()
        and returns just the output Path for easy chaining.

        Args:
            input_path: Input video path (any aspect ratio).
            output_path: Output path for the cropped video.

        Returns:
            Path to the cropped output (or original input on failure).
        """
        result = await self.process(input_path, output_path)
        return result.get("path", input_path)

    async def process(
        self,
        clip_path: Path,
        output_path: Optional[Path] = None,
        fps: Optional[float] = None,
        crop_info: Optional["CropInfo"] = None,
    ) -> Dict[str, Any]:
        """Apply face-tracking auto-crop to a video clip.

        Args:
            clip_path: Input video path (any aspect ratio).
            output_path: Output path (default: clip_path.parent / autocrop_{name}).
            fps: Target fps. If None, detected from input.
            crop_info: Optional CropInfo from ShortsHighlightEngine.
                       When provided, the crop window is guided by these hints
                       instead of running full-frame face detection.

        Returns:
            Dict with:
                - "path": Path to the cropped output (or original on failure)
                - "success": bool
                - "method": "face_tracking" | "center_crop" | "skip_vertical" | "fallback" | "guided_crop"
                - "face_detection_rate": float (0-1, fraction of frames with face)
                - "error": Optional error message
        """
        out = output_path or clip_path.parent / f"autocrop_{clip_path.name}"

        # 1. Probe input video
        frames_dir = Path(tempfile.mkdtemp(prefix="viraclip_face_"))
        try:
            probe = await self._probe_video(clip_path)
            if not probe:
                logger.warning("[FaceAutocrop] Could not probe video, using fallback")
                return await self._fallback_center_crop(clip_path, out)

            input_width = probe["width"]
            input_height = probe["height"]
            detected_fps = fps or probe.get("fps", 30.0)
            duration = probe.get("duration", 60.0)
            total_frames = int(duration * detected_fps)

            # ── CropInfo shortcut: use provided crop hints directly ──
            if crop_info is not None:
                logger.info(
                    "[FaceAutocrop] Using CropInfo hint: (%d,%d) %dx%d "
                    "(confidence=%.2f)",
                    crop_info.x, crop_info.y,
                    crop_info.width, crop_info.height,
                    crop_info.confidence,
                )
                # Build a single crop box from the CropInfo
                crop_boxes = [(float(crop_info.x), float(crop_info.y),
                               float(crop_info.width), float(crop_info.height))]
                face_detection_rate = crop_info.confidence
                return await self._render_crop(
                    clip_path, out, crop_boxes, detected_fps,
                )

            logger.info(
                "[FaceAutocrop] Input: %dx%d, %.1ffps, %.1fs (%d frames)",
                input_width, input_height, detected_fps, duration, total_frames,
            )

            # ── Aspect ratio check: skip if already 9:16 (within tolerance) ──
            input_aspect = input_width / input_height
            if abs(input_aspect - TARGET_ASPECT) < 0.02:
                logger.info(
                    "[FaceAutocrop] Input already 9:16 (%.4f), skipping autocrop",
                    input_aspect,
                )
                # Copy original to output path if different
                if out != clip_path:
                    import shutil
                    shutil.copy2(str(clip_path), str(out))
                return {
                    "path": out,
                    "success": True,
                    "method": "skip_vertical",
                    "face_detection_rate": 0.0,
                    "error": None,
                }

            # 2. Extract frames at low resolution for face detection
            frame_count = await self._extract_frames(
                clip_path, frames_dir, detected_fps, duration,
            )
            if frame_count == 0:
                logger.warning("[FaceAutocrop] No frames extracted, using fallback")
                return await self._fallback_center_crop(clip_path, out)

            # 3. Detect faces in each frame (CPU-bound, run in executor)
            loop = asyncio.get_event_loop()
            if self.mode == "advanced":
                face_centroids = await loop.run_in_executor(
                    None,
                    self._detect_faces_batch_sync_advanced,
                    frames_dir, frame_count,
                )
            else:
                face_centroids = await loop.run_in_executor(
                    None,
                    self._detect_faces_batch_sync,
                    frames_dir, frame_count,
                )

            # 4. Smooth trajectory
            if self.mode == "advanced":
                smoothed = self._smooth_trajectory_kalman(face_centroids)
            else:
                smoothed = self._smooth_trajectory(face_centroids)

            # 5. Calculate 9:16 crop boxes
            if self.mode == "advanced":
                crop_boxes = self._calculate_crop_boxes_advanced(
                    smoothed, input_width, input_height, detected_fps,
                )
            else:
                crop_boxes = self._calculate_crop_boxes(
                    smoothed, input_width, input_height, detected_fps,
                )


            # 6. First-frame safe zone validation: ensure the first crop box
            # keeps the face vertically centred (no ceiling / background-only).
            # If the first frame's crop is too high (face in upper 25% of output)
            # we shift it down so the face sits in the middle third.
            if crop_boxes and face_centroids and face_centroids[0] is not None:
                _first_cx, _first_cy = crop_boxes[0][0], crop_boxes[0][1]
                _first_cw, _first_ch = crop_boxes[0][2], crop_boxes[0][3]
                # Normalised vertical centre of the crop window (0=top, 1=bottom)
                _crop_centre_y = (_first_cy + _first_ch / 2) / OUTPUT_HEIGHT
                # If the crop centre is in the upper 30% of the frame → too high
                if _crop_centre_y < 0.30:
                    # Shift crop down so centre sits at ~40% (upper-middle third)
                    _shift_y = int((0.40 * OUTPUT_HEIGHT) - (_first_cy + _first_ch / 2))
                    # Clamp so we don't go out of bounds
                    _max_y = input_height - OUTPUT_HEIGHT
                    _new_cy = max(0, min(_max_y, _first_cy + _shift_y))
                    logger.info(
                        "[FaceAutocrop] First-frame safe zone: crop centre was at "
                        "%.0f%% height → shifting down by %d px (new y=%d)",
                        _crop_centre_y * 100, _shift_y, _new_cy,
                    )
                    # Apply the same vertical shift to ALL crop boxes (smooth transition)
                    # so the first second stays well-framed.
                    _shift_per_frame = _shift_y / max(len(crop_boxes), 1)
                    for _i in range(len(crop_boxes)):
                        _bx, _by, _bw, _bh = crop_boxes[_i]
                        _new_by = max(0, min(_max_y, int(_by + _shift_per_frame * (_i + 1))))
                        crop_boxes[_i] = (_bx, _new_by, _bw, _bh)

            # 7. Build FFmpeg crop expression
            face_detection_rate = (
                sum(1 for c in face_centroids if c is not None) / len(face_centroids)
                if face_centroids else 0.0
            )

            if face_detection_rate < 0.1:
                logger.info(
                    "[FaceAutocrop] Face detection rate too low (%.0f%%), "
                    "using center crop fallback",
                    face_detection_rate * 100,
                )
                return await self._fallback_center_crop(clip_path, out)

            # 7. Render with FFmpeg crop filter
            success = await self._render_crop(
                clip_path, out, crop_boxes, detected_fps,
            )

            if success and out.exists():
                method = "face_tracking" if face_detection_rate > 0.3 else "center_crop"
                logger.info(
                    "[FaceAutocrop] ✓ %s: %s (%d frames, %.0f%% face detection)",
                    method, out.name, frame_count, face_detection_rate * 100,
                )
                return {
                    "path": out,
                    "success": True,
                    "method": method,
                    "face_detection_rate": round(face_detection_rate, 3),
                    "error": None,
                }
            else:
                logger.warning("[FaceAutocrop] FFmpeg render failed, using fallback")
                return await self._fallback_center_crop(clip_path, out)

        except Exception as e:
            logger.warning("[FaceAutocrop] Error: %s, using fallback", e)
            return await self._fallback_center_crop(clip_path, out)
        finally:
            # Cleanup temp frames
            import shutil
            shutil.rmtree(frames_dir, ignore_errors=True)

    # ── Frame extraction ────────────────────────────────────────────────────

    async def _extract_frames(
        self, clip_path: Path, out_dir: Path, fps: float, duration: float,
    ) -> int:
        """Extract frames at detection resolution.

        Samples at the video's native fps but at DETECT_WIDTH×DETECT_HEIGHT
        resolution for fast processing. Caps at ~3000 frames to avoid OOM.

        When sample_rate > 1, only every Nth frame is extracted (e.g. sample_rate=2
        means every 2nd frame). This is inspired by TwitchClip2Vertical which
        samples 10 random frames from 199 for fast face detection.
        """
        max_frames = min(int(duration * fps), 3000)
        sample_fps = max(1.0, max_frames / duration) if duration > 0 else fps

        # Apply sample rate: if sample_rate > 1, reduce the effective fps
        effective_fps = sample_fps / self.sample_rate if self.sample_rate > 1 else sample_fps
        effective_max = max(1, int(max_frames / self.sample_rate)) if self.sample_rate > 1 else max_frames

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vf", f"fps={effective_fps:.4f},scale={DETECT_WIDTH}:{DETECT_HEIGHT}",
            "-frames:v", str(effective_max),
            "-qscale:v", "5",  # reasonable quality, fast encode
            str(out_dir / "frame_%06d.jpg"),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=300,
            )
            if result.returncode != 0:
                logger.warning(
                    "[FaceAutocrop] Frame extraction failed: %s",
                    result.stderr.decode()[:200],
                )
                return 0

            frames = sorted(out_dir.glob("frame_*.jpg"))
            return len(frames)
        except Exception as e:
            logger.warning("[FaceAutocrop] Frame extraction error: %s", e)
            return 0

    # ── Face detection ──────────────────────────────────────────────────────

    def _load_cascades(self) -> bool:
        """Load OpenCV Haar cascades. Returns True if loaded."""
        if self._face_cascade is not None:
            return True
        try:
            import cv2
            # Try multiple possible cascade paths
            cascade_paths = [
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
                os.path.join(cv2.__path__[0] if hasattr(cv2, "__path__") else "", "data",
                             "haarcascade_frontalface_default.xml"),
                "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
                "/usr/local/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
            ]
            profile_paths = [
                cv2.data.haarcascades + "haarcascade_profileface.xml",
                "/usr/share/opencv4/haarcascades/haarcascade_profileface.xml",
                "/usr/local/share/opencv4/haarcascades/haarcascade_profileface.xml",
            ]

            face_xml = None
            for p in cascade_paths:
                if os.path.exists(p):
                    face_xml = p
                    break

            profile_xml = None
            for p in profile_paths:
                if os.path.exists(p):
                    profile_xml = p
                    break

            if face_xml is None:
                logger.warning("[FaceAutocrop] Haar cascade XML not found")
                return False

            self._face_cascade = cv2.CascadeClassifier(face_xml)
            if self._face_cascade.empty():
                logger.warning("[FaceAutocrop] Failed to load face cascade")
                self._face_cascade = None
                return False

            if profile_xml:
                self._profile_cascade = cv2.CascadeClassifier(profile_xml)

            logger.debug(
                "[FaceAutocrop] Cascades loaded: face=%s profile=%s",
                face_xml, profile_xml or "N/A",
            )
            return True

        except ImportError:
            logger.warning("[FaceAutocrop] OpenCV (cv2) not installed")
            return False
        except Exception as e:
            logger.warning("[FaceAutocrop] Cascade load error: %s", e)
            return False

    def _load_retinaface(self) -> bool:
        """Lazy-load RetinaFace detector. Returns True if loaded.

        RetinaFace (from batch_face) is a deep-learning face detector that is
        more accurate than Haar cascades, especially for profile/side faces.
        Falls back gracefully if batch_face is not installed.
        """
        if self._retinaface_detector is not None:
            return True
        try:
            from batch_face import RetinaFace  # type: ignore[import-untyped]
            self._retinaface_detector = RetinaFace()
            logger.debug("[FaceAutocrop] RetinaFace detector loaded")
            return True
        except ImportError:
            logger.debug("[FaceAutocrop] batch_face not installed, RetinaFace unavailable")
            return False
        except Exception as e:
            logger.warning("[FaceAutocrop] RetinaFace load error: %s", e)
            return False

    def _detect_faces_haar(
        self, frame_path: Path,
    ) -> Optional[Tuple[float, float, float, float]]:
        """Detect faces in a single frame using OpenCV Haar cascades.

        Returns (x, y, w, h) bounding box in DETECT coords, or None.
        Tries frontal face first, then profile face as fallback.
        """
        import cv2
        gray = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None

        # Detect frontal faces
        faces = self._face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(int(DETECT_WIDTH * 0.05), int(DETECT_HEIGHT * 0.05)),
        )

        if len(faces) > 0:
            largest = max(faces, key=lambda r: r[2] * r[3])
            return tuple(largest)  # (x, y, w, h)

        # Try profile face detection
        if self._profile_cascade is not None:
            profiles = self._profile_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=3,
                minSize=(int(DETECT_WIDTH * 0.04), int(DETECT_HEIGHT * 0.04)),
            )
            if len(profiles) > 0:
                largest = max(profiles, key=lambda r: r[2] * r[3])
                return tuple(largest)

        return None

    def _detect_faces_retinaface(
        self, frame_path: Path,
    ) -> Optional[Tuple[float, float, float, float]]:
        """Detect faces in a single frame using RetinaFace (batch_face).

        Returns (x, y, w, h) bounding box in DETECT coords, or None.
        RetinaFace returns boxes in (x1, y1, x2, y2) format which we convert
        to (x, y, w, h) for consistency with the Haar cascade interface.

        Only returns detections with a single face (like TwitchClip2Vertical
        which skips frames with 0 or 2+ faces).
        """
        import cv2
        img = cv2.imread(str(frame_path))
        if img is None:
            return None

        try:
            faces = self._retinaface_detector(img, cv=True)
        except Exception as e:
            logger.debug("[FaceAutocrop] RetinaFace detection error: %s", e)
            return None

        if len(faces) == 0:
            return None

        # TwitchClip2Vertical skips frames with 2+ faces
        if len(faces) > 1:
            return None

        box, landmarks, confidence = faces[0]
        x1, y1, x2, y2 = box

        # Convert to (x, y, w, h) format
        w = x2 - x1
        h = y2 - y1
        return (x1, y1, w, h)

    def _expand_face_box(
        self, box: Tuple[float, float, float, float],
        img_width: int, img_height: int,
    ) -> Tuple[float, float, float, float]:
        """Expand face bounding box by face_margin fraction.

        Like TwitchClip2Vertical's 30% margin: expands the box by
        margin * width on all sides, clamped to image bounds.

        Args:
            box: (x, y, w, h) in image coordinates.
            img_width: Image width for clamping.
            img_height: Image height for clamping.

        Returns:
            Expanded (x, y, w, h) clamped to image bounds.
        """
        x, y, w, h = box
        margin = int(self.face_margin * w)
        x_new = max(x - margin, 0)
        y_new = max(y - margin, 0)
        x2_new = min(x + w + margin, img_width)
        y2_new = min(y + h + margin, img_height)
        return (x_new, y_new, x2_new - x_new, y2_new - y_new)

    def _detect_faces_batch_sync(
        self, frames_dir: Path, frame_count: int,
    ) -> List[Optional[Tuple[float, float]]]:
        """Synchronous version of face detection for run_in_executor.

        Detects face centroids in extracted frames using the configured
        detector backend. This is the CPU-bound work that gets offloaded
        to a thread pool executor.

        Returns list of (cx, cy) tuples in DETECT_WIDTH×DETECT_HEIGHT coords,
        or None for frames where no face was detected.
        """
        # Determine which detector to use
        use_retinaface = self.detector_backend in ("auto", "retinaface")
        use_haar = self.detector_backend in ("auto", "haar")

        retinaface_loaded = False
        haar_loaded = False

        if use_retinaface:
            retinaface_loaded = self._load_retinaface()

        if use_haar or (use_retinaface and not retinaface_loaded):
            haar_loaded = self._load_cascades()

        if not retinaface_loaded and not haar_loaded:
            logger.warning(
                "[FaceAutocrop] No face detector available (backend=%s)",
                self.detector_backend,
            )
            return [None] * frame_count

        import cv2

        results: List[Optional[Tuple[float, float]]] = []
        frame_files = sorted(frames_dir.glob("frame_*.jpg"))

        for frame_path in frame_files:
            try:
                box: Optional[Tuple[float, float, float, float]] = None

                # Try RetinaFace first (if available and configured)
                if retinaface_loaded:
                    box = self._detect_faces_retinaface(frame_path)

                # Fall back to Haar if RetinaFace didn't find anything
                if box is None and haar_loaded:
                    box = self._detect_faces_haar(frame_path)

                if box is not None:
                    # Apply margin expansion (like TwitchClip2Vertical's 30%)
                    expanded = self._expand_face_box(
                        box, DETECT_WIDTH, DETECT_HEIGHT,
                    )
                    x, y, w, h = expanded
                    cx = x + w / 2
                    cy = y + h / 2
                    results.append((cx, cy))
                else:
                    results.append(None)

            except Exception as e:
                logger.debug("[FaceAutocrop] Frame detection error: %s", e)
                results.append(None)

        # Pad if fewer frames than expected
        while len(results) < frame_count:
            results.append(None)

        detected = sum(1 for r in results if r is not None)
        logger.debug(
            "[FaceAutocrop] Detected faces in %d/%d frames (backend=%s)",
            detected, len(results), self.detector_backend,
        )
        return results

    async def _detect_faces_batch(
        self, frames_dir: Path, frame_count: int,
    ) -> List[Optional[Tuple[float, float]]]:
        """Detect face centroids in extracted frames (async wrapper).

        Delegates to the synchronous _detect_faces_batch_sync via
        run_in_executor for CPU-bound OpenCV work.

        Returns list of (cx, cy) tuples in DETECT_WIDTH×DETECT_HEIGHT coords,
        or None for frames where no face was detected.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._detect_faces_batch_sync,
            frames_dir, frame_count,
        )

    # ── Trajectory smoothing ────────────────────────────────────────────────

    def _smooth_trajectory(
        self, centroids: List[Optional[Tuple[float, float]]],
    ) -> List[Optional[Tuple[float, float]]]:
        """Apply moving-average smoothing to face trajectory.

        Interpolates missing frames (no detection) and then applies a
        centred moving-average window to eliminate jitter.

        Args:
            centroids: List of (cx, cy) or None per frame.

        Returns:
            Smoothed centroids (same length). Missing frames at start/end
            are filled with nearest neighbour; internal gaps are linearly
            interpolated.
        """
        n = len(centroids)
        if n == 0:
            return []

        # Step 1: Linear interpolation for internal gaps
        filled: List[Optional[Tuple[float, float]]] = list(centroids)

        # Find runs of None and interpolate
        i = 0
        while i < n:
            if filled[i] is None:
                # Find the start and end of this None run
                j = i
                while j < n and filled[j] is None:
                    j += 1
                # Find previous known centroid
                prev = None
                for k in range(i - 1, -1, -1):
                    if filled[k] is not None:
                        prev = filled[k]
                        break
                # Find next known centroid
                nxt = None
                for k in range(j, n):
                    if filled[k] is not None:
                        nxt = filled[k]
                        break

                if prev is not None and nxt is not None:
                    # Linear interpolation
                    gap_len = j - i
                    for k in range(i, j):
                        t = (k - i + 1) / (gap_len + 1)
                        cx = prev[0] + (nxt[0] - prev[0]) * t
                        cy = prev[1] + (nxt[1] - prev[1]) * t
                        filled[k] = (cx, cy)
                elif prev is not None:
                    # Fill with previous
                    for k in range(i, j):
                        filled[k] = prev
                elif nxt is not None:
                    # Fill with next
                    for k in range(i, j):
                        filled[k] = nxt
                i = j
            else:
                i += 1

        # Step 2: Moving-average smoothing
        half_window = self.smoothing_window // 2
        smoothed: List[Optional[Tuple[float, float]]] = []

        for i in range(n):
            if filled[i] is None:
                smoothed.append(None)
                continue

            # Collect valid centroids in window
            cx_sum = 0.0
            cy_sum = 0.0
            count = 0
            for k in range(
                max(0, i - half_window),
                min(n, i + half_window + 1),
            ):
                if filled[k] is not None:
                    cx_sum += filled[k][0]
                    cy_sum += filled[k][1]
                    count += 1

            if count > 0:
                smoothed.append((cx_sum / count, cy_sum / count))
            else:
                smoothed.append(filled[i])

        return smoothed

    # ── Advanced mode: Kalman filter smoothing ─────────────────────────────

    def _init_kalman_filter(self) -> bool:
        """Initialize a 4-state OpenCV Kalman filter for trajectory smoothing.

        State vector: [x, y, dx, dy] where (x, y) is position and (dx, dy)
        is velocity. Uses configurable process and measurement noise.

        Returns:
            True if Kalman filter was initialized successfully.
        """
        try:
            import cv2
            # 4-state: x, y, dx, dy
            # 2-measurement: x, y
            kalman = cv2.KalmanFilter(4, 2)

            # State transition matrix (constant velocity model)
            # x_k = x_{k-1} + dx_{k-1}
            # y_k = y_{k-1} + dy_{k-1}
            # dx_k = dx_{k-1}
            # dy_k = dy_{k-1}
            kalman.transitionMatrix = np.array([
                [1, 0, 1, 0],
                [0, 1, 0, 1],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ], dtype=np.float32)

            # Measurement matrix: we observe x, y
            kalman.measurementMatrix = np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ], dtype=np.float32)

            # Process noise covariance (how much we trust the model)
            # Lower = smoother but more lag; higher = more responsive but jittery
            kalman.processNoiseCov = np.eye(4, dtype=np.float32) * self.kalman_process_noise

            # Measurement noise covariance (how much we trust the detection)
            # Lower = trust detections more; higher = trust model more
            kalman.measurementNoiseCov = np.eye(2, dtype=np.float32) * self.kalman_measurement_noise

            # Initial error covariance
            kalman.errorCovPost = np.eye(4, dtype=np.float32) * 100.0

            self._kalman = kalman
            self._kalman_initialized = False
            logger.debug("[FaceAutocrop] Kalman filter initialized (proc_noise=%s, meas_noise=%s)",
                         self.kalman_process_noise, self.kalman_measurement_noise)
            return True
        except ImportError:
            logger.warning("[FaceAutocrop] OpenCV not available for Kalman filter")
            return False
        except Exception as e:
            logger.warning("[FaceAutocrop] Kalman filter init error: %s", e)
            return False

    def _smooth_trajectory_kalman(
        self, centroids: List[Optional[Tuple[float, float]]],
    ) -> List[Optional[Tuple[float, float]]]:
        """Apply Kalman filter smoothing to face trajectory (advanced mode).

        Uses a 4-state Kalman filter (x, y, dx, dy) with constant velocity
        model. For each frame:
          - Predict: advance state using transition matrix
          - Correct: if detection available, update with measurement
          - If no detection: use prediction only (coasts on velocity)

        Falls back to moving-average smoothing if Kalman filter is not
        available or initialization fails.

        Args:
            centroids: List of (cx, cy) or None per frame.

        Returns:
            Smoothed centroids (same length).
        """
        n = len(centroids)
        if n == 0:
            return []

        # Try to initialize Kalman filter
        if self._kalman is None:
            if not self._init_kalman_filter():
                # Fallback to moving-average smoothing
                logger.debug("[FaceAutocrop] Kalman unavailable, falling back to moving average")
                return self._smooth_trajectory(centroids)

        import numpy as np

        smoothed: List[Optional[Tuple[float, float]]] = []
        kalman = self._kalman

        for i, centroid in enumerate(centroids):
            if centroid is not None:
                cx, cy = centroid
                measurement = np.array([[cx], [cy]], dtype=np.float32)

                if not self._kalman_initialized:
                    # First detection: initialize state
                    kalman.statePost = np.array([[cx], [cy], [0], [0]], dtype=np.float32)
                    self._kalman_initialized = True
                    smoothed.append((cx, cy))
                    continue

                # Predict + correct
                kalman.predict()
                kalman.correct(measurement)
            else:
                # No detection: predict only (coast on velocity)
                if not self._kalman_initialized:
                    smoothed.append(None)
                    continue
                kalman.predict()

            # Extract smoothed position from state
            state = kalman.statePost
            sx = float(state[0, 0])
            sy = float(state[1, 0])
            smoothed.append((sx, sy))

        # Fill any remaining None at start with nearest neighbour
        for i in range(n):
            if smoothed[i] is None:
                for j in range(i + 1, n):
                    if smoothed[j] is not None:
                        smoothed[i] = smoothed[j]
                        break
                if smoothed[i] is None:
                    # All remaining are None, fill with center
                    smoothed[i] = (DETECT_WIDTH / 2, DETECT_HEIGHT * FALLBACK_CROP_Y_RATIO)

        return smoothed

    # ── Advanced mode: upper body detection ─────────────────────────────────

    def _load_upper_body_cascade(self) -> bool:
        """Load OpenCV upper body Haar cascade.

        Uses haarcascade_upperbody.xml from OpenCV data paths.

        Returns:
            True if cascade was loaded successfully.
        """
        if self._upper_body_cascade is not None:
            return True
        try:
            import cv2
            # Try multiple possible cascade paths
            cascade_paths = [
                cv2.data.haarcascades + "haarcascade_upperbody.xml",
                os.path.join(cv2.__path__[0] if hasattr(cv2, "__path__") else "", "data",
                             "haarcascade_upperbody.xml"),
                "/usr/share/opencv4/haarcascades/haarcascade_upperbody.xml",
                "/usr/local/share/opencv4/haarcascades/haarcascade_upperbody.xml",
            ]

            upper_xml = None
            for p in cascade_paths:
                if os.path.exists(p):
                    upper_xml = p
                    break

            if upper_xml is None:
                logger.warning("[FaceAutocrop] Upper body cascade XML not found")
                return False

            self._upper_body_cascade = cv2.CascadeClassifier(upper_xml)
            if self._upper_body_cascade.empty():
                logger.warning("[FaceAutocrop] Failed to load upper body cascade")
                self._upper_body_cascade = None
                return False

            logger.debug("[FaceAutocrop] Upper body cascade loaded: %s", upper_xml)
            return True

        except ImportError:
            logger.warning("[FaceAutocrop] OpenCV (cv2) not installed for upper body")
            return False
        except Exception as e:
            logger.warning("[FaceAutocrop] Upper body cascade load error: %s", e)
            return False

    def _detect_upper_body(
        self, frame_path: Path,
    ) -> Optional[Tuple[float, float, float, float]]:
        """Detect upper body in a single frame using OpenCV Haar cascade.

        Returns (x, y, w, h) bounding box in DETECT coords, or None.
        Used in advanced mode to improve tracking when face is not visible
        (e.g. speaker turns away from camera).

        The upper body cascade detects head + shoulders region, which is
        larger and more stable than face detection alone.
        """
        if self._upper_body_cascade is None:
            if not self._load_upper_body_cascade():
                return None

        import cv2
        gray = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None

        bodies = self._upper_body_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=3,
            minSize=(int(DETECT_WIDTH * 0.10), int(DETECT_HEIGHT * 0.15)),
        )

        if len(bodies) > 0:
            largest = max(bodies, key=lambda r: r[2] * r[3])
            return tuple(largest)

        return None

    def _detect_faces_batch_sync_advanced(
        self, frames_dir: Path, frame_count: int,
    ) -> List[Optional[Tuple[float, float]]]:
        """Synchronous advanced face+body detection for run_in_executor.

        In advanced mode, this method:
          1. Detects face using the configured backend (RetinaFace or Haar)
          2. If face not found, tries upper body detection
          3. If upper body found, uses its centroid (adjusted to approximate
             face position: upper body center shifted up by ~25% of height)
          4. If neither found, returns None (will be interpolated later)

        Returns list of (cx, cy) tuples in DETECT_WIDTH×DETECT_HEIGHT coords,
        or None for frames where no detection was possible.
        """
        # Determine which face detector to use
        use_retinaface = self.detector_backend in ("auto", "retinaface")
        use_haar = self.detector_backend in ("auto", "haar")

        retinaface_loaded = False
        haar_loaded = False

        if use_retinaface:
            retinaface_loaded = self._load_retinaface()

        if use_haar or (use_retinaface and not retinaface_loaded):
            haar_loaded = self._load_cascades()

        # Load upper body cascade if enabled
        upper_body_loaded = False
        if self.upper_body_enabled:
            upper_body_loaded = self._load_upper_body_cascade()

        if not retinaface_loaded and not haar_loaded and not upper_body_loaded:
            logger.warning(
                "[FaceAutocrop] No detector available for advanced mode (backend=%s)",
                self.detector_backend,
            )
            return [None] * frame_count

        import cv2

        results: List[Optional[Tuple[float, float]]] = []
        frame_files = sorted(frames_dir.glob("frame_*.jpg"))

        for frame_path in frame_files:
            try:
                box: Optional[Tuple[float, float, float, float]] = None
                detection_source = "none"

                # 1. Try face detection first
                if retinaface_loaded:
                    box = self._detect_faces_retinaface(frame_path)
                    if box is not None:
                        detection_source = "retinaface"

                if box is None and haar_loaded:
                    box = self._detect_faces_haar(frame_path)
                    if box is not None:
                        detection_source = "haar"

                # 2. If face not found, try upper body
                if box is None and upper_body_loaded:
                    body_box = self._detect_upper_body(frame_path)
                    if body_box is not None:
                        # Upper body box is larger; approximate face position
                        # by shifting centroid up by ~25% of body height
                        bx, by, bw, bh = body_box
                        face_approx_y = by + bh * 0.25  # face is in upper portion
                        box = (bx, face_approx_y, bw, bh * 0.5)
                        detection_source = "upper_body"

                if box is not None:
                    # Apply margin expansion
                    expanded = self._expand_face_box(
                        box, DETECT_WIDTH, DETECT_HEIGHT,
                    )
                    x, y, w, h = expanded
                    cx = x + w / 2
                    cy = y + h / 2
                    results.append((cx, cy))
                else:
                    results.append(None)

            except Exception as e:
                logger.debug("[FaceAutocrop] Advanced frame detection error: %s", e)
                results.append(None)

        # Pad if fewer frames than expected
        while len(results) < frame_count:
            results.append(None)

        detected = sum(1 for r in results if r is not None)
        logger.debug(
            "[FaceAutocrop] Advanced detection: %d/%d frames (face=%s, upper_body=%s)",
            detected, len(results), retinaface_loaded or haar_loaded, upper_body_loaded,
        )
        return results

    # ── Advanced mode: upper-body-aware crop boxes ──────────────────────────

    def _calculate_crop_boxes_advanced(
        self,
        centroids: List[Optional[Tuple[float, float]]],
        input_width: int,
        input_height: int,
        fps: float,
    ) -> List[Tuple[float, float, float, float]]:
        """Calculate 9:16 crop boxes with upper-body awareness (advanced mode).

        Extends _calculate_crop_boxes with:
          - Upper-third bias: shifts crop box up so the face appears in the
            upper third of the frame (more natural composition)
          - Forehead padding: adds space above the face centroid to avoid
            cropping the top of the head
          - Chin padding: adds space below the face centroid to avoid
            cropping the chin

        The crop box is calculated as follows:
          1. Start with the face centroid (or upper body centroid)
          2. Apply forehead_padding: shift centroid up by forehead_padding * crop_h
          3. Apply upper_third_bias: shift centroid up by upper_third_bias * crop_h
          4. Apply chin_padding: ensure at least chin_padding * crop_h below centroid
          5. Clamp to frame bounds

        Args:
            centroids: Smoothed face centroids in DETECT coords.
            input_width: Original video width.
            input_height: Original video height.
            fps: Frame rate (unused, kept for API consistency).

        Returns:
            List of (x, y, w, h) crop boxes in input coordinates.
        """
        # Scale factor from detection resolution to input resolution
        scale_x = input_width / DETECT_WIDTH
        scale_y = input_height / DETECT_HEIGHT

        # Target crop dimensions in input coordinates
        crop_h = float(input_height)
        crop_w = crop_h * TARGET_ASPECT

        # If input is narrower than 9:16, crop vertically instead
        if crop_w > input_width:
            crop_w = float(input_width)
            crop_h = crop_w / TARGET_ASPECT

        boxes: List[Tuple[float, float, float, float]] = []
        for centroid in centroids:
            if centroid is None:
                # Fallback: centre of upper third
                cx = input_width / 2
                cy = input_height * FALLBACK_CROP_Y_RATIO + crop_h / 2
            else:
                cx_detect, cy_detect = centroid
                cx = cx_detect * scale_x
                cy = cy_detect * scale_y

                # Apply forehead padding: shift centroid up to avoid
                # cropping the top of the head
                cy = cy - self.forehead_padding * crop_h

                # Apply upper-third bias: shift centroid up so face
                # appears in the upper third of the frame
                cy = cy - self.upper_third_bias * crop_h

            # Calculate crop box centered on (cx, cy)
            x = cx - crop_w / 2
            y = cy - crop_h / 2

            # Apply chin padding: ensure at least chin_padding * crop_h
            # below the centroid (to avoid cropping the chin)
            # The centroid should be at least chin_padding from bottom
            min_y_from_centroid = cy - crop_h * (1.0 - self.chin_padding)
            if y > min_y_from_centroid:
                y = min_y_from_centroid

            # Clamp x
            if x < 0:
                x = 0.0
            elif x + crop_w > input_width:
                x = float(input_width - crop_w)

            # Clamp y
            if y < 0:
                y = 0.0
            elif y + crop_h > input_height:
                y = float(input_height - crop_h)

            boxes.append((x, y, crop_w, crop_h))

        return boxes

    # ── Crop box calculation ────────────────────────────────────────────────

    def _calculate_crop_boxes(
        self,
        centroids: List[Optional[Tuple[float, float]]],
        input_width: int,
        input_height: int,
        fps: float,
    ) -> List[Tuple[float, float, float, float]]:
        """Calculate 9:16 crop boxes from smoothed face centroids.

        Each crop box is (x, y, w, h) in INPUT frame coordinates.
        The box is always 9:16 aspect ratio, centred on the face centroid
        as much as possible while staying within frame bounds.

        Args:
            centroids: Smoothed face centroids in DETECT coords.
            input_width: Original video width.
            input_height: Original video height.
            fps: Frame rate (unused, kept for API consistency).

        Returns:
            List of (x, y, w, h) crop boxes in input coordinates.
        """
        # Scale factor from detection resolution to input resolution
        scale_x = input_width / DETECT_WIDTH
        scale_y = input_height / DETECT_HEIGHT

        # Target crop dimensions in input coordinates
        # For 9:16, crop width = height * 9/16
        crop_h = float(input_height)
        crop_w = crop_h * TARGET_ASPECT

        # If input is wider than 9:16, we crop horizontally
        # If input is narrower (e.g. 4:3), we need to crop vertically too
        if crop_w > input_width:
            # Input is narrower than 9:16 — crop vertically instead
            crop_w = float(input_width)
            crop_h = crop_w / TARGET_ASPECT

        boxes: List[Tuple[float, float, float, float]] = []
        for centroid in centroids:
            if centroid is None:
                # Fallback: centre of upper third
                cx = input_width / 2
                cy = input_height * FALLBACK_CROP_Y_RATIO + crop_h / 2
            else:
                cx_detect, cy_detect = centroid
                cx = cx_detect * scale_x
                cy = cy_detect * scale_y

            # Clamp crop box to frame bounds
            x = cx - crop_w / 2
            y = cy - crop_h / 2

            # Clamp x
            if x < 0:
                x = 0.0
            elif x + crop_w > input_width:
                x = float(input_width - crop_w)

            # Clamp y
            if y < 0:
                y = 0.0
            elif y + crop_h > input_height:
                y = float(input_height - crop_h)

            boxes.append((x, y, crop_w, crop_h))

        return boxes

    # ── FFmpeg render ───────────────────────────────────────────────────────

    async def _render_crop(
        self,
        clip_path: Path,
        output_path: Path,
        crop_boxes: List[Tuple[float, float, float, float]],
        fps: float,
    ) -> bool:
        """Render the cropped video using FFmpeg crop filter with time-varying
        expressions.

        Uses the `n` (frame number) variable in FFmpeg to index into the
        pre-computed crop trajectory. Since FFmpeg's crop filter doesn't
        support lookup tables natively, we generate a series of
        if( eq(n,FRAME), x, ... ) expressions for the first ~100 frames
        where movement is most noticeable, then use the last known position
        for the remainder.

        For longer clips with significant movement, we split into segments
        and concatenate.
        """
        if not crop_boxes:
            return False

        n_frames = len(crop_boxes)

        # Strategy: For clips with ≤ 200 frames, use a single if-else chain.
        # For longer clips, use keyframe-based approach: sample every K frames
        # and interpolate between them using between(n, start, end) expressions.
        if n_frames <= 200:
            return await self._render_single_pass(
                clip_path, output_path, crop_boxes, fps,
            )
        else:
            return await self._render_segmented(
                clip_path, output_path, crop_boxes, fps,
            )

    async def _render_single_pass(
        self,
        clip_path: Path,
        output_path: Path,
        crop_boxes: List[Tuple[float, float, float, float]],
        fps: float,
    ) -> bool:
        """Render with a single FFmpeg pass using if-else chain for crop x,y.

        For efficiency, we only emit explicit expressions for frames where
        the crop position changes significantly (> 2px), and use the last
        known position for static runs.
        """
        # Simplify: sample keyframes where position changes significantly
        keyframes: List[Tuple[int, float, float]] = []  # (frame_idx, x, y)
        last_x, last_y = crop_boxes[0][0], crop_boxes[0][1]
        keyframes.append((0, last_x, last_y))

        for i in range(1, len(crop_boxes)):
            x, y, w, h = crop_boxes[i]
            dx = abs(x - last_x)
            dy = abs(y - last_y)
            if dx > 2.0 or dy > 2.0:
                keyframes.append((i, x, y))
                last_x, last_y = x, y

        # Ensure last frame is included
        if keyframes[-1][0] != len(crop_boxes) - 1:
            x, y = crop_boxes[-1][0], crop_boxes[-1][1]
            keyframes.append((len(crop_boxes) - 1, x, y))

        w, h = crop_boxes[0][2], crop_boxes[0][3]

        # Build the crop expression using between(n, start, end)
        # For each keyframe interval, use linear interpolation:
        # x = x_start + (x_end - x_start) * (n - n_start) / (n_end - n_start)
        expr_parts = []
        for k in range(len(keyframes) - 1):
            n0, x0, y0 = keyframes[k]
            n1, x1, y1 = keyframes[k + 1]
            if n1 == n0:
                continue

            dx = x1 - x0
            dy = y1 - y0
            dur = n1 - n0

            # x expression for this segment
            if abs(dx) < 0.5:
                x_seg = f"{x0:.1f}"
            else:
                slope_x = dx / dur
                x_seg = f"{x0:.1f}+{slope_x:.4f}*(n-{n0})"

            # y expression for this segment
            if abs(dy) < 0.5:
                y_seg = f"{y0:.1f}"
            else:
                slope_y = dy / dur
                y_seg = f"{y0:.1f}+{slope_y:.4f}*(n-{n0})"

            if k == 0 and n0 == 0:
                expr_parts.append(
                    f"if(lt(n,{n1}),{x_seg}:{y_seg}:{w:.1f}:{h:.1f},"
                )
            else:
                expr_parts.append(
                    f"if(lt(n,{n1}),{x_seg}:{y_seg}:{w:.1f}:{h:.1f},"
                )

        # Final else: use last keyframe position
        last_x, last_y = keyframes[-1][1], keyframes[-1][2]
        expr_parts.append(f"{last_x:.1f}:{last_y:.1f}:{w:.1f}:{h:.1f}")
        expr_parts.append(")" * (len(keyframes) - 1))

        crop_expr = "".join(expr_parts)

        # Build FFmpeg command
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vf", f"crop={crop_expr},scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},setsar=1",
            "-c:a", "copy",
            str(output_path),
        ]

        logger.debug(
            "[FaceAutocrop] Single-pass crop expression (%d keyframes, %d chars)",
            len(keyframes), len(crop_expr),
        )

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode != 0:
                logger.warning(
                    "[FaceAutocrop] FFmpeg error: %s",
                    result.stderr.decode()[:300],
                )
                return False
            return output_path.exists()
        except Exception as e:
            logger.warning("[FaceAutocrop] FFmpeg exception: %s", e)
            return False

    async def _render_segmented(
        self,
        clip_path: Path,
        output_path: Path,
        crop_boxes: List[Tuple[float, float, float, float]],
        fps: float,
    ) -> bool:
        """Render long clips by splitting into segments, cropping each, then
        concatenating.

        Each segment is ~2 seconds (60 frames at 30fps) to keep the crop
        expression simple and accurate.
        """
        segment_duration_frames = int(fps * 2.0)  # 2-second segments
        n_frames = len(crop_boxes)
        segments: List[Path] = []
        temp_dir = Path(tempfile.mkdtemp(prefix="viraclip_autocrop_"))

        try:
            for seg_start in range(0, n_frames, segment_duration_frames):
                seg_end = min(seg_start + segment_duration_frames, n_frames)
                seg_boxes = crop_boxes[seg_start:seg_end]

                # Time range in seconds
                t_start = seg_start / fps
                t_end = seg_end / fps

                seg_out = temp_dir / f"seg_{seg_start:06d}.mp4"

                # Use the average crop box for this segment (stable, no jitter)
                avg_x = sum(b[0] for b in seg_boxes) / len(seg_boxes)
                avg_y = sum(b[1] for b in seg_boxes) / len(seg_boxes)
                w, h = seg_boxes[0][2], seg_boxes[0][3]

                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{t_start:.3f}",
                    "-i", str(clip_path),
                    "-t", f"{t_end - t_start:.3f}",
                    "-vf", f"crop={avg_x:.1f}:{avg_y:.1f}:{w:.1f}:{h:.1f},"
                           f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},setsar=1",
                    "-c:a", "copy",
                    str(seg_out),
                ]

                result = subprocess.run(cmd, capture_output=True, timeout=120)
                if result.returncode != 0 or not seg_out.exists():
                    logger.warning(
                        "[FaceAutocrop] Segment %d failed: %s",
                        seg_start, result.stderr.decode()[:200],
                    )
                    continue

                segments.append(seg_out)

            if not segments:
                return False

            if len(segments) == 1:
                segments[0].rename(output_path)
                return True

            # Concatenate segments
            concat_file = temp_dir / "concat.txt"
            with open(concat_file, "w") as f:
                for seg in segments:
                    f.write(f"file '{seg.name}'\n")

            cmd_concat = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(output_path),
            ]

            result = subprocess.run(cmd_concat, capture_output=True, timeout=120)
            if result.returncode != 0 or not output_path.exists():
                logger.warning(
                    "[FaceAutocrop] Concat failed: %s",
                    result.stderr.decode()[:200],
                )
                # Fallback: use first segment
                if segments:
                    segments[0].rename(output_path)
                    return True
                return False

            return True

        except Exception as e:
            logger.warning("[FaceAutocrop] Segmented render error: %s", e)
            return False
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ── Fallback ────────────────────────────────────────────────────────────

    async def _fallback_center_crop(
        self, clip_path: Path, output_path: Path,
    ) -> Dict[str, Any]:
        """Fallback: center crop on upper third of frame.

        Used when face detection fails or OpenCV is unavailable.
        Output is always 1080×1920, setsar=1.
        """
        logger.info("[FaceAutocrop] No face detected, using center crop")

        probe = await self._probe_video(clip_path)
        if not probe:
            # Last resort: copy original
            import shutil
            shutil.copy2(str(clip_path), str(output_path))
            return {
                "path": output_path,
                "success": True,
                "method": "fallback",
                "face_detection_rate": 0.0,
                "error": "Could not probe video",
            }

        input_width = probe["width"]
        input_height = probe["height"]

        # Calculate 9:16 crop from upper third
        crop_h = float(input_height)
        crop_w = crop_h * TARGET_ASPECT

        if crop_w > input_width:
            crop_w = float(input_width)
            crop_h = crop_w / TARGET_ASPECT

        # Center horizontally, upper third vertically
        x = (input_width - crop_w) / 2
        y = input_height * FALLBACK_CROP_Y_RATIO

        # Clamp
        if y + crop_h > input_height:
            y = float(input_height - crop_h)
        if y < 0:
            y = 0.0

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vf", f"crop={x:.1f}:{y:.1f}:{crop_w:.1f}:{crop_h:.1f},"
                   f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},setsar=1",
            "-c:a", "copy",
            str(output_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and output_path.exists():
                logger.info(
                    "[FaceAutocrop] ✓ Fallback center crop applied → %s",
                    output_path.name,
                )
                return {
                    "path": output_path,
                    "success": True,
                    "method": "center_crop",
                    "face_detection_rate": 0.0,
                    "error": None,
                }
        except Exception as e:
            logger.warning("[FaceAutocrop] Fallback FFmpeg error: %s", e)

        # Absolute last resort: copy original
        import shutil
        shutil.copy2(str(clip_path), str(output_path))
        return {
            "path": output_path,
            "success": True,
            "method": "fallback",
            "face_detection_rate": 0.0,
            "error": "FFmpeg fallback failed",
        }

    # ── Video probing ───────────────────────────────────────────────────────

    async def _probe_video(self, clip_path: Path) -> Optional[Dict[str, Any]]:
        """Probe video dimensions, fps, and duration using ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            str(clip_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=15)
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)

            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if not video_stream:
                return None

            width = int(video_stream.get("width", 0))
            height = int(video_stream.get("height", 0))

            # Parse fps
            r_frame_rate = video_stream.get("r_frame_rate", "30/1")
            num, den = r_frame_rate.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 30.0

            # Duration
            duration_str = data.get("format", {}).get("duration", "0")
            duration = float(duration_str)

            return {
                "width": width,
                "height": height,
                "fps": fps,
                "duration": duration,
            }
        except Exception as e:
            logger.debug("[FaceAutocrop] Probe error: %s", e)
            return None


# ── Convenience function ─────────────────────────────────────────────────────

_autocrop_instance: Optional[FaceAutocropService] = None


def get_face_autocrop_service() -> FaceAutocropService:
    """Get or create the singleton FaceAutocropService instance."""
    global _autocrop_instance
    if _autocrop_instance is None:
        _autocrop_instance = FaceAutocropService()
    return _autocrop_instance


async def apply_face_autocrop(
    clip_path: Path,
    output_path: Optional[Path] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Convenience function: apply face-tracking auto-crop in one call.

    Args:
        clip_path: Input video path.
        output_path: Output path (default: clip_path.parent / autocrop_{name}).
        **kwargs: Passed through to FaceAutocropService.process().

    Returns:
        Dict with path, success, method, face_detection_rate, error.
    """
    svc = get_face_autocrop_service()
    return await svc.process(clip_path, output_path, **kwargs)
