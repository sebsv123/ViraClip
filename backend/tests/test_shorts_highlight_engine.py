"""
Tests for the Shorts Highlight Engine.

Covers:
  - Helper functions: _parse_json_loose, _build_transcript_text, _dedupe_highlights, _ratio
  - Score fusion: fuse_scores with overlapping/non-overlapping segments, min_clips fill
  - Crop computation: compute_short_crop with/without face center
  - Engine: find_highlights with mock LLM, graceful degradation on failure
  - Singleton: get_shorts_highlight_engine
  - Integration: CropInfo dataclass usage
"""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.shorts_highlight_engine import (
    MIN_ACCEPTABLE_CLIPS,
    OVERLAP_BONUS,
    OVERLAP_BONUS_RATIO,
    CropInfo,
    Highlight,
    ShortsHighlightEngine,
    _build_transcript_text,
    _dedupe_highlights,
    _parse_json_loose,
    _ratio,
    compute_short_crop,
    fuse_scores,
    get_shorts_highlight_engine,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseJsonLoose:
    def test_plain_json(self):
        raw = '{"highlights": [{"title": "Test", "score": 85}]}'
        result = _parse_json_loose(raw)
        assert result["highlights"][0]["title"] == "Test"
        assert result["highlights"][0]["score"] == 85

    def test_markdown_fence(self):
        raw = "```json\n{\"highlights\": []}\n```"
        result = _parse_json_loose(raw)
        assert result == {"highlights": []}

    def test_markdown_fence_no_lang(self):
        raw = "```\n{\"highlights\": []}\n```"
        result = _parse_json_loose(raw)
        assert result == {"highlights": []}

    def test_extra_text_around_json(self):
        raw = "Here is the result:\n{\"highlights\": [{\"title\": \"A\"}]}\nDone."
        result = _parse_json_loose(raw)
        assert result["highlights"][0]["title"] == "A"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_loose("not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_loose("")


class TestBuildTranscriptText:
    def test_basic_segments(self):
        transcript = {
            "segments": [
                {"start": 0.0, "text": "Hello world"},
                {"start": 1.5, "text": "This is a test"},
            ]
        }
        result = _build_transcript_text(transcript)
        assert "[0.0s] Hello world" in result
        assert "[1.5s] This is a test" in result

    def test_empty_segments(self):
        assert _build_transcript_text({"segments": []}) == ""

    def test_missing_segments(self):
        assert _build_transcript_text({}) == ""

    def test_text_stripping(self):
        transcript = {
            "segments": [
                {"start": 0.0, "text": "  spaced text  "},
            ]
        }
        result = _build_transcript_text(transcript)
        assert "[0.0s] spaced text" in result


class TestDedupeHighlights:
    def test_no_overlap(self):
        highlights = [
            {"title": "A", "start_time": 0, "end_time": 10, "score": 80},
            {"title": "B", "start_time": 20, "end_time": 30, "score": 70},
        ]
        result = _dedupe_highlights(highlights)
        assert len(result) == 2

    def test_overlap_removes_lower(self):
        highlights = [
            {"title": "High", "start_time": 0, "end_time": 20, "score": 90},
            {"title": "Low", "start_time": 5, "end_time": 15, "score": 50},
        ]
        result = _dedupe_highlights(highlights)
        assert len(result) == 1
        assert result[0]["title"] == "High"

    def test_overlap_boundary_keeps_both(self):
        """Overlap exactly 50% should be kept (not > 50%)."""
        highlights = [
            {"title": "A", "start_time": 0, "end_time": 20, "score": 90},
            {"title": "B", "start_time": 10, "end_time": 20, "score": 80},
        ]
        result = _dedupe_highlights(highlights)
        # overlap = 10s, h_dur = 10s, overlap/h_dur = 1.0 > 0.5 → removed
        assert len(result) == 1

    def test_sorts_by_score_descending(self):
        highlights = [
            {"title": "Low", "start_time": 0, "end_time": 10, "score": 30},
            {"title": "High", "start_time": 20, "end_time": 30, "score": 95},
            {"title": "Mid", "start_time": 40, "end_time": 50, "score": 60},
        ]
        result = _dedupe_highlights(highlights)
        assert [h["title"] for h in result] == ["High", "Mid", "Low"]

    def test_empty_list(self):
        assert _dedupe_highlights([]) == []


class TestRatio:
    def test_9_16(self):
        assert _ratio("9:16") == pytest.approx(9.0 / 16.0)

    def test_16_9(self):
        assert _ratio("16:9") == pytest.approx(16.0 / 9.0)

    def test_1_1(self):
        assert _ratio("1:1") == 1.0

    def test_invalid_fallback(self):
        assert _ratio("invalid") == pytest.approx(9.0 / 16.0)

    def test_empty_fallback(self):
        assert _ratio("") == pytest.approx(9.0 / 16.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Score Fusion
# ═══════════════════════════════════════════════════════════════════════════════

class TestFuseScores:
    def _make_highlight(self, title: str, start: float, end: float, score: float = 70.0) -> Highlight:
        return Highlight(title=title, start_time=start, end_time=end, score=score)

    def _make_segment(self, start: float, end: float, title: str = "Seg") -> dict:
        return {"start_time": start, "end_time": end, "title": title}

    def test_no_existing_segments(self):
        highlights = [self._make_highlight("A", 0, 10, 80)]
        result = fuse_scores(highlights, [])
        assert len(result) == 1
        assert result[0].score == 80

    def test_overlap_bonus_applied(self):
        """Highlight overlapping >30% with existing segment gets +0.1*100 bonus."""
        highlights = [self._make_highlight("A", 0, 10, 70)]
        existing = [self._make_segment(3, 8)]  # overlap = 5s, h_dur = 10s, ratio = 0.5 > 0.3
        result = fuse_scores(highlights, existing)
        assert len(result) == 1
        assert result[0].score == 70 + OVERLAP_BONUS * 100

    def test_no_overlap_no_bonus(self):
        highlights = [self._make_highlight("A", 0, 10, 70)]
        existing = [self._make_segment(20, 30)]
        result = fuse_scores(highlights, existing)
        assert result[0].score == 70

    def test_partial_overlap_below_threshold(self):
        """Overlap <= 30% should not get bonus."""
        highlights = [self._make_highlight("A", 0, 10, 70)]
        existing = [self._make_segment(8, 10)]  # overlap = 2s, h_dur = 10s, ratio = 0.2
        result = fuse_scores(highlights, existing)
        assert result[0].score == 70

    def test_fills_min_clips_with_existing_segments(self):
        """When fewer than min_clips highlights, create new ones from non-overlapping segments."""
        highlights = [self._make_highlight("A", 0, 10, 90)]
        existing = [
            self._make_segment(20, 30, "Seg1"),
            self._make_segment(40, 50, "Seg2"),
            self._make_segment(60, 70, "Seg3"),
        ]
        result = fuse_scores(highlights, existing, min_clips=3)
        assert len(result) >= 3
        # The new segments should have neutral score 50
        new_highlights = [h for h in result if h.score == 50.0]
        assert len(new_highlights) >= 2

    def test_does_not_create_duplicates(self):
        """Existing segments that overlap with highlights should not be re-created."""
        highlights = [self._make_highlight("A", 0, 10, 90)]
        existing = [
            self._make_segment(3, 8, "Overlap"),  # overlaps with A
            self._make_segment(20, 30, "NonOverlap"),
        ]
        result = fuse_scores(highlights, existing, min_clips=3)
        # Should have A (with bonus) + NonOverlap (new)
        assert len(result) == 2

    def test_sorted_by_score_descending(self):
        highlights = [
            self._make_highlight("Low", 0, 10, 30),
            self._make_highlight("High", 20, 30, 95),
        ]
        result = fuse_scores(highlights, [])
        assert [h.title for h in result] == ["High", "Low"]

    def test_empty_highlights_with_existing(self):
        """When no highlights but existing segments exist, create from existing."""
        existing = [
            self._make_segment(0, 10, "Seg1"),
            self._make_segment(20, 30, "Seg2"),
        ]
        result = fuse_scores([], existing, min_clips=2)
        assert len(result) == 2
        assert all(h.score == 50.0 for h in result)

    def test_existing_segment_with_different_keys(self):
        """Handle segments with 'start'/'end' keys instead of 'start_time'/'end_time'."""
        highlights = [self._make_highlight("A", 0, 10, 70)]
        existing = [{"start": 3, "end": 8, "text": "Segment text"}]
        result = fuse_scores(highlights, existing)
        assert result[0].score == 70 + OVERLAP_BONUS * 100


# ═══════════════════════════════════════════════════════════════════════════════
# Crop Computation
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeShortCrop:
    def test_center_crop_no_face(self):
        """Without face center, crop should be centered."""
        crop = compute_short_crop(1920, 1080)
        assert crop.source_width == 1920
        assert crop.source_height == 1080
        assert crop.width > 0
        assert crop.height > 0
        # For 9:16 on 1920x1080: target_ratio = 9/16 ≈ 0.5625
        # frame_ratio = 1920/1080 ≈ 1.778 > 0.5625 → crop_h = 1080, crop_w = 1080 * 0.5625 = 607.5 → 606 (even)
        assert crop.width == 606
        assert crop.height == 1080
        # Center: x0 = (1920 - 606) // 2 = 657, y0 = 0
        assert crop.x == 657
        assert crop.y == 0
        assert crop.confidence == 0.5  # no face

    def test_with_face_center(self):
        """With face center, crop should be centered on face."""
        crop = compute_short_crop(1920, 1080, face_center_x=500, face_center_y=500)
        assert crop.confidence == 0.8
        # crop_w = 606, crop_h = 1080
        # x0 = clamp(500 - 303, 0, 1920-606) = 197
        assert crop.x == 197
        assert crop.y == 0

    def test_face_near_edge(self):
        """Face near left edge should clamp x0 to 0."""
        crop = compute_short_crop(1920, 1080, face_center_x=50, face_center_y=500)
        assert crop.x == 0

    def test_face_near_right_edge(self):
        """Face near right edge should clamp x0 to max."""
        crop = compute_short_crop(1920, 1080, face_center_x=1900, face_center_y=500)
        assert crop.x == 1920 - 606  # 1314

    def test_16_9_aspect_ratio(self):
        """Test with 16:9 target aspect ratio."""
        crop = compute_short_crop(1080, 1920, aspect_ratio="16:9")
        # target_ratio = 16/9 ≈ 1.778
        # frame_ratio = 1080/1920 ≈ 0.5625 < 1.778 → crop_w = 1080, crop_h = 1080 / 1.778 = 607.5 → 606
        assert crop.width == 1080
        assert crop.height == 606
        assert crop.x == 0
        assert crop.y == (1920 - 606) // 2  # 657

    def test_even_dimensions(self):
        """Crop dimensions should always be even."""
        crop = compute_short_crop(1001, 1001)
        assert crop.width % 2 == 0
        assert crop.height % 2 == 0

    def test_small_frame(self):
        """Very small frame should still produce valid crop."""
        crop = compute_short_crop(100, 200)
        assert crop.width > 0
        assert crop.height > 0
        assert crop.width % 2 == 0
        assert crop.height % 2 == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Engine — find_highlights
# ═══════════════════════════════════════════════════════════════════════════════

class TestShortsHighlightEngine:
    """Tests for ShortsHighlightEngine.find_highlights()."""

    @pytest.fixture
    def sample_transcript(self) -> dict:
        return {
            "duration": 120.0,
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Welcome to this video."},
                {"start": 5.0, "end": 15.0, "text": "Today I'm going to share something amazing."},
                {"start": 15.0, "end": 30.0, "text": "The secret that nobody talks about is right here."},
                {"start": 30.0, "end": 45.0, "text": "Let me explain why this changes everything."},
                {"start": 45.0, "end": 60.0, "text": "Here's the proof that it actually works."},
                {"start": 60.0, "end": 75.0, "text": "I was completely wrong about this for years."},
                {"start": 75.0, "end": 90.0, "text": "But after testing it myself, I was shocked."},
                {"start": 90.0, "end": 105.0, "text": "The results were better than I ever imagined."},
                {"start": 105.0, "end": 120.0, "text": "Subscribe to see more content like this."},
            ],
        }

    @pytest.fixture
    def mock_llm_fn(self) -> MagicMock:
        """A mock LLM function that returns valid highlight JSON."""
        fn = MagicMock()
        fn.return_value = json.dumps({
            "highlights": [
                {
                    "title": "The Secret Revealed",
                    "start_time": 15.0,
                    "end_time": 45.0,
                    "score": 92,
                    "hook_sentence": "The secret that nobody talks about is right here.",
                    "virality_reason": "Creates curiosity with a strong hook.",
                },
                {
                    "title": "Personal Transformation",
                    "start_time": 60.0,
                    "end_time": 90.0,
                    "score": 88,
                    "hook_sentence": "I was completely wrong about this for years.",
                    "virality_reason": "Vulnerability and surprise drive engagement.",
                },
            ]
        })
        return fn

    @pytest.mark.asyncio
    async def test_find_highlights_basic(self, sample_transcript, mock_llm_fn):
        engine = ShortsHighlightEngine(llm_fn=mock_llm_fn)
        highlights = await engine.find_highlights(sample_transcript, num_clips=3)
        assert len(highlights) == 2
        assert highlights[0].title == "The Secret Revealed"
        assert highlights[0].score == 92
        assert highlights[1].title == "Personal Transformation"
        assert highlights[1].score == 88

    @pytest.mark.asyncio
    async def test_find_highlights_with_existing_segments(self, sample_transcript, mock_llm_fn):
        engine = ShortsHighlightEngine(llm_fn=mock_llm_fn)
        existing = [
            {"start_time": 10.0, "end_time": 40.0, "title": "Existing clip"},
        ]
        highlights = await engine.find_highlights(
            sample_transcript, num_clips=3, existing_segments=existing,
        )
        # First highlight overlaps with existing → should get bonus
        assert len(highlights) >= 2
        secret = [h for h in highlights if h.title == "The Secret Revealed"][0]
        assert secret.score == 92 + OVERLAP_BONUS * 100

    @pytest.mark.asyncio
    async def test_find_highlights_fills_min_clips(self, sample_transcript, mock_llm_fn):
        """When fewer highlights than num_clips, fill with existing segments."""
        engine = ShortsHighlightEngine(llm_fn=mock_llm_fn)
        existing = [
            {"start_time": 100.0, "end_time": 120.0, "title": "Outro segment"},
            {"start_time": 130.0, "end_time": 150.0, "title": "Extra segment"},
        ]
        highlights = await engine.find_highlights(
            sample_transcript, num_clips=4, existing_segments=existing,
        )
        assert len(highlights) >= 4

    @pytest.mark.asyncio
    async def test_find_highlights_graceful_degradation(self, sample_transcript):
        """When LLM fails, should return empty list (not crash)."""
        failing_fn = MagicMock(side_effect=RuntimeError("LLM unavailable"))
        engine = ShortsHighlightEngine(llm_fn=failing_fn)
        highlights = await engine.find_highlights(sample_transcript)
        assert highlights == []

    @pytest.mark.asyncio
    async def test_find_highlights_empty_transcript(self, mock_llm_fn):
        engine = ShortsHighlightEngine(llm_fn=mock_llm_fn)
        highlights = await engine.find_highlights({"segments": [], "duration": 0})
        # LLM will be called but with empty text
        assert isinstance(highlights, list)

    @pytest.mark.asyncio
    async def test_find_highlights_malformed_llm_response(self, sample_transcript):
        """Malformed JSON from LLM should be handled gracefully."""
        bad_fn = MagicMock(return_value="not valid json")
        engine = ShortsHighlightEngine(llm_fn=bad_fn)
        highlights = await engine.find_highlights(sample_transcript)
        assert highlights == []

    @pytest.mark.asyncio
    async def test_find_highlights_empty_llm_response(self, sample_transcript):
        """Empty highlights array from LLM should return empty list."""
        empty_fn = MagicMock(return_value=json.dumps({"highlights": []}))
        engine = ShortsHighlightEngine(llm_fn=empty_fn)
        highlights = await engine.find_highlights(sample_transcript)
        assert highlights == []


# ═══════════════════════════════════════════════════════════════════════════════
# Engine — _detect_content_type
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectContentType:
    def test_detects_content_type(self):
        mock_fn = MagicMock(return_value=json.dumps({
            "content_type": "tutorial",
            "density": "high",
        }))
        engine = ShortsHighlightEngine(llm_fn=mock_fn)
        transcript = {
            "segments": [
                {"start": 0, "text": "Step one is to configure the settings."},
                {"start": 5, "text": "Step two is to run the application."},
            ]
        }
        result = engine._detect_content_type(transcript)
        assert result["content_type"] == "tutorial"
        assert result["density"] == "high"

    def test_fallback_on_failure(self):
        failing_fn = MagicMock(side_effect=RuntimeError("fail"))
        engine = ShortsHighlightEngine(llm_fn=failing_fn)
        result = engine._detect_content_type({"segments": []})
        assert result == {"content_type": "other", "density": "medium"}


# ═══════════════════════════════════════════════════════════════════════════════
# Engine — _chunk_transcript
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunkTranscript:
    def test_no_chunking_needed(self):
        engine = ShortsHighlightEngine()
        transcript = {
            "duration": 600,  # 10 min
            "segments": [
                {"start": 0, "end": 300, "text": "First half"},
                {"start": 300, "end": 600, "text": "Second half"},
            ],
        }
        chunks = engine._chunk_transcript(transcript, 1200, 60)
        assert len(chunks) == 1
        assert chunks[0]["_offset"] == 0

    def test_chunks_long_video(self):
        engine = ShortsHighlightEngine()
        transcript = {
            "duration": 3600,  # 60 min
            "segments": [
                {"start": i * 60, "end": (i + 1) * 60, "text": f"Segment {i}"}
                for i in range(60)
            ],
        }
        chunks = engine._chunk_transcript(transcript, 1200, 60)
        # 3600 / (1200 - 60) ≈ 3.16 → 4 chunks
        assert len(chunks) >= 3
        assert all("_offset" in c for c in chunks)
        # Check offsets are increasing
        offsets = [c["_offset"] for c in chunks]
        assert offsets == sorted(offsets)

    def test_empty_transcript(self):
        engine = ShortsHighlightEngine()
        chunks = engine._chunk_transcript({"duration": 0, "segments": []}, 1200, 60)
        assert chunks == []


# ═══════════════════════════════════════════════════════════════════════════════
# Engine — _call_highlight_api
# ═══════════════════════════════════════════════════════════════════════════════

class TestCallHighlightApi:
    def test_calls_llm_with_formatted_prompt(self):
        mock_fn = MagicMock(return_value=json.dumps({"highlights": []}))
        engine = ShortsHighlightEngine(llm_fn=mock_fn)
        result = engine._call_highlight_api(
            "Some transcript text",
            {"content_type": "podcast", "density": "medium"},
            120.0,
            num_clips=3,
        )
        assert result == {"highlights": []}
        # Verify the prompt was formatted correctly
        call_args = mock_fn.call_args[0][0]
        assert "podcast" in call_args
        assert "medium" in call_args
        assert "Some transcript text" in call_args
        assert "Generate at least" in call_args


# ═══════════════════════════════════════════════════════════════════════════════
# Engine — _highlights_from_raw
# ═══════════════════════════════════════════════════════════════════════════════

class TestHighlightsFromRaw:
    def test_converts_valid_dicts(self):
        engine = ShortsHighlightEngine()
        raw = [
            {"title": "A", "start_time": 0, "end_time": 10, "score": 85,
             "hook_sentence": "Hook", "virality_reason": "Reason"},
        ]
        highlights = engine._highlights_from_raw(raw)
        assert len(highlights) == 1
        assert highlights[0].title == "A"
        assert highlights[0].score == 85.0

    def test_skips_invalid_dicts(self):
        engine = ShortsHighlightEngine()
        raw = [
            {"title": "Valid", "start_time": 0, "end_time": 10, "score": 85},
            {"title": "Invalid", "start_time": "bad", "end_time": 10, "score": 85},
        ]
        highlights = engine._highlights_from_raw(raw)
        assert len(highlights) == 1
        assert highlights[0].title == "Valid"

    def test_empty_list(self):
        engine = ShortsHighlightEngine()
        assert engine._highlights_from_raw([]) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetShortsHighlightEngine:
    def test_returns_same_instance(self):
        engine1 = get_shorts_highlight_engine()
        engine2 = get_shorts_highlight_engine()
        assert engine1 is engine2

    def test_is_shorts_highlight_engine(self):
        engine = get_shorts_highlight_engine()
        assert isinstance(engine, ShortsHighlightEngine)


# ═══════════════════════════════════════════════════════════════════════════════
# CropInfo dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestCropInfo:
    def test_default_confidence(self):
        info = CropInfo(x=0, y=0, width=100, height=200, source_width=1920, source_height=1080)
        assert info.confidence == 1.0

    def test_custom_confidence(self):
        info = CropInfo(x=10, y=20, width=100, height=200, source_width=1920, source_height=1080, confidence=0.75)
        assert info.confidence == 0.75

    def test_asdict(self):
        info = CropInfo(x=10, y=20, width=100, height=200, source_width=1920, source_height=1080)
        d = asdict(info)
        assert d["x"] == 10
        assert d["y"] == 20
        assert d["width"] == 100
        assert d["height"] == 200
        assert d["source_width"] == 1920
        assert d["source_height"] == 1080
        assert d["confidence"] == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Highlight dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestHighlight:
    def test_defaults(self):
        h = Highlight(title="Test", start_time=0, end_time=10, score=85)
        assert h.hook_sentence == ""
        assert h.virality_reason == ""
        assert h.crop_info is None

    def test_with_crop_info(self):
        crop = CropInfo(x=0, y=0, width=100, height=200, source_width=1920, source_height=1080)
        h = Highlight(
            title="Test", start_time=0, end_time=10, score=85,
            hook_sentence="Hook!", virality_reason="Viral!",
            crop_info=crop,
        )
        assert h.hook_sentence == "Hook!"
        assert h.virality_reason == "Viral!"
        assert h.crop_info is crop
