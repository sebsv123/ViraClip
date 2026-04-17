"""Quick smoke-test: run the full EditingPipeline on a synthetic test clip."""
import asyncio
import subprocess
from pathlib import Path

TEST_IN  = Path("/tmp/ep_test_input.mp4")
TEST_OUT = Path("/tmp/ep_test_output.mp4")


def make_test_video() -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=15",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=15",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac",
        str(TEST_IN),
    ]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0


async def run_test():
    from src.video_processing.editing_pipeline import EditingPipeline

    ep = EditingPipeline()
    result = await ep.apply(
        video_path=TEST_IN,
        words=[
            {"start": 2.0, "end": 2.2, "word": "INCREDIBLE",
             "is_emphasis": True, "confidence": 0.99},
            {"start": 7.0, "end": 7.3, "word": "AMAZING",
             "is_emphasis": True, "confidence": 0.98},
        ],
        output_path=TEST_OUT,
        segment_text="Este clip viral tiene efectos profesionales",
        flash_timestamps=[3.5, 8.2],
    )
    ok = result == TEST_OUT and TEST_OUT.exists()
    size = TEST_OUT.stat().st_size // 1024 if ok else 0
    print(f"{'✅' if ok else '❌'} EditingPipeline: result={result.name}  size={size}KB")
    return ok


def main():
    print("→ Creating test input video…")
    if not make_test_video():
        print("✗ Failed to create test input")
        return 1
    print("→ Running EditingPipeline…")
    ok = asyncio.run(run_test())
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
