"""
Timeline renderer - consumes ClipTimeline and applies camera movements + captions.
Connects the Videofy data contract to FFmpeg rendering.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from ..schemas_v2 import ClipTimeline, VALID_CAMERA_MOVEMENTS

logger = logging.getLogger(__name__)


def _sec_to_ass(seconds: float) -> str:
    """Convert seconds to ASS subtitle format: H:MM:SS.CC"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_subtitles(timeline: ClipTimeline) -> str:
    """
    Generate ASS subtitle file from timeline TextLines.
    Synchronized word-level captions with TikTok styling.
    """
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,TikTokSans-Bold,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,0,2,10,10,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    
    for seg in timeline.segments:
        for tl in seg.texts:
            start = _sec_to_ass(tl.start)
            end = _sec_to_ass(tl.end)
            text = (tl.display_text or tl.text).upper()
            # Escape ASS special chars
            text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    
    return "\n".join(lines)


def build_camera_filter(timeline: ClipTimeline, fps: int = 25) -> Optional[str]:
    """
    Build FFmpeg zoompan filter for camera movements per segment.
    
    Returns filter string or None if no movements to apply.
    """
    movement_filters = {
        "zoom-in": lambda dur: f"zoompan=z='min(zoom+0.0015,1.5)':d={int(dur*fps)}:fps={fps}",
        "zoom-out": lambda dur: f"zoompan=z='if(lte(zoom,1.0),1.5,max(1.0,zoom-0.002))':d={int(dur*fps)}:fps={fps}",
        "pan-right": lambda dur: f"zoompan=z=1.2:x='iw/2-(iw/zoom/2)+t*8':d={int(dur*fps)}:fps={fps}",
        "pan-left": lambda dur: f"zoompan=z=1.2:x='iw/2-(iw/zoom/2)-t*8':d={int(dur*fps)}:fps={fps}",
        "pan-up": lambda dur: f"zoompan=z=1.2:y='ih/2-(ih/zoom/2)-t*8':d={int(dur*fps)}:fps={fps}",
        "pan-down": lambda dur: f"zoompan=z=1.2:y='ih/2-(ih/zoom/2)+t*8':d={int(dur*fps)}:fps={fps}",
    }
    
    filter_parts = []
    for seg in timeline.segments:
        if seg.camera_movement in movement_filters and seg.camera_movement != "none":
            duration = seg.end - seg.start
            filter_func = movement_filters[seg.camera_movement]
            filter_parts.append(filter_func(duration))
    
    if not filter_parts:
        return None
    
    # For now, return first segment's movement (full implementation would need trim+concat)
    return filter_parts[0] if filter_parts else None


async def apply_timeline_to_clip(
    timeline: ClipTimeline,
    source_video: Path,
    output_path: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """
    Render ClipTimeline to video with camera movements and captions.
    
    Args:
        timeline: ClipTimeline with segments, texts, camera movements
        source_video: Original video file
        output_path: Where to save rendered output
        ffmpeg_bin: FFmpeg binary path
    
    Returns:
        Path to rendered video
    """
    
    # Generate ASS subtitle file
    ass_content = build_ass_subtitles(timeline)
    ass_path = output_path.parent / f"{output_path.stem}.ass"
    ass_path.write_text(ass_content, encoding="utf-8")
    
    # Build camera movement filter
    camera_filter = build_camera_filter(timeline)
    
    # Build FFmpeg command
    cmd = [ffmpeg_bin, "-y", "-i", str(source_video)]
    
    # Video filters
    vf_parts = []
    
    # Add camera movement if present
    if camera_filter:
        vf_parts.append(camera_filter)
    
    # Add subtitles
    ass_path_escaped = str(ass_path).replace('\\', '/').replace(':', '\\:')
    vf_parts.append(f"ass={ass_path_escaped}")
    
    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])
    
    # Audio copy (preserve original)
    cmd.extend(["-c:a", "copy"])
    
    # Output
    cmd.append(str(output_path))
    
    try:
        logger.info(f"[TimelineRender] Rendering {timeline.clip_id} with {len(timeline.segments)} segments")
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)
        
        if proc.returncode == 0 and output_path.exists():
            logger.info(f"[TimelineRender] Success: {output_path} ({output_path.stat().st_size // 1024} KB)")
            return output_path
        else:
            error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "Unknown error"
            logger.error(f"[TimelineRender] FFmpeg failed: {error_msg[:500]}")
            raise RuntimeError(f"FFmpeg rendering failed: return code {proc.returncode}")
    
    except asyncio.TimeoutError:
        logger.error(f"[TimelineRender] Timeout rendering {timeline.clip_id}")
        raise
    
    except Exception as e:
        logger.error(f"[TimelineRender] Render failed: {e}", exc_info=True)
        raise
    
    finally:
        # Cleanup temporary ASS file
        ass_path.unlink(missing_ok=True)


def get_segment_at_time(timeline: ClipTimeline, time: float) -> Optional[int]:
    """Get segment index at given timestamp."""
    for i, seg in enumerate(timeline.segments):
        if seg.start <= time < seg.end:
            return i
    return None


def extract_segment_clip(
    timeline: ClipTimeline,
    segment_id: int,
    source_video: Path,
    output_path: Path,
) -> Path:
    """
    Extract a single segment from timeline as standalone clip.
    Useful for creating multiple clips from one timeline.
    """
    if segment_id >= len(timeline.segments):
        raise ValueError(f"Segment {segment_id} not found in timeline")
    
    seg = timeline.segments[segment_id]
    
    # Use ffmpeg to extract segment
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seg.start:.3f}",
        "-i", str(source_video),
        "-t", f"{seg.end - seg.start:.3f}",
        "-c", "copy",
        str(output_path),
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        return output_path
    except Exception as e:
        logger.error(f"[SegmentExtract] Failed to extract segment {segment_id}: {e}")
        raise
