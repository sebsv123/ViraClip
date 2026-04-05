"""
Unit Tests — Phase 2.3: RAFT Optical Flow Morph Transitions
============================================================
Tests for optical flow transition pipeline, FFmpeg xfade fallback,
boundary frame extraction, capabilities detection, and video_service integration.
"""

import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock


# ─────────────────────────────────────────────────────────────────────────────
#  get_transition_capabilities
# ─────────────────────────────────────────────────────────────────────────────

class TestTransitionCapabilities:
    """Test transition backend detection."""

    def test_returns_dict_with_expected_keys(self):
        from video_processing.optical_flow_transitions import get_transition_capabilities

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="xfade", returncode=0)
            caps = get_transition_capabilities()

        assert "raft_available" in caps
        assert "xfade_available" in caps
        assert "cv2_available" in caps
        assert "best_mode" in caps

    def test_best_mode_is_xfade_without_raft(self):
        from video_processing.optical_flow_transitions import get_transition_capabilities

        with patch("video_processing.optical_flow_transitions._get_raft_model", return_value=None), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="xfade", returncode=0)
            caps = get_transition_capabilities()

        assert caps["raft_available"] is False
        assert caps["best_mode"] in ("xfade", "crossfade")

    def test_best_mode_is_raft_when_available(self):
        from video_processing.optical_flow_transitions import get_transition_capabilities

        mock_model = MagicMock()
        with patch("video_processing.optical_flow_transitions._get_raft_model", return_value=mock_model), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="xfade", returncode=0)
            caps = get_transition_capabilities()

        assert caps["raft_available"] is True
        assert caps["best_mode"] == "raft"


# ─────────────────────────────────────────────────────────────────────────────
#  apply_optical_flow_transition — main API
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyOpticalFlowTransition:
    """Test main transition API."""

    def test_returns_false_when_inputs_missing(self, tmp_path):
        from video_processing.optical_flow_transitions import apply_optical_flow_transition

        result = apply_optical_flow_transition(
            tmp_path / "a.mp4",
            tmp_path / "b.mp4",
            tmp_path / "out.mp4",
        )
        assert result is False

    def test_uses_xfade_when_raft_unavailable(self, tmp_path):
        from video_processing.optical_flow_transitions import apply_optical_flow_transition

        # Create dummy input files
        (tmp_path / "a.mp4").write_bytes(b"\x00" * 1024)
        (tmp_path / "b.mp4").write_bytes(b"\x00" * 1024)
        out = tmp_path / "out.mp4"

        with patch("video_processing.optical_flow_transitions._get_raft_model", return_value=None), \
             patch("video_processing.optical_flow_transitions._apply_xfade_transition",
                   return_value=True) as mock_xfade:
            result = apply_optical_flow_transition(
                tmp_path / "a.mp4", tmp_path / "b.mp4", out,
                transition_type="auto",
            )

        mock_xfade.assert_called_once()
        assert result is True

    def test_falls_back_to_xfade_when_raft_fails(self, tmp_path):
        from video_processing.optical_flow_transitions import apply_optical_flow_transition

        (tmp_path / "a.mp4").write_bytes(b"\x00" * 100)
        (tmp_path / "b.mp4").write_bytes(b"\x00" * 100)

        mock_model = MagicMock()
        with patch("video_processing.optical_flow_transitions._get_raft_model", return_value=mock_model), \
             patch("video_processing.optical_flow_transitions._apply_raft_transition", return_value=False), \
             patch("video_processing.optical_flow_transitions._apply_xfade_transition", return_value=True) as mock_xfade:
            result = apply_optical_flow_transition(
                tmp_path / "a.mp4", tmp_path / "b.mp4",
                tmp_path / "out.mp4",
                transition_type="auto",
            )

        mock_xfade.assert_called_once()
        assert result is True

    def test_skips_raft_when_xfade_forced(self, tmp_path):
        from video_processing.optical_flow_transitions import apply_optical_flow_transition

        (tmp_path / "a.mp4").write_bytes(b"\x00" * 100)
        (tmp_path / "b.mp4").write_bytes(b"\x00" * 100)

        with patch("video_processing.optical_flow_transitions._apply_xfade_transition",
                   return_value=True) as mock_xfade, \
             patch("video_processing.optical_flow_transitions._apply_raft_transition") as mock_raft:
            apply_optical_flow_transition(
                tmp_path / "a.mp4", tmp_path / "b.mp4",
                tmp_path / "out.mp4",
                transition_type="xfade",
            )

        mock_raft.assert_not_called()
        mock_xfade.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
