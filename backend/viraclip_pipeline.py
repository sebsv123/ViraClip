"""
ViraClip AI Full Pipeline Processor
Implementación real usando VideoService, transcripción y análisis AI
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Configurar logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Videos de prueba
VIDEO_URLS = [
    "https://youtu.be/DHSigj8uPnE",
    "https://youtu.be/3wgwaxIfUJQ"
]

async def process_video_full(video_url: str, task_id: str):
    """
    Procesa un video completo usando el pipeline de ViraClip:
    1. Descarga
    2. Transcripción (faster-whisper)
    3. Análisis AI (segmentos virales)
    4. Generación de clips con subtítulos
    """
    from src.services.video_service import VideoService
    from src.config import Config
    
    config = Config()
    logger.info(f"\n{'='*70}")
    logger.info(f"PROCESANDO: {task_id}")
    logger.info(f"URL: {video_url}")
    logger.info(f"{'='*70}\n")
    
    # Progress callback
    async def progress_callback(progress: int, message: str, status: str):
        logger.info(f"[{progress}%] {message}")
    
    try:
        # Ejecutar pipeline completo
        result = await VideoService.process_video_complete(
            url=video_url,
            source_type="youtube",
            task_id=task_id,
            font_family="TikTokSans-Regular",
            font_size=28,
            font_color="#FFFFFF",
            caption_template="viral_pro",  # Template profesional
            processing_mode="quality",  # Modo calidad para mejor análisis
            output_format="vertical",   # 9:16 para shorts/reels
            add_subtitles=True,         # SÍ: Agregar subtítulos
            include_broll=True,         # SÍ: Sugerencias B-roll
            split_screen=False,
            target_platform="tiktok",
            progress_callback=progress_callback
        )
        
        # Extraer resultados
        segments = result.get("segments", [])
        transcript = result.get("transcript", "")
        
        logger.info(f"\n{'='*70}")
        logger.info(f"ANÁLISIS COMPLETO")
        logger.info(f"{'='*70}")
        logger.info(f"Transcript: {len(transcript)} caracteres")
        logger.info(f"Segmentos virales detectados: {len(segments)}")
        
        # Mostrar detalles de cada segmento
        for i, seg in enumerate(segments[:6], 1):  # Top 6
            logger.info(f"\n[CLIP {i}] {seg.get('start_time', 'N/A')} - {seg.get('end_time', 'N/A')}")
            logger.info(f"         Score Viral: {seg.get('virality_score', 0):.0f}/100")
            logger.info(f"         Hook Score: {seg.get('hook_score', 0):.0f}")
            logger.info(f"         Tipo Hook: {seg.get('hook_type', 'N/A')}")
            logger.info(f"         Texto: {seg.get('text', '')[:80]}...")
            
            # Mostrar hashtags si existen
            hashtags = seg.get('suggested_hashtags', [])
            if hashtags:
                logger.info(f"         Hashtags: {', '.join(hashtags[:5])}")
            
            # Mostrar análisis de hooks
            hook_analysis = seg.get('hook_analysis', {})
            if hook_analysis:
                detected = hook_analysis.get('detected_hooks', [])
                if detected:
                    logger.info(f"         Hooks detectados: {len(detected)}")
                    for h in detected[:2]:
                        logger.info(f"           - {h.get('type')}: {h.get('text', '')[:30]}")
        
        return {
            "status": "success",
            "task_id": task_id,
            "segments_count": len(segments),
            "segments": segments[:6],
            "transcript_length": len(transcript)
        }
        
    except Exception as e:
        logger.error(f"Error procesando video: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "failed",
            "error": str(e)
        }

async def render_clips_for_segments(task_id: str, video_path: str, segments: list):
    """
    Renderiza los clips físicamente para los segmentos detectados
    """
    from src.services.video_service import VideoService
    from src.config import Config
    from pathlib import Path
    
    config = Config()
    output_dir = Path(config.output_dir) / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"\n{'='*70}")
    logger.info(f"RENDERIZANDO CLIPS")
    logger.info(f"{'='*70}")
    
    clips_rendered = []
    
    for i, segment in enumerate(segments[:6], 1):  # Renderizar top 6
        logger.info(f"\nRenderizando clip {i}/{min(6, len(segments))}...")
        
        try:
            clip_info = await VideoService.create_single_clip(
                video_path=Path(video_path),
                segment=segment,
                clip_index=i-1,
                output_dir=output_dir,
                font_family="TikTokSans-Regular",
                font_size=28,
                font_color="#FFFFFF",
                caption_template=segment.get("niche_info", {}).get("template", "viral_pro"),
                output_format="vertical",
                add_subtitles=True,
                broll_suggestions=segment.get("broll_suggestions", []),
                hook_title=segment.get("suggested_title", ""),
                task_id=task_id
            )
            
            if clip_info:
                clips_rendered.append(clip_info)
                logger.info(f"✓ Clip guardado: {clip_info.get('filename')}")
                logger.info(f"  Duración: {clip_info.get('duration', 0):.1f}s")
                logger.info(f"  Path: {clip_info.get('path')}")
            
        except Exception as e:
            logger.error(f"✗ Error renderizando clip {i}: {e}")
    
    return clips_rendered

async def main():
    """Entry point"""
    logger.info("="*70)
    logger.info("VIRACLIP AI - PIPELINE COMPLETO")
    logger.info("="*70)
    logger.info("Features:")
    logger.info("  • Transcripción AI (faster-whisper)")
    logger.info("  • Análisis viral con scoring Ollama")
    logger.info("  • Detección de hooks y retention")
    logger.info("  • Subtítulos profesionales (viral_pro)")
    logger.info("  • B-roll automático")
    logger.info("="*70)
    
    results = []
    
    for i, url in enumerate(VIDEO_URLS, 1):
        task_id = f"video_{i}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Procesar video (análisis)
        result = await process_video_full(url, task_id)
        results.append(result)
        
        if result["status"] == "success" and result.get("segments"):
            # Renderizar clips físicos
            # Necesitamos el video_path del resultado
            # Por ahora, buscar en temp
            temp_dir = Path("temp")
            video_files = list(temp_dir.glob(f"{task_id}*")) if temp_dir.exists() else []
            
            if video_files:
                video_path = video_files[0]
                clips = await render_clips_for_segments(
                    task_id, str(video_path), result["segments"]
                )
                result["clips_rendered"] = len(clips)
        
        # Esperar entre videos
        if i < len(VIDEO_URLS):
            logger.info("\n[Esperando 5s antes del siguiente video...]")
            await asyncio.sleep(5)
    
    # Resumen final
    logger.info(f"\n{'='*70}")
    logger.info("RESUMEN FINAL")
    logger.info(f"{'='*70}")
    
    total_segments = sum(r.get("segments_count", 0) for r in results if r["status"] == "success")
    total_clips = sum(r.get("clips_rendered", 0) for r in results if r["status"] == "success")
    successful = sum(1 for r in results if r["status"] == "success")
    
    logger.info(f"Videos procesados: {len(results)}")
    logger.info(f"Exitosos: {successful}/{len(results)}")
    logger.info(f"Total segmentos virales: {total_segments}")
    logger.info(f"Total clips renderizados: {total_clips}")
    
    # Listar clips generados
    clips_dir = Path("exports/clips")
    if clips_dir.exists():
        files = sorted(clips_dir.glob("*.mp4"))
        logger.info(f"\nClips en disco ({len(files)}):")
        for f in files[-12:]:  # últimos 12
            size_mb = f.stat().st_size / (1024*1024)
            logger.info(f"  • {f.name} ({size_mb:.1f} MB)")
    
    logger.info(f"\n{'='*70}")

if __name__ == "__main__":
    asyncio.run(main())
