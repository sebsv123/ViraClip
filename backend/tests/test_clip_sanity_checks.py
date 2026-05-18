"""Tests for the QA sanity checks module (clip_sanity_checks.py)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.qa.clip_sanity_checks import (
    MAX_DESYNC_MS,
    MAX_SUBTITLE_STREAMS,
    MIN_BROLL_UNIQUE_IDS,
    SanityCheckResult,
    SanityReport,
    _detect_burned_in_subtitles,
    _estimate_audio_sync,
    _frame_has_subtitle_band,
    _get_video_stream_info,
    _measure_loudness,
    _run_ffprobe,
    _safe_float,
    check_audio_sync_and_loudness,
    check_broll_diversity,
    check_no_triple_subtitles,
    check_stable_framing,
    run_all_sanity_checks,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_ffprobe_streams() -> str:
    """Return a realistic ffprobe JSON output for a 30s 1080p clip."""
    return json.dumps({
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "duration": "30.0",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "duration": "30.0",
            },
            {
                "index": 2,
                "codec_type": "subtitle",
                "duration": "30.0",
            },
        ],
        "format": {
            "filename": "/tmp/test.mp4",
            "duration": "30.0",
        },
    })


@pytest.fixture
def mock_ffprobe_no_subtitles() -> str:
    """ffprobe output with no subtitle streams."""
    return json.dumps({
        "streams": [
            {"index": 0, "codec_type": "video", "width": 1920, "height": 1080,
             "r_frame_rate": "30/1", "duration": "30.0"},
            {"index": 1, "codec_type": "audio", "duration": "30.0"},
        ],
        "format": {"filename": "/tmp/test.mp4", "duration": "30.0"},
    })


@pytest.fixture
def mock_ffprobe_many_subtitles() -> str:
    """ffprobe output with 4 subtitle streams (exceeds MAX_SUBTITLE_STREAMS)."""
    streams = [
        {"index": 0, "codec_type": "video", "width": 1920, "height": 1080,
         "r_frame_rate": "30/1", "duration": "30.0"},
        {"index": 1, "codec_type": "audio", "duration": "30.0"},
    ]
    for i in range(4):
        streams.append({"index": 2 + i, "codec_type": "subtitle", "duration": "30.0"})
    return json.dumps({"streams": streams, "format": {"filename": "/tmp/test.mp4", "duration": "30.0"}})


@pytest.fixture
def mock_loudnorm_output() -> str:
    """Simulated FFmpeg loudnorm stderr output with JSON."""
    return (
        "Some ffmpeg output...\n"
        "Parsed_loudnorm_0\n"
        '{\n'
        '  "input_i" : "-14.2",\n'
        '  "input_lra" : "7.0",\n'
        '  "input_tp" : "-1.5",\n'
        '  "input_thresh" : "-31.0",\n'
        '  "output_i" : "-14.0",\n'
        '  "output_lra" : "1.0",\n'
        '  "output_tp" : "-1.0",\n'
        '  "output_thresh" : "-31.0",\n'
        '  "normalization_type" : "dynamic",\n'
        '  "target_offset" : "0.0"\n'
        '}\n'
        "more output...\n"
    )


@pytest.fixture
def mock_loudnorm_quiet_output() -> str:
    """Loudnorm output indicating audio is too quiet (-18 LUFS)."""
    return (
        "Parsed_loudnorm_0\n"
        '{\n'
        '  "input_i" : "-18.5",\n'
        '  "input_lra" : "6.0",\n'
        '  "input_tp" : "-3.0",\n'
        '  "output_i" : "-14.0"\n'
        '}\n'
    )


@pytest.fixture
def mock_loudnorm_loud_output() -> str:
    """Loudnorm output indicating audio is too loud (-10 LUFS)."""
    return (
        "Parsed_loudnorm_0\n"
        '{\n'
        '  "input_i" : "-10.2",\n'
        '  "input_lra" : "8.0",\n'
        '  "input_tp" : "-0.5",\n'
        '  "output_i" : "-14.0"\n'
        '}\n'
    )


@pytest.fixture
def sample_task_context() -> Dict[str, Any]:
    """A realistic task context with good B-roll diversity."""
    return {
        "broll_sources": [
            "pexels_12345",
            "pexels_67890",
            "pexels_11111",
        ],
        "broll_metadata": [
            {"source_id": "pexels_22222", "url": "https://pexels.com/video/22222"},
            {"source_id": "pexels_33333", "url": "https://pexels.com/video/33333"},
        ],
        "clips": [
            {
                "broll_sources": ["pexels_44444", "pexels_55555"],
            },
        ],
    }


# ── SanityCheckResult tests ───────────────────────────────────────────────────────


class TestSanityCheckResult:
    """Tests for the SanityCheckResult dataclass."""

    def test_default_values(self):
        """SanityCheckResult has sensible defaults."""
        result = SanityCheckResult(name="Test Check", passed=True)
        assert result.name == "Test Check"
        assert result.passed is True
        assert result.details == ""
        assert result.metrics == {}

    def test_to_dict(self):
        """to_dict serialises correctly."""
        result = SanityCheckResult(
            name="Test",
            passed=True,
            details="All good",
            metrics={"value": 42},
        )
        d = result.to_dict()
        assert d["name"] == "Test"
        assert d["passed"] is True
        assert d["details"] == "All good"
        assert d["metrics"]["value"] == 42

    def test_to_dict_failed(self):
        """to_dict works for failed checks too."""
        result = SanityCheckResult(
            name="Test",
            passed=False,
            details="Something wrong",
            metrics={"error": "timeout"},
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert d["metrics"]["error"] == "timeout"


# ── SanityReport tests ────────────────────────────────────────────────────────────


class TestSanityReport:
    """Tests for the SanityReport dataclass."""

    def test_default_values(self):
        """SanityReport has sensible defaults."""
        report = SanityReport(clip_path="/tmp/clip.mp4")
        assert report.clip_path == "/tmp/clip.mp4"
        assert report.checks == []
        assert report.overall_pass is True

    def test_to_dict(self):
        """to_dict serialises correctly."""
        report = SanityReport(
            clip_path="/tmp/clip.mp4",
            checks=[
                SanityCheckResult(name="Check 1", passed=True),
                SanityCheckResult(name="Check 2", passed=False),
            ],
            overall_pass=False,
        )
        d = report.to_dict()
        assert d["clip_path"] == "/tmp/clip.mp4"
        assert d["overall_pass"] is False
        assert len(d["checks"]) == 2
        assert d["checks"][0]["name"] == "Check 1"
        assert d["checks"][1]["passed"] is False

    def test_overall_pass_all_good(self):
        """overall_pass is True when all checks pass."""
        report = SanityReport(
            clip_path="/tmp/clip.mp4",
            checks=[
                SanityCheckResult(name="A", passed=True),
                SanityCheckResult(name="B", passed=True),
            ],
        )
        assert report.overall_pass is True

    def test_overall_pass_any_fail(self):
        """overall_pass is False when any check fails."""
        report = SanityReport(
            clip_path="/tmp/clip.mp4",
            checks=[
                SanityCheckResult(name="A", passed=True),
                SanityCheckResult(name="B", passed=False),
            ],
        )
        assert report.overall_pass is False


# ── _safe_float tests ─────────────────────────────────────────────────────────────


class TestSafeFloat:
    """Tests for the _safe_float helper."""

    def test_none(self):
        """_safe_float returns None for None input."""
        assert _safe_float(None) is None

    def test_float_string(self):
        """_safe_float parses float strings."""
        assert _safe_float("-14.2") == -14.2
        assert _safe_float("0.0") == 0.0

    def test_int_string(self):
        """_safe_float parses integer strings."""
        assert _safe_float("42") == 42.0

    def test_float_value(self):
        """_safe_float passes through float values."""
        assert _safe_float(3.14) == 3.14

    def test_int_value(self):
        """_safe_float converts int to float."""
        assert _safe_float(42) == 42.0

    def test_invalid_string(self):
        """_safe_float returns None for unparseable strings."""
        assert _safe_float("not-a-number") is None

    def test_empty_string(self):
        """_safe_float returns None for empty string."""
        assert _safe_float("") is None


# ── _run_ffprobe tests ────────────────────────────────────────────────────────────


class TestRunFfprobe:
    """Tests for the _run_ffprobe helper."""

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_success(self, mock_run):
        """_run_ffprobe returns stdout on success."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b'{"key": "value"}'
        mock_proc.stderr = b""
        mock_run.return_value = mock_proc

        result = _run_ffprobe(["ffprobe", "input.mp4"])
        assert result == '{"key": "value"}'

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_failure(self, mock_run):
        """_run_ffprobe raises RuntimeError on non-zero exit."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = b""
        mock_proc.stderr = b"error: file not found"
        mock_run.return_value = mock_proc

        with pytest.raises(RuntimeError, match="ffprobe failed"):
            _run_ffprobe(["ffprobe", "nonexistent.mp4"])

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_timeout(self, mock_run):
        """_run_ffprobe raises on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", "timed out")

        with pytest.raises(TimeoutError):
            _run_ffprobe(["ffprobe", "input.mp4"], timeout=1)


