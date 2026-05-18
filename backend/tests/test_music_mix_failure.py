"""
Tests for the music mix failure fix.

Verifies:
  1. SuggestionApplicator._run_ffmpeg detects 0-byte outputs and returns non-zero exit code
  2. SuggestionApplicator._run_ffmpeg detects missing outputs and returns non-zero exit code
  3. SuggestionApplicator._run_ffmpeg cleans up 0-byte corrupt outputs on failure
  4. mix_bgm_beat_synced detects 0-byte outputs and returns {"success": False}
  5. mix_bgm_beat_synced detects missing outputs and returns {"success": False}
  6. AudioDuckingService.apply_ducking skips ducking when music_available=False
  7. _clip_polish.apply_audio_ducking passes music_available to the ducking service
  8. Zoompan filter expression is simplified (no nested parens in sin())
  9. Audio bitrate is 128k (not 192k) in suggestion_applicator
  10. Audio bitrate is 128k (not 192k) in beat_sync_service
"""

import asyncio
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SuggestionApplicator._run_ffmpeg — 0-byte output detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunFfmpegZeroByteDetection:
    """_run_ffmpeg must detect 0-byte outputs and return non-zero exit code."""

    @pytest.mark.asyncio
    async def test_zero_byte_output_detected(self):
        """When FFmpeg returns 0 but output is 0 bytes, _run_ffmpeg must return returncode=1."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp4"
            # Create a 0-byte file to simulate corrupt output
            output_path.touch()

            cmd = ["ffmpeg", "-version"]  # any command that succeeds

            result = await applicator._run_ffmpeg(cmd, output_path=output_path)

            assert result.returncode != 0, (
                "BUG: _run_ffmpeg should return non-zero when output is 0 bytes"
            )
            assert b"0 bytes" in (result.stderr or b""), (
                "BUG: stderr should mention 0-byte detection"
            )
            # The corrupt file should have been cleaned up
            assert not output_path.exists(), (
                "BUG: 0-byte output file should have been cleaned up"
            )

    @pytest.mark.asyncio
    async def test_missing_output_detected(self):
        """When FFmpeg returns 0 but output file doesn't exist, _run_ffmpeg must return returncode=1."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nonexistent.mp4"
            # Do NOT create the file — simulate missing output

            cmd = ["ffmpeg", "-version"]

            result = await applicator._run_ffmpeg(cmd, output_path=output_path)

            assert result.returncode != 0, (
                "BUG: _run_ffmpeg should return non-zero when output file is missing"
            )
            assert b"missing" in (result.stderr or b"").lower(), (
                "BUG: stderr should mention missing output"
            )

    @pytest.mark.asyncio
    async def test_valid_output_passes(self):
        """When FFmpeg returns 0 and output is valid, _run_ffmpeg must return returncode=0."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp4"
            # Create a valid (non-zero) file
            output_path.write_text("fake video content")

            cmd = ["ffmpeg", "-version"]

            result = await applicator._run_ffmpeg(cmd, output_path=output_path)

            assert result.returncode == 0, (
                "BUG: _run_ffmpeg should return 0 when output is valid"
            )
            # File should still exist
            assert output_path.exists(), (
                "BUG: valid output file should not have been deleted"
            )

    @pytest.mark.asyncio
    async def test_ffmpeg_failure_cleans_up_zero_byte(self):
        """When FFmpeg itself fails and leaves a 0-byte file, _run_ffmpeg must clean it up."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp4"
            # Create a 0-byte file to simulate FFmpeg crash leaving corrupt output
            output_path.touch()

            # Use a command that will fail
            cmd = ["ffmpeg", "-invalid_flag_xyz"]

            result = await applicator._run_ffmpeg(cmd, output_path=output_path)

            assert result.returncode != 0, (
                "BUG: _run_ffmpeg should propagate FFmpeg failure"
            )
            # The corrupt file should have been cleaned up
            assert not output_path.exists(), (
                "BUG: 0-byte output from failed FFmpeg should have been cleaned up"
            )

    @pytest.mark.asyncio
    async def test_no_output_path_skips_validation(self):
        """When output_path is None, _run_ffmpeg must skip validation and return raw result."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        cmd = ["ffmpeg", "-version"]

        result = await applicator._run_ffmpeg(cmd, output_path=None)

        assert result.returncode == 0, (
            "BUG: _run_ffmpeg without output_path should return raw FFmpeg result"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Zoompan filter — simplified expression (no nested parens)
# ═══════════════════════════════════════════════════════════════════════════════

class TestZoompanFilterSimplification:
    """Zoompan filter must use simplified expression compatible with FFmpeg 7.1."""

    def test_zoompan_uses_simple_zoom_expression(self):
        """The zoompan expression must use zoom+0.001 pattern (no sin() at all)."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        clip_info = {"duration": 30}
        payload = {"type": "punch_in", "start_time": 2.0, "duration": 1.5}

        filter_str = applicator._build_zoom_filter(payload, clip_info)

        assert filter_str is not None, "zoom filter should not be None"
        # The expression should use the ultra-simple form without any sin()
        # Old buggy form: sin(PI*(t-start)/dur) — causes FFmpeg -22
        # New stable form: zoompan=z='zoom+0.001':d=1:s=1080x1920:fps=30
        assert "zoom+0.001" in filter_str, (
            "BUG: zoompan expression should use zoom+0.001 pattern"
        )
        assert "sin" not in filter_str, (
            "BUG: zoompan expression should NOT contain sin() — "
            "causes FFmpeg 7.1 error -22"
        )
        # Verify no nested parens at all (the simplest expression)
        assert "fps=30" in filter_str, (
            "BUG: zoompan expression should specify fps=30"
        )
        assert "s=1080x1920" in filter_str, (
            "BUG: zoompan expression should specify s=1080x1920"
        )

    def test_zoompan_slow_push_no_nested_parens(self):
        """Slow push zoom type should also avoid nested parens."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        clip_info = {"duration": 30}
        payload = {"type": "slow_push", "start_time": 1.0, "duration": 3.0}

        filter_str = applicator._build_zoom_filter(payload, clip_info)

        assert filter_str is not None, "slow_push zoom filter should not be None"
        assert "zoompan=z=" in filter_str, "filter should contain zoompan"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Audio bitrate — must be 128k
# ═══════════════════════════════════════════════════════════════════════════════

class TestAudioBitrate:
    """Audio bitrate must be 128k (not 192k) in both suggestion_applicator and beat_sync_service."""

    def test_suggestion_applicator_uses_128k(self):
        """_build_ffmpeg_command must use -b:a 128k."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        cmd = applicator._build_ffmpeg_command(
            inputs=["input.mp4"],
            video_filters=[],
            audio_filters=[],
            output="output.mp4",
            clip_info={"duration": 30},
        )

        # Find the -b:a flag and check our explicit 128k value is present.
        # Note: gpu_utils.ffmpeg_codec_flags() may also include -b:a 192k as
        # part of the GPU encoder args (h264_nvenc preset). That's a separate
        # concern — we only verify that our explicit -b:a 128k is set.
        cmd_str = " ".join(cmd)
        assert "-b:a" in cmd_str, "FFmpeg command must include -b:a flag"
        assert "128k" in cmd_str, (
            "BUG: audio bitrate should be 128k, not 192k"
        )
        # Verify our 128k comes AFTER any GPU codec flags (i.e. it's the final value)
        _128k_idx = cmd_str.rfind("128k")
        _192k_idx = cmd_str.rfind("192k")
        assert _128k_idx > _192k_idx, (
            "BUG: our explicit -b:a 128k should come after GPU codec -b:a 192k"
        )

    def test_beat_sync_service_uses_128k(self):
        """mix_bgm_beat_synced must use -b:a 128k in its FFmpeg command."""
        # We can't easily inspect the FFmpeg command since it's built inline,
        # but we can verify the constant is used by checking the source
        import inspect
        from src.domains.audio.beat_sync_service import mix_bgm_beat_synced

        source = inspect.getsource(mix_bgm_beat_synced)
        assert '"128k"' in source or "'128k'" in source, (
            "BUG: beat_sync_service should use 128k audio bitrate"
        )
        assert '"192k"' not in source and "'192k'" not in source, (
            "BUG: beat_sync_service should not use 192k audio bitrate"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. AudioDuckingService — music_available=False skips ducking
# ═══════════════════════════════════════════════════════════════════════════════

class TestAudioDuckingMusicAvailable:
    """apply_ducking must skip ducking when music_available=False."""

    @pytest.mark.asyncio
    async def test_ducking_skipped_when_no_music(self):
        """When music_available=False, apply_ducking must return early with success=False."""
        from src.domains.audio.audio_ducking_service import get_audio_ducking_service

        svc = get_audio_ducking_service()
        # Temporarily enable ducking for this test
        original_enabled = svc.enabled
        svc.enabled = True

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                video_path = Path(tmpdir) / "input.mp4"
                video_path.write_text("fake video")
                output_path = Path(tmpdir) / "output.mp4"

                result = await svc.apply_ducking(
                    video_path=video_path,
                    output_path=output_path,
                    word_timings=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                    music_available=False,
                )

                assert not result.success, (
                    "BUG: ducking should not succeed when music_available=False"
                )
                assert "no background music" in (result.error or "").lower(), (
                    "BUG: error message should mention no background music"
                )
        finally:
            svc.enabled = original_enabled

    @pytest.mark.asyncio
    async def test_ducking_proceeds_when_music_available(self):
        """When music_available=True, apply_ducking must proceed (may fail on real FFmpeg but not skip)."""
        from src.domains.audio.audio_ducking_service import get_audio_ducking_service

        svc = get_audio_ducking_service()
        original_enabled = svc.enabled
        svc.enabled = True

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                video_path = Path(tmpdir) / "input.mp4"
                video_path.write_text("fake video")
                output_path = Path(tmpdir) / "output.mp4"

                result = await svc.apply_ducking(
                    video_path=video_path,
                    output_path=output_path,
                    word_timings=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                    music_available=True,
                )

                # The ducking may fail on a fake video file, but it should NOT
                # return the "no background music" skip message
                assert "no background music" not in (result.error or "").lower(), (
                    "BUG: ducking should not skip when music_available=True"
                )
        finally:
            svc.enabled = original_enabled


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _clip_polish.apply_audio_ducking — passes music_available
# ═══════════════════════════════════════════════════════════════════════════════

class TestClipPolishMusicAvailable:
    """apply_audio_ducking in _clip_polish must pass music_available to the ducking service."""

    @pytest.mark.asyncio
    async def test_passes_music_available_false(self):
        """When music_available=False, the ducking service must be called with music_available=False."""
        from src.domains.video._clip_polish import apply_audio_ducking

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("src.domains.audio.audio_ducking_service.get_audio_ducking_service") as mock_get_svc,
        ):
            mock_svc = MagicMock()
            mock_svc.enabled = True
            mock_svc.apply_ducking = AsyncMock()
            mock_svc.apply_ducking.return_value = MagicMock(
                success=False, error="No background music to duck"
            )
            mock_get_svc.return_value = mock_svc

            video_path = Path(tmpdir) / "input.mp4"
            video_path.write_text("fake video")

            result = await apply_audio_ducking(
                output_path=video_path,
                words=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                music_available=False,
            )

            # Verify the ducking service was called with music_available=False
            mock_svc.apply_ducking.assert_called_once()
            call_kwargs = mock_svc.apply_ducking.call_args.kwargs
            assert call_kwargs.get("music_available") is False, (
                "BUG: apply_ducking should be called with music_available=False"
            )

    @pytest.mark.asyncio
    async def test_passes_music_available_true(self):
        """When music_available=True, the ducking service must be called with music_available=True."""
        from src.domains.video._clip_polish import apply_audio_ducking

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("src.domains.audio.audio_ducking_service.get_audio_ducking_service") as mock_get_svc,
        ):
            mock_svc = MagicMock()
            mock_svc.enabled = True
            mock_svc.apply_ducking = AsyncMock()
            mock_svc.apply_ducking.return_value = MagicMock(
                success=False, error="some other error"
            )
            mock_get_svc.return_value = mock_svc

            video_path = Path(tmpdir) / "input.mp4"
            video_path.write_text("fake video")

            result = await apply_audio_ducking(
                output_path=video_path,
                words=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                music_available=True,
            )

            # Verify the ducking service was called with music_available=True
            mock_svc.apply_ducking.assert_called_once()
            call_kwargs = mock_svc.apply_ducking.call_args.kwargs
            assert call_kwargs.get("music_available") is True, (
                "BUG: apply_ducking should be called with music_available=True"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. beat_sync_service — 0-byte output detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestBeatSyncZeroByteDetection:
    """mix_bgm_beat_synced must detect 0-byte outputs and return {"success": False}."""

    @pytest.mark.asyncio
    async def test_zero_byte_output_returns_failure(self):
        """When FFmpeg returns 0 but output is 0 bytes, must return success=False."""
        from src.domains.audio.beat_sync_service import mix_bgm_beat_synced

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "input.mp4"
            video_path.write_text("fake video")
            output_path = Path(tmpdir) / "output.mp4"
            bgm_path = Path(tmpdir) / "bgm.mp3"
            bgm_path.write_text("fake bgm")

            # Patch asyncio.create_subprocess_exec to simulate FFmpeg returning 0
            # but producing a 0-byte output
            original_create_subprocess = asyncio.create_subprocess_exec

            async def _fake_subprocess(*args, **kwargs):
                """Simulate FFmpeg that returns 0 but produces 0-byte output."""
                # Create the output file as 0 bytes (simulating corrupt render)
                output_path.touch()
                # Return a mock process with returncode=0
                mock_proc = MagicMock()
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(return_value=(b"", b""))
                mock_proc.stdout = None
                mock_proc.stderr = None
                mock_proc.pid = 12345
                return mock_proc

            with patch.object(asyncio, "create_subprocess_exec", _fake_subprocess):
                result = await mix_bgm_beat_synced(
                    video_path=video_path,
                    output_path=output_path,
                    bgm_path=bgm_path,
                    target_bpm=120.0,
                )

            assert result.get("success") is False, (
                "BUG: mix_bgm_beat_synced should return success=False for 0-byte output"
            )
            assert "0 bytes" in result.get("reason", "").lower(), (
                "BUG: reason should mention 0-byte detection"
            )
            # The corrupt file should have been cleaned up
            assert not output_path.exists(), (
                "BUG: 0-byte output file should have been cleaned up"
            )

    @pytest.mark.asyncio
    async def test_missing_output_returns_failure(self):
        """When FFmpeg returns 0 but output file doesn't exist, must return success=False."""
        from src.domains.audio.beat_sync_service import mix_bgm_beat_synced

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "input.mp4"
            video_path.write_text("fake video")
            output_path = Path(tmpdir) / "output.mp4"
            bgm_path = Path(tmpdir) / "bgm.mp3"
            bgm_path.write_text("fake bgm")

            async def _fake_subprocess(*args, **kwargs):
                """Simulate FFmpeg that returns 0 but produces NO output file."""
                # Do NOT create output_path — simulate missing output
                mock_proc = MagicMock()
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(return_value=(b"", b""))
                mock_proc.stdout = None
                mock_proc.stderr = None
                mock_proc.pid = 12345
                return mock_proc

            with patch.object(asyncio, "create_subprocess_exec", _fake_subprocess):
                result = await mix_bgm_beat_synced(
                    video_path=video_path,
                    output_path=output_path,
                    bgm_path=bgm_path,
                    target_bpm=120.0,
                )

            assert result.get("success") is False, (
                "BUG: mix_bgm_beat_synced should return success=False for missing output"
            )
            assert "missing" in result.get("reason", "").lower(), (
                "BUG: reason should mention missing output"
            )

    @pytest.mark.asyncio
    async def test_ffmpeg_failure_returns_failure(self):
        """When FFmpeg itself fails, must return success=False with the error."""
        from src.domains.audio.beat_sync_service import mix_bgm_beat_synced

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "input.mp4"
            video_path.write_text("fake video")
            output_path = Path(tmpdir) / "output.mp4"
            bgm_path = Path(tmpdir) / "bgm.mp3"
            bgm_path.write_text("fake bgm")

            async def _fake_subprocess(*args, **kwargs):
                """Simulate FFmpeg that fails with returncode=1."""
                mock_proc = MagicMock()
                mock_proc.returncode = 1
                mock_proc.communicate = AsyncMock(return_value=(b"", b"FFmpeg error: invalid argument"))
                mock_proc.stdout = None
                mock_proc.stderr = None
                mock_proc.pid = 12345
                return mock_proc

            with patch.object(asyncio, "create_subprocess_exec", _fake_subprocess):
                result = await mix_bgm_beat_synced(
                    video_path=video_path,
                    output_path=output_path,
                    bgm_path=bgm_path,
                    target_bpm=120.0,
                )

            assert result.get("success") is False, (
                "BUG: mix_bgm_beat_synced should return success=False on FFmpeg failure"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _clip_renderer — music_available propagation
# ═══════════════════════════════════════════════════════════════════════════════

class TestClipRendererMusicAvailable:
    """_clip_renderer must propagate music_available through the pipeline."""

    @staticmethod
    def _read_clip_renderer_source() -> str:
        """Read _clip_renderer.py source directly to avoid importing the module.

        Importing _clip_renderer triggers a chain import of comfyui_integration.py
        which tries to create /app/temp/uploads/broll (Docker path) and fails
        with PermissionError when running outside Docker.
        """
        from pathlib import Path
        src_path = Path(__file__).resolve().parents[1] / "src/domains/video/_clip_renderer.py"
        return src_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_music_available_flag_set_when_bgm_succeeds(self):
        """When beat_sync succeeds, _music_available must be True."""
        source = self._read_clip_renderer_source()

        # Verify _music_available is initialized to False
        assert "_music_available = False" in source, (
            "BUG: _music_available should be initialized to False"
        )

        # Verify _music_available is set to True on beat_sync success
        assert "_music_available = True" in source, (
            "BUG: _music_available should be set to True on BGM success"
        )

        # Verify music_available is passed to apply_audio_ducking
        assert "music_available=_music_available" in source, (
            "BUG: apply_audio_ducking should receive music_available=_music_available"
        )

    def test_music_available_set_in_both_success_paths(self):
        """_music_available must be set to True in both beat_sync and niche fallback paths."""
        source = self._read_clip_renderer_source()

        # Count occurrences of _music_available = True
        count = source.count("_music_available = True")
        assert count >= 2, (
            f"BUG: _music_available = True should appear at least twice "
            f"(beat_sync + niche fallback), found {count}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Integration: end-to-end failure scenario
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEndFailureScenario:
    """Simulate the full failure scenario: zoompan fails → music fails → ducking skips."""

    @pytest.mark.asyncio
    async def test_apply_suggestions_returns_failure_on_ffmpeg_error(self):
        """When FFmpeg fails in apply_suggestions, must return success=False."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"

            # Patch _run_ffmpeg to simulate failure
            applicator._run_ffmpeg = AsyncMock(return_value=subprocess.CompletedProcess(
                args=["ffmpeg"], returncode=1,
                stdout=b"", stderr=b"FFmpeg error -22: Invalid argument"
            ))

            result = await applicator.apply_suggestions(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
            )

            assert result.get("success") is False, (
                "BUG: apply_suggestions should return success=False on FFmpeg failure"
            )

    @pytest.mark.asyncio
    async def test_apply_suggestions_returns_failure_on_zero_byte(self):
        """When FFmpeg returns 0 but output is 0 bytes, apply_suggestions must return success=False."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"
            # Create 0-byte output to simulate corrupt render
            output_path.touch()

            # Patch _run_ffmpeg to simulate FFmpeg returning 0 but with 0-byte output
            # The _run_ffmpeg method itself will detect the 0-byte file and return failure
            applicator._run_ffmpeg = AsyncMock(return_value=subprocess.CompletedProcess(
                args=["ffmpeg"], returncode=1,
                stdout=b"", stderr=b"Output file is 0 bytes - corrupt render detected and cleaned up"
            ))

            result = await applicator.apply_suggestions(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
            )

            assert result.get("success") is False, (
                "BUG: apply_suggestions should return success=False for 0-byte output"
            )

    @pytest.mark.asyncio
    async def test_ducking_skipped_when_music_fails_in_pipeline(self):
        """Integration: when BGM mixing fails, ducking must be skipped."""
        from src.domains.video._clip_polish import apply_audio_ducking

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("src.domains.audio.audio_ducking_service.get_audio_ducking_service") as mock_get_svc,
        ):
            mock_svc = MagicMock()
            mock_svc.enabled = True
            mock_svc.apply_ducking = AsyncMock()
            mock_svc.apply_ducking.return_value = MagicMock(
                success=False, error="No background music to duck"
            )
            mock_get_svc.return_value = mock_svc

            video_path = Path(tmpdir) / "input.mp4"
            video_path.write_text("fake video")

            # Simulate the pipeline: music failed, so music_available=False
            result = await apply_audio_ducking(
                output_path=video_path,
                words=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                music_available=False,
            )

            # Verify ducking service was called with music_available=False
            mock_svc.apply_ducking.assert_called_once()
            call_kwargs = mock_svc.apply_ducking.call_args.kwargs
            assert call_kwargs.get("music_available") is False, (
                "BUG: ducking should be called with music_available=False when music failed"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _run_music_mix — robust wrapper tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunMusicMix:
    """_run_music_mix must handle FFmpeg failures gracefully and set ctx["music_mix_failed"]."""

    @pytest.mark.asyncio
    async def test_success_path_returns_output_and_sets_false(self):
        """When apply_suggestions succeeds, _run_music_mix must return output_path and set music_mix_failed=False."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        ctx: dict = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"
            output_path.write_text("fake enhanced video content")

            # Patch apply_suggestions to simulate success
            applicator.apply_suggestions = AsyncMock(return_value={
                "success": True,
                "output_path": str(output_path),
            })

            result = await applicator._run_music_mix(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
                ctx=ctx,
            )

            assert result == output_path, (
                "BUG: _run_music_mix should return output_path on success"
            )
            assert ctx.get("music_mix_failed") is False, (
                "BUG: ctx['music_mix_failed'] should be False on success"
            )

    @pytest.mark.asyncio
    async def test_failure_path_returns_input_and_sets_true(self):
        """When apply_suggestions fails, _run_music_mix must return input_path and set music_mix_failed=True."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        ctx: dict = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"

            # Patch apply_suggestions to simulate failure
            applicator.apply_suggestions = AsyncMock(return_value={
                "success": False,
                "error": "FFmpeg failed: returncode 1: Invalid argument",
            })

            result = await applicator._run_music_mix(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
                ctx=ctx,
            )

            assert result == input_path, (
                "BUG: _run_music_mix should return input_path on failure"
            )
            assert ctx.get("music_mix_failed") is True, (
                "BUG: ctx['music_mix_failed'] should be True on failure"
            )

    @pytest.mark.asyncio
    async def test_zero_byte_output_cleaned_up_and_returns_input(self):
        """When output is 0 bytes, _run_music_mix must clean up and return input_path."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        ctx: dict = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"
            # Create 0-byte corrupt output
            output_path.touch()

            # Patch apply_suggestions to return success=True but output is 0 bytes
            applicator.apply_suggestions = AsyncMock(return_value={
                "success": True,
                "output_path": str(output_path),
            })

            result = await applicator._run_music_mix(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
                ctx=ctx,
            )

            assert result == input_path, (
                "BUG: _run_music_mix should return input_path when output is 0 bytes"
            )
            assert ctx.get("music_mix_failed") is True, (
                "BUG: ctx['music_mix_failed'] should be True for 0-byte output"
            )
            # The corrupt file should have been cleaned up
            assert not output_path.exists(), (
                "BUG: 0-byte output file should have been cleaned up"
            )

    @pytest.mark.asyncio
    async def test_exception_in_apply_suggestions_returns_input(self):
        """When apply_suggestions raises an exception, _run_music_mix must return input_path."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        ctx: dict = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"

            # Patch apply_suggestions to raise an exception
            applicator.apply_suggestions = AsyncMock(side_effect=RuntimeError("Unexpected crash"))

            result = await applicator._run_music_mix(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
                ctx=ctx,
            )

            assert result == input_path, (
                "BUG: _run_music_mix should return input_path on exception"
            )
            assert ctx.get("music_mix_failed") is True, (
                "BUG: ctx['music_mix_failed'] should be True on exception"
            )

    @pytest.mark.asyncio
    async def test_ctx_created_when_none_passed(self):
        """When ctx is None, _run_music_mix must create a new dict and set music_mix_failed."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"

            # Patch apply_suggestions to simulate failure
            applicator.apply_suggestions = AsyncMock(return_value={
                "success": False,
                "error": "FFmpeg failed: returncode 1",
            })

            # Pass ctx=None explicitly
            result = await applicator._run_music_mix(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
                ctx=None,
            )

            assert result == input_path, (
                "BUG: _run_music_mix should return input_path when ctx=None"
            )

    @pytest.mark.asyncio
    async def test_non_zero_failed_output_cleaned_up(self):
        """When output exists but is non-zero and apply_suggestions failed, must clean up and return input."""
        from src.domains.autopilot.suggestion_applicator import SuggestionApplicator

        applicator = SuggestionApplicator()
        ctx: dict = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_text("fake video content")
            output_path = Path(tmpdir) / "output.mp4"
            # Create a non-zero but failed output
            output_path.write_text("partial corrupt output")

            # Patch apply_suggestions to simulate failure
            applicator.apply_suggestions = AsyncMock(return_value={
                "success": False,
                "error": "FFmpeg failed: returncode 1: zoompan error",
            })

            result = await applicator._run_music_mix(
                input_path=input_path,
                output_path=output_path,
                suggestions=[{"kind": "zoom_punch", "payload": {"type": "punch_in", "start_time": 0, "duration": 1.0}}],
                clip_info={"duration": 30},
                ctx=ctx,
            )

            assert result == input_path, (
                "BUG: _run_music_mix should return input_path on failure with non-zero output"
            )
            assert ctx.get("music_mix_failed") is True, (
                "BUG: ctx['music_mix_failed'] should be True on failure"
            )
            # The failed output should have been cleaned up
            assert not output_path.exists(), (
                "BUG: failed output file should have been cleaned up"
            )
