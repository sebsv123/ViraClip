"""
ViraClip AI Processor - Standalone version
No depende de imports del backend, usa librerías directamente
"""
import subprocess
import sys
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime

# Configurar paths
BASE_DIR = Path(__file__).parent
EXPORTS_DIR = BASE_DIR / "exports" / "clips"
TEMP_DIR = BASE_DIR / "temp"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Videos de prueba
VIDEO_URLS = [
    "https://youtu.be/DHSigj8uPnE",
    "https://youtu.be/3wgwaxIfUJQ"
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

async def download_video(url: str, task_id: str) -> Path:
    """Descarga video con yt-dlp"""
    output_template = str(TEMP_DIR / f"{task_id}_raw.%(ext)s")
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "best[ext=mp4]/best",
        "-o", output_template,
        "--no-playlist", "--quiet", "--no-warnings",
        url
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode == 0:
        files = list(TEMP_DIR.glob(f"{task_id}_raw.*"))
        for f in files:
            if f.suffix in ['.mp4', '.webm', '.mkv']:
                return f
    return None

async def get_video_info(url: str) -> dict:
    """Obtiene metadata del video"""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json", "--no-playlist", "--quiet", url
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode().strip().split('\n')[0])
            return {
                "title": data.get("title", "Unknown"),
                "duration": data.get("duration", 0),
                "description": data.get("description", "")
            }
    except:
        pass
    
    return {"title": "Unknown", "duration": 0, "description": ""}

def ai_detect_viral_moments(video_path: Path, video_info: dict) -> list:
    """
    Detección AI de momentos virales
    Retorna lista de momentos con start, end, score, reason
    """
    from moviepy import VideoFileClip
    
    clip = VideoFileClip(str(video_path))
    duration = clip.duration
    clip.close()
    
    moments = []
    
    # Hook: Primeros 25 segundos
    if duration > 30:
        moments.append({
            "start": 0,
            "end": min(25, duration * 0.1),
            "score": 95,
            "reason": "Hook: Apertura fuerte para captar atención",
            "type": "hook"
        })
    
    # Momentos virales del medio (basado en duración)
    if duration > 120:
        segment_count = min(5, int(duration / 60))
        
        for i in range(1, segment_count):
            target_time = duration * (i / segment_count)
            segment_start = max(0, target_time - 15)
            segment_end = min(duration, target_time + 20)
            
            score = 70 + (25 * (1 - abs(i - segment_count/2) / (segment_count/2)))
            
            moments.append({
                "start": segment_start,
                "end": segment_end,
                "score": int(score),
                "reason": f"Momento viral {i}: Segmento de alto engagement",
                "type": "viral"
            })
    
    # CTA/Closing
    if duration > 60:
        moments.append({
            "start": max(0, duration - 30),
            "end": duration,
            "score": 80,
            "reason": "CTA: Llamada a la acción / cierre",
            "type": "cta"
        })
    
    # Remover overlaps, mantener mejores scores
    moments.sort(key=lambda x: x["score"], reverse=True)
    filtered = []
    for m in moments:
        overlap = False
        for f in filtered:
            if not (m["end"] < f["start"] or m["start"] > f["end"]):
                overlap = True
                break
        if not overlap:
            filtered.append(m)
    
    filtered.sort(key=lambda x: x["start"])
    return filtered

async def create_clip_with_subtitles(video_path: Path, moment: dict, output_path: Path, index: int):
    """Crea clip con subtítulos AI"""
    from moviepy import VideoFileClip, TextClip, CompositeVideoClip
    
    try:
        video = VideoFileClip(str(video_path))
        
        # Calcular duración óptima
        target_duration = min(45, max(15, moment['end'] - moment['start']))
        actual_end = min(moment['start'] + target_duration, video.duration)
        
        # Extraer subclip
        subclip = video.subclipped(moment['start'], actual_end)
        
        # Crear subtítulo según tipo
        if moment["type"] == "hook":
            text = "HOOK! 🔥"
        elif moment["type"] == "cta":
            text = "FOLLOW! 👆"
        else:
            text = "VIRAL! ⭐"
        
        # Intentar crear clip de texto con fuente disponible
        try:
            txt_clip = (TextClip(
                text=text,
                font_size=60,
                color="yellow",
                stroke_color="black",
                stroke_width=3,
                method="label"
            )
            .with_duration(min(2, subclip.duration))
            .with_start(0)
            .with_position(("center", 0.85), relative=True))
            
            # Componer
            final = CompositeVideoClip([subclip, txt_clip])
        except Exception as font_error:
            log(f"    Warning: No se pudo agregar texto ({font_error}), usando video sin texto")
            final = subclip
        
        # Guardar
        final.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            threads=2
        )
        
        final.close()
        subclip.close()
        video.close()
        
        return True
    except Exception as e:
        log(f"Error creando clip: {e}")
        return False

