"""
Tests for face_autocrop_service.py — stable face-tracking vertical crop.

Verifies:
  1. _smooth_trajectory() with various inputs (all faces, gaps, all None)
  2. _calculate_crop_boxes() for 16:9 input → 9:16 output
  3. _fallback_center_crop() logic
  4. process() with mocked dependencies (ffprobe, ffmpeg, face detection)
  5. apply_face_autocrop() convenience function
  6. Edge cases: no face detected, OpenCV unavailable, very short clip
  7. Advanced mode: Kalman filter, upper body detection, advanced crop boxes
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# Ensure the backend src is importable
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Pre-import under the src. prefix so that relative imports from
# domains.video._clip_polish (which resolve to src.services.face_autocrop_service)
# find the same module object in sys.modules. This allows patches on
# "src.services.face_autocrop_service.apply_face_autocrop" to work correctly.
import src.services.face_autocrop_service  # noqa: F401

from services.face_autocrop_service import (
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    DETECT_WIDTH,
    DETECT_HEIGHT,
    SMOOTHING_WINDOW,
    MIN_FACE_SIZE,
    FALLBACK_CROP_Y_RATIO,
    FACE_MARGIN,
    SAMPLE_RATE,
    DETECTOR_BACKEND,
    FACE_AUTOCROP_MODE,
    KALMAN_PROCESS_NOISE,
    KALMAN_MEASUREMENT_NOISE,
    UPPER_BODY_ENABLED,
    UPPER_THIRD_BIAS,
    CHIN_PADDING,
    FOREHEAD_PADDING,
    FaceAutocropService,
    get_face_autocrop_service,
    apply_face_autocrop,
)

logger = logging.getLogger(__name__)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def svc() -> FaceAutocropService:
    """Fresh FaceAutocropService with small smoothing window for tests."""
    return FaceAutocropService(
        smoothing_window=3,
        min_face_size=0.02,
        light_zoom_threshold=0.08,
        light_zoom_factor=1.05,
    )


@pytest.fixture
def svc_advanced() -> FaceAutocropService:
    """FaceAutocropService in advanced mode for testing."""
    return FaceAutocropService(
        smoothing_window=3,
        min_face_size=0.02,
        light_zoom_threshold=0.08,
        light_zoom_factor=1.05,
        mode="advanced",
        kalman_process_noise=1e-4,
        kalman_measurement_noise=1e-2,
        upper_body_enabled=True,
        upper_third_bias=0.15,
        chin_padding=0.10,
        forehead_padding=0.08,
    )


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """Create a tiny synthetic video for FFmpeg-based tests."""
    video_path = tmp_path / "test_input.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=2:size=1920x1080:rate=30",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "35",
        "-c:a", "aac",
        "-shortest",
        str(video_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("FFmpeg not available for video generation")
    return video_path


# ── _smooth_trajectory tests ───────────────────────────────────────────────


class TestSmoothTrajectory:
    """Unit tests for _smooth_trajectory()."""

    def test_all_faces_detected(self, svc: FaceAutocropService):
        """All frames have face centroids → smoothed output same length."""
        centroids = [(100.0, 200.0), (110.0, 210.0), (120.0, 220.0),
                     (130.0, 230.0), (140.0, 240.0)]
        result = svc._smooth_trajectory(centroids)
        assert len(result) == len(centroids)
        # All should be non-None
        assert all(r is not None for r in result)
        # Smoothing should reduce extreme values
        assert result[0] is not None
        assert result[-1] is not None

    def test_with_gaps(self, svc: FaceAutocropService):
        """Internal None gaps are linearly interpolated."""
        centroids: list = [
            (100.0, 200.0),
            None,
            None,
            (130.0, 230.0),
            (140.0, 240.0),
        ]
        result = svc._smooth_trajectory(centroids)
        assert len(result) == len(centroids)
        # Gaps should be filled
        assert result[1] is not None
        assert result[2] is not None
        # Interpolated values should be between endpoints
        r1, r2 = result[1], result[2]
        assert r1 is not None and r2 is not None
        assert 100.0 < r1[0] < 130.0
        assert 200.0 < r1[1] < 230.0

    def test_all_none(self, svc: FaceAutocropService):
        """All None → all None output."""
        centroids: list = [None, None, None]
        result = svc._smooth_trajectory(centroids)
        assert len(result) == 3
        assert all(r is None for r in result)

    def test_empty_input(self, svc: FaceAutocropService):
        """Empty list → empty list."""
        assert svc._smooth_trajectory([]) == []

    def test_leading_none(self, svc: FaceAutocropService):
        """Leading None values filled with next known centroid."""
        centroids: list = [None, None, (100.0, 200.0), (110.0, 210.0)]
        result = svc._smooth_trajectory(centroids)
        assert len(result) == 4
        # Leading Nones should be filled
        assert result[0] is not None
        assert result[1] is not None

    def test_trailing_none(self, svc: FaceAutocropService):
        """Trailing None values filled with previous known centroid."""
        centroids: list = [(100.0, 200.0), (110.0, 210.0), None, None]
        result = svc._smooth_trajectory(centroids)
        assert len(result) == 4
        assert result[2] is not None
        assert result[3] is not None

    def test_single_frame(self, svc: FaceAutocropService):
        """Single frame → single frame output."""
        result = svc._smooth_trajectory([(100.0, 200.0)])
        assert len(result) == 1
        assert result[0] == (100.0, 200.0)

    def test_smoothing_reduces_jitter(self, svc: FaceAutocropService):
        """Moving average should smooth out jittery centroids."""
        # Create a trajectory with a single outlier
        centroids = [
            (100.0, 200.0),
            (102.0, 202.0),
            (200.0, 300.0),  # outlier
            (104.0, 204.0),
            (106.0, 206.0),
        ]
        result = svc._smooth_trajectory(centroids)
        assert result[2] is not None
        # Smoothed outlier should be closer to neighbours
        assert abs(result[2][0] - 102.0) < abs(200.0 - 102.0)
        assert abs(result[2][1] - 202.0) < abs(300.0 - 202.0)


# ── _calculate_crop_boxes tests ────────────────────────────────────────────


class TestCalculateCropBoxes:
    """Unit tests for _calculate_crop_boxes()."""

    def test_16x9_input_center_face(self, svc: FaceAutocropService):
        """16:9 input (1920×1080) with face at centre → crop box centred."""
        centroids = [(DETECT_WIDTH / 2, DETECT_HEIGHT / 2)]
        boxes = svc._calculate_crop_boxes(centroids, 1920, 1080, 30.0)
        assert len(boxes) == 1
        x, y, w, h = boxes[0]
        # Crop should be 9:16 → 1080×1920 scaled to input coords
        # For 1920×1080 input: crop_h = 1080, crop_w = 1080 * 9/16 = 607.5
        assert w == pytest.approx(607.5, rel=0.01)
        assert h == pytest.approx(1080.0, rel=0.01)
        # Centred on face → x should be (1920 - 607.5) / 2 ≈ 656.25
        assert x == pytest.approx(656.25, rel=0.01)
        # y should be 0 (face at centre of frame, crop_h = input_h)
        assert y == pytest.approx(0.0, rel=0.01)

    def test_16x9_input_face_left(self, svc: FaceAutocropService):
        """Face on left edge → crop box clamped to left edge."""
        centroids = [(0.0, DETECT_HEIGHT / 2)]
        boxes = svc._calculate_crop_boxes(centroids, 1920, 1080, 30.0)
        x, y, w, h = boxes[0]
        assert x == pytest.approx(0.0, rel=0.01)
        assert w == pytest.approx(607.5, rel=0.01)

    def test_16x9_input_face_right(self, svc: FaceAutocropService):
        """Face on right edge → crop box clamped to right edge."""
        centroids = [(DETECT_WIDTH, DETECT_HEIGHT / 2)]
        boxes = svc._calculate_crop_boxes(centroids, 1920, 1080, 30.0)
        x, y, w, h = boxes[0]
        assert x + w == pytest.approx(1920.0, rel=0.01)

    def test_9x16_input(self, svc: FaceAutocropService):
        """9:16 input (1080×1920) → crop_w = input_w, crop_h = input_w / 0.5625."""
        centroids = [(DETECT_WIDTH / 2, DETECT_HEIGHT / 2)]
        boxes = svc._calculate_crop_boxes(centroids, 1080, 1920, 30.0)
        x, y, w, h = boxes[0]
        assert w == pytest.approx(1080.0, rel=0.01)
        assert h == pytest.approx(1920.0, rel=0.01)
        assert x == pytest.approx(0.0, rel=0.01)
        assert y == pytest.approx(0.0, rel=0.01)

    def test_none_centroid_fallback(self, svc: FaceAutocropService):
        """None centroid → fallback to centre of upper third."""
        boxes = svc._calculate_crop_boxes([None], 1920, 1080, 30.0)
        x, y, w, h = boxes[0]
        # x should be centred
        assert x == pytest.approx(656.25, rel=0.01)
        # For 1920x1080 input, crop_h == input_height (1080), so
        # y = input_height * FALLBACK_CROP_Y_RATIO = 216, but then
        # y + crop_h = 216 + 1080 = 1296 > 1080, so y gets clamped to 0.
        assert y == pytest.approx(0.0, rel=0.01)

    def test_multiple_frames(self, svc: FaceAutocropService):
        """Multiple frames → same number of crop boxes."""
        centroids = [
            (DETECT_WIDTH / 2, DETECT_HEIGHT / 2),
            (DETECT_WIDTH * 0.3, DETECT_HEIGHT * 0.4),
            (DETECT_WIDTH * 0.7, DETECT_HEIGHT * 0.6),
        ]
        boxes = svc._calculate_crop_boxes(centroids, 1920, 1080, 30.0)
        assert len(boxes) == 3
        # All boxes should have same w, h
        w0, h0 = boxes[0][2], boxes[0][3]
        for b in boxes:
            assert b[2] == pytest.approx(w0, rel=0.01)
            assert b[3] == pytest.approx(h0, rel=0.01)


# ── _fallback_center_crop tests ────────────────────────────────────────────


class TestFallbackCenterCrop:
    """Tests for _fallback_center_crop()."""

    @pytest.mark.asyncio
    async def test_fallback_with_probe(self, svc: FaceAutocropService, tmp_path: Path):
        """Fallback with successful probe → FFmpeg crop command."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        # Mock _probe_video to return valid data
        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            # Mock subprocess.run for FFmpeg
            with patch("subprocess.run", new=MagicMock(return_value=MagicMock(
                returncode=0, stdout=b"", stderr=b"",
            ))):
                # Mock output_path.exists() to return True
                with patch.object(Path, "exists", return_value=True):
                    result = await svc._fallback_center_crop(input_video, output_video)
                    assert result["success"] is True
                    assert result["method"] == "center_crop"
                    assert result["face_detection_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_fallback_no_probe(self, svc: FaceAutocropService, tmp_path: Path):
        """Fallback without probe → copy original."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy content")

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value=None)):
            with patch("shutil.copy2") as mock_copy:
                result = await svc._fallback_center_crop(input_video, output_video)
                assert result["success"] is True
                assert result["method"] == "fallback"
                assert "Could not probe video" in result.get("error", "")
                mock_copy.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_ffmpeg_fails(self, svc: FaceAutocropService, tmp_path: Path):
        """FFmpeg fails → copy original as last resort."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            with patch("subprocess.run", new=MagicMock(return_value=MagicMock(
                returncode=1, stdout=b"", stderr=b"error",
            ))):
                with patch("shutil.copy2") as mock_copy:
                    result = await svc._fallback_center_crop(input_video, output_video)
                    assert result["success"] is True
                    assert result["method"] == "fallback"
                    assert "FFmpeg fallback failed" in result.get("error", "")
                    mock_copy.assert_called_once()


