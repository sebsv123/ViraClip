"""
Export Profiles - Perfiles de exportación por plataforma
Optimiza calidad y compatibilidad para TikTok, Instagram Reels y YouTube Shorts
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class Platform(Enum):
    TIKTOK = "tiktok"
    REELS = "reels"
    SHORTS = "shorts"
    UNIVERSAL = "universal"


@dataclass
class ExportProfile:
    """Perfil de exportación con parámetros FFmpeg"""
    name: str
    platform: Platform
    resolution: str  # ej: "1080x1920"
    video_codec: str
    video_bitrate: str
    audio_codec: str
    audio_bitrate: str
    fps: int
    pixel_format: str
    max_file_size_mb: Optional[int]
    extra_args: List[str]  # Argumentos FFmpeg adicionales
    description: str


# Perfiles optimizados por plataforma
EXPORT_PROFILES = {
    Platform.TIKTOK: ExportProfile(
        name="TikTok Optimized",
        platform=Platform.TIKTOK,
        resolution="1080x1920",
        video_codec="libx264",
        video_bitrate="12M",  # 12 Mbps = calidad alta sin exceder límites
        audio_codec="aac",
        audio_bitrate="192k",
        fps=30,
        pixel_format="yuv420p",
        max_file_size_mb=287,
        extra_args=[
            "-movflags", "+faststart",  # Streaming optimizado
            "-profile:v", "high",
            "-level", "4.2",
            "-bf", "2",  # B-frames para compresión
            "-g", "30",  # GOP size
            "-pix_fmt", "yuv420p",  # Compatibilidad máxima
        ],
        description="Optimizado para TikTok: 9:16, H.264, max 287MB"
    ),
    
    Platform.REELS: ExportProfile(
        name="Instagram Reels",
        platform=Platform.REELS,
        resolution="1080x1920",
        video_codec="libx264",
        video_bitrate="15M",  # Reels permite más bitrate
        audio_codec="aac",
        audio_bitrate="192k",
        fps=30,
        pixel_format="yuv420p",
        max_file_size_mb=3500,  # 4GB teórico, pero comprime agresivo
        extra_args=[
            "-movflags", "+faststart",
            "-profile:v", "high",
            "-level", "4.2",
            "-crf", "23",  # Constant Rate Factor para balance calidad/tamaño
            "-preset", "slow",  # Mejor compresión
        ],
        description="Optimizado para Reels: mejor calidad, compresión eficiente"
    ),
    
    Platform.SHORTS: ExportProfile(
        name="YouTube Shorts",
        platform=Platform.SHORTS,
        resolution="1080x1920",
        video_codec="libx264",  # VP9 preferido pero H.264 más compatible
        video_bitrate="16M",    # YouTube re-encodea de todos modos
        audio_codec="aac",
        audio_bitrate="256k",   # Audio mejor para Shorts
        fps=60,  # 60fps preferido para Shorts
        pixel_format="yuv420p",
        max_file_size_mb=256,  # Límite real de Shorts
        extra_args=[
            "-movflags", "+faststart",
            "-profile:v", "high",
            "-level", "5.1",
            "-rc-lookahead", "60",  # Mejor rate control
            "-aq-mode", "3",  # Adaptive quantization
        ],
        description="Optimizado para Shorts: 60fps, audio premium"
    ),
    
    Platform.UNIVERSAL: ExportProfile(
        name="Universal 9:16",
        platform=Platform.UNIVERSAL,
        resolution="1080x1920",
        video_codec="libx264",
        video_bitrate="10M",
        audio_codec="aac",
        audio_bitrate="128k",
        fps=30,
        pixel_format="yuv420p",
        max_file_size_mb=None,
        extra_args=[
            "-movflags", "+faststart",
            "-profile:v", "main",
            "-level", "4.0",
        ],
        description="Perfil universal compatible con todas las plataformas"
    ),
}


class ExportService:
    """
    Servicio de exportación con perfiles por plataforma
    """
    
    def __init__(self):
        self.profiles = EXPORT_PROFILES
        logger.info("✓ Export Service initialized with %d profiles", len(self.profiles))
    
    def get_profile(self, platform: Platform) -> ExportProfile:
        """Obtiene el perfil para una plataforma"""
        return self.profiles.get(platform, self.profiles[Platform.UNIVERSAL])
    
    def build_ffmpeg_command(
        self,
        input_path: str,
        output_path: str,
        platform: Platform,
        start_time: Optional[float] = None,
        duration: Optional[float] = None,
        burn_subtitles: Optional[str] = None
    ) -> List[str]:
        """
        Construye comando FFmpeg completo para exportación
        
        Args:
            input_path: Video de entrada
            output_path: Video de salida
            platform: Plataforma objetivo
            start_time: Segundo de inicio (para clips)
            duration: Duración en segundos
            burn_subtitles: Path a archivo .srt para quemar subtítulos
            
        Returns:
            Lista de argumentos FFmpeg
        """
        profile = self.get_profile(platform)
        
        cmd = ["ffmpeg", "-y"]
        
        # Input
        if start_time is not None:
            cmd.extend(["-ss", str(start_time)])
        cmd.extend(["-i", input_path])
        
        if duration is not None:
            cmd.extend(["-t", str(duration)])
        
        # Video codec y parámetros
        cmd.extend([
            "-c:v", profile.video_codec,
            "-b:v", profile.video_bitrate,
            "-r", str(profile.fps),
            "-pix_fmt", profile.pixel_format,
        ])
        
        # Filtro de video: escalar a 9:16 si es necesario
        scale_filter = self._build_scale_filter(profile.resolution)
        
        if burn_subtitles:
            # Subtítulos quemados
            vf_filter = f"{scale_filter},subtitles='{burn_subtitles}':force_style='FontSize=18,PrimaryColour=&H00FFFFFF'"
            cmd.extend(["-vf", vf_filter])
        else:
            cmd.extend(["-vf", scale_filter])
        
        # Audio
        cmd.extend([
            "-c:a", profile.audio_codec,
            "-b:a", profile.audio_bitrate,
        ])
        
        # Args extra del perfil
        cmd.extend(profile.extra_args)
        
        # Output
        cmd.append(output_path)
        
        return cmd
    
    def _build_scale_filter(self, target_resolution: str) -> str:
        """
        Construye filtro de escalado manteniendo aspecto 9:16
        """
        width, height = target_resolution.split("x")
        
        # Estrategia: escalar manteniendo proporción, luego crop/pad a 9:16
        # Si el video es 16:9, hacemos zoom y seguimiento de cara
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        )
    
    def get_recommended_platform(self, target_platforms: List[str]) -> Platform:
        """
        Determina el perfil más restrictivo para múltiples plataformas
        """
        if "tiktok" in target_platforms:
            return Platform.TIKTOK  # Más restrictivo
        elif "shorts" in target_platforms:
            return Platform.SHORTS
        elif "reels" in target_platforms:
            return Platform.REELS
        else:
            return Platform.UNIVERSAL
    
    def get_export_specs(self, platform: Platform) -> Dict:
        """Devuelve especificaciones legibles para la UI"""
        profile = self.get_profile(platform)
        return {
            "platform": profile.platform.value,
            "name": profile.name,
            "resolution": profile.resolution,
            "video_bitrate": profile.video_bitrate,
            "fps": profile.fps,
            "max_file_size": f"{profile.max_file_size_mb}MB" if profile.max_file_size_mb else "Unlimited",
            "description": profile.description
        }


def get_ffmpeg_export_command(
    input_path: str,
    output_path: str,
    platform: str = "tiktok",
    burn_subtitles_path: Optional[str] = None
) -> List[str]:
    """
    Función de conveniencia para obtener comando FFmpeg
    
    Example:
        cmd = get_ffmpeg_export_command(
            "input.mp4", 
            "output.mp4", 
            platform="tiktok",
            burn_subtitles_path="subs.srt"
        )
        subprocess.run(cmd)
    """
    service = ExportService()
    platform_enum = Platform(platform.lower())
    return service.build_ffmpeg_command(
        input_path, 
        output_path, 
        platform_enum,
        burn_subtitles=burn_subtitles_path
    )
