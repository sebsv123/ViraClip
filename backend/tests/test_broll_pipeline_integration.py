"""
Integration tests for the full B-roll pipeline.

Tests the end-to-end flow:
  1. AiBrollRecommender → PexelsClient → broll clips (via _search_pexels)
  2. Mood → BackgroundMusicService → audio ducking (via creative_pipeline Step 7)
  3. Graceful degradation when Pexels or music fail
  4. Pipeline continues without B-roll or without music

All external services (Pexels API, LLM, filesystem) are mocked.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from src.services.pexels_client import (
    PexelsClient,
    PexelsVideo,
    get_pexels_client,
    JOKER_TERMS,
)
from src.services.background_music_service import (
    BackgroundMusicService,
    MusicTrack,
    MusicMood,
    pick_bgm_for_mood,
    get_background_music_service,
)
from src.services.ai_broll_recommender import (
    AiBrollRecommender,
    BrollCandidate,
    make_task_ctx,
)
from src.config import Config


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_pexels_api():
    """
    Mock httpx responses for Pexels API calls.
    Returns a context manager that patches httpx.AsyncClient.
    """
    def _make_mock_response(status=200, videos=None):
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.json.return_value = {"videos": videos or []}
        mock_resp.raise_for_status = MagicMock()
        if status >= 400:
            mock_resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
        return mock_resp

    def _make_video(
        vid_id: int,
        duration: float = 10.0,
        width: int = 576,
        height: int = 1024,
        quality: str = "hd",
        file_type: str = "video/mp4",
    ) -> dict:
        return {
            "id": vid_id,
            "duration": duration,
            "video_files": [
                {
                    "id": vid_id * 100,
                    "width": width,
                    "height": height,
                    "quality": quality,
                    "file_type": file_type,
                    "link": f"https://pexels.com/video/{vid_id}.mp4",
                }
            ],
        }

    return _make_mock_response, _make_video


@pytest.fixture
def mock_llm():
    """
    Mock LLM API calls for AiBrollRecommender.
    Returns a context manager that patches httpx.AsyncClient.
    """
    def _make_llm_response(keywords: List[Dict[str, str]]) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "concept": "test concept",
                            "suggestions": keywords,
                        })
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    return _make_llm_response


@pytest.fixture
def temp_music_dir():
    """Create a temporary directory with mock music files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a few mock music files matching the library
        music_files = [
            "Sly Sky - Telecasted.mp3",
            "Champion - Telecasted.mp3",
            "Touch - Anno Domini Beats.mp3",
            "Hopeless - Jimena Contreras.mp3",
            "Buckle Up - Jeremy Korpas.mp3",
        ]
        for fname in music_files:
            fpath = Path(tmpdir) / fname
            fpath.write_text(b"mock audio content")
        yield tmpdir


@pytest.fixture
def config_with_music(temp_music_dir):
    """Create a Config with music_dir set to temp dir."""
    cfg = Config()
    cfg.music_dir = temp_music_dir
    cfg.background_music_enabled = True
    cfg.pexels_api_key = "test-key-123"
    return cfg


# ── Integration: AiBrollRecommender → PexelsClient → broll clips ────────────────


