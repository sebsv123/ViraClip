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
    """Service for advanced video processing like gaze redirection."""
    
    def __init__(self):
        self.face_cascade = None
        self.eye_cascade = None
        # Placeholder for deep learning model
        self.gaze_model = None

    def _load_cascades(self):
        if self.face_cascade is None:
            face_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            eye_path = cv2.data.haarcascades + 'haarcascade_eye.xml'
            self.face_cascade = cv2.CascadeClassifier(face_path)
            self.eye_cascade = cv2.CascadeClassifier(eye_path)
            
            if self.face_cascade is None or self.face_cascade.empty():
                logger.error(f"Failed to load face cascade from {face_path}")
                self.face_cascade = None
            if self.eye_cascade is None or self.eye_cascade.empty():
                logger.error(f"Failed to load eye cascade from {eye_path}")
                self.eye_cascade = None

    async def auto_center_face(self, input_path: Path, output_path: Path) -> bool:
        """
        Zooms in and centers the face for a better portrait/shorts look.
        Returns True on success, False on failure (gracefully degrades to copy).
        """
        logger.info(f"Auto-centering face for {input_path}")
        self._load_cascades()

        try:
            cap = cv2.VideoCapture(str(input_path))
            if not cap.isOpened():
                logger.error(f"Failed to open video: {input_path}")
                # Fallback: copy original file
                import shutil
                shutil.copy(input_path, output_path)
                return False

            width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps    = cap.get(cv2.CAP_PROP_FPS)

            if fps <= 0:
                fps = 30  # Fallback FPS

            # Define output target (usually 9:16 for shorts)
            target_aspect = 9/16
            target_w = int(height * target_aspect)
            if target_w > width:
                target_w = width
                target_h = int(width / target_aspect)
            else:
                target_h = height

            # Ensure even dimensions for H.264 compatibility
            target_w = target_w - (target_w % 2)
            target_h = target_h - (target_h % 2)

            # Use avc1/H.264 fourcc when available; fall back to mp4v
            fourcc = cv2.VideoWriter_fourcc(*'avc1')
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (target_w, target_h))
            if not out.isOpened():
                # avc1 not available in this OpenCV build — use mp4v
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(str(output_path), fourcc, fps, (target_w, target_h))

            if not out.isOpened():
                logger.error(f"Failed to open video writer for {output_path}")
                cap.release()
                return False

            # Smoothed face position tracking — exponential moving average to eliminate
            # shakycam jitter when face detection flickers between frames.
            _smooth_cx: float = width / 2.0  # start at center
            _alpha: float = 0.12             # smoothing factor (lower = smoother, more lag)
            _face_detected_frames: int = 0
            _total_frames: int = 0

            frame_count = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                _total_frames += 1

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = []
                if self.face_cascade:
                    faces = self.face_cascade.detectMultiScale(
                        gray, scaleFactor=1.1, minNeighbors=4,
                        minSize=(40, 40), maxSize=(int(width * 0.8), int(height * 0.8)),
                    )

                if len(faces) > 0:
                    # Pick largest face (most likely the primary speaker)
                    (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
                    raw_cx = float(x + w // 2)
                    # Exponential moving average smoothing
                    _smooth_cx = _alpha * raw_cx + (1.0 - _alpha) * _smooth_cx
                    _face_detected_frames += 1

                center_x = int(_smooth_cx)

                # Calculate crop boundaries around smoothed face center
                left = max(0, center_x - target_w // 2)
                right = left + target_w
                if right > width:
                    right = width
                    left = right - target_w
                left = max(0, left)

                # Ensure even boundaries for H.264
                left = left - (left % 2)
                right = left + target_w
                right = min(right, width)

                if left >= 0 and right <= width and (right - left) == target_w:
                    cropped = frame[0:target_h, left:right]
                    out.write(cropped)
                else:
                    # Fallback to center crop
                    left = (width - target_w) // 2
                    cropped = frame[0:target_h, left:left+target_w]
                    out.write(cropped)

                frame_count += 1

            cap.release()
            out.release()
            face_pct = int(100 * _face_detected_frames / max(_total_frames, 1))
            logger.info(
                f"✅ Auto-centered face (video-only) written: {frame_count} frames | "
                f"face detected in {face_pct}% of frames → now merging audio"
            )

            # cv2.VideoWriter writes video-only (no audio track). Use ffmpeg to merge
            # the original audio stream back into the centered video.
            temp_noaudio = output_path.with_suffix(".noaudio.mp4")
            try:
                os.rename(str(output_path), str(temp_noaudio))
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-i", str(temp_noaudio),   # video-only from cv2
                    "-i", str(input_path),      # original clip (for audio)
                    "-map", "0:v:0",            # take video from cv2 output
                    "-map", "1:a:0?",           # take audio from original (? = optional)
                    "-c:v", "copy",             # copy video as-is (fast, no re-encode)
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",               # match shortest stream
                    str(output_path),
                ]
                result = subprocess.run(
                    ffmpeg_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    logger.warning(f"ffmpeg audio merge warning: {result.stderr[-300:]}")
                    # Fallback: at least use the silent video
                    os.rename(str(temp_noaudio), str(output_path))
                else:
                    os.unlink(str(temp_noaudio))
                    logger.info(f"✅ Audio merged into centered clip: {output_path.name}")
            except Exception as merge_e:
                logger.error(f"Audio merge failed: {merge_e}")
                # Recover: rename noaudio back to output
                try:
                    if temp_noaudio.exists() and not output_path.exists():
                        os.rename(str(temp_noaudio), str(output_path))
                except Exception:
                    pass

            return True

        except Exception as e:
            logger.error(f"❌ Auto-center face failed: {e}")
            try:
                import shutil
                shutil.copy(input_path, output_path)
                logger.info(f"Fallback: copied original to {output_path}")
                return False
            except Exception as copy_e:
                logger.error(f"Fallback copy also failed: {copy_e}")
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
            except Exception:
                pass

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
            except Exception:
                pass

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
            except Exception:
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
            logger.error(f"❌ Pattern interrupts error: {e}")
            try:
                import shutil
                shutil.copy(input_path, output_path)
            except Exception:
                pass
            return False
