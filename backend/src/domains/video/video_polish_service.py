"""
Video Polish Service - handles advanced AI enhancements like eye contact correction.
"""
import logging
import os
import subprocess
import tempfile
from pathlib import Path
import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

class VideoPolishService:
    """Service for advanced video processing — MediaPipe-powered face tracking."""

    def __init__(self):
        self.face_cascade        = None   # frontal face
        self.face_profile_casc   = None   # side/profile face
        self.eye_cascade         = None   # standard eyes
        self.eye_glasses_casc    = None   # eyes with glasses
        self.gaze_model          = None

    def _load_cascades(self):
        if self.face_cascade is not None:
            return
        d = cv2.data.haarcascades
        def _load(name):
            c = cv2.CascadeClassifier(d + name)
            return None if c.empty() else c
        self.face_cascade      = _load("haarcascade_frontalface_default.xml")
        self.face_profile_casc = _load("haarcascade_profileface.xml")
        self.eye_cascade       = _load("haarcascade_eye.xml")
        # haarcascade_eye_tree_eyeglasses detects eyes WITH glasses much better
        self.eye_glasses_casc  = _load("haarcascade_eye_tree_eyeglasses.xml")

    # ── FaceMesh landmark helpers ────────────────────────────────────────────

    # Face-oval landmark indices (MediaPipe FaceMesh 478-point model)
    # These form the outer boundary of the face — great for bounding-box extraction.
    _OVAL_LM = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
                397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
                172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]

    @staticmethod
    def _face_centroid_from_landmarks(landmarks, img_w: int, img_h: int):
        """Return (cx, cy) in pixel coords from FaceMesh oval landmarks."""
        xs = [landmarks.landmark[i].x * img_w for i in VideoPolishService._OVAL_LM]
        ys = [landmarks.landmark[i].y * img_h for i in VideoPolishService._OVAL_LM]
        return float(np.mean(xs)), float(np.mean(ys))

    @staticmethod
    def _gaussian_smooth(arr: np.ndarray, sigma: float = 8.0) -> np.ndarray:
        """Apply 1-D Gaussian smoothing to a position array.

        Uses reflect-padding (not zero-padding) so edge values are preserved
        without being dragged toward zero by the convolution boundary.
        """
        kernel_r = int(3 * sigma)
        kernel_size = 2 * kernel_r + 1
        x = np.arange(kernel_size) - kernel_r
        kernel = np.exp(-0.5 * (x / sigma) ** 2)
        kernel /= kernel.sum()
        padded = np.pad(arr, kernel_r, mode="reflect")
        return np.convolve(padded, kernel, mode="valid")

    # ── Main face-tracking crop (MediaPipe FaceMesh, two-pass, smooth XY) ───

    async def auto_center_face(self, input_path: Path, output_path: Path) -> bool:
        """
        Two-pass MediaPipe FaceMesh face-tracking crop with smooth XY trajectory.

        Pass 1: Extract face centroid (cx, cy) for every frame using FaceMesh.
                Missing detections are linearly interpolated from neighbours.
        Smooth: Apply Gaussian filter (σ=8 frames) independently over X and Y
                trajectories — eliminates jitter without introducing lag spikes.
        Pass 2: Re-read frames, apply per-frame crop at smoothed position, write.
        FFmpeg: Merge original audio back (cv2.VideoWriter is video-only).

        Falls back to Haar cascade + EMA if MediaPipe is unavailable.
        
        If SAM2_ENABLED=true, uses enhanced multi-subject tracking instead.
        """
        # Check if enhanced tracking should be used
        sam2_enabled = os.environ.get("SAM2_ENABLED", "false").lower() == "true"
        
        if sam2_enabled:
            try:
                from ...services.enhanced_tracking_service import get_enhanced_tracking_service, TrackingMode
                logger.info("🎯 Using enhanced SAM2 tracking for face-centering: %s", input_path.name)
                
                # Use enhanced tracking service
                tracking_svc = get_enhanced_tracking_service()
                tracking_mode_str = os.environ.get("TRACKING_MODE", "auto")
                tracking_mode = TrackingMode(tracking_mode_str)
                
                # Track subject (this returns trajectory, not crop video)
                # For now, log that enhanced tracking is available but fall through to standard method
                logger.info("Enhanced tracking mode: %s (trajectory-based cropping not yet implemented)", tracking_mode.value)
                
            except Exception as e:
                logger.debug("Enhanced tracking unavailable, using standard face tracking: %s", e)
        
        logger.info("🎯 Starting MediaPipe FaceMesh face-tracking crop: %s", input_path.name)

        try:
            import mediapipe as mp  # noqa: F401
            # MediaPipe 0.10+ removed mp.solutions — check before enabling
            _use_mediapipe = hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh")
            if not _use_mediapipe:
                logger.warning("MediaPipe installed but mp.solutions unavailable (v0.10+) — using Haar cascade")
        except ImportError:
            logger.warning("MediaPipe not installed — falling back to Haar cascade crop")
            _use_mediapipe = False

        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._center_face_two_pass, input_path, output_path, _use_mediapipe
        )

    def _center_face_two_pass(
        self, input_path: Path, output_path: Path, use_mediapipe: bool
    ) -> bool:
        try:
            cap = cv2.VideoCapture(str(input_path))
            if not cap.isOpened():
                import shutil; shutil.copy(input_path, output_path)
                return False

            width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
            n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

            # ── Target dimensions (9:16 portrait) ──────────────────────────
            target_w = min(int(height * 9 / 16), width)
            target_h = height
            target_w -= target_w % 2
            target_h -= target_h % 2

            # ── PASS 1: Collect face centroids ──────────────────────────────
            raw_cx = np.full(max(n_frames, 1), width  / 2.0, dtype=np.float32)
            raw_cy = np.full(max(n_frames, 1), height * 0.35, dtype=np.float32)
            detected = np.zeros(max(n_frames, 1), dtype=bool)
            frame_count = 0

            if use_mediapipe:
                import mediapipe as mp
                mp_fm = mp.solutions.face_mesh  # type: ignore[attr-defined]
                fm_cfg = dict(
                    static_image_mode=False, max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.4,
                    min_tracking_confidence=0.4,
                )
                with mp_fm.FaceMesh(**fm_cfg) as fm:
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        idx = frame_count
                        frame_count += 1
                        if idx >= len(raw_cx):
                            raw_cx = np.append(raw_cx, width / 2.0)
                            raw_cy = np.append(raw_cy, height * 0.35)
                            detected = np.append(detected, False)

                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        results = fm.process(rgb)
                        if results.multi_face_landmarks:
                            cx, cy = self._face_centroid_from_landmarks(
                                results.multi_face_landmarks[0], width, height
                            )
                            raw_cx[idx] = cx
                            raw_cy[idx] = cy
                            detected[idx] = True
            else:
                # Haar cascade fallback for pass 1
                self._load_cascades()
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    idx = frame_count
                    frame_count += 1
                    if idx >= len(raw_cx):
                        raw_cx = np.append(raw_cx, width / 2.0)
                        raw_cy = np.append(raw_cy, height * 0.35)
                        detected = np.append(detected, False)
                    if self.face_cascade:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        faces = self.face_cascade.detectMultiScale(
                            gray, 1.1, 4, minSize=(40, 40)
                        )
                        if len(faces) > 0:
                            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                            raw_cx[idx] = float(x + w / 2)
                            raw_cy[idx] = float(y + h * 0.4)
                            detected[idx] = True

            cap.release()
            if frame_count == 0:
                import shutil; shutil.copy(input_path, output_path)
                return False

            raw_cx = raw_cx[:frame_count]
            raw_cy = raw_cy[:frame_count]
            detected = detected[:frame_count]

            # ── Interpolate missing detections ──────────────────────────────
            if detected.any():
                det_idx = np.where(detected)[0]
                raw_cx = np.interp(np.arange(frame_count), det_idx, raw_cx[det_idx])
                raw_cy = np.interp(np.arange(frame_count), det_idx, raw_cy[det_idx])

            # ── Gaussian smooth XY trajectory ───────────────────────────────
            sigma = max(4.0, fps * 0.25)   # 0.25 s of smoothing
            smooth_cx = self._gaussian_smooth(raw_cx, sigma)
            smooth_cy = self._gaussian_smooth(raw_cy, sigma)

            face_pct = int(100 * detected.sum() / frame_count)
            logger.info(
                "Pass 1 done: %d frames, face detected %.0f%%, σ=%.1f",
                frame_count, face_pct, sigma
            )

            # ── PASS 2: Write cropped frames ────────────────────────────────
            cap2 = cv2.VideoCapture(str(input_path))
            fourcc = cv2.VideoWriter_fourcc(*"avc1")
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (target_w, target_h))
            if not out.isOpened():
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                out = cv2.VideoWriter(str(output_path), fourcc, fps, (target_w, target_h))

            written = 0
            while True:
                ret, frame = cap2.read()
                if not ret:
                    break
                idx = min(written, frame_count - 1)

                cx = int(np.clip(smooth_cx[idx], target_w // 2, width - target_w // 2))
                cy = int(np.clip(smooth_cy[idx], 0, height - target_h))

                # Horizontal crop centred on face X
                left = cx - target_w // 2
                left = max(0, min(left, width - target_w))
                left -= left % 2

                # Vertical crop: face in upper-middle area of frame
                top = max(0, min(cy - int(target_h * 0.30), height - target_h))
                top -= top % 2

                cropped = frame[top:top + target_h, left:left + target_w]
                if cropped.shape[:2] == (target_h, target_w):
                    out.write(cropped)
                else:
                    cl = (width - target_w) // 2
                    out.write(frame[0:target_h, cl:cl + target_w])
                written += 1

            cap2.release()
            out.release()
            logger.info("Pass 2 done: %d frames written", written)

            # ── FFmpeg: merge original audio ────────────────────────────────
            temp_v = output_path.with_suffix(".noaudio.mp4")
            os.rename(str(output_path), str(temp_v))
            ffmpeg_cmd = [
                _get_ffmpeg_exe(), "-y", "-hide_banner",
                "-i", str(temp_v),
                "-i", str(input_path),
                "-map", "0:v:0",
                "-map", "1:a:0?",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(output_path),
            ]
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=120)
            try:
                os.unlink(str(temp_v))
            except OSError:
                pass
            if result.returncode != 0:
                logger.warning("ffmpeg audio merge warning: %s", result.stderr[-300:])
            else:
                logger.info("✅ FaceMesh face-tracking crop complete: %s", output_path.name)
            return True

        except Exception as exc:
            logger.error("❌ auto_center_face failed: %s", exc, exc_info=True)
            try:
                import shutil; shutil.copy(input_path, output_path)
            except Exception:
                pass
            return False

    async def apply_eye_contact_correction(self, input_path: Path, output_path: Path):
        """
        Gaze correction using OpenCV only (no MediaPipe required).

        Algorithm:
        1. Detect face + eye regions with Haar cascades.
        2. Within each eye ROI: detect iris/pupil center with HoughCircles on the
           grayscale ROI — works even with glasses (finds dark circular pupil).
        3. Compute target = center of the eye bounding box (= camera-aligned position).
        4. Apply a local rubber-sheet warp (cv2.remap) to nudge iris toward target.
        5. Glasses glare reduction: in each eye ROI, detect bright specular highlights
           (top 1% luminance) and blend them down with the surrounding skin tone.
        6. Audio merged back via FFmpeg.

        Falls back to pass-through if face detection fails entirely.
        """
        logger.info(f"👁 Applying OpenCV gaze correction to {input_path.name}")

        CORRECTION_FACTOR = 0.30   # 0=no change, 1=full center; 0.30 = subtle
        IRIS_RADIUS_FRAC  = 0.020  # iris warp radius as fraction of frame height
        PROCESS_EVERY_N   = 3      # run detection every N frames, interpolate rest
        GLARE_PERCENTILE  = 99     # luminance threshold for glare detection

        try:
            import shutil
            self._load_cascades()
            if self.face_cascade is None:
                raise RuntimeError("Haar cascades unavailable")

            cap = cv2.VideoCapture(str(input_path))
            if not cap.isOpened():
                raise RuntimeError(f"VideoCapture failed: {input_path}")

            fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
            width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            iris_radius = max(10, int(height * IRIS_RADIUS_FRAC))

            tmp_video = output_path.parent / f"_ecc_tmp_{output_path.stem}.mp4"
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (width, height))

            # ── helpers ────────────────────────────────────────────────────────

            def _warp_iris(frame, cx, cy, tx, ty, radius, strength=1.0):
                """Rubber-sheet local warp: nudge iris toward target.
                `strength` scales the correction (0=none, 1=full CORRECTION_FACTOR)."""
                if strength <= 0.01:
                    return frame
                h, w = frame.shape[:2]
                map_x = np.tile(np.arange(w, dtype=np.float32), (h, 1))
                map_y = np.repeat(np.arange(h, dtype=np.float32)[:, None], w, axis=1)
                dx = (tx - cx) * strength
                dy = (ty - cy) * strength
                x0, x1 = max(0, int(cx)-radius), min(w, int(cx)+radius+1)
                y0, y1 = max(0, int(cy)-radius), min(h, int(cy)+radius+1)
                xs = np.arange(x0, x1, dtype=np.float32)
                ys = np.arange(y0, y1, dtype=np.float32)
                gx, gy = np.meshgrid(xs, ys)
                dist = np.sqrt((gx - cx)**2 + (gy - cy)**2)
                weight = np.clip(1.0 - dist / radius, 0, 1)
                map_x[y0:y1, x0:x1] -= dx * weight
                map_y[y0:y1, x0:x1] -= dy * weight
                return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)

            def _reduce_glare(frame, ex, ey, ew, eh):
                """Reduce specular glare (glasses lens reflections) using local blending."""
                if ew <= 0 or eh <= 0:
                    return frame
                roi = frame[ey:ey+eh, ex:ex+ew].copy()
                gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                thresh = np.percentile(gray_roi, GLARE_PERCENTILE)
                if thresh >= 250:   # whole area is bright — skip to avoid over-processing
                    return frame
                glare_mask = (gray_roi > thresh).astype(np.uint8) * 255
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                glare_mask = cv2.dilate(glare_mask, kernel, iterations=1)
                if glare_mask.sum() == 0:
                    return frame
                blurred = cv2.GaussianBlur(roi, (15, 15), 0)
                mask_3c = cv2.cvtColor(glare_mask, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
                roi_out = (roi.astype(np.float32) * (1 - mask_3c * 0.55) +
                           blurred.astype(np.float32) * (mask_3c * 0.55)).astype(np.uint8)
                result = frame.copy()
                result[ey:ey+eh, ex:ex+ew] = roi_out
                return result

            def _detect_iris_hough(eye_roi_gray):
                """Detect iris/pupil center using HoughCircles — works with glasses."""
                h, w = eye_roi_gray.shape
                blurred = cv2.GaussianBlur(eye_roi_gray, (7, 7), 1.5)
                min_r = max(3, w // 8)
                max_r = max(min_r + 2, w // 3)
                circles = cv2.HoughCircles(
                    blurred, cv2.HOUGH_GRADIENT, dp=1,
                    minDist=w // 2,
                    param1=50, param2=15,
                    minRadius=min_r, maxRadius=max_r,
                )
                if circles is not None:
                    c = circles[0][0]
                    return float(c[0]), float(c[1])
                # Fallback: darkest region centroid (pupil is darkest even through glass)
                _, thresh = cv2.threshold(blurred, 0, 255,
                                          cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                M = cv2.moments(thresh)
                if M["m00"] > 0:
                    return M["m10"] / M["m00"], M["m01"] / M["m00"]
                return float(w // 2), float(h // 2)

            def _detect_face_and_eyes(gray):
                """
                Detect face + eyes, returning a list of corrections and a frontality score.

                Frontality score (0.0–1.0):
                  - Estimated from face aspect ratio (w/h): a fully frontal face
                    has w/h ≈ 0.75–0.85. Very narrow = profile = low frontality.
                  - Profile cascade hit with no frontal hit → frontality = 0 (no correction).
                  - Score is used to scale CORRECTION_FACTOR so side-facing frames
                    get little or no gaze correction (would look unnatural).

                Eye cascade priority:
                  1. haarcascade_eye_tree_eyeglasses (glasses-aware, if available)
                  2. haarcascade_eye (standard)
                """
                corrections = []

                # 1. Try frontal detection
                faces_frontal = self.face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
                ) if self.face_cascade else []

                # 2. Try profile if no frontal hit
                faces_profile = []
                if len(faces_frontal) == 0 and self.face_profile_casc:
                    faces_profile = self.face_profile_casc.detectMultiScale(
                        gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50)
                    )
                    # Mirror image and try again (profile cascade is one-directional)
                    if len(faces_profile) == 0:
                        faces_profile = self.face_profile_casc.detectMultiScale(
                            cv2.flip(gray, 1), scaleFactor=1.1, minNeighbors=4, minSize=(50, 50)
                        )

                is_profile = len(faces_frontal) == 0 and len(faces_profile) > 0
                all_faces  = list(faces_frontal) if len(faces_frontal) > 0 else list(faces_profile)

                if len(all_faces) == 0:
                    return corrections, 0.0

                fx, fy, fw, fh = max(all_faces, key=lambda r: r[2]*r[3])

                # Frontality score: ratio of face width to height
                # Frontal ≈ 0.75–0.90 aspect; profile ≈ 0.4–0.6
                aspect = fw / max(fh, 1)
                if is_profile:
                    frontality = 0.0   # side view — no correction
                else:
                    # Linearly map aspect 0.55→0.0 .. 0.80→1.0
                    frontality = float(np.clip((aspect - 0.55) / (0.80 - 0.55), 0.0, 1.0))

                if frontality < 0.05:
                    return corrections, frontality  # too side-on, skip

                face_gray = gray[fy:fy+fh, fx:fx+fw]
                upper_h   = int(fh * 0.60)  # eyes are in upper 60% of face

                # Choose best eye cascade (glasses-aware preferred)
                eye_casc = self.eye_glasses_casc or self.eye_cascade
                if eye_casc is None:
                    return corrections, frontality

                eyes = eye_casc.detectMultiScale(
                    face_gray[:upper_h], scaleFactor=1.1,
                    minNeighbors=3, minSize=(18, 18)
                )
                # If glasses cascade found nothing, try standard cascade as backup
                if len(eyes) == 0 and self.eye_glasses_casc and self.eye_cascade:
                    eyes = self.eye_cascade.detectMultiScale(
                        face_gray[:upper_h], scaleFactor=1.1,
                        minNeighbors=3, minSize=(18, 18)
                    )

                for (ex, ey, ew, eh) in eyes[:2]:
                    abs_ex, abs_ey = fx + ex, fy + ey
                    eye_cx = abs_ex + ew / 2.0
                    eye_cy = abs_ey + eh / 2.0
                    eye_roi = gray[abs_ey:abs_ey+eh, abs_ex:abs_ex+ew]
                    if eye_roi.size == 0:
                        continue
                    lx, ly = _detect_iris_hough(eye_roi)
                    ix, iy = abs_ex + lx, abs_ey + ly
                    tx = ix + (eye_cx - ix) * CORRECTION_FACTOR
                    ty = iy + (eye_cy - iy) * CORRECTION_FACTOR
                    corrections.append((ix, iy, tx, ty, abs_ex, abs_ey, ew, eh))

                return corrections, frontality

            # ── main processing loop ───────────────────────────────────────────
            frame_idx        = 0
            prev_corrections: list = []
            prev_frontality  = 1.0
            processed_count  = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_idx += 1
                corrected = frame.copy()

                if frame_idx % PROCESS_EVERY_N == 0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = cv2.equalizeHist(gray)
                    prev_corrections, prev_frontality = _detect_face_and_eyes(gray)

                # Scale correction by frontality: side-facing → less/no correction
                for (ix, iy, tx, ty, abs_ex, abs_ey, ew, eh) in prev_corrections:
                    corrected = _reduce_glare(corrected, abs_ex, abs_ey, ew, eh)
                    corrected = _warp_iris(corrected, ix, iy, tx, ty,
                                           iris_radius, strength=prev_frontality)

                writer.write(corrected)
                processed_count += 1

            cap.release()
            writer.release()
            logger.info(f"👁 Gaze correction: {processed_count} frames processed")

            # Merge original audio back
            ffmpeg_cmd = [
                _get_ffmpeg_exe(), "-y",
                "-i", str(tmp_video),
                "-i", str(input_path),
                "-c:v", "copy", "-c:a", "aac",
                "-map", "0:v:0", "-map", "1:a:0?",
                "-shortest", str(output_path),
            ]
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.warning(f"Audio merge failed — using silent output")
                shutil.copy(tmp_video, output_path)
            try:
                tmp_video.unlink()
            except Exception:
                pass
            logger.info(f"✅ Gaze correction done: {output_path.name}")

        except Exception as e:
            logger.error(f"❌ Gaze correction failed: {e} — pass-through")
            import shutil
            try:
                shutil.copy(input_path, output_path)
            except Exception as ce:
                logger.error(f"Pass-through copy failed: {ce}", exc_info=True)

    async def apply_pattern_interrupts(self, input_path: Path, output_path: Path, viral_cues: list) -> bool:
        """
        Applies dynamic micro-zoom Pattern Interrupts to maximize viewer retention.

        Adds subtle zoom-in/out pulses every 3-4 seconds using ffmpeg zoompan filter.
        These "pattern interrupts" reset viewer attention and are characteristic of
        high-retention viral content.

        Returns True on success, False on failure.
        """
        logger.info(f"🎬 Applying Pattern Interrupts to {input_path.name}")
        try:
            # Get clip duration via ffmpeg -i (imageio_ffmpeg doesn't bundle ffprobe)
            import re
            probe_result = subprocess.run(
                [_get_ffmpeg_exe(), "-i", str(input_path)],
                capture_output=True, text=True, timeout=30,
            )
            stderr = probe_result.stderr
            
            # Parse duration: "Duration: 00:01:23.45"
            duration = 0.0
            dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
            if dur_match:
                hours = int(dur_match.group(1))
                minutes = int(dur_match.group(2))
                seconds = float(dur_match.group(3))
                duration = hours * 3600 + minutes * 60 + seconds
            
            if duration < 2.0:
                logger.warning(f"Clip too short for pattern interrupts ({duration:.1f}s) — skipping")
                import shutil
                shutil.copy(input_path, output_path)
                return True

            # Parse dimensions: "1920x1080" or "1080x1920"
            dim_match = re.search(r'(\d{3,4})x(\d{3,4})', stderr)
            if dim_match:
                width = int(dim_match.group(1))
                height = int(dim_match.group(2))
            else:
                width, height = 1080, 1920
            
            # Parse FPS: "30 fps" or "29.97 fps"
            fps = 30.0
            fps_match = re.search(r'(\d+\.?\d*)\s*fps', stderr)
            if fps_match:
                fps = float(fps_match.group(1))

            total_frames = int(duration * fps)

            # Build zoompan expression:
            # Every INTERRUPT_INTERVAL seconds, apply a micro-zoom (1.0 → 1.04 → 1.0)
            # over ZOOM_FRAMES frames. Between interrupts the zoom stays at 1.0.
            INTERRUPT_INTERVAL = 3.5  # seconds between zooms
            ZOOM_FRAMES = int(fps * 0.35)  # 0.35s zoom duration
            ZOOM_PEAK = 1.04             # subtle 4% zoom — professional, not jarring

            # ffmpeg zoompan: zoom=expression:x=expression:y=expression:d=1:s=WxH:fps=FPS
            # We'll use a piecewise expression: check frame number modulo interval_frames
            interval_frames = int(fps * INTERRUPT_INTERVAL)

            # Build zoom expression:
            # Within each interval: first ZOOM_FRAMES zoom in (0→peak), next ZOOM_FRAMES zoom out (peak→1), rest stay at 1
            # t = frame mod interval_frames
            # if t < ZOOM_FRAMES: zoom = 1 + (ZOOM_PEAK-1) * t/ZOOM_FRAMES
            # elif t < 2*ZOOM_FRAMES: zoom = ZOOM_PEAK - (ZOOM_PEAK-1) * (t-ZOOM_FRAMES)/ZOOM_FRAMES
            # else: zoom = 1
            half = ZOOM_FRAMES
            expr_zoom = (
                f"if(lt(mod(n\\,{interval_frames})\\,{half})"
                f"\\,1+{ZOOM_PEAK-1:.4f}*mod(n\\,{interval_frames})/{half}"
                f"\\,if(lt(mod(n\\,{interval_frames})\\,{2*half})"
                f"\\,{ZOOM_PEAK:.4f}-{ZOOM_PEAK-1:.4f}*(mod(n\\,{interval_frames})-{half})/{half}"
                f"\\,1))"
            )
            # Keep center locked during zoom
            expr_x = f"(iw-iw/zoom)/2"
            expr_y = f"(ih-ih/zoom)/2"

            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vf", f"zoompan=z='{expr_zoom}':x='{expr_x}':y='{expr_y}':d=1:s={width}x{height}:fps={fps:.2f}",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ]
            logger.info(f"Pattern interrupts: running ffmpeg zoompan (interval={INTERRUPT_INTERVAL}s, peak={ZOOM_PEAK}x)")
            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                logger.error(f"ffmpeg zoompan failed: {result.stderr[-400:]}")
                import shutil
                shutil.copy(input_path, output_path)
                return False

            logger.info(f"✅ Pattern interrupts applied: {output_path.name}")
            return True

        except Exception as e:
            logger.error(f"[POLISH] Pattern interrupts error: {e}", exc_info=True)
            try:
                import shutil
                shutil.copy(input_path, output_path)
            except Exception as copy_e:
                logger.error(f"[POLISH] Fallback copy also failed: {copy_e}", exc_info=True)
            return False

    # ── Portrait Background Blur ─────────────────────────────────────────────

    async def blur_background(
        self,
        input_path: Path,
        output_path: Path,
        blur_radius: int = 35,
        process_every_n: int = 3,
    ) -> bool:
        """
        Separate subject from background using MediaPipe Selfie Segmentation
        and apply a Gaussian blur to the background only.

        Algorithm:
        1. Pass 1 (Python/OpenCV): For every Nth frame, run SelfieSegmentation
           (model_selection=1, landscape) to get a soft segmentation mask.
           Blend: blurred_bg * (1-mask) + original * mask.
        2. All frames are written to a temp MP4 (no audio).
        3. FFmpeg merges original audio back into the blurred video.

        Falls back to a simple FFmpeg boxblur pass when MediaPipe is unavailable.
        """
        logger.info("🌫️  Starting background blur: %s", input_path.name)
        BLUR_STR = f"{blur_radius}:{blur_radius}"

        try:
            import mediapipe as mp
        except ImportError:
            logger.info("  MediaPipe unavailable — using FFmpeg boxblur fallback")
            return await self._ffmpeg_boxblur_fallback(input_path, output_path, BLUR_STR)

        try:
            cap = cv2.VideoCapture(str(input_path))
            if not cap.isOpened():
                raise RuntimeError(f"Cannot open {input_path}")

            width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            temp_v = output_path.with_suffix(".noaudio.mp4")
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(temp_v), fourcc, fps, (width, height))

            seg = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
            prev_mask: np.ndarray | None = None
            frame_idx = 0

            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if frame_idx % process_every_n == 0:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    result = seg.process(rgb)
                    raw_mask = result.segmentation_mask  # float32, 0..1
                    # Smooth mask edges
                    prev_mask = cv2.GaussianBlur(raw_mask, (21, 21), 0)

                if prev_mask is not None:
                    # Blur entire frame then composite using mask
                    blurred = cv2.GaussianBlur(frame, (blur_radius | 1, blur_radius | 1), 0)
                    mask3 = np.stack([prev_mask] * 3, axis=-1)
                    composited = (frame * mask3 + blurred * (1.0 - mask3)).astype(np.uint8)
                    writer.write(composited)
                else:
                    writer.write(frame)

                frame_idx += 1

            cap.release()
            writer.release()
            seg.close()
            logger.info("  Background blur pass done: %d frames", frame_idx)

            # Merge original audio
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-hide_banner",
                "-i", str(temp_v),
                "-i", str(input_path),
                "-map", "0:v:0", "-map", "1:a:0?",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(output_path),
            ]
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=180)
            try:
                os.unlink(str(temp_v))
            except OSError:
                pass
            if result.returncode != 0:
                logger.warning("  ffmpeg audio merge warning: %s", result.stderr[-300:])
            logger.info("✅ Background blur complete: %s", output_path.name)
            return True

        except Exception as exc:
            logger.error("❌ blur_background failed: %s", exc, exc_info=True)
            try:
                import shutil
                shutil.copy(input_path, output_path)
            except Exception:
                pass
            return False

    async def _ffmpeg_boxblur_fallback(
        self, input_path: Path, output_path: Path, blur_str: str
    ) -> bool:
        """FFmpeg boxblur on the full frame — fast, no subject isolation."""
        import asyncio as _asyncio
        proc = await _asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
            "-vf", f"boxblur={blur_str}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy", str(output_path),
            stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
        )
        _, _ = await _asyncio.wait_for(proc.communicate(), timeout=180.0)
        return proc.returncode == 0
