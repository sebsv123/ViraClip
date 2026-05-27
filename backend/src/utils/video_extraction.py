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


def _ffmpeg_codec_flags() -> List[str]:
    from ..gpu_utils import ffmpeg_codec_flags

    return ffmpeg_codec_flags("high")


def _libx264_flags() -> List[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


async def _run_ffmpeg_with_nvenc_fallback(
    cmd: List[str],
    fallback_cmd: List[str],
):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0 or "h264_nvenc" not in cmd:
        return proc.returncode, stdout, stderr

    logger.warning("[gpu] NVENC failed; retrying with libx264")
    logger.debug("[extract] NVENC stderr: %s", stderr.decode("utf-8", errors="ignore")[-500:])
    proc = await asyncio.create_subprocess_exec(
        *fallback_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    returncode_stdout, returncode_stderr = await proc.communicate()
    return proc.returncode, returncode_stdout, returncode_stderr


async def extract_segments_fast(
    video_path: Path,
    segments: List[Dict[str, Any]],
    output_dir: Path,
    task_id: str = "unknown",
    exact_seek: bool = False,
) -> List[Optional[Path]]:
    """
    Extract multiple video segments using ffmpeg.
    
    When exact_seek=False (default): uses stream copy (-c copy) with -ss before -i
    for maximum speed (~0.5-2s per segment).  The extracted segment may start at
    the nearest keyframe before the requested start_time, causing a small offset.
    
    When exact_seek=True: uses re-encode with -ss after -i for frame-accurate
    seeking.  This is slower (~30-180s per segment) but guarantees the segment
    starts exactly at start_time — critical for subtitle sync.
    
    Args:
        video_path: Source video file
        segments: List of dicts with start_time, end_time (MM:SS format)
        output_dir: Where to save extracted segments
        task_id: For logging/debugging
        exact_seek: If True, use precise re-encode instead of fast stream copy
        
    Returns:
        List of Path objects to extracted segment files (None if extraction failed)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Launch all extractions concurrently
    tasks = []
    for i, segment in enumerate(segments):
        task = _extract_single_segment(
            video_path=video_path,
            segment=segment,
            segment_index=i,
            output_dir=output_dir,
            task_id=task_id,
            exact_seek=exact_seek,
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
    mode = "exact" if exact_seek else "fast"
    logger.info(f"Extracted {successful}/{len(segments)} segments ({mode}) for task {task_id}")
    
    return extracted_paths


async def _extract_single_segment(
    video_path: Path,
    segment: Dict[str, Any],
    segment_index: int,
    output_dir: Path,
    task_id: str,
    exact_seek: bool = False,
) -> Optional[Path]:
    """
    Extract one segment using ffmpeg.
    
    When exact_seek=False (default): fast path using -ss before -i + -c copy.
    May start at the nearest keyframe before start_time (imprecise).
    
    When exact_seek=True: precise path using -i before -ss + re-encode.
    Guarantees frame-accurate start at start_time — needed for subtitle sync.
    
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
        
        if exact_seek:
            # ── PRECISE PATH: re-encode with -ss AFTER -i for frame accuracy ──
            # This is slower but guarantees the segment starts exactly at
            # start_seconds — critical for subtitle word-timestamp sync.
            logger.info(
                "[extract] exact_seek=True using precise re-encode for subtitles "
                "(segment %d, %.1fs-%.1fs)",
                segment_index, start_seconds, end_seconds,
            )
            _codec_flags = _ffmpeg_codec_flags()
            cmd = [
                "ffmpeg",
                "-y",
                "-i", str(video_path),          # -i BEFORE -ss for precise seek
                "-ss", str(start_seconds),
                "-t", str(duration),
                "-map", "0:v:0",                # video stream
                "-map", "0:a?",                  # audio if present (optional)
                *_codec_flags,
                "-c:a", "aac",
                "-b:a", "160k",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(output_file),
            ]
            fallback_cmd = [
                "ffmpeg",
                "-y",
                "-i", str(video_path),
                "-ss", str(start_seconds),
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a?",
                *_libx264_flags(),
                "-c:a", "aac",
                "-b:a", "160k",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(output_file),
            ]
        else:
            # ── FAST PATH: stream copy with -ss before -i ──
            # Fast seek to nearest keyframe; may have small offset.
            logger.info(
                "[extract] exact_seek=False using fast stream copy "
                "(segment %d, %.1fs-%.1fs)",
                segment_index, start_seconds, end_seconds,
            )
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start_seconds),
                "-i", str(video_path),
                "-t", str(duration),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(output_file),
            ]
            fallback_cmd = cmd
        
        # Run in subprocess (non-blocking)
        returncode, stdout, stderr = await _run_ffmpeg_with_nvenc_fallback(
            cmd,
            fallback_cmd,
        )

        if returncode != 0:
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
        logger.info(
            f"✓ Extracted segment {segment_index}: "
            f"{duration:.1f}s → {file_size_mb:.1f}MB ({output_file.name})"
        )
        
        # ── Best-effort ffprobe: log actual start_time of extracted segment ──
        try:
            _probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(output_file)],
                capture_output=True, timeout=10,
            )
            if _probe.returncode == 0:
                import json as _json
                _info = _json.loads(_probe.stdout)
                _fmt_start = _info.get("format", {}).get("start_time", "?")
                _v_start = "?"
                _a_start = "?"
                for _s in _info.get("streams", []):
                    _st = _s.get("start_time", "?")
                    if _s.get("codec_type") == "video" and _v_start == "?":
                        _v_start = _st
                    elif _s.get("codec_type") == "audio" and _a_start == "?":
                        _a_start = _st
                logger.info(
                    "[extract] ffprobe start_time after extract: "
                    "format=%s video=%s audio=%s",
                    _fmt_start, _v_start, _a_start,
                )
        except Exception as _probe_e:
            logger.debug("[extract] ffprobe best-effort failed: %s", _probe_e)
        
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
