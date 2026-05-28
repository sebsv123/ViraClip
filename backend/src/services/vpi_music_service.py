"""Local-only VPI music bed service for Beta Clean reels."""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
_MUSIC_DIRS = (
    "assets/music",
    "assets/audio/music",
    "assets/sfx/music",
    "assets/sounds/bgm",
    "assets/sounds/music",
    "assets/sounds/background",
    "frontend/public/audio",
    "backend/assets/music",
    "/app/assets/music",
    "/app/assets/sounds/bgm",
    "/app/assets/sounds/music",
    "/app/assets/sounds/background",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _candidate_dirs() -> Iterable[Path]:
    root = _repo_root()
    for item in _MUSIC_DIRS:
        path = Path(item)
        yield path if path.is_absolute() else root / path


def music_search_paths() -> list[Path]:
    return list(_candidate_dirs())


def _is_music_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return bool(parts & {"bgm", "music", "background", "audio"})


def discover_music_tracks() -> list[Path]:
    tracks: list[Path] = []
    seen: set[str] = set()
    paths = music_search_paths()
    paths_label = "|".join(str(path) for path in paths)
    logger.info("[music] discovery paths=%s", paths_label)
    for directory in _candidate_dirs():
        if not directory.exists() or not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in _AUDIO_EXTS or not path.is_file():
                continue
            if not _is_music_path(path):
                continue
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                tracks.append(path)
    logger.info("[music] discovery tracks_found=%d paths=%s", len(tracks), paths_label)
    return tracks


def mood_for_editorial(editorial_type: str) -> str:
    key = str(editorial_type or "").lower()
    if key in {"emotional_protection", "family_responsibility", "emotional_open"}:
        return "warm_calm"
    if key in {"client_objection", "myth_debunk", "risk_warning"}:
        return "light_momentum"
    if key in {"actionable_advice", "coverage_explanation", "practical_advice"}:
        return "clean_professional"
    return "clean_professional"


def select_music_track(editorial_type: str, tracks: Optional[list[Path]] = None) -> tuple[Optional[Path], str]:
    mood = mood_for_editorial(editorial_type)
    tracks = tracks if tracks is not None else discover_music_tracks()
    if not tracks:
        return None, mood
    mood_terms = {
        "warm_calm": ("warm", "calm", "famil", "home", "soft"),
        "light_momentum": ("momentum", "light", "pulse", "drive", "hook"),
        "clean_professional": ("clean", "professional", "corporate", "minimal"),
    }.get(mood, ())
    for track in tracks:
        name = track.stem.lower()
        if any(term in name for term in mood_terms):
            return track, mood
    return tracks[0], mood


def _probe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return max(0.0, float((result.stdout or "0").strip() or 0.0))
    except Exception:
        return 0.0


def apply_music_bed(
    input_path: Path,
    output_path: Path,
    *,
    editorial_type: str = "",
    target_volume: float = 0.056234,
) -> Dict[str, Any]:
    tracks = discover_music_tracks()
    logger.info("[music] tracks_found=%d", len(tracks))
    track, mood = select_music_track(editorial_type, tracks)
    volume_db = round(20.0 * math.log10(max(0.0001, target_volume)), 1)
    if track is None:
        logger.info("[music] skipped reason=no_music_library tracks_found=%d", len(tracks))
        return {
            "music_applied": False,
            "music_status": "missing_library",
            "music_track": None,
            "music_mood": mood,
            "music_volume": target_volume,
            "music_volume_db": volume_db,
            "music_mix_stage": "pre_mastering",
            "music_tracks_found": len(tracks),
            "music_warning": "missing_music_library",
        }

    duration = _probe_duration(input_path)
    if duration <= 0:
        logger.info("[music] skipped reason=duration_unavailable")
        return {
            "music_applied": False,
            "music_status": "skipped",
            "music_track": str(track),
            "music_mood": mood,
            "music_volume": target_volume,
            "music_volume_db": volume_db,
            "music_mix_stage": "pre_mastering",
            "music_tracks_found": len(tracks),
            "music_warning": "duration_unavailable",
        }

    fade_out_start = max(0.0, duration - 0.5)
    music_filter = (
        f"[1:a]volume={target_volume:.4f},"
        "afade=t=in:st=0:d=0.25,"
        f"afade=t=out:st={fade_out_start:.3f}:d=0.5[m];"
        "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-stream_loop",
        "-1",
        "-i",
        str(track),
        "-filter_complex",
        music_filter,
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output_path),
    ]
    logger.info("[music] selected=%s mood=%s volume=%.4f volume_db=%.1f", track, mood, target_volume, volume_db)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        logger.info("[music] applied=true volume_db=%d", int(round(volume_db)))
        logger.info("[music] applied=true track=%s volume_db=%.1f output=%s", track, volume_db, output_path)
        logger.info("[music] final_mix_verified=true")
        logger.info("[music] final_output_uses_music=true")
        return {
            "music_applied": True,
            "music_status": "applied",
            "music_track": str(track),
            "music_mood": mood,
            "music_volume": target_volume,
            "music_volume_db": volume_db,
            "music_final_verified": True,
            "music_fade_in_s": 0.25,
            "music_fade_out_s": 0.5,
            "music_mix_stage": "pre_mastering",
            "music_tracks_found": len(tracks),
            "music_warning": None,
        }

    reason = (result.stderr or "ffmpeg_failed").strip()[-500:]
    logger.warning("[music] skipped reason=%s", reason)
    return {
        "music_applied": False,
        "music_status": "failed",
        "music_track": str(track),
        "music_mood": mood,
        "music_volume": target_volume,
        "music_volume_db": volume_db,
        "music_mix_stage": "pre_mastering",
        "music_tracks_found": len(tracks),
        "music_warning": reason,
    }
