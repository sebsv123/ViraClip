"""
Quick manual test for NonLinearEditingEngine
"""
import asyncio
from pathlib import Path

from src.video_processing.nonlinear_edit_engine import NonLinearEditingEngine


async def run_test():
    engine = NonLinearEditingEngine()

    # TODO: adjust this path to a real test video in the repo
    source_video = Path("backend/temp/video_1.mp4")
    if not source_video.exists():
        raise FileNotFoundError(f"Test video not found: {source_video}")

    # Sample non-contiguous segments (start/end in seconds)
    segments = [
        {"start": 10.0, "end": 25.0, "text": "Segment 1"},
        {"start": 142.0, "end": 158.0, "text": "Segment 2"},
        {"start": 87.0, "end": 103.0, "text": "Segment 3"},
    ]

    output_dir = Path("./output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "test_frankenstein.mp4"

    # Assemble metadata
    frankenstein = engine.assemble_frankenstein_clip(segments, full_transcript=[], max_duration=90.0)

    success = engine.render_frankenstein_clip(frankenstein, str(source_video), str(output_path))
    print(f"Render success: {success}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_test())
