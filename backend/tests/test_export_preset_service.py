"""
Tests for the Export Preset Service (TikTok/Reels/Shorts formatting).

These tests generate a synthetic test video using ffmpeg, then verify that
the export preset service correctly applies cropping, scaling, and stacking.

Prerequisites:
  - ffmpeg and ffprobe available on PATH
  - ``src.services.export_preset_service`` module importable

Test strategy:
  1. Generate a short 1920×1080 (landscape) test video with a colour pattern + tone.
  2. Apply ``tiktok_basic`` preset → verify output is 1080×1920, H.264, AAC, 30 fps.
  3. Apply ``tiktok_stacked`` preset with two videos → verify vstack dimensions.
  4. Test graceful fallback when input does not exist.
  5. Test ``ExportPresetConfig.from_env()`` with mocked config.
  6. Test the convenience ``export_with_preset()`` function.
"""
from __future__ import annotations

import json
import subprocess as sp
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.services.export_preset_service import (
    ExportPresetConfig,
    ExportPresetService,
    Preset,
    export_with_preset,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _ffprobe(path: Path) -> Dict[str, Any]:
    """Run ffprobe and return parsed JSON output."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    result = sp.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _get_video_stream(probe: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first video stream from ffprobe output."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return None


def _get_audio_stream(probe: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first audio stream from ffprobe output."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            return stream
    return None


def _generate_test_video(
    path: Path,
    width: int = 1920,
    height: int = 1080,
    duration: float = 3.0,
    rate: int = 30,
    pattern: str = "smptebars",
) -> Path:
    """
    Generate a short synthetic test video using ffmpeg.

    Uses ``smptebars`` video source + ``sine`` audio tone so the file is
    self-contained and reproducible.
    """
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"{pattern}=size={width}x{height}:rate={rate}:duration={duration}",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(path),
    ]
    sp.run(cmd, capture_output=True, check=True, timeout=30)
    return path


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def test_video_landscape(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 1920×1080 landscape test video (3 seconds)."""
    tmp = tmp_path_factory.mktemp("videos")
    return _generate_test_video(tmp / "input_landscape.mp4", 1920, 1080)


@pytest.fixture(scope="module")
def test_video_portrait(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 1080×1920 portrait test video (3 seconds) — already 9:16."""
    tmp = tmp_path_factory.mktemp("videos")
    return _generate_test_video(tmp / "input_portrait.mp4", 1080, 1920)


@pytest.fixture(scope="module")
def test_video_second(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A second 1920×1080 video for stacking tests."""
    tmp = tmp_path_factory.mktemp("videos")
    return _generate_test_video(tmp / "input_second.mp4", 1920, 1080, pattern="smptehdbars")


# ── Tests: Preset enum ────────────────────────────────────────────────────────


class TestPresetEnum:
    """Verify the Preset enum values and aliases."""

    def test_tiktok_basic_value(self):
        assert Preset.TIKTOK_BASIC.value == "tiktok_basic"

    def test_tiktok_stacked_value(self):
        assert Preset.TIKTOK_STACKED.value == "tiktok_stacked"

    def test_reels_alias(self):
        assert Preset.REELS_BASIC.value == "reels_basic"

    def test_shorts_alias(self):
        assert Preset.SHORTS_BASIC.value == "shorts_basic"

    def test_from_string(self):
        assert Preset("tiktok_basic") == Preset.TIKTOK_BASIC
        assert Preset("tiktok_stacked") == Preset.TIKTOK_STACKED


# ── Tests: ExportPresetConfig ──────────────────────────────────────────────────


class TestExportPresetConfig:
    """Verify config creation and env override."""

    def test_defaults(self):
        """Default config has expected values."""
        cfg = ExportPresetConfig()
        assert cfg.output_width == 1080
        assert cfg.output_height == 1920
        assert cfg.video_bitrate == "10M"
        assert cfg.audio_bitrate == "128k"
        assert cfg.fps == 30
        assert cfg.video_codec == "libx264"
        assert cfg.audio_codec == "aac"
        assert cfg.pixel_format == "yuv420p"

    @patch("src.services.export_preset_service.get_config")
    def test_from_env(self, mock_get_config):
        """from_env reads overrides from config."""
        fake_cfg = MagicMock()
        fake_cfg.export_video_bitrate = "8M"
        fake_cfg.export_audio_bitrate = "96k"
        fake_cfg.export_fps = 24
        mock_get_config.return_value = fake_cfg

        cfg = ExportPresetConfig.from_env("tiktok_basic")
        assert cfg.video_bitrate == "8M"
        assert cfg.audio_bitrate == "96k"
        assert cfg.fps == 24
        # Non-overridden defaults should still be present
        assert cfg.output_width == 1080
        assert cfg.output_height == 1920


# ── Tests: ExportPresetService._apply_basic ────────────────────────────────────


class TestApplyBasic:
    """Integration tests for the basic (single-video) preset."""

    def test_output_exists(self, test_video_landscape: Path, tmp_path: Path):
        """Output file is created."""
        out = tmp_path / "output_basic.mp4"
        svc = ExportPresetService()
        result = svc._apply_basic(test_video_landscape, out, ExportPresetConfig())
        assert result == out
        assert out.exists()

    def test_output_dimensions_1080x1920(self, test_video_landscape: Path, tmp_path: Path):
        """Output is 1080×1920 (9:16 portrait)."""
        out = tmp_path / "output_basic.mp4"
        svc = ExportPresetService()
        svc._apply_basic(test_video_landscape, out, ExportPresetConfig())
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_output_codec_h264(self, test_video_landscape: Path, tmp_path: Path):
        """Video codec is H.264 (libx264)."""
        out = tmp_path / "output_basic.mp4"
        svc = ExportPresetService()
        svc._apply_basic(test_video_landscape, out, ExportPresetConfig())
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["codec_name"] == "h264"

    def test_output_audio_aac(self, test_video_landscape: Path, tmp_path: Path):
        """Audio codec is AAC."""
        out = tmp_path / "output_basic.mp4"
        svc = ExportPresetService()
        svc._apply_basic(test_video_landscape, out, ExportPresetConfig())
        probe = _ffprobe(out)
        audio = _get_audio_stream(probe)
        assert audio is not None
        assert audio["codec_name"] == "aac"

    def test_output_fps_30(self, test_video_landscape: Path, tmp_path: Path):
        """Output frame rate is 30 fps (or close to it)."""
        out = tmp_path / "output_basic.mp4"
        svc = ExportPresetService()
        svc._apply_basic(test_video_landscape, out, ExportPresetConfig())
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        # ffprobe reports avg_frame_rate as "30/1" or "30000/1001" etc.
        fps_str = vs.get("avg_frame_rate", "0/1")
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0
        assert fps == pytest.approx(30, abs=2), f"Expected ~30 fps, got {fps}"

    def test_portrait_input_passthrough(self, test_video_portrait: Path, tmp_path: Path):
        """A 1080×1920 input stays 1080×1920 after basic preset."""
        out = tmp_path / "output_portrait.mp4"
        svc = ExportPresetService()
        svc._apply_basic(test_video_portrait, out, ExportPresetConfig())
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_custom_bitrate(self, test_video_landscape: Path, tmp_path: Path):
        """Custom video bitrate is respected."""
        out = tmp_path / "output_bitrate.mp4"
        cfg = ExportPresetConfig(video_bitrate="5M", audio_bitrate="64k")
        svc = ExportPresetService()
        svc._apply_basic(test_video_landscape, out, cfg)
        assert out.exists()
        # Bitrate won't be exact, but file should be valid
        probe = _ffprobe(out)
        assert _get_video_stream(probe) is not None
        assert _get_audio_stream(probe) is not None


# ── Tests: ExportPresetService._apply_stacked ──────────────────────────────────


class TestApplyStacked:
    """Integration tests for the stacked (two-video) preset."""

    def test_output_exists(self, test_video_landscape: Path, test_video_second: Path, tmp_path: Path):
        """Output file is created with two inputs."""
        out = tmp_path / "output_stacked.mp4"
        svc = ExportPresetService()
        result = svc._apply_stacked(test_video_landscape, out, ExportPresetConfig(), test_video_second)
        assert result == out
        assert out.exists()

    def test_output_height_double_half(self, test_video_landscape: Path, test_video_second: Path, tmp_path: Path):
        """Stacked output height is 1920 (2 × 960 halves)."""
        out = tmp_path / "output_stacked.mp4"
        svc = ExportPresetService()
        svc._apply_stacked(test_video_landscape, out, ExportPresetConfig(), test_video_second)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["height"] == 1920

    def test_output_width_1080(self, test_video_landscape: Path, test_video_second: Path, tmp_path: Path):
        """Stacked output width is 1080."""
        out = tmp_path / "output_stacked.mp4"
        svc = ExportPresetService()
        svc._apply_stacked(test_video_landscape, out, ExportPresetConfig(), test_video_second)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080

    def test_fallback_without_secondary(self, test_video_landscape: Path, tmp_path: Path):
        """Without secondary_input, stacked falls back to basic."""
        out = tmp_path / "output_stacked_fallback.mp4"
        svc = ExportPresetService()
        result = svc._apply_stacked(test_video_landscape, out, ExportPresetConfig())
        assert result == out
        assert out.exists()
        # Should be basic crop (1080×1920)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920


# ── Tests: Graceful fallback ───────────────────────────────────────────────────


class TestGracefulFallback:
    """Verify that failures return the input path unchanged."""

    def test_nonexistent_input(self, tmp_path: Path):
        """Non-existent input returns input path."""
        fake_input = tmp_path / "does_not_exist.mp4"
        out = tmp_path / "output.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(str(fake_input), str(out), Preset.TIKTOK_BASIC)
        assert result == Path(fake_input)

    def test_invalid_secondary(self, test_video_landscape: Path, tmp_path: Path):
        """Stacked with non-existent secondary falls back to fast_vertical."""
        out = tmp_path / "output.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(
            str(test_video_landscape), str(out),
            Preset.TIKTOK_STACKED,
            secondary_input=str(tmp_path / "ghost.mp4"),
        )
        # Should fall back to fast_vertical and produce output
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_unknown_preset(self, test_video_landscape: Path, tmp_path: Path):
        """Unknown preset falls back gracefully."""
        out = tmp_path / "output.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(
            str(test_video_landscape), str(out),
            preset="nonexistent_preset",
        )
        # Should still produce output (falls back to basic)
        assert Path(out).exists() or result == Path(test_video_landscape)