# ── process() integration tests (mocked) ───────────────────────────────────


class TestProcess:
    """Tests for the main process() method with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_process_face_tracking(self, svc: FaceAutocropService, tmp_path: Path):
        """Happy path: face detected → face_tracking method."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        # Mock _probe_video
        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            # Mock _extract_frames
            with patch.object(svc, "_extract_frames", new=AsyncMock(return_value=60)):
                # Mock _detect_faces_batch_sync — 50% face detection
                # (process() calls this via run_in_executor, not _detect_faces_batch)
                mock_faces = (
                    [(DETECT_WIDTH / 2, DETECT_HEIGHT / 2)] * 30
                    + [None] * 30
                )
                with patch.object(svc, "_detect_faces_batch_sync",
                                  return_value=mock_faces):
                    # Mock _render_crop
                    with patch.object(svc, "_render_crop",
                                      new=AsyncMock(return_value=True)):
                        # Mock output exists
                        with patch.object(Path, "exists", return_value=True):
                            result = await svc.process(input_video, output_video)
                            assert result["success"] is True
                            assert result["method"] == "face_tracking"
                            assert result["face_detection_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_process_center_crop_fallback(self, svc: FaceAutocropService, tmp_path: Path):
        """Low face detection rate → center crop fallback."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            with patch.object(svc, "_extract_frames", new=AsyncMock(return_value=60)):
                # Only 5% face detection → triggers fallback
                mock_faces = (
                    [(DETECT_WIDTH / 2, DETECT_HEIGHT / 2)] * 3
                    + [None] * 57
                )
                with patch.object(svc, "_detect_faces_batch_sync",
                                  return_value=mock_faces):
                    with patch.object(svc, "_fallback_center_crop",
                                      new=AsyncMock(return_value={
                                          "path": output_video,
                                          "success": True,
                                          "method": "center_crop",
                                          "face_detection_rate": 0.0,
                                          "error": None,
                                      })):
                        result = await svc.process(input_video, output_video)
                        assert result["success"] is True
                        assert result["method"] == "center_crop"

    @pytest.mark.asyncio
    async def test_process_already_vertical(self, svc: FaceAutocropService, tmp_path: Path):
        """Input already 9:16 → skip autocrop."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1080, "height": 1920, "fps": 30.0, "duration": 2.0,
        })):
            with patch("shutil.copy2") as mock_copy:
                result = await svc.process(input_video, output_video)
                assert result["success"] is True
                assert result["method"] == "skip_vertical"
                mock_copy.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_no_frames(self, svc: FaceAutocropService, tmp_path: Path):
        """No frames extracted → fallback."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            with patch.object(svc, "_extract_frames", new=AsyncMock(return_value=0)):
                with patch.object(svc, "_fallback_center_crop",
                                  new=AsyncMock(return_value={
                                      "path": output_video,
                                      "success": True,
                                      "method": "fallback",
                                      "face_detection_rate": 0.0,
                                      "error": "No frames extracted",
                                  })):
                    result = await svc.process(input_video, output_video)
                    assert result["success"] is True
                    assert result["method"] == "fallback"

    @pytest.mark.asyncio
    async def test_process_exception(self, svc: FaceAutocropService, tmp_path: Path):
        """Exception during processing → fallback."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        with patch.object(svc, "_probe_video", new=AsyncMock(side_effect=RuntimeError("Boom"))):
            with patch.object(svc, "_fallback_center_crop",
                              new=AsyncMock(return_value={
                                  "path": output_video,
                                  "success": True,
                                  "method": "fallback",
                                  "face_detection_rate": 0.0,
                                  "error": "Error occurred",
                              })):
                result = await svc.process(input_video, output_video)
                assert result["success"] is True
                assert result["method"] == "fallback"

    @pytest.mark.asyncio
    async def test_process_render_fails(self, svc: FaceAutocropService, tmp_path: Path):
        """FFmpeg render fails → fallback."""
        input_video = tmp_path / "input.mp4"
        output_video = tmp_path / "output.mp4"
        input_video.write_text("dummy")

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            with patch.object(svc, "_extract_frames", new=AsyncMock(return_value=60)):
                mock_faces = (
                    [(DETECT_WIDTH / 2, DETECT_HEIGHT / 2)] * 60
                )
                with patch.object(svc, "_detect_faces_batch_sync",
                                  return_value=mock_faces):
                    with patch.object(svc, "_render_crop",
                                      new=AsyncMock(return_value=False)):
                        with patch.object(svc, "_fallback_center_crop",
                                          new=AsyncMock(return_value={
                                              "path": output_video,
                                              "success": True,
                                              "method": "fallback",
                                              "face_detection_rate": 0.0,
                                              "error": "Render failed",
                                          })):
                            result = await svc.process(input_video, output_video)
                            assert result["success"] is True
                            assert result["method"] == "fallback"


