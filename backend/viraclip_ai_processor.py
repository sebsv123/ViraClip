"""
ViraClip AI Full Processor - Using ALL AI capabilities
"""
import asyncio
import sys
import os
from pathlib import Path

# Setup paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Test videos
VIDEO_URLS = [
    ("https://youtu.be/DHSigj8uPnE", "video1"),
    ("https://youtu.be/3wgwaxIfUJQ", "video2")
]

async def process_with_full_ai(url: str, task_id: str):
    """Process video using complete ViraClip AI pipeline."""
    
    print(f"\n{'='*70}")
    print(f"VIRACLIP AI PROCESSING: {task_id}")
    print(f"URL: {url}")
    print(f"{'='*70}\n")
    
    try:
        # Import ViraClip services
        from src.services.video_service import VideoService
        from src.config import Config
        
        config = Config()
        print(f"[CONFIG] Output: {config.output_dir}")
        print(f"[CONFIG] Temp: {config.temp_dir}")
        print(f"[CONFIG] AI Provider: {config.ai_provider}")
        
        # Use the FULL pipeline with ALL AI features
        print(f"\n[1/8] Starting AI-powered video processing...")
        print(f"       - Transcription enabled")
        print(f"       - Viral moment detection enabled")
        print(f"       - Subtitle generation enabled")
        print(f"       - Scene analysis enabled")
        print(f"       - Elite Creative Direction enabled")
        print(f"       - Visual scoring enabled")
        
        result = await VideoService.process_video_complete(
            url=url,
            source_type="youtube",
            task_id=task_id,
            processing_mode="quality",  # Use quality for better AI analysis
            output_format="vertical",   # 9:16 for shorts/reels
            add_subtitles=True,         # ENABLE SUBTITLES
            include_broll=True,         # ENABLE B-ROLL SUGGESTIONS
            split_screen=False,
            target_platform="tiktok",   # Optimize for TikTok/Shorts
        )
        
        # Extract results
        clips = result.get("clips", [])
        segments = result.get("segments", [])
        metrics = result.get("_metrics", {})
        
        print(f"\n[2/8] Processing complete!")
        print(f"       - AI identified {len(segments)} viral moments")
        print(f"       - Generated {len(clips)} clips with subtitles")
        
        # Show each clip with AI analysis
        for i, clip in enumerate(clips, 1):
            print(f"\n[CLIP {i}] {clip.get('filename', 'unknown')}")
            print(f"         Duration: {clip.get('duration', 0):.1f}s")
            print(f"         Virality Score: {clip.get('virality_score', 0):.0f}/100")
            print(f"         Hook Score: {clip.get('hook_score', 0):.0f}")
            print(f"         Scene Count: {clip.get('scene_count', 'N/A')}")
            print(f"         Has Subtitles: {clip.get('has_subtitles', True)}")
            
            # Show viral reasoning
            reasoning = clip.get('reasoning', '')
            if reasoning:
                print(f"         AI Reasoning: {reasoning[:100]}...")
            
            # Show suggested hashtags
            hashtags = clip.get('suggested_hashtags', [])
            if hashtags:
                print(f"         Suggested Hashtags: {', '.join(hashtags[:5])}")
            
            # Show if loop detected
            if clip.get('is_loop'):
                print(f"         ✓ Perfect Loop Detected!")
            
            # Show style applied
            if clip.get('is_styled'):
                print(f"         ✓ Style Applied: {clip.get('style_name', 'AI Style')}")
        
        # Show clips location
        output_dir = Path(config.output_dir) / "clips"
        print(f"\n{'='*70}")
        print(f"CLIPS SAVED TO: {output_dir.absolute()}")
        print(f"{'='*70}\n")
        
        return {
            "status": "success",
            "clips_count": len(clips),
            "segments_count": len(segments),
            "clips": clips,
            "metrics": metrics
        }
        
    except Exception as e:
        print(f"\n[ERROR] Processing failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "failed",
            "error": str(e)
        }

async def main():
    """Main entry point."""
    print("="*70)
    print("VIRACLIP AI FULL PROCESSOR")
    print("="*70)
    print("\nAI Features Enabled:")
    print("  ✓ Transcription (AssemblyAI/Whisper)")
    print("  ✓ Viral Moment Detection")
    print("  ✓ Automatic Subtitles")
    print("  ✓ Scene Rhythm Analysis")
    print("  ✓ Visual Scoring (Ollama)")
    print("  ✓ Elite Creative Direction")
    print("  ✓ B-Roll Suggestions")
    print("  ✓ Loop Detection")
    print("  ✓ Trending Hashtags")
    print("="*70)
    
    results = []
    
    for url, task_id in VIDEO_URLS:
        result = await process_with_full_ai(url, task_id)
        results.append(result)
        
        # Wait between videos
        if url != VIDEO_URLS[-1][0]:
            print("\n[Waiting 5 seconds before next video...]")
            await asyncio.sleep(5)
    
    # Final summary
    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}")
    
    total_clips = sum(r.get("clips_count", 0) for r in results)
    successful = sum(1 for r in results if r.get("status") == "success")
    
    print(f"\nVideos processed: {len(results)}")
    print(f"Successful: {successful}/{len(results)}")
    print(f"Total AI-generated clips: {total_clips}")
    
    # List all generated files
    try:
        from src.config import Config
        config = Config()
        clips_dir = Path(config.output_dir) / "clips"
        
        if clips_dir.exists():
            files = sorted(clips_dir.glob("*.mp4"))
            print(f"\nGenerated clips ({len(files)}):")
            for f in files:
                size_mb = f.stat().st_size / (1024*1024)
                print(f"  - {f.name} ({size_mb:.2f} MB)")
    except Exception as e:
        print(f"Could not list files: {e}")
    
    print(f"\n{'='*70}\n")

if __name__ == "__main__":
    asyncio.run(main())
