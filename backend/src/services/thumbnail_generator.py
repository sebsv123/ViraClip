"""
Thumbnail candidate generator — 3 types: expressive, sharp, representative.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

THUMB_CANDIDATES = int(os.getenv("THUMB_CANDIDATES", "3"))
THUMB_W = 1080
THUMB_H = 1920


async def _get_duration(path: Path) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", str(path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return float(json.loads(stdout)["format"]["duration"])
    except Exception:
        return 60.0


async def _extract_frame_as_thumbnail(
    clip_path: Path, offset: float, output_path: Path,
) -> bool:
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(offset),
            "-i", str(clip_path),
            "-frames:v", "1",
            "-vf", f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=decrease,"
                   f"pad={THUMB_W}:{THUMB_H}:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "2", str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return output_path.exists() and output_path.stat().st_size > 5000
    except Exception:
        return False


async def _find_best_thumbnail_frame(clip_path: Path, duration: float) -> float:
    """Smart frame selection: sample 10 frames, pick the best one.
    
    Criteria (in order of priority):
    1. Face detected with eyes open and mouth not wide open
    2. Frame is not blurry (Laplacian variance > 100)
    3. Fallback: frame at 30% of clip duration
    
    Returns the best offset in seconds.
    """
    import cv2
    import numpy as np
    
    sample_count = 10
    offsets = [duration * (i + 1) / (sample_count + 1) for i in range(sample_count)]
    best_offset = duration * 0.3
    best_score = -1.0
    best_face_detected = False
    
    # Pre-load OpenCV face cascade
    try:
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    except Exception:
        face_cascade = None
    
    for offset in offsets:
        tmp = Path(f"/tmp/viraclip_th_{os.getpid()}_{int(offset*100)}.jpg")
        try:
            # Extract frame
            cmd = [
                "ffmpeg", "-y", "-ss", str(offset),
                "-i", str(clip_path), "-frames:v", "1",
                "-vf", "scale=540:960", str(tmp),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            
            if not tmp.exists() or tmp.stat().st_size < 8000:
                continue
            
            # Read frame with OpenCV
            frame = cv2.imread(str(tmp))
            if frame is None:
                continue
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score = 0.0
            face_detected = False
            
            # 1. Face detection
            if face_cascade is not None:
                faces = face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50)
                )
                if len(faces) > 0:
                    face_detected = True
                    score += 50.0
                    
                    # For each face, check eye region and mouth
                    for (fx, fy, fw, fh) in faces:
                        # Eye region: top 30-50% of face
                        eye_region = gray[fy:fy + int(fh * 0.5), fx:fx + fw]
                        if eye_region.size > 0:
                            eye_mean = np.mean(eye_region)
                            # Eyes open = lighter eye region (not too dark/closed)
                            if eye_mean > 60:
                                score += 25.0
                        
                        # Mouth region: bottom 20-40% of face
                        mouth_region = gray[fy + int(fh * 0.6):fy + int(fh * 0.85), fx:fx + fw]
                        if mouth_region.size > 0:
                            mouth_std = np.std(mouth_region)
                            # Wide open mouth = high contrast in mouth region (teeth vs dark)
                            if mouth_std < 40:
                                score += 15.0  # Closed/natural mouth
            
            # 2. Blur detection (Laplacian variance)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            if laplacian_var > 100:
                score += 20.0
            elif laplacian_var > 50:
                score += 10.0
            
            # Prefer face-detected frames strongly
            if face_detected and not best_face_detected:
                best_offset = offset
                best_score = score
                best_face_detected = True
            elif face_detected == best_face_detected and score > best_score:
                best_offset = offset
                best_score = score
                
        except Exception:
            pass
        finally:
            tmp.unlink(missing_ok=True)
    
    logger.info(
        "[THUMBNAIL] Selected frame at t=%.1fs (face detected: %s, score=%.1f)",
        best_offset, best_face_detected, best_score,
    )
    return best_offset


async def generate_thumbnail_candidates(
    clip_path: Path,
    clip_id: str,
    output_dir: Path,
) -> list[dict]:
    """Generate 3 thumbnail candidates: expressive, sharp, representative."""
    duration = await _get_duration(clip_path)
    if duration < 0.5:
        return []

    best_offset = await _find_best_thumbnail_frame(clip_path, duration)
    representative_offset = duration * 0.4

    candidates = [
        ("best", best_offset, "Mejor frame"),
        ("representative", representative_offset, "Representativo"),
    ]

    results = []
    for ctype, offset, label in candidates:
        thumb_path = output_dir / f"{clip_id}_thumb_{ctype}.jpg"
        ok = await _extract_frame_as_thumbnail(clip_path, offset, thumb_path)
        if ok:
            results.append({
                "type": ctype,
                "label": label,
                "path": str(thumb_path),
                "offset_s": round(offset, 2),
                "url": f"/clips/{clip_id}/thumbnails/{ctype}",
            })

    logger.info("[Thumb] Generated %d candidates for clip %s", len(results), clip_id)
    return results
