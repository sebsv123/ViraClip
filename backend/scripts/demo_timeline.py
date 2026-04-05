#!/usr/bin/env python3
"""
Demo script: Videofy Timeline Integration
Shows end-to-end timeline building and rendering.

Usage:
    python scripts/demo_timeline.py --video /path/to/video.mp4 [--enable-vision]
"""

import asyncio
import sys
import os
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.project_store import ProjectStore
from src.schemas_v2 import ClipTimeline
from src.services.timeline_builder import build_clip_timeline
from src.services.timeline_renderer import apply_timeline_to_clip

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def demo_timeline_building(video_path: Path, enable_vision: bool = False):
    """
    Demonstrate timeline building with a real video.
    
    Steps:
    1. Create project structure
    2. Mock Whisper words (in real usage, comes from faster-whisper)
    3. Mock AI segments (in real usage, comes from ai.py)
    4. Build timeline with Vision AI (optional)
    5. Save timeline.json
    6. Optionally render with camera movements
    """
    
    logger.info("=" * 80)
    logger.info("Videofy Timeline Demo")
    logger.info("=" * 80)
    
    # Step 1: Initialize project store
    logger.info("\n[Step 1] Initializing project store...")
    store = ProjectStore(base_dir="/app/projects")
    task_id = f"demo-{int(asyncio.get_event_loop().time())}"
    
    logger.info(f"Task ID: {task_id}")
    logger.info(f"Project path: {store.project_path(task_id)}")
    
    # Copy video to input folder
    input_dir = store.input_path(task_id)
    input_video = input_dir / "video.mp4"
    
    if not video_path.exists():
        logger.error(f"Video not found: {video_path}")
        return
    
    logger.info(f"Copying video to: {input_video}")
    import shutil
    shutil.copy(video_path, input_video)
    
    # Step 2: Mock Whisper word timings
    logger.info("\n[Step 2] Creating mock Whisper words...")
    logger.info("(In production, this comes from faster-whisper)")
    
    whisper_words = [
        {"word": "Check", "start": 0.0, "end": 0.3},
        {"word": "out", "start": 0.4, "end": 0.6},
        {"word": "this", "start": 0.7, "end": 0.9},
        {"word": "amazing", "start": 1.0, "end": 1.5},
        {"word": "hack", "start": 1.6, "end": 2.0},
        {"word": "that", "start": 2.1, "end": 2.3},
        {"word": "will", "start": 2.4, "end": 2.6},
        {"word": "blow", "start": 2.7, "end": 3.0},
        {"word": "your", "start": 3.1, "end": 3.3},
        {"word": "mind", "start": 3.4, "end": 3.8},
    ]
    
    logger.info(f"Created {len(whisper_words)} word timings")
    
    # Step 3: Mock AI segment analysis
    logger.info("\n[Step 3] Creating mock AI segment...")
    logger.info("(In production, this comes from ai.py virality analysis)")
    
    ai_segments = [
        {
            "text": "Check out this amazing hack that will blow your mind",
            "start_time": 0.0,
            "end_time": 3.8,
            "virality_score": 87.5,
            "hook_score": 24.0,
            "hook_type": "curiosity",
            "mood": "hype",
        }
    ]
    
    logger.info(f"Segment: virality={ai_segments[0]['virality_score']}, hook_type={ai_segments[0]['hook_type']}")
    
    # Step 4: Get OpenAI client for Vision AI (if enabled)
    openai_client = None
    if enable_vision:
        try:
            from openai import OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                openai_client = OpenAI(api_key=api_key)
                logger.info("\n[Step 4] OpenAI client initialized for Vision AI")
            else:
                logger.warning("\n[Step 4] OPENAI_API_KEY not found, skipping Vision AI")
                enable_vision = False
        except Exception as e:
            logger.warning(f"\n[Step 4] OpenAI client failed: {e}, skipping Vision AI")
            enable_vision = False
    else:
        logger.info("\n[Step 4] Vision AI disabled (use --enable-vision to enable)")
    
    # Step 5: Build timeline
    logger.info("\n[Step 5] Building ClipTimeline...")
    
    timeline = await build_clip_timeline(
        task_id=task_id,
        video_path=input_video,
        whisper_words=whisper_words,
        ai_segments=ai_segments,
        store=store,
        openai_client=openai_client,
        preset="tiktok_viral",
        skip_vision=not enable_vision,
    )
    
    logger.info("\n" + "=" * 80)
    logger.info("Timeline Built Successfully!")
    logger.info("=" * 80)
    logger.info(f"Clip ID: {timeline.clip_id}")
    logger.info(f"Preset: {timeline.preset}")
    logger.info(f"Segments: {len(timeline.segments)}")
    logger.info(f"Total Duration: {timeline.total_duration:.2f}s")
    
    # Print segment details
    logger.info("\nSegment Details:")
    for seg in timeline.segments:
        logger.info(f"  Segment {seg.id}:")
        logger.info(f"    - Time: {seg.start:.2f}s → {seg.end:.2f}s")
        logger.info(f"    - Virality: {seg.virality_score:.1f}")
        logger.info(f"    - Hook Type: {seg.hook_type}")
        logger.info(f"    - Camera Movement: {seg.camera_movement}")
        logger.info(f"    - Text Lines: {len(seg.texts)}")
        logger.info(f"    - Visual Assets: {len(seg.assets)}")
        if seg.assets:
            for asset in seg.assets:
                logger.info(f"      • {asset.type}: {asset.description or 'N/A'}")
    
    # Step 6: Check saved files
    logger.info("\n[Step 6] Checking saved files...")
    
    timeline_json = store.working_path(task_id) / "timeline.json"
    if timeline_json.exists():
        logger.info(f"✅ timeline.json saved ({timeline_json.stat().st_size} bytes)")
    
    if enable_vision:
        frames_dir = store.frames_path(task_id)
        if frames_dir.exists():
            frame_count = len(list(frames_dir.glob("*.jpg")))
            logger.info(f"✅ {frame_count} frames extracted")
        
        desc_json = store.analysis_path(task_id) / "descriptions.json"
        if desc_json.exists():
            logger.info(f"✅ descriptions.json saved")
        
        place_json = store.analysis_path(task_id) / "placements.json"
        if place_json.exists():
            logger.info(f"✅ placements.json saved")
    
    # Step 7: Optional rendering demo
    logger.info("\n[Step 7] Rendering with camera movements (optional)...")
    logger.info("To render with timeline, use:")
    logger.info(f"  await apply_timeline_to_clip(")
    logger.info(f"      timeline=timeline,")
    logger.info(f"      source_video=Path('{input_video}'),")
    logger.info(f"      output_path=Path('{store.output_path(task_id)}/timeline_render.mp4'),")
    logger.info(f"  )")
    
    logger.info("\n" + "=" * 80)
    logger.info("Demo Complete!")
    logger.info("=" * 80)
    logger.info(f"\nProject files saved to: {store.project_path(task_id)}")
    logger.info(f"  input/    → {input_video}")
    logger.info(f"  working/  → timeline.json, analysis/")
    logger.info(f"  output/   → (ready for rendering)")
    
    return timeline


