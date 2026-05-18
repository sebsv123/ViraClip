"""
Background Music Service — Port of short-video-maker's MusicManager.

Provides mood-based background music selection for video clips.
Ports the 31-track music library from short-video-maker with mood tags,
random selection from matching mood, and graceful fallback.

If no music matches the requested mood, returns None (pipeline continues
without background music).
"""

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Mood enum (ported from short-video-maker's MusicMoodEnum) ──────────────────

class MusicMood:
    """Mood tags for background music tracks."""
    SAD = "sad"
    MELANCHOLIC = "melancholic"
    HAPPY = "happy"
    EUPHORIC = "euphoric/high"
    EXCITED = "excited"
    CHILL = "chill"
    UNEASY = "uneasy"
    ANGRY = "angry"
    DARK = "dark"
    HOPEFUL = "hopeful"
    CONTEMPLATIVE = "contemplative"
    FUNNY = "funny/quirky"

    ALL = {SAD, MELANCHOLIC, HAPPY, EUPHORIC, EXCITED, CHILL,
           UNEASY, ANGRY, DARK, HOPEFUL, CONTEMPLATIVE, FUNNY}


# ── Mood mapping: map generic moods to available music moods ──────────────────
# When a requested mood doesn't exist, fall back to the closest match.
MOOD_MAPPING: dict[str, str] = {
    "sad":            MusicMood.SAD,
    "melancholic":    MusicMood.MELANCHOLIC,
    "melancholy":     MusicMood.MELANCHOLIC,
    "happy":          MusicMood.HAPPY,
    "joyful":         MusicMood.HAPPY,
    "euphoric":       MusicMood.EUPHORIC,
    "high_energy":    MusicMood.EUPHORIC,
    "excited":        MusicMood.EXCITED,
    "exciting":       MusicMood.EXCITED,
    "chill":          MusicMood.CHILL,
    "relaxed":        MusicMood.CHILL,
    "calm":           MusicMood.CHILL,
    "uneasy":         MusicMood.UNEASY,
    "tense":          MusicMood.UNEASY,
    "suspenseful":    MusicMood.UNEASY,
    "angry":          MusicMood.ANGRY,
    "aggressive":     MusicMood.ANGRY,
    "dark":           MusicMood.DARK,
    "mysterious":     MusicMood.DARK,
    "hopeful":        MusicMood.HOPEFUL,
    "inspiring":      MusicMood.HOPEFUL,
    "contemplative":  MusicMood.CONTEMPLATIVE,
    "thoughtful":     MusicMood.CONTEMPLATIVE,
    "funny":          MusicMood.FUNNY,
    "quirky":         MusicMood.FUNNY,
    "playful":        MusicMood.FUNNY,
    "neutral":        MusicMood.CHILL,
}


@dataclass
class MusicTrack:
    """
    A single background music track with mood tag and timing info.

    Ported from short-video-maker's Music type.
    """
    file: str           # filename (e.g., "Sly Sky - Telecasted.mp3")
    start: float        # start offset in seconds
    end: float          # end offset in seconds
    mood: str           # mood tag from MusicMood
    url: str = ""       # full path resolved at runtime


class BackgroundMusicService:
    """
    Mood-based background music selector.

    Ported from short-video-maker's MusicManager class.
    Maintains a static library of 31 tracks with mood tags.
    """

    # ── Static music library (31 tracks, ported from short-video-maker) ────────
    _MUSIC_LIBRARY: List[MusicTrack] = [
        MusicTrack(file="Sly Sky - Telecasted.mp3", start=0, end=152, mood=MusicMood.MELANCHOLIC),
        MusicTrack(file="No.2 Remembering Her - Esther Abrami.mp3", start=2, end=134, mood=MusicMood.MELANCHOLIC),
        MusicTrack(file="Champion - Telecasted.mp3", start=0, end=142, mood=MusicMood.CHILL),
        MusicTrack(file="Oh Please - Telecasted.mp3", start=0, end=154, mood=MusicMood.CHILL),
        MusicTrack(file="Jetski - Telecasted.mp3", start=0, end=142, mood=MusicMood.UNEASY),
        MusicTrack(file="Phantom - Density & Time.mp3", start=0, end=178, mood=MusicMood.UNEASY),
        MusicTrack(file="On The Hunt - Andrew Langdon.mp3", start=0, end=95, mood=MusicMood.UNEASY),
        MusicTrack(file="Name The Time And Place - Telecasted.mp3", start=0, end=142, mood=MusicMood.EXCITED),
        MusicTrack(file="Delayed Baggage - Ryan Stasik.mp3", start=3, end=108, mood=MusicMood.EUPHORIC),
        MusicTrack(file="Like It Loud - Dyalla.mp3", start=4, end=160, mood=MusicMood.EUPHORIC),
        MusicTrack(file="Organic Guitar House - Dyalla.mp3", start=2, end=160, mood=MusicMood.EUPHORIC),
        MusicTrack(file="Honey, I Dismembered The Kids - Ezra Lipp.mp3", start=2, end=144, mood=MusicMood.DARK),
        MusicTrack(file="Night Hunt - Jimena Contreras.mp3", start=0, end=88, mood=MusicMood.DARK),
        MusicTrack(file="Curse of the Witches - Jimena Contreras.mp3", start=0, end=102, mood=MusicMood.DARK),
        MusicTrack(file="Restless Heart - Jimena Contreras.mp3", start=0, end=94, mood=MusicMood.SAD),
        MusicTrack(file="Heartbeat Of The Wind - Asher Fulero.mp3", start=0, end=124, mood=MusicMood.SAD),
        MusicTrack(file="Hopeless - Jimena Contreras.mp3", start=0, end=250, mood=MusicMood.SAD),
        MusicTrack(file="Touch - Anno Domini Beats.mp3", start=0, end=165, mood=MusicMood.HAPPY),
        MusicTrack(file="Cafecito por la Manana - Cumbia Deli.mp3", start=0, end=184, mood=MusicMood.HAPPY),
        MusicTrack(file="Aurora on the Boulevard - National Sweetheart.mp3", start=0, end=130, mood=MusicMood.HAPPY),
        MusicTrack(file="Buckle Up - Jeremy Korpas.mp3", start=0, end=128, mood=MusicMood.ANGRY),
        MusicTrack(file="Twin Engines - Jeremy Korpas.mp3", start=0, end=120, mood=MusicMood.ANGRY),
        MusicTrack(file="Hopeful - Nat Keefe.mp3", start=0, end=175, mood=MusicMood.HOPEFUL),
        MusicTrack(file="Hopeful Freedom - Asher Fulero.mp3", start=1, end=172, mood=MusicMood.HOPEFUL),
        MusicTrack(file="Crystaline - Quincas Moreira.mp3", start=0, end=140, mood=MusicMood.CONTEMPLATIVE),
        MusicTrack(file="Final Soliloquy - Asher Fulero.mp3", start=1, end=178, mood=MusicMood.CONTEMPLATIVE),
        MusicTrack(file="Seagull - Telecasted.mp3", start=0, end=123, mood=MusicMood.FUNNY),
        MusicTrack(file="Banjo Doops - Joel Cummins.mp3", start=0, end=98, mood=MusicMood.FUNNY),
        MusicTrack(file="Baby Animals Playing - Joel Cummins.mp3", start=0, end=124, mood=MusicMood.FUNNY),
        MusicTrack(file="Sinister - Anno Domini Beats.mp3", start=0, end=215, mood=MusicMood.DARK),
        MusicTrack(file="Traversing - Godmode.mp3", start=0, end=95, mood=MusicMood.DARK),
    ]

    def __init__(self, music_dir: Optional[str] = None):
        """
        Initialize the music service.

        Args:
            music_dir: Path to directory containing music files.
                       If None, uses default search paths.
        """
        self.music_dir = Path(music_dir) if music_dir else None

    # ── Public API ───────────────────────────────────────────────────────────

    def pick_music_for_segment(
        self,
        mood: str,
        duration_s: float,
    ) -> Optional[MusicTrack]:
        """
        Pick a background music track matching the given mood.

        Ported from short-video-maker's ShortCreator.findMusic() logic.

        Args:
            mood: Target mood string (e.g., "happy", "sad", "chill").
                  Will be mapped to the closest available mood.
            duration_s: Desired clip duration in seconds. The track's
                        available duration (end - start) should cover this.

        Returns:
            MusicTrack if a match is found, None otherwise.
        """
        # Map the requested mood to our available moods
        target_mood = MOOD_MAPPING.get(mood.lower().strip(), mood.lower().strip())

        # Validate the mapped mood
        if target_mood not in MusicMood.ALL:
            logger.debug(
                "[BackgroundMusic] Unknown mood '%s' (mapped from '%s'), "
                "falling back to chill",
                target_mood, mood,
            )
            target_mood = MusicMood.CHILL

        # Find tracks matching the mood
        candidates = [
            t for t in self._MUSIC_LIBRARY
            if t.mood == target_mood
        ]

        if not candidates:
            logger.info(
                "[BackgroundMusic] No tracks found for mood '%s' (requested: '%s')",
                target_mood, mood,
            )
            return None

        # Filter by duration: track must cover at least duration_s
        duration_ok = [
            t for t in candidates
            if (t.end - t.start) >= duration_s
        ]

        # If no track is long enough, pick the longest available
        if not duration_ok:
            longest = max(candidates, key=lambda t: t.end - t.start)
            logger.info(
                "[BackgroundMusic] No track covers %.1fs for mood '%s', "
                "using longest (%.1fs): %s",
                duration_s, target_mood, longest.end - longest.start, longest.file,
            )
            selected = longest
        else:
            # Pick a random track from duration-ok candidates
            selected = random.choice(duration_ok)

        # Resolve the full path
        selected.url = self._resolve_path(selected.file)

        logger.info(
            "[BackgroundMusic] Selected '%s' (mood=%s, dur=%.1fs) for mood='%s'",
            selected.file, selected.mood, selected.end - selected.start, mood,
        )
        return selected

    def list_tracks_by_mood(self, mood: str) -> List[MusicTrack]:
        """List all tracks matching a given mood."""
        target = MOOD_MAPPING.get(mood.lower().strip(), mood.lower().strip())
        return [t for t in self._MUSIC_LIBRARY if t.mood == target]

    def list_all_tracks(self) -> List[MusicTrack]:
        """Return the full music library."""
        return list(self._MUSIC_LIBRARY)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _resolve_path(self, filename: str) -> str:
        """
        Resolve the full path to a music file.

        Searches in order:
        1. Configured music_dir
        2. Default Docker mount paths
        3. Returns just the filename if not found (caller handles fallback)
        """
        search_dirs = []
        if self.music_dir:
            search_dirs.append(self.music_dir)
        search_dirs.extend([
            Path("/app/assets/sounds/bgm"),
            Path("/app/assets/sounds/music"),
            Path("/app/assets/sounds"),
            Path("/app/music/bgm"),
            Path("/app/music"),
        ])

        for d in search_dirs:
            p = d / filename
            if p.exists():
                return str(p)

        # Fallback: return just the filename (smart_audio.find_bgm_track
        # will handle the actual file search at runtime)
        return filename

    def ensure_music_files_exist(self) -> List[str]:
        """
        Verify that all music files exist on disk.

        Ported from short-video-maker's MusicManager.ensureMusicFilesExist().

        Returns:
            List of missing filenames (empty if all present).
        """
        missing: List[str] = []
        for track in self._MUSIC_LIBRARY:
            resolved = self._resolve_path(track.file)
            if not Path(resolved).exists():
                missing.append(track.file)
        if missing:
            logger.warning(
                "[BackgroundMusic] %d music file(s) not found: %s",
                len(missing), missing[:5],
            )
        return missing


# ── Convenience function ──────────────────────────────────────────────────────

def pick_bgm_for_mood(
    mood: str,
    duration_s: float,
    music_dir: Optional[str] = None,
) -> Optional[MusicTrack]:
    """
    Convenience function to pick background music by mood.

    Args:
        mood: Target mood string.
        duration_s: Desired clip duration.
        music_dir: Optional music directory override.

    Returns:
        MusicTrack or None.
    """
    service = BackgroundMusicService(music_dir=music_dir)
    return service.pick_music_for_segment(mood=mood, duration_s=duration_s)


# ── Singleton ─────────────────────────────────────────────────────────────────

_background_music_service: Optional[BackgroundMusicService] = None


def get_background_music_service(
    music_dir: Optional[str] = None,
) -> BackgroundMusicService:
    """Return a cached BackgroundMusicService singleton."""
    global _background_music_service
    if _background_music_service is None:
        _background_music_service = BackgroundMusicService(music_dir=music_dir)
    return _background_music_service