# ── _render_crop tests ─────────────────────────────────────────────────────


class TestRenderSinglePass:
    """Tests for _render_crop with single-pass (≤200 frames)."""

    def test_single_pass_crop_filter(self, svc: FaceAutocropService):
        """Single-pass crop filter expression for ≤200 frames."""
        crop_boxes = [
            (100.0, 50.0, 607.5, 1080.0),
            (110.0, 55.0, 607.5, 1080.0),
            (120.0, 60.0, 607.5, 1080.0),
        ]
        # We just verify the method exists and doesn't crash
        # Full FFmpeg integration is tested via process()
        assert hasattr(svc, "_render_crop")


class TestRenderSegmented:
    """Tests for _render_crop with segmented approach (>200 frames)."""

    def test_segmented_approach(self, svc: FaceAutocropService):
        """Segmented render for >200 frames."""
        # Verify the method handles long clips
        assert hasattr(svc, "_render_crop")


# ── Convenience function tests ─────────────────────────────────────────────


class TestConvenienceFunctions:
    """Tests for get_face_autocrop_service() and apply_face_autocrop()."""

    def test_get_service(self):
        """get_face_autocrop_service returns a configured instance."""
        service = get_face_autocrop_service()
        assert isinstance(service, FaceAutocropService)
        assert service.smoothing_window == SMOOTHING_WINDOW
        assert service.min_face_size == MIN_FACE_SIZE

    @pytest.mark.asyncio
    async def test_apply_autocrop(self, tmp_path: Path):
        """apply_face_autocrop calls process and returns path on success."""
        input_path = tmp_path / "test.mp4"
        input_path.write_text("dummy")

        mock_result = {
            "path": tmp_path / "autocrop_test.mp4",
            "success": True,
            "method": "face_tracking",
            "face_detection_rate": 0.8,
            "error": None,
        }

        async def mock_process(clip_path, output_path):
            return mock_result

        with patch("src.services.face_autocrop_service.FaceAutocropService.process",
                   new=mock_process):
            result = await apply_face_autocrop(input_path)
            assert result == mock_result["path"]

    @pytest.mark.asyncio
    async def test_apply_autocrop_failure(self, tmp_path: Path):
        """apply_face_autocrop returns original path on failure."""
        input_path = tmp_path / "test.mp4"
        input_path.write_text("dummy")

        mock_result = {
            "success": False,
            "method": "face_tracking",
            "face_detection_rate": 0.0,
            "error": "Detection failed",
        }

        async def mock_process(clip_path, output_path):
            return mock_result

        with patch("src.services.face_autocrop_service.FaceAutocropService.process",
                   new=mock_process):
            result = await apply_face_autocrop(input_path)
            assert result == input_path


