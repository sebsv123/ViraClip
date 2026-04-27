"""
Sound Design Service - Efectos de sonido virales
Inyecta sonidos condicionados psicológicamente para maximizar retención
"""
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional
import subprocess
import os

logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

# Mapeo: tipo de momento viral → sound effect
# Phase 3: expandido con 8 tipos contextuales nuevos para reglas inteligentes
# (zoom→whoosh, broll→pop, pre-reveal→riser, jump-cut→shutter, ...)
VIRAL_SOUND_MAP = {
    # ── Legacy hook-types (compatibilidad) ───────────────────────────────────
    "curiosity_gap":     "tension_riser.mp3",      # Pitch ascendente 1.5s
    "pattern_interrupt": "glitch_burst.mp3",       # Glitch agresivo (was: glitch_hit)
    "cliffhanger":       "bass_boom.mp3",          # Impacto grave 0.8s
    "insight_reveal":    "ding_chime.mp3",         # Campana suave 0.5s
    "transition":        "whoosh_fast.mp3",        # Swipe 0.3s
    "emphasis_word":     "punch_impact.mp3",       # Hit seco 0.2s
    "scroll_stop":       "whoosh_zoom.mp3",        # Whoosh direccional (was: whoosh_heavy)

    # ── Phase 3: Tipos contextuales nuevos ───────────────────────────────────
    "whoosh_zoom":       "whoosh_zoom.mp3",        # Acompaña ZoomCue (R1)
    "pop_broll":         "pop_appear.mp3",         # Aparición de B-roll (R2)
    "riser_pre_reveal":  "riser_01.mp3",           # 2.2s antes de reveal (R3)
    "camera_shutter":    "camera_shutter.mp3",     # Jump-cut narrativo (R4)
    "magic_reveal":      "magic_reveal.mp3",       # Revelación superlativa
    "bass_drop":         "cinematic_hit.mp3",      # Post-cliffhanger (R5)
    "notification":      "notification_ding.mp3",  # Insight sutil / estadística
    "glitch_burst":      "glitch_burst.mp3",       # Pattern interrupt agresivo
}

# Rutas posibles para los sonidos
SOUND_PATHS = [
    Path("/app/assets/sounds"),           # Docker volume mount (absolute)
    Path("assets/sounds"),
    Path("./assets/sounds"),
    Path("../assets/sounds"),
    Path("backend/assets/sounds"),
]


def find_sounds_dir() -> Optional[Path]:
    """Encuentra el directorio de sonidos"""
    for path in SOUND_PATHS:
        if path.exists() and any(path.iterdir()):
            return path
    return None


def _find_best_sfx(keyword: str) -> Optional[Path]:
    """
    Phase 3: Explicit VIRAL_SOUND_MAP takes priority for known SFX types.
    CLAP semantic matching only fires for arbitrary keywords NOT in the map.

    The planner produces well-defined types (whoosh_zoom, pop_broll, magic_reveal)
    with intentional file pairings — CLAP could pick imperfect substring matches
    that override the curated mapping.

    Args:
        keyword: SFX type from VIRAL_SOUND_MAP (preferred) OR arbitrary keyword.

    Returns:
        Path to the matched SFX, or None if nothing found.
    """
    # 1. Explicit mapping (planner output → curated file)
    sounds_dir = find_sounds_dir()
    if sounds_dir and keyword in VIRAL_SOUND_MAP:
        mapped = sounds_dir / VIRAL_SOUND_MAP[keyword]
        if mapped.exists():
            return mapped

    # 2. CLAP semantic matching (free-form keyword → closest SFX in library)
    try:
        from .clap_sfx_service import find_best_sfx as clap_find
        from pathlib import Path as _Path
        import os as _os

        sfx_library = _Path(_os.getenv("SFX_LIBRARY_PATH", "/app/assets/sfx_library"))
        if sfx_library.exists() and any(sfx_library.iterdir()):
            result = clap_find(keyword, sfx_dir=sfx_library)
            if result:
                return result
    except Exception as e:
        logger.debug(f"[sfx] CLAP lookup failed for '{keyword}': {e}")

    return None


