"""
Process YouTube Videos - Simplified version
"""
import subprocess
import sys
from pathlib import Path

# Videos to process
URLS = [
    "https://youtu.be/DHSigj8uPnE",
    "https://youtu.be/3wgwaxIfUJQ"
]

# Create directories
Path("exports/clips").mkdir(parents=True, exist_ok=True)
Path("temp").mkdir(parents=True, exist_ok=True)

print("="*60)
print("ViraClip Video Processor")
print("="*60)

# Check yt-dlp
try:
    result = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], 
                          capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        print(f"✓ yt-dlp: {result.stdout.strip()}")
    else:
        print("✗ yt-dlp not available")
        sys.exit(1)
except Exception as e:
    print(f"✗ Error checking yt-dlp: {e}")
    sys.exit(1)

# Check ffmpeg
try:
    result = subprocess.run(["ffmpeg", "-version"], 
                          capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        version = result.stdout.split('\n')[0]
        print(f"✓ FFmpeg: {version[:50]}")
    else:
        print("⚠ FFmpeg not in PATH - will try moviepy")
except Exception:
    print("⚠ FFmpeg not available - will use moviepy")

print("="*60)

# Process videos
for i, url in enumerate(URLS, 1):
    print(f"\n[{i}/{len(URLS)}] Processing: {url}")
    
    # Download
    output_file = f"temp/video_{i}.mp4"
    print(f"  Downloading...")
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "best[ext=mp4]/best",
        "-o", output_file,
        "--quiet", "--no-warnings",
        "--no-playlist",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  ✗ Download failed: {result.stderr[:200]}")
            continue
        
        # Find downloaded file
        files = list(Path("temp").glob(f"video_{i}.*"))
        if not files:
            print(f"  ✗ File not found after download")
            continue
            
        video_file = files[0]
        size_mb = video_file.stat().st_size / (1024*1024)
        print(f"  ✓ Downloaded: {video_file.name} ({size_mb:.1f} MB)")
        
        # Get info
        info_cmd = [
            sys.executable, "-m", "yt_dlp",
            "--print", "%(title)s|%(duration)s",
            "--quiet", url
        ]
        info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)
        if info_result.returncode == 0:
            parts = info_result.stdout.strip().split("|")
            if len(parts) == 2:
                print(f"  Title: {parts[0][:60]}")
                print(f"  Duration: {parts[1]}s")
        
        # Create clips with FFmpeg
        print(f"  Creating clips...")
        
        # Use moviepy if available, otherwise skip clipping
        try:
            from moviepy.editor import VideoFileClip
            
            clip = VideoFileClip(str(video_file))
            duration = int(clip.duration)
            
            # Create 2-3 clips
            segments = [
                (0, min(30, duration)),
                (int(duration*0.3), min(int(duration*0.3)+30, duration)),
                (int(duration*0.6), min(int(duration*0.6)+30, duration))
            ]
            
            clips_created = 0
            for idx, (start, end) in enumerate(segments, 1):
                if start >= duration:
                    continue
                    
                output_clip = f"exports/clips/video{i}_clip{idx}_{start}-{end}.mp4"
                print(f"    Clip {idx}: {start}s-{end}s...", end=" ")
                
                try:
                    subclip = clip.subclip(start, end)
                    subclip.write_videofile(output_clip, verbose=False, logger=None)
                    subclip.close()
                    
                    if Path(output_clip).exists():
                        clips_created += 1
                        print("✓")
                    else:
                        print("✗")
                except Exception as e:
                    print(f"✗ ({e})")
            
            clip.close()
            print(f"  ✓ Created {clips_created} clips")
            
        except ImportError:
            print(f"  ⚠ MoviePy not available - skipping clip creation")
            print(f"  ✓ Video saved to: {video_file}")
        
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout (5 minutes)")
    except Exception as e:
        print(f"  ✗ Error: {e}")

# Summary
print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")

clip_files = list(Path("exports/clips").glob("*.mp4"))
print(f"Clips generated: {len(clip_files)}")
for f in sorted(clip_files):
    size = f.stat().st_size / (1024*1024)
    print(f"  - {f.name} ({size:.2f} MB)")

print(f"\nLocation: {Path('exports/clips').absolute()}")
