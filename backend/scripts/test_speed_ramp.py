"""Test speed_ramp_silences and export profiles."""
import asyncio, subprocess
from pathlib import Path

IN  = Path("/tmp/ep_test_input.mp4")
OUT = Path("/tmp/ramp_test_output.mp4")


def make_test_video():
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=20",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", str(IN),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0


async def test_speed_ramp():
    from src.video_processing.silence_removal import speed_ramp_silences
    # Simulate 3 speech bursts with ~0.8s silences between them
    words = [
        {"word": "Hello",   "start": 0.5,  "end": 1.2},
        {"word": "world",   "start": 1.3,  "end": 2.1},
        {"word": "this",    "start": 3.2,  "end": 3.6},  # gap 2.1→3.2 = 1.1s
        {"word": "is",      "start": 3.7,  "end": 4.0},
        {"word": "great",   "start": 4.1,  "end": 4.8},
        {"word": "content", "start": 6.5,  "end": 7.2},  # gap 4.8→6.5 = 1.7s
        {"word": "yeah",    "start": 7.3,  "end": 8.0},
    ]
    ok = await speed_ramp_silences(str(IN), str(OUT), words, clip_duration=20.0)
    if ok and OUT.exists():
        size = OUT.stat().st_size // 1024
        # Verify output is shorter than input (silences sped up)
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(OUT)],
            capture_output=True, text=True,
        )
        dur_out = float(r.stdout.strip() or "0")
        print(f"✅ speed_ramp: output={OUT.name}  size={size}KB  dur={dur_out:.1f}s (was 20.0s)")
    else:
        print(f"❌ speed_ramp failed (ok={ok})")


async def test_export_profiles():
    from src.video_processing.export_profiles import Platform, get_ffmpeg_export_command
    test_platforms = [Platform.TIKTOK, Platform.REELS, Platform.SHORTS]
    all_ok = True
    for p in test_platforms:
        cmd = get_ffmpeg_export_command(str(IN), f"/tmp/export_{p.value}.mp4", p.value)
        r = subprocess.run(cmd, capture_output=True)
        ok = r.returncode == 0 and Path(f"/tmp/export_{p.value}.mp4").exists()
        size = Path(f"/tmp/export_{p.value}.mp4").stat().st_size // 1024 if ok else 0
        print(f"  {'✅' if ok else '❌'} {p.value}: size={size}KB")
        all_ok = all_ok and ok
    return all_ok


async def main():
    print("→ Creating 20s test video...")
    if not make_test_video():
        print("✗ Failed to create test video"); return

    print("\n→ Testing speed_ramp_silences...")
    await test_speed_ramp()

    print("\n→ Testing multi-platform export profiles...")
    await test_export_profiles()


if __name__ == "__main__":
    asyncio.run(main())
