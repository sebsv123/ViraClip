"""
Beat-Sync BGM Service — librosa BPM Detection + Auto BGM Selection
===================================================================

Detects BPM from the video audio track, then:
  1. Selects the closest-matching BGM track from the local library
  2. Optionally time-stretches the BGM to match the video BPM exactly
  3. Mixes the BGM with adaptive ducking during speech segments

BPM ranges (matching BackgroundMusicService track IDs):
  slow      : 60-75  BPM  (chill, lo-fi, ambient)
  midtempo  : 76-95  BPM  (pop, R&B, hip-hop)
  upbeat    : 96-115 BPM  (energetic pop, funk)
  hype      : 116-140 BPM (EDM, trap, high-energy)
  fast      : 141+   BPM  (drum & bass, fast EDM)

Inspired by:
  https://github.com/librosa/librosa/blob/main/examples/plot_beat_track.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BGM_LIBRARY_DIR = Path(os.environ.get("BGM_LIBRARY_DIR", "/app/assets/sounds/bgm"))
SFX_LIBRARY_DIR = Path(os.environ.get("SFX_LIBRARY_DIR", "/app/sfx_library"))

_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}


# ── BPM Range helper ──────────────────────────────────────────────────────────

def bpm_category(bpm: float) -> str:
    if bpm < 76:
        return "slow"
    if bpm < 96:
        return "midtempo"
    if bpm < 116:
        return "upbeat"
    if bpm < 141:
        return "hype"
    return "fast"


def bpm_distance(a: float, b: float) -> float:
    """Tempo-aware distance: 2× BPM is a valid double-time match."""
    direct = abs(a - b)
    double = abs(a - b * 2)
    half   = abs(a - b * 0.5)
    return min(direct, double, half)


# ── BGM library index ─────────────────────────────────────────────────────────

@dataclass
class BGMTrack:
    path: Path
    bpm: float = 0.0
    category: str = "unknown"
    duration: float = 0.0

    @property
    def name(self) -> str:
        return self.path.stem


def _scan_bgm_library(directory: Path) -> List[BGMTrack]:
    """Scan directory for audio files and return BGMTrack list."""
    tracks = []
    if not directory.exists():
        return tracks
    for f in directory.rglob("*"):
        if f.suffix.lower() in _AUDIO_EXTS:
            tracks.append(BGMTrack(path=f))
    return tracks


def _estimate_bpm_from_filename(name: str) -> float:
    """Extract BPM from filename patterns like '95bpm_chill.mp3' or 'lo-fi-80.mp3'."""
    import re
    m = re.search(r"(\d{2,3})\s*bpm", name, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r"[-_](\d{2,3})[-_]", name)
    if m:
        v = float(m.group(1))
        if 60 <= v <= 200:
            return v
    return 0.0


# ── BPM Analysis ──────────────────────────────────────────────────────────────

def analyse_bpm(audio_path: Path, duration: float = 60.0, bgm_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Detect BPM and beat timestamps from an audio file using librosa.

    Args:
        audio_path: Path to audio or video file (used as fallback if bgm_path is None).
        duration:   Max seconds to analyse (first N seconds for speed).
        bgm_path:   Optional path to BGM file. If provided, BPM is detected from
                    the BGM (music beats) instead of the clip audio (voice pauses),
                    so zoom punches align with music beats rather than silence gaps.

    Returns:
        {
          "bpm": float,
          "beat_times": [float, ...],  # timestamps of beat onsets (seconds)
          "category": str,
          "confidence": float (0-1),
        }
    """
    from src.core.feature_flags import FEATURE_FLAGS
    if not FEATURE_FLAGS.get("beat_sync_librosa", True):
        logger.info("[BeatSync] librosa unavailable — using FFmpeg tempo estimate")
        return {"bpm": 120.0, "beat_times": [], "category": "unknown", "confidence": 0.0}

    from src.core.feature_flags import FEATURE_FLAGS
    if not FEATURE_FLAGS.get("beat_sync_librosa", True):
        logger.info("[BeatSync] librosa unavailable — using FFmpeg tempo estimate")
        return {"bpm": 120.0, "beat_times": [], "category": "unknown", "confidence": 0.0}

    try:
        import librosa

        # Prefer BGM audio for beat detection so zooms align with music, not voice pauses
        _source = bgm_path if bgm_path else audio_path
        y, sr = librosa.load(str(_source), sr=22050, mono=True,
                             duration=duration, res_type="kaiser_fast")

        # Onset-strength envelope for more robust tempo
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo_arr, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, trim=False
        )
        # librosa ≥ 0.10 returns array; take scalar
        bpm = float(np.asarray(tempo_arr).flat[0]) if hasattr(tempo_arr, "__len__") else float(tempo_arr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        # Confidence: how consistent is the inter-beat interval?
        if len(beat_times) > 4:
            ibis = [beat_times[i+1] - beat_times[i] for i in range(len(beat_times)-1)]
            mean_ibi = sum(ibis) / len(ibis)
            variance = sum((x - mean_ibi) ** 2 for x in ibis) / len(ibis)
            confidence = max(0.0, min(1.0, 1.0 - (variance ** 0.5) / max(mean_ibi, 0.001)))
        else:
            confidence = 0.5

        return {
            "bpm": round(bpm, 1),
            "beat_times": [round(t, 3) for t in beat_times[:200]],
            "category": bpm_category(bpm),
            "confidence": round(confidence, 3),
        }

    except ImportError:
        logger.warning("[beat_sync] librosa not available — using FFmpeg tempo estimate")
        return _ffprobe_bpm_estimate(audio_path)
    except Exception as exc:
        logger.warning("[beat_sync] BPM analysis failed: %s", exc)
        return {"bpm": 95.0, "beat_times": [], "category": "midtempo", "confidence": 0.0}


def _ffprobe_bpm_estimate(audio_path: Path) -> Dict[str, Any]:
    """Fallback: use ffprobe metadata BPM tag if present."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(audio_path)],
            capture_output=True, text=True, timeout=10
        )
        import json
        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})
        for key in ("bpm", "BPM", "TBPM"):
            if key in tags:
                bpm = float(tags[key])
                return {"bpm": bpm, "beat_times": [], "category": bpm_category(bpm), "confidence": 0.3}
    except Exception:
        pass
    return {"bpm": 95.0, "beat_times": [], "category": "midtempo", "confidence": 0.0}


try:
    import numpy as np
except ImportError:
    import types
    np = types.SimpleNamespace(asarray=lambda x: x)  # type: ignore


# ── BGM selection ─────────────────────────────────────────────────────────────

def select_bgm(
    target_bpm: float,
    tracks: Optional[List[BGMTrack]] = None,
    prefer_category: Optional[str] = None,
) -> Optional[BGMTrack]:
    """
    Pick the best-matching BGM track for a target BPM.

    Priority:
      1. Exact category match + smallest BPM distance
      2. Any track with smallest BPM distance
    """
    if tracks is None:
        tracks = _scan_bgm_library(BGM_LIBRARY_DIR)

    if not tracks:
        return None

    # Fill in BPM from filename where not yet set
    for t in tracks:
        if t.bpm == 0.0:
            t.bpm = _estimate_bpm_from_filename(t.name)
        if t.bpm == 0.0:
            t.bpm = 95.0   # default midtempo
        if t.category == "unknown":
            t.category = bpm_category(t.bpm)

    target_cat = prefer_category or bpm_category(target_bpm)
    cat_tracks  = [t for t in tracks if t.category == target_cat]
    pool        = cat_tracks if cat_tracks else tracks

    return min(pool, key=lambda t: bpm_distance(target_bpm, t.bpm))


# ── BGM mix with beat-sync intro ──────────────────────────────────────────────

async def mix_bgm_beat_synced(
    video_path: Path,
    output_path: Path,
    bgm_path: Optional[Path] = None,
    target_bpm: Optional[float] = None,
    speech_segments: Optional[List[Dict[str, Any]]] = None,
    bgm_volume: float = 0.15,
    fade_in: float = 1.5,
    fade_out: float = 2.0,
    preferred_category: Optional[str] = None,
    word_timings: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Mix beat-synced BGM into a video.

    1. If target_bpm is None, analyse the video audio for BPM.
    2. Select the closest BGM track from the library (or use supplied bgm_path).
    3. Build an adaptive volume envelope: low during speech, louder in gaps.
    4. Run FFmpeg amix.

    Returns a result dict with bpm, track used, and success flag.
    """
    # Step 1: BPM analysis
    bpm_info: Dict[str, Any] = {"bpm": target_bpm or 95.0, "beat_times": [], "confidence": 0.0}
    if target_bpm is None:
        try:
            bpm_info = await asyncio.get_event_loop().run_in_executor(
                None, analyse_bpm, video_path, 30.0
            )
        except Exception as e:
            logger.warning("[beat_sync] BPM analysis skipped: %s", e)

    bpm = bpm_info["bpm"]
    logger.info("[beat_sync] Target BPM=%.1f (%s)", bpm, bpm_info.get("category", "?"))

    # Step 2: BGM selection
    if bgm_path is None:
        tracks = _scan_bgm_library(BGM_LIBRARY_DIR)
        track = select_bgm(bpm, tracks, prefer_category=preferred_category)
        if track:
            bgm_path = track.path
            logger.info("[beat_sync] Selected BGM: %s (%.1f BPM)", track.name, track.bpm)
        else:
            logger.warning("[beat_sync] No BGM tracks found in %s", BGM_LIBRARY_DIR)
            return {"success": False, "bpm": bpm, "reason": "no bgm tracks found"}

    # Step 3: Build volume filter — SIMPLIFICADO
    # El ducking predictivo con expresiones FFmpeg complejas
    # (volume=eval=frame:expr='if(gte...') causa errores de parsing
    # porque FFmpeg no soporta paréntesis anidados ni comas dentro
    # de filter_complex option values.
    #
    # Usamos volumen constante. El smart_audio en creative_pipeline
    # Step 7 maneja el ducking real.
    vol_filter = f"volume={bgm_volume}"
    logger.info(f"[beat_sync] Volumen constante: {bgm_volume} (ducking delegado a smart_audio)")

    # Step 4: FFmpeg amix
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-i", str(bgm_path),
            "-filter_complex",
            f"[1:a]{vol_filter}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode != 0:
            logger.error("[beat_sync] FFmpeg mix failed: %s", stderr.decode()[-400:])
            return {"success": False, "bpm": bpm, "reason": stderr.decode()[-200:]}

        logger.info("[beat_sync] BGM mixed → %s", output_path.name)
        return {
            "success": True,
            "bpm": bpm,
            "category": bpm_info.get("category", "midtempo"),
            "beat_count": len(bpm_info.get("beat_times", [])),
            "bgm_used": str(bgm_path),
            "confidence": bpm_info.get("confidence", 0.0),
        }

    except (asyncio.TimeoutError, Exception) as exc:
        logger.error("[beat_sync] mix_bgm_beat_synced error: %s", exc)
        return {"success": False, "bpm": bpm, "reason": str(exc)}


def _build_speech_duck_filter(
    speech_segments: List[Dict[str, Any]],
    base_vol: float,
    fade_in: float,
    fade_out: float,
) -> str:
    """
    Build an FFmpeg audio volume filter that:
      - Fades in at the start
      - Applies consistent base volume (no complex ducking that causes noise)
      - Fades out at the end
    
    NOTE: Complex if/between expressions with many segments cause white noise.
    Simplified to use consistent volume with smooth fades only.
    """
    # Cap volume to prevent distortion
    safe_vol = min(base_vol, 0.50)
    
    # Simple: fade in, constant volume, fade out
    # Volume curve: music always present at audible level
    return (
        f"afade=t=in:st=0:d={fade_in},"
        f"volume={safe_vol},"
        f"afade=t=out:st=999:d={fade_out}"
    )


# ── Singleton ─────────────────────────────────────────────────────────────────

class BeatSyncService:
    """Beat detection + BGM auto-selection + adaptive mixing."""

    def analyse_bpm(self, audio_path: Path, duration: float = 60.0) -> Dict[str, Any]:
        return analyse_bpm(audio_path, duration)

    def select_bgm(self, target_bpm: float,
                   prefer_category: Optional[str] = None) -> Optional[Dict[str, Any]]:
        track = select_bgm(target_bpm, prefer_category=prefer_category)
        if not track:
            return None
        return {"path": str(track.path), "name": track.name,
                "bpm": track.bpm, "category": track.category}

    def list_library(self) -> List[Dict[str, Any]]:
        tracks = _scan_bgm_library(BGM_LIBRARY_DIR)
        return [{"path": str(t.path), "name": t.name,
                 "bpm": t.bpm, "category": t.category} for t in tracks]

    async def mix(
        self,
        video_path: Path,
        output_path: Path,
        bgm_path: Optional[Path] = None,
        target_bpm: Optional[float] = None,
        speech_segments: Optional[List[Dict[str, Any]]] = None,
        bgm_volume: float = 0.15,
    ) -> Dict[str, Any]:
        return await mix_bgm_beat_synced(
            video_path, output_path,
            bgm_path=bgm_path,
            target_bpm=target_bpm,
            speech_segments=speech_segments,
            bgm_volume=bgm_volume,
        )

    def get_info(self) -> Dict[str, Any]:
        try:
            import librosa
            librosa_available = True
        except ImportError:
            librosa_available = False
        tracks = _scan_bgm_library(BGM_LIBRARY_DIR)
        return {
            "librosa_available": librosa_available,
            "bgm_library_dir": str(BGM_LIBRARY_DIR),
            "track_count": len(tracks),
            "bpm_categories": ["slow", "midtempo", "upbeat", "hype", "fast"],
        }


_instance: Optional[BeatSyncService] = None


def get_beat_sync_service() -> BeatSyncService:
    global _instance
    if _instance is None:
        _instance = BeatSyncService()
    return _instance