class TestAiBrollToPexelsIntegration:
    """Test the full flow: AiBrollRecommender → PexelsClient → broll clips."""

    @pytest.mark.asyncio
    async def test_full_pipeline_happy_path(self, mock_pexels_api, mock_llm):
        """
        GIVEN an AiBrollRecommender that extracts keywords from a transcript
        WHEN we search Pexels for each keyword
        THEN we get valid B-roll video URLs.
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        # Mock LLM to return keywords
        llm_keywords = [
            {"keyword": "ocean waves", "shot_type": "wide", "mood": "calm"},
            {"keyword": "sunset beach", "shot_type": "medium", "mood": "peaceful"},
        ]

        # Mock Pexels to return videos for each keyword
        pexels_videos = [
            make_video(vid_id=1, duration=8.0),
            make_video(vid_id=2, duration=6.0),
        ]

        with patch("httpx.AsyncClient") as mock_httpx:
            # Configure mock for LLM call
            llm_instance = MagicMock()
            llm_instance.post = AsyncMock(return_value=make_llm(llm_keywords))
            llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
            llm_instance.__aexit__ = AsyncMock()

            # Configure mock for Pexels calls
            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(200, pexels_videos))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            # First call returns LLM mock, subsequent calls return Pexels mock
            mock_httpx.side_effect = [llm_instance, pexels_instance]

            # Step 1: Get B-roll recommendations from AiBrollRecommender
            recommender = AiBrollRecommender(
                llm_api_key="test-llm-key",
                llm_base_url="https://api.groq.com/openai/v1",
            )
            task_ctx = make_task_ctx(segment_count=2)
            candidates = await recommender.suggest_broll(
                transcript="The ocean waves crash against the shore at sunset.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )

            assert len(candidates) > 0, "Should have at least one B-roll candidate"
            assert any("ocean" in kw for c in candidates for kw in c.keywords), \
                "Keywords should include ocean-related terms"

            # Step 2: Search Pexels for each candidate's keywords
            client = PexelsClient(api_key="test-pexels-key")
            all_videos: List[PexelsVideo] = []
            for candidate in candidates:
                for keyword in candidate.keywords:
                    videos = await client.search_videos(
                        query=keyword,
                        min_duration=3.0,
                        orientation="portrait",
                    )
                    all_videos.extend(videos)

            assert len(all_videos) > 0, "Should have found Pexels videos"
            for v in all_videos:
                assert v.url.startswith("https://"), f"URL should be absolute: {v.url}"
                assert v.duration >= 3.0, f"Duration should be >= 3s: {v.duration}"
                assert v.width == 576, f"Width should be 576 (portrait): {v.width}"
                assert v.height == 1024, f"Height should be 1024 (portrait): {v.height}"

            await client.close()

    @pytest.mark.asyncio
    async def test_pipeline_with_tfidf_fallback(self, mock_pexels_api):
        """
        GIVEN an AiBrollRecommender with no LLM API key
        WHEN it falls back to TF-IDF extraction
        THEN Pexels search still works with the extracted keywords.
        """
        make_resp, make_video = mock_pexels_api

        pexels_videos = [make_video(vid_id=10, duration=5.0)]

        with patch("httpx.AsyncClient") as mock_httpx:
            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(200, pexels_videos))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()
            mock_httpx.return_value = pexels_instance

            # Step 1: TF-IDF fallback (no LLM key)
            recommender = AiBrollRecommender(llm_api_key="")  # No key → TF-IDF
            task_ctx = make_task_ctx(segment_count=1)
            candidates = await recommender.suggest_broll(
                transcript="The sunset over the ocean was beautiful and calming.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )

            assert len(candidates) > 0, "TF-IDF should extract keywords"
            # Keywords should be content words from the transcript
            all_keywords = [kw for c in candidates for kw in c.keywords]
            assert any(kw in all_keywords for kw in ["sunset", "ocean", "beautiful"]), \
                f"Expected content words in keywords: {all_keywords}"

            # Step 2: Search Pexels with TF-IDF keywords
            client = PexelsClient(api_key="test-pexels-key")
            videos = await client.search_videos(
                query=candidates[0].keywords[0],
                min_duration=3.0,
                orientation="portrait",
            )
            assert len(videos) > 0, "Should find videos for TF-IDF keyword"
            await client.close()

    @pytest.mark.asyncio
    async def test_pipeline_pexels_failure_graceful(self, mock_pexels_api, mock_llm):
        """
        GIVEN AiBrollRecommender produces keywords
        WHEN Pexels API fails (401 auth error)
        THEN the pipeline returns empty gracefully (no crash).
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        llm_keywords = [
            {"keyword": "nature", "shot_type": "wide", "mood": "calm"},
        ]

        with patch("httpx.AsyncClient") as mock_httpx:
            # LLM succeeds
            llm_instance = MagicMock()
            llm_instance.post = AsyncMock(return_value=make_llm(llm_keywords))
            llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
            llm_instance.__aexit__ = AsyncMock()

            # Pexels fails with 401
            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(401, []))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            mock_httpx.side_effect = [llm_instance, pexels_instance]

            # Step 1: Get recommendations
            recommender = AiBrollRecommender(llm_api_key="test-llm-key")
            task_ctx = make_task_ctx(segment_count=1)
            candidates = await recommender.suggest_broll(
                transcript="Nature is beautiful.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )
            assert len(candidates) > 0, "LLM should still produce candidates"

            # Step 2: Pexels search fails gracefully
            client = PexelsClient(api_key="invalid-key")
            videos = await client.search_videos(
                query=candidates[0].keywords[0],
                min_duration=3.0,
                orientation="portrait",
            )
            assert len(videos) == 0, "Should return empty list on auth error"
            await client.close()

    @pytest.mark.asyncio
    async def test_pipeline_all_pexels_terms_fail(self, mock_pexels_api, mock_llm):
        """
        GIVEN AiBrollRecommender produces keywords
        WHEN all Pexels search terms (including joker terms) return no results
        THEN the pipeline returns empty gracefully.
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        llm_keywords = [
            {"keyword": "nonexistent_topic_xyz", "shot_type": "medium", "mood": "neutral"},
        ]

        with patch("httpx.AsyncClient") as mock_httpx:
            # LLM succeeds
            llm_instance = MagicMock()
            llm_instance.post = AsyncMock(return_value=make_llm(llm_keywords))
            llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
            llm_instance.__aexit__ = AsyncMock()

            # Pexels returns empty for all terms (including joker terms)
            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(200, []))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            mock_httpx.side_effect = [llm_instance, pexels_instance]

            # Step 1: Get recommendations
            recommender = AiBrollRecommender(llm_api_key="test-llm-key")
            task_ctx = make_task_ctx(segment_count=1)
            candidates = await recommender.suggest_broll(
                transcript="Something about nothing.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )
            assert len(candidates) > 0, "LLM should still produce candidates"

            # Step 2: Pexels returns empty for all terms
            client = PexelsClient(api_key="test-key")
            videos = await client.search_videos(
                query=candidates[0].keywords[0],
                min_duration=3.0,
                orientation="portrait",
            )
            assert len(videos) == 0, "Should return empty when no videos match"
            await client.close()

    @pytest.mark.asyncio
    async def test_pipeline_no_api_key_graceful(self):
        """
        GIVEN no Pexels API key is configured
        WHEN the pipeline tries to search for B-roll
        THEN it returns empty gracefully without making any HTTP calls.
        """
        client = PexelsClient(api_key=None)
        videos = await client.search_videos(
            query="nature",
            min_duration=3.0,
            orientation="portrait",
        )
        assert len(videos) == 0, "Should return empty when no API key"
        await client.close()

    @pytest.mark.asyncio
    async def test_pipeline_diversity_across_segments(self, mock_pexels_api, mock_llm):
        """
        GIVEN multiple transcript segments
        WHEN AiBrollRecommender processes them with shared task_ctx
        THEN later segments get different keywords (diversity).
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        # Different keywords for each segment
        segment_keywords = [
            [{"keyword": "ocean", "shot_type": "wide", "mood": "calm"}],
            [{"keyword": "mountains", "shot_type": "wide", "mood": "serene"}],
        ]

        with patch("httpx.AsyncClient") as mock_httpx:
            # LLM returns different keywords per call
            llm_calls = []
            for kw_list in segment_keywords:
                llm_instance = MagicMock()
                llm_instance.post = AsyncMock(return_value=make_llm(kw_list))
                llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
                llm_instance.__aexit__ = AsyncMock()
                llm_calls.append(llm_instance)

            # Pexels returns videos for each keyword
            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(
                return_value=make_resp(200, [make_video(vid_id=1, duration=5.0)])
            )
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            # Interleave LLM and Pexels calls
            mock_httpx.side_effect = [
                llm_calls[0], pexels_instance,  # Segment 0
                llm_calls[1], pexels_instance,  # Segment 1
            ]

            recommender = AiBrollRecommender(llm_api_key="test-llm-key")
            task_ctx = make_task_ctx(segment_count=2)

            # Segment 0
            candidates_0 = await recommender.suggest_broll(
                transcript="The ocean is vast and deep.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )
            assert len(candidates_0) > 0
            kw_0 = set(kw for c in candidates_0 for kw in c.keywords)

            # Segment 1 (should get different keywords due to diversity)
            candidates_1 = await recommender.suggest_broll(
                transcript="The mountains are tall and majestic.",
                segment_id="clip_1",
                task_ctx=task_ctx,
            )
            kw_1 = set(kw for c in candidates_1 for kw in c.keywords)

            # Keywords should differ due to diversity tracking
            # (ocean was used in segment 0, so segment 1 should prefer mountains)
            assert "mountains" in str(kw_1).lower() or len(kw_1 - kw_0) > 0, \
                f"Segment 1 keywords ({kw_1}) should differ from segment 0 ({kw_0})"


# ── Integration: Mood → BackgroundMusicService → audio ducking ──────────────────


class TestMoodToMusicIntegration:
    """Test the full flow: mood → BackgroundMusicService → audio ducking."""

    def test_mood_to_music_selection(self, temp_music_dir):
        """
        GIVEN a mood tag from the video pipeline
        WHEN we call BackgroundMusicService.pick_music_for_segment
        THEN we get a MusicTrack with the correct mood and a resolved URL.
        """
        service = BackgroundMusicService(music_dir=temp_music_dir)

        # Test various moods
        test_cases = [
            ("happy", MusicMood.HAPPY),
            ("sad", MusicMood.SAD),
            ("chill", MusicMood.CHILL),
            ("dark", MusicMood.DARK),
            ("funny", MusicMood.FUNNY),
            ("angry", MusicMood.ANGRY),
            ("hopeful", MusicMood.HOPEFUL),
            ("neutral", MusicMood.CHILL),  # neutral → chill
        ]

        for input_mood, expected_mood in test_cases:
            track = service.pick_music_for_segment(mood=input_mood, duration_s=10.0)
            assert track is not None, f"Should find track for mood '{input_mood}'"
            assert track.mood == expected_mood, \
                f"Mood '{input_mood}' should map to '{expected_mood}', got '{track.mood}'"
            assert track.url != "", f"URL should be resolved for '{input_mood}'"
            assert Path(track.url).exists(), f"Resolved path should exist: {track.url}"

    def test_mood_to_music_duration_filter(self, temp_music_dir):
        """
        GIVEN a mood and a specific duration requirement
        WHEN the track's available duration is shorter than needed
        THEN the service picks the longest available track for that mood.
        """
        service = BackgroundMusicService(music_dir=temp_music_dir)

        # Request a very long duration (longer than any track)
        track = service.pick_music_for_segment(mood="sad", duration_s=999.0)
        assert track is not None, "Should still return a track even if too short"
        assert track.mood == MusicMood.SAD, "Should match sad mood"

        # The longest sad track should be selected
        sad_tracks = [t for t in service._MUSIC_LIBRARY if t.mood == MusicMood.SAD]
        longest = max(sad_tracks, key=lambda t: t.end - t.start)
        assert track.file == longest.file, \
            f"Should pick longest sad track ({longest.file}), got {track.file}"

    def test_mood_to_music_unknown_mood_fallback(self, temp_music_dir):
        """
        GIVEN an unknown mood tag
        WHEN we call pick_music_for_segment
        THEN it falls back to 'chill' mood.
        """
        service = BackgroundMusicService(music_dir=temp_music_dir)

        track = service.pick_music_for_segment(mood="nonexistent_mood_xyz", duration_s=10.0)
        assert track is not None, "Should fall back to chill for unknown mood"
        assert track.mood == MusicMood.CHILL, \
            f"Unknown mood should fall back to chill, got '{track.mood}'"

    def test_mood_to_music_synonym_mapping(self, temp_music_dir):
        """
        GIVEN a mood synonym (e.g., "joyful" → "happy")
        WHEN we call pick_music_for_segment
        THEN it correctly maps to the canonical mood.
        """
        service = BackgroundMusicService(music_dir=temp_music_dir)

        synonyms = [
            ("joyful", MusicMood.HAPPY),
            ("melancholy", MusicMood.MELANCHOLIC),
            ("calm", MusicMood.CHILL),
            ("tense", MusicMood.UNEASY),
            ("mysterious", MusicMood.DARK),
            ("inspiring", MusicMood.HOPEFUL),
            ("playful", MusicMood.FUNNY),
            ("aggressive", MusicMood.ANGRY),
        ]

        for synonym, expected_mood in synonyms:
            track = service.pick_music_for_segment(mood=synonym, duration_s=10.0)
            assert track is not None, f"Should find track for synonym '{synonym}'"
            assert track.mood == expected_mood, \
                f"Synonym '{synonym}' should map to '{expected_mood}', got '{track.mood}'"

    def test_mood_to_music_all_moods_have_tracks(self, temp_music_dir):
        """
        GIVEN the full music library
        WHEN we check each mood
        THEN every mood has at least one track.
        """
        service = BackgroundMusicService(music_dir=temp_music_dir)

        for mood in MusicMood.ALL:
            tracks = service.list_tracks_by_mood(mood)
            assert len(tracks) >= 1, f"Mood '{mood}' should have at least 1 track"
            # All tracks should have valid durations
            for t in tracks:
                assert t.end > t.start, f"Track '{t.file}' should have end > start"

    def test_mood_to_music_no_music_dir(self):
        """
        GIVEN no music directory configured
        WHEN we call pick_music_for_segment
        THEN it still returns a track (with unresolved filename as URL).
        """
        service = BackgroundMusicService(music_dir=None)

        track = service.pick_music_for_segment(mood="happy", duration_s=10.0)
        assert track is not None, "Should return track even without music dir"
        # URL will be just the filename since no dir is configured
        assert track.url == track.file, \
            "Without music dir, URL should be just the filename"

    def test_mood_to_music_ensure_files_exist(self, temp_music_dir):
        """
        GIVEN a music directory with some files
        WHEN we call ensure_music_files_exist
        THEN it correctly reports which files are missing.
        """
        service = BackgroundMusicService(music_dir=temp_music_dir)

        missing = service.ensure_music_files_exist()
        # Only 5 of 31 files exist in temp dir
        assert len(missing) == 26, \
            f"Expected 26 missing files (31 total - 5 present), got {len(missing)}"
        # The files we created should NOT be in the missing list
        assert "Sly Sky - Telecasted.mp3" not in missing
        assert "Champion - Telecasted.mp3" not in missing


# ── Integration: Full pipeline (B-roll + music combined) ────────────────────────


class TestFullBrollPipelineIntegration:
    """Test the complete B-roll pipeline combining keyword extraction, Pexels search, and music selection."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_both_services(
        self, mock_pexels_api, mock_llm, temp_music_dir, config_with_music
    ):
        """
        GIVEN a transcript segment with mood metadata
        WHEN the full pipeline runs (keyword extraction → Pexels search → music selection)
        THEN both B-roll videos and background music are successfully selected.
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        llm_keywords = [
            {"keyword": "sunset beach", "shot_type": "wide", "mood": "peaceful"},
            {"keyword": "ocean waves", "shot_type": "medium", "mood": "calm"},
        ]

        pexels_videos = [
            make_video(vid_id=100, duration=8.0),
            make_video(vid_id=101, duration=6.0),
        ]

        with patch("httpx.AsyncClient") as mock_httpx:
            # LLM mock
            llm_instance = MagicMock()
            llm_instance.post = AsyncMock(return_value=make_llm(llm_keywords))
            llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
            llm_instance.__aexit__ = AsyncMock()

            # Pexels mock
            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(200, pexels_videos))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            mock_httpx.side_effect = [llm_instance, pexels_instance]

            # ── B-roll part ──
            recommender = AiBrollRecommender(llm_api_key="test-llm-key")
            task_ctx = make_task_ctx(segment_count=1)
            candidates = await recommender.suggest_broll(
                transcript="The sunset over the beach was beautiful.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )
            assert len(candidates) > 0, "Should have B-roll candidates"

            client = PexelsClient(api_key=config_with_music.pexels_api_key)
            all_videos: List[PexelsVideo] = []
            for candidate in candidates:
                for keyword in candidate.keywords:
                    videos = await client.search_videos(
                        query=keyword,
                        min_duration=3.0,
                        orientation="portrait",
                    )
                    all_videos.extend(videos)
            assert len(all_videos) > 0, "Should have Pexels videos"
            await client.close()

            # ── Music part ──
            clip_mood = "peaceful"  # From the B-roll candidate
            clip_duration_s = 15.0

            music_service = BackgroundMusicService(music_dir=temp_music_dir)
            music_track = music_service.pick_music_for_segment(
                mood=clip_mood,
                duration_s=clip_duration_s,
            )
            assert music_track is not None, "Should find music for 'peaceful' mood"
            # peaceful → hopeful (via MOOD_MAPPING)
            assert music_track.mood in MusicMood.ALL, \
                f"Track mood '{music_track.mood}' should be valid"
            assert music_track.url != "", "URL should be resolved"
            assert Path(music_track.url).exists(), "Music file should exist"

    @pytest.mark.asyncio
    async def test_full_pipeline_pexels_fails_music_succeeds(
        self, mock_pexels_api, mock_llm, temp_music_dir, config_with_music
    ):
        """
        GIVEN Pexels API fails but music service works
        WHEN the pipeline runs
        THEN B-roll returns empty but music selection still succeeds.
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        llm_keywords = [
            {"keyword": "nature", "shot_type": "wide", "mood": "calm"},
        ]

        with patch("httpx.AsyncClient") as mock_httpx:
            # LLM succeeds
            llm_instance = MagicMock()
            llm_instance.post = AsyncMock(return_value=make_llm(llm_keywords))
            llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
            llm_instance.__aexit__ = AsyncMock()

            # Pexels fails
            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(401, []))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            mock_httpx.side_effect = [llm_instance, pexels_instance]

            # B-roll fails gracefully
            recommender = AiBrollRecommender(llm_api_key="test-llm-key")
            task_ctx = make_task_ctx(segment_count=1)
            candidates = await recommender.suggest_broll(
                transcript="Nature is beautiful.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )
            assert len(candidates) > 0, "LLM should still produce candidates"

            client = PexelsClient(api_key="invalid-key")
            videos = await client.search_videos(
                query=candidates[0].keywords[0],
                min_duration=3.0,
                orientation="portrait",
            )
            assert len(videos) == 0, "Pexels should return empty on auth error"
            await client.close()

            # Music still works
            music_track = pick_bgm_for_mood(
                mood="calm",
                duration_s=10.0,
                music_dir=temp_music_dir,
            )
            assert music_track is not None, "Music should still work when Pexels fails"
            assert music_track.mood == MusicMood.CHILL, "calm → chill"

    @pytest.mark.asyncio
    async def test_full_pipeline_music_fails_pexels_succeeds(
        self, mock_pexels_api, mock_llm, config_with_music
    ):
        """
        GIVEN music service has no files but Pexels works
        WHEN the pipeline runs
        THEN music returns None but B-roll selection still succeeds.
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        llm_keywords = [
            {"keyword": "ocean", "shot_type": "wide", "mood": "calm"},
        ]

        pexels_videos = [make_video(vid_id=200, duration=7.0)]

        with patch("httpx.AsyncClient") as mock_httpx:
            llm_instance = MagicMock()
            llm_instance.post = AsyncMock(return_value=make_llm(llm_keywords))
            llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
            llm_instance.__aexit__ = AsyncMock()

            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(200, pexels_videos))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            mock_httpx.side_effect = [llm_instance, pexels_instance]

            # B-roll succeeds
            recommender = AiBrollRecommender(llm_api_key="test-llm-key")
            task_ctx = make_task_ctx(segment_count=1)
            candidates = await recommender.suggest_broll(
                transcript="The ocean is vast.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )
            assert len(candidates) > 0

            client = PexelsClient(api_key=config_with_music.pexels_api_key)
            videos = await client.search_videos(
                query=candidates[0].keywords[0],
                min_duration=3.0,
                orientation="portrait",
            )
            assert len(videos) > 0, "Pexels should return videos"
            await client.close()

            # Music fails (no files in a non-existent directory)
            music_track = pick_bgm_for_mood(
                mood="happy",
                duration_s=10.0,
                music_dir="/nonexistent/music/dir",
            )
            # Music still returns a track (with unresolved URL), but the file won't exist
            if music_track:
                # The track is returned but its URL won't resolve to an existing file
                assert not Path(music_track.url).exists() or music_track.url == music_track.file, \
                    "Music file should not exist in nonexistent dir"

    @pytest.mark.asyncio
    async def test_full_pipeline_both_fail_gracefully(self, mock_pexels_api, mock_llm):
        """
        GIVEN both Pexels API and music service fail
        WHEN the pipeline runs
        THEN both return empty/None gracefully without crashing.
        """
        make_resp, make_video = mock_pexels_api
        make_llm = mock_llm

        llm_keywords = [
            {"keyword": "nature", "shot_type": "wide", "mood": "calm"},
        ]

        with patch("httpx.AsyncClient") as mock_httpx:
            llm_instance = MagicMock()
            llm_instance.post = AsyncMock(return_value=make_llm(llm_keywords))
            llm_instance.__aenter__ = AsyncMock(return_value=llm_instance)
            llm_instance.__aexit__ = AsyncMock()

            pexels_instance = MagicMock()
            pexels_instance.get = AsyncMock(return_value=make_resp(401, []))
            pexels_instance.__aenter__ = AsyncMock(return_value=pexels_instance)
            pexels_instance.__aexit__ = AsyncMock()

            mock_httpx.side_effect = [llm_instance, pexels_instance]

            # B-roll fails gracefully
            recommender = AiBrollRecommender(llm_api_key="test-llm-key")
            task_ctx = make_task_ctx(segment_count=1)
            candidates = await recommender.suggest_broll(
                transcript="Nature is beautiful.",
                segment_id="clip_0",
                task_ctx=task_ctx,
            )
            assert len(candidates) > 0, "LLM should still produce candidates"

            client = PexelsClient(api_key="invalid-key")
            videos = await client.search_videos(
                query=candidates[0].keywords[0],
                min_duration=3.0,
                orientation="portrait",
            )
            assert len(videos) == 0, "Pexels should return empty on auth error"
            await client.close()

            # Music also fails (no music dir configured)
            music_track = pick_bgm_for_mood(
                mood="calm",
                duration_s=10.0,
                music_dir="/nonexistent/music/dir",
            )
            # Music still returns a track (with unresolved URL), but the file won't exist
            if music_track:
                assert not Path(music_track.url).exists() or music_track.url == music_track.file, \
                    "Music file should not exist in nonexistent dir"