# ── _get_video_stream_info tests ──────────────────────────────────────────────────


class TestGetVideoStreamInfo:
    """Tests for the _get_video_stream_info helper."""

    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_parses_all_streams(self, mock_ffprobe, mock_ffprobe_streams):
        """_get_video_stream_info parses video, audio, and subtitle streams."""
        mock_ffprobe.return_value = mock_ffprobe_streams

        info = _get_video_stream_info("/tmp/test.mp4")

        assert info["duration_s"] == 30.0
        assert info["width"] == 1920
        assert info["height"] == 1080
        assert info["fps"] == 30.0
        assert info["video_streams"] == 1
        assert info["audio_streams"] == 1
        assert info["subtitle_streams"] == 1

    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_no_subtitles(self, mock_ffprobe, mock_ffprobe_no_subtitles):
        """_get_video_stream_info handles missing subtitle streams."""
        mock_ffprobe.return_value = mock_ffprobe_no_subtitles

        info = _get_video_stream_info("/tmp/test.mp4")

        assert info["subtitle_streams"] == 0
        assert info["video_streams"] == 1
        assert info["audio_streams"] == 1

    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_fps_parsing(self, mock_ffprobe):
        """_get_video_stream_info handles various fps formats."""
        mock_ffprobe.return_value = json.dumps({
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1920, "height": 1080,
                 "r_frame_rate": "30000/1001", "duration": "30.0"},
            ],
            "format": {"duration": "30.0"},
        })

        info = _get_video_stream_info("/tmp/test.mp4")
        assert info["fps"] == pytest.approx(29.97, rel=1e-2)

    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_fps_division_by_zero(self, mock_ffprobe):
        """_get_video_stream_info handles 0/1 fps gracefully."""
        mock_ffprobe.return_value = json.dumps({
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1920, "height": 1080,
                 "r_frame_rate": "0/1", "duration": "30.0"},
            ],
            "format": {"duration": "30.0"},
        })

        info = _get_video_stream_info("/tmp/test.mp4")
        assert info["fps"] == 0.0

    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_no_duration(self, mock_ffprobe):
        """_get_video_stream_info handles missing duration."""
        mock_ffprobe.return_value = json.dumps({
            "streams": [],
            "format": {},
        })

        info = _get_video_stream_info("/tmp/test.mp4")
        assert info["duration_s"] == 0.0
        assert info["video_streams"] == 0