# ── Tests: Convenience function ────────────────────────────────────────────────


class TestExportWithPresetFunction:
    """Verify the module-level convenience function."""

    def test_basic_preset(self, test_video_landscape: Path, tmp_path: Path):
        """export_with_preset() works with tiktok_basic."""
        out = tmp_path / "output_func.mp4"
        result = export_with_preset(
            str(test_video_landscape), str(out), Preset.TIKTOK_BASIC,
        )
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_stacked_preset(self, test_video_landscape: Path, test_video_second: Path, tmp_path: Path):
        """export_with_preset() works with tiktok_stacked."""
        out = tmp_path / "output_func_stacked.mp4"
        result = export_with_preset(
            str(test_video_landscape), str(out),
            Preset.TIKTOK_STACKED,
            secondary_input=str(test_video_second),
        )
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["height"] == 1920

    def test_string_preset_name(self, test_video_landscape: Path, tmp_path: Path):
        """export_with_preset() accepts string preset names."""
        out = tmp_path / "output_str.mp4"
        result = export_with_preset(str(test_video_landscape), str(out), preset="tiktok_basic")
        assert result == Path(out)
        assert out.exists()


# ── Tests: ExportPresetService.export_with_preset (public API) ─────────────────


class TestExportWithPresetPublicAPI:
    """Verify the public API method on ExportPresetService."""

    def test_tiktok_basic(self, test_video_landscape: Path, tmp_path: Path):
        """export_with_preset with tiktok_basic produces correct output."""
        out = tmp_path / "output_api.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(test_video_landscape, out, Preset.TIKTOK_BASIC)
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_reels_alias(self, test_video_landscape: Path, tmp_path: Path):
        """reels_basic alias works the same as tiktok_basic."""
        out = tmp_path / "output_reels.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(test_video_landscape, out, Preset.REELS_BASIC)
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_shorts_alias(self, test_video_landscape: Path, tmp_path: Path):
        """shorts_basic alias works the same as tiktok_basic."""
        out = tmp_path / "output_shorts.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(test_video_landscape, out, Preset.SHORTS_BASIC)
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_stacked(self, test_video_landscape: Path, test_video_second: Path, tmp_path: Path):
        """export_with_preset with tiktok_stacked produces correct output."""
        out = tmp_path / "output_api_stacked.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(
            test_video_landscape, out, Preset.TIKTOK_STACKED,
            secondary_input=test_video_second,
        )
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920


