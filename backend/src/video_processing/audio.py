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

_PIXABAY_MUSIC_CACHE = Path("/tmp/viraclip_music_cache")


def _get_background_music_path(config_obj=None) -> Optional[Path]:
    """
    Return a random background music track from the music library folder,
    or None if none are available.
    """
    from ..config import get_config as _get_cfg_inner

    _cfg = config_obj or _get_cfg_inner()
    search_dirs = [
        Path("/app/assets/sounds/bgm"),   # Docker volume: ./backend/music:/app/assets/sounds
        Path("/app/assets/sounds/music"),
        Path(_cfg.temp_dir) / "music",
        Path("/app/music"),
        Path("/app/backend/music"),
        Path("/tmp/viraclip_music_cache"),
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
            f"https://pixabay.com/api/videos/"
            f"?key={key}&q={safe_query}&type=music&per_page=10&min_duration=30"
        )
        req = urllib.request.Request(api_url, headers={"User-Agent": "ViraClip/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        hits = data.get("hits", [])
        if not hits:
            logger.debug(f"Pixabay music: no results for query '{mood_query}'")
            return None

        track = _random.choice(hits[:5])
        track_id = track.get("id")
        # Pixabay videos API returns pageURL or videos dict; audio tracks have audio_url or pageURL
        audio_url = (
            track.get("audio_url")
            or track.get("url")
            or (track.get("videos") or {}).get("small", {}).get("url")
        )

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
    from ..config import get_config as _get_cfg_inner

    _cfg = config_obj or _get_cfg_inner()
    import random as _random

    # 1. Check local music folder (multiple candidate paths, bgm/ preferred to avoid SFX)
    for music_dir in [
        Path("/app/assets/sounds/bgm"),
        Path("/app/assets/sounds/music"),
        Path(_cfg.temp_dir) / "music",
        Path("/app/music"),  # legacy path
    ]:
        if music_dir.exists():
            tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
            if tracks:
                chosen = _random.choice(tracks)
                logger.debug(f"[music] Found local track: {chosen.name} (from {music_dir})")
                return chosen

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


async def apply_voice_enhancement(
    video_path: str,
    output_path: str,
    model_path: Optional[str] = None,
    pitch_shift: int = 0,
) -> bool:
    """
    Phase 3.2 — RVC (Retrieval-based Voice Conversion) voice enhancement.
    Converts the speaker voice to a cleaner, more energetic vocal profile.

    Requires: pip install rvc-python (or torch + faiss-gpu/faiss-cpu)
    Falls back to lightweight FFmpeg vocal EQ when RVC is unavailable.

    Returns True on success (output_path written), False if skipped.
    """
    import asyncio

    try:
        from rvc_python.infer import RVCInference   # type: ignore

        rvc_model = model_path or os.environ.get("RVC_MODEL_PATH", "")
        if not rvc_model or not Path(rvc_model).exists():
            raise FileNotFoundError(f"RVC model not found: {rvc_model}")

        rvc = RVCInference()
        rvc.load_model(rvc_model)
        rvc.infer_file(video_path, output_path, pitch_shift=pitch_shift)
        logger.info(f"🎤 RVC voice enhancement applied: {Path(output_path).name}")
        return True

    except (ImportError, FileNotFoundError) as _rvc_e:
        logger.debug(f"[RVC] Unavailable ({_rvc_e}) — using FFmpeg vocal EQ fallback")

    # Fallback: vocal presence boost + de-essing via FFmpeg
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-af",
        "equalizer=f=3000:width_type=o:width=2:g=2,"
        "equalizer=f=7500:width_type=o:width=2:g=-3,"
        "compand=attacks=0.05:decays=0.2:points=-70/-70|-24/-12|0/-6:soft-knee=0.1,"
        "afftdn=nf=-20",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        ok = proc.returncode == 0 and Path(output_path).exists()
        if ok:
            logger.info(f"🎤 Vocal EQ fallback applied: {Path(output_path).name}")
        return ok
    except Exception as exc:
        logger.debug(f"[RVC] FFmpeg fallback failed: {exc}")
        return False


async def denoise_audio(
    video_path: str,
    output_path: str,
    noise_floor_db: float = -25.0,
) -> bool:
    """
    Apply adaptive FFT denoising via FFmpeg's built-in afftdn filter.
    No external model required. Removes background hiss/hum without distorting speech.

    Returns True on success, False on failure (caller keeps original).
    """
    import asyncio

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-af", f"afftdn=nf={noise_floor_db:.0f}",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0 and Path(output_path).exists():
            logger.info(f"🔇 Audio denoised (afftdn nf={noise_floor_db}dB): {Path(output_path).name}")
            return True
        logger.debug(f"[denoise] ffmpeg returned {proc.returncode}: {stderr.decode()[:200]}")
        return False
    except Exception as exc:
        logger.debug(f"[denoise] Exception: {exc}")
        return False


def mix_background_music(
    video_path: Path,
    output_path: Path,
    music_volume: float = 0.22,
    ducking_enabled: bool = True,
    music_path: Optional[Path] = None,
) -> bool:
    """
    Mix a background music track into a video at low volume (default 12%).
    Uses ffmpeg for fast, high-quality audio mixing.

    If music_path is provided it is used directly; otherwise a random local
    track is selected via _get_background_music_path().

    Returns True on success, False on failure.
    """
    if music_path is None:
        music_path = _get_background_music_path()
    if music_path is None:
        logger.info("No background music tracks found — skipping music mix")
        return False

    logger.info(f"🎵 Mixing background music: {music_path.name} @ {int(music_volume*100)}% volume")
    try:
        if ducking_enabled:
            # [music_loop] = signal to compress, [0:a] = sidechain trigger (voice)
            # When voice is loud the music is ducked down; music recovers in 800ms
            filter_complex = (
                f"[1:a]volume={music_volume:.3f},aloop=loop=-1:size=2000000000[music_loop];"
                "[music_loop][0:a]sidechaincompress=threshold=0.015:ratio=6:attack=50:release=800[music_ducked];"
                "[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
            )
        else:
            filter_complex = (
                f"[1:a]volume={music_volume:.3f},aloop=loop=-1:size=2000000000[music_loop];"
                "[0:a][music_loop]amix=inputs=2:duration=first:normalize=0[aout]"
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
