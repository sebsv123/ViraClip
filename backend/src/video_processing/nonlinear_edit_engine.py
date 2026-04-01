"""
Non-Linear Editing Engine ("Frankenstein" Editing)
Une segmentos no contiguos de forma coherente, ocultando cortes con transiciones
"""
import logging
import asyncio
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)


@dataclass
class SegmentBlock:
    """Bloque de video para ensamblaje non-linear"""
    start: float
    end: float
    text: str
    source_video: str
    virality_score: int
    transition_in: str  # "cut", "fade", "jump"
    transition_out: str
    needs_broll: bool


@dataclass  
class FrankensteinClip:
    """Clip resultante del ensamblaje non-linear"""
    segments: List[SegmentBlock]
    total_duration: float
    transitions: List[Dict]
    broll_insertions: List[Dict]


class NonLinearEditingEngine:
    """
    Engine de edición non-linear que une segmentos no contiguos
    Oculta cortes con: jump cuts suaves, fade negro, B-roll
    """
    
    def __init__(self, min_segment_duration: float = 2.0):
        self.min_segment_duration = min_segment_duration
        self.transitions = {
            "jump_cut": {"duration": 0.1, "type": "hard"},
            "fade_black": {"duration": 0.3, "type": "fade"},
            "crossfade": {"duration": 0.2, "type": "smooth"},
            "broll_cover": {"duration": 1.5, "type": "insert"}
        }
    
    def assemble_frankenstein_clip(
        self,
        selected_segments: List[Dict],
        full_transcript: List[Dict],
        max_duration: float = 60.0
    ) -> FrankensteinClip:
        """
        Ensambla segmentos no contiguos en un clip coherente
        
        Args:
            selected_segments: Segmentos virales seleccionados (no contiguos)
            full_transcript: Transcripción completa para encontrar continuaciones
            max_duration: Duración máxima objetivo
            
        Returns:
            FrankensteinClip con metadatos de ensamblaje
        """
        if not selected_segments:
            return FrankensteinClip([], 0, [], [])
        
        # Ordenar por timestamp
        sorted_segments = sorted(selected_segments, key=lambda x: x.get("start", 0))
        
        blocks = []
        total_duration = 0
        transitions = []
        broll_insertions = []
        
        for i, seg in enumerate(sorted_segments):
            # Determinar transición
            if i == 0:
                transition_in = "fade_in"
            else:
                gap = seg.get("start", 0) - sorted_segments[i-1].get("end", 0)
                
                if gap > 5:
                    # Gap grande = usar B-roll para cubrir
                    transition_in = "broll_cover"
                    broll_insertions.append({
                        "position": total_duration,
                        "duration": min(gap, 3.0),  # Max 3s de B-roll
                        "context": seg.get("text", "")[:50]
                    })
                elif gap > 1:
                    # Gap mediano = fade negro
                    transition_in = "fade_black"
                else:
                    # Gap pequeño = jump cut suave
                    transition_in = "jump_cut"
            
            # Calcular duración del bloque
            seg_duration = seg.get("end", 0) - seg.get("start", 0)
            
            # Verificar si excedemos duración máxima
            if total_duration + seg_duration > max_duration:
                # Truncar último segmento
                remaining = max_duration - total_duration
                if remaining < self.min_segment_duration:
                    break
                seg_duration = remaining
            
            block = SegmentBlock(
                start=seg.get("start", 0),
                end=seg.get("start", 0) + seg_duration,
                text=seg.get("text", ""),
                source_video=seg.get("source_video", ""),
                virality_score=seg.get("virality_score", 50),
                transition_in=transition_in,
                transition_out="cut" if i < len(sorted_segments) - 1 else "fade_out",
                needs_broll=(transition_in == "broll_cover")
            )
            
            blocks.append(block)
            total_duration += seg_duration
            
            # Registrar transición
            if i > 0:
                transitions.append({
                    "from_segment": i - 1,
                    "to_segment": i,
                    "type": transition_in,
                    "timestamp": total_duration - seg_duration,
                    "gap_seconds": gap if 'gap' in locals() else 0
                })
            
            if total_duration >= max_duration:
                break
        
        return FrankensteinClip(
            segments=blocks,
            total_duration=total_duration,
            transitions=transitions,
            broll_insertions=broll_insertions
        )
    
    def find_missing_context(
        self,
        segment: Dict,
        full_transcript: List[Dict],
        max_context_duration: float = 5.0
    ) -> Optional[Dict]:
        """
        Encuentra contexto previo necesario para que un segmento tenga sentido
        
        Args:
            segment: Segmento que necesita contexto
            full_transcript: Transcripción completa
            max_context_duration: Cuánto contexto máximo buscar
            
        Returns:
            Segmento de contexto o None
        """
        seg_start = segment.get("start", 0)
        
        # Buscar segmento inmediatamente anterior
        candidates = [
            t for t in full_transcript
            if t.get("end", 0) <= seg_start
            and (seg_start - t.get("end", 0)) < 2.0  # Muy cercano
        ]
        
        if not candidates:
            return None
        
        # Elegir el más cercano
        best = max(candidates, key=lambda x: x.get("end", 0))
        
        # Verificar si aporta contexto valioso
        context_duration = best.get("end", 0) - best.get("start", 0)
        if context_duration > max_context_duration:
            # Truncar a duración máxima
            best = {
                **best,
                "start": best.get("end", 0) - max_context_duration
            }
        
        return best
    
    async def _extract_segment(
        self,
        source_video: str,
        start: float,
        end: float,
        output_path: str
    ) -> bool:
        """
        Extrae un segmento y lo re-encodea para garantizar timestamps continuos.
        
        Fix AV desync: -reset_timestamps 1 reinicia timestamps desde 0.
        Esto permite que concat posterior use -c copy sin desync.
        """
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", source_video,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-ar", "44100",
            "-reset_timestamps", "1",  # ← CLAVE: reinicia timestamps desde 0
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            output_path
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"[FRANKENSTEIN] FFmpeg segment extract failed: {stderr.decode()[-500:]}")
                return False
            return True
        except Exception as e:
            logger.error(f"[FRANKENSTEIN] Segment extract exception: {e}", exc_info=True)
            return False

    async def _concat_segments(self, segment_files: List[str], output_path: str) -> bool:
        """
        Concat de segmentos ya normalizados — aquí sí es seguro -c copy.
        
        Como todos los segmentos tienen timestamps desde 0, el concat mantiene sync perfecto.
        """
        concat_list = Path(output_path).parent / "concat_list.txt"
        with open(concat_list, "w") as f:
            for seg in segment_files:
                f.write(f"file '{seg}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",   # ← seguro porque timestamps ya están normalizados
            "-movflags", "+faststart",
            output_path
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"[FRANKENSTEIN] FFmpeg concat failed: {stderr.decode()[-500:]}")
                return False
            logger.info(f"[FRANKENSTEIN] Concat exitoso: {len(segment_files)} segmentos → {output_path}")
            return True
        except Exception as e:
            logger.error(f"[FRANKENSTEIN] Concat exception: {e}", exc_info=True)
            return False

    async def render_frankenstein_clip(
        self,
        frankenstein: FrankensteinClip,
        source_video_path: str,
        output_path: str,
        broll_service=None
    ) -> bool:
        """
        Renderiza el clip frankenstein usando FFmpeg (versión async optimizada).
        
        Cambios vs versión anterior:
        - Un solo re-encode por segmento (no doble)
        - Concat final con -c copy (rápido, sin pérdida)
        - Timestamps normalizados = AV sync perfecto
        
        Args:
            frankenstein: Metadatos del ensamblaje
            source_video_path: Video fuente original
            output_path: Ruta de salida
            broll_service: Servicio opcional para obtener B-roll
            
        Returns:
            True si éxito
        """
        if not frankenstein.segments:
            logger.warning("[FRANKENSTEIN] No segments to render")
            return False
        
        try:
            temp_segments = []
            
            for i, block in enumerate(frankenstein.segments):
                segment_path = str(Path(output_path).parent / f"segment_{i}.mp4")
                
                # Extraer segmento con timestamps normalizados
                success = await self._extract_segment(
                    source_video_path,
                    block.start,
                    block.end,
                    segment_path
                )
                
                if not success:
                    logger.error(f"[FRANKENSTEIN] Failed to extract segment {i}")
                    # Limpiar segmentos parciales
                    for seg in temp_segments:
                        Path(seg).unlink(missing_ok=True)
                    return False
                
                temp_segments.append(segment_path)
                
                # B-roll si es necesario
                if block.needs_broll and broll_service:
                    logger.info(f"[FRANKENSTEIN] Fetching B-roll for gap at {block.start:.1f}s")
            
            # Concatenar segmentos normalizados
            concat_success = await self._concat_segments(temp_segments, output_path)
            
            if not concat_success:
                logger.error("[FRANKENSTEIN] Concat failed")
                return False
            
            # Limpiar archivos temporales
            for seg_file in temp_segments:
                Path(seg_file).unlink(missing_ok=True)
            Path(output_path).parent.joinpath("concat_list.txt").unlink(missing_ok=True)
            
            logger.info(f"✓ [FRANKENSTEIN] Clip rendered: {output_path}")
            logger.info(f"  Segments: {len(frankenstein.segments)}")
            logger.info(f"  Total duration: {frankenstein.total_duration:.1f}s")
            logger.info(f"  Transitions: {len(frankenstein.transitions)}")
            
            return True
            
        except Exception as e:
            logger.error(f"[FRANKENSTEIN] Failed to render frankenstein clip: {e}", exc_info=True)
            return False
    
    def calculate_dynamic_duration(
        self,
        segments: List[Dict],
        base_duration: float = 30.0,
        virality_multiplier: float = 1.5
    ) -> float:
        """
        Calcula duración óptima basada en virality de los segmentos
        
        Args:
            segments: Segmentos seleccionados
            base_duration: Duración base
            virality_multiplier: Multiplicador por alta virality
            
        Returns:
            Duración óptima en segundos
        """
        if not segments:
            return base_duration
        
        # Calcular virality promedio
        avg_virality = sum(s.get("virality_score", 50) for s in segments) / len(segments)
        
        # Ajustar duración
        if avg_virality > 80:
            # Alto virality = más tiempo para desarrollar
            target_duration = min(55, base_duration * virality_multiplier)
        elif avg_virality > 60:
            # Virality medio = duración estándar
            target_duration = base_duration
        else:
            # Bajo virality = clip corto y punchy
            target_duration = max(15, base_duration * 0.6)
        
        logger.info(f"Dynamic duration: {target_duration:.0f}s (avg virality: {avg_virality:.0f})")
        return target_duration


# Funciones de conveniencia
def create_frankenstein_clip(
    selected_segments: List[Dict],
    full_transcript: List[Dict],
    source_video: str,
    output_path: str,
    max_duration: float = 60.0
) -> bool:
    """
    Función de conveniencia para crear un clip frankenstein completo
    
    Example:
        segments = [
            {"start": 10, "end": 18, "text": "Hook fuerte", "virality_score": 85},
            {"start": 45, "end": 52, "text": "Momento viral", "virality_score": 90},
        ]
        create_frankenstein_clip(segments, transcript, "input.mp4", "output.mp4")
    """
    engine = NonLinearEditingEngine()
    
    # Calcular duración dinámica
    dynamic_duration = engine.calculate_dynamic_duration(selected_segments)
    
    # Ensamblar
    frankenstein = engine.assemble_frankenstein_clip(
        selected_segments,
        full_transcript,
        max_duration=dynamic_duration
    )
    
    # Renderizar
    return engine.render_frankenstein_clip(frankenstein, source_video, output_path)
