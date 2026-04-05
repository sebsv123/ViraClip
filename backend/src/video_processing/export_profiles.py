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
    TIKTOK_UPLOAD = "tiktok_upload"
    REELS = "reels"
    SHORTS = "shorts"
    UNIVERSAL = "universal"


@dataclass
class BitrateVariant:
    """Variant with different quality/bitrate for adaptive delivery."""
    suffix: str  # "hq", "mq", "lq"
    video_bitrate: str
    audio_bitrate: str
    quality: str = "medium"  # "high", "medium", "low"
    max_file_size_mb: Optional[int] = None
    crf: Optional[int] = 23  # Constant Rate Factor (lower = better quality; 23 = FFmpeg default)


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
    max_duration_seconds: int = 60   # Hard cap per platform
    min_duration_seconds: int = 15   # Minimum viable clip length
    bitrate_variants: Optional[List[BitrateVariant]] = None  # Quality ladder for adaptive export

    def __hash__(self):
        return hash((self.platform, self.resolution, self.video_codec))

    @property
    def width(self) -> int:
        """Parsed width from resolution string (e.g. '1080x1920' → 1080)."""
        try:
            return int(self.resolution.split("x")[0])
        except (ValueError, IndexError):
            return 0

    @property
    def height(self) -> int:
        """Parsed height from resolution string (e.g. '1080x1920' → 1920)."""
        try:
            return int(self.resolution.split("x")[1])
        except (ValueError, IndexError):
            return 0

    @property
    def max_duration(self) -> int:
        """Alias for max_duration_seconds."""
        return self.max_duration_seconds


