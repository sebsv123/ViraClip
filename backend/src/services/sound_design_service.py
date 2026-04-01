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

# Mapeo: tipo de momento viral → sound effect
VIRAL_SOUND_MAP = {
    "curiosity_gap": "tension_riser.mp3",      # Pitch ascendente 1.5s
    "pattern_interrupt": "glitch_hit.mp3",     # Distorsión 0.4s
    "cliffhanger": "bass_boom.mp3",            # Impacto grave 0.8s
    "insight_reveal": "ding_chime.mp3",        # Campana suave 0.5s
    "transition": "whoosh_fast.mp3",           # Swipe 0.3s
    "emphasis_word": "punch_impact.mp3",       # Hit seco 0.2s
    "scroll_stop": "whoosh_heavy.mp3",         # Whoosh intenso 0.5s
}

# Rutas posibles para los sonidos
SOUND_PATHS = [
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
            
            # Whoosh al inicio de cada segmento (excepto el primero)
            if i > 0:
                cues.append({
                    "timestamp": seg_start,
                    "type": "transition",
                    "intensity": 0.8
                })
            else:
                # Primer segmento: scroll_stop whoosh
                cues.append({
                    "timestamp": seg_start,
                    "type": "scroll_stop",
                    "intensity": 1.0
                })
            
            # Sound específico según hook_type
            hook_type = segment.get("hook_type", "")
            if hook_type in VIRAL_SOUND_MAP:
                # El impacto va 0.3s después del inicio
                cues.append({
                    "timestamp": seg_start + 0.3,
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
        if not self.sounds_dir or not sound_cues:
            logger.info("No sound effects to inject")
            return video_path
        
        try:
            # Filtrar solo cues con sonidos disponibles
            valid_cues = []
            for cue in sound_cues:
                sound_type = cue.get("type", "")
                if sound_type in VIRAL_SOUND_MAP:
                    filename = VIRAL_SOUND_MAP[sound_type]
                    sound_path = self.sounds_dir / filename
                    if sound_path.exists():
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
                "ffmpeg", "-y",
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
