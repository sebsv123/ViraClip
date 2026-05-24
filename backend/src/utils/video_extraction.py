"""
Fast video segment extraction using ffmpeg.

Extracts temporal segments from source video using stream copy (no re-encoding).
This is 50-100x faster than MoviePy for simple extraction.

Usage:
    segments = [
        {"start_time": "00:15", "end_time": "00:45"},
        {"start_time": "01:20", "end_time": "02:00"}
    ]
    temp_files = await extract_segments_fast(video_path, segments, output_dir)
    # temp_files[0] contains frames from 00:15 to 00:45 (30s clip)
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..video_processing.utils import parse_timestamp_to_seconds

logger = logging.getLogger(__name__)


async def extract_segments_fast(
    video_path: Path,
    segments: List[Dict[str, Any]],
    output_dir: Path,
    task_id: str = "unknown"
) -> List[Optional[Path]]:
    """
    Extract multiple video segments using ffmpeg with stream copy (no re-encoding).
    
    This is the critical optimization: instead of re-decoding the entire video
    for each clip, we extract temporal segments once, then render from those.
    
    Args:
        video_path: Source video file
        segments: List of dicts with start_time, end_time (MM:SS format)
        output_dir: Where to save extracted segments
        task_id: For logging/debugging
        
    Returns:
        List of Path objects to extracted segment files (None if extraction failed)
        
    Performance:
        - ~0.5-2s per segment (vs 30-180s with MoviePy re-decode)
        - Uses -c copy (stream copy, no transcode)
        - Async/concurrent extraction of all segments
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Launch all extractions concurrently (ffmpeg is fast with -c copy)
    tasks = []
    for i, segment in enumerate(segments):
        task = _extract_single_segment(
            video_path=video_path,
            segment=segment,
            segment_index=i,
            output_dir=output_dir,
            task_id=task_id
        )
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert exceptions to None
    extracted_paths = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Segment {i+1} extraction failed: {result}")
            extracted_paths.append(None)
        else:
            extracted_paths.append(result)
    
    successful = sum(1 for p in extracted_paths if p is not None)
    logger.info(f"Extracted {successful}/{len(segments)} segments for task {task_id}")
    
    return extracted_paths


async def _extract_single_segment(
    video_path: Path,
    segment: Dict[str, Any],
    segment_index: int,
    output_dir: Path,
    task_id: str
) -> Optional[Path]:
    """
    Extract one segment using ffmpeg -ss -t -c copy.
    
    Returns:
        Path to extracted segment, or None if failed
    """
    try:
        start_seconds = parse_timestamp_to_seconds(segment["start_time"])
        end_seconds = parse_timestamp_to_seconds(segment["end_time"])
        duration = end_seconds - start_seconds
        
        if duration <= 0:
            logger.warning(f"Invalid segment {segment_index}: duration={duration}s")
            return None
        
        # Output filename: segment_{index}_{start}-{end}.mp4
        start_str = segment["start_time"].replace(":", "")
        end_str = segment["end_time"].replace(":", "")
        output_file = output_dir / f"segment_{segment_index}_{start_str}-{end_str}.mp4"
        
        # ffmpeg command:
        # -ss: seek to start position (before input for fast seek)
        # -i: input file
        # -t: duration to extract
        # Re-encode with NVENC for frame-accurate cuts (was -c copy which
        # caused truncation because -ss fast seek + -c copy can only cut at
        # keyframes, producing unpredictable durations).
        cmd = [
            "ffmpeg",
            "-y",  # overwrite without asking
            "-ss", str(start_seconds),
            "-i", str(video_path),
            "-t", str(duration),
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "hq",
            "-b:v", "8M",
            "-c:a", "aac",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            str(output_file)
        ]
        
        # Run in subprocess (non-blocking)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            stderr_str = stderr.decode('utf-8', errors='ignore')[-500:]
            logger.error(
                f"ffmpeg extraction failed for segment {segment_index}: "
                f"{stderr_str}"
            )
            return None
        
        if not output_file.exists():
            logger.error(f"Extraction completed but file not found: {output_file}")
            return None
        
        file_size_mb = output_file.stat().st_size / (1024 * 1024)
        
        # Verificar duración real del segmento extraído con ffprobe
        import json as _json
        _probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(output_file)],
            capture_output=True, text=True, timeout=10
        )
        _probe_data = _json.loads(_probe.stdout)
        _real_duration = float(_probe_data.get("format", {}).get("duration", 0))
        logger.info(
            f"Segment extracted: requested={duration:.1f}s "
            f"real={_real_duration:.1f}s path={output_file.name}"
        )
        if _real_duration < duration * 0.8:
            logger.warning(
                f"SEGMENT TRUNCATED: {_real_duration:.1f}s vs "
                f"{duration:.1f}s requested — re-extracting with libx264 fallback"
            )
            # Fallback: re-extract with libx264 (CPU) for frame-accurate cut
            _fallback_cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_seconds),
                "-i", str(video_path),
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "128k",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(output_file)
            ]
            _fb_proc = await asyncio.create_subprocess_exec(
                *_fallback_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await _fb_proc.communicate()
            if _fb_proc.returncode == 0:
                _fb_size = output_file.stat().st_size / (1024 * 1024)
                logger.info(f"  Fallback re-extract OK: {_fb_size:.1f}MB")
        
        logger.info(
            f"✓ Extracted segment {segment_index}: "
            f"{duration:.1f}s → {file_size_mb:.1f}MB ({output_file.name})"
        )
        if duration < 40.0:
            logger.warning(
                f"⚠️ Segment {segment_index} is only {duration:.1f}s "
                f"(expected ≥40s) — video may be shorter than target duration"
            )
        
        return output_file
        
    except Exception as e:
        logger.error(f"Exception extracting segment {segment_index}: {e}", exc_info=True)
        return None


def cleanup_extracted_segments(segment_paths: List[Optional[Path]]) -> None:
    """
    Clean up temporary segment files after rendering is complete.
    
    Call this after all clips have been rendered from the extracted segments.
    """
    deleted = 0
    for path in segment_paths:
        if path and path.exists():
            try:
                path.unlink()
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to cleanup {path}: {e}")
    
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} temporary segment files")
