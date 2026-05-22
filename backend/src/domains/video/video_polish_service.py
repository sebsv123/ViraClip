"""
Video Polish Service - handles advanced AI enhancements like eye contact correction.
"""
import logging
import os

# Protobuf compatibility fix for MediaPipe FaceMesh.
# MediaPipe 0.10.x is incompatible with protobuf >= 4.x (which uses
# upb-backed C extension by default). Setting this env var forces the
# pure-Python protobuf implementation, which is compatible with both
# MediaPipe's symbol_database usage and other protobuf-dependent services.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import subprocess
import tempfile
from pathlib import Path
import cv2
import numpy as np


logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
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
        self.eye_glasses_casc  = _load("haarcascade_eye_tree_eyeglasses.xml")

    # ── FaceMesh landmark helpers ────────────────────────────────────────────

    _OVAL_LM = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
                397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
                172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]

    @staticmethod
    def _face_centroid_from_landmarks(landmarks, img_w: int, img_h: int):
        xs = [landmarks.landmark[i].x * img_w for i in VideoPolishService._OVAL_LM]
        ys = [landmarks.landmark[i].y * img_h for i in VideoPolishService._OVAL_LM]
        return float(np.mean(xs)), float(np.mean(ys))

    @staticmethod
    def _gaussian_smooth(arr: np.ndarray, sigma: float = 8.0) -> np.ndarray:
        kernel_r = int(3 * sigma)
        kernel_size = 2 * kernel_r + 1
        x = np.arange(kernel_size) - kernel_r
        kernel = np.exp(-0.5 * (x / sigma) ** 2)
        kernel /= kernel.sum()
        padded = np.pad(arr, kernel_r, mode="reflect")
        return np.convolve(padded, kernel, mode="valid")

    @staticmethod
    def _write_frames_via_ffmpeg(
        frames_iter,
        output_path: Path,
        fps: float,
        width: int,
        height: int,
        pix_fmt: str = "bgr24",
    ) -> None:
        """Write video frames via FFmpeg pipe using nvenc_h264 (GPU) or libx264 fallback.
        Replaces cv2.VideoWriter which doesn't support NVENC."""
        from ...gpu_utils import ffmpeg_codec_flags as _vp_gpu_flags
        _vp_enc = _vp_gpu_flags("high")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", pix_fmt,
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "-",
        ] + _vp_enc + [
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            for frame in frames_iter:
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            proc.wait(timeout=300)
        except Exception:
            proc.kill()
            raise
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg pipe encoding failed (exit {proc.returncode})")

    # ── Main face-tracking crop (MediaPipe FaceMesh, two-pass, smooth XY) ───

    async def auto_center_face(self, input_path: Path, output_path: Path) -> bool:
        sam2_enabled = os.environ.get("SAM2_ENABLED", "false").lower() == "true"
        if sam2_enabled:
            try:
                from ...core.enhanced_tracking_service import get_enhanced_tracking_service, TrackingMode
                logger.info("🎯 Using enhanced SAM2 tracking for face-centering: %s", input_path.name)
                tracking_svc = get_enhanced_tracking_service()
                tracking_mode_str = os.environ.get("TRACKING_MODE", "auto")
                tracking_mode = TrackingMode(tracking_mode_str)
                logger.info("Enhanced tracking mode: %s (trajectory-based cropping not yet implemented)", tracking_mode.value)
            except Exception as e:
                logger.debug("Enhanced tracking unavailable, using standard face tracking: %s", e)
        logger.info("🎯 Starting MediaPipe FaceMesh face-tracking crop: %s", input_path.name)
        try:
            import mediapipe as mp
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
                mp_fm = mp.solutions.face_mesh
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
                        faces = self.face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
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
            if detected.any():
                det_idx = np.where(detected)[0]
                raw_cx = np.interp(np.arange(frame_count), det_idx, raw_cx[det_idx])
                raw_cy = np.interp(np.arange(frame_count), det_idx, raw_cy[det_idx])
            sigma = max(4.0, fps * 0.25)
            smooth_cx = self._gaussian_smooth(raw_cx, sigma)
            smooth_cy = self._gaussian_smooth(raw_cy, sigma)
            face_pct = int(100 * detected.sum() / frame_count)
            logger.info("Pass 1 done: %d frames, face detected %.0f%%, σ=%.1f", frame_count, face_pct, sigma)

            # ── PASS 2: Write cropped frames via FFmpeg pipe (NVENC) ────────
            cap2 = cv2.VideoCapture(str(input_path))
            def _gen_frames():
                written = 0
                while True:
                    ret, frame = cap2.read()
                    if not ret:
                        break
                    idx = min(written, frame_count - 1)
                    cx = int(np.clip(smooth_cx[idx], target_w // 2, width - target_w // 2))
                    cy = int(np.clip(smooth_cy[idx], 0, height - target_h))
                    left = max(0, min(cx - target_w // 2, width - target_w))
                    left -= left % 2
                    top = max(0, min(cy - int(target_h * 0.30), height - target_h))
                    top -= top % 2
                    cropped = frame[top:top + target_h, left:left + target_w]
                    if cropped.shape[:2] == (target_h, target_w):
                        yield cropped
                    else:
                        cl = (width - target_w) // 2
                        yield frame[0:target_h, cl:cl + target_w]
                    written += 1
            temp_v = output_path.with_suffix(".noaudio.mp4")
            self._write_frames_via_ffmpeg(_gen_frames(), temp_v, fps, target_w, target_h)
            cap2.release()
            logger.info("Pass 2 done via FFmpeg pipe")

            # ── FFmpeg: merge original audio ────────────────────────────────
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
        logger.info(f"👁 Applying OpenCV gaze correction to {input_path.name}")
        CORRECTION_FACTOR = 0.30
        IRIS_RADIUS_FRAC  = 0.020
        PROCESS_EVERY_N   = 3
        GLARE_PERCENTILE  = 99
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

            def _warp_iris(frame, cx, cy, tx, ty, radius, strength=1.0):
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
                return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

            def _reduce_glare(frame, ex, ey, ew, eh):
                if ew <= 0 or eh <= 0:
                    return frame
                roi = frame[ey:ey+eh, ex:ex+ew].copy()
                gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                thresh = np.percentile(gray_roi, GLARE_PERCENTILE)
                if thresh >= 250:
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
                h, w = eye_roi_gray.shape
                blurred = cv2.GaussianBlur(eye_roi_gray, (7, 7), 1.5)
                min_r = max(3, w // 8)
                max_r = max(min_r + 2, w // 3)
                circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1,
                    minDist=w // 2, param1=50, param2=15, minRadius=min_r, maxRadius=max_r)
                if circles is not None:
                    c = circles[0][0]
                    return float(c[0]), float(c[1])
                _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                M = cv2.moments(thresh)
                if M["m00"] > 0:
                    return M["m10"] / M["m00"], M["m01"] / M["m00"]
                return float(w // 2), float(h // 2)

            def _detect_face_and_eyes(gray):
                corrections = []
                faces_frontal = self.face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
                ) if self.face_cascade else []
                faces_profile = []
                if len(faces_frontal) == 0 and self.face_profile_casc:
                    faces_profile = self.face_profile_casc.detectMultiScale(
                        gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50))
                    if len(faces_profile) == 0:
                        faces_profile = self.face_profile_casc.detectMultiScale(
                            cv2.flip(gray, 1), scaleFactor=1.1, minNeighbors=4, minSize=(50, 50))
                is_profile = len(faces_frontal) == 0 and len(faces_profile) > 0
                all_faces  = list(faces_frontal) if len(faces_frontal) > 0 else list(faces_profile)
                if len(all_faces) == 0:
                    return corrections, 0.0
                fx, fy, fw, fh = max(all_faces, key=lambda r: r[2]*r[3])
                aspect = fw / max(fh, 1)
                if is_profile:
                    frontality = 0.0
                else:
                    frontality = float(np.clip((aspect - 0.55) / (0.80 - 0.55), 0.0, 1.0))
                if frontality < 0.05:
                    return corrections, frontality
                face_gray = gray[fy:fy+fh, fx:fx+fw]
                upper_h   = int(fh * 0.60)
                eye_casc = self.eye_glasses_casc or self.eye_cascade
                if eye_casc is None:
                    return corrections, frontality
                eyes = eye_casc.detectMultiScale(face_gray[:upper_h], scaleFactor=1.1,
                    minNeighbors=3, minSize=(18, 18))
                if len(eyes) == 0 and self.eye_glasses_casc and self.eye_cascade:
                    eyes = self.eye_cascade.detectMultiScale(face_gray[:upper_h],
                        scaleFactor=1.1, minNeighbors=3, minSize=(18, 18))
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

            # ── main processing loop → FFmpeg pipe ──────────────────────────
            frame_idx        = 0
            prev_corrections: list = []
            prev_frontality  = 1.0
            processed_count  = 0

            def _gen_frames():
                nonlocal frame_idx, prev_corrections, prev_frontality, processed_count
                cap2 = cv2.VideoCapture(str(input_path))
                while True:
                    ret, frame = cap2.read()
                    if not ret:
                        break
                    frame_idx += 1
                    corrected = frame.copy()
                    if frame_idx % PROCESS_EVERY_N == 0:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        gray = cv2.equalizeHist(gray)
                        prev_corrections, prev_frontality = _detect_face_and_eyes(gray)
                    for (ix, iy, tx, ty, abs_ex, abs_ey, ew, eh) in prev_corrections:
                        corrected = _reduce_glare(corrected, abs_ex, abs_ey, ew, eh)
                        corrected = _warp_iris(corrected, ix, iy, tx, ty,
                                               iris_radius, strength=prev_frontality)
                    yield corrected
                    processed_count += 1
                cap2.release()

            self._write_frames_via_ffmpeg(_gen_frames(), tmp_video, fps, width, height)
            logger.info(f"👁 Gaze correction: {processed_count} frames processed via FFmpeg pipe")

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
        logger.info(f"🎬 Applying Pattern Interrupts to {input_path.name}")
        try:
            import re
            probe_result = subprocess.run(
                [_get_ffmpeg_exe(), "-i", str(input_path)],
                capture_output=True, text=True, timeout=30,
            )
            stderr = probe_result.stderr
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
            dim_match = re.search(r'(\d{3,4})x(\d{3,4})', stderr)
            if dim_match:
                width = int(dim_match.group(1))
                height = int(dim_match.group(2))
            else:
                width, height = 1080, 1920
            fps = 30.0
            fps_match = re.search(r'(\d+\.?\d*)\s*fps', stderr)
            if fps_match:
                fps = float(fps_match.group(1))
            total_frames = int(duration * fps)
            INTERRUPT_INTERVAL = 3.5
            ZOOM_FRAMES = int(fps * 0.35)
            ZOOM_PEAK = 1.04
            interval_frames = int(fps * INTERRUPT_INTERVAL)
            half = ZOOM_FRAMES
            expr_zoom = (
                f"if(lt(mod(n\\,{interval_frames})\\,{half})"
                f"\\,1+{ZOOM_PEAK-1:.4f}*mod(n\\,{interval_frames})/{half}"
                f"\\,if(lt(mod(n\\,{interval_frames})\\,{2*half})"
                f"\\,{ZOOM_PEAK:.4f}-{ZOOM_PEAK-1:.4f}*(mod(n\\,{interval_frames})-{half})/{half}"
                f"\\,1))"
            )
            expr_x = f"(iw-iw/zoom)/2"
            expr_y = f"(ih-ih/zoom)/2"
            from ...gpu_utils import ffmpeg_codec_flags as _pi_gpu_flags
            _pi_enc = _pi_gpu_flags("high")
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vf", f"zoompan=z='{expr_zoom}':x='{expr_x}':y='{expr_y}':d=1:s={width}x{height}:fps={fps:.2f}",
            ] + _pi_enc + [
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ]
            logger.info(f"Pattern interrupts: running ffmpeg zoompan (interval={INTERRUPT_INTERVAL}s, peak={ZOOM_PEAK}x)")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
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

    async def blur_background(self, input_path: Path, output_path: Path, blur_radius: int = 35, process_every_n: int = 3) -> bool:
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
            seg = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
            prev_mask: np.ndarray | None = None
            frame_idx = 0

            def _gen_frames():
                nonlocal prev_mask, frame_idx
                cap2 = cv2.VideoCapture(str(input_path))
                while True:
                    ok, frame = cap2.read()
                    if not ok:
                        break
                    if frame_idx % process_every_n == 0:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        result = seg.process(rgb)
                        raw_mask = result.segmentation_mask
                        prev_mask = cv2.GaussianBlur(raw_mask, (21, 21), 0)
                    if prev_mask is not None:
                        blurred = cv2.GaussianBlur(frame, (blur_radius | 1, blur_radius | 1), 0)
                        mask3 = np.stack([prev_mask] * 3, axis=-1)
                        composited = (frame * mask3 + blurred * (1.0 - mask3)).astype(np.uint8)
                        yield composited
                    else:
                        yield frame
                    frame_idx += 1
                cap2.release()

            self._write_frames_via_ffmpeg(_gen_frames(), temp_v, fps, width, height)
            seg.close()
            logger.info("  Background blur pass done via FFmpeg pipe: %d frames", frame_idx)
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

    async def _ffmpeg_boxblur_fallback(self, input_path: Path, output_path: Path, blur_str: str) -> bool:
        from ...gpu_utils import ffmpeg_codec_flags as _bb_gpu_flags
        _bb_enc = _bb_gpu_flags("high")
        import asyncio as _asyncio
        proc = await _asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
            "-vf", f"boxblur={blur_str}",
            *_bb_enc,
            "-c:a", "copy", str(output_path),
            stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
        )
        _, _ = await _asyncio.wait_for(proc.communicate(), timeout=180.0)
        return proc.returncode == 0