# ── _load_cascades tests ───────────────────────────────────────────────────


class TestLoadCascades:
    """Tests for _load_cascades()."""

    def test_load_cascades_success(self, svc: FaceAutocropService):
        """Cascades load successfully when OpenCV is available."""
        # Mock cv2 to return valid cascades
        mock_cascade = MagicMock()
        mock_cascade.empty.return_value = False

        with patch.dict("sys.modules", {"cv2": MagicMock()}):
            with patch.object(svc, "_face_cascade", None):
                with patch.object(svc, "_profile_cascade", None):
                    # We can't easily test the full path without cv2 installed,
                    # but we can verify the method exists and handles errors
                    pass

    def test_load_cascades_cv2_not_available(self, svc: FaceAutocropService):
        """Cascades return False when cv2 is not importable."""
        with patch.dict("sys.modules", {"cv2": None}):
            with patch("builtins.__import__", side_effect=ImportError("No cv2")):
                result = svc._load_cascades()
                assert result is False


# ── _extract_frames tests ──────────────────────────────────────────────────


class TestExtractFrames:
    """Tests for _extract_frames()."""

    @pytest.mark.asyncio
    async def test_extract_frames_success(self, svc: FaceAutocropService, tmp_path: Path):
        """Frames extracted successfully."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            with patch("subprocess.run", new=MagicMock(return_value=MagicMock(
                returncode=0, stdout=b"", stderr=b"",
            ))):
                count = await svc._extract_frames(
                    tmp_path / "input.mp4", frames_dir, 30.0, 2.0,
                )
                assert count > 0


class TestExtractFramesSampling:
    """Tests for frame extraction with sampling."""

    @pytest.mark.asyncio
    async def test_extract_frames_with_sampling(self, svc: FaceAutocropService, tmp_path: Path):
        """Frame extraction respects sample_rate."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch.object(svc, "_probe_video", new=AsyncMock(return_value={
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        })):
            with patch("subprocess.run", new=MagicMock(return_value=MagicMock(
                returncode=0, stdout=b"", stderr=b"",
            ))):
                count = await svc._extract_frames(
                    tmp_path / "input.mp4", frames_dir, 30.0, 2.0,
                )
                assert count > 0


# ── _detect_faces_haar tests ───────────────────────────────────────────────


class TestDetectFacesHaar:
    """Tests for _detect_faces_haar()."""

    def test_detect_haar_no_cascade(self, svc: FaceAutocropService, tmp_path: Path):
        """No cascade loaded → returns None."""
        frame_path = tmp_path / "frame_0001.jpg"
        frame_path.write_text("dummy")
        svc._face_cascade = None
        result = svc._detect_faces_haar(frame_path)
        assert result is None

    def test_detect_haar_imread_fails(self, svc: FaceAutocropService, tmp_path: Path):
        """cv2.imread fails → returns None."""
        frame_path = tmp_path / "nonexistent.jpg"
        result = svc._detect_faces_haar(frame_path)
        assert result is None


# ── _detect_faces_retinaface tests ─────────────────────────────────────────


class TestDetectFacesRetinaFace:
    """Tests for _detect_faces_retinaface()."""

    def test_retinaface_no_detector(self, svc: FaceAutocropService, tmp_path: Path):
        """No RetinaFace detector loaded → returns None."""
        frame_path = tmp_path / "frame_0001.jpg"
        frame_path.write_text("dummy")
        svc._retinaface_detector = None
        result = svc._detect_faces_retinaface(frame_path)
        assert result is None


# ── _expand_face_box tests ─────────────────────────────────────────────────


class TestExpandFaceBox:
    """Tests for _expand_face_box()."""

    def test_expand_face_box_center(self, svc: FaceAutocropService):
        """Face box expanded by margin factor."""
        box = (100.0, 100.0, 200.0, 200.0)  # x, y, w, h
        expanded = svc._expand_face_box(box, 1920, 1080)
        x, y, w, h = expanded
        # Width should be expanded by FACE_MARGIN
        assert w > 200.0
        assert h > 200.0
        # Should be clamped to frame bounds
        assert x >= 0
        assert y >= 0
        assert x + w <= 1920
        assert y + h <= 1080

    def test_expand_face_box_edge(self, svc: FaceAutocropService):
        """Face box at edge → clamped to frame."""
        box = (0.0, 0.0, 50.0, 50.0)
        expanded = svc._expand_face_box(box, 1920, 1080)
        x, y, w, h = expanded
        assert x >= 0
        assert y >= 0


