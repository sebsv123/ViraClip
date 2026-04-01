"""
Audio utilities for background music mixing and audio processing.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
import os
import json
import urllib.request
import urllib.parse
import subprocess

logger = logging.getLogger(__name__)

# Niche → Pixabay search query mapping
_NICHE_MUSIC_MOOD: Dict[str, str] = {
    "finance": "corporate background",
    "fitness": "energetic workout",
    "motivation": "inspiring motivational",
    "tech": "technology innovation",
    "education": "study focus",
    "health": "calm wellness",
    "entertainment": "upbeat fun",
    "gaming": "epic gaming",
    "cooking": "pleasant acoustic",
    "travel": "adventure exploration",
    "general": "background cinematic",
}

_PIXABAY_MUSIC_CACHE = Path("/tmp/supoclip_music_cache")


def _get_background_music_path(config_obj=None) -> Optional[Path]:
    """
    Return a random background music track from the music library folder,
    or None if none are available.
    """
    from ..config import config

    _cfg = config_obj or config
    search_dirs = [
        Path(_cfg.temp_dir) / "music",
        Path("/app/music"),
        Path("/app/backend/music"),
        Path("/tmp/supoclip_music_cache"),
    ]
    import random as _random

    for music_dir in search_dirs:
        if music_dir.exists():
            tracks = (
                list(music_dir.glob("*.mp3"))
                + list(music_dir.glob("*.wav"))
                + list(music_dir.glob("*.aac"))
            )
            if tracks:
                return _random.choice(tracks)
    return None


def fetch_pixabay_music(niche: str = "general", api_key: Optional[str] = None) -> Optional[Path]:
    """
    Fetch a royalty-free background music track from Pixabay API.
    """
    import random as _random

    key = api_key or os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        return None

    mood_query = _NICHE_MUSIC_MOOD.get(niche, _NICHE_MUSIC_MOOD["general"])
    safe_query = urllib.parse.quote(mood_query)

    _PIXABAY_MUSIC_CACHE.mkdir(parents=True, exist_ok=True)

    # Check local cache first
    niche_cached = list(_PIXABAY_MUSIC_CACHE.glob(f"{niche}_*.mp3"))
    if niche_cached:
        return _random.choice(niche_cached)

    try:
        api_url = (
            f"https://pixabay.com/api/videos/music/"
            f"?key={key}&q={safe_query}&per_page=10&min_duration=30"
        )
        req = urllib.request.Request(api_url, headers={"User-Agent": "SupoClip/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        hits = data.get("hits", [])
        if not hits:
            logger.debug(f"Pixabay music: no results for query '{mood_query}'")
            return None

        track = _random.choice(hits[:5])
        track_id = track.get("id")
        audio_url = track.get("audio_url") or track.get("url")

        if not audio_url:
            return None

        cache_filename = _PIXABAY_MUSIC_CACHE / f"{niche}_{track_id}.mp3"
        logger.info(f"🎵 Downloading Pixabay track: {track.get('title', 'unknown')} ({niche})")

        with urllib.request.urlopen(audio_url, timeout=60) as resp:
            cache_filename.write_bytes(resp.read())

        logger.info(f"✅ Pixabay music cached: {cache_filename.name}")
        return cache_filename

    except Exception as _pix_e:
        logger.debug(f"Pixabay music fetch skipped: {_pix_e}")
        return None


def get_background_music_for_niche(niche: str = "general", config_obj=None) -> Optional[Path]:
    """
    Get background music for a specific niche, trying:
    1. Local music folder (user-placed)
    2. Pixabay API (auto-downloaded, cached)
    3. Any available track from cache
    """
    from ..config import config

    _cfg = config_obj or config
    import random as _random

    # 1. Check local music folder
    for music_dir in [Path(_cfg.temp_dir) / "music", Path("/app/music")]:
        if music_dir.exists():
            tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
            if tracks:
                return _random.choice(tracks)

    # 2. Try Pixabay API
    pixabay_track = fetch_pixabay_music(niche)
    if pixabay_track:
        return pixabay_track

    # 3. Fallback: any cached track
    if _PIXABAY_MUSIC_CACHE.exists():
        any_tracks = list(_PIXABAY_MUSIC_CACHE.glob("*.mp3"))
        if any_tracks:
            return _random.choice(any_tracks)

    return None


def mix_background_music(
    video_path: Path,
    output_path: Path,
    music_volume: float = 0.12,
    ducking_enabled: bool = False,
) -> bool:
    """
    Mix a random background music track into a video at low volume (default 12%).
    Uses ffmpeg for fast, high-quality audio mixing.

    Returns True on success, False on failure.
    """
    music_path = _get_background_music_path()
    if music_path is None:
        logger.info("No background music tracks found — skipping music mix")
        return False

    logger.info(f"🎵 Mixing background music: {music_path.name} @ {int(music_volume*100)}% volume")
    try:
        filter_complex = (
            f"[1:a]volume={music_volume:.3f},aloop=loop=-1:size=2147483647[music];" +
            (f"[0:a][music]sidechaincompress=threshold=0.1:ratio=20:attack=20:release=100[music_ducked];[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
             if ducking_enabled else
             f"[0:a][music]amix=inputs=2:duration=first:normalize=0[aout]")
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(music_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-shortest",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"Music mix failed: {result.stderr[-300:]}")
            return False
        logger.info(f"✅ Background music mixed into {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Music mix error: {e}")
        return False
