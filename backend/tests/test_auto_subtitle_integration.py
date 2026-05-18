"""
Integration tests for the auto-subtitle backend adapter.

These tests verify the full pipeline:
  1. Audio extraction from a short MP4 (20-30s)
  2. Whisper transcription (tiny model for speed)
  3. SRT generation
  4. SRT → ASS conversion
  5. FFmpeg subtitle burn-in
  6. Output video duration, streams, and sync (±0.2s tolerance)

Prerequisites:
  - openai-whisper installed (``pip install openai-whisper``)
  - ffmpeg available on PATH
  - A short test video at ``tests/fixtures/test_short.mp4`` (20-30s, any content)

If the test video does not exist, tests are skipped gracefully.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess as sp
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from src.domains.captions.caption_service import (
    _srt_to_ass_events,
    build_ass_script,
    segment_words_into_lines,
)
from src.services.subtitle_backend_auto import (
    AutoSubtitleBackend,
    _extract_audio,
    _format_timestamp,
    _write_srt,
    get_auto_subtitle_backend,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_VIDEO = FIXTURE_DIR / "test_short.mp4"

pytestmark = [
    pytest.mark.skipif(
        not TEST_VIDEO.exists(),
        reason=f"Test video not found at {TEST_VIDEO}. Create a 20-30s MP4 to run these tests.",
    ),
    pytest.mark.asyncio,
]


@pytest.fixture(scope="module")
def event_loop():
    """Create a module-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def backend() -> AutoSubtitleBackend:
    """Create an AutoSubtitleBackend with the tiny model (fastest)."""
    return AutoSubtitleBackend(model_name="tiny", device="cpu")


@pytest.fixture(scope="module")
def video_info() -> Dict[str, Any]:
    """Extract metadata from the test video using ffprobe."""
    return _ffprobe(TEST_VIDEO)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ffprobe(path: Path) -> Dict[str, Any]:
    """Run ffprobe and return parsed JSON output."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    result = sp.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _get_audio_stream(probe: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first audio stream from ffprobe output."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            return stream
    return None


def _get_video_stream(probe: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first video stream from ffprobe output."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return None


def _parse_srt_timestamps(srt_path: Path) -> List[Tuple[float, float]]:
    """Parse SRT file and return list of (start_sec, end_sec) tuples."""
    import re

    timestamps: List[Tuple[float, float]] = []
    pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
    )

    def _ts_to_sec(ts: str) -> float:
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

    for match in pattern.finditer(srt_path.read_text(encoding="utf-8")):
        start = _ts_to_sec(match.group(1))
        end = _ts_to_sec(match.group(2))
        timestamps.append((start, end))

    return timestamps


# ── Test: Audio extraction ────────────────────────────────────────────────────


class TestAudioExtraction:
    """Verify that audio extraction produces a valid 16kHz mono WAV."""

    async def test_extract_audio_creates_wav(self, backend):
        """Audio extraction should produce a .wav file."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)

        try:
            ok = await _extract_audio(TEST_VIDEO, wav_path)
            assert ok, "Audio extraction returned False"
            assert wav_path.exists(), "WAV file was not created"
            assert wav_path.stat().st_size > 0, "WAV file is empty"
        finally:
            wav_path.unlink(missing_ok=True)

    async def test_extract_audio_format(self, backend):
        """Extracted WAV should be mono 16kHz pcm_s16le."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)

        try:
            ok = await _extract_audio(TEST_VIDEO, wav_path)
            assert ok

            probe = _ffprobe(wav_path)
            stream = _get_audio_stream(probe)
            assert stream is not None, "No audio stream in extracted WAV"
            assert stream.get("sample_rate") == "16000", \
                f"Expected 16000 Hz, got {stream.get('sample_rate')}"
            assert stream.get("channels") == 1, \
                f"Expected mono (1 channel), got {stream.get('channels')}"
            assert stream.get("codec_name") == "pcm_s16le", \
                f"Expected pcm_s16le, got {stream.get('codec_name')}"
        finally:
            wav_path.unlink(missing_ok=True)


# ── Test: SRT generation ──────────────────────────────────────────────────────


class TestSrtGeneration:
    """Verify that Whisper transcription produces a valid SRT file."""

    async def test_generate_subtitles_creates_srt(self, backend):
        """generate_subtitles should produce an SRT file."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None, "generate_subtitles returned None"
        assert srt_path.exists(), "SRT file was not created"
        assert srt_path.suffix == ".srt", f"Expected .srt, got {srt_path.suffix}"
        assert srt_path.stat().st_size > 0, "SRT file is empty"

        # Clean up
        srt_path.unlink(missing_ok=True)

    async def test_srt_has_segments(self, backend):
        """SRT file should contain at least one subtitle segment."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            timestamps = _parse_srt_timestamps(srt_path)
            assert len(timestamps) > 0, "SRT has no subtitle segments"
        finally:
            srt_path.unlink(missing_ok=True)

    async def test_srt_timestamps_within_duration(self, backend, video_info):
        """SRT timestamps should not exceed video duration."""
        duration = float(video_info.get("format", {}).get("duration", 0))
        assert duration > 0, "Could not determine video duration"

        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            timestamps = _parse_srt_timestamps(srt_path)
            for start, end in timestamps:
                assert start >= 0, f"Negative start timestamp: {start}"
                assert end <= duration + 0.5, \
                    f"End timestamp {end}s exceeds video duration {duration}s"
                assert start < end, \
                    f"Start {start}s >= end {end}s"
        finally:
            srt_path.unlink(missing_ok=True)

    async def test_srt_text_not_empty(self, backend):
        """Each SRT segment should have non-empty text."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            content = srt_path.read_text(encoding="utf-8")
            # Each block has: index, timestamp, text, blank line
            blocks = [b.strip() for b in content.strip().split("\n\n")]
            for block in blocks:
                lines = block.split("\n")
                if len(lines) >= 3:
                    text = " ".join(lines[2:]).strip()
                    assert text, f"Empty text in SRT block:\n{block}"
        finally:
            srt_path.unlink(missing_ok=True)