class SoundDesignService:
    """
    Servicio de diseño sonoro viral
    Inyecta efectos de sonido en momentos clave para maximizar engagement
    """
    
    def __init__(self):
        self.sounds_dir = find_sounds_dir()
        self.volume = 0.35  # 35% del volumen original
        
        if self.sounds_dir:
            logger.info(f"✓ Sound Design Service initialized: {self.sounds_dir}")
            self._verify_sounds()
        else:
            logger.warning("⚠ Sounds directory not found. Sound effects disabled.")
    
    def _verify_sounds(self):
        """Verifica qué sonidos están disponibles"""
        available = []
        missing = []
        
        for sound_type, filename in VIRAL_SOUND_MAP.items():
            path = self.sounds_dir / filename
            if path.exists():
                available.append(sound_type)
            else:
                missing.append(filename)
        
        if available:
            logger.info(f"  Available sounds: {', '.join(available)}")
        if missing:
            logger.warning(f"  Missing sounds: {', '.join(missing)}")
    
    def get_sound_cues_from_virality(
        self,
        virality_segments: List[Dict]
    ) -> List[Dict]:
        """
        Convierte segmentos virales en cues de sonido concretos
        
        Args:
            virality_segments: Lista de segmentos con hook_type, timestamps
            
        Returns:
            Lista de cues: [{"timestamp": 4.2, "type": "curiosity_gap"}, ...]
        """
        cues = []
        
        for i, segment in enumerate(virality_segments):
            seg_start = segment.get("start", 0)
            seg_end = segment.get("end", 0)
            
            hook_type = segment.get("hook_type", "")

            if i > 0:
                # Whoosh transition between segments
                cues.append({
                    "timestamp": seg_start,
                    "type": "transition",
                    "intensity": 0.8
                })
            
            # Hook-type sound: slight delay so it doesn't clash with the first frame
            if hook_type in VIRAL_SOUND_MAP:
                offset = 0.5 if i == 0 else 0.3
                cues.append({
                    "timestamp": seg_start + offset,
                    "type": hook_type,
                    "intensity": 0.9
                })
            
            # Emphasis hits en palabras clave
            for word_ts in segment.get("emphasis_words", []):
                if isinstance(word_ts, dict):
                    ts = word_ts.get("start", 0)
                else:
                    ts = word_ts
                cues.append({
                    "timestamp": ts,
                    "type": "emphasis_word",
                    "intensity": 0.6
                })
        
        # Ordenar por timestamp
        cues.sort(key=lambda x: x["timestamp"])
        
        logger.info(f"Generated {len(cues)} sound cues from {len(virality_segments)} segments")
        return cues
    
    async def _apply_audio_normalization(
        self,
        video_path: str,
        output_path: str,
    ) -> str:
        """Fallback: loudnorm + fade in/out when no sound assets are available."""
        try:
            # Use ffmpeg -i instead of ffprobe
            import re
            proc = await asyncio.create_subprocess_exec(
                _get_ffmpeg_exe(), "-i", video_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            stderr_text = stderr.decode('utf-8', errors='replace')
            # Parse duration
            vid_dur = 60.0
            dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr_text)
            if dur_match:
                vid_dur = int(dur_match.group(1)) * 3600 + int(dur_match.group(2)) * 60 + float(dur_match.group(3))
            fade_out_start = max(0.0, vid_dur - 0.5)
            af = f"loudnorm,afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out_start:.2f}:d=0.5"
            norm_proc = await asyncio.create_subprocess_exec(
                _get_ffmpeg_exe(), "-y", "-i", video_path,
                "-af", af,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, norm_stderr = await norm_proc.communicate()
            if norm_proc.returncode == 0 and Path(output_path).exists():
                logger.info(f"  ✓ Audio normalized (loudnorm + fade): {output_path}")
                return output_path
            logger.warning(f"  Audio normalization failed: {norm_stderr.decode()[:200]}")
        except Exception as norm_e:
            logger.warning(f"  Audio normalization exception: {norm_e}")
        return video_path

    async def inject_sound_effects(
        self,
        video_path: str,
        output_path: str,
        sound_cues: List[Dict]
    ) -> Optional[str]:
        """
        Inserta sound effects en timestamps específicos usando FFmpeg
        
        Args:
            video_path: Video original
            output_path: Video de salida con sonidos
            sound_cues: Lista de cues con timestamp y type
            
        Returns:
            Path del video final o None si falla
        """
        if not self.sounds_dir:
            logger.info("No sounds dir — applying loudnorm audio normalization as fallback")
            return await self._apply_audio_normalization(video_path, output_path)
        if not sound_cues:
            logger.info("No sound cues — applying loudnorm audio normalization as fallback")
            return await self._apply_audio_normalization(video_path, output_path)
        
        try:
            # Filtrar solo cues con sonidos disponibles
            # Phase 2.5: use CLAP semantic matching (falls back to VIRAL_SOUND_MAP)
            valid_cues = []
            for cue in sound_cues:
                sound_type = cue.get("type", "")
                sound_path = _find_best_sfx(sound_type)
                if sound_path and sound_path.exists():
                    valid_cues.append((cue, sound_path))
            
            if not valid_cues:
                logger.info("No valid sound cues with available files")
                return video_path
            
            logger.info(f"Injecting {len(valid_cues)} sound effects...")
            
            # Construir comando FFmpeg con múltiples inputs
            inputs = ["-i", video_path]
            filter_parts = []
            
            for i, (cue, sound_path) in enumerate(valid_cues):
                inputs.extend(["-i", str(sound_path)])
                
                # Delay en milisegundos
                delay_ms = int(cue["timestamp"] * 1000)
                intensity = cue.get("intensity", 0.35)
                volume = min(0.45, max(0.20, self.volume * intensity))
                
                # Filtro para este sonido
                filter_parts.append(
                    f"[{i+1}:a]adelay={delay_ms}|{delay_ms},volume={volume}[sfx{i}]"
                )
            
            # Construir mezcla
            num_sounds = len(valid_cues)
            mix_parts = "[0:a]" + "".join(f"[sfx{i}]" for i in range(num_sounds))
            
            filter_complex = ";".join(filter_parts)
            filter_complex += f";{mix_parts}amix=inputs={num_sounds+1}:normalize=0[aout]"
            
            cmd = [
                _get_ffmpeg_exe(), "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                output_path
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                logger.info(f"✓ Sound effects injected: {output_path}")
                return output_path
            else:
                logger.error(f"FFmpeg failed: {stderr.decode()[:500]}")
                return video_path
                
        except Exception as e:
            logger.error(f"Failed to inject sound effects: {e}")
            return video_path
    
    def preview_sound_plan(
        self,
        sound_cues: List[Dict]
    ) -> str:
        """
        Genera resumen legible del plan de sonido
        """
        if not sound_cues:
            return "No sound effects planned"
        
        lines = [f"Sound Design Plan ({len(sound_cues)} effects):"]
        lines.append("-" * 40)
        
        for cue in sound_cues:
            ts = cue["timestamp"]
            stype = cue["type"]
            sound_file = VIRAL_SOUND_MAP.get(stype, "unknown")
            lines.append(f"  {ts:5.1f}s | {stype:20s} | {sound_file}")
        
        return "\n".join(lines)


# Funciones de conveniencia
async def add_viral_sound_effects(
    video_path: str,
    output_path: str,
    virality_segments: List[Dict]
) -> str:
    """
    Función simple para añadir efectos de sonido virales
    
    Example:
        segments = [
            {"start": 0, "end": 5, "hook_type": "curiosity_gap"},
            {"start": 10, "end": 15, "hook_type": "cliffhanger"},
        ]
        await add_viral_sound_effects("clip.mp4", "output.mp4", segments)
    """
    service = SoundDesignService()
    cues = service.get_sound_cues_from_virality(virality_segments)
    result = await service.inject_sound_effects(video_path, output_path, cues)
    return result or video_path