# ── Tests: fast_vertical preset ────────────────────────────────────────────────


class TestFastVertical:
    """Integration tests for the fast_vertical preset."""

    def test_output_exists(self, test_video_landscape: Path, tmp_path: Path):
        """Output file is created."""
        out = tmp_path / "output_fast.mp4"
        svc = ExportPresetService()
        result = svc._apply_fast_vertical(test_video_landscape, out)
        assert result == out
        assert out.exists()

    def test_output_dimensions_1080x1920(self, test_video_landscape: Path, tmp_path: Path):
        """Output is 1080×1920 (9:16 portrait)."""
        out = tmp_path / "output_fast.mp4"
        svc = ExportPresetService()
        svc._apply_fast_vertical(test_video_landscape, out)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_output_codec_h264(self, test_video_landscape: Path, tmp_path: Path):
        """Video codec is H.264 (libx264)."""
        out = tmp_path / "output_fast.mp4"
        svc = ExportPresetService()
        svc._apply_fast_vertical(test_video_landscape, out)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["codec_name"] == "h264"

    def test_output_audio_aac(self, test_video_landscape: Path, tmp_path: Path):
        """Audio codec is AAC."""
        out = tmp_path / "output_fast.mp4"
        svc = ExportPresetService()
        svc._apply_fast_vertical(test_video_landscape, out)
        probe = _ffprobe(out)
        audio = _get_audio_stream(probe)
        assert audio is not None
        assert audio["codec_name"] == "aac"

    def test_output_fps_30(self, test_video_landscape: Path, tmp_path: Path):
        """Output frame rate is 30 fps (or close to it)."""
        out = tmp_path / "output_fast.mp4"
        svc = ExportPresetService()
        svc._apply_fast_vertical(test_video_landscape, out)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        fps_str = vs.get("avg_frame_rate", "0/1")
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0
        assert fps == pytest.approx(30, abs=2), f"Expected ~30 fps, got {fps}"

    def test_portrait_input_passthrough(self, test_video_portrait: Path, tmp_path: Path):
        """A 1080×1920 input stays 1080×1920 after fast_vertical."""
        out = tmp_path / "output_fast_portrait.mp4"
        svc = ExportPresetService()
        svc._apply_fast_vertical(test_video_portrait, out)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_landscape_input_centered_crop(self, test_video_landscape: Path, tmp_path: Path):
        """A 1920×1080 input is centre-cropped to 9:16 (1080×1920)."""
        out = tmp_path / "output_fast_landscape.mp4"
        svc = ExportPresetService()
        svc._apply_fast_vertical(test_video_landscape, out)
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_via_public_api(self, test_video_landscape: Path, tmp_path: Path):
        """fast_vertical works via the public export_with_preset API."""
        out = tmp_path / "output_fast_api.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(
            test_video_landscape, out, Preset.FAST_VERTICAL,
        )
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_via_convenience_function(self, test_video_landscape: Path, tmp_path: Path):
        """fast_vertical works via the module-level convenience function."""
        out = tmp_path / "output_fast_func.mp4"
        result = export_with_preset(
            str(test_video_landscape), str(out), Preset.FAST_VERTICAL,
        )
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_string_preset_name(self, test_video_landscape: Path, tmp_path: Path):
        """fast_vertical works when passed as a string."""
        out = tmp_path / "output_fast_str.mp4"
        result = export_with_preset(
            str(test_video_landscape), str(out), preset="fast_vertical",
        )
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920


