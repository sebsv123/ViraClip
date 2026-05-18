"""
Tests for transitions_service.py — professional video transitions.

Verifies:
  1. apply_transition produces valid output for all 3 transition types
  2. Output duration ≈ dur_a + dur_b - transition_duration
  3. Output has 1 video + 1 audio stream
  4. Fallback to concat when xfade fails
  5. Preset system resolves correctly
  6. Batch concatenation works
  7. Edge cases: single clip, invalid type, zero-duration
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the backend src is importable
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from services.transitions_service import (
    DEFAULT_TRANSITION_DURATION,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
    DEFAULT_FPS,
    TRANSITION_TYPES,
    PRESETS,
    apply_transition,
    apply_transition_batch,
    _probe_duration,
    _probe_streams,
    _normalise_input,
    _apply_crossfade,
    _apply_fade_black,
    _apply_slide_left,
    _fallback_concat,
)

logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _get_ffprobe_exe() -> str:
    """Return path to ffprobe binary."""
    import shutil
    if shutil.which("ffprobe"):
        return "ffprobe"
    ffmpeg = _get_ffmpeg_exe()
    if ffmpeg.endswith("ffmpeg"):
        return ffmpeg.replace("ffmpeg", "ffprobe")
    return "ffprobe"


def _probe_streams_sync(video_path: Path) -> dict:
    """Synchronous version of _probe_streams for test assertions."""
    info = {"width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT, "fps": DEFAULT_FPS,
            "has_audio": True, "audio_codec": "aac", "video_codec": "h264"}
    try:
        cmd = [
            _get_ffprobe_exe(), "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        video_count = 0
        audio_count = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_count += 1
                info["width"] = int(stream.get("width", DEFAULT_WIDTH))
                info["height"] = int(stream.get("height", DEFAULT_HEIGHT))
                fps_str = stream.get("r_frame_rate", "30/1")
                try:
                    num, den = fps_str.split("/")
                    info["fps"] = round(float(num) / float(den), 3)
                except Exception:
                    info["fps"] = DEFAULT_FPS
                info["video_codec"] = stream.get("codec_name", "h264")
            elif stream.get("codec_type") == "audio":
                audio_count += 1
                info["has_audio"] = True
                info["audio_codec"] = stream.get("codec_name", "aac")
        info["video_count"] = video_count
        info["audio_count"] = audio_count
    except Exception as exc:
        logger.debug("probe_streams_sync failed for %s: %s", video_path, exc)
        info["video_count"] = 0
        info["audio_count"] = 0
    return info


def _probe_duration_sync(video_path: Path) -> float:
    """Synchronous version of _probe_duration."""
    try:
        cmd = [
            _get_ffprobe_exe(), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _generate_test_clip(
    output_path: Path,
    duration: float = 2.0,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    color: str = "red",
    with_audio: bool = True,
) -> Path:
    """Generate a simple test video clip using FFmpeg.

    Creates a solid-color video with optional sine tone audio.
    """
    cmd = [
        _get_ffmpeg_exe(), "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s={width}x{height}:d={duration}:r={DEFAULT_FPS}",
    ]
    if with_audio:
        cmd += [
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration}:sample_rate=48000",
        ]
        map_flags = ["-map", "0:v", "-map", "1:a"]
    else:
        map_flags = ["-map", "0:v"]

    cmd += [
        *map_flags,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "48000",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    assert result.returncode == 0, f"Test clip generation failed: {result.stderr.decode()[-300:]}"
    assert output_path.exists(), f"Test clip not created: {output_path}"
    assert output_path.stat().st_size > 1000, f"Test clip too small: {output_path.stat().st_size}"
    return output_path


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory(prefix="viraclip_test_trans_") as d:
        yield Path(d)


@pytest.fixture
def clip_a(tmp_dir):
    """Generate clip A (red, 2s)."""
    return _generate_test_clip(tmp_dir / "clip_a.mp4", duration=2.0, color="red")


@pytest.fixture
def clip_b(tmp_dir):
    """Generate clip B (blue, 2s)."""
    return _generate_test_clip(tmp_dir / "clip_b.mp4", duration=2.0, color="blue")


@pytest.fixture
def clip_c(tmp_dir):
    """Generate clip C (green, 2s)."""
    return _generate_test_clip(tmp_dir / "clip_c.mp4", duration=2.0, color="green")


@pytest.fixture
def clip_no_audio(tmp_dir):
    """Generate a clip without audio (2s)."""
    return _generate_test_clip(tmp_dir / "clip_no_audio.mp4", duration=2.0, color="white", with_audio=False)


# ── Tests ──────────────────────────────────────────────────────────────────


class TestProbeHelpers:
    """Test the probe helper functions."""

    def test_probe_duration(self, clip_a):
        dur = _probe_duration_sync(clip_a)
        assert abs(dur - 2.0) < 0.1, f"Expected ~2.0s, got {dur}"

    def test_probe_streams_video_audio(self, clip_a):
        info = _probe_streams_sync(clip_a)
        assert info["video_count"] >= 1
        assert info["audio_count"] >= 1
        assert info["width"] == DEFAULT_WIDTH
        assert info["height"] == DEFAULT_HEIGHT

    def test_probe_streams_no_audio(self, clip_no_audio):
        info = _probe_streams_sync(clip_no_audio)
        assert info["video_count"] >= 1
        # Audio may or may not be present depending on ffmpeg version
        # Just verify it doesn't crash


class TestNormaliseInput:
    """Test the input normalisation step."""

    @pytest.mark.asyncio
    async def test_normalise_success(self, tmp_dir, clip_a):
        out = tmp_dir / "norm_a.mp4"
        ok = await _normalise_input(clip_a, out)
        assert ok, "Normalisation should succeed"
        assert out.exists()
        assert out.stat().st_size > 1000
        info = _probe_streams_sync(out)
        assert info["width"] == DEFAULT_WIDTH
        assert info["height"] == DEFAULT_HEIGHT
        assert abs(info["fps"] - DEFAULT_FPS) < 1.0

    @pytest.mark.asyncio
    async def test_normalise_nonexistent_input(self, tmp_dir):
        out = tmp_dir / "norm_fail.mp4"
        ok = await _normalise_input(Path("/nonexistent/video.mp4"), out)
        assert not ok, "Normalisation should fail for nonexistent input"


class TestTransitionTypes:
    """Test each transition type produces valid output."""

    @pytest.mark.asyncio
    async def test_crossfade(self, tmp_dir, clip_a, clip_b):
        out = tmp_dir / "crossfade_out.mp4"
        result = await apply_transition(clip_a, clip_b, transition_type="crossfade",
                                        duration=0.25, output_path=out)
        assert result == out, f"Expected {out}, got {result}"
        assert out.exists(), "Output should exist"
        assert out.stat().st_size > 1000, "Output should not be empty"
        # Verify streams
        info = _probe_streams_sync(out)
        assert info["video_count"] >= 1, "Should have video stream"
        assert info["audio_count"] >= 1, "Should have audio stream"
        # Verify duration ≈ 2 + 2 - 0.25 = 3.75
        dur = _probe_duration_sync(out)
        expected = 2.0 + 2.0 - 0.25
        assert abs(dur - expected) < 0.5, f"Expected ~{expected}s, got {dur}"

    @pytest.mark.asyncio
    async def test_fade_black(self, tmp_dir, clip_a, clip_b):
        out = tmp_dir / "fade_black_out.mp4"
        result = await apply_transition(clip_a, clip_b, transition_type="fade_black",
                                        duration=0.25, output_path=out)
        assert result == out, f"Expected {out}, got {result}"
        assert out.exists()
        assert out.stat().st_size > 1000
        info = _probe_streams_sync(out)
        assert info["video_count"] >= 1
        assert info["audio_count"] >= 1

    @pytest.mark.asyncio
    async def test_slide_left(self, tmp_dir, clip_a, clip_b):
        out = tmp_dir / "slide_left_out.mp4"
        result = await apply_transition(clip_a, clip_b, transition_type="slide_left",
                                        duration=0.25, output_path=out)
        assert result == out, f"Expected {out}, got {result}"
        assert out.exists()
        assert out.stat().st_size > 1000
        info = _probe_streams_sync(out)
        assert info["video_count"] >= 1
        assert info["audio_count"] >= 1

    @pytest.mark.asyncio
    async def test_default_transition(self, tmp_dir, clip_a, clip_b):
        """Default should be crossfade."""
        out = tmp_dir / "default_out.mp4"
        result = await apply_transition(clip_a, clip_b, output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    @pytest.mark.asyncio
    async def test_invalid_transition_type(self, tmp_dir, clip_a, clip_b):
        """Should raise ValueError for unknown transition type."""
        with pytest.raises(ValueError, match="Unknown transition type"):
            await apply_transition(clip_a, clip_b, transition_type="invalid_type",
                                   output_path=tmp_dir / "invalid.mp4")


class TestPresetSystem:
    """Test the preset resolution logic."""

    def test_preset_default(self):
        preset = PRESETS["default"]
        assert preset["transition_for"]("talking_head") == "crossfade"
        assert preset["transition_for"]("broll") == "crossfade"
        assert preset["transition_for"]("action") == "crossfade"

    def test_preset_dynamic(self):
        preset = PRESETS["dynamic"]
        assert preset["transition_for"]("talking_head") == "crossfade"
        assert preset["transition_for"]("broll") == "slide_left"
        assert preset["transition_for"]("action") == "slide_left"
        assert preset["transition_for"]("transition") == "slide_left"
        assert preset["transition_for"]("unknown") == "crossfade"

    @pytest.mark.asyncio
    async def test_apply_with_preset_default(self, tmp_dir, clip_a, clip_b):
        out = tmp_dir / "preset_default_out.mp4"
        result = await apply_transition(clip_a, clip_b, preset="default",
                                        output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    @pytest.mark.asyncio
    async def test_apply_with_preset_dynamic(self, tmp_dir, clip_a, clip_b):
        out = tmp_dir / "preset_dynamic_out.mp4"
        result = await apply_transition(clip_a, clip_b, preset="dynamic",
                                        clip_type="broll", output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000


class TestBatchTransitions:
    """Test apply_transition_batch."""

    @pytest.mark.asyncio
    async def test_batch_three_clips(self, tmp_dir, clip_a, clip_b, clip_c):
        out = tmp_dir / "batch_out.mp4"
        result = await apply_transition_batch(
            [clip_a, clip_b, clip_c],
            transition_type="crossfade",
            duration=0.25,
            output_path=out,
        )
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000
        info = _probe_streams_sync(out)
        assert info["video_count"] >= 1
        assert info["audio_count"] >= 1
        # Duration ≈ 2 + 2 + 2 - 2*0.25 = 5.5
        dur = _probe_duration_sync(out)
        expected = 6.0 - 2 * 0.25
        assert abs(dur - expected) < 0.5, f"Expected ~{expected}s, got {dur}"

    @pytest.mark.asyncio
    async def test_batch_single_clip(self, tmp_dir, clip_a):
        """Single clip should be returned as-is."""
        result = await apply_transition_batch([clip_a])
        assert result == clip_a

    @pytest.mark.asyncio
    async def test_batch_empty(self):
        """Empty list should raise ValueError."""
        with pytest.raises(ValueError, match="at least 1 clip"):
            await apply_transition_batch([])

    @pytest.mark.asyncio
    async def test_batch_with_preset(self, tmp_dir, clip_a, clip_b, clip_c):
        out = tmp_dir / "batch_preset_out.mp4"
        result = await apply_transition_batch(
            [clip_a, clip_b, clip_c],
            preset="dynamic",
            clip_types=["talking_head", "broll", "talking_head"],
            output_path=out,
        )
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000


class TestFallback:
    """Test fallback behaviour when transitions fail."""

    @pytest.mark.asyncio
    async def test_fallback_concat(self, tmp_dir, clip_a, clip_b):
        """_fallback_concat should produce valid output."""
        out = tmp_dir / "fallback_out.mp4"
        ok = await _fallback_concat(clip_a, clip_b, out)
        assert ok, "Fallback concat should succeed"
        assert out.exists()
        assert out.stat().st_size > 1000
        info = _probe_streams_sync(out)
        assert info["video_count"] >= 1
        assert info["audio_count"] >= 1
        # Duration ≈ 2 + 2 = 4
        dur = _probe_duration_sync(out)
        expected = 4.0
        assert abs(dur - expected) < 0.3, f"Expected ~{expected}s, got {dur}"

    @pytest.mark.asyncio
    async def test_apply_transition_returns_input_a_on_total_failure(self, tmp_dir, clip_a):
        """When both transition and fallback fail, should return input_a."""
        # Use a nonexistent clip_b to force failure
        fake_b = tmp_dir / "nonexistent.mp4"
        out = tmp_dir / "total_fail_out.mp4"
        result = await apply_transition(clip_a, fake_b, output_path=out)
        assert result == clip_a, "Should return input_a unchanged on total failure"


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_zero_duration_transition(self, tmp_dir, clip_a, clip_b):
        """Zero-duration transition should still produce output."""
        out = tmp_dir / "zero_dur_out.mp4"
        result = await apply_transition(clip_a, clip_b, duration=0.0, output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    @pytest.mark.asyncio
    async def test_no_audio_input(self, tmp_dir, clip_a, clip_no_audio):
        """Transition with one clip missing audio should still work."""
        out = tmp_dir / "no_audio_out.mp4"
        result = await apply_transition(clip_a, clip_no_audio, output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000

    @pytest.mark.asyncio
    async def test_output_path_none(self, tmp_dir, clip_a, clip_b):
        """When output_path is None, should create a temp path."""
        result = await apply_transition(clip_a, clip_b)
        assert result != clip_a, "Should not return input_a unchanged"
        assert result.exists()
        assert result.stat().st_size > 1000

    @pytest.mark.asyncio
    async def test_different_sizes(self, tmp_dir):
        """Clips with different sizes should be normalised before transition."""
        small = tmp_dir / "small.mp4"
        large = tmp_dir / "large.mp4"
        _generate_test_clip(small, duration=1.5, width=720, height=1280, color="red")
        _generate_test_clip(large, duration=1.5, width=1920, height=1080, color="blue")
        out = tmp_dir / "diff_size_out.mp4"
        result = await apply_transition(small, large, output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000
        info = _probe_streams_sync(out)
        assert info["width"] == DEFAULT_WIDTH
        assert info["height"] == DEFAULT_HEIGHT


class TestTransitionsServiceModule:
    """Test module-level constants and structure."""

    def test_transition_types_set(self):
        assert "crossfade" in TRANSITION_TYPES
        assert "fade_black" in TRANSITION_TYPES
        assert "slide_left" in TRANSITION_TYPES
        assert len(TRANSITION_TYPES) == 3

    def test_presets_defined(self):
        assert "default" in PRESETS
        assert "dynamic" in PRESETS
        assert "description" in PRESETS["default"]
        assert "transition_for" in PRESETS["default"]

    def test_default_duration(self):
        assert DEFAULT_TRANSITION_DURATION == 0.25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