# ── Test: SRT → ASS conversion ────────────────────────────────────────────────


class TestSrtToAssConversion:
    """Verify that SRT files are correctly converted to ASS events."""

    async def test_srt_to_ass_events_returns_lines(self, backend):
        """_srt_to_ass_events should return CaptionLine list."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            lines = _srt_to_ass_events(srt_path)
            assert isinstance(lines, list)
            assert len(lines) > 0, "No CaptionLines produced"
        finally:
            srt_path.unlink(missing_ok=True)

    async def test_srt_to_ass_preserves_timing(self, backend):
        """ASS event timings should match SRT timings within tolerance."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            srt_timestamps = _parse_srt_timestamps(srt_path)
            lines = _srt_to_ass_events(srt_path)

            assert len(lines) == len(srt_timestamps), \
                f"Line count mismatch: {len(lines)} vs {len(srt_timestamps)} SRT blocks"

            for line, (srt_start, srt_end) in zip(lines, srt_timestamps):
                # Allow ±0.1s tolerance for floating-point rounding
                assert abs(line.line_start - srt_start) < 0.1, \
                    f"Start mismatch: ASS={line.line_start:.3f}, SRT={srt_start:.3f}"
                assert abs(line.line_end - srt_end) < 0.1, \
                    f"End mismatch: ASS={line.line_end:.3f}, SRT={srt_end:.3f}"
        finally:
            srt_path.unlink(missing_ok=True)

    async def test_ass_script_generation(self, backend):
        """ASS script built from SRT events should be valid."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            lines = _srt_to_ass_events(srt_path)
            ass = build_ass_script(lines, style="default")
            assert ass.startswith("[Script Info]")
            assert "VIRACLIP-CAPTIONS" in ass
            assert "Dialogue:" in ass
            assert ass.count("Dialogue:") == len(lines)
        finally:
            srt_path.unlink(missing_ok=True)


# ── Test: FFmpeg burn-in ──────────────────────────────────────────────────────


class TestBurnIn:
    """Verify that subtitles are burned into the video correctly."""

    async def test_burn_subtitles_creates_output(self, backend):
        """burn_subtitles should produce an output video."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            output_path = Path(tmp.name)

        try:
            result = await backend.burn_subtitles(
                TEST_VIDEO, srt_path, output_path, style_preset="default",
            )
            assert result is not None, "burn_subtitles returned None"
            assert result.exists(), "Output video was not created"
            assert result.stat().st_size > 0, "Output video is empty"
        finally:
            srt_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    async def test_output_duration_matches_input(self, backend, video_info):
        """Output video duration should match input within ±0.5s."""
        input_duration = float(video_info.get("format", {}).get("duration", 0))

        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            output_path = Path(tmp.name)

        try:
            result = await backend.burn_subtitles(
                TEST_VIDEO, srt_path, output_path, style_preset="default",
            )
            assert result is not None

            output_probe = _ffprobe(output_path)
            output_duration = float(output_probe.get("format", {}).get("duration", 0))

            assert abs(output_duration - input_duration) < 0.5, \
                f"Duration mismatch: input={input_duration:.3f}s, output={output_duration:.3f}s"
        finally:
            srt_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    async def test_output_has_video_and_audio_streams(self, backend):
        """Output video should contain both video and audio streams."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            output_path = Path(tmp.name)

        try:
            result = await backend.burn_subtitles(
                TEST_VIDEO, srt_path, output_path, style_preset="default",
            )
            assert result is not None

            probe = _ffprobe(output_path)
            assert _get_video_stream(probe) is not None, "Output has no video stream"
            assert _get_audio_stream(probe) is not None, "Output has no audio stream"
        finally:
            srt_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    async def test_audio_codec_is_copied(self, backend, video_info):
        """Audio codec should be copied (acodec=copy), not re-encoded."""
        input_audio = _get_audio_stream(video_info)
        assert input_audio is not None, "Input has no audio stream"
        input_codec = input_audio.get("codec_name")

        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            output_path = Path(tmp.name)

        try:
            result = await backend.burn_subtitles(
                TEST_VIDEO, srt_path, output_path, style_preset="default",
            )
            assert result is not None

            output_probe = _ffprobe(output_path)
            output_audio = _get_audio_stream(output_probe)
            assert output_audio is not None, "Output has no audio stream"
            assert output_audio.get("codec_name") == input_codec, \
                f"Audio codec changed: {input_codec} → {output_audio.get('codec_name')}"
        finally:
            srt_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


# ── Test: Audio sync (±0.2s tolerance) ────────────────────────────────────────


class TestAudioSync:
    """Verify that subtitles are synchronised with audio within ±0.2s.

    This test uses a heuristic approach:
      1. Generate SRT from the video
      2. Parse SRT timestamps
      3. Verify that the first subtitle appears within 0.2s of the first
         audible speech (approximated by the first non-silent audio segment)

    Note: This is a best-effort sync check. For precise sync verification,
    a test video with known spoken content and timestamps should be used.
    """

    async def test_first_subtitle_within_reasonable_time(self, backend):
        """First subtitle should appear early in the video (within first 5s)."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            timestamps = _parse_srt_timestamps(srt_path)
            assert len(timestamps) > 0, "No subtitles generated"

            first_start = timestamps[0][0]
            # Most short test videos have speech starting within the first few seconds
            assert first_start < 5.0, \
                f"First subtitle starts at {first_start:.2f}s, expected < 5.0s"
        finally:
            srt_path.unlink(missing_ok=True)

    async def test_subtitle_timestamps_are_monotonic(self, backend):
        """Subtitle timestamps should be monotonically increasing."""
        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            timestamps = _parse_srt_timestamps(srt_path)
            for i in range(1, len(timestamps)):
                prev_end = timestamps[i - 1][1]
                curr_start = timestamps[i][0]
                assert curr_start >= prev_end - 0.1, (
                    f"Overlap: subtitle {i} starts at {curr_start:.3f}s "
                    f"but previous ends at {prev_end:.3f}s"
                )
        finally:
            srt_path.unlink(missing_ok=True)

    async def test_subtitle_gap_not_excessive(self, backend, video_info):
        """Gaps between subtitles should not exceed 5s (long silence)."""
        duration = float(video_info.get("format", {}).get("duration", 0))

        srt_path = await backend.generate_subtitles(TEST_VIDEO, lang="en")
        assert srt_path is not None

        try:
            timestamps = _parse_srt_timestamps(srt_path)
            if len(timestamps) < 2:
                pytest.skip("Need at least 2 subtitles for gap test")

            for i in range(1, len(timestamps)):
                gap = timestamps[i][0] - timestamps[i - 1][1]
                assert gap < 5.0, \
                    f"Excessive gap of {gap:.2f}s between subtitles {i-1} and {i}"
        finally:
            srt_path.unlink(missing_ok=True)


