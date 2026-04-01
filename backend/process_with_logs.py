import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

# Setup logging
log_file = open("processing_detailed.log", "w", encoding="utf-8")
def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    log_file.write(line + "\n")
    log_file.flush()

# Create dirs
Path("exports/clips").mkdir(parents=True, exist_ok=True)
Path("temp").mkdir(parents=True, exist_ok=True)

URLS = [
    "https://youtu.be/DHSigj8uPnE",
    "https://youtu.be/3wgwaxIfUJQ"
]

log("="*60)
log("VIRACLIP VIDEO PROCESSOR")
log("="*60)

# Check dependencies
log("Checking dependencies...")

try:
    result = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], 
                          capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        log(f"✓ yt-dlp: {result.stdout.strip()}")
    else:
        log("✗ yt-dlp check failed")
except Exception as e:
    log(f"✗ yt-dlp error: {e}")

# Check moviepy
try:
    import moviepy
    log(f"✓ MoviePy: {moviepy.__version__}")
except ImportError:
    log("✗ MoviePy not installed")
    log("Please run: pip install moviepy")
    sys.exit(1)

log("="*60)

# Process each video
results = []

for i, url in enumerate(URLS, 1):
    log(f"\n[{i}/{len(URLS)}] Processing: {url}")
    
    result = {"url": url, "clips": [], "errors": []}
    
    # Download
    output_template = f"temp/video_{i}.%(ext)s"
    log(f"  Downloading with yt-dlp...")
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "best[ext=mp4]/best",
        "-o", output_template,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        url
    ]
    
    try:
        dl_result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if dl_result.returncode != 0:
            error_msg = f"Download failed: {dl_result.stderr[:200]}"
            log(f"  ✗ {error_msg}")
            result["errors"].append(error_msg)
            results.append(result)
            continue
        
        # Find downloaded file
        files = list(Path("temp").glob(f"video_{i}.*"))
        if not files:
            log(f"  ✗ No file found after download")
            result["errors"].append("No file found")
            results.append(result)
            continue
        
        video_file = files[0]
        size_mb = video_file.stat().st_size / (1024*1024)
        log(f"  ✓ Downloaded: {video_file.name} ({size_mb:.1f} MB)")
        
        # Process with MoviePy
        log(f"  Processing with MoviePy...")
        
        try:
            from moviepy import VideoFileClip
            
            clip = VideoFileClip(str(video_file))
            duration = int(clip.duration)
            
            log(f"  Video duration: {duration}s")
            
            # Generate clips
            segments = [
                (0, min(30, duration)),
                (int(duration*0.3), min(int(duration*0.3)+30, duration)),
            ]
            
            clips_created = 0
            for idx, (start, end) in enumerate(segments, 1):
                if start >= duration:
                    continue
                    
                output_path = f"exports/clips/video{i}_clip{idx}_{start:03d}-{end:03d}.mp4"
                log(f"    Creating clip {idx}: {start}s-{end}s...", end=" ")
                
                try:
                    subclip = clip.subclip(start, end)
                    subclip.write_videofile(
                        output_path,
                        codec="libx264",
                        audio_codec="aac",
                        verbose=False,
                        logger=None,
                        threads=2
                    )
                    subclip.close()
                    
                    if Path(output_path).exists():
                        clips_created += 1
                        clip_size = Path(output_path).stat().st_size / (1024*1024)
                        log(f"OK ({clip_size:.1f} MB)")
                        result["clips"].append(output_path)
                    else:
                        log("FAILED")
                        
                except Exception as e:
                    log(f"ERROR: {e}")
            
            clip.close()
            log(f"  ✓ Created {clips_created} clips")
            
        except Exception as e:
            log(f"  ✗ MoviePy error: {e}")
            result["errors"].append(str(e))
        
    except subprocess.TimeoutExpired:
        log(f"  ✗ Timeout after 5 minutes")
        result["errors"].append("Timeout")
    except Exception as e:
        log(f"  ✗ Error: {e}")
        result["errors"].append(str(e))
    
    results.append(result)

# Summary
log(f"\n{'='*60}")
log("PROCESSING COMPLETE")
log(f"{'='*60}")

total_clips = sum(len(r["clips"]) for r in results)
successful = sum(1 for r in results if r["clips"])

log(f"Videos processed: {len(results)}")
log(f"Successful: {successful}/{len(results)}")
log(f"Total clips: {total_clips}")

# List all clips
clip_files = list(Path("exports/clips").glob("*.mp4"))
log(f"\nGenerated files ({len(clip_files)}):")
for f in sorted(clip_files):
    size = f.stat().st_size / (1024*1024)
    log(f"  - {f.name} ({size:.2f} MB)")

log(f"\nOutput directory: {Path('exports/clips').absolute()}")

log_file.close()
print(f"\nDetailed log saved to: processing_detailed.log")
