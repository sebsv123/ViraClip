"""
Background Music Service - Auto-volume adjustment
Fetches free music from Pixabay/FMA and auto-adjusts volume based on speech
"""
import httpx
import os
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)
from src.services.metrics_aggregator import record_event


@dataclass
class MusicTrack:
    """Track de música con metadatos"""
    id: str
    title: str
    artist: str
    url: str
    duration: int
    genre: str
    mood: str
    license: str


class BackgroundMusicService:
    """
    Servicio de música de fondo con auto-ajuste de volumen
    - Volumen bajo (15%) cuando hay habla
    - Volumen alto (80%) en intros/outros
    - Integración con Pixabay API (gratuita)
    """
    
    def __init__(self, pixabay_key: Optional[str] = None):
        self.pixabay_key = pixabay_key or os.environ.get("PIXABAY_API_KEY")
        self.base_url = "https://pixabay.com/api"
        self.music_cache_dir = Path("./temp/music")
        self.music_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Niveles de volumen adaptativos
        self.volume_levels = {
            "speech": 0.15,      # 15% durante habla
            "silence": 0.80,     # 80% durante silencios
            "intro": 0.60,       # 60% en intro
            "outro": 0.40,       # 40% en outro (fade out)
            "transition": 0.50   # 50% en transiciones
        }
        
        logger.info("Background Music Service initialized")
    
    async def search_music(
        self,
        genre: Optional[str] = None,
        mood: str = "upbeat",
        duration: int = 60
    ) -> List[MusicTrack]:
        """
        Busca música de fondo en Pixabay
        
        Args:
            genre: Género musical (electronic, pop, rock, etc.)
            mood: Estado de ánimo (upbeat, calm, energetic, etc.)
            duration: Duración mínima en segundos
            
        Returns:
            Lista de tracks disponibles
        """
        if not self.pixabay_key:
            logger.warning("Pixabay API key not set, using local music")
            return []
        
        params = {
            "key": self.pixabay_key,
            "q": f"{mood} {genre or 'background'} music",
            "category": "music",
            "video_type": "film",  # Background music tracks
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
                
                tracks = []
                for hit in data.get("hits", [])[:5]:  # Top 5 results
                    tracks.append(MusicTrack(
                        id=str(hit.get("id")),
                        title=hit.get("tags", "Unknown"),
                        artist="Pixabay",
                        url=hit.get("videos", {}).get("small", {}).get("url", ""),
                        duration=hit.get("duration", 0),
                        genre=genre or "mixed",
                        mood=mood,
                        license="Pixabay License (Free)"
                    ))
                
                # [Metrics] music_background
                record_event("music_background", payload={
                    "genre": genre, "mood": mood, "tracks_found": len(tracks),
                })
                return tracks
                
        except Exception as e:
            logger.error(f"Pixabay search failed: {e}")
            # [Metrics] engine_error
            record_event("engine_error", payload={
                "engine": "background_music_service", "error": str(e)[:200],
            })
            return []
    
    def download_music(self, track: MusicTrack, output_path: str) -> bool:
        """Descarga un track de música"""
        try:
            import urllib.request
            urllib.request.urlretrieve(track.url, output_path)
            return True
        except Exception as e:
            logger.error(f"Failed to download music: {e}")
            return False
    
    def add_background_music(
        self,
        video_path: str,
        music_path: str,
        output_path: str,
        speech_segments: List[Dict] = None,
        fade_in: float = 2.0,
        fade_out: float = 3.0
    ) -> bool:
        """
        Añade música de fondo con auto-ajuste de volumen basado en segmentos de habla
        
        Args:
            video_path: Video original
            music_path: Archivo de música
            output_path: Video de salida
            speech_segments: Lista de {start, end} con timestamps de habla
            fade_in: Segundos de fade in
            fade_out: Segundos de fade out
            
        Returns:
            True si éxito
        """
        try:
            if speech_segments:
                # Crear filtro de volumen complejo basado en segmentos de habla
                volume_filter = self._build_volume_filter(speech_segments, fade_in, fade_out)
            else:
                # Volumen simple: intro alto, luego bajo, outro fade
                volume_filter = f"volume='if(lt(t,{fade_in}),0.6,if(gt(t,t-{fade_out}),0.2,0.15))':eval=frame"
            
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", music_path,
                "-filter_complex", 
                f"[1:a]{volume_filter}[music];[0:a][music]amix=inputs=2:duration=longest:dropout_transition=3[audio]",
                "-map", "0:v",
                "-map", "[audio]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, check=True)
            logger.info(f"✓ Background music added: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add background music: {e}")
            return False
    
    def _build_volume_filter(
        self,
        speech_segments: List[Dict],
        fade_in: float,
        fade_out: float
    ) -> str:
        """
        Construye filtro de volumen FFmpeg basado en segmentos de habla
        
        Ejemplo de salida:
        volume='if(between(t,0,5),0.15,if(between(t,5,10),0.8,0.15))':eval=frame
        """
        # Simplificación: usar niveles básicos
        # En producción, esto generaría un filtro complejo con múltiples condiciones
        
        conditions = []
        base_volume = self.volume_levels["speech"]
        silence_volume = self.volume_levels["silence"]
        
        for seg in speech_segments:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            # Durante habla: volumen bajo
            conditions.append(f"between(t,{start},{end})")
        
        if not conditions:
            return f"volume={silence_volume}"
        
        # Construir expresión if anidada
        # Formato: if(condition, volume_if_true, volume_if_false)
        expression = f"{base_volume}"  # Default: bajo
        
        for condition in conditions:
            expression = f"if({condition},{base_volume},{silence_volume})"
        
        return f"volume='{expression}':eval=frame"
    
    def auto_select_music(
        self,
        niche: str,
        target_duration: float,
        mood: str = "energetic"
    ) -> Optional[MusicTrack]:
        """
        Selecciona automáticamente música basada en el nicho de contenido
        
        Args:
            niche: Nicho de contenido (tech, gaming, fitness, etc.)
            target_duration: Duración objetivo del clip
            mood: Estado de ánimo deseado
            
        Returns:
            MusicTrack seleccionado o None
        """
        # Mapeo de nichos a géneros
        niche_to_genre = {
            "tech": "electronic",
            "gaming": "electronic",
            "fitness": "pop",
            "education": "ambient",
            "comedy": "funk",
            "news": "ambient",
            "motivation": "epic"
        }
        
        genre = niche_to_genre.get(niche, "pop")
        
        # Para demo, retornar un track mock
        return MusicTrack(
            id="local_001",
            title=f"{genre.title()} Background",
            artist="ViraClip",
            url="",
            duration=int(target_duration),
            genre=genre,
            mood=mood,
            license="Internal"
        )


def mix_background_music_simple(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.15
) -> bool:
    """
    Función simple para mezclar música de fondo
    
    Example:
        mix_background_music_simple("clip.mp4", "music.mp3", "output.mp4", 0.15)
    """
    service = BackgroundMusicService()
    return service.add_background_music(
        video_path,
        music_path,
        output_path,
        speech_segments=None
    )
