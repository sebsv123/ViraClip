"""
Unit tests for BackgroundMusicService (backend/src/services/background_music_service.py).

Tests cover:
- MusicTrack dataclass
- MusicMood constants and validation
- pick_music_for_segment with various moods
- Mood mapping (e.g., "joyful" → "happy")
- Duration filtering (track must cover requested duration)
- Fallback to longest track when none covers duration
- Unknown mood fallback to "chill"
- Empty candidates for unmapped mood
- list_tracks_by_mood
- list_all_tracks
- ensure_music_files_exist
- _resolve_path logic
- Singleton pattern
- Convenience function pick_bgm_for_mood
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import List, Optional

from src.services.background_music_service import (
    BackgroundMusicService,
    MusicTrack,
    MusicMood,
    MOOD_MAPPING,
    pick_bgm_for_mood,
    get_background_music_service,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def service():
    """BackgroundMusicService with no music_dir (uses default search paths)."""
    return BackgroundMusicService()


@pytest.fixture()
def service_with_dir(tmp_path):
    """BackgroundMusicService with a temporary music directory."""
    return BackgroundMusicService(music_dir=str(tmp_path))


# ── Tests: MusicMood ──────────────────────────────────────────────────────────


class TestMusicMood:
    """MusicMood constants and validation."""

    def test_all_moods_present(self):
        assert MusicMood.SAD == "sad"
        assert MusicMood.MELANCHOLIC == "melancholic"
        assert MusicMood.HAPPY == "happy"
        assert MusicMood.EUPHORIC == "euphoric/high"
        assert MusicMood.EXCITED == "excited"
        assert MusicMood.CHILL == "chill"
        assert MusicMood.UNEASY == "uneasy"
        assert MusicMood.ANGRY == "angry"
        assert MusicMood.DARK == "dark"
        assert MusicMood.HOPEFUL == "hopeful"
        assert MusicMood.CONTEMPLATIVE == "contemplative"
        assert MusicMood.FUNNY == "funny/quirky"

    def test_all_set_contains_all(self):
        assert len(MusicMood.ALL) == 12
        assert MusicMood.SAD in MusicMood.ALL
        assert MusicMood.FUNNY in MusicMood.ALL


# ── Tests: MusicTrack ─────────────────────────────────────────────────────────


class TestMusicTrack:
    """MusicTrack dataclass."""

    def test_dataclass_creation(self):
        t = MusicTrack(file="test.mp3", start=0, end=120, mood="happy")
        assert t.file == "test.mp3"
        assert t.start == 0
        assert t.end == 120
        assert t.mood == "happy"
        assert t.url == ""  # default

    def test_dataclass_with_url(self):
        t = MusicTrack(file="test.mp3", start=0, end=120, mood="happy", url="/path/to/test.mp3")
        assert t.url == "/path/to/test.mp3"

    def test_dataclass_repr(self):
        t = MusicTrack(file="test.mp3", start=0, end=120, mood="happy")
        r = repr(t)
        assert "MusicTrack" in r
        assert "test.mp3" in r


# ── Tests: Mood Mapping ───────────────────────────────────────────────────────


class TestMoodMapping:
    """MOOD_MAPPING dictionary."""

    def test_direct_mappings(self):
        assert MOOD_MAPPING["sad"] == "sad"
        assert MOOD_MAPPING["happy"] == "happy"
        assert MOOD_MAPPING["chill"] == "chill"

    def test_synonym_mappings(self):
        assert MOOD_MAPPING["joyful"] == "happy"
        assert MOOD_MAPPING["melancholy"] == "melancholic"
        assert MOOD_MAPPING["high_energy"] == "euphoric/high"
        assert MOOD_MAPPING["relaxed"] == "chill"
        assert MOOD_MAPPING["tense"] == "uneasy"
        assert MOOD_MAPPING["aggressive"] == "angry"
        assert MOOD_MAPPING["mysterious"] == "dark"
        assert MOOD_MAPPING["inspiring"] == "hopeful"
        assert MOOD_MAPPING["thoughtful"] == "contemplative"
        assert MOOD_MAPPING["quirky"] == "funny/quirky"
        assert MOOD_MAPPING["playful"] == "funny/quirky"

    def test_neutral_maps_to_chill(self):
        assert MOOD_MAPPING["neutral"] == "chill"


# ── Tests: pick_music_for_segment ─────────────────────────────────────────────


class TestPickMusicForSegment:
    """Core music selection logic."""

    def test_pick_happy_mood(self, service):
        """Should return a track with mood='happy'."""
        track = service.pick_music_for_segment(mood="happy", duration_s=30.0)
        assert track is not None
        assert track.mood == "happy"
        assert track.file != ""

    def test_pick_sad_mood(self, service):
        """Should return a track with mood='sad'."""
        track = service.pick_music_for_segment(mood="sad", duration_s=30.0)
        assert track is not None
        assert track.mood == "sad"

    def test_pick_chill_mood(self, service):
        """Should return a track with mood='chill'."""
        track = service.pick_music_for_segment(mood="chill", duration_s=30.0)
        assert track is not None
        assert track.mood == "chill"

    def test_pick_dark_mood(self, service):
        """Should return a track with mood='dark'."""
        track = service.pick_music_for_segment(mood="dark", duration_s=30.0)
        assert track is not None
        assert track.mood == "dark"

    def test_pick_funny_mood(self, service):
        """Should return a track with mood='funny/quirky'."""
        track = service.pick_music_for_segment(mood="funny", duration_s=30.0)
        assert track is not None
        assert track.mood == "funny/quirky"

    def test_pick_via_synonym(self, service):
        """'joyful' should map to 'happy' and return a happy track."""
        track = service.pick_music_for_segment(mood="joyful", duration_s=30.0)
        assert track is not None
        assert track.mood == "happy"

    def test_pick_via_synonym_quirky(self, service):
        """'quirky' should map to 'funny/quirky'."""
        track = service.pick_music_for_segment(mood="quirky", duration_s=30.0)
        assert track is not None
        assert track.mood == "funny/quirky"

    def test_unknown_mood_falls_back_to_chill(self, service):
        """Unknown mood should fall back to 'chill'."""
        track = service.pick_music_for_segment(mood="nonexistent_mood_xyz", duration_s=30.0)
        assert track is not None
        assert track.mood == "chill"

    def test_duration_filter(self, service):
        """Track should have enough duration to cover the request."""
        track = service.pick_music_for_segment(mood="happy", duration_s=10.0)
        assert track is not None
        available = track.end - track.start
        assert available >= 10.0

    def test_long_duration_fallback(self, service):
        """When no track covers the requested duration, pick the longest."""
        # Request a very long duration that no track can cover
        track = service.pick_music_for_segment(mood="happy", duration_s=9999.0)
        assert track is not None
        # Should have picked the longest happy track
        happy_tracks = [t for t in service._MUSIC_LIBRARY if t.mood == "happy"]
        longest = max(happy_tracks, key=lambda t: t.end - t.start)
        assert track.file == longest.file

    def test_url_is_resolved(self, service):
        """The returned track should have its url field set."""
        track = service.pick_music_for_segment(mood="chill", duration_s=30.0)
        assert track is not None
        assert track.url != ""  # resolved path or filename

    def test_all_moods_have_tracks(self, service):
        """Every canonical mood should have at least one track."""
        for mood in MusicMood.ALL:
            track = service.pick_music_for_segment(mood=mood, duration_s=10.0)
            assert track is not None, f"No track found for mood '{mood}'"
            assert track.mood == mood


class TestPickMusicForSegmentEdgeCases:
    """Edge cases for music selection."""

    def test_zero_duration(self, service):
        """Zero duration should still find a track."""
        track = service.pick_music_for_segment(mood="happy", duration_s=0)
        assert track is not None

    def test_negative_duration(self, service):
        """Negative duration should still find a track."""
        track = service.pick_music_for_segment(mood="happy", duration_s=-1)
        assert track is not None

    def test_case_insensitive_mood(self, service):
        """Mood should be case-insensitive."""
        track_upper = service.pick_music_for_segment(mood="HAPPY", duration_s=30.0)
        track_lower = service.pick_music_for_segment(mood="happy", duration_s=30.0)
        assert track_upper is not None
        assert track_lower is not None
        assert track_upper.mood == track_lower.mood

    def test_whitespace_in_mood(self, service):
        """Mood with extra whitespace should be trimmed."""
        track = service.pick_music_for_segment(mood="  happy  ", duration_s=30.0)
        assert track is not None
        assert track.mood == "happy"


# ── Tests: list_tracks_by_mood ────────────────────────────────────────────────


class TestListTracksByMood:
    """Listing tracks by mood."""

    def test_list_happy(self, service):
        tracks = service.list_tracks_by_mood("happy")
        assert len(tracks) >= 1
        assert all(t.mood == "happy" for t in tracks)

    def test_list_via_synonym(self, service):
        tracks = service.list_tracks_by_mood("joyful")
        assert len(tracks) >= 1
        assert all(t.mood == "happy" for t in tracks)

    def test_list_unknown_mood(self, service):
        tracks = service.list_tracks_by_mood("nonexistent")
        # Unknown mood falls back to itself, which won't match anything
        assert len(tracks) == 0

    def test_list_all_moods_have_tracks(self, service):
        for mood in MusicMood.ALL:
            tracks = service.list_tracks_by_mood(mood)
            assert len(tracks) >= 1, f"No tracks for mood '{mood}'"


# ── Tests: list_all_tracks ────────────────────────────────────────────────────


class TestListAllTracks:
    """Listing all tracks."""

    def test_list_all(self, service):
        tracks = service.list_all_tracks()
        assert len(tracks) == 31  # 31 tracks ported from short-video-maker

    def test_list_all_returns_copy(self, service):
        tracks1 = service.list_all_tracks()
        tracks2 = service.list_all_tracks()
        # Should be independent copies
        assert tracks1 is not tracks2

    def test_all_tracks_have_valid_mood(self, service):
        for t in service.list_all_tracks():
            assert t.mood in MusicMood.ALL, f"Track '{t.file}' has invalid mood '{t.mood}'"

    def test_all_tracks_have_positive_duration(self, service):
        for t in service.list_all_tracks():
            assert t.end > t.start, f"Track '{t.file}' has end <= start"


# ── Tests: _resolve_path ──────────────────────────────────────────────────────


class TestResolvePath:
    """Path resolution logic."""

    def test_resolve_with_configured_dir(self, tmp_path):
        """Should find file in configured music_dir."""
        music_file = tmp_path / "test_song.mp3"
        music_file.write_text("fake audio data")
        svc = BackgroundMusicService(music_dir=str(tmp_path))
        path = svc._resolve_path("test_song.mp3")
        assert path == str(music_file)

    def test_resolve_not_found_returns_filename(self, service):
        """When file is not found, return just the filename."""
        path = service._resolve_path("nonexistent_file_xyz.mp3")
        assert path == "nonexistent_file_xyz.mp3"

    def test_resolve_without_dir(self, service):
        """Without configured dir, should search default paths."""
        # Since we can't guarantee files exist, just check it returns something
        path = service._resolve_path("some_file.mp3")
        assert isinstance(path, str)
        assert len(path) > 0


# ── Tests: ensure_music_files_exist ───────────────────────────────────────────


class TestEnsureMusicFilesExist:
    """File existence verification."""

    def test_all_missing_without_dir(self, service):
        """Without music_dir, all files should be missing."""
        missing = service.ensure_music_files_exist()
        assert len(missing) == 31  # all 31 tracks missing

    def test_some_present(self, tmp_path, service_with_dir):
        """When some files exist, only missing ones are reported."""
        # Create one music file
        track = service_with_dir._MUSIC_LIBRARY[0]
        music_file = tmp_path / track.file
        music_file.write_text("fake audio")
        missing = service_with_dir.ensure_music_files_exist()
        assert track.file not in missing
        assert len(missing) == 30  # 30 still missing

    def test_all_present(self, tmp_path):
        """When all files exist, missing list should be empty."""
        svc = BackgroundMusicService(music_dir=str(tmp_path))
        for t in svc._MUSIC_LIBRARY:
            music_file = tmp_path / t.file
            music_file.write_text("fake audio")
        missing = svc.ensure_music_files_exist()
        assert missing == []


# ── Tests: Singleton ──────────────────────────────────────────────────────────


class TestSingleton:
    """Singleton pattern."""

    def test_get_background_music_service(self):
        s1 = get_background_music_service()
        s2 = get_background_music_service()
        assert s1 is s2

    def test_singleton_with_dir(self, tmp_path):
        s1 = get_background_music_service(music_dir=str(tmp_path))
        s2 = get_background_music_service(music_dir=str(tmp_path))
        assert s1 is s2

    def test_cleanup(self):
        # Reset singleton for other tests
        import src.services.background_music_service as bms
        bms._background_music_service = None
        assert get_background_music_service() is not None


# ── Tests: Convenience function ───────────────────────────────────────────────


class TestPickBgmForMood:
    """Convenience function pick_bgm_for_mood."""

    def test_pick_bgm_for_mood(self):
        track = pick_bgm_for_mood(mood="happy", duration_s=30.0)
        assert track is not None
        assert track.mood == "happy"

    def test_pick_bgm_for_mood_with_dir(self, tmp_path):
        track = pick_bgm_for_mood(mood="sad", duration_s=30.0, music_dir=str(tmp_path))
        assert track is not None
        assert track.mood == "sad"

    def test_pick_bgm_for_mood_unknown(self):
        track = pick_bgm_for_mood(mood="nonexistent", duration_s=30.0)
        assert track is not None
        assert track.mood == "chill"  # falls back to chill


# ── Tests: Music library integrity ────────────────────────────────────────────


class TestMusicLibraryIntegrity:
    """Ensure the ported music library is complete and consistent."""

    def test_31_tracks(self, service):
        assert len(service._MUSIC_LIBRARY) == 31

    def test_all_tracks_have_file(self, service):
        for t in service._MUSIC_LIBRARY:
            assert t.file, f"Track missing file: {t}"
            assert t.file.endswith(".mp3"), f"Track file should be .mp3: {t.file}"

    def test_all_tracks_have_valid_start_end(self, service):
        for t in service._MUSIC_LIBRARY:
            assert t.start >= 0, f"Negative start for {t.file}"
            assert t.end > t.start, f"end <= start for {t.file}"

    def test_mood_distribution(self, service):
        """Each mood should have at least 2 tracks for variety."""
        from collections import Counter
        mood_counts = Counter(t.mood for t in service._MUSIC_LIBRARY)
        for mood, count in mood_counts.items():
            assert count >= 2, f"Mood '{mood}' only has {count} track(s)"

    def test_no_duplicate_filenames(self, service):
        filenames = [t.file for t in service._MUSIC_LIBRARY]
        assert len(filenames) == len(set(filenames)), "Duplicate filenames found"
