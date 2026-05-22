"""
Background Music Service — Port of short-video-maker's MusicManager.

Provides mood-based background music selection for video clips.
Ports the 31-track music library from short-video-maker with mood tags,
random selection from matching mood, and graceful fallback.

If no music matches the requested mood, returns None (pipeline continues
without background music).
"""

import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Local fallback music library ──────────────────────────────────────────────
# Directory for locally stored music files named with energy prefix:
#   low_*.mp3, mid_*.mp3, high_*.mp3
MUSIC_LIBRARY_PATH = Path(os.environ.get(
    "MUSIC_LIBRARY_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "assets" / "music"),
))


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
    has_vocals: bool = False  # True if track contains lyrics/singing


class BackgroundMusicService:
    """
    Mood-based background music selector.

    Ported from short-video-maker's MusicManager class.
    Maintains a static library of 31 tracks with mood tags.
    """

    # ── Static music library (all tracks present on disk) ─────────────────────
    # Auto-generated from ./backend/music/bgm/*.mp3
    # has_vocals=True for tracks with lyrics/singing (avoid for talking-head clips)
    _MUSIC_LIBRARY: List[MusicTrack] = [
        MusicTrack(file="Back To The Start - Patrick Jordan Patrikios.mp3", start=0, end=120, mood=MusicMood.HAPPY, has_vocals=True),
        MusicTrack(file="Be The One - Lore Vain.mp3", start=0, end=120, mood=MusicMood.HOPEFUL, has_vocals=True),
        MusicTrack(file="bgm_cinematic_ambient.mp3", start=0, end=120, mood=MusicMood.CHILL, has_vocals=False),
        MusicTrack(file="bgm_dramatic_tension.mp3", start=0, end=120, mood=MusicMood.DARK, has_vocals=False),
        MusicTrack(file="bgm_energetic_hype.mp3", start=0, end=120, mood=MusicMood.EXCITED, has_vocals=False),
        MusicTrack(file="bgm_lofi_chill.mp3", start=0, end=120, mood=MusicMood.CHILL, has_vocals=False),
        MusicTrack(file="bgm_upbeat_positive.mp3", start=0, end=120, mood=MusicMood.HAPPY, has_vocals=False),
        MusicTrack(file="Care Is Heavy - Jeremy Korpas, Rick Barry.mp3", start=0, end=120, mood=MusicMood.DARK, has_vocals=False),
        MusicTrack(file="corporate_clean.mp3", start=0, end=120, mood=MusicMood.CONTEMPLATIVE, has_vocals=False),
        MusicTrack(file="Delirium - Anno Domini Beats.mp3", start=0, end=120, mood=MusicMood.DARK, has_vocals=False),
        MusicTrack(file="Elysian Fields - Jeremy Korpas, Rick Barry.mp3", start=0, end=120, mood=MusicMood.DARK, has_vocals=False),
        MusicTrack(file="Eyes - Patrick Jordan Patrikios.mp3", start=0, end=120, mood=MusicMood.HAPPY, has_vocals=True),
        MusicTrack(file="House Of Cards - Blue Deer.mp3", start=0, end=120, mood=MusicMood.CHILL, has_vocals=True),
        MusicTrack(file="lofi_chill.mp3", start=0, end=120, mood=MusicMood.CHILL, has_vocals=False),
        MusicTrack(file="Scratches On The B-Side - National Sweetheart.mp3", start=0, end=120, mood=MusicMood.HAPPY, has_vocals=True),
        MusicTrack(file="Talk To Me (feat. Devyn Rush) - Blue Deer.mp3", start=0, end=120, mood=MusicMood.HOPEFUL, has_vocals=True),
        MusicTrack(file="Through The Night (feat. Devyn Rush) - Blue Deer.mp3", start=0, end=120, mood=MusicMood.HOPEFUL, has_vocals=True),
        MusicTrack(file="Tiny Shell - Blue Deer, Nyles Lannon.mp3", start=0, end=120, mood=MusicMood.CHILL, has_vocals=True),
        MusicTrack(file="Tonight Again - Rod Kim (feat. Mostly Moss).mp3", start=0, end=120, mood=MusicMood.HAPPY, has_vocals=True),
        MusicTrack(file="Turn In The Sun - Simon Herody.mp3", start=0, end=120, mood=MusicMood.HOPEFUL, has_vocals=True),
        MusicTrack(file="upbeat_energy.mp3", start=0, end=120, mood=MusicMood.EUPHORIC, has_vocals=False),
        MusicTrack(file="Visions - Patrick Jordan Patrikios.mp3", start=0, end=120, mood=MusicMood.HOPEFUL, has_vocals=True),
        MusicTrack(file="Way Back Home - Simon Herody.mp3", start=0, end=120, mood=MusicMood.HOPEFUL, has_vocals=True),
        MusicTrack(file="Yesterdays - Blue Deer.mp3", start=0, end=120, mood=MusicMood.CHILL, has_vocals=True),
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
        content_type: str = "",
    ) -> Optional[MusicTrack]:
        """
        Pick a background music track matching the given mood.

        Ported from short-video-maker's ShortCreator.findMusic() logic.

        Args:
            mood: Target mood string (e.g., "happy", "sad", "chill").
                  Will be mapped to the closest available mood.
            duration_s: Desired clip duration in seconds. The track's
                        available duration (end - start) should cover this.
            content_type: Content type hint ("talking_head", "interview", etc.).
                          For talking-head clips, prefers instrumental tracks.

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

        # For talking_head / interview clips: EXCLUDE vocal tracks entirely
        _is_talking = content_type.lower() in ("talking_head", "interview", "podcast", "tutorial")
        if _is_talking:
            instrumental = [t for t in candidates if not t.has_vocals]
            if instrumental:
                logger.info(
                    "[BackgroundMusic] Talking-head clip — excluding vocal tracks entirely "
                    "(%d instrumental available, %d vocal tracks excluded)",
                    len(instrumental), len(candidates) - len(instrumental),
                )
                candidates = instrumental
            else:
                # No instrumental tracks for this mood — use all but reduce volume
                logger.info(
                    "[BackgroundMusic] No instrumental tracks for mood '%s' — "
                    "will use vocal track at reduced volume",
                    target_mood,
                )

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
            "[BackgroundMusic] Selected '%s' (mood=%s, dur=%.1fs, vocals=%s) for mood='%s'",
            selected.file, selected.mood, selected.end - selected.start, selected.has_vocals, mood,
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


# ── Local fallback music ──────────────────────────────────────────────────────

def get_local_music_track(energy_level: str) -> Optional[str]:
    """
    Scan MUSIC_LIBRARY_PATH for a local music file matching the energy level.

    Files should be named with an energy prefix: low_*, mid_*, high_*.
    Returns a random matching file path, or any file if no match, or None.
    """
    if not MUSIC_LIBRARY_PATH.exists():
        logger.debug("[BackgroundMusic] Local music dir not found: %s", MUSIC_LIBRARY_PATH)
        return None

    all_files = sorted(MUSIC_LIBRARY_PATH.glob("*.mp3")) + sorted(MUSIC_LIBRARY_PATH.glob("*.wav"))
    if not all_files:
        logger.debug("[BackgroundMusic] No local music files in %s", MUSIC_LIBRARY_PATH)
        return None

    # Filter by energy prefix
    prefix = energy_level.lower().strip() + "_"
    matching = [f for f in all_files if f.name.lower().startswith(prefix)]

    if matching:
        chosen = random.choice(matching)
        logger.info(
            "[BackgroundMusic] Local fallback: '%s' (energy=%s)",
            chosen.name, energy_level,
        )
        return str(chosen)

    # No match — return any file
    chosen = random.choice(all_files)
    logger.info(
        "[BackgroundMusic] Local fallback (no energy match): '%s'",
        chosen.name,
    )
    return str(chosen)


def pick_music_with_fallback(
    mood: str,
    duration_s: float,
    virality_score: float = 50.0,
    music_dir: Optional[str] = None,
) -> Optional[MusicTrack]:
    """
    Pick background music with local fallback.

    1. Try the external mood-based library first (pick_music_for_segment).
    2. If that returns None, falls back to get_local_music_track().
    3. Derives energy_level from virality_score:
       score < 40 → "low", 40–70 → "mid", > 70 → "high"
    4. If local fallback also returns None, logs a warning and returns None
       (pipeline continues without music).

    Args:
        mood: Target mood string.
        duration_s: Desired clip duration.
        virality_score: Segment virality/engagement score (0–100).
        music_dir: Optional music directory override.

    Returns:
        MusicTrack or None.
    """
    # Step 1: Try the external mood-based library
    service = BackgroundMusicService(music_dir=music_dir)
    track = service.pick_music_for_segment(mood=mood, duration_s=duration_s)
    if track is not None:
        return track

    # Step 2: Derive energy level from virality score
    if virality_score < 40:
        energy_level = "low"
    elif virality_score <= 70:
        energy_level = "mid"
    else:
        energy_level = "high"

    # Step 3: Fall back to local music
    local_path = get_local_music_track(energy_level)
    if local_path is None:
        logger.warning(
            "[BackgroundMusic] No music track available — "
            "skipping background music for this clip",
        )
        return None

    # Wrap local file as a MusicTrack
    local_file = Path(local_path)
    return MusicTrack(
        file=local_file.name,
        start=0,
        end=duration_s,
        mood=energy_level,
        url=local_path,
    )


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