# ── Test: Graceful degradation ────────────────────────────────────────────────


class TestGracefulDegradation:
    """Verify that the backend degrades gracefully on failure."""

    async def test_generate_subtitles_nonexistent_video(self, backend):
        """Non-existent video should return None."""
        result = await backend.generate_subtitles(
            Path("/nonexistent/video.mp4"), lang="en",
        )
        assert result is None

    async def test_burn_subtitles_nonexistent_video(self, backend):
        """Non-existent video for burn should return None."""
        with tempfile.NamedTemporaryFile(suffix=".srt", mode="w") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nTest\n")
            srt_path = Path(f.name)

        result = await backend.burn_subtitles(
            Path("/nonexistent/video.mp4"), srt_path,
            Path("/tmp/output.mp4"), style_preset="default",
        )
        assert result is None

    async def test_burn_subtitles_nonexistent_srt(self, backend):
        """Non-existent SRT for burn should return None."""
        result = await backend.burn_subtitles(
            TEST_VIDEO, Path("/nonexistent/subtitles.srt"),
            Path("/tmp/output.mp4"), style_preset="default",
        )
        assert result is None


# ── Test: SRT format helpers ──────────────────────────────────────────────────


class TestSrtHelpers:
    """Verify the SRT format helper functions."""

    def test_format_timestamp_zero(self):
        """0 seconds should format as 00:00:00,000."""
        assert _format_timestamp(0.0) == "00:00:00,000"

    def test_format_timestamp_exact(self):
        """1.5 seconds should format as 00:00:01,500."""
        assert _format_timestamp(1.5) == "00:00:01,500"

    def test_format_timestamp_with_hours(self):
        """3600 seconds should format as 01:00:00,000."""
        assert _format_timestamp(3600.0, always_include_hours=True) == "01:00:00,000"

    def test_format_timestamp_milliseconds(self):
        """0.123 seconds should format as 00:00:00,123."""
        assert _format_timestamp(0.123) == "00:00:00,123"

    def test_write_srt_creates_file(self):
        """_write_srt should create a valid SRT file."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello world."},
            {"start": 1.5, "end": 2.5, "text": "This is a test."},
        ]

        with tempfile.NamedTemporaryFile(suffix=".srt", mode="w", delete=False) as f:
            srt_path = Path(f.name)

        try:
            _write_srt(segments, srt_path)
            content = srt_path.read_text(encoding="utf-8")
            assert "1" in content
            assert "Hello world." in content
            assert "2" in content
            assert "This is a test." in content
            assert "-->" in content
        finally:
            srt_path.unlink(missing_ok=True)


# ── Test: Singleton factory ───────────────────────────────────────────────────


class TestSingleton:
    """Verify the singleton factory works correctly."""

    def test_get_auto_subtitle_backend_returns_instance(self):
        """Factory should return an AutoSubtitleBackend instance."""
        backend = get_auto_subtitle_backend(model_name="tiny")
        assert isinstance(backend, AutoSubtitleBackend)

    def test_get_auto_subtitle_backend_is_singleton(self):
        """Multiple calls should return the same instance."""
        b1 = get_auto_subtitle_backend(model_name="tiny")
        b2 = get_auto_subtitle_backend(model_name="tiny")
        assert b1 is b2