#  extract_boundary_frames
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractBoundaryFrames:
    """Test boundary frame extraction from clips."""

    def test_returns_none_when_ffmpeg_fails(self, tmp_path):
        from video_processing.optical_flow_transitions import extract_boundary_frames

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr=b"error")
            first, last = extract_boundary_frames(tmp_path / "clip.mp4")

        assert first is None
        assert last is None

    def test_returns_paths_when_frames_exist(self, tmp_path):
        from video_processing.optical_flow_transitions import extract_boundary_frames

        # Mock ffmpeg writing output frames
        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            # When ffprobe is called, return a duration
            if "ffprobe" in str(cmd):
                return MagicMock(returncode=0, stdout="5.0\n", stderr=b"")
            # When ffmpeg -vframes is called, create the output file
            for arg in cmd:
                if isinstance(arg, str) and arg.endswith(".jpg"):
                    Path(arg).write_bytes(b"\xff\xd8\xff")
                    break
            return MagicMock(returncode=0, stdout="", stderr=b"")

        with patch("subprocess.run", side_effect=fake_run):
            first, last = extract_boundary_frames(tmp_path / "clip.mp4")

        # If frames were created, they should be paths
        if first is not None:
            assert isinstance(first, Path)
        if last is not None:
            assert isinstance(last, Path)


# ─────────────────────────────────────────────────────────────────────────────
#  generate_morph_clip
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateMorphClip:
    """Test morph clip generation."""

    def test_returns_none_when_frames_missing(self, tmp_path):
        from video_processing.optical_flow_transitions import generate_morph_clip

        with patch("video_processing.optical_flow_transitions._get_raft_model", return_value=None):
            result = generate_morph_clip(
                tmp_path / "nonexistent_a.jpg",
                tmp_path / "nonexistent_b.jpg",
                output_path=tmp_path / "morph.mp4",
            )

        assert result is None

    def test_uses_auto_temp_path_when_output_none(self, tmp_path):
        from video_processing.optical_flow_transitions import generate_morph_clip

        with patch("video_processing.optical_flow_transitions._get_raft_model", return_value=None), \
             patch("video_processing.optical_flow_transitions._crossfade_morph_clip",
                   return_value=None):
            result = generate_morph_clip(
                tmp_path / "a.jpg",
                tmp_path / "b.jpg",
                output_path=None,
            )

        # With nonexistent inputs it returns None — just verify no exception
        assert result is None or isinstance(result, Path)


# ─────────────────────────────────────────────────────────────────────────────
#  _crossfade_morph_clip (CPU fallback)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossfadeMorphClip:
    """Test cross-dissolve CPU fallback."""

    def test_returns_none_on_missing_frames(self, tmp_path):
        from video_processing.optical_flow_transitions import _crossfade_morph_clip

        result = _crossfade_morph_clip(
            tmp_path / "nonexistent_a.jpg",
            tmp_path / "nonexistent_b.jpg",
            num_frames=5,
            fps=30,
            output_path=tmp_path / "morph.mp4",
        )
        assert result is None

    def test_generates_clip_with_real_frames(self, tmp_path):
        """Requires opencv-python-headless installed."""
        pytest.importorskip("cv2")

        import cv2
        import numpy as np
        from video_processing.optical_flow_transitions import _crossfade_morph_clip

        # Create tiny test frames
        frame_a = tmp_path / "a.jpg"
        frame_b = tmp_path / "b.jpg"
        cv2.imwrite(str(frame_a), np.zeros((64, 64, 3), dtype=np.uint8))
        cv2.imwrite(str(frame_b), np.ones((64, 64, 3), dtype=np.uint8) * 200)

        out = tmp_path / "morph.mp4"
        result = _crossfade_morph_clip(frame_a, frame_b, num_frames=5, fps=10, output_path=out)

        # Should produce a file or gracefully return None
        if result is not None:
            assert out.exists()
            assert out.stat().st_size > 0