async def demo_timeline_rendering(timeline: ClipTimeline, store: ProjectStore, task_id: str):
    """
    Demonstrate rendering a clip from timeline with camera movements.
    """
    logger.info("\n" + "=" * 80)
    logger.info("Timeline Rendering Demo")
    logger.info("=" * 80)
    
    input_video = store.input_path(task_id) / "video.mp4"
    output_video = store.output_path(task_id) / "timeline_render.mp4"
    
    logger.info(f"Source: {input_video}")
    logger.info(f"Output: {output_video}")
    logger.info(f"Camera movements: {[s.camera_movement for s in timeline.segments]}")
    
    try:
        result = await apply_timeline_to_clip(
            timeline=timeline,
            source_video=input_video,
            output_path=output_video,
        )
        
        if result.exists():
            logger.info(f"✅ Rendered successfully: {result} ({result.stat().st_size // 1024} KB)")
        else:
            logger.error("❌ Rendering failed: output not created")
    
    except Exception as e:
        logger.error(f"❌ Rendering error: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Demo Videofy Timeline Integration")
    parser.add_argument("--video", type=Path, help="Path to video file", required=True)
    parser.add_argument("--enable-vision", action="store_true", help="Enable Vision AI frame analysis")
    parser.add_argument("--render", action="store_true", help="Also render with camera movements")
    
    args = parser.parse_args()
    
    # Run demo
    async def main():
        timeline = await demo_timeline_building(args.video, args.enable_vision)
        
        if timeline and args.render:
            store = ProjectStore(base_dir="/app/projects")
            task_id = timeline.task_id
            await demo_timeline_rendering(timeline, store, task_id)
    
    asyncio.run(main())