# ── check_no_triple_subtitles tests ───────────────────────────────────────────────


class TestCheckNoTripleSubtitles:
    """Tests for the check_no_triple_subtitles function."""

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    @patch("src.qa.clip_sanity_checks._detect_burned_in_subtitles")
    def test_passes_with_few_subtitles(self, mock_burned, mock_info):
        """Passes when subtitle streams <= MAX_SUBTITLE_STREAMS and no burned-in text."""
        mock_info.return_value = {
            "subtitle_streams": 1,
            "duration_s": 30.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "audio_streams": 1,
            "video_streams": 1,
        }
        mock_burned.return_value = 0

        result = check_no_triple_subtitles("/tmp/test.mp4")

        assert result.passed is True
        assert result.name == "Triple Subtitles"
        assert result.metrics["subtitle_streams"] == 1
        assert result.metrics["burned_in_frames"] == 0

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    def test_fails_with_many_subtitle_streams(self, mock_info, mock_ffprobe_many_subtitles):
        """Fails when subtitle streams exceed MAX_SUBTITLE_STREAMS."""
        mock_info.return_value = {
            "subtitle_streams": 4,
            "duration_s": 30.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "audio_streams": 1,
            "video_streams": 1,
        }

        result = check_no_triple_subtitles("/tmp/test.mp4")

        assert result.passed is False
        assert "Found 4 embedded subtitle streams" in result.details
        assert result.metrics["subtitle_streams"] == 4

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    @patch("src.qa.clip_sanity_checks._detect_burned_in_subtitles")
    def test_fails_with_burned_in_text(self, mock_burned, mock_info):
        """Fails when burned-in subtitle text is detected on many frames."""
        mock_info.return_value = {
            "subtitle_streams": 1,
            "duration_s": 30.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "audio_streams": 1,
            "video_streams": 1,
        }
        mock_burned.return_value = 4  # > 2 frames with text

        result = check_no_triple_subtitles("/tmp/test.mp4")

        assert result.passed is False
        assert "burned-in subtitle text" in result.details
        assert result.metrics["burned_in_frames"] == 4

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    def test_handles_exception_gracefully(self, mock_info):
        """Returns failed result when an exception occurs."""
        mock_info.side_effect = RuntimeError("ffprobe not found")

        result = check_no_triple_subtitles("/tmp/test.mp4")

        assert result.passed is False
        assert "Check error" in result.details
        assert "ffprobe not found" in result.details


