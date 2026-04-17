"""
Timeline builder - bridges Whisper + AI analysis → ClipTimeline.
This is the missing link between ai.py and video_utils.py.
"""

import logging
from pathlib import Path
from typing import Optional

from ..schemas_v2 import (
    Segment, TextLine, SegmentAsset, ClipTimeline,
    DEFAULT_CAMERA_MOVEMENTS
)
from ..asset_analysis import (
    extract_frames_from_clip,
    describe_frame,
    assign_frames_to_segments
)
from ..project_store import ProjectStore

logger = logging.getLogger(__name__)


async def build_clip_timeline(
    task_id: str,
    video_path: Path,
    whisper_words: list[dict],
    ai_segments: list[dict],
    store: ProjectStore,
    openai_client,
    preset: str = "default",
    skip_vision: bool = False,
) -> ClipTimeline:
    """
    Convert Whisper + ai.py outputs into structured ClipTimeline.
    
    This is the bridge that was missing between analysis and render.
    
    Args:
        task_id: Task identifier
        video_path: Path to source video
        whisper_words: Faster-whisper output with word timestamps
        ai_segments: ai.py output with virality_score, hook_type, etc.
        store: ProjectStore for persistent state
        openai_client: OpenAI client for Vision AI
        preset: Render preset name
        skip_vision: Skip Vision AI frame analysis (faster, no visual context)
    
    Returns:
        ClipTimeline with segments, text lines, and assets
    """
    
    # ── Step 1: Extract frames for visual analysis ────────────────────────
    described_frames = []
    
    if not skip_vision and openai_client:
        try:
            frames_dir = store.frames_path(task_id)
            frames = extract_frames_from_clip(
                video_path, frames_dir, task_id, n_frames=8
            )
            
            if frames:
                logger.info(f"[Timeline] Extracted {len(frames)} frames from {video_path.name}")
                
                # ── Step 2: Describe each frame with Vision AI ────────────
                for f in frames:
                    try:
                        frame_path = Path(f["path"])
                        desc = describe_frame(frame_path, openai_client)
                        described_frames.append({
                            "id": f["id"],
                            "path": f["path"],
                            "time_seconds": f["time_seconds"],
                            "description": desc or f"Frame at {f['time_seconds']:.1f}s",
                        })
                    except Exception as e:
                        logger.warning(f"Frame description failed for {f['id']}: {e}")
                
                if described_frames:
                    store.save_json(
                        task_id,
                        "descriptions.json",
                        {"frames": described_frames},
                        folder="analysis"
                    )
                    logger.info(f"[Timeline] Described {len(described_frames)} frames")
        
        except Exception as e:
            logger.warning(f"[Timeline] Frame analysis failed: {e}, continuing without")
    
    # ── Step 3: Assign frames to segments ──────────────────────────────────
    assigned_frame_ids = []
    frame_by_id = {f["id"]: f for f in described_frames}
    
    if described_frames and openai_client and not skip_vision:
        try:
            segment_texts = [seg.get("text", "") for seg in ai_segments]
            assigned_frame_ids = assign_frames_to_segments(
                segment_texts, described_frames, openai_client
            )
            
            if assigned_frame_ids:
                store.save_json(
                    task_id,
                    "placements.json",
                    {"assignments": list(zip(segment_texts, assigned_frame_ids))},
                    folder="analysis"
                )
                logger.info(f"[Timeline] Assigned {len(assigned_frame_ids)} frames to segments")
        
        except Exception as e:
            logger.warning(f"[Timeline] Frame assignment failed: {e}")
    
    # ── Step 4: Build segments with TextLines from Whisper ────────────────
    segments = []
    
    for i, ai_seg in enumerate(ai_segments):
        seg_start = ai_seg.get("start_time", 0.0)
        seg_end = ai_seg.get("end_time", seg_start + 3.0)
        
        # Filter Whisper words that belong to this segment
        text_lines = []
        line_id = 0
        current_chunk = []
        current_start = None
        
        for word in whisper_words:
            w_start = word.get("start", 0.0)
            w_end = word.get("end", 0.0)
            w_text = word.get("word", "").strip()
            
            if seg_start <= w_start < seg_end and w_text:
                if current_start is None:
                    current_start = w_start
                current_chunk.append(w_text)
                
                # Group words into chunks of ~4 words (for caption timing)
                if len(current_chunk) >= 4:
                    text_lines.append(TextLine(
                        line_id=line_id,
                        text=" ".join(current_chunk),
                        start=current_start,
                        end=w_end,
                    ))
                    line_id += 1
                    current_chunk = []
                    current_start = None
        
        # Last chunk
        if current_chunk and current_start is not None:
            text_lines.append(TextLine(
                line_id=line_id,
                text=" ".join(current_chunk),
                start=current_start,
                end=seg_end,
            ))
        
        # If no text lines, create one from segment text
        if not text_lines and ai_seg.get("text"):
            text_lines.append(TextLine(
                line_id=0,
                text=ai_seg["text"],
                start=seg_start,
                end=seg_end,
            ))
        
        # Assign frame visual to segment
        assets = []
        if i < len(assigned_frame_ids):
            assigned_id = assigned_frame_ids[i]
            frame_data = frame_by_id.get(assigned_id, {})
            if frame_data and frame_data.get("path"):
                assets.append(SegmentAsset(
                    type="frame",
                    path=frame_data["path"],
                    description=frame_data.get("description"),
                ))
        
        # Cyclic camera movement (Videofy pattern)
        camera_movement = DEFAULT_CAMERA_MOVEMENTS[i % len(DEFAULT_CAMERA_MOVEMENTS)]
        
        segments.append(Segment(
            id=i,
            virality_score=ai_seg.get("virality_score", 0.0),
            hook_score=ai_seg.get("hook_score", 0.0),
            hook_type=ai_seg.get("hook_type", "none"),
            mood=ai_seg.get("mood", "neutral"),
            camera_movement=camera_movement,
            style="bottom",
            texts=text_lines,
            assets=assets,
            start=seg_start,
            end=seg_end,
        ))
    
    timeline = ClipTimeline(
        clip_id=f"{task_id}-timeline",
        task_id=task_id,
        source_url="",
        preset=preset,
        segments=segments,
        total_duration=sum(s.end - s.start for s in segments),
    )
    
    # Save timeline for renderer to consume
    store.save_json(task_id, "timeline.json", timeline.model_dump())
    logger.info(f"[Timeline] Built timeline with {len(segments)} segments, duration={timeline.total_duration:.1f}s")
    
    return timeline
