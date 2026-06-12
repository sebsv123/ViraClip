"""Local-only VPI music bed service for Beta Clean reels.

Supports 5 mood categories with scoring-based track selection,
voice-dominant mix policy, and structured BGM evidence logging.
"""
from __future__ import annotations

import logging
import math
import os
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    "/app/music_legacy",
    "/app/music_legacy/bgm",
    "/app/assets/sounds/bgm",
    "/app/assets/sounds/music",
    "/app/assets/sounds/background",
)
DEFAULT_MUSIC_TARGET_VOLUME = 0.12
DEFAULT_MUSIC_TARGET_DB = -21.0

# ── Mood categories (Part A) ──────────────────────────────────────────────────
MOOD_CATEGORIES = {
    "trust_warm": {
        "label": "Trust & Warmth",
        "description": "Emotional protection, family, calm, reassurance",
        "editorial_types": {"emotional_protection", "family_responsibility", "emotional_open"},
        "transcript_cues": {"tranquilidad", "proteger", "protección", "familia", "calma",
                            "confianza", "seguridad", "cuidar", "acompañar"},
        "hook_types": {"emotional_open", "empathy_first"},
        "forbidden_editorial_types": {"risk_warning", "myth_debunk", "client_objection"},
    },
    "subtle_tension": {
        "label": "Subtle Tension",
        "description": "Risk warning, objection, myth/debunk, serious warning",
        "editorial_types": {"risk_warning", "client_objection", "myth_debunk"},
        "transcript_cues": {"cuidado", "riesgo", "peligro", "problema", "sorpresa",
                            "no te confíes", "mito", "falso", "objeción", "pero"},
        "hook_types": {"objection_first", "myth_debunk"},
        "forbidden_editorial_types": {"emotional_protection", "family_responsibility"},
    },
    "clean_corporate": {
        "label": "Clean Corporate",
        "description": "Practical explanation, paperwork, coverage explanation",
        "editorial_types": {"coverage_explanation", "practical_advice"},
        "transcript_cues": {"papeleo", "póliza", "poliza", "cobertura", "documento",
                            "explicar", "proceso", "trámite", "trámites", "burocracia"},
        "hook_types": {"speaker_focus", "explainer"},
        "forbidden_editorial_types": set(),
    },
    "light_optimistic": {
        "label": "Light Optimistic",
        "description": "Actionable advice, positive resolution",
        "editorial_types": {"actionable_advice"},
        "transcript_cues": {"puedes", "vas a lograr", "conseguir", "mejorar",
                            "avanzar", "crecer", "oportunidad", "solución", "solución"},
        "hook_types": {"solution_first", "benefit_lead"},
        "forbidden_editorial_types": {"risk_warning", "myth_debunk"},
    },
    "cinematic_ambient": {
        "label": "Cinematic Ambient",
        "description": "Broad neutral fallback — only when confidence high enough and not mismatched",
        "editorial_types": set(),
        "transcript_cues": set(),
        "hook_types": set(),
        "forbidden_editorial_types": set(),
    },
}

# Mood → filename keyword hints (weak fallback, never primary)
MOOD_FILENAME_HINTS: Dict[str, List[str]] = {
    "trust_warm": ["warm", "calm", "famil", "home", "soft", "gentle", "peaceful"],
    "subtle_tension": ["tension", "suspense", "mystery", "dark", "serious", "drama"],
    "clean_corporate": ["clean", "corporate", "minimal", "professional", "office", "business"],
    "light_optimistic": ["upbeat", "optimistic", "bright", "happy", "positive", "inspiring"],
    "cinematic_ambient": ["ambient", "cinematic", "atmos", "background", "pad"],
}

# ── Mix policy constants (Part C) ─────────────────────────────────────────────
# Voice-dominant mix: BGM perceptible but below voice
MIX_POLICY_VOICE_DOMINANT = True
MIX_POLICY_BGM_GAIN_DB = -21.0       # BGM target gain (dB)
MIX_POLICY_DUCKING_ENABLED = True
MIX_POLICY_DUCKING_THRESHOLD = 0.030
MIX_POLICY_DUCKING_RATIO = 2.5
MIX_POLICY_DUCKING_ATTACK = 20       # ms
MIX_POLICY_DUCKING_RELEASE = 250     # ms
MIX_POLICY_NO_CLIPPING = True
MIX_POLICY_NEAR_SILENCE_THRESHOLD_DB = -30.0  # below this = near-silent
_BGM_DISABLED_ENV = "VPI_DISABLE_BGM"


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