# ── _detect_burned_in_subtitles tests ─────────────────────────────────────────────


class TestDetectBurnedInSubtitles:
    """Tests for the _detect_burned_in_subtitles helper."""

    @patch("src.qa.clip_sanity_checks.Path.exists")
    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    @patch("src.qa.clip_sanity_checks.subprocess.run")
    @patch("src.qa.clip_sanity_checks._frame_has_subtitle_band")
    def test_detects_text_frames(self, mock_band, mock_run, mock_info, mock_exists):
        """Returns count of frames with subtitle bands."""
        mock_info.return_value = {"duration_s": 30.0}
        mock_run.return_value = MagicMock(returncode=0)
        mock_band.side_effect = [True, False, True, False, True]
        mock_exists.return_value = True

        count = _detect_burned_in_subtitles("/tmp/test.mp4", num_samples=5)

        assert count == 3
        assert mock_band.call_count == 5

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    def test_returns_zero_on_error(self, mock_info):
        """Returns 0 when an error occurs."""
        mock_info.side_effect = RuntimeError("error")

        count = _detect_burned_in_subtitles("/tmp/test.mp4")
        assert count == 0

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    def test_returns_zero_for_zero_duration(self, mock_info):
        """Returns 0 when duration is 0."""
        mock_info.return_value = {"duration_s": 0.0}

        count = _detect_burned_in_subtitles("/tmp/test.mp4")
        assert count == 0


# ── _frame_has_subtitle_band tests ────────────────────────────────────────────────


class TestFrameHasSubtitleBand:
    """Tests for the _frame_has_subtitle_band helper."""

    @patch("src.qa.clip_sanity_checks.cv2.imread")
    def test_detects_text_band(self, mock_imread):
        """Returns True when a text-like band is found in bottom third."""
        # Create a 100x200 image with a white band in bottom third
        img = np.zeros((100, 200), dtype=np.uint8)
        img[75:85, :] = 200  # White band in bottom third
        mock_imread.return_value = img

        assert _frame_has_subtitle_band("/tmp/frame.png") is True

    @patch("src.qa.clip_sanity_checks.cv2.imread")
    def test_no_text_band(self, mock_imread):
        """Returns False when no text-like band is found."""
        # Uniform gray image
        img = np.full((100, 200), 128, dtype=np.uint8)
        mock_imread.return_value = img

        assert _frame_has_subtitle_band("/tmp/frame.png") is False

    @patch("src.qa.clip_sanity_checks.cv2.imread")
    def test_returns_false_for_none_image(self, mock_imread):
        """Returns False when cv2.imread returns None."""
        mock_imread.return_value = None

        assert _frame_has_subtitle_band("/tmp/frame.png") is False

    @patch("src.qa.clip_sanity_checks.cv2.imread")
    def test_handles_exception(self, mock_imread):
        """Returns False when an exception occurs."""
        mock_imread.side_effect = RuntimeError("OpenCV error")

        assert _frame_has_subtitle_band("/tmp/frame.png") is False


# ── check_broll_diversity tests ───────────────────────────────────────────────────


