"""
Vision AI frame analysis and asset placement.
Adapted from schibsted/videofy_minimal/api/asset_analysis.py
"""

import base64
import json
import subprocess
import logging
from pathlib import Path
from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


class DescriptionResult(BaseModel):
    description: str


class PlacementResult(BaseModel):
    asset_ids: list[str]


def extract_frames_from_clip(
    video_path: Path,
    output_dir: Path,
    clip_id: str,
    n_frames: int = 6,
) -> list[dict]:
    """
    Extract N frames from clip for visual analysis.
    Uses ffprobe for duration, then ffmpeg for extraction.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        duration = float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"ffprobe failed for {video_path}: {e}, using default duration")
        duration = 10.0

    step = duration / n_frames
    frames = []
    for i in range(n_frames):
        t = round(i * step, 3)
        frame_path = output_dir / f"{clip_id}-frame-{i+1:03}.jpg"
        cmd = [
            _get_ffmpeg_exe(), "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2", str(frame_path)
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=30)
            if frame_path.exists() and frame_path.stat().st_size > 0:
                frames.append({
                    "path": str(frame_path),
                    "time_seconds": t,
                    "id": f"f{i+1:03}"
                })
        except Exception as e:
            logger.warning(f"Frame extraction failed at {t}s: {e}")
            continue
    
    return frames


def describe_frame(
    image_path: Path,
    client: OpenAI,
    model: str = "gpt-4o-mini"
) -> str:
    """
    Send frame to GPT-4o Vision and get textual description.
    """
    suffix = image_path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    
    try:
        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except Exception as e:
        logger.warning(f"Failed to read image {image_path}: {e}")
        return ""
    
    data_url = f"data:{mime};base64,{b64}"
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Describe concisely what you see in this video frame. Focus on the main subject, action, and visual mood. Max 2 sentences."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url}
                        }
                    ]
                }
            ],
            max_tokens=120,
            temperature=0.2,
        )
        
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content.strip()
        return ""
    
    except Exception as e:
        logger.warning(f"Frame description failed: {e}")
        return ""


def assign_frames_to_segments(
    segments_text: list[str],
    frame_descriptions: list[dict],
    client: OpenAI,
    model: str = "gpt-4o-mini",
) -> list[str]:
    """
    AI decides which frame visual matches each text segment best.
    Returns list of frame IDs, one per segment.
    Fallback: cyclic assignment if AI fails.
    """
    candidate_ids = [f["id"] for f in frame_descriptions]
    if not candidate_ids:
        return []
    
    if not segments_text:
        return []
    
    try:
        prompt = """Given script segments and visual frame descriptions, assign the best matching frame to each segment.
Return exactly one frame_id per segment, in order. Only use the provided frame IDs.
Respond with a JSON object: {"asset_ids": ["f001", "f002", ...]}"""
        
        payload = {
            "segments": [{"id": i+1, "text": t} for i, t in enumerate(segments_text)],
            "frames": frame_descriptions,
        }
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.2,
        )
        
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content.strip()
            result = json.loads(content)
            ids = result.get("asset_ids", [])
            valid = set(candidate_ids)
            
            if len(ids) == len(segments_text) and all(i in valid for i in ids):
                return ids
        
    except Exception as e:
        logger.warning(f"Frame placement failed, using fallback: {e}")
    
    # Fallback: cyclic assignment
    return [candidate_ids[i % len(candidate_ids)] for i in range(len(segments_text))]