# ── Tests: Fallback to fast_vertical ───────────────────────────────────────────


class TestFallbackToFastVertical:
    """Verify that complex presets fall back to fast_vertical on failure."""

    def test_stacked_fallback_to_fast_vertical(
        self, test_video_landscape: Path, tmp_path: Path,
    ):
        """Stacked without secondary_input falls back to fast_vertical."""
        out = tmp_path / "output_stacked_fallback.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(
            test_video_landscape, out, Preset.TIKTOK_STACKED,
            secondary_input=tmp_path / "nonexistent.mp4",
        )
        # Should fall back to fast_vertical and produce output
        assert result == Path(out)
        assert out.exists()
        probe = _ffprobe(out)
        vs = _get_video_stream(probe)
        assert vs is not None
        assert vs["width"] == 1080
        assert vs["height"] == 1920

    def test_basic_fallback_to_fast_vertical(
        self, test_video_landscape: Path, tmp_path: Path,
    ):
        """If basic preset fails, it falls back to fast_vertical."""
        out = tmp_path / "output_basic_fallback.mp4"
        svc = ExportPresetService()
        # Simulate failure by passing a non-existent input
        result = svc.export_with_preset(
            tmp_path / "nonexistent.mp4", out, Preset.TIKTOK_BASIC,
        )
        # Should return the original input path (graceful fallback)
        assert result == Path(tmp_path / "nonexistent.mp4")

    def test_fast_vertical_does_not_self_fallback(
        self, test_video_landscape: Path, tmp_path: Path,
    ):
        """fast_vertical itself does not attempt a second fallback."""
        out = tmp_path / "output_no_self_fallback.mp4"
        svc = ExportPresetService()
        # Pass a non-existent input to fast_vertical directly
        result = svc.export_with_preset(
            tmp_path / "nonexistent.mp4", out, Preset.FAST_VERTICAL,
        )
        # Should return the original input path (no infinite loop)
        assert result == Path(tmp_path / "nonexistent.mp4")

    def test_unknown_preset_falls_back_to_fast_vertical(
        self, test_video_landscape: Path, tmp_path: Path,
    ):
        """Unknown preset falls back to basic, then fast_vertical on failure."""
        out = tmp_path / "output_unknown_fallback.mp4"
        svc = ExportPresetService()
        result = svc.export_with_preset(
            test_video_landscape, out, preset="nonexistent_preset",
        )
        # Should produce output via fallback chain
        assert Path(out).exists() or result == Path(test_video_landscape)
        if Path(out).exists():
            probe = _ffprobe(out)
            vs = _get_video_stream(probe)
            assert vs is not None
            assert vs["width"] == 1080
            assert vs["height"] == 1920
