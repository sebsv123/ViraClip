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


def get_background_music_for_niche(niche: str = "general", config_obj=None, video_path: Optional[Path] = None) -> Optional[Path]:
    """
    Get background music for a specific niche, trying:
    1. Local music folder (user-placed)
    2. Pixabay API (auto-downloaded, cached)
    3. Freesound API (mood-matched)
    4. Any available track from cache

    If video_path is provided, AudioAnalysisService detects actual mood and refines niche.
    """
    from ..config import get_config as _get_cfg_inner

    _cfg = config_obj or _get_cfg_inner()
    import random as _random

    # 0. AudioAnalysisService: detect actual audio mood to refine niche
    if video_path and video_path.exists():
        try:
            import asyncio as _asyncio
            from ..services.audio_analysis import get_audio_analysis_service
            _aa = get_audio_analysis_service()
            _loop = _asyncio.new_event_loop()
            _audio_data = _loop.run_until_complete(_aa.analyze_audio(video_path, extract_music_info=False))
            _loop.close()
            _stats = _audio_data.get("statistics", {})
            _mood = _stats.get("dominant_mood") or _stats.get("mood")
            if _mood and isinstance(_mood, str):
                niche = _mood
                logger.info(f"[music] AudioAnalysis detected mood='{niche}' — using for BGM selection")
        except Exception as _aa_e:
            logger.debug(f"[music] AudioAnalysis mood detection skipped: {_aa_e}")

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

    # 2.5. BackgroundMusicService: Pixabay mood-search with adaptive volume metadata
    try:
        import asyncio as _asyncio2
        from ..services.background_music_service import BackgroundMusicService as _BMS
        _bms = _BMS()
        _bms_loop = _asyncio2.new_event_loop()
        _bms_tracks = _bms_loop.run_until_complete(_bms.search_music(mood=niche, duration=30))
        _bms_loop.close()
        if _bms_tracks:
            _bms_track = _bms_tracks[0]
            _bms_cache = Path(_cfg.temp_dir) / "bgm_service"
            _bms_cache.mkdir(parents=True, exist_ok=True)
            _bms_out = str(_bms_cache / f"{_bms_track.id}_{niche}.mp3")
            _bms_ok = _bms.download_music(_bms_track, _bms_out)
            if _bms_ok and Path(_bms_out).exists():
                logger.info(f"[music] BackgroundMusicService track: {Path(_bms_out).name}")
                return Path(_bms_out)
    except Exception as _bms_e:
        logger.debug(f"[music] BackgroundMusicService skipped: {_bms_e}")

    # 3. Try Freesound API (mood-matched background music)
    if os.environ.get("FREESOUND_API_KEY", "") and os.environ.get("FREESOUND_AUTO_MATCH", "true").lower() == "true":
        try:
            import asyncio as _asyncio
            from ..services.freesound_service import FreesoundService as _FS
            _fs_svc = _FS()
            _fs_cache = Path(_cfg.temp_dir) / "freesound_bgm"
            _fs_cache.mkdir(parents=True, exist_ok=True)
            _cached = list(_fs_cache.glob("*.mp3")) + list(_fs_cache.glob("*.wav"))
            if _cached:
                chosen = _random.choice(_cached)
                logger.info(f"[music] Freesound cache hit: {chosen.name}")
                return chosen
            # Async search — only works when called from async context
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures as _cf
                _future = _asyncio.ensure_future(
                    _fs_svc.search_music(mood=niche, duration_max=15.0, limit=3)
                )
                _results = loop.run_until_complete(_future) if not loop.is_running() else None
                if _results:
                    _track_path = _fs_cache / f"{_results[0].sound_id}.mp3"
                    if _asyncio.get_event_loop().run_until_complete(_fs_svc.download(_results[0], _track_path)):
                        return _track_path
        except Exception as _fs_e:
            logger.debug(f"[music] Freesound skipped: {_fs_e}")

    # 4. Fallback: any cached track
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

    # Fallback: pipeline profesional de voice enhancement via FFmpeg
    _noise_gate_db  = os.environ.get("VOICE_NOISE_GATE_THRESHOLD", "-35")
    _presence_boost = os.environ.get("VOICE_PRESENCE_BOOST", "2.5")
    _enhancement_chain = (
        "highpass=f=80,"                                              # Cortar rumble de baja
        f"agate=threshold={_noise_gate_db}dB:ratio=4:attack=5:release=50,"  # Noise gate
        "equalizer=f=200:t=h:w=100:g=-2,"                            # Reducir mud
        f"equalizer=f=3000:t=h:w=1000:g={_presence_boost},"          # Presencia vocal
        "equalizer=f=5000:t=h:w=2000:g=1,"                           # Claridad
        "equalizer=f=8000:t=h:w=3000:g=-1.5,"                        # Reducir harshness
        "acompressor=threshold=-20dB:ratio=3:attack=10:release=100:makeup=2dB,"  # Compresion
        "alimiter=limit=0.95:attack=1:release=10"                     # Prevenir clipping
    )
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-af", _enhancement_chain,
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
    music_volume: float = 0.50,  # 50% volumen base - audible como ambiente con ducking suave
    ducking_enabled: bool = True,
    music_path: Optional[Path] = None,
    word_timings: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Mix a background music track into a video as ambient background.
    Uses ffmpeg for fast, high-quality audio mixing.

    If word_timings is provided and ducking_enabled=True, uses PREDICTIVE ducking
    based on word timestamps (more precise than sidechain).
    Falls back to sidechain ducking if no word_timings are available.

    Returns True on success, False on failure.
    """
    if music_path is None:
        music_path = _get_background_music_path()
    if music_path is None:
        logger.info("No background music tracks found — skipping music mix")
        return False

    logger.info(f"🎵 Mixing background music: {music_path.name} @ {int(music_volume*100)}% volume")
    try:
        if ducking_enabled and word_timings:
            # Ducking PREDICTIVO basado en timestamps de palabras
            from ..services.audio_ducking_service import build_word_aware_ducking_filter
            _ducking_mode = os.environ.get("DUCKING_MODE", "predictive").lower()
            if _ducking_mode == "predictive":
                _voice_ratio      = float(os.environ.get("DUCKING_VOICE_RATIO", "0.80"))
                _long_boost       = float(os.environ.get("DUCKING_LONG_PAUSE_BOOST", "1.25"))
                _short_boost      = float(os.environ.get("DUCKING_SHORT_PAUSE_BOOST", "1.15"))
                ducking_filter = build_word_aware_ducking_filter(
                    words=word_timings,
                    music_base_volume=music_volume,
                    voice_duck_ratio=_voice_ratio,
                    long_pause_boost=_long_boost,
                    short_pause_boost=_short_boost,
                )
                filter_complex = (
                    f"[1:a]{ducking_filter},aloop=loop=-1:size=2000000000[music_ducked];"
                    "[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
                )
                logger.info("[DUCKING] Modo: PREDICTIVO (word timestamps)")
            else:
                # Sidechain cuando se pide explicitamente
                filter_complex = (
                    f"[1:a]volume={music_volume:.3f},aloop=loop=-1:size=2000000000[music_loop];"
                    "[music_loop][0:a]sidechaincompress=threshold=0.08:ratio=2:attack=100:release=600[music_ducked];"  # Muy suave - música ambiente audible
                    "[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
                )
                logger.info("[DUCKING] Modo: SIDECHAIN (reactivo)")
        elif ducking_enabled:
            # Fallback: sidechain cuando no hay word_timings
            filter_complex = (
                f"[1:a]volume={music_volume:.3f},aloop=loop=-1:size=2000000000[music_loop];"
                "[music_loop][0:a]sidechaincompress=threshold=0.08:ratio=2:attack=100:release=600[music_ducked];"  # Muy suave - música ambiente audible
                "[0:a][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
            )
            logger.info("[DUCKING] Modo: SIDECHAIN fallback (sin word_timings)")
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
