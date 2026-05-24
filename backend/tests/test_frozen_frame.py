"""
Integration tests for the frozen-frame bug fix in EditingPipeline.

Replaces zoompan (frame-counter-based, freezes on VFR/FPS misdetection)
with scale+crop animated zoom (time-based, immune to frame count issues).

Each test generates its own synthetic video via FFmpeg and verifies
the output frame count via ffprobe -count_packets.
"""

from __future__ import annotations

import asyncio
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _require_ffmpeg() -> None:
    if not _FFMPEG:
        pytest.skip("ffmpeg not found in PATH")


def _require_ffprobe() -> None:
    if not _FFPROBE:
        pytest.skip("ffprobe not found in PATH")


def _probe_frame_count(path: Path) -> int:
    """Return the actual number of video packets (frames) via ffprobe -count_packets."""
    result = subprocess.run(
        [
            _FFPROBE,
            "-v", "error",
            "-select_streams", "v:0",
            "-count_packets",
            "-show_entries", "stream=nb_read_packets",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, timeout=15, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return int(result.stdout.strip())
    return 0


def _probe_audio_duration(path: Path) -> float:
    """Return audio stream duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            _FFPROBE,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, timeout=15, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass
    return 0.0


def _probe_video_duration(path: Path) -> float:
    """Return video stream duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            _FFPROBE,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, timeout=15, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass
    # Fallback: format duration
    result2 = subprocess.run(
        [
            _FFPROBE,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, timeout=15, text=True,
    )
    if result2.returncode == 0 and result2.stdout.strip():
        try:
            return float(result2.stdout.strip())
        except ValueError:
            pass
    return 0.0


def _generate_synthetic_clip(
    tmp_dir: Path,
    duration: float,
    fps: float = 30.0,
    width: int = 1080,
    height: int = 1920,
    with_audio: bool = True,
    audio_duration: float | None = None,
    vfr: bool = False,
) -> Path:
    """
    Generate a synthetic test clip using FFmpeg.

    Args:
        tmp_dir: Directory for the output file.
        duration: Target video duration in seconds.
        fps: Target framerate.
        width, height: Video dimensions.
        with_audio: Whether to include a silent audio track.
        audio_duration: If set, audio will be this duration (may differ from video).
        vfr: If True, generate a VFR-like clip by using a low constant framerate
             and then re-encoding with a different rate to simulate frame drops.

    Returns:
        Path to the generated clip.
    """
    clip_path = tmp_dir / "input.mp4"

    if vfr:
        # Simulate VFR: generate at a low FPS, then re-wrap at a higher rate
        # so the declared fps differs from the actual frame count.
        raw_path = tmp_dir / "raw.mp4"
        cmd_raw = [
            _FFMPEG, "-y",
            "-f", "lavfi",
            "-i", f"testsrc=duration={duration}:size={width}x{height}:rate={fps * 0.4:.1f}",
        ]
        if with_audio:
            adur = audio_duration if audio_duration is not None else duration
            cmd_raw += [
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=stereo:d={adur}",
            ]
        cmd_raw += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw_path)]
        subprocess.run(cmd_raw, capture_output=True, timeout=30, check=True)

        # Re-encode at a higher declared fps — actual frames stay low = VFR-like
        cmd_vfr = [
            _FFMPEG, "-y",
            "-r", str(fps),  # declare higher fps
            "-i", str(raw_path),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", str(fps),
            str(clip_path),
        ]
        subprocess.run(cmd_vfr, capture_output=True, timeout=30, check=True)
    else:
        cmd = [
            _FFMPEG, "-y",
            "-f", "lavfi",
            "-i", f"testsrc=duration={duration}:size={width}x{height}:rate={fps}",
        ]
        if with_audio:
            adur = audio_duration if audio_duration is not None else duration
            cmd += [
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=stereo:d={adur}",
            ]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip_path)]
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)

    return clip_path


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def editing_pipeline():
    """Return a shared EditingPipeline instance."""
    from backend.src.video_processing.editing_pipeline import EditingPipeline
    return EditingPipeline()


# ── tests ─────────────────────────────────────────────────────────────────────


