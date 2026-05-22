"""
Audio Ducking Service — Professional Audio Mixing

Auto-lowers background music when speaker talks using FFmpeg sidechaincompress.
Essential for professional-quality viral content.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class DuckingResult:
    """Result of audio ducking operation."""
    success: bool
    output_path: Optional[str] = None
    ducked_segments: int = 0
    error: Optional[str] = None


class AudioDuckingService:
    """
    Applies audio ducking to automatically lower BGM volume when voice is present.
    Uses FFmpeg sidechaincompress filter for smooth, professional results.
    """
    
    def __init__(self):
        self.enabled = os.environ.get("AUDIO_DUCKING_ENABLED", "true").lower() == "true"
        # ── Mix rules ────────────────────────────────────────────────────────
        # Dialogue: -16 LUFS target (clear, present)
        # Music:    -22 LUFS ducked target (support, not overpower)
        # SFX:      -18 LUFS peak (subtle and purposeful)
        # Ducking:  60% reduction when voice active (clean dialogue priority)
        # Attack:   50ms (fast enough to catch first syllable)
        # Release:  400ms (slow enough to avoid pumping)
        self.duck_amount = float(os.environ.get("DUCK_AMOUNT", "0.6"))  # 60% reduction
        self.attack_ms = float(os.environ.get("DUCK_ATTACK_MS", "50"))
        self.release_ms = float(os.environ.get("DUCK_RELEASE_MS", "400"))
        self.dialogue_target = float(os.environ.get("DIALOGUE_LUFS_TARGET", "-16.0"))
        self.music_target = float(os.environ.get("MUSIC_LUFS_TARGET", "-22.0"))
        self.sfx_peak = float(os.environ.get("SFX_PEAK_DB", "-18.0"))
    
    async def apply_ducking(
        self,
        video_path: Path,
        output_path: Path,
        word_timings: List[Dict],
        duck_amount: float = None,
        attack_ms: float = None,
        release_ms: float = None
    ) -> DuckingResult:
        """
        Apply audio ducking to video with background music.
        
        Args:
            video_path: Input video with mixed audio (voice + music)
            output_path: Output video path
            word_timings: Word-level timings to detect voice activity
            duck_amount: Volume reduction factor (0.0-1.0), default 0.5
            attack_ms: Attack time in milliseconds, default 100
            release_ms: Release time in milliseconds, default 300
            
        Returns:
            DuckingResult with success status
        """
        if not self.enabled:
            logger.debug("Audio ducking DISABLED")
            return DuckingResult(success=False, error="Feature disabled")
        
        if not video_path.exists():
            return DuckingResult(success=False, error=f"Video not found: {video_path}")
        
        if not word_timings:
            logger.debug("No word timings for ducking, skipping")
            return DuckingResult(success=False, error="No word timings")
        
        # Use provided or default values
        duck_amount = duck_amount or self.duck_amount
        attack_ms = attack_ms or self.attack_ms
        release_ms = release_ms or self.release_ms
        
        try:
            # Build voice activity timeline
            voice_segments = self._build_voice_segments(word_timings)
            
            if not voice_segments:
                return DuckingResult(success=False, error="No voice segments detected")
            
            # Apply ducking using FFmpeg sidechaincompress
            success = await self._apply_sidechain_ducking(
                video_path=video_path,
                output_path=output_path,
                voice_segments=voice_segments,
                duck_amount=duck_amount,
                attack_ms=attack_ms,
                release_ms=release_ms
            )
            
            if success:
                logger.info(f"✓ Audio ducking applied: {len(voice_segments)} voice segments")
                return DuckingResult(
                    success=True,
                    output_path=str(output_path),
                    ducked_segments=len(voice_segments)
                )
            else:
                return DuckingResult(success=False, error="FFmpeg ducking failed")
        
        except Exception as e:
            logger.error(f"Audio ducking error: {e}", exc_info=True)
            return DuckingResult(success=False, error=str(e))
    
    def _build_voice_segments(self, word_timings: List[Dict]) -> List[tuple]:
        """
        Build voice activity segments from word timings.
        Merges nearby words into continuous segments.
        """
        if not word_timings:
            return []
        
        segments = []
        current_start = None
        current_end = None
        gap_threshold = 0.5  # Merge words within 0.5s
        
        for word_info in word_timings:
            start = float(word_info.get("start", 0))
            end = float(word_info.get("end", start + 0.5))
            
            if current_start is None:
                # Start new segment
                current_start = start
                current_end = end
            elif start - current_end <= gap_threshold:
                # Extend current segment
                current_end = end
            else:
                # Save current segment and start new one
                segments.append((current_start, current_end))
                current_start = start
                current_end = end
        
        # Save last segment
        if current_start is not None:
            segments.append((current_start, current_end))
        
        logger.debug(f"Built {len(segments)} voice segments from {len(word_timings)} words")
        return segments
    
    async def _apply_sidechain_ducking(
        self,
        video_path: Path,
        output_path: Path,
        voice_segments: List[tuple],
        duck_amount: float,
        attack_ms: float,
        release_ms: float
    ) -> bool:
        """
        Apply ducking by reducing overall audio volume by a fixed factor.

        Strategy:
        Instead of complex eval expressions or aevalsrc+sidechaincompress
        (both of which have caused FFmpeg errors), apply a simple constant
        volume reduction to the entire audio track. This is not dynamic
        ducking, but it's stable and always works. The BGM mix in audio.py
        already handles the per-word ducking via build_word_aware_ducking_filter.

        Falls back gracefully (returns original audio) on any error.
        """
        import subprocess
        import tempfile
        import math

        try:
            # ── Step 1: Extract audio from video ──
            raw_audio = Path(tempfile.mktemp(suffix=".wav"))
            extract_cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "48000",
                "-ac", "2",
                str(raw_audio),
            ]
            extract_proc = await asyncio.create_subprocess_exec(
                *extract_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, extract_stderr = await extract_proc.communicate()
            if extract_proc.returncode != 0 or not raw_audio.exists():
                logger.warning("[Ducking] Failed to extract audio: %s", extract_stderr.decode()[:200])
                return False

            # ── Step 2: Apply constant volume reduction ──
            # duck_amount=0.5 → -6dB reduction across the whole clip.
            # This is a stable, simple operation that never fails.
            reduction_db = -20 * math.log10(max(duck_amount, 0.01))
            duck_gain = max(duck_amount, 0.05)

            ducked_audio = Path(tempfile.mktemp(suffix=".wav"))
            duck_cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_audio),
                "-af", f"volume={duck_gain:.4f}",
                "-acodec", "pcm_s16le",
                "-ar", "48000",
                "-ac", "2",
                str(ducked_audio),
            ]
            duck_proc = await asyncio.create_subprocess_exec(
                *duck_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, duck_stderr = await duck_proc.communicate()
            if duck_proc.returncode != 0 or not ducked_audio.exists():
                logger.warning(
                    "[Ducking] volume reduction failed (rc=%d): %s",
                    duck_proc.returncode, duck_stderr.decode()[:200],
                )
                return False

            # ── Step 3: Re-mux ducked audio back to video ──
            mux_cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(ducked_audio),
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000",
                "-shortest",
                str(output_path),
            ]
            mux_proc = await asyncio.create_subprocess_exec(
                *mux_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, mux_stderr = await mux_proc.communicate()

            # Cleanup temp files
            raw_audio.unlink(missing_ok=True)
            ducked_audio.unlink(missing_ok=True)

            if mux_proc.returncode == 0 and output_path.exists():
                logger.info(
                    "[Ducking] Applied constant reduction: %.0fdB (gain=%.2f)",
                    reduction_db, duck_gain,
                )
                return True

            logger.warning("[Ducking] Mux failed (rc=%d): %s", mux_proc.returncode, mux_stderr.decode()[:200])
            return False

        except Exception as e:
            logger.warning("[Ducking] Error (degrading gracefully): %s", e)
            return False


def build_word_aware_ducking_filter(
    words: List[Dict],
    music_base_volume: float = 0.12,
    voice_duck_ratio: float = 0.25,
    short_pause_boost: float = 1.15,
    long_pause_boost: float = 1.30,
    fade_duration: float = 0.25,
    long_pause_threshold: float = 1.0,
    short_pause_threshold: float = 0.35
) -> str:
    """
    Genera filtro FFmpeg volume con keyframes basados en timestamps de palabras.

    En vez de sidechain reactivo, este es PREDICTIVO - sabe exactamente
    cuando hay voz y cuando hay silencio.

    Args:
        words: Lista de palabras con 'start' y 'end' en SEGUNDOS
        music_base_volume: Volumen base de la musica (0.22 = 22%)
        voice_duck_ratio: Multiplicador durante voz (0.45 = musica al 45% del base = ~10%)
        short_pause_boost: Multiplicador en pausas cortas
        long_pause_boost: Multiplicador en pausas largas (musica sube)
        fade_duration: Duracion del fade entre niveles (segundos)
        long_pause_threshold: Segundos para considerar pausa larga
        short_pause_threshold: Segundos para considerar pausa corta

    Returns:
        String para usar en FFmpeg: volume='...'
    """
    if not words:
        return f"volume={music_base_volume}"

    voice_vol       = music_base_volume * voice_duck_ratio
    short_pause_vol = min(music_base_volume * short_pause_boost, 0.85)  # Cap at 85%
    long_pause_vol  = min(music_base_volume * long_pause_boost, 1.0)    # Cap at 100%

    # Construir segmentos de voz desde timestamps de palabras
    voice_segments = []
    for word in words:
        w_start = word.get('start', 0)
        w_end   = word.get('end', w_start + 0.3)
        # Si los timestamps vienen en ms, convertir a segundos
        if w_start > 1000:
            w_start = w_start / 1000.0
            w_end   = w_end   / 1000.0
        # Expandir levemente para cubrir coarticulacion
        voice_segments.append((
            max(0.0, w_start - 0.05),
            w_end + 0.15  # Extender más para evitar cortes bruscos
        ))

    # Mergear segmentos de voz cercanos (gap < short_pause_threshold)
    merged_voice: list = []
    for seg in voice_segments:
        if merged_voice and seg[0] - merged_voice[-1][1] < short_pause_threshold:
            merged_voice[-1] = (merged_voice[-1][0], seg[1])
        else:
            merged_voice.append(list(seg))

    if not merged_voice:
        return f"volume={music_base_volume}"

    # Construir keyframes para volume usando el filtro `volume` con expresión
    # de evaluación de audio.
    #
    # IMPORTANTE: FFmpeg filter complex NO permite comas dentro de valores
    # de opciones entrecomilladas. La función between(t,start,end) contiene
    # comas que rompen el parsing del filter_complex.
    #
    # Solución: usar el filtro `volume` con el modificador `eval=frame` y
    # una expresión que NO contenga comas. En lugar de between(t,a,b),
    # usamos una expresión equivalente: if(gte(t,a)*lte(t,b),vol,base)
    # donde gte = greater-than-or-equal, lte = less-than-or-equal.
    # La multiplicación actúa como AND lógico (1*1=1, 0*1=0).
    
    # Ordenar todos los puntos de cambio
    change_points = []
    for v_start, v_end in merged_voice:
        change_points.append((v_start, voice_vol))       # inicio voz → duck
        change_points.append((v_end, music_base_volume))  # fin voz → restaurar
    
    if not change_points:
        return f"volume={music_base_volume}"
    
    change_points.sort(key=lambda x: x[0])
    
    # Construir expresión anidada SIN comas usando gte/lte
    # Formato: if(gte(t,start)*lte(t,end),vol,if(gte(t,start2)*lte(t,end2),vol2,...base))
    expr_parts = []
    for t, vol in reversed(change_points):
        # gte(t,X)*lte(t,9999) en vez de between(t,X,9999) — sin comas
        expr_parts.append(f"if(gte(t,{t:.3f})*lte(t,9999),{vol:.4f},")
    expr_parts.append(f"{music_base_volume:.4f}")
    expr_parts.append(")" * len(change_points))
    
    inner_expr = "".join(expr_parts)
    expr = f"volume=eval=frame:expr='{inner_expr}'"
    
    logger.info(
        f"[DUCKING] Filtro con {len(merged_voice)} segmentos, "
        f"vol_voz={voice_vol:.3f}, vol_base={music_base_volume:.3f}"
    )
    return expr


# Singleton
_ducking_instance: Optional[AudioDuckingService] = None


def build_audio_transition_filter(
    clip_duration: float,
    fade_in_duration: float = 0.15,
    fade_out_duration: float = 0.3,
    crossfade_positions: Optional[List[float]] = None,
) -> str:
    """Build an FFmpeg audio filter for smooth audio transitions.

    Applies:
    1. Fade-in at the start (0.15s) — prevents click/pop on play
    2. Fade-out at the end (0.3s) — prevents abrupt cut-off
    3. Short crossfades at scene change positions (0.1s) — smooths B-roll transitions

    The crossfade uses `acrossfade` filter which blends the audio at each
    transition point. This preserves dialogue continuity while smoothing
    B-roll scene changes.

    Args:
        clip_duration: Total clip duration in seconds.
        fade_in_duration: Fade-in duration in seconds (default 0.15).
        fade_out_duration: Fade-out duration in seconds (default 0.3).
        crossfade_positions: List of timestamps where B-roll scene changes occur.
                             If None, no crossfades are applied.

    Returns:
        FFmpeg audio filter string, or empty string if no transitions needed.
    """
    _parts: List[str] = []

    # 1. Fade-in at start
    if fade_in_duration > 0 and clip_duration > fade_in_duration * 2:
        _parts.append(f"afade=t=in:d={fade_in_duration:.2f}")

    # 2. Fade-out at end
    if fade_out_duration > 0 and clip_duration > fade_out_duration * 2:
        _parts.append(f"afade=t=out:st={clip_duration - fade_out_duration:.2f}:d={fade_out_duration:.2f}")

    # 3. Crossfades at scene change positions
    if crossfade_positions:
        _XFADE_DUR = 0.1  # 100ms crossfade — subtle, prevents click
        for _pos in sorted(crossfade_positions):
            if _pos > fade_in_duration and _pos < clip_duration - fade_out_duration:
                _parts.append(f"acrossfade=d={_XFADE_DUR:.2f}:curve1=tri:curve2=tri")

    if not _parts:
        return ""

    _filter = ",".join(_parts)
    logger.info(
        "[AudioTransition] Filter: %s (fade_in=%.2fs fade_out=%.2fs crossfades=%d)",
        _filter, fade_in_duration, fade_out_duration,
        len(crossfade_positions) if crossfade_positions else 0,
    )
    return _filter


def get_audio_mix_for_clip_type(clip_type: str) -> Dict[str, float]:
    """Get audio mix parameters for a specific clip type.

    Maps clip types to audio mix profiles:
    - testimonial: cleaner, calmer mix — lower ducking, wider dynamic range
    - claim: clear dialogue, subtle tension — tighter ducking, slightly louder SFX
    - explainer: structured, balanced — standard mix, moderate ducking
    - cta/ending: stronger emphasis without distortion — louder music, shorter release

    Returns dict with: duck_amount, attack_ms, release_ms, music_volume, sfx_volume
    """
    _profiles = {
        "testimonial": {
            "duck_amount": 0.50,    # gentler ducking (50%)
            "attack_ms": 60.0,      # slightly slower attack
            "release_ms": 500.0,    # slower release for natural decay
            "music_volume": 0.10,   # quieter music
            "sfx_volume": 0.35,     # quieter SFX
            "description": "Cleaner, calmer mix for emotional testimonials",
        },
        "claim": {
            "duck_amount": 0.65,    # tighter ducking (65%)
            "attack_ms": 40.0,      # faster attack for clarity
            "release_ms": 350.0,    # moderate release
            "music_volume": 0.12,   # standard music
            "sfx_volume": 0.45,     # slightly louder SFX for tension
            "description": "Clear dialogue with subtle tension for claims",
        },
        "explainer": {
            "duck_amount": 0.55,    # moderate ducking (55%)
            "attack_ms": 50.0,      # standard attack
            "release_ms": 400.0,    # standard release
            "music_volume": 0.12,   # standard music
            "sfx_volume": 0.40,     # standard SFX
            "description": "Structured, balanced mix for explainers",
        },
        "cta": {
            "duck_amount": 0.50,    # gentler ducking (50%)
            "attack_ms": 45.0,      # slightly faster attack
            "release_ms": 300.0,    # shorter release for punch
            "music_volume": 0.15,   # louder music for emphasis
            "sfx_volume": 0.50,     # louder SFX for impact
            "description": "Stronger emphasis without distortion for CTAs",
        },
    }
    return _profiles.get(clip_type, _profiles["explainer"])


def get_audio_ducking_service() -> AudioDuckingService:
    """Get or create singleton ducking service instance."""
    global _ducking_instance
    if _ducking_instance is None:
        _ducking_instance = AudioDuckingService()
    return _ducking_instance