# Perfiles optimizados por plataforma
EXPORT_PROFILES = {
    Platform.TIKTOK: ExportProfile(
        name="TikTok Optimized",
        platform=Platform.TIKTOK,
        resolution="1080x1920",
        video_codec="libx264",
        video_bitrate="8M",
        audio_codec="aac",
        audio_bitrate="192k",
        fps=30,
        pixel_format="yuv420p",
        max_file_size_mb=287,
        extra_args=[
            "-movflags", "+faststart",
            "-profile:v", "high",
            "-level", "4.2",
            "-bf", "2",
            "-g", "30",
            "-pix_fmt", "yuv420p",
        ],
        description="Optimizado para TikTok: 9:16, H.264, max 287MB",
        max_duration_seconds=60,
        min_duration_seconds=15,
        bitrate_variants=[
            BitrateVariant(
                quality="high",
                video_bitrate="8M",
                audio_bitrate="192k",
                max_file_size_mb=287,
                suffix="hq"
            ),
            BitrateVariant(
                quality="medium",
                video_bitrate="5M",
                audio_bitrate="128k",
                max_file_size_mb=180,
                suffix="mq"
            ),
            BitrateVariant(
                quality="low",
                video_bitrate="3M",
                audio_bitrate="96k",
                max_file_size_mb=100,
                suffix="lq"
            ),
        ],
    ),

    Platform.TIKTOK_UPLOAD: ExportProfile(
        name="TikTok Upload (Small)",
        platform=Platform.TIKTOK_UPLOAD,
        resolution="1080x1920",
        video_codec="libx264",
        video_bitrate="4M",
        audio_codec="aac",
        audio_bitrate="128k",
        fps=30,
        pixel_format="yuv420p",
        max_file_size_mb=50,
        extra_args=[
            "-movflags", "+faststart",
            "-profile:v", "baseline",
            "-level", "4.0",
            "-bf", "0",
            "-g", "30",
            "-pix_fmt", "yuv420p",
        ],
        description="TikTok upload-optimized: small file, fast upload, broad device compat",
        max_duration_seconds=60,
        min_duration_seconds=15,
    ),

    Platform.REELS: ExportProfile(
        name="Instagram Reels",
        platform=Platform.REELS,
        resolution="1080x1920",
        video_codec="libx264",
        video_bitrate="15M",
        audio_codec="aac",
        audio_bitrate="192k",
        fps=30,
        pixel_format="yuv420p",
        max_file_size_mb=3500,
        extra_args=[
            "-movflags", "+faststart",
            "-profile:v", "high",
            "-level", "4.2",
            "-crf", "25",
            "-preset", "veryfast",
        ],
        description="Optimizado para Reels: mejor calidad, compresión eficiente",
        max_duration_seconds=90,
        min_duration_seconds=15,
        bitrate_variants=[
            BitrateVariant(
                quality="high",
                video_bitrate="15M",
                audio_bitrate="192k",
                max_file_size_mb=3500,
                suffix="hq"
            ),
            BitrateVariant(
                quality="medium",
                video_bitrate="10M",
                audio_bitrate="128k",
                max_file_size_mb=2500,
                suffix="mq"
            ),
            BitrateVariant(
                quality="low",
                video_bitrate="6M",
                audio_bitrate="96k",
                max_file_size_mb=1500,
                suffix="lq"
            ),
        ],
    ),

    Platform.SHORTS: ExportProfile(
        name="YouTube Shorts",
        platform=Platform.SHORTS,
        resolution="1080x1920",
        video_codec="libx264",
        video_bitrate="16M",
        audio_codec="aac",
        audio_bitrate="256k",
        fps=60,
        pixel_format="yuv420p",
        max_file_size_mb=256,
        extra_args=[
            "-movflags", "+faststart",
            "-profile:v", "high",
            "-level", "5.1",
        ],
        description="Optimizado para Shorts: 60fps, audio premium",
        max_duration_seconds=60,
        min_duration_seconds=15,
        bitrate_variants=[
            BitrateVariant(
                quality="high",
                video_bitrate="16M",
                audio_bitrate="256k",
                max_file_size_mb=256,
                suffix="hq"
            ),
            BitrateVariant(
                quality="medium",
                video_bitrate="12M",
                audio_bitrate="192k",
                max_file_size_mb=200,
                suffix="mq"
            ),
            BitrateVariant(
                quality="low",
                video_bitrate="8M",
                audio_bitrate="128k",
                max_file_size_mb=150,
                suffix="lq"
            ),
        ],
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
        description="Perfil universal compatible con todas las plataformas",
        max_duration_seconds=120,
        min_duration_seconds=15,
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
        input_path: str = "",
        output_path: str = "",
        platform: Optional[Platform] = None,
        start_time: Optional[float] = None,
        duration: Optional[float] = None,
        burn_subtitles: Optional[str] = None,
        # test-friendly aliases
        input_file: Optional[str] = None,
        output_file: Optional[str] = None,
        profile: Optional["ExportProfile"] = None,
    ) -> List[str]:
        """
        Construye comando FFmpeg completo para exportación
        
        Args:
            input_path / input_file: Video de entrada
            output_path / output_file: Video de salida
            platform: Plataforma objetivo (or pass profile directly)
            start_time: Segundo de inicio (para clips)
            duration: Duración en segundos
            burn_subtitles: Path a archivo .srt para quemar subtítulos
            
        Returns:
            Lista de argumentos FFmpeg
        """
        # Accept either input_path or input_file
        effective_input = input_file or input_path
        effective_output = output_file or output_path
        if profile is None:
            profile = self.get_profile(platform or Platform.UNIVERSAL)
        
        cmd = ["ffmpeg", "-y"]
        
        # Input
        if start_time is not None:
            cmd.extend(["-ss", str(start_time)])
        cmd.extend(["-i", effective_input])
        
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
        cmd.append(effective_output)
        
        return cmd
    
    def enforce_clip_duration(self, duration: float, platform_or_profile=None) -> float:
        """Clamp duration to platform min/max limits. Accepts Platform enum or ExportProfile."""
        if isinstance(platform_or_profile, ExportProfile):
            profile = platform_or_profile
        elif isinstance(platform_or_profile, Platform):
            profile = self.get_profile(platform_or_profile)
        else:
            profile = self.get_profile(Platform.UNIVERSAL)
        clamped = max(float(profile.min_duration_seconds),
                      min(float(profile.max_duration_seconds), duration))
        if clamped != duration:
            logger.info(
                f"[export] Duration {duration:.1f}s → {clamped:.1f}s "
                f"(platform={profile.platform.value} cap={profile.max_duration_seconds}s)"
            )
        return clamped

    def _build_scale_filter(self, target_resolution: str) -> str:
        """
        Center-crop to 9:16 then scale — no black bars.
        Consistent with _PLATFORM_VF in clip_creation.py.
        """
        return "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920"
    
    def get_recommended_platform(self, target_platforms: Optional[List[str]] = None,
                                   aspect_ratio: Optional[float] = None) -> Platform:
        """
        Determina el perfil más restrictivo para múltiples plataformas,
        o recomienda una plataforma basado en aspect_ratio (w/h).
        """
        if aspect_ratio is not None:
            if aspect_ratio < 0.75:   # narrower than 3:4 → vertical (9:16)
                return Platform.TIKTOK
            elif aspect_ratio <= 1.1:  # roughly square
                return Platform.REELS
            else:                       # wider than 1:1
                return Platform.UNIVERSAL
        if target_platforms:
            if "tiktok" in target_platforms:
                return Platform.TIKTOK
            elif "shorts" in target_platforms:
                return Platform.SHORTS
            elif "reels" in target_platforms:
                return Platform.REELS
        return Platform.UNIVERSAL
    
    def get_export_specs(self, platform: Platform) -> Dict:
        """Devuelve especificaciones legibles para la UI"""
        profile = self.get_profile(platform)
        variants = []
        if profile.bitrate_variants:
            for v in profile.bitrate_variants:
                variants.append({
                    "suffix": v.suffix,
                    "quality": v.quality,
                    "video_bitrate": v.video_bitrate,
                    "audio_bitrate": v.audio_bitrate,
                    "max_file_size_mb": v.max_file_size_mb,
                })
        return {
            "platform": profile.platform.value,
            "name": profile.name,
            "resolution": profile.resolution,
            "video_bitrate": profile.video_bitrate,
            "fps": profile.fps,
            "max_file_size": f"{profile.max_file_size_mb}MB" if profile.max_file_size_mb else "Unlimited",
            "description": profile.description,
            "has_variants": bool(profile.bitrate_variants),
            "variants": variants,
        }
    
    def export_srt_captions(self, words_with_confidence: List[Dict], output_path: str) -> str:
        """Export word-level captions as SRT file.
        
        Args:
            words_with_confidence: List of {word, start, end, confidence}
            output_path: Base output path (will append .srt)
            
        Returns:
            Path to generated SRT file
        """
        import os
        srt_path = os.path.splitext(output_path)[0] + ".srt"
        
        with open(srt_path, 'w', encoding='utf-8') as f:
            for idx, word_data in enumerate(words_with_confidence, start=1):
                start_time = self._format_srt_time(word_data['start'])
                end_time = self._format_srt_time(word_data['end'])
                word = word_data['word'].strip()
                
                f.write(f"{idx}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{word}\n\n")
        
        logger.info(f"[export] SRT captions exported: {srt_path}")
        return srt_path
    
    def _format_srt_time(self, seconds: float) -> str:
        """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    def export_with_variants(self, input_path: str, output_base: str, platform: Platform,
                           burn_subtitles: Optional[str] = None, duration: Optional[float] = None) -> List[str]:
        """Export multiple quality variants for adaptive delivery.
        
        Returns:
            List of output file paths (base + all variants)
        """
        profile = self.get_profile(platform)
        outputs = []
        
        # Export base quality
        base_output = f"{output_base}.mp4"
        cmd = self.build_ffmpeg_command(input_path, base_output, platform, burn_subtitles, duration)
        # Execute would go here (handled by caller)
        outputs.append(base_output)
        
        # Export variants if available
        if profile.bitrate_variants:
            for variant in profile.bitrate_variants:
                variant_output = f"{output_base}{variant.suffix}.mp4"
                
                # Build variant command (modify bitrates)
                cmd_variant = ["ffmpeg", "-y", "-i", input_path]
                
                if duration is not None:
                    cmd_variant.extend(["-t", str(duration)])
                
                cmd_variant.extend([
                    "-c:v", profile.video_codec,
                    "-b:v", variant.video_bitrate,
                    "-r", str(profile.fps),
                    "-pix_fmt", profile.pixel_format,
                ])
                
                scale_filter = self._build_scale_filter(profile.resolution)
                if burn_subtitles:
                    vf_filter = f"{scale_filter},subtitles='{burn_subtitles}':force_style='FontSize=18,PrimaryColour=&H00FFFFFF'"
                    cmd_variant.extend(["-vf", vf_filter])
                else:
                    cmd_variant.extend(["-vf", scale_filter])
                
                cmd_variant.extend([
                    "-c:a", profile.audio_codec,
                    "-b:a", variant.audio_bitrate,
                ])
                cmd_variant.extend(profile.extra_args)
                cmd_variant.append(variant_output)
                
                outputs.append(variant_output)
        
        return outputs


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
