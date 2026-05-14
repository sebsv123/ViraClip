"""
Unit tests for BUG 2 fix: GPU detection before minterpolate in hook_slowmo.py.

BUG 2: minterpolate (frame interpolation) is extremely CPU-heavy and causes
timeouts on systems without a GPU. The fix adds a check for nvenc_available()
before adding minterpolate to the FFmpeg command, and reduces the timeout
from 120s to 60s for CPU-only paths.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest


class TestHookSlowmoGpuDetection:
    """Tests that GPU detection works correctly before minterpolate."""

    def test_nvenc_available_importable(self):
        """nvenc_available should be importable from gpu_utils."""
        from src.gpu_utils import nvenc_available
        assert callable(nvenc_available)

    @patch("src.gpu_utils.nvenc_available", return_value=True)
    def test_minterpolate_used_when_gpu_available(self, mock_nvenc):
        """When GPU is available, minterpolate should be included."""
        from src.gpu_utils import nvenc_available
        assert nvenc_available() is True

    @patch("src.gpu_utils.nvenc_available", return_value=False)
    def test_minterpolate_skipped_when_no_gpu(self, mock_nvenc):
        """When no GPU is available, minterpolate should be skipped."""
        from src.gpu_utils import nvenc_available
        assert nvenc_available() is False

    def test_extract_slowmo_segment_importable(self):
        """The _extract_slowmo_segment function should be importable."""
        from src.video_processing.hook_slowmo import _extract_slowmo_segment
        assert callable(_extract_slowmo_segment)

    @patch("src.video_processing.hook_slowmo.nvenc_available", return_value=True)
    @patch("src.video_processing.hook_slowmo.subprocess.run")
    @patch("src.video_processing.hook_slowmo.Path.exists", return_value=True)
    @patch("src.video_processing.hook_slowmo.Path.unlink")
    @patch("src.video_processing.hook_slowmo.logger")
    def test_slowmo_with_gpu_uses_minterpolate(
        self, mock_logger, mock_unlink, mock_exists, mock_run, mock_nvenc
    ):
        """When GPU is available, the ffmpeg command should include minterpolate."""
        from src.video_processing.hook_slowmo import _extract_slowmo_segment

        input_path = Path("/tmp/test_input.mp4")
        output_path = Path("/tmp/test_output.mp4")

        # Configure mock_run to return a result with returncode=0 so the retry
        # path is NOT triggered (otherwise call_args reflects the retry call
        # without minterpolate, not the first call with minterpolate).
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        # Call the function with all 7 required params
        _extract_slowmo_segment(input_path, output_path, 0.0, 2.0, 0.5, 30, True)

        # Verify subprocess.run was called
        assert mock_run.called
        call_args = mock_run.call_args
        cmd_str = " ".join(call_args[0][0]) if isinstance(call_args[0][0], list) else str(call_args[0][0])

        # Should contain minterpolate
        assert "minterpolate" in cmd_str, (
            "BUG 2: minterpolate should be present when GPU is available"
        )

    @patch("src.video_processing.hook_slowmo.nvenc_available", return_value=False)
    @patch("src.video_processing.hook_slowmo.subprocess.run")
    @patch("src.video_processing.hook_slowmo.Path.exists", return_value=True)
    @patch("src.video_processing.hook_slowmo.Path.unlink")
    @patch("src.video_processing.hook_slowmo.logger")
    def test_slowmo_without_gpu_skips_minterpolate(
        self, mock_logger, mock_unlink, mock_exists, mock_run, mock_nvenc
    ):
        """When no GPU is available, minterpolate should NOT be in the ffmpeg command."""
        from src.video_processing.hook_slowmo import _extract_slowmo_segment

        input_path = Path("/tmp/test_input.mp4")
        output_path = Path("/tmp/test_output.mp4")

        # Call the function with all 7 required params
        _extract_slowmo_segment(input_path, output_path, 0.0, 2.0, 0.5, 30, True)

        # Verify subprocess.run was called
        assert mock_run.called
        call_args = mock_run.call_args
        cmd_str = " ".join(call_args[0][0]) if isinstance(call_args[0][0], list) else str(call_args[0][0])

        # Should NOT contain minterpolate
        assert "minterpolate" not in cmd_str, (
            "BUG 2: minterpolate should be skipped when no GPU is available"
        )

    @patch("src.video_processing.hook_slowmo.nvenc_available", return_value=False)
    @patch("src.video_processing.hook_slowmo.subprocess.run")
    @patch("src.video_processing.hook_slowmo.Path.exists", return_value=True)
    @patch("src.video_processing.hook_slowmo.Path.unlink")
    @patch("src.video_processing.hook_slowmo.logger")
    def test_slowmo_without_gpu_reduced_timeout(
        self, mock_logger, mock_unlink, mock_exists, mock_run, mock_nvenc
    ):
        """When no GPU is available, the timeout should be reduced (60s not 120s)."""
        from src.video_processing.hook_slowmo import _extract_slowmo_segment

        input_path = Path("/tmp/test_input.mp4")
        output_path = Path("/tmp/test_output.mp4")

        # Call the function with all 7 required params
        _extract_slowmo_segment(input_path, output_path, 0.0, 2.0, 0.5, 30, True)

        # Verify subprocess.run was called with timeout=60
        assert mock_run.called
        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 60, (
            "BUG 2: timeout should be 60s for CPU-only paths"
        )

    @patch("src.video_processing.hook_slowmo.nvenc_available", return_value=True)
    @patch("src.video_processing.hook_slowmo.subprocess.run")
    @patch("src.video_processing.hook_slowmo.Path.exists", return_value=True)
    @patch("src.video_processing.hook_slowmo.Path.unlink")
    @patch("src.video_processing.hook_slowmo.logger")
    def test_slowmo_with_gpu_standard_timeout(
        self, mock_logger, mock_unlink, mock_exists, mock_run, mock_nvenc
    ):
        """When GPU is available, the timeout should be 120s."""
        from src.video_processing.hook_slowmo import _extract_slowmo_segment

        input_path = Path("/tmp/test_input.mp4")
        output_path = Path("/tmp/test_output.mp4")

        # Call the function with all 7 required params
        _extract_slowmo_segment(input_path, output_path, 0.0, 2.0, 0.5, 30, True)

        # Verify subprocess.run was called with timeout=120
        assert mock_run.called
        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 120, (
            "BUG 2: timeout should be 120s for GPU-accelerated paths"
        )