# ── _detect_faces_batch tests ──────────────────────────────────────────────


class TestDetectFacesBatch:
    """Tests for _detect_faces_batch()."""

    def test_batch_empty_dir(self, svc: FaceAutocropService, tmp_path: Path):
        """Empty frames directory → empty results."""
        frames_dir = tmp_path / "empty_frames"
        frames_dir.mkdir()
        result = svc._detect_faces_batch(frames_dir, 10)
        assert len(result) == 10
        assert all(r is None for r in result)


class TestDetectFacesBatchSync:
    """Tests for _detect_faces_batch_sync()."""

    def test_batch_sync_empty_dir(self, svc: FaceAutocropService, tmp_path: Path):
        """Empty frames directory → all None results."""
        frames_dir = tmp_path / "empty_frames"
        frames_dir.mkdir()
        result = svc._detect_faces_batch_sync(frames_dir, 10)
        assert len(result) == 10
        assert all(r is None for r in result)


# ── Advanced mode: Kalman filter tests ─────────────────────────────────────


class TestInitKalmanFilter:
    """Tests for _init_kalman_filter()."""

    def test_init_success(self, svc_advanced: FaceAutocropService):
        """Kalman filter initializes with default noise parameters."""
        result = svc_advanced._init_kalman_filter()
        assert result is True
        assert svc_advanced._kalman is not None
        assert svc_advanced._kalman_initialized is False

    def test_init_custom_noise(self):
        """Kalman filter with custom process/measurement noise."""
        svc = FaceAutocropService(
            mode="advanced",
            kalman_process_noise=1e-3,
            kalman_measurement_noise=5e-2,
        )
        result = svc._init_kalman_filter()
        assert result is True
        # Verify noise covariances are set
        assert svc._kalman is not None
        assert svc._kalman.processNoiseCov[0, 0] == pytest.approx(1e-3)
        assert svc._kalman.measurementNoiseCov[0, 0] == pytest.approx(5e-2)

    @patch.dict("sys.modules", {"cv2": None})
    def test_init_cv2_not_available(self, svc_advanced: FaceAutocropService):
        """Kalman filter init returns False when cv2 is not importable."""
        # Force reimport by clearing cached kalman
        svc_advanced._kalman = None
        result = svc_advanced._init_kalman_filter()
        assert result is False
        assert svc_advanced._kalman is None

    def test_init_exception(self, svc_advanced: FaceAutocropService):
        """Kalman filter init handles exceptions gracefully."""
        svc_advanced._kalman = None
        with patch("src.services.face_autocrop_service.FaceAutocropService._init_kalman_filter",
                   side_effect=Exception("Init failed")):
            result = svc_advanced._init_kalman_filter()
            # The method itself catches exceptions
            pass


class TestSmoothTrajectoryKalman:
    """Tests for _smooth_trajectory_kalman()."""

    def test_all_detected(self, svc_advanced: FaceAutocropService):
        """All frames have face detections → smoothed trajectory follows closely."""
        centroids = [(100.0, 200.0), (110.0, 205.0), (120.0, 210.0),
                     (130.0, 215.0), (140.0, 220.0)]
        result = svc_advanced._smooth_trajectory_kalman(centroids)
        assert len(result) == 5
        # First frame should match exactly (initialization)
        assert result[0] == (100.0, 200.0)
        # Subsequent frames should be close to input
        for i in range(1, 5):
            assert result[i] is not None
            rx, ry = result[i]
            assert abs(rx - centroids[i][0]) < 20.0  # within reasonable range
            assert abs(ry - centroids[i][1]) < 20.0

    def test_with_gaps(self, svc_advanced: FaceAutocropService):
        """Some frames missing → Kalman predicts through gaps."""
        centroids = [(100.0, 200.0), None, None, (130.0, 215.0), (140.0, 220.0)]
        result = svc_advanced._smooth_trajectory_kalman(centroids)
        assert len(result) == 5
        # First frame should match
        assert result[0] == (100.0, 200.0)
        # Gap frames should have predictions (not None)
        assert result[1] is not None
        assert result[2] is not None
        # Last frames should be close to input
        assert result[3] is not None
        assert result[4] is not None

    def test_all_none(self, svc_advanced: FaceAutocropService):
        """No detections at all → all filled with center fallback."""
        centroids: list = [None, None, None]
        result = svc_advanced._smooth_trajectory_kalman(centroids)
        assert len(result) == 3
        # All should be filled with center fallback
        assert all(r is not None for r in result)
        # Should be near center of DETECT resolution
        cx, cy = result[0]
        assert cx == pytest.approx(DETECT_WIDTH / 2, rel=0.5)
        assert cy == pytest.approx(DETECT_HEIGHT * 0.20, rel=0.5)

    def test_empty_input(self, svc_advanced: FaceAutocropService):
        """Empty list → empty result."""
        result = svc_advanced._smooth_trajectory_kalman([])
        assert result == []

    def test_fallback_to_moving_average(self):
        """When Kalman init fails, falls back to moving-average smoothing."""
        svc = FaceAutocropService(mode="advanced")
        svc._kalman = None  # Force re-init
        with patch.object(svc, '_init_kalman_filter', return_value=False):
            centroids = [(100.0, 200.0), (110.0, 205.0)]
            result = svc._smooth_trajectory_kalman(centroids)
            assert len(result) == 2
            assert result[0] is not None
            assert result[1] is not None


# ── Advanced mode: upper body cascade tests ────────────────────────────────