class TestCheckBrollDiversity:
    """Tests for the check_broll_diversity function."""

    def test_passes_with_good_diversity(self, sample_task_context):
        """Passes when there are enough unique B-roll sources."""
        result = check_broll_diversity(sample_task_context)

        assert result.passed is True
        assert result.name == "B-Roll Diversity"
        assert result.metrics["unique_sources"] >= MIN_BROLL_UNIQUE_IDS
        assert result.metrics["total_sources"] > 0

    def test_fails_with_no_sources(self):
        """Fails when no B-roll sources are found."""
        result = check_broll_diversity({})

        assert result.passed is False
        assert "No B-roll sources found" in result.details
        assert result.metrics["total_sources"] == 0

    def test_fails_with_single_source(self):
        """Fails when only one unique source is found."""
        context = {"broll_sources": ["pexels_12345", "pexels_12345", "pexels_12345"]}
        result = check_broll_diversity(context)

        assert result.passed is False
        assert "Low B-roll diversity" in result.details
        assert result.metrics["unique_sources"] == 1

    def test_handles_broll_metadata_format(self):
        """Handles broll_metadata list of dicts."""
        context = {
            "broll_metadata": [
                {"source_id": "pexels_111"},
                {"source_id": "pexels_222"},
                {"source_id": "pexels_333"},
            ],
        }
        result = check_broll_diversity(context)

        assert result.passed is True
        assert result.metrics["unique_sources"] == 3

    def test_handles_clips_format(self):
        """Handles clips list with nested broll_sources."""
        context = {
            "clips": [
                {"broll_sources": ["pexels_a", "pexels_b"]},
                {"broll_sources": ["pexels_c"]},
            ],
        }
        result = check_broll_diversity(context)

        assert result.passed is True
        assert result.metrics["unique_sources"] == 3

    def test_handles_mixed_formats(self):
        """Handles combination of broll_sources, broll_metadata, and clips."""
        context = {
            "broll_sources": ["pexels_1", "pexels_2"],
            "broll_metadata": [{"source_id": "pexels_3"}],
            "clips": [{"broll_ids": ["pexels_4", "pexels_5"]}],
        }
        result = check_broll_diversity(context)

        assert result.passed is True
        assert result.metrics["unique_sources"] == 5

    def test_handles_exception_gracefully(self):
        """Returns failed result when an exception occurs."""
        # Pass something that will cause an error when iterating
        class BrokenDict(dict):
            def get(self, key, default=None):
                raise RuntimeError("boom")

        result = check_broll_diversity(BrokenDict())

        assert result.passed is False
        assert "Check error" in result.details

    def test_diversity_ratio_calculation(self):
        """Diversity ratio is correctly calculated."""
        context = {"broll_sources": ["a", "a", "b", "b", "c"]}
        result = check_broll_diversity(context)

        assert result.metrics["total_sources"] == 5
        assert result.metrics["unique_sources"] == 3
        assert result.metrics["diversity_ratio"] == 0.6  # 3/5


# ── check_stable_framing tests ────────────────────────────────────────────────────


class TestCheckStableFraming:
    """Tests for the check_stable_framing function."""

    @patch("src.qa.clip_sanity_checks.cv2.VideoCapture")
    def test_passes_with_stable_framing(self, mock_cap_class):
        """Passes when frame differences are low (stable)."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        # Use integer constants for CAP_PROP keys (7=frame count, 5=fps)
        mock_cap.get.side_effect = lambda prop: {
            7: 300,   # CAP_PROP_FRAME_COUNT
            5: 30.0,  # CAP_PROP_FPS
        }.get(prop, 0)

        # Return stable frames (low difference)
        frames_called = [False]

        def mock_read():
            if not frames_called[0]:
                frames_called[0] = True
                return True, np.zeros((100, 100, 3), dtype=np.uint8)
            return True, np.ones((100, 100, 3), dtype=np.uint8) * 5

        mock_cap.read.side_effect = mock_read
        mock_cap_class.return_value = mock_cap

        result = check_stable_framing("/tmp/test.mp4")

        assert result.passed is True
        assert "Framing stable" in result.details

    @patch("src.qa.clip_sanity_checks.cv2.VideoCapture")
    def test_fails_with_jitter(self, mock_cap_class):
        """Fails when frame differences are high (jitter)."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            7: 300,    # CAP_PROP_FRAME_COUNT
            5: 30.0,   # CAP_PROP_FPS
        }.get(prop, 0)

        frames_called = [False]

        def mock_read():
            if not frames_called[0]:
                frames_called[0] = True
                return True, np.zeros((100, 100, 3), dtype=np.uint8)
            # Return very different frame to simulate jitter
            return True, np.ones((100, 100, 3), dtype=np.uint8) * 255

        mock_cap.read.side_effect = mock_read
        mock_cap_class.return_value = mock_cap

        result = check_stable_framing("/tmp/test.mp4")

        assert result.passed is False
        assert "High jitter" in result.details

    @patch("src.qa.clip_sanity_checks.cv2.VideoCapture")
    def test_fails_when_cannot_open(self, mock_cap_class):
        """Fails when video cannot be opened."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_cap_class.return_value = mock_cap

        result = check_stable_framing("/tmp/test.mp4")

        assert result.passed is False
        assert "Cannot open video" in result.details

    @patch("src.qa.clip_sanity_checks.cv2.VideoCapture")
    def test_fails_with_short_video(self, mock_cap_class):
        """Fails when video has too few frames."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            7: 1,     # CAP_PROP_FRAME_COUNT — only 1 frame
            5: 30.0,  # CAP_PROP_FPS
        }.get(prop, 0)
        mock_cap_class.return_value = mock_cap

        result = check_stable_framing("/tmp/test.mp4")

        assert result.passed is False
        assert "too short" in result.details

    @patch("src.qa.clip_sanity_checks.cv2.VideoCapture")
    def test_handles_exception_gracefully(self, mock_cap_class):
        """Returns failed result when an exception occurs."""
        mock_cap = MagicMock()
        mock_cap.isOpened.side_effect = RuntimeError("OpenCV error")
        mock_cap_class.return_value = mock_cap

        result = check_stable_framing("/tmp/test.mp4")

        assert result.passed is False
        assert "Check error" in result.details


