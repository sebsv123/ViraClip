"""
Standalone Video Processor - No import issues
Processes YouTube videos and generates viral clips.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add src to path before any imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

print(f"Python path: {sys.path}")
print(f"Current directory: {os.getcwd()}")

# Test videos from user
TEST_VIDEOS = [
    "https://youtu.be/DHSigj8uPnE",
    "https://youtu.be/3wgwaxIfUJQ"
]

async def process_video_real(url: str, task_id: str):
    """Process a real YouTube video."""
    print(f"\n{'='*60}")
    print(f"Processing: {url}")
    print(f"Task ID: {task_id}")
    print(f"{'='*60}\n")
    
    try:
        # Import here after path setup
        from src.services.video_service import VideoService
        from src.config import Config
        
        config = Config()
        print(f"Output directory: {config.output_dir}")
        print(f"Temp directory: {config.temp_dir}")
        
        # Ensure directories exist
        output_path = Path(config.output_dir)
        temp_path = Path(config.temp_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        temp_path.mkdir(parents=True, exist_ok=True)
        
        print(f"\n[1/5] Downloading video...")
        video_path = await VideoService.download_video(url, task_id=task_id)
        
        if not video_path or not video_path.exists():
            print(f"ERROR: Download failed")
            return None
            
        print(f"Downloaded: {video_path}")
        print(f"Size: {video_path.stat().st_size / (1024*1024):.2f} MB")
        
        print(f"\n[2/5] Generating transcript...")
        transcript = await VideoService.generate_transcript(video_path, processing_mode="fast")
        word_count = len(transcript.split()) if transcript else 0
        print(f"Transcript: {word_count} words")
        print(f"Preview: {transcript[:200]}...")
        
        print(f"\n[3/5] Analyzing content with AI...")
        from src.video_processing.youtube_handler import async_get_youtube_video_info
        video_info = await async_get_youtube_video_info(url, task_id=task_id)
        duration = video_info.get('duration', 0) if video_info else 0
        
        analysis = await VideoService.analyze_transcript(transcript, video_duration=duration)
        segments = getattr(analysis, 'most_relevant_segments', [])
        print(f"Found {len(segments)} viral moments")
        
        print(f"\n[4/5] Processing complete pipeline...")
        result = await VideoService.process_video_complete(
            url=url,
            source_type="youtube",
            task_id=task_id,
            processing_mode="fast"
        )
        
        clips = result.get('clips', [])
        metrics = result.get('_metrics', {})
        
        print(f"\n{'='*60}")
        print(f"SUCCESS! Generated {len(clips)} clips")
        print(f"Processing time: {metrics.get('total_duration_seconds', 'N/A')}s")
        print(f"{'='*60}")
        
        # List generated files
        exports_dir = Path(config.output_dir)
        if exports_dir.exists():
            clips_dir = exports_dir / "clips"
            if clips_dir.exists():
                files = list(clips_dir.glob(f"*{task_id}*.mp4"))
                print(f"\nGenerated files:")
                for f in files:
                    print(f"  - {f.name} ({f.stat().st_size / (1024*1024):.2f} MB)")
        
        return result
        
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    """Main entry point."""
    print("ViraClip Real Video Processor")
    print("=" * 60)
    
    results = []
    for i, url in enumerate(TEST_VIDEOS, 1):
        task_id = f"real_test_{i}_{int(time.time())}"
        result = await process_video_real(url, task_id)
        results.append(result)
        
        if i < len(TEST_VIDEOS):
            print("\nWaiting 5 seconds before next video...")
            await asyncio.sleep(5)
    
    # Summary
    print(f"\n{'='*60}")
    print("PROCESSING COMPLETE")
    print(f"{'='*60}")
    print(f"Videos processed: {len([r for r in results if r])}/{len(results)}")
    
    # Show output location
    try:
        from src.config import Config
        config = Config()
        output_dir = Path(config.output_dir)
        print(f"\nClips saved to: {output_dir.absolute()}")
        
        if output_dir.exists():
            clips_dir = output_dir / "clips"
            if clips_dir.exists():
                all_clips = list(clips_dir.glob("*.mp4"))
                print(f"Total clips in directory: {len(all_clips)}")
                for clip in all_clips[-5:]:  # Show last 5
                    print(f"  - {clip.name}")
    except Exception as e:
        print(f"Could not list output directory: {e}")

if __name__ == "__main__":
    asyncio.run(main())