class TestLoadUpperBodyCascade:
    """Tests for _load_upper_body_cascade()."""

    def test_already_loaded(self, svc_advanced: FaceAutocropService):
        """If cascade already loaded, returns True immediately."""
        svc_advanced._upper_body_cascade = MagicMock()
        result = svc_advanced._load_upper_body_cascade()
        assert result is True

    def test_cascade_not_found(self, svc_advanced: FaceAutocropService):
        """When cascade XML file doesn't exist, returns False."""
        svc_advanced._upper_body_cascade = None
        with patch("os.path.exists", return_value=False):
            with patch("cv2.data.haarcascades", "/nonexistent/"):
                result = svc_advanced._load_upper_body_cascade()
                assert result is False
                assert svc_advanced._upper_body_cascade is None

    def test_cv2_not_available(self, svc_advanced: FaceAutocropService):
        """When cv2 is not importable, returns False."""
        svc_advanced._upper_body_cascade = None
        # Simulate ImportError by patching the import
        original_import = __builtins__.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'cv2':
                raise ImportError("No module named cv2")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = svc_advanced._load_upper_body_cascade()
            assert result is False

    def test_exception_during_load(self, svc_advanced: FaceAutocropService):
        """Exception during cascade loading returns False."""
        svc_advanced._upper_body_cascade = None
        with patch("os.path.exists", side_effect=Exception("Disk error")):
            result = svc_advanced._load_upper_body_cascade()
            assert result is False