# ── check_audio_sync_and_loudness tests ───────────────────────────────────────────


class TestCheckAudioSyncAndLoudness:
    """Tests for the check_audio_sync_and_loudness function."""

    @patch("src.qa.clip_sanity_checks._measure_loudness")
    @patch("src.qa.clip_sanity_checks._estimate_audio_sync")
    def test_passes_with_good_audio(self, mock_sync, mock_loudness):
        """Passes when loudness is in range and sync is good."""
        mock_loudness.return_value = {
            "integrated_loudness": -14.2,
            "loudness_range": 7.0,
            "true_peak": -1.5,
        }
        mock_sync.return_value = 30.0  # 30ms desync, well under 100ms

        result = check_audio_sync_and_loudness("/tmp/test.mp4")

        assert result.passed is True
        assert "Audio OK" in result.details
        assert result.metrics["integrated_loudness_lufs"] == -14.2
        assert result.metrics["estimated_desync_ms"] == 30.0

    @patch("src.qa.clip_sanity_checks._measure_loudness")
    @patch("src.qa.clip_sanity_checks._estimate_audio_sync")
    def test_fails_when_too_quiet(self, mock_sync, mock_loudness):
        """Fails when loudness is below LOUDNESS_MIN."""
        mock_loudness.return_value = {
            "integrated_loudness": -18.5,
            "loudness_range": 6.0,
            "true_peak": -3.0,
        }
        mock_sync.return_value = 20.0

        result = check_audio_sync_and_loudness("/tmp/test.mp4")

        assert result.passed is False
        assert "Too quiet" in result.details
        assert result.metrics["integrated_loudness_lufs"] == -18.5

    @patch("src.qa.clip_sanity_checks._measure_loudness")
    @patch("src.qa.clip_sanity_checks._estimate_audio_sync")
    def test_fails_when_too_loud(self, mock_sync, mock_loudness):
        """Fails when loudness is above LOUDNESS_MAX."""
        mock_loudness.return_value = {
            "integrated_loudness": -10.2,
            "loudness_range": 8.0,
            "true_peak": -0.5,
        }
        mock_sync.return_value = 20.0

        result = check_audio_sync_and_loudness("/tmp/test.mp4")

        assert result.passed is False
        assert "Too loud" in result.details
        assert result.metrics["integrated_loudness_lufs"] == -10.2

    @patch("src.qa.clip_sanity_checks._measure_loudness")
    @patch("src.qa.clip_sanity_checks._estimate_audio_sync")
    def test_fails_when_desynced(self, mock_sync, mock_loudness):
        """Fails when audio desync exceeds MAX_DESYNC_MS."""
        mock_loudness.return_value = {
            "integrated_loudness": -14.0,
            "loudness_range": 7.0,
            "true_peak": -1.5,
        }
        mock_sync.return_value = 500.0  # 500ms desync

        result = check_audio_sync_and_loudness("/tmp/test.mp4")

        assert result.passed is False
        assert "desync" in result.details.lower()
        assert result.metrics["estimated_desync_ms"] == 500.0

    @patch("src.qa.clip_sanity_checks._measure_loudness")
    @patch("src.qa.clip_sanity_checks._estimate_audio_sync")
    def test_fails_when_loudness_unmeasurable(self, mock_sync, mock_loudness):
        """Fails when loudness cannot be measured."""
        mock_loudness.return_value = {
            "integrated_loudness": None,
            "loudness_range": None,
            "true_peak": None,
        }
        mock_sync.return_value = 20.0

        result = check_audio_sync_and_loudness("/tmp/test.mp4")

        assert result.passed is False
        assert "Could not measure loudness" in result.details
        assert result.metrics["integrated_loudness_lufs"] is None

    @patch("src.qa.clip_sanity_checks._measure_loudness")
    @patch("src.qa.clip_sanity_checks._estimate_audio_sync")
    def test_handles_exception_gracefully(self, mock_sync, mock_loudness):
        """Returns failed result when an exception occurs."""
        mock_loudness.side_effect = RuntimeError("FFmpeg error")
        mock_sync.return_value = 20.0

        result = check_audio_sync_and_loudness("/tmp/test.mp4")

        assert result.passed is False
        assert "Check error" in result.details
        assert "FFmpeg error" in result.details


# ── _measure_loudness tests ─────────────────────────────────────────────────────


