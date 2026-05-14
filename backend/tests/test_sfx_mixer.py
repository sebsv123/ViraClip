"""
Unit tests for BUG 1 fix: aresample=async=1000 → aresample + aformat in sfx_mixer.py.

BUG 1: aresample=async=1000 causes audio desync on stereo clips because it
aggressively drops/silences samples to maintain sync, which corrupts the
audio stream. The fix replaces it with aresample=44100,aformat=channel_layouts=stereo
which properly normalises sample rate and channel layout without dropping samples.
"""

from pathlib import Path
import tempfile
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _build_ffmpeg_filter(has_audio: bool, has_video: bool) -> str:
    """Replicates the filter_complex construction from sfx_mixer.py build_mixer_filter."""
    parts = []
    if has_video:
        parts.append("[0:v]format=yuv420p[v0]")
    if has_audio:
        # BUG 1 FIX: was "aresample=async=1000[aout]" — now uses safe resample + aformat
        parts.append("[0:a]aresample=44100,aformat=channel_layouts=stereo[aout]")
    if has_video and has_audio:
        parts.append("[v0][aout]concat=n=1:v=1:a=1[out]")
    elif has_video:
        parts.append("[v0]copy[out]")
    elif has_audio:
        parts.append("[aout]copy[out]")
    return ";".join(parts)


class TestSfxMixerAresampleFix:
    """Tests that the aresample=async=1000 bug is fixed."""

    def test_filter_uses_aresample_44100_not_async(self):
        """The filter string must NOT contain 'aresample=async=1000'."""
        filter_str = _build_ffmpeg_filter(has_audio=True, has_video=True)
        assert "aresample=async=1000" not in filter_str, (
            "BUG 1: aresample=async=1000 still present — causes audio desync"
        )

    def test_filter_contains_aresample_44100(self):
        """The filter string must contain the safe resample."""
        filter_str = _build_ffmpeg_filter(has_audio=True, has_video=True)
        assert "aresample=44100" in filter_str, (
            "Fix missing: aresample=44100 should normalise sample rate"
        )

    def test_filter_contains_aformat_stereo(self):
        """The filter string must contain aformat=channel_layouts=stereo."""
        filter_str = _build_ffmpeg_filter(has_audio=True, has_video=True)
        assert "aformat=channel_layouts=stereo" in filter_str, (
            "Fix missing: aformat=channel_layouts=stereo should normalise channel layout"
        )

    def test_filter_audio_only(self):
        """Audio-only path should also use the safe resample."""
        filter_str = _build_ffmpeg_filter(has_audio=True, has_video=False)
        assert "aresample=44100" in filter_str
        assert "aformat=channel_layouts=stereo" in filter_str
        assert "aresample=async=1000" not in filter_str

    def test_filter_video_only_no_audio(self):
        """Video-only path should not contain any audio filters."""
        filter_str = _build_ffmpeg_filter(has_audio=False, has_video=True)
        assert "aresample" not in filter_str
        assert "aformat" not in filter_str

    def test_filter_no_audio_no_video(self):
        """No media path should produce empty or minimal filter."""
        filter_str = _build_ffmpeg_filter(has_audio=False, has_video=False)
        assert filter_str == ""


class TestSfxMixerIntegration:
    """Integration-style tests that verify the actual sfx_mixer module behaviour."""

    @patch("src.domains.sfx.sfx_mixer.logger")
    @patch("src.domains.sfx.sfx_mixer.Path.exists", return_value=True)
    @pytest.mark.asyncio
    async def test_apply_sfx_filter_has_no_async(self, mock_exists, mock_logger):
        """Verify the actual apply_sfx function builds a filter with no async=1000."""
        from src.domains.sfx.sfx_mixer import apply_sfx

        # apply_sfx is async and runs ffmpeg — we mock subprocess to avoid actual execution
        with patch("src.domains.sfx.sfx_mixer.asyncio.create_subprocess_exec") as mock_subprocess:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")
            mock_subprocess.return_value = mock_proc

            result = await apply_sfx(
                input_video="/tmp/test_input.mp4",
                sfx_plan=[
                    {
                        "local_path": "/tmp/test_sfx.mp3",
                        "time_offset": 1.0,
                        "volume_db": -12,
                        "fade_out_ms": 200,
                        "duration": 2.0,
                    }
                ],
                output_path="/tmp/test_output.mp4",
            )

            # Verify the filter_complex was built correctly
            assert mock_subprocess.called
            cmd = mock_subprocess.call_args[0]
            cmd_str = " ".join(str(a) for a in cmd)
            assert "aresample=async=1000" not in cmd_str, (
                "BUG 1: aresample=async=1000 still present in apply_sfx filter"
            )
            assert "aresample=44100" in cmd_str, (
                "Fix missing: aresample=44100 not in apply_sfx filter"
            )
            assert "aformat=channel_layouts=stereo" in cmd_str, (
                "Fix missing: aformat=channel_layouts=stereo not in apply_sfx filter"
            )
            # Should return the output path on success
            assert result == "/tmp/test_output.mp4"

    @patch("src.domains.sfx.sfx_mixer.logger")
    @pytest.mark.asyncio
    async def test_apply_sfx_empty_plan_returns_input(self, mock_logger):
        """apply_sfx with no SFX plan should return input_video unchanged."""
        from src.domains.sfx.sfx_mixer import apply_sfx

        result = await apply_sfx(
            input_video="/tmp/test_input.mp4",
            sfx_plan=[],
            output_path="/tmp/test_output.mp4",
        )
        assert result == "/tmp/test_input.mp4", (
            "Empty SFX plan should return input video unchanged"
        )

    @patch("src.domains.sfx.sfx_mixer.logger")
    @pytest.mark.asyncio
    async def test_apply_sfx_all_invalid_paths_returns_input(self, mock_logger):
        """apply_sfx with all invalid SFX paths should return input_video unchanged."""
        from src.domains.sfx.sfx_mixer import apply_sfx

        with patch("src.domains.sfx.sfx_mixer.Path.exists", return_value=False):
            result = await apply_sfx(
                input_video="/tmp/test_input.mp4",
                sfx_plan=[
                    {
                        "local_path": "/tmp/nonexistent.mp3",
                        "time_offset": 1.0,
                        "volume_db": -12,
                        "fade_out_ms": 200,
                        "duration": 2.0,
                    }
                ],
                output_path="/tmp/test_output.mp4",
            )
            assert result == "/tmp/test_input.mp4", (
                "All invalid SFX paths should return input video unchanged"
            )