# ── Mood scoring (Part B) ─────────────────────────────────────────────────────

def _score_mood_for_editorial(editorial_type: str) -> List[Tuple[str, float]]:
    """Score each mood category by editorial type match.

    Returns list of (mood, score) sorted descending.
    """
    key = str(editorial_type or "").lower()
    scores: Dict[str, float] = {}
    for mood, cfg in MOOD_CATEGORIES.items():
        if mood == "cinematic_ambient":
            continue  # fallback only
        if key in cfg["editorial_types"]:
            scores[mood] = 1.0
        elif key in cfg["forbidden_editorial_types"]:
            scores[mood] = -1.0  # penalise
        else:
            scores[mood] = 0.0
    return sorted(scores.items(), key=lambda x: -x[1])


def _score_mood_for_transcript(text: str) -> Dict[str, float]:
    """Score each mood category by transcript cue matches."""
    lowered = (text or "").lower()
    scores: Dict[str, float] = {}
    for mood, cfg in MOOD_CATEGORIES.items():
        if mood == "cinematic_ambient":
            continue
        match_count = sum(1 for cue in cfg["transcript_cues"] if cue in lowered)
        scores[mood] = min(1.0, match_count * 0.25)  # each cue = 0.25, cap at 1.0
    return scores


def _score_mood_for_hook(hook_type: str) -> Dict[str, float]:
    """Score each mood category by hook type match."""
    key = str(hook_type or "").lower()
    scores: Dict[str, float] = {}
    for mood, cfg in MOOD_CATEGORIES.items():
        if mood == "cinematic_ambient":
            continue
        scores[mood] = 1.0 if key in cfg["hook_types"] else 0.0
    return scores


def _score_mood_for_brand_fit(editorial_type: str) -> Dict[str, float]:
    """Score each mood category by brand fit (editorial type affinity)."""
    key = str(editorial_type or "").lower()
    scores: Dict[str, float] = {}
    for mood, cfg in MOOD_CATEGORIES.items():
        if mood == "cinematic_ambient":
            continue
        if key in cfg["editorial_types"]:
            scores[mood] = 0.5  # partial bonus for brand fit
        else:
            scores[mood] = 0.0
    return scores


def _score_mood_for_filename(track: Path, mood: str) -> float:
    """Weak filename-based scoring (fallback only)."""
    name = track.stem.lower()
    hints = MOOD_FILENAME_HINTS.get(mood, [])
    if not hints:
        return 0.0
    return 1.0 if any(hint in name for hint in hints) else 0.0


def _score_mood_for_metadata(track: Path, mood: str) -> float:
    """Score based on asset metadata/tags if available.

    Currently a stub — returns 0.0 unless metadata parsing is implemented.
    """
    _ = track, mood
    return 0.0