class TestMeasureLoudness:
    """Tests for the _measure_loudness helper."""

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_parses_loudnorm_output(self, mock_run, mock_loudnorm_output):
        """Parses loudnorm JSON output correctly."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = mock_loudnorm_output.encode()
        mock_run.return_value = mock_proc

        result = _measure_loudness("/tmp/test.mp4")

        assert result["integrated_loudness"] == -14.2
        assert result["loudness_range"] == 7.0
        assert result["true_peak"] == -1.5

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_quiet_audio(self, mock_run, mock_loudnorm_quiet_output):
        """Parses quiet audio loudnorm output."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = mock_loudnorm_quiet_output.encode()
        mock_run.return_value = mock_proc

        result = _measure_loudness("/tmp/test.mp4")

        assert result["integrated_loudness"] == -18.5
        assert result["loudness_range"] == 6.0
        assert result["true_peak"] == -3.0

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_loud_audio(self, mock_run, mock_loudnorm_loud_output):
        """Parses loud audio loudnorm output."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = mock_loudnorm_loud_output.encode()
        mock_run.return_value = mock_proc

        result = _measure_loudness("/tmp/test.mp4")

        assert result["integrated_loudness"] == -10.2
        assert result["loudness_range"] == 8.0
        assert result["true_peak"] == -0.5

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_unparseable_output(self, mock_run):
        """Returns None values when output cannot be parsed."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = b"some random ffmpeg output without JSON"
        mock_run.return_value = mock_proc

        result = _measure_loudness("/tmp/test.mp4")

        assert result["integrated_loudness"] is None
        assert result["loudness_range"] is None
        assert result["true_peak"] is None

    @patch("src.qa.clip_sanity_checks.subprocess.run")
    def test_handles_timeout(self, mock_run):
        """Returns None values on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", "timed out")

        result = _measure_loudness("/tmp/test.mp4")

        assert result["integrated_loudness"] is None
        assert result["loudness_range"] is None
        assert result["true_peak"] is None


# ── _estimate_audio_sync tests ──────────────────────────────────────────────────


class TestEstimateAudioSync:
    """Tests for the _estimate_audio_sync helper."""

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_matching_durations(self, mock_ffprobe, mock_info):
        """Returns ~0ms desync when audio and video durations match."""
        mock_info.return_value = {"duration_s": 30.0}
        mock_ffprobe.return_value = json.dumps({
            "streams": [
                {"index": 0, "codec_type": "audio", "duration": "30.0"},
            ],
        })

        desync = _estimate_audio_sync("/tmp/test.mp4")

        assert desync is not None
        assert desync < 1.0  # Less than 1ms desync

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_mismatched_durations(self, mock_ffprobe, mock_info):
        """Returns correct desync when durations differ."""
        mock_info.return_value = {"duration_s": 30.0}
        mock_ffprobe.return_value = json.dumps({
            "streams": [
                {"index": 0, "codec_type": "audio", "duration": "29.5"},
            ],
        })

        desync = _estimate_audio_sync("/tmp/test.mp4")

        assert desync is not None
        assert desync == pytest.approx(500.0, rel=1.0)  # ~500ms desync

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_no_audio_stream(self, mock_ffprobe, mock_info):
        """Returns None when no audio stream is found."""
        mock_info.return_value = {"duration_s": 30.0}
        mock_ffprobe.return_value = json.dumps({"streams": []})

        desync = _estimate_audio_sync("/tmp/test.mp4")

        assert desync is None

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    def test_zero_video_duration(self, mock_info):
        """Returns None when video duration is 0."""
        mock_info.return_value = {"duration_s": 0.0}

        desync = _estimate_audio_sync("/tmp/test.mp4")

        assert desync is None

    @patch("src.qa.clip_sanity_checks._get_video_stream_info")
    @patch("src.qa.clip_sanity_checks._run_ffprobe")
    def test_handles_exception(self, mock_ffprobe, mock_info):
        """Returns None when an exception occurs."""
        mock_info.side_effect = RuntimeError("error")

        desync = _estimate_audio_sync("/tmp/test.mp4")

        assert desync is None


# ── run_all_sanity_checks tests ─────────────────────────────────────────────────


class TestRunAllSanityChecks:
    """Tests for the run_all_sanity_checks aggregation function."""

    @patch("src.qa.clip_sanity_checks.check_audio_sync_and_loudness")
    @patch("src.qa.clip_sanity_checks.check_stable_framing")
    @patch("src.qa.clip_sanity_checks.check_no_triple_subtitles")
    def test_all_pass(self, mock_subtitles, mock_framing, mock_audio):
        """Returns overall_pass=True when all checks pass."""
        mock_subtitles.return_value = SanityCheckResult(name="Triple Subtitles", passed=True)
        mock_framing.return_value = SanityCheckResult(name="Stable Framing", passed=True)
        mock_audio.return_value = SanityCheckResult(name="Audio Sync & Loudness", passed=True)

        report = run_all_sanity_checks("/tmp/test.mp4")

        assert report.overall_pass is True
        assert len(report.checks) == 3
        assert report.clip_path == "/tmp/test.mp4"

    @patch("src.qa.clip_sanity_checks.check_audio_sync_and_loudness")
    @patch("src.qa.clip_sanity_checks.check_stable_framing")
    @patch("src.qa.clip_sanity_checks.check_no_triple_subtitles")
    def test_some_fail(self, mock_subtitles, mock_framing, mock_audio):
        """Returns overall_pass=False when any check fails."""
        mock_subtitles.return_value = SanityCheckResult(name="Triple Subtitles", passed=True)
        mock_framing.return_value = SanityCheckResult(name="Stable Framing", passed=False)
        mock_audio.return_value = SanityCheckResult(name="Audio Sync & Loudness", passed=True)

        report = run_all_sanity_checks("/tmp/test.mp4")

        assert report.overall_pass is False
        assert len(report.checks) == 3

    @patch("src.qa.clip_sanity_checks.check_audio_sync_and_loudness")
    @patch("src.qa.clip_sanity_checks.check_stable_framing")
    @patch("src.qa.clip_sanity_checks.check_no_triple_subtitles")
    def test_all_fail(self, mock_subtitles, mock_framing, mock_audio):
        """Returns overall_pass=False when all checks fail."""
        mock_subtitles.return_value = SanityCheckResult(name="Triple Subtitles", passed=False)
        mock_framing.return_value = SanityCheckResult(name="Stable Framing", passed=False)
        mock_audio.return_value = SanityCheckResult(name="Audio Sync & Loudness", passed=False)

        report = run_all_sanity_checks("/tmp/test.mp4")

        assert report.overall_pass is False
        assert len(report.checks) == 3

    @patch("src.qa.clip_sanity_checks.check_audio_sync_and_loudness")
    @patch("src.qa.clip_sanity_checks.check_stable_framing")
    @patch("src.qa.clip_sanity_checks.check_no_triple_subtitles")
    @patch("src.qa.clip_sanity_checks.check_broll_diversity")
    def test_with_task_context(self, mock_broll, mock_subtitles, mock_framing, mock_audio):
        """Includes B-roll diversity check when task_context is provided."""
        mock_subtitles.return_value = SanityCheckResult(name="Triple Subtitles", passed=True)
        mock_framing.return_value = SanityCheckResult(name="Stable Framing", passed=True)
        mock_audio.return_value = SanityCheckResult(name="Audio Sync & Loudness", passed=True)
        mock_broll.return_value = SanityCheckResult(name="B-Roll Diversity", passed=True)

        report = run_all_sanity_checks("/tmp/test.mp4", task_context={"broll_sources": ["a", "b"]})

        assert report.overall_pass is True
        assert len(report.checks) == 4
        mock_broll.assert_called_once_with({"broll_sources": ["a", "b"]})

    @patch("src.qa.clip_sanity_checks.check_audio_sync_and_loudness")
    @patch("src.qa.clip_sanity_checks.check_stable_framing")
    @patch("src.qa.clip_sanity_checks.check_no_triple_subtitles")
    def test_without_task_context(self, mock_subtitles, mock_framing, mock_audio):
        """Skips B-roll diversity check when task_context is None."""
        mock_subtitles.return_value = SanityCheckResult(name="Triple Subtitles", passed=True)
        mock_framing.return_value = SanityCheckResult(name="Stable Framing", passed=True)
        mock_audio.return_value = SanityCheckResult(name="Audio Sync & Loudness", passed=True)

        report = run_all_sanity_checks("/tmp/test.mp4", task_context=None)

        assert report.overall_pass is True
        assert len(report.checks) == 3

    def test_to_dict_serialisation(self):
        """SanityReport.to_dict works after run_all_sanity_checks."""
        report = SanityReport(
            clip_path="/tmp/test.mp4",
            checks=[
                SanityCheckResult(name="A", passed=True),
                SanityCheckResult(name="B", passed=False),
            ],
            overall_pass=False,
        )
        d = report.to_dict()
        assert d["clip_path"] == "/tmp/test.mp4"
        assert d["overall_pass"] is False
        assert len(d["checks"]) == 2
        assert d["checks"][0]["name"] == "A"
        assert d["checks"][1]["passed"] is False
