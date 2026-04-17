"""
Gate 0 — Pre-flight checks before expensive pipeline operations.
Validates video file before Whisper transcription is called.
"""
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_DURATION_SEC = 10
MAX_DURATION_SEC = 3600  # 1 hora
MIN_FILE_SIZE_MB = 0.1
MAX_FILE_SIZE_MB = 4096  # 4GB


def _get_video_info(video_path: str) -> dict:
    """Extract duration and audio presence via ffprobe."""
    try:
        import json
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", video_path
        ], capture_output=True, text=True, timeout=15)
        
        if result.returncode != 0:
            return {"error": "ffprobe failed"}
        
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        streams = data.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        has_video = any(s.get("codec_type") == "video" for s in streams)
        
        return {
            "duration": duration,
            "has_audio": has_audio,
            "has_video": has_video,
        }
    except Exception as e:
        return {"error": str(e)}


def check_preflight(video_path: str) -> dict:
    """
    Run pre-flight checks on video file.
    Returns dict with passed, reason, recommendation, summary.
    """
    path = Path(video_path)
    
    # Check file exists
    if not path.exists():
        return {
            "passed": False,
            "reason": f"Video file not found: {video_path}",
            "recommendation": "Check the file path and try again",
            "summary": "file not found",
        }
    
    # Check file size
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb < MIN_FILE_SIZE_MB:
        return {
            "passed": False,
            "reason": f"File too small ({size_mb:.1f}MB) — likely corrupted",
            "recommendation": "Re-upload the video file",
            "summary": f"file too small ({size_mb:.1f}MB)",
        }
    if size_mb > MAX_FILE_SIZE_MB:
        return {
            "passed": False,
            "reason": f"File too large ({size_mb:.0f}MB > {MAX_FILE_SIZE_MB}MB limit)",
            "recommendation": "Compress or trim the video before processing",
            "summary": f"file too large ({size_mb:.0f}MB)",
        }
    
    # Check video info via ffprobe
    info = _get_video_info(video_path)
    if "error" in info:
        logger.warning(f"[Gate 0] ffprobe error: {info['error']} — skipping media checks")
    else:
        # Check has video stream
        if not info.get("has_video"):
            return {
                "passed": False,
                "reason": "No video stream detected",
                "recommendation": "Ensure the file is a valid video",
                "summary": "no video stream",
            }
        
        # Check has audio stream
        if not info.get("has_audio"):
            return {
                "passed": False,
                "reason": "No audio stream detected — ViraClip requires audio for transcription",
                "recommendation": "Use a video with spoken audio",
                "summary": "no audio stream",
            }
        
        # Check duration
        duration = info.get("duration", 0)
        if duration < MIN_DURATION_SEC:
            return {
                "passed": False,
                "reason": f"Video too short ({duration:.1f}s < {MIN_DURATION_SEC}s minimum)",
                "recommendation": "Use a video of at least 10 seconds",
                "summary": f"too short ({duration:.1f}s)",
            }
        if duration > MAX_DURATION_SEC:
            return {
                "passed": False,
                "reason": f"Video too long ({duration/60:.0f}min > {MAX_DURATION_SEC/60:.0f}min limit)",
                "recommendation": "Trim the video to under 60 minutes",
                "summary": f"too long ({duration/60:.0f}min)",
            }
    
    size_summary = f"{size_mb:.0f}MB"
    dur_summary = f"{info.get('duration', 0):.0f}s" if "error" not in info else "unknown duration"
    
    return {
        "passed": True,
        "reason": "All pre-flight checks passed",
        "recommendation": "",
        "summary": f"{size_summary}, {dur_summary}, audio ✅",
    }