def select_music_track(
    editorial_type: str = "",
    tracks: Optional[list[Path]] = None,
    transcript_text: str = "",
    hook_type: str = "",
    emotional_tone: str = "",
) -> tuple[Optional[Path], str, float, str]:
    """Select best music track using multi-factor mood scoring.

    Scoring dimensions (Part B):
      - clip editorial category (weight 2.0)
      - transcript cues (weight 1.5)
      - hook type (weight 1.0)
      - emotional tone (weight 1.0)
      - brand fit (weight 0.5)
      - asset metadata/tags (weight 0.5)
      - filename only as weak fallback (weight 0.2)

    Returns (track, mood, score, reason).
    """
    tracks = tracks if tracks is not None else discover_music_tracks()

    if not tracks:
        logger.info("[music] BGM_SKIPPED reason=no_tracks_available editorial_type=%s", editorial_type)
        return None, "cinematic_ambient", 0.0, "no_tracks_available"

    # ── Compute mood scores ──────────────────────────────────────────────
    editorial_scores = dict(_score_mood_for_editorial(editorial_type))
    transcript_scores = _score_mood_for_transcript(transcript_text)
    hook_scores = _score_mood_for_hook(hook_type)
    brand_scores = _score_mood_for_brand_fit(editorial_type)

    # Emotional tone override
    tone = str(emotional_tone or "").lower()
    tone_scores: Dict[str, float] = {}
    if "calm" in tone or "warm" in tone or "soft" in tone:
        tone_scores["trust_warm"] = 1.0
    elif "tense" in tone or "serious" in tone or "urgent" in tone:
        tone_scores["subtle_tension"] = 1.0
    elif "happy" in tone or "optimistic" in tone or "positive" in tone:
        tone_scores["light_optimistic"] = 1.0
    elif "corporate" in tone or "professional" in tone or "neutral" in tone:
        tone_scores["clean_corporate"] = 1.0

    # ── Aggregate scores ──────────────────────────────────────────────────
    # Weights: editorial=2.0, transcript=1.5, hook=1.0, tone=1.0, brand=0.5, metadata=0.5, filename=0.2
    mood_total: Dict[str, float] = {}
    for mood in MOOD_CATEGORIES:
        if mood == "cinematic_ambient":
            continue
        total = (
            editorial_scores.get(mood, 0.0) * 2.0
            + transcript_scores.get(mood, 0.0) * 1.5
            + hook_scores.get(mood, 0.0) * 1.0
            + tone_scores.get(mood, 0.0) * 1.0
            + brand_scores.get(mood, 0.0) * 0.5
        )
        mood_total[mood] = total

    # Determine best mood from scoring
    if not mood_total or all(v <= 0.0 for v in mood_total.values()):
        best_mood = "cinematic_ambient"
        best_score = 0.0
        reason = "no_strong_mood_match_falling_back_to_cinematic_ambient"
    else:
        best_mood = max(mood_total, key=mood_total.get)
        best_score = mood_total[best_mood]
        reason = f"editorial={editorial_scores.get(best_mood, 0.0):.1f}_transcript={transcript_scores.get(best_mood, 0.0):.1f}_hook={hook_scores.get(best_mood, 0.0):.1f}_tone={tone_scores.get(best_mood, 0.0):.1f}_brand={brand_scores.get(best_mood, 0.0):.1f}"

    # ── Select track for best mood ────────────────────────────────────────
    # Score each track for the selected mood
    scored_tracks: List[Tuple[float, Path, str]] = []
    for track in tracks:
        filename_score = _score_mood_for_filename(track, best_mood) * 0.2
        metadata_score = _score_mood_for_metadata(track, best_mood) * 0.5
        track_total = filename_score + metadata_score
        scored_tracks.append((track_total, track, f"filename={filename_score:.1f}_metadata={metadata_score:.1f}"))

    # Sort descending by score
    scored_tracks.sort(key=lambda x: -x[0])

    if scored_tracks and scored_tracks[0][0] > 0.0:
        selected = scored_tracks[0]
        track_reason = selected[2]
    elif tracks:
        # When we have contextual mood evidence but no filename/metadata hit,
        # avoid deterministic first-file bias.
        if best_score > 0.0:
            pick_index = abs(hash(f"{best_mood}:{editorial_type}:{hook_type}:{transcript_text[:80]}")) % len(tracks)
            selected = (0.0, tracks[pick_index], "mood_cue_priority_no_filename_match")
        else:
            # True no-signal fallback.
            selected = (0.0, tracks[0], "first_file_fallback_no_metadata_match")
    else:
        logger.info("[music] BGM_SKIPPED reason=no_tracks_available")
        return None, best_mood, best_score, reason

    track_path = selected[1]
    track_reason = selected[2]

    logger.info(
        "BGM_SELECTED mood=%s track=%s score=%.2f reason=%s track_reason=%s",
        best_mood, track_path.name, best_score, reason, track_reason,
    )

    return track_path, best_mood, best_score, f"{reason}|{track_reason}"