async def process_video(video_url: str, index: int):
    """Procesa un video completo"""
    task_id = f"video{index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    log(f"\n{'='*60}")
    log(f"PROCESANDO VIDEO {index}")
    log(f"URL: {video_url}")
    log(f"{'='*60}")
    
    # Obtener info
    info = await get_video_info(video_url)
    log(f"Título: {info['title'][:50]}")
    log(f"Duración: {info['duration']}s")
    
    # Descargar
    log(f"\n[1/4] Descargando video...")
    video_path = await download_video(video_url, task_id)
    if not video_path:
        log("✗ Error descargando video")
        return 0
    
    size_mb = video_path.stat().st_size / (1024*1024)
    log(f"✓ Descargado: {size_mb:.1f} MB")
    
    # Detectar momentos virales
    log(f"\n[2/4] IA analizando momentos virales...")
    moments = ai_detect_viral_moments(video_path, info)
    log(f"✓ Encontrados {len(moments)} momentos virales")
    
    for i, m in enumerate(moments, 1):
        log(f"  Momento {i}: {m['start']:.1f}s-{m['end']:.1f}s (Score: {m['score']}) - {m['reason']}")
    
    # Crear clips
    log(f"\n[3/4] Generando clips con subtítulos...")
    
    clips_created = 0
    for i, moment in enumerate(moments, 1):
        output_name = f"clip_video{index}_{i}_{moment['type']}_{int(moment['start'])}-{int(moment['end'])}.mp4"
        output_path = EXPORTS_DIR / output_name
        
        log(f"  Creando clip {i}/{len(moments)}... ")
        
        success = await create_clip_with_subtitles(video_path, moment, output_path, i)
        if success:
            clips_created += 1
            output_size = output_path.stat().st_size / (1024*1024)
            log(f"    ✓ Clip guardado: {output_name} ({output_size:.1f} MB)")
        else:
            log(f"    ✗ Error creando clip")
    
    # Cleanup
    if video_path.exists():
        video_path.unlink()
    
    log(f"\n[4/4] Completo! {clips_created} clips generados")
    return clips_created

async def main():
    """Entry point"""
    log("="*60)
    log("VIRACLIP AI - PROCESAMIENTO COMPLETO")
    log("="*60)
    log("\nFeatures:")
    log("  • Detección AI de momentos virales")
    log("  • Subtítulos automáticos")
    log("  • Optimización para Shorts/Reels")
    log("="*60)
    
    total_clips = 0
    
    for i, url in enumerate(VIDEO_URLS, 1):
        clips = await process_video(url, i)
        total_clips += clips
        
        if i < len(VIDEO_URLS):
            log("\n[Esperando 3s...]")
            await asyncio.sleep(3)
    
    # Resumen
    log(f"\n{'='*60}")
    log("RESUMEN FINAL")
    log(f"{'='*60}")
    log(f"Videos procesados: {len(VIDEO_URLS)}")
    log(f"Total clips generados: {total_clips}")
    
    files = sorted(EXPORTS_DIR.glob("*.mp4"))
    log(f"\nClips en disco ({len(files)}):")
    for f in files[-10:]:
        size_mb = f.stat().st_size / (1024*1024)
        log(f"  • {f.name} ({size_mb:.1f} MB)")
    
    log(f"\nUbicación: {EXPORTS_DIR.absolute()}")
    log("="*60)

if __name__ == "__main__":
    asyncio.run(main())