class TestFrozenFrameRegression:
    """Verify that the scale+crop zoom does not produce frozen frames."""

    @pytest.mark.timeout(60)
    @pytest.mark.asyncio
    async def test_vfr_real(self, editing_pipeline):
        """
        Caso 1 — VFR real: clip with fewer actual frames than declared fps.
        Verifies output has ≥ 92% of expected frames at 24fps.
        """
        _require_ffmpeg()
        _require_ffprobe()

        tmp_dir = Path(tempfile.mkdtemp(prefix="vfr_"))
        try:
            dur = 10.0
            declared_fps = 30.0
            clip = _generate_synthetic_clip(
                tmp_dir, duration=dur, fps=declared_fps, vfr=True,
            )

            output = tmp_dir / "output.mp4"
            result = await editing_pipeline.apply(
                video_path=clip,
                words=[],
                output_path=output,
                segment_text="Test VFR clip",
            )

            assert result is not None, "apply() returned None"
            assert result.exists(), "output file does not exist"
            assert result.stat().st_size > 0, "output file is empty"

            actual_frames = _probe_frame_count(result)
            target_fps = 24.0  # minimum fps used by the pipeline
            expected_frames = int(math.ceil(dur * target_fps))
            min_frames = int(expected_frames * 0.92)

            assert actual_frames >= min_frames, (
                f"VFR clip: expected ≥{min_frames} frames ({expected_frames}*0.92), "
                f"got {actual_frames} — frozen frame regression!"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.timeout(60)
    @pytest.mark.asyncio
    async def test_low_fps(self, editing_pipeline):
        """
        Caso 2 — FPS muy bajo (< 15fps): the exact case that caused the
        original freeze. 8s at 12fps → zoompan would overestimate frames.
        """
        _require_ffmpeg()
        _require_ffprobe()

        tmp_dir = Path(tempfile.mkdtemp(prefix="lowfps_"))
        try:
            dur = 8.0
            low_fps = 12.0
            clip = _generate_synthetic_clip(
                tmp_dir, duration=dur, fps=low_fps,
            )

            output = tmp_dir / "output.mp4"
            result = await editing_pipeline.apply(
                video_path=clip,
                words=[],
                output_path=output,
                segment_text="Test low FPS clip",
            )

            assert result is not None
            assert result.exists()
            assert result.stat().st_size > 0

            actual_frames = _probe_frame_count(result)
            target_fps = 24.0
            expected_frames = int(math.ceil(dur * target_fps))
            min_frames = int(expected_frames * 0.92)

            assert actual_frames >= min_frames, (
                f"Low FPS clip: expected ≥{min_frames} frames ({expected_frames}*0.92), "
                f"got {actual_frames} — frozen frame regression!"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.timeout(60)
    @pytest.mark.asyncio
    async def test_very_short_clip(self, editing_pipeline):
        """
        Caso 3 — Clip muy corto (< 1s): 0.7s at 30fps.
        Verifies no exception and output exists.
        """
        _require_ffmpeg()

        tmp_dir = Path(tempfile.mkdtemp(prefix="short_"))
        try:
            dur = 0.7
            clip = _generate_synthetic_clip(
                tmp_dir, duration=dur, fps=30.0,
            )

            output = tmp_dir / "output.mp4"
            result = await editing_pipeline.apply(
                video_path=clip,
                words=[],
                output_path=output,
                segment_text="Short",
            )

            assert result is not None, "apply() returned None for short clip"
            assert result.exists(), "output file does not exist for short clip"
            assert result.stat().st_size > 0, "output file is empty for short clip"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.timeout(60)
    @pytest.mark.asyncio
    async def test_audio_shorter_than_video(self, editing_pipeline):
        """
        Caso 4 — Audio más corto que video: video 10s, audio 6s.
        Verifies output audio duration ≥ 9.5s (apad should pad the gap).
        """
        _require_ffmpeg()
        _require_ffprobe()

        tmp_dir = Path(tempfile.mkdtemp(prefix="audioshort_"))
        try:
            dur = 10.0
            audio_dur = 6.0
            clip = _generate_synthetic_clip(
                tmp_dir, duration=dur, fps=30.0,
                with_audio=True, audio_duration=audio_dur,
            )

            output = tmp_dir / "output.mp4"
            result = await editing_pipeline.apply(
                video_path=clip,
                words=[],
                output_path=output,
                segment_text="Test audio shorter than video",
            )

            assert result is not None
            assert result.exists()
            assert result.stat().st_size > 0

            actual_audio_dur = _probe_audio_duration(result)
            # apad=whole_dur=10.0 should pad audio to full video duration
            assert actual_audio_dur >= 9.5, (
                f"Audio duration {actual_audio_dur:.2f}s < 9.5s — "
                f"apad did not pad the gap (video={dur}s, source audio={audio_dur}s)"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.timeout(60)
    @pytest.mark.asyncio
    async def test_zoom_intensity_off(self, editing_pipeline):
        """
        Caso 5 — zoom_intensity="off": verifies output frame count matches
        input frame count (no frames added or lost).
        """
        _require_ffmpeg()
        _require_ffprobe()

        tmp_dir = Path(tempfile.mkdtemp(prefix="zoomoff_"))
        try:
            dur = 10.0
            fps = 30.0
            clip = _generate_synthetic_clip(
                tmp_dir, duration=dur, fps=fps,
            )

            input_frames = _probe_frame_count(clip)

            output = tmp_dir / "output.mp4"
            result = await editing_pipeline.apply(
                video_path=clip,
                words=[],
                output_path=output,
                segment_text="Test zoom off",
                zoom_intensity="off",
            )

            assert result is not None
            assert result.exists()
            assert result.stat().st_size > 0

            output_frames = _probe_frame_count(result)
            # With zoom off, the pipeline should produce the same number of frames
            # (or very close — allow 5% tolerance for encoder rounding)
            min_frames = int(input_frames * 0.95)
            max_frames = int(input_frames * 1.05)

            assert min_frames <= output_frames <= max_frames, (
                f"zoom_intensity=off: input had {input_frames} frames, "
                f"output has {output_frames} — expected between {min_frames} and {max_frames}"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
