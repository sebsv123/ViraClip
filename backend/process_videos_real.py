"""
Standalone Video Processor for ViraClip
Processes YouTube videos without complex import chains.
"""

import os
import sys
import asyncio
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Configuration
OUTPUT_DIR = Path("exports/clips")
TEMP_DIR = Path("temp")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Test videos
VIDEO_URLS = [
    "https://youtu.be/DHSigj8uPnE",
    "https://youtu.be/3wgwaxIfUJQ"
]


def download_video(url: str, task_id: str) -> Path:
    """Download video using yt-dlp."""
    print(f"[DOWNLOAD] Starting: {url}")
    
    output_path = TEMP_DIR / f"{task_id}_raw.mp4"
    
    cmd = [
        "yt-dlp",
        "-f", "best[ext=mp4]/best",
        "-o", str(output_path),
        "--no-playlist",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"[DOWNLOAD] Success: {output_path}")
            return output_path
        else:
            print(f"[DOWNLOAD] Error: {result.stderr}")
            return None
    except Exception as e:
        print(f"[DOWNLOAD] Exception: {e}")
        return None


def get_video_info(url: str) -> dict:
    """Get video metadata."""
    print(f"[INFO] Getting metadata...")
    
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout.strip().split('\n')[0])
            return {
                "title": data.get("title", "Unknown"),
                "duration": data.get("duration", 0),
                "author": data.get("uploader", "Unknown"),
                "view_count": data.get("view_count", 0)
            }
    except Exception as e:
        print(f"[INFO] Error: {e}")
    
    return {"title": "Unknown", "duration": 0, "author": "Unknown"}


def extract_clip(video_path: Path, start: int, end: int, output_name: str) -> Path:
    """Extract clip using FFmpeg."""
    print(f"[CLIP] Extracting {start}s to {end}s...")
    
    output_path = OUTPUT_DIR / output_name
    
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-ss", str(start),
        "-t", str(end - start),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-y",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            print(f"[CLIP] Created: {output_name} ({output_path.stat().st_size / (1024*1024):.2f} MB)")
            return output_path
        else:
            print(f"[CLIP] FFmpeg error: {result.stderr[:200]}")
            return None
    except Exception as e:
        print(f"[CLIP] Exception: {e}")
        return None


def analyze_and_clip(video_path: Path, video_info: dict, task_id: str) -> list:
    """Analyze video and generate clips based on duration."""
    duration = video_info.get("duration", 0)
    clips = []
    
    print(f"[ANALYZE] Video duration: {duration}s")
    
    if duration == 0:
        print("[ANALYZE] Cannot analyze - no duration")
        return clips
    
    # Strategy: Extract viral moments based on video length
    if duration < 60:
        # Short video - split in half
        mid = duration // 2
        segments = [(0, min(30, mid)), (mid, min(duration, mid + 30))]
    elif duration < 300:
        # Medium video (1-5 min) - extract 3 segments
        segments = [
            (0, min(60, duration * 0.2)),
            (int(duration * 0.3), int(duration * 0.3) + 45),
            (int(duration * 0.6), min(duration, int(duration * 0.6) + 60))
        ]
    else:
        # Long video - extract 4-5 segments
        segments = [
            (0, 60),
            (int(duration * 0.2), int(duration * 0.2) + 60),
            (int(duration * 0.4), int(duration * 0.4) + 60),
            (int(duration * 0.6), int(duration * 0.6) + 60),
            (int(duration * 0.8), min(duration, int(duration * 0.8) + 60))
        ]
    
    print(f"[ANALYZE] Will generate {len(segments)} clips")
    
    for i, (start, end) in enumerate(segments, 1):
        if start >= duration:
            continue
        end = min(end, duration)
        
        clip_name = f"clip_{task_id}_{i:02d}_{start:04d}-{end:04d}.mp4"
        clip_path = extract_clip(video_path, start, end, clip_name)
        
        if clip_path:
            clips.append({
                "path": str(clip_path),
                "start": start,
                "end": end,
                "duration": end - start,
                "name": clip_name
            })
    
    return clips


def process_single_video(url: str, index: int) -> dict:
    """Process one video end-to-end."""
    task_id = f"video{index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"\n{'='*60}")
    print(f"PROCESSING VIDEO {index}: {url}")
    print(f"Task ID: {task_id}")
    print(f"{'='*60}\n")
    
    result = {
        "url": url,
        "task_id": task_id,
        "status": "pending",
        "info": {},
        "clips": [],
        "errors": []
    }
    
    # Get info
    info = get_video_info(url)
    result["info"] = info
    print(f"Title: {info['title']}")
    print(f"Duration: {info['duration']}s")
    print(f"Author: {info['author']}")
    
    # Download
    video_path = download_video(url, task_id)
    if not video_path:
        result["status"] = "failed"
        result["errors"].append("Download failed")
        return result
    
    # Analyze and clip
    clips = analyze_and_clip(video_path, info, task_id)
    result["clips"] = clips
    
    if clips:
        result["status"] = "success"
        print(f"\n[✓] Generated {len(clips)} clips successfully!")
    else:
        result["status"] = "partial"
        result["errors"].append("No clips generated")
    
    return result


def main():
    """Main entry point."""
    print("VIRACLIP VIDEO PROCESSOR")
    print("=" * 60)
    print(f"Output directory: {OUTPUT_DIR.absolute()}")
    print(f"Temp directory: {TEMP_DIR.absolute()}")
    print("=" * 60)
    
    all_results = []
    
    for i, url in enumerate(VIDEO_URLS, 1):
        result = process_single_video(url, i)
        all_results.append(result)
        
        if i < len(VIDEO_URLS):
            print("\n[Waiting 3 seconds...]")
            import time
            time.sleep(3)
    
    # Summary
    print(f"\n{'='*60}")
    print("PROCESSING COMPLETE - SUMMARY")
    print(f"{'='*60}")
    
    total_clips = sum(len(r["clips"]) for r in all_results)
    successful = sum(1 for r in all_results if r["status"] == "success")
    
    print(f"\nVideos processed: {len(all_results)}")
    print(f"Successful: {successful}/{len(all_results)}")
    print(f"Total clips generated: {total_clips}")
    
    print(f"\nGenerated Files Location:")
    print(f"  {OUTPUT_DIR.absolute()}")
    
    if OUTPUT_DIR.exists():
        files = list(OUTPUT_DIR.glob("*.mp4"))
        print(f"\nFiles in output directory ({len(files)} total):")
        for f in sorted(files)[-10:]:  # Show last 10
            size_mb = f.stat().st_size / (1024*1024)
            print(f"  - {f.name} ({size_mb:.2f} MB)")
    
    # Save report
    report_file = f"processing_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nReport saved: {report_file}")


if __name__ == "__main__":
    main()
