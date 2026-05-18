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
        self.duck_amount = float(os.environ.get("DUCK_AMOUNT", "0.5"))  # 50% reduction
        self.attack_ms = float(os.environ.get("DUCK_ATTACK_MS", "100"))
        self.release_ms = float(os.environ.get("DUCK_RELEASE_MS", "300"))
    
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
        Apply sidechain compression ducking using FFmpeg.
        
        Strategy:
        1. Extract audio track
        2. Create a sidechain signal from voice segments
        3. Apply sidechaincompress to music track
        4. Mix ducked music back with original voice
        5. Mux audio back to video
        """
        # DISABLED: This approach causes white noise because it applies volume
        # changes to already-mixed audio (voice + music). The beat_sync_service
        # handles ducking correctly during BGM mixing phase.
        # 
        # For proper ducking, audio must be split into voice/music tracks,
        # apply ducking only to music, then remix. This is done in beat_sync_service.
        logger.debug("Audio ducking disabled in this service - use beat_sync_service instead")
        return False


def build_word_aware_ducking_filter(
    words: List[Dict],
    music_base_volume: float = 0.35,
    voice_duck_ratio: float = 0.65,
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


def get_audio_ducking_service() -> AudioDuckingService:
    """Get or create singleton ducking service instance."""
    global _ducking_instance
    if _ducking_instance is None:
        _ducking_instance = AudioDuckingService()
    return _ducking_instance