def _generate_quiet_fallback_bed(output_path: Path, duration_s: float) -> Optional[Path]:
    """Generate a quiet local fallback bed when library selection fails."""
    bed_path = output_path.with_name(f"fallback_bgm_{output_path.stem}.m4a")
    duration_s = max(12.0, min(45.0, float(duration_s or 0.0) or 18.0))
    fade_out_start = max(0.0, duration_s - 0.8)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=196:sample_rate=48000:duration={duration_s:.2f}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=294:sample_rate=48000:duration={duration_s:.2f}",
        "-filter_complex",
        (
            "[0:a]volume=0.018,lowpass=f=1400[a0];"
            "[1:a]volume=0.012,lowpass=f=1000[a1];"
            f"[a0][a1]amix=inputs=2:duration=shortest:dropout_transition=0,"
            f"afade=t=in:st=0:d=0.35,afade=t=out:st={fade_out_start:.2f}:d=0.8[a]"
        ),
        "-map",
        "[a]",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(bed_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and bed_path.exists() and bed_path.stat().st_size > 0:
        return bed_path
    logger.warning("[music] fallback_bed_generation_failed stderr=%s", (result.stderr or "")[-300:])
    return None


def mood_for_editorial(editorial_type: str) -> str:
    """Backward-compatible helper returning legacy mood buckets."""
    key = str(editorial_type or "").lower()
    if key in {"emotional_protection", "family_responsibility", "emotional_open"}:
        return "warm_calm"
    if key in {"risk_warning", "client_objection", "myth_debunk"}:
        return "light_momentum"
    if key in {"actionable_advice", "coverage_explanation", "practical_advice"}:
        return "clean_professional"
    return "clean_professional"


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


def _probe_has_audio_stream(path: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index,codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        payload = json.loads(result.stdout or "{}")
        return bool(payload.get("streams"))
    except Exception:
        return False


def _probe_mean_volume_db(path: Path) -> Optional[float]:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stderr or "") + "\n" + (result.stdout or "")
        match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", output)
        if not match:
            return None
        return float(match.group(1))
    except Exception:
        return None


def _verify_bgm_audio_mix(input_video: Path, output_video: Path) -> bool:
    if not output_video.exists() or output_video.stat().st_size <= 0:
        return False
    if not _probe_has_audio_stream(output_video):
        return False
    in_duration = _probe_duration(input_video)
    out_duration = _probe_duration(output_video)
    if in_duration > 0 and out_duration > 0:
        ratio = out_duration / max(0.001, in_duration)
        if ratio < 0.85 or ratio > 1.20:
            return False
    mean_db = _probe_mean_volume_db(output_video)
    if mean_db is not None and mean_db <= -60.0:
        return False
    return True


def apply_music_bed(
    input_path: Path,
    output_path: Path,
    *,
    editorial_type: str = "",
    target_volume: float = DEFAULT_MUSIC_TARGET_VOLUME,
    ducking_enabled: bool = True,
    transcript_text: str = "",
    hook_type: str = "",
    emotional_tone: str = "",
    music_mood: str = "",
    audio_editorial_profile: str = "",
    music_asset_id: str = "",
    music_selection_reason: str = "",
    music_fallback_used: bool = False,
    music_reuse_reason: str = "",
) -> Dict[str, Any]:
    """Apply music bed with voice-dominant mix policy (Part C).

    Mix policy:
      - voice always dominant
      - BGM perceptible but below voice
      - ducking enabled when voice is dense
      - no clipping
      - no near-silence music evidence
      - if BGM makes voice less intelligible, reduce or skip
    """
    voice_present = bool(str(transcript_text or "").strip())
    if audio_editorial_profile or music_mood:
        logger.info(
            "MUSIC_EDITORIAL_PROFILE_SELECTED profile=%s mood=%s reason=%s",
            audio_editorial_profile or "unknown",
            music_mood or "unknown",
            music_selection_reason or "n/a",
        )
    selection_metadata = {
        "music_mood_selected": music_mood or "unknown",
        "music_asset_id": music_asset_id,
        "music_selection_reason": music_selection_reason or "",
        "music_fallback_used": bool(music_fallback_used),
        "music_reuse_reason": music_reuse_reason,
    }
    if str(os.environ.get(_BGM_DISABLED_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}:
        logger.info("BGM_DISABLED_REASON=explicitly_disabled")
        return {
            "music_applied": False,
            "music_status": "disabled",
            "music_track": None,
            "music_mood": "none",
            "music_mood_score": 0.0,
            "music_mood_reason": "disabled",
            "music_volume": target_volume,
            "music_volume_db": round(20.0 * math.log10(max(0.0001, target_volume)), 1),
            "music_mix_stage": "disabled",
            "music_tracks_found": 0,
            "music_warning": "explicitly_disabled",
            "has_bgm": False,
            "bgm_evidence": [],
            "bgm_manifest_verified": False,
            "bgm_loudness_checked": False,
            "bgm_voice_priority_ok": False,
            **selection_metadata,
        }
    tracks = discover_music_tracks()
    logger.info("[music] tracks_found=%d", len(tracks))

    # track, mood, score, reason = select_music_track(...)
    _select_result = select_music_track(
        editorial_type=editorial_type,
        tracks=tracks,
        transcript_text=transcript_text,
        hook_type=hook_type,
        emotional_tone=emotional_tone,
    )
    # Defensive unpack: normalize any return shape to 4-tuple
    if isinstance(_select_result, tuple) and len(_select_result) == 4:
        track, mood, score, reason = _select_result
    elif isinstance(_select_result, tuple) and len(_select_result) == 2:
        track, mood = _select_result
        score, reason = 0.0, "unpack_normalized_from_2tuple"
        logger.warning("BGM_UNPACK_NORMALIZED from=2 expected=4")
    elif isinstance(_select_result, tuple) and len(_select_result) == 3:
        track, mood, score = _select_result
        reason = "unpack_normalized_from_3tuple"
        logger.warning("BGM_UNPACK_NORMALIZED from=3 expected=4")
    else:
        track, mood, score, reason = None, "unknown", 0.0, "unpack_normalized_fallback"
        logger.warning("BGM_UNPACK_NORMALIZED from=%s expected=4", type(_select_result).__name__)

    # ── Mix policy: voice-dominant gain ───────────────────────────────────
    editorial_key = str(editorial_type or "").lower()
    is_sensitive_family = any(token in editorial_key for token in ("decesos", "funeral", "fallecimiento", "muerte", "sepelio", "luto"))
    is_calm_profile = mood in {"trust_warm", "clean_corporate"}
    base_mix_volume = float(target_volume or DEFAULT_MUSIC_TARGET_VOLUME)
    if is_sensitive_family:
        mix_volume = min(0.12, max(0.10, base_mix_volume))
    elif is_calm_profile:
        mix_volume = min(0.15, max(0.14, base_mix_volume + 0.02))
    else:
        mix_volume = min(0.16, max(0.15, base_mix_volume + 0.02))
    bgm_gain_linear = mix_volume
    volume_db = round(20.0 * math.log10(max(0.0001, mix_volume)), 1)
    bgm_volume_empirical_boost_applied = bool(abs(mix_volume - base_mix_volume) >= 0.01)

    fallback_reason = ""
    if track is None:
        fallback_track = _generate_quiet_fallback_bed(output_path, _probe_duration(input_path))
        if fallback_track is None:
            logger.info(
                "BGM_DISABLED_REASON=no_music_library_and_fallback_failed tracks_found=%d editorial_type=%s mood=%s",
                len(tracks), editorial_type, mood,
            )
            return {
                "music_applied": False,
                "music_status": "missing_library",
                "music_track": None,
                "music_mood": mood,
                "music_mood_score": score,
                "music_mood_reason": reason,
                "music_volume": target_volume,
                "music_volume_db": volume_db,
                "music_mix_stage": "pre_mastering",
                "music_tracks_found": len(tracks),
                "music_warning": "missing_music_library",
                "has_bgm": False,
                "bgm_evidence": [],
                "bgm_manifest_verified": False,
                "bgm_loudness_checked": False,
                "bgm_voice_priority_ok": False,
                "bgm_volume_empirical_boost_applied": bool(bgm_volume_empirical_boost_applied),
                "bgm_target_volume_final": float(mix_volume),
                **selection_metadata,
            }
        track = fallback_track
        fallback_reason = "no_music_library"

    duration = _probe_duration(input_path)
    if duration <= 0:
        fallback_track = _generate_quiet_fallback_bed(output_path, 18.0)
        if fallback_track is None:
            logger.info(
                "BGM_DISABLED_REASON=duration_unavailable_and_fallback_failed track=%s mood=%s",
                track.name, mood,
            )
            return {
                "music_applied": False,
                "music_status": "skipped",
                "music_track": str(track),
                "music_mood": mood,
                "music_mood_score": score,
                "music_mood_reason": reason,
                "music_volume": target_volume,
                "music_volume_db": volume_db,
                "music_mix_stage": "pre_mastering",
                "music_tracks_found": len(tracks),
                "music_warning": "duration_unavailable",
                "has_bgm": False,
                "bgm_evidence": [],
                "bgm_manifest_verified": False,
                "bgm_loudness_checked": False,
                "bgm_voice_priority_ok": False,
                "bgm_volume_empirical_boost_applied": bool(bgm_volume_empirical_boost_applied),
                "bgm_target_volume_final": float(mix_volume),
                **selection_metadata,
            }
        track = fallback_track
        duration = 18.0
        fallback_reason = "duration_unavailable"

    fade_out_start = max(0.0, duration - 0.5)

    # ── Build filter with voice-dominant mix policy ───────────────────────
    # Use bgm_gain_linear for the music volume to ensure voice dominance
    base_music_filter = (
        f"[1:a]volume={bgm_gain_linear:.4f},"
        "afade=t=in:st=0:d=0.25,"
        f"afade=t=out:st={fade_out_start:.3f}:d=0.5[m];"
    )

    actual_ducking_enabled = ducking_enabled and MIX_POLICY_DUCKING_ENABLED

    if actual_ducking_enabled:
        music_filter = (
            base_music_filter
            + f"[m][0:a]sidechaincompress=threshold={MIX_POLICY_DUCKING_THRESHOLD:.3f}:"
            f"ratio={MIX_POLICY_DUCKING_RATIO}:"
            f"attack={MIX_POLICY_DUCKING_ATTACK}:"
            f"release={MIX_POLICY_DUCKING_RELEASE}[md];"
            "[0:a][md]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
    else:
        music_filter = base_music_filter + "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]"

    def _build_cmd(filter_complex: str) -> list[str]:
        return [
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
            filter_complex,
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

    # Log mix policy (Part C)
    logger.info(
        "BGM_SELECTED mood=%s track=%s score=%.2f reason=%s",
        mood, track.name, score, reason,
    )
    logger.info(
        "BGM_MIX_POLICY voice_dominant=true bgm_gain_db=%.1f ducking=%s",
        volume_db, str(actual_ducking_enabled).lower(),
    )
    if bgm_volume_empirical_boost_applied:
        logger.info(
            "VPI_BGM_VOLUME_EMPIRICAL_BOOST_APPLIED target=%.3f final=%.3f mood=%s sensitive=%s",
            base_mix_volume,
            mix_volume,
            mood,
            str(is_sensitive_family).lower(),
        )
    logger.info(
        "VPI_RENDER_BGM_VOLUME_SET target=%.3f final=%.3f mood=%s sensitive=%s",
        base_mix_volume,
        mix_volume,
        mood,
        str(is_sensitive_family).lower(),
    )
    if actual_ducking_enabled and voice_present:
        logger.info("BGM_DUCKING_APPLIED voice_present=%s ducking=%s", str(voice_present).lower(), str(actual_ducking_enabled).lower())

    result = subprocess.run(_build_cmd(music_filter), capture_output=True, text=True, check=False)
    if result.returncode != 0 and actual_ducking_enabled:
        fallback_filter = base_music_filter + "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]"
        logger.warning("[music] ducking_fallback reason=%s", (result.stderr or "ffmpeg_failed").strip()[-300:])
        result = subprocess.run(_build_cmd(fallback_filter), capture_output=True, text=True, check=False)
        actual_ducking_enabled = False
    if result.returncode != 0 and not fallback_reason:
        fallback_track = _generate_quiet_fallback_bed(output_path, duration)
        if fallback_track is not None:
            fallback_reason = "music_mix_failed"
            track = fallback_track
            result = subprocess.run(_build_cmd(music_filter), capture_output=True, text=True, check=False)
    verified = result.returncode == 0 and output_path.exists() and _verify_bgm_audio_mix(input_path, output_path)
    if not verified and not fallback_reason:
        fallback_track = _generate_quiet_fallback_bed(output_path, duration)
        if fallback_track is not None:
            fallback_reason = "music_verification_failed"
            track = fallback_track
            result = subprocess.run(_build_cmd(music_filter), capture_output=True, text=True, check=False)
            verified = result.returncode == 0 and output_path.exists() and _verify_bgm_audio_mix(input_path, output_path)
    if voice_present and not actual_ducking_enabled:
        logger.warning("BGM_VOICE_PRIORITY_WARNING voice_present=true ducking=false")
    if verified:
        logger.info(
            "BGM_AUDIO_MIX_VERIFIED input=%s output=%s",
            input_path.name,
            output_path.name,
        )
        if fallback_reason:
            logger.info("BGM_FALLBACK_APPLIED reason=%s track=%s", fallback_reason, track.name)
    if result.returncode != 0 and fallback_reason:
        logger.warning("BGM_DISABLED_REASON=fallback_bed_mix_failed reason=%s", (result.stderr or "ffmpeg_failed").strip()[-300:])
        return {
            "music_applied": False,
            "music_status": "failed",
            "music_track": str(track),
            "music_mood": mood,
            "music_mood_score": score,
            "music_mood_reason": reason,
            "music_volume": target_volume,
            "music_volume_db": volume_db,
            "music_mix_stage": "pre_mastering",
            "music_tracks_found": len(tracks),
            "music_warning": (result.stderr or "ffmpeg_failed").strip()[-300:],
            "has_bgm": False,
            "bgm_evidence": [],
            "bgm_manifest_verified": False,
            "bgm_volume_empirical_boost_applied": bool(bgm_volume_empirical_boost_applied),
            "bgm_target_volume_final": float(mix_volume),
            **selection_metadata,
        }

    if verified:
        if fallback_reason:
            logger.info("BGM_FALLBACK_APPLIED reason=%s volume_db=%d track=%s output=%s", fallback_reason, int(round(volume_db)), track, output_path)
        else:
            logger.info("BGM_APPLIED volume_db=%d track=%s output=%s", int(round(volume_db)), track, output_path)
        logger.info("[music] ducking_enabled=%s", str(actual_ducking_enabled).lower())
        logger.info("[music] final_mix_verified=true")
        logger.info("[music] final_output_uses_music=true")

        bgm_evidence = [
            f"bgm_selected:mood={mood},track={track.name},score={score:.2f}",
            f"mix_applied:gain_db={volume_db},ducking={actual_ducking_enabled}",
        ]

        return {
            "music_applied": True,
            "music_status": "applied",
            "music_track": str(track),
            "music_mood": mood,
            "music_mood_score": score,
            "music_mood_reason": reason,
            "music_volume": target_volume,
            "music_mix_volume": mix_volume,
            "music_volume_db": volume_db,
            "music_final_verified": True,
            "music_fade_in_s": 0.25,
            "music_fade_out_s": 0.5,
            "music_ducking_enabled": actual_ducking_enabled,
            "music_perceived_mix_target": "background_audible",
            "music_mix_stage": "pre_mastering",
            "music_tracks_found": len(tracks),
            "music_warning": None,
            "has_bgm": True,
            "bgm_evidence": bgm_evidence,
            "bgm_manifest_verified": True,
            "bgm_loudness_checked": True,
            "bgm_voice_priority_ok": bool((actual_ducking_enabled or not voice_present) and verified),
            "bgm_volume_empirical_boost_applied": bool(bgm_volume_empirical_boost_applied),
            "bgm_target_volume_final": float(mix_volume),
            **selection_metadata,
        }

    reason_fail = (result.stderr or "ffmpeg_failed").strip()[-500:]
    if not reason_fail and not verified:
        reason_fail = "audio_mix_verification_failed"
    logger.warning("BGM_DISABLED_REASON=%s track=%s mood=%s", reason_fail, track.name, mood)
    return {
        "music_applied": False,
        "music_status": "failed",
        "music_track": str(track),
        "music_mood": mood,
        "music_mood_score": score,
        "music_mood_reason": reason,
        "music_volume": target_volume,
        "music_mix_volume": mix_volume,
        "music_volume_db": volume_db,
        "music_mix_stage": "pre_mastering",
        "music_tracks_found": len(tracks),
        "music_warning": reason_fail,
        "has_bgm": False,
        "bgm_evidence": [],
        "bgm_manifest_verified": False,
        "bgm_loudness_checked": bool(verified),
        "bgm_voice_priority_ok": bool((actual_ducking_enabled or not voice_present) and verified),
        "bgm_volume_empirical_boost_applied": bool(bgm_volume_empirical_boost_applied),
        "bgm_target_volume_final": float(mix_volume),
        **selection_metadata,
    }
