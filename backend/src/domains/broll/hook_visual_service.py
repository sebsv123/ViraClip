"""
Hook Visual Overlay Service
Añade texto grande impactante en los primeros 2 segundos para scroll-stop effect
"""
import asyncio
import logging
from typing import Optional, Dict, List
from src import gpu_utils
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def _resolve_bold_font() -> str:
    """Return a drawtext-ready fontfile= path that works on Linux & Windows."""
    candidates = [
        # Linux / Docker (most common)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        # Windows fallback
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial Bold.ttf",
        # macOS fallback
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    from pathlib import Path as _P
    for c in candidates:
        if _P(c).exists():
            return c
    return ""  # empty → FFmpeg uses built-in default font


@dataclass
class HookOverlay:
    """Configuración de overlay de hook"""
    text: str
    start_time: float = 0.0
    duration: float = 2.0
    font_size: int = 72
    font_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 3
    position: str = "center"  # center, top, bottom
    animation: str = "fade_zoom"  # fade_zoom, slide_in, typewriter
    background_blur: bool = True


class HookVisualService:
    """
    Servicio de hook visual para los primeros segundos del clip
    Genera texto grande que aparece dramáticamente para detener el scroll
    """
    
    def __init__(self):
        self.default_duration = 2.0  # 2 segundos estándar
        logger.info("✓ Hook Visual Service initialized")
    
    def extract_hook_text(
        self,
        segment_text: str,
        hook_type: str,
        max_chars: int = 50
    ) -> str:
        """
        Extrae el texto más impactante del segmento para el hook
        
        Args:
            segment_text: Texto completo del segmento
            hook_type: Tipo de hook detectado
            max_chars: Máximo de caracteres
            
        Returns:
            Texto optimizado para hook visual
        """
        # Dividir en oraciones
        sentences = segment_text.replace("!", ".").replace("?", ".").split(".")
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        
        if not sentences:
            return segment_text[:max_chars].strip()
        
        # Estrategia según tipo de hook
        if hook_type == "curiosity_gap":
            # Para curiosidad: primera pregunta o frase incompleta
            for sent in sentences:
                if "?" in sent or "what" in sent.lower() or "how" in sent.lower():
                    return self._truncate_with_impact(sent, max_chars)
            return self._truncate_with_impact(sentences[0], max_chars)
            
        elif hook_type == "cliffhanger":
            # Para cliffhanger: última parte del segmento
            return self._truncate_with_impact(sentences[-1], max_chars)
            
        elif hook_type == "pattern_interrupt":
            # Para interrupt: frase más corta y punchy
            shortest = min(sentences, key=len)
            return self._truncate_with_impact(shortest, max_chars)
            
        elif hook_type == "insight_reveal":
            # Para insight: frase con número o dato
            for sent in sentences:
                if any(c.isdigit() for c in sent):
                    return self._truncate_with_impact(sent, max_chars)
            return self._truncate_with_impact(sentences[0], max_chars)
        
        # Default: primera oración
        return self._truncate_with_impact(sentences[0], max_chars)
    
    def _truncate_with_impact(self, text: str, max_chars: int) -> str:
        """Trunca manteniendo impacto - corta en palabra completa"""
        text = text.strip()
        if len(text) <= max_chars:
            return text
        
        # Cortar en último espacio antes del límite
        truncated = text[:max_chars]
        last_space = truncated.rfind(" ")
        if last_space > max_chars * 0.7:  # Al menos 70% del texto
            truncated = truncated[:last_space]
        
        return truncated.strip() + "..."
    
    def create_hook_overlay_filter(
        self,
        hook: HookOverlay,
        video_width: int = 1080,
        video_height: int = 1920
    ) -> str:
        """
        Crea filtro FFmpeg drawtext para el hook visual
        
        Args:
            hook: Configuración del hook
            video_width: Ancho del video
            video_height: Alto del video
            
        Returns:
            String del filtro FFmpeg
        """
        # Escalar fuente proporcional al video
        font_size = min(hook.font_size, int(video_height * 0.08))
        
        # Posición Y según configuración
        if hook.position == "center":
            y_pos = "(h-text_h)/2"
        elif hook.position == "top":
            y_pos = "h*0.15"
        else:  # bottom
            y_pos = "h*0.75"
        
        # Construir filtro drawtext
        # Escape comillas para FFmpeg
        escaped_text = hook.text.replace("'", "'\\''")
        
        # Filtro con animación fade-in y zoom
        _font_path = _resolve_bold_font()
        _fontfile_part = f"fontfile={_font_path}:" if _font_path else ""
        filter_str = (
            f"drawtext=text='{escaped_text}':"
            f"{_fontfile_part}"
            f"fontsize={font_size}:"
            f"fontcolor={hook.font_color}:"
            f"borderw={hook.stroke_width}:"
            f"bordercolor={hook.stroke_color}:"
            f"x=(w-text_w)/2:"
            f"y={y_pos}:"
            f"enable='between(t,{hook.start_time},{hook.start_time + hook.duration})':"
            f"alpha='if(lt(t,{hook.start_time + 0.3}),(t-{hook.start_time})/0.3,1)':"
            f"expansion=normal"
        )
        
        return filter_str
    
    async def add_hook_to_video(
        self,
        video_path: str,
        output_path: str,
        hook: HookOverlay,
        subtitle_path: Optional[str] = None
    ) -> str:
        """
        Añade hook visual al video usando FFmpeg
        
        Args:
            video_path: Video original
            output_path: Video de salida
            hook: Configuración del hook
            subtitle_path: Opcional: subtítulos SRT para combinar
            
        Returns:
            Path del video resultante
        """
        try:
            # Construir filtro
            hook_filter = self.create_hook_overlay_filter(hook)
            
            if subtitle_path:
                # Combinar hook + subtítulos
                vf_filter = (
                    f"subtitles='{subtitle_path}',"
                    f"{hook_filter}"
                )
            else:
                vf_filter = hook_filter
            
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vf", vf_filter,
                *gpu_utils.ffmpeg_codec_flags("high"),
                "-crf", "23",
                "-preset", "fast",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output_path
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                logger.info(f"✓ Hook overlay added: {output_path}")
                return output_path
            else:
                logger.error(f"FFmpeg error: {stderr.decode()[:500]}")
                return video_path
                
        except Exception as e:
            logger.error(f"Failed to add hook overlay: {e}")
            return video_path
    
    def generate_hook_from_segment(
        self,
        segment: Dict,
        duration: float = 2.0
    ) -> HookOverlay:
        """
        Genera hook automáticamente desde datos del segmento
        
        Args:
            segment: Diccionario con text, hook_type, etc.
            duration: Duración del hook en segundos
            
        Returns:
            HookOverlay configurado
        """
        text = segment.get("text", "")
        hook_type = segment.get("hook_type", "insight_reveal")
        
        hook_text = self.extract_hook_text(text, hook_type)
        
        # Colores según tipo de hook
        color_schemes = {
            "curiosity_gap": ("#FFD700", "#000000"),  # Dorado/negro
            "cliffhanger": ("#FF4444", "#000000"),    # Rojo/negro
            "pattern_interrupt": ("#00FFFF", "#000000"),  # Cyan/negro
            "insight_reveal": ("#FFFFFF", "#FF8C00"),  # Blanco/naranja
        }
        
        font_color, stroke_color = color_schemes.get(
            hook_type, 
            ("#FFFFFF", "#000000")
        )
        
        return HookOverlay(
            text=hook_text,
            start_time=0.0,
            duration=duration,
            font_size=68,
            font_color=font_color,
            stroke_color=stroke_color,
            stroke_width=4,
            position="center",
            animation="fade_zoom"
        )


# Funciones de conveniencia
async def add_hook_overlay_to_clip(
    video_path: str,
    output_path: str,
    segment_text: str,
    hook_type: str = "insight_reveal",
    duration: float = 2.0
) -> str:
    """
    Función simple para añadir hook a un clip
    
    Example:
        await add_hook_overlay_to_clip(
            "clip.mp4", 
            "output.mp4",
            "Este es el texto del segmento",
            hook_type="curiosity_gap"
        )
    """
    service = HookVisualService()
    hook = service.generate_hook_from_segment({
        "text": segment_text,
        "hook_type": hook_type
    }, duration)
    return await service.add_hook_to_video(video_path, output_path, hook)