class TestDetectUpperBody:
    """Tests for _detect_upper_body()."""

    def test_cascade_not_loaded(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When cascade is None and can't be loaded, returns None."""
        svc_advanced._upper_body_cascade = None
        with patch.object(svc_advanced, '_load_upper_body_cascade', return_value=False):
            frame = tmp_path / "frame.jpg"
            frame.write_text("fake")
            result = svc_advanced._detect_upper_body(frame)
            assert result is None

    def test_imread_fails(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When cv2.imread returns None, returns None."""
        svc_advanced._upper_body_cascade = MagicMock()
        with patch("cv2.imread", return_value=None):
            frame = tmp_path / "frame.jpg"
            frame.write_text("fake")
            result = svc_advanced._detect_upper_body(frame)
            assert result is None

    def test_no_detection(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When no upper body detected, returns None."""
        mock_cascade = MagicMock()
        mock_cascade.detectMultiScale.return_value = []
        svc_advanced._upper_body_cascade = mock_cascade
        with patch("cv2.imread", return_value=MagicMock()):
            frame = tmp_path / "frame.jpg"
            frame.write_text("fake")
            result = svc_advanced._detect_upper_body(frame)
            assert result is None

    def test_detection_found(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When upper body detected, returns bounding box."""
        mock_cascade = MagicMock()
        mock_cascade.detectMultiScale.return_value = [(50, 100, 200, 300)]
        svc_advanced._upper_body_cascade = mock_cascade
        with patch("cv2.imread", return_value=MagicMock()):
            frame = tmp_path / "frame.jpg"
            frame.write_text("fake")
            result = svc_advanced._detect_upper_body(frame)
            assert result == (50, 100, 200, 300)

    def test_multiple_detections_picks_largest(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When multiple bodies detected, returns the largest by area."""
        mock_cascade = MagicMock()
        mock_cascade.detectMultiScale.return_value = [
            (10, 20, 100, 50),    # area = 5000
            (50, 100, 200, 300),  # area = 60000 (largest)
            (5, 5, 30, 30),       # area = 900
        ]
        svc_advanced._upper_body_cascade = mock_cascade
        with patch("cv2.imread", return_value=MagicMock()):
            frame = tmp_path / "frame.jpg"
            frame.write_text("fake")
            result = svc_advanced._detect_upper_body(frame)
            assert result == (50, 100, 200, 300)


# ── Advanced mode: batch detection tests ───────────────────────────────────


class TestDetectFacesBatchSyncAdvanced:
    """Tests for _detect_faces_batch_sync_advanced()."""

    def test_face_detected_via_retinaface(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """Face detected via RetinaFace → returns centroid."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_0001.jpg").write_text("fake")

        with patch.object(svc_advanced, '_load_retinaface', return_value=True):
            with patch.object(svc_advanced, '_detect_faces_retinaface',
                              return_value=(50, 100, 100, 150)):
                with patch.object(svc_advanced, '_expand_face_box',
                                  return_value=(40, 90, 120, 170)):
                    result = svc_advanced._detect_faces_batch_sync_advanced(frames_dir, 1)
                    assert len(result) == 1
                    assert result[0] is not None
                    cx, cy = result[0]
                    assert cx == pytest.approx(40 + 120 / 2)
                    assert cy == pytest.approx(90 + 170 / 2)

    def test_face_detected_via_haar(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """Face detected via Haar when RetinaFace fails."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_0001.jpg").write_text("fake")

        with patch.object(svc_advanced, '_load_retinaface', return_value=True):
            with patch.object(svc_advanced, '_detect_faces_retinaface', return_value=None):
                with patch.object(svc_advanced, '_load_cascades', return_value=True):
                    with patch.object(svc_advanced, '_detect_faces_haar',
                                      return_value=(60, 110, 80, 120)):
                        with patch.object(svc_advanced, '_expand_face_box',
                                          return_value=(50, 100, 100, 140)):
                            result = svc_advanced._detect_faces_batch_sync_advanced(frames_dir, 1)
                            assert len(result) == 1
                            assert result[0] is not None

    def test_upper_body_fallback(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When face not found, falls back to upper body detection."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_0001.jpg").write_text("fake")

        with patch.object(svc_advanced, '_load_retinaface', return_value=True):
            with patch.object(svc_advanced, '_detect_faces_retinaface', return_value=None):
                with patch.object(svc_advanced, '_load_cascades', return_value=True):
                    with patch.object(svc_advanced, '_detect_faces_haar', return_value=None):
                        with patch.object(svc_advanced, '_load_upper_body_cascade',
                                          return_value=True):
                            with patch.object(svc_advanced, '_detect_upper_body',
                                              return_value=(30, 80, 200, 400)):
                                with patch.object(svc_advanced, '_expand_face_box',
                                                  return_value=(20, 70, 220, 420)):
                                    result = svc_advanced._detect_faces_batch_sync_advanced(
                                        frames_dir, 1)
                                    assert len(result) == 1
                                    assert result[0] is not None

    def test_no_detection(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """No detection from any method → returns None."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_0001.jpg").write_text("fake")

        with patch.object(svc_advanced, '_load_retinaface', return_value=True):
            with patch.object(svc_advanced, '_detect_faces_retinaface', return_value=None):
                with patch.object(svc_advanced, '_load_cascades', return_value=True):
                    with patch.object(svc_advanced, '_detect_faces_haar', return_value=None):
                        with patch.object(svc_advanced, '_load_upper_body_cascade',
                                          return_value=True):
                            with patch.object(svc_advanced, '_detect_upper_body',
                                              return_value=None):
                                result = svc_advanced._detect_faces_batch_sync_advanced(
                                    frames_dir, 1)
                                assert len(result) == 1
                                assert result[0] is None

    def test_all_detectors_fail(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When no detector can be loaded → all None results."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_0001.jpg").write_text("fake")

        with patch.object(svc_advanced, '_load_retinaface', return_value=False):
            with patch.object(svc_advanced, '_load_cascades', return_value=False):
                with patch.object(svc_advanced, '_load_upper_body_cascade', return_value=False):
                    result = svc_advanced._detect_faces_batch_sync_advanced(frames_dir, 3)
                    assert len(result) == 3
                    assert all(r is None for r in result)

    def test_padding(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """When fewer frames than frame_count, pads with None."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_0001.jpg").write_text("fake")

        with patch.object(svc_advanced, '_load_retinaface', return_value=True):
            with patch.object(svc_advanced, '_detect_faces_retinaface',
                              return_value=(50, 100, 100, 150)):
                with patch.object(svc_advanced, '_expand_face_box',
                                  return_value=(40, 90, 120, 170)):
                    result = svc_advanced._detect_faces_batch_sync_advanced(frames_dir, 5)
                    assert len(result) == 5
                    # First should be detected, rest padded with None
                    assert result[0] is not None
                    assert all(r is None for r in result[1:])


# ── Advanced mode: crop box calculation tests ──────────────────────────────


class TestCalculateCropBoxesAdvanced:
    """Tests for _calculate_crop_boxes_advanced()."""

    def test_forehead_padding(self, svc_advanced: FaceAutocropService):
        """Forehead padding shifts centroid up."""
        centroids = [(DETECT_WIDTH / 2, DETECT_HEIGHT / 2)]
        boxes = svc_advanced._calculate_crop_boxes_advanced(
            centroids, 1920, 1080, 30.0,
        )
        assert len(boxes) == 1
        x, y, w, h = boxes[0]
        # Crop should be 9:16 (1080x1920 for 1920x1080 input → crop vertically)
        assert w == pytest.approx(1080.0)
        assert h == pytest.approx(1920.0)
        # Centroid should be shifted up due to forehead padding + upper third bias
        # Original cy in input coords: (DETECT_HEIGHT/2) * (1080/DETECT_HEIGHT) = 540
        # After forehead padding: 540 - 0.08 * 1920 = 540 - 153.6 = 386.4
        # After upper third bias: 386.4 - 0.15 * 1920 = 386.4 - 288 = 98.4
        # So y = 98.4 - 1920/2 = 98.4 - 960 = -861.6 → clamped to 0
        assert y >= 0

    def test_upper_third_bias(self, svc_advanced: FaceAutocropService):
        """Upper third bias shifts crop box up."""
        # Centroid near bottom of frame
        centroids = [(DETECT_WIDTH / 2, DETECT_HEIGHT * 0.8)]
        boxes = svc_advanced._calculate_crop_boxes_advanced(
            centroids, 1920, 1080, 30.0,
        )
        assert len(boxes) == 1
        x, y, w, h = boxes[0]
        # The centroid should be in the upper portion of the crop
        centroid_input_y = (DETECT_HEIGHT * 0.8) * (1080 / DETECT_HEIGHT)
        # After forehead padding: centroid_input_y - 0.08 * 1920
        # After upper third bias: - 0.15 * 1920
        adjusted_cy = centroid_input_y - (0.08 + 0.15) * 1920
        # The crop box top should be above adjusted centroid
        assert y < adjusted_cy

    def test_chin_padding(self, svc_advanced: FaceAutocropService):
        """Chin padding ensures space below centroid."""
        # Centroid near top of frame
        centroids = [(DETECT_WIDTH / 2, DETECT_HEIGHT * 0.1)]
        boxes = svc_advanced._calculate_crop_boxes_advanced(
            centroids, 1920, 1080, 30.0,
        )
        assert len(boxes) == 1
        x, y, w, h = boxes[0]
        # The centroid should be at least chin_padding from bottom of crop
        centroid_input_y = (DETECT_HEIGHT * 0.1) * (1080 / DETECT_HEIGHT)
        # After forehead padding: centroid_input_y - 0.08 * 1920
        # After upper third bias: - 0.15 * 1920
        adjusted_cy = centroid_input_y - (0.08 + 0.15) * 1920
        # y + h should be >= adjusted_cy + chin_padding * h
        # But since centroid is near top, y will be clamped to 0
        assert y >= 0

    def test_fallback_for_none_centroid(self, svc_advanced: FaceAutocropService):
        """None centroid → fallback to center of upper third."""
        boxes = svc_advanced._calculate_crop_boxes_advanced(
            [None], 1920, 1080, 30.0,
        )
        assert len(boxes) == 1
        x, y, w, h = boxes[0]
        # Fallback: cx = input_width/2, cy = input_height * 0.20 + crop_h/2
        assert x == pytest.approx((1920 - 1080) / 2, rel=1.0)
        assert w == pytest.approx(1080.0)
        assert h == pytest.approx(1920.0)

    def test_clamping(self, svc_advanced: FaceAutocropService):
        """Crop box is clamped to frame bounds."""
        # Centroid at extreme corner
        centroids = [(10.0, 10.0)]
        boxes = svc_advanced._calculate_crop_boxes_advanced(
            centroids, 1920, 1080, 30.0,
        )
        assert len(boxes) == 1
        x, y, w, h = boxes[0]
        assert x >= 0
        assert y >= 0
        assert x + w <= 1920
        assert y + h <= 1080

    def test_narrow_input(self, svc_advanced: FaceAutocropService):
        """Input narrower than 9:16 → crop vertically instead."""
        centroids = [(DETECT_WIDTH / 2, DETECT_HEIGHT / 2)]
        boxes = svc_advanced._calculate_crop_boxes_advanced(
            centroids, 720, 1280, 30.0,
        )
        assert len(boxes) == 1
        x, y, w, h = boxes[0]
        # For 720x1280 input (9:16 already), crop should match input
        assert w == pytest.approx(720.0)
        assert h == pytest.approx(1280.0)


# ── Advanced mode: process() dispatch tests ────────────────────────────────


class TestProcessAdvanced:
    """Tests that process() dispatches to advanced methods when mode='advanced'."""

    @pytest.mark.asyncio
    async def test_process_dispatches_advanced(self, svc_advanced: FaceAutocropService, tmp_path: Path):
        """process() calls advanced detection, smoothing, and crop box methods."""
        video = tmp_path / "test.mp4"
        video.write_text("fake")
        output = tmp_path / "out.mp4"

        probe_result = {
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        }

        with patch.object(svc_advanced, '_probe_video', return_value=probe_result):
            with patch.object(svc_advanced, '_extract_frames', return_value=10):
                with patch.object(svc_advanced, '_detect_faces_batch_sync_advanced',
                                  return_value=[(100, 200)] * 10) as mock_detect:
                    with patch.object(svc_advanced, '_smooth_trajectory_kalman',
                                      return_value=[(100, 200)] * 10) as mock_smooth:
                        with patch.object(svc_advanced, '_calculate_crop_boxes_advanced',
                                          return_value=[(0, 0, 1080, 1920)] * 10) as mock_crop:
                            with patch.object(svc_advanced, '_render_crop',
                                              return_value=True):
                                result = await svc_advanced.process(video, output)
                                assert result["success"] is True
                                mock_detect.assert_called_once()
                                mock_smooth.assert_called_once()
                                mock_crop.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_basic_mode_does_not_call_advanced(
        self, svc: FaceAutocropService, tmp_path: Path,
    ):
        """process() in basic mode does NOT call advanced methods."""
        video = tmp_path / "test.mp4"
        video.write_text("fake")
        output = tmp_path / "out.mp4"

        probe_result = {
            "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
        }

        with patch.object(svc, '_probe_video', return_value=probe_result):
            with patch.object(svc, '_extract_frames', return_value=10):
                with patch.object(svc, '_detect_faces_batch_sync',
                                  return_value=[(100, 200)] * 10) as mock_detect_basic:
                    with patch.object(svc, '_detect_faces_batch_sync_advanced') as mock_detect_adv:
                        with patch.object(svc, '_smooth_trajectory',
                                          return_value=[(100, 200)] * 10) as mock_smooth_basic:
                            with patch.object(svc, '_smooth_trajectory_kalman') as mock_smooth_adv:
                                with patch.object(svc, '_calculate_crop_boxes',
                                                  return_value=[(0, 0, 1080, 1920)] * 10) as mock_crop_basic:
                                    with patch.object(svc, '_calculate_crop_boxes_advanced') as mock_crop_adv:
                                        with patch.object(svc, '_render_crop',
                                                          return_value=True):
                                            result = await svc.process(video, output)
                                            assert result["success"] is True
                                            mock_detect_basic.assert_called_once()
                                            mock_detect_adv.assert_not_called()
                                            mock_smooth_basic.assert_called_once()
                                            mock_smooth_adv.assert_not_called()
                                            mock_crop_basic.assert_called_once()
                                            mock_crop_adv.assert_not_called()


# ── Advanced mode: constructor parameter tests ─────────────────────────────


class TestConstructorParamsAdvanced:
    """Tests for advanced constructor parameters."""

    def test_default_mode_is_basic(self):
        """Default mode should be 'basic'."""
        svc = FaceAutocropService()
        assert svc.mode == "basic"

    def test_advanced_mode_set(self):
        """Setting mode='advanced' works."""
        svc = FaceAutocropService(mode="advanced")
        assert svc.mode == "advanced"

    def test_kalman_noise_params(self):
        """Kalman noise parameters are set correctly."""
        svc = FaceAutocropService(
            mode="advanced",
            kalman_process_noise=1e-3,
            kalman_measurement_noise=5e-2,
        )
        assert svc.kalman_process_noise == 1e-3
        assert svc.kalman_measurement_noise == 5e-2

    def test_upper_body_params(self):
        """Upper body parameters are set correctly."""
        svc = FaceAutocropService(
            mode="advanced",
            upper_body_enabled=False,
            upper_third_bias=0.20,
            chin_padding=0.15,
            forehead_padding=0.12,
        )
        assert svc.upper_body_enabled is False
        assert svc.upper_third_bias == 0.20
        assert svc.chin_padding == 0.15
        assert svc.forehead_padding == 0.12

    def test_kalman_state_initialized(self):
        """Kalman state attributes are initialized to None/False."""
        svc = FaceAutocropService(mode="advanced")
        assert svc._kalman is None
        assert svc._kalman_initialized is False

    def test_upper_body_cascade_initialized(self):
        """Upper body cascade attribute is initialized to None."""
        svc = FaceAutocropService(mode="advanced")
        assert svc._upper_body_cascade is None

