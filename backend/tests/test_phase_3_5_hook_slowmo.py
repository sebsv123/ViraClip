"""
Unit Tests — Phase 3.5: Hook Slow-Motion
==========================================
Tests for apply_hook_slowmo, maybe_apply_hook_slowmo, capability detection,
FFmpeg command construction, and pipeline integration.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
#  get_slowmo_capabilities
# ─────────────────────────────────────────────────────────────────────────────

class TestSlowmoCapabilities:
    """Test capability detection."""

    def test_returns_expected_keys(self):
        from video_processing.hook_slowmo import get_slowmo_capabilities

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="minterpolate", returncode=0)
            caps = get_slowmo_capabilities()

        assert "minterpolate_available" in caps
        assert "enabled" in caps
        assert "default_duration" in caps
        assert "default_speed" in caps
        assert "min_virality_score" in caps

    def test_minterpolate_detected_when_present(self):
        from video_processing.hook_slowmo import get_slowmo_capabilities

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="minterpolate xfade scale", returncode=0)
            caps = get_slowmo_capabilities()

        assert caps["minterpolate_available"] is True

    def test_minterpolate_absent_when_not_in_output(self):
        from video_processing.hook_slowmo import get_slowmo_capabilities

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="scale fade overlay", returncode=0)
            caps = get_slowmo_capabilities()

        assert caps["minterpolate_available"] is False


# ─────────────────────────────────────────────────────────────────────────────
#  apply_hook_slowmo — input validation
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyHookSlowmoValidation:
    """Test input validation and graceful failures."""

    def test_returns_false_when_input_missing(self, tmp_path):
        from video_processing.hook_slowmo import apply_hook_slowmo

        result = apply_hook_slowmo(
            tmp_path / "nonexistent.mp4",
            tmp_path / "out.mp4",
        )
        assert result is False

    def test_returns_false_for_invalid_speed_factor(self, tmp_path):
        from video_processing.hook_slowmo import apply_hook_slowmo

        (tmp_path / "clip.mp4").write_bytes(b"\x00" * 100)
        result = apply_hook_slowmo(
            tmp_path / "clip.mp4",
            tmp_path / "out.mp4",
            speed_factor=0.0,
        )
        assert result is False

    def test_returns_false_for_speed_above_1(self, tmp_path):
        from video_processing.hook_slowmo import apply_hook_slowmo

        (tmp_path / "clip.mp4").write_bytes(b"\x00" * 100)
        result = apply_hook_slowmo(
            tmp_path / "clip.mp4",
            tmp_path / "out.mp4",
            speed_factor=1.5,
        )
        assert result is False

    def test_returns_false_when_clip_too_short(self, tmp_path):
        from video_processing.hook_slowmo import apply_hook_slowmo

        (tmp_path / "clip.mp4").write_bytes(b"\x00" * 100)

        with patch("video_processing.hook_slowmo._probe_duration", return_value=0.3):
            result = apply_hook_slowmo(
                tmp_path / "clip.mp4",
                tmp_path / "out.mp4",
            )

        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
#  apply_hook_slowmo — execution paths
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyHookSlowmoExecution:
    """Test slowmo application with mocked ffmpeg."""

    def _make_clip(self, tmp_path: Path) -> Path:
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"\x00" * 200)
        return p

    def test_calls_ffmpeg_with_setpts(self, tmp_path):
        from video_processing.hook_slowmo import apply_hook_slowmo

        clip = self._make_clip(tmp_path)
        out = tmp_path / "out.mp4"
        call_args = []

        def fake_run(cmd, **kwargs):
            call_args.append(cmd)
            # Create output file to simulate success
            for arg in cmd:
                if isinstance(arg, str) and arg.endswith(".mp4") and "out" in arg:
                    Path(arg).write_bytes(b"\x00" * 500)
                elif isinstance(arg, str) and arg.startswith("/") and arg.endswith(".mp4"):
                    Path(arg).write_bytes(b"\x00" * 500)
            return MagicMock(returncode=0, stdout="5.0\n", stderr=b"")

        with patch("video_processing.hook_slowmo._probe_duration", return_value=10.0), \
             patch("subprocess.run", side_effect=fake_run):
            apply_hook_slowmo(clip, out, speed_factor=0.5)

        # Check that setpts appeared in at least one ffmpeg call
        setpts_found = any(
            "setpts" in str(arg)
            for cmd_list in call_args
            for arg in cmd_list
        )
        assert setpts_found

    def test_applies_atempo_for_audio(self, tmp_path):
        from video_processing.hook_slowmo import apply_hook_slowmo

        clip = self._make_clip(tmp_path)
        out = tmp_path / "out.mp4"
        call_args = []

        def fake_run(cmd, **kwargs):
            call_args.append(cmd)
            return MagicMock(returncode=0, stdout="5.0\n", stderr=b"")

        with patch("video_processing.hook_slowmo._probe_duration", return_value=10.0), \
             patch("subprocess.run", side_effect=fake_run):
            apply_hook_slowmo(clip, out, speed_factor=0.5)

        atempo_found = any(
            "atempo" in str(arg)
            for cmd_list in call_args
            for arg in cmd_list
        )
        assert atempo_found


# ─────────────────────────────────────────────────────────────────────────────
#  _probe_duration
# ─────────────────────────────────────────────────────────────────────────────

class TestProbeDuration:
    """Test ffprobe duration parsing."""

    def test_returns_float_when_successful(self, tmp_path):
        from video_processing.hook_slowmo import _probe_duration

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="15.500000\n", returncode=0
            )
            dur = _probe_duration(tmp_path / "clip.mp4")

        assert dur == pytest.approx(15.5)

    def test_returns_none_on_parse_failure(self, tmp_path):
        from video_processing.hook_slowmo import _probe_duration

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=1)
            dur = _probe_duration(tmp_path / "clip.mp4")

        assert dur is None

    def test_returns_none_on_exception(self, tmp_path):
        from video_processing.hook_slowmo import _probe_duration

        with patch("subprocess.run", side_effect=Exception("ffprobe not found")):
            dur = _probe_duration(tmp_path / "clip.mp4")

        assert dur is None


# ─────────────────────────────────────────────────────────────────────────────
#  maybe_apply_hook_slowmo
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeApplyHookSlowmo:
    """Test conditional application based on env flag and virality score."""

    def test_skips_when_disabled(self, tmp_path):
        from video_processing import hook_slowmo

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"\x00" * 100)

        with patch.object(hook_slowmo, "HOOK_SLOWMO_ENABLED", False):
            result = hook_slowmo.maybe_apply_hook_slowmo(clip, virality_score=90)

        assert result is False

    def test_skips_when_score_below_threshold(self, tmp_path):
        from video_processing import hook_slowmo

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"\x00" * 100)

        with patch.object(hook_slowmo, "HOOK_SLOWMO_ENABLED", True), \
             patch.object(hook_slowmo, "MIN_VIRALITY_SCORE", 70):
            result = hook_slowmo.maybe_apply_hook_slowmo(clip, virality_score=60)

        assert result is False

    def test_applies_when_enabled_and_score_high(self, tmp_path):
        from video_processing import hook_slowmo

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"\x00" * 100)

        with patch.object(hook_slowmo, "HOOK_SLOWMO_ENABLED", True), \
             patch.object(hook_slowmo, "MIN_VIRALITY_SCORE", 70), \
             patch("video_processing.hook_slowmo.apply_hook_slowmo", return_value=True) as mock_apply:
            # Create the output file that apply_hook_slowmo would create
            (tmp_path / f"_sm_{clip.name}").write_bytes(b"\x00" * 500)
            result = hook_slowmo.maybe_apply_hook_slowmo(clip, virality_score=85, inplace=False)

        mock_apply.assert_called_once()

    def test_returns_false_when_clip_missing(self, tmp_path):
        from video_processing import hook_slowmo

        with patch.object(hook_slowmo, "HOOK_SLOWMO_ENABLED", True):
            result = hook_slowmo.maybe_apply_hook_slowmo(
                tmp_path / "nonexistent.mp4", virality_score=90
            )

        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
#  .env.example coverage
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvVarCoverage:
    """Verify that the env vars used by hook_slowmo are documented."""

    def test_env_example_has_hook_slowmo_enabled(self):
        import re
        env_file = Path(__file__).parent.parent.parent / "backend" / ".env.example"
        if not env_file.exists():
            pytest.skip(".env.example not found")

        content = env_file.read_text()
        assert "HOOK_SLOWMO" in content or "hook_slowmo" in content.lower(), \
            "HOOK_SLOWMO_ENABLED should be documented in .env.example"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