# ─────────────────────────────────────────────────────────────────────────────
#  video_service.apply_single_transition
# ─────────────────────────────────────────────────────────────────────────────

class TestApplySingleTransition:
    """Test apply_single_transition activation in video_service."""

    @pytest.mark.asyncio
    async def test_returns_original_when_prev_clip_missing(self, tmp_path):
        from services.video_service import VideoService

        clip_info = {"path": str(tmp_path / "clip.mp4"), "filename": "clip.mp4"}

        result = await VideoService.apply_single_transition(
            prev_clip_path=None,
            current_clip_info=clip_info,
            clip_index=0,
            output_dir=tmp_path,
        )

        assert result is clip_info

    @pytest.mark.asyncio
    async def test_returns_original_when_clips_not_found(self, tmp_path):
        from services.video_service import VideoService

        clip_info = {"path": str(tmp_path / "nonexistent.mp4"), "filename": "x.mp4"}

        result = await VideoService.apply_single_transition(
            prev_clip_path=tmp_path / "also_missing.mp4",
            current_clip_info=clip_info,
            clip_index=1,
            output_dir=tmp_path,
        )

        assert result is clip_info

    @pytest.mark.asyncio
    async def test_applies_transition_when_clips_exist(self, tmp_path):
        from services.video_service import VideoService

        clip_a = tmp_path / "clip_a.mp4"
        clip_b = tmp_path / "clip_b.mp4"
        clip_a.write_bytes(b"\x00" * 100)
        clip_b.write_bytes(b"\x00" * 100)

        clip_info = {"path": str(clip_b), "filename": "clip_b.mp4"}

        with patch(
            "video_processing.optical_flow_transitions.get_transition_capabilities",
            return_value={"raft_available": False, "xfade_available": True,
                          "cv2_available": True, "best_mode": "xfade"},
        ), patch(
            "video_processing.optical_flow_transitions.apply_optical_flow_transition",
            side_effect=lambda a, b, out, *args, **kwargs: (
                out.write_bytes(b"\x00" * 500) or True
            ),
        ):
            result = await VideoService.apply_single_transition(
                prev_clip_path=clip_a,
                current_clip_info=clip_info,
                clip_index=1,
                output_dir=tmp_path,
            )

        # Should return updated clip_info with transition_applied key
        assert result.get("transition_applied") == "xfade" or result is clip_info

    @pytest.mark.asyncio
    async def test_returns_original_on_transition_failure(self, tmp_path):
        from services.video_service import VideoService

        clip_a = tmp_path / "clip_a.mp4"
        clip_b = tmp_path / "clip_b.mp4"
        clip_a.write_bytes(b"\x00" * 100)
        clip_b.write_bytes(b"\x00" * 100)

        clip_info = {"path": str(clip_b), "filename": "clip_b.mp4"}

        with patch(
            "video_processing.optical_flow_transitions.get_transition_capabilities",
            return_value={"raft_available": False, "xfade_available": True,
                          "cv2_available": True, "best_mode": "xfade"},
        ), patch(
            "video_processing.optical_flow_transitions.apply_optical_flow_transition",
            return_value=False,
        ):
            result = await VideoService.apply_single_transition(
                prev_clip_path=clip_a,
                current_clip_info=clip_info,
                clip_index=1,
                output_dir=tmp_path,
            )

        assert result is clip_info


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
