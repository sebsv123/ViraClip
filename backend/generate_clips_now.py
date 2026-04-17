"""
Process existing downloaded videos into clips
"""
from pathlib import Path
from moviepy import VideoFileClip
from datetime import datetime

# Paths
TEMP_DIR = Path("temp")
OUTPUT_DIR = Path("exports/clips")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Videos to process
VIDEOS = [
    ("video_1.mp4", "Video 1 - DHSigj8uPnE"),
    ("video_2.mp4", "Video 2 - 3wgwaxIfUJQ"),
]

print("="*60)
print("ViraClip Clip Generator")
print("="*60)
print(f"Processing {len(VIDEOS)} downloaded videos...")
print()

all_clips = []

for video_file, desc in VIDEOS:
    video_path = TEMP_DIR / video_file
    
    if not video_path.exists():
        print(f"✗ {video_file} not found, skipping")
        continue
    
    print(f"\nProcessing: {desc}")
    print(f"  File: {video_file}")
    
    try:
        # Load video
        clip = VideoFileClip(str(video_path))
        duration = int(clip.duration)
        size_mb = video_path.stat().st_size / (1024*1024)
        
        print(f"  Duration: {duration}s")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"  Generating clips...")
        
        # Strategy: Create 2-3 clips from different parts
        if duration < 60:
            segments = [(0, min(30, duration))]
        elif duration < 300:
            segments = [
                (0, min(60, int(duration * 0.2))),
                (int(duration * 0.4), int(duration * 0.4) + 45),
            ]
        else:
            segments = [
                (0, 60),
                (int(duration * 0.25), int(duration * 0.25) + 60),
                (int(duration * 0.5), int(duration * 0.5) + 60),
            ]
        
        clips_created = 0
        for i, (start, end) in enumerate(segments, 1):
            if start >= duration:
                continue
            end = min(end, duration)
            
            # Generate filename
            video_num = video_file.split("_")[1].split(".")[0]
            output_name = f"clip_video{video_num}_{i}_{start:03d}-{end:03d}.mp4"
            output_path = OUTPUT_DIR / output_name
            
            print(f"    Clip {i}: {start}s-{end}s... ", end="", flush=True)
            
            try:
                # Extract subclip - MoviePy 2.x API
                subclip = clip.subclipped(start, end)
                
                # Write file
                subclip.write_videofile(
                    str(output_path),
                    codec="libx264",
                    audio_codec="aac",
                    logger=None,
                    threads=2
                )
                subclip.close()
                
                if output_path.exists():
                    clip_size = output_path.stat().st_size / (1024*1024)
                    clips_created += 1
                    all_clips.append(output_path)
                    print(f"✓ ({clip_size:.1f} MB)")
                else:
                    print("✗")
                    
            except Exception as e:
                print(f"✗ Error: {e}")
        
        clip.close()
        print(f"  ✓ Created {clips_created} clips from this video")
        
    except Exception as e:
        print(f"  ✗ Failed: {e}")

# Summary
print(f"\n{'='*60}")
print("PROCESSING COMPLETE")
print(f"{'='*60}")
print(f"Total clips generated: {len(all_clips)}")

if all_clips:
    print(f"\nGenerated files:")
    for clip in sorted(all_clips):
        size = clip.stat().st_size / (1024*1024)
        print(f"  - {clip.name} ({size:.2f} MB)")
    
    print(f"\nLocation: {OUTPUT_DIR.absolute()}")
    print(f"\nYou can now use these clips!")
else:
    print("\nNo clips were generated. Please check the errors above.")
