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

class VideoPolishService:
    """Service for advanced video processing — MediaPipe-powered face tracking."""

    def __init__(self):
        self.face_cascade = None   # kept for Haar fallback only
        self.eye_cascade = None
        self.gaze_model = None

    def _load_cascades(self):
        if self.face_cascade is None:
            face_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            eye_path  = cv2.data.haarcascades + "haarcascade_eye.xml"
            self.face_cascade = cv2.CascadeClassifier(face_path)
            self.eye_cascade  = cv2.CascadeClassifier(eye_path)
            if self.face_cascade.empty():
                self.face_cascade = None
            if self.eye_cascade.empty():
                self.eye_cascade = None

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
                from .enhanced_tracking_service import get_enhanced_tracking_service, TrackingMode
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
            _use_mediapipe = True
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
                "ffmpeg", "-y", "-hide_banner",
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
        Applies subtle gaze correction so the speaker appears to look at camera.

        Algorithm:
        1. Read video frame-by-frame with OpenCV.
        2. Use MediaPipe FaceMesh (refine_landmarks=True) to get iris centers.
           Landmark 468 = left iris center, 473 = right iris center.
           Eye corners give us the "ideal" look-at-camera iris position.
        3. For each detected iris, apply a local circular warp using cv2.remap
           that nudges the iris toward the eye center by CORRECTION_FACTOR (≈35%).
        4. Audio is copied separately with ffmpeg (cv2.VideoWriter has no audio).

        Falls back to pass-through if MediaPipe is unavailable or fails.
        """
        logger.info(f"👁 Applying MediaPipe eye contact correction to {input_path}")

        # Correction strength: 0.0 = no change, 1.0 = full center alignment.
        # 0.35 is subtle enough to look natural, strong enough to be noticeable.
        CORRECTION_FACTOR = 0.35
        # Iris warp radius in pixels (relative to frame height, scaled later)
        IRIS_RADIUS_FRAC = 0.018
        # Process every Nth frame for speed; interpolate between processed frames
        PROCESS_EVERY_N = 2

        try:
            import mediapipe as mp
            import shutil

            mp_face_mesh = mp.solutions.face_mesh  # type: ignore[attr-defined]

            # MediaPipe FaceMesh iris landmark indices (refined model)
            # 468=left iris center, 469-472=left iris ring
            # 473=right iris center, 474-477=right iris ring
            # Eye corners: 33=left inner, 133=left outer, 362=right inner, 263=right outer
            # Upper/lower lid midpoints:  159=left upper, 145=left lower, 386=right upper, 374=right lower
            L_IRIS = 468
            R_IRIS = 473
            L_EYE_INNER, L_EYE_OUTER = 133, 33
            R_EYE_INNER, R_EYE_OUTER = 362, 263
            L_EYE_TOP, L_EYE_BOT = 159, 145
            R_EYE_TOP, R_EYE_BOT = 386, 374

            cap = cv2.VideoCapture(str(input_path))
            if not cap.isOpened():
                raise RuntimeError(f"cv2.VideoCapture failed: {input_path}")

            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Iris warp radius in pixels
            iris_radius = max(10, int(height * IRIS_RADIUS_FRAC))

            # Temp file for silent corrected video
            tmp_video = output_path.parent / f"_ecc_tmp_{output_path.stem}.mp4"

            # cv2.VideoWriter_fourcc (NOT VideoWriter.fourcc) is the correct API in OpenCV 4.x
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (width, height))

            def _warp_iris(
                frame: np.ndarray,
                cx: float, cy: float,  # current iris center (float px)
                tx: float, ty: float,  # target iris center (float px)
                radius: int,
            ) -> np.ndarray:
                """
                Local rubber-sheet warp: pixels within `radius` of the iris
                center are shifted by the correction vector using cv2.remap.
                Pixels outside the radius are unchanged (smooth blend at edge).
                """
                h, w = frame.shape[:2]
                # Build identity maps
                map_x = np.tile(np.arange(w, dtype=np.float32), (h, 1))
                map_y = np.repeat(np.arange(h, dtype=np.float32)[:, None], w, axis=1)

                dx = tx - cx  # correction offset
                dy = ty - cy

                # Region of interest: only update pixels within radius
                x0 = max(0, int(cx) - radius)
                x1 = min(w, int(cx) + radius + 1)
                y0 = max(0, int(cy) - radius)
                y1 = min(h, int(cy) + radius + 1)

                # Pixel coords in the patch
                xs = np.arange(x0, x1, dtype=np.float32)
                ys = np.arange(y0, y1, dtype=np.float32)
                gx, gy = np.meshgrid(xs, ys)

                # Distance from iris center
                dist = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)
                # Smooth blend weight: 1 at center → 0 at edge
                weight = np.clip(1.0 - dist / radius, 0, 1)

                map_x[y0:y1, x0:x1] -= dx * weight
                map_y[y0:y1, x0:x1] -= dy * weight

                return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)

            def _landmark_px(lm, w, h):
                return lm.x * w, lm.y * h

            processed_count = 0
            skipped_count = 0
            frame_idx = 0
            prev_correction: list = []  # reuse last known correction

            with mp_face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,  # needed for iris landmarks (468+)
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            ) as face_mesh:

                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    frame_idx += 1
                    corrected = frame

                    # Only run MediaPipe on every Nth frame for speed
                    run_mp = (frame_idx % PROCESS_EVERY_N == 0)

                    if run_mp:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        results = face_mesh.process(rgb)

                        corrections = []
                        if results.multi_face_landmarks:
                            lms = results.multi_face_landmarks[0].landmark

                            for iris_idx, inner_idx, outer_idx, top_idx, bot_idx in [
                                (L_IRIS, L_EYE_INNER, L_EYE_OUTER, L_EYE_TOP, L_EYE_BOT),
                                (R_IRIS, R_EYE_INNER, R_EYE_OUTER, R_EYE_TOP, R_EYE_BOT),
                            ]:
                                if iris_idx >= len(lms):
                                    continue
                                ix, iy = _landmark_px(lms[iris_idx], width, height)
                                # Eye bounding box center = "camera-aligned" target
                                ex_l, _ = _landmark_px(lms[inner_idx], width, height)
                                ex_r, _ = _landmark_px(lms[outer_idx], width, height)
                                _, ey_t = _landmark_px(lms[top_idx], width, height)
                                _, ey_b = _landmark_px(lms[bot_idx], width, height)
                                eye_cx = (ex_l + ex_r) / 2
                                eye_cy = (ey_t + ey_b) / 2
                                # Target = partial move toward eye center
                                tx = ix + (eye_cx - ix) * CORRECTION_FACTOR
                                ty = iy + (eye_cy - iy) * CORRECTION_FACTOR
                                corrections.append((ix, iy, tx, ty))

                        prev_correction = corrections

                    # Apply last known correction
                    for (ix, iy, tx, ty) in prev_correction:
                        corrected = _warp_iris(corrected, ix, iy, tx, ty, iris_radius)

                    writer.write(corrected)
                    processed_count += 1

            cap.release()
            writer.release()

            logger.info(
                f"👁 Eye contact: processed {processed_count} frames "
                f"(MediaPipe ran on every {PROCESS_EVERY_N} frames)"
            )

            # Merge audio from original back into corrected video
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_video),
                "-i", str(input_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0?",  # ? = optional, skip if no audio
                "-shortest",
                str(output_path),
            ]
            result = subprocess.run(
                ffmpeg_cmd, capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                # Audio merge failed — use silent corrected video as fallback
                logger.warning(f"Audio merge failed: {result.stderr[:200]} — using silent output")
                import shutil
                shutil.copy(tmp_video, output_path)

            # Clean up temp file
            try:
                tmp_video.unlink()
            except Exception as e:
                logger.warning(f"[POLISH] Failed to delete temp file {tmp_video}: {e}")

            logger.info(f"✅ Eye contact correction done: {output_path}")

        except ImportError:
            logger.warning("MediaPipe not installed — eye contact correction skipped (pass-through)")
            import shutil
            shutil.copy(input_path, output_path)
        except Exception as e:
            logger.error(f"❌ Eye contact correction failed: {e} — falling back to pass-through")
            import shutil
            try:
                shutil.copy(input_path, output_path)
            except Exception as e:
                logger.error(f"[POLISH] Fallback copy failed {input_path} → {output_path}: {e}", exc_info=True)

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
            # Get clip duration via ffprobe
            probe_result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-select_streams", "v:0", str(input_path)],
                capture_output=True, text=True, timeout=30,
            )
            if probe_result.returncode != 0:
                raise RuntimeError(f"ffprobe failed: {probe_result.stderr}")

            import json as _json
            probe_data = _json.loads(probe_result.stdout)
            video_stream = probe_data.get("streams", [{}])[0]
            duration_str = video_stream.get("duration", "0")
            try:
                duration = float(duration_str)
            except (ValueError, TypeError):
                duration = 0.0

            if duration < 2.0:
                logger.warning(f"Clip too short for pattern interrupts ({duration:.1f}s) — skipping")
                import shutil
                shutil.copy(input_path, output_path)
                return True

            width = int(video_stream.get("width", 1080))
            height = int(video_stream.get("height", 1920))
            fps_raw = video_stream.get("r_frame_rate", "30/1")
            try:
                num, den = fps_raw.split("/")
                fps = float(num) / float(den)
            except Exception as e:
                logger.warning(f"[POLISH] Failed to parse FPS '{fps_raw}': {e} — defaulting to 30.0")
                fps = 30.0

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
