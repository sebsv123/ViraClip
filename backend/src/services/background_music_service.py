"""
Background Music Service - Local-first BGM with GPU-accelerated FFmpeg
Uses local BGM assets from the VPI asset library with NVENC support.
"""
import os
import logging
import subprocess
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from pathlib import Path

from .vpi_production_safe_edit import production_safe_mode_active

logger = logging.getLogger(__name__)


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
    - Local-first: usa assets locales desde VPI asset library
    - GPU-accelerated: usa NVENC si VIRACLIP_ENABLE_NVENC=true y probe pasa
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
        
        # GPU probe cache
        self._nvenc_available: Optional[bool] = None
        
        logger.info("Background Music Service initialized (local-first mode)")
    
    def _probe_nvenc(self) -> bool:
        """Probe NVENC availability once and cache result."""
        if self._nvenc_available is not None:
            return self._nvenc_available
        
        env_enabled = os.environ.get("VIRACLIP_ENABLE_NVENC", "false").lower() in ("1", "true", "yes")
        if not env_enabled:
            self._nvenc_available = False
            return False
        
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15
            )
            self._nvenc_available = "h264_nvenc" in result.stdout
            if self._nvenc_available:
                logger.info("[bgm-nvenc] h264_nvenc available")
            else:
                logger.info("[bgm-nvenc] h264_nvenc not found in encoders")
        except Exception as exc:
            logger.warning("[bgm-nvenc] probe failed: %s", exc)
            self._nvenc_available = False
        
        return self._nvenc_available
    
    def _get_video_encoder(self) -> str:
        """Return the best available video encoder."""
        if self._probe_nvenc():
            return "h264_nvenc"
        return "libx264"
    
    def _get_encoder_preset(self) -> str:
        """Return encoder preset."""
        if self._probe_nvenc():
            return "p4"
        return "veryfast"
    
    def _get_encoder_params(self) -> List[str]:
        """Return encoder-specific parameters."""
        if self._probe_nvenc():
            return ["-rc", "constqp", "-qp", "18"]
        return ["-crf", "20"]

    @staticmethod
    def _is_legacy_audio_path(path: str) -> bool:
        normalized = str(path or "").lower().replace("\\", "/")
        return "music_legacy" in normalized or "/legacy/" in normalized
    
    def select_local_bgm(self, niche: str = "general", target_duration: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Select a local BGM asset from the VPI asset library.
        
        Returns a dict with asset info or None if no local BGM available.
        Logs LOCAL_BGM_SELECTED or LOCAL_BGM_SKIPPED.
        """
        try:
            from .vpi_asset_library_service import build_asset_index, select_verified_bgm_candidate
        except ImportError:
            logger.warning("[bgm-local] vpi_asset_library_service not available")
            return None
        
        try:
            asset_index = build_asset_index()
        except Exception as exc:
            logger.debug("[bgm-local] asset_library_unavailable reason=%s", exc)
            return None
        
        verified_bgm = list((asset_index.get("verified") or {}).get("bgm") or [])
        unverified_bgm = list((asset_index.get("unverified") or {}).get("bgm") or [])
        
        # Try verified first, then unverified
        candidates = verified_bgm or ([] if production_safe_mode_active() else unverified_bgm)
        
        if not candidates:
            logger.info("[bgm-local] LOCAL_BGM_SKIPPED reason=no_local_bgm_assets")
            return None
        
        # Select first candidate (simple strategy)
        selected = candidates[0]
        asset_path = str(selected.get("path") or "")
        
        if not asset_path or not Path(asset_path).exists():
            logger.info("[bgm-local] LOCAL_BGM_SKIPPED reason=asset_file_not_found path=%s", asset_path)
            return None
        
        logger.info(
            "[bgm-local] LOCAL_BGM_SELECTED path=%s title=%s source=%s",
            asset_path,
            selected.get("title", "unknown"),
            selected.get("source_name", "local_fallback"),
        )
        
        return {
            "asset_path": asset_path,
            "title": selected.get("title", "local_bgm"),
            "source": selected.get("source_name", "local_fallback"),
            "license": selected.get("license_name", "local_fallback"),
            "verified": bool(selected.get("asset_valid")),
        }
    
    def add_background_music(
        self,
        video_path: str,
        music_path: str,
        output_path: str,
        speech_segments: List[Dict] = None,
        fade_in: float = 2.0,
        fade_out: float = 3.0,
        music_volume: float = 0.15,
    ) -> bool:
        """
        Añade música de fondo con auto-ajuste de volumen basado en segmentos de habla.
        Uses NVENC if available for video re-encode.
        
        Args:
            video_path: Video original
            music_path: Archivo de música
            output_path: Video de salida
            speech_segments: Lista de {start, end} con timestamps de habla
            fade_in: Segundos de fade in
            fade_out: Segundos de fade out
            music_volume: Volumen base de la música (0.0-1.0)
            
        Returns:
            True si éxito
        """
        try:
            if production_safe_mode_active() and self._is_legacy_audio_path(music_path):
                logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=background_music_legacy reason=premium_local_stability")
                return False
            if speech_segments:
                volume_filter = self._build_volume_filter(speech_segments, fade_in, fade_out, music_volume)
            else:
                # Simple constant volume with fades
                volume_filter = (
                    f"volume='if(lt(t,{fade_in}),"
                    f"{music_volume}*t/{fade_in},"
                    f"if(gt(t,t-{fade_out}),"
                    f"{music_volume}*(1-(t-(t-{fade_out}))/{fade_out}),"
                    f"{music_volume}))':eval=frame"
                )
            
            encoder = self._get_video_encoder()
            preset = self._get_encoder_preset()
            encoder_params = self._get_encoder_params()
            
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", video_path,
                "-i", music_path,
                "-filter_complex", 
                f"[1:a]{volume_filter}[music];[0:a][music]amix=inputs=2:duration=longest:dropout_transition=3[audio]",
                "-map", "0:v",
                "-map", "[audio]",
                "-c:v", encoder,
                "-preset", preset,
                *encoder_params,
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, check=True, timeout=300)
            logger.info(
                "[bgm-local] LOCAL_BGM_APPLIED video=%s music=%s encoder=%s",
                output_path, music_path, encoder,
            )
            return True
            
        except subprocess.TimeoutExpired:
            logger.warning("[bgm-local] LOCAL_BGM_SKIPPED reason=ffmpeg_timeout")
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "")[-240:]
            logger.warning("[bgm-local] LOCAL_BGM_SKIPPED reason=ffmpeg_error stderr=%s", stderr)
        except Exception as e:
            logger.warning("[bgm-local] LOCAL_BGM_SKIPPED reason=%s", e)
        
        return False
    
    def _build_volume_filter(
        self,
        speech_segments: List[Dict],
        fade_in: float,
        fade_out: float,
        music_volume: float = 0.15,
    ) -> str:
        """
        Construye filtro de volumen FFmpeg basado en segmentos de habla.
        """
        conditions = []
        base_volume = music_volume
        silence_volume = min(0.80, music_volume * 4.0)  # Boost during silence
        
        for seg in speech_segments:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            conditions.append(f"between(t,{start},{end})")
        
        if not conditions:
            return f"volume={silence_volume}:eval=frame"
        
        # Build nested if expression
        expression = f"{base_volume}"
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
        Selecciona automáticamente música basada en el nicho de contenido.
        Prefers local BGM assets over external APIs.
        
        Args:
            niche: Nicho de contenido (tech, gaming, fitness, etc.)
            target_duration: Duración objetivo del clip
            mood: Estado de ánimo deseado
            
        Returns:
            MusicTrack seleccionado o None
        """
        # Try local BGM first
        local_bgm = self.select_local_bgm(niche, target_duration)
        if local_bgm:
            return MusicTrack(
                id="local_bgm_001",
                title=local_bgm.get("title", "Local BGM"),
                artist="ViraClip",
                url=local_bgm["asset_path"],
                duration=int(target_duration),
                genre=niche,
                mood=mood,
                license=local_bgm.get("license", "Internal")
            )
        
        # Fallback: return a mock track for demo
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
        speech_segments=None,
        music_volume=music_volume,
    )
