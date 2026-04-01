"""
ViraClip AI Simple Processor
Procesa videos y genera clips sin depender de fuentes del sistema
"""
import subprocess
import sys
import os
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
EXPORTS_DIR = BASE_DIR / "exports" / "clips"
TEMP_DIR = BASE_DIR / "temp"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_URLS = [
    "https://youtu.be/DHSigj8uPnE",
    "https://youtu.be/3wgwaxIfUJQ"
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def download_video(url: str, task_id: str) -> Path:
    """Descarga video con yt-dlp"""
    output_template = str(TEMP_DIR / f"{task_id}_raw.%(ext)s")
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "best[ext=mp4]/best",
        "-o", output_template,
        "--no-playlist", "--quiet", "--no-warnings",
        url
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    if result.returncode == 0:
        files = list(TEMP_DIR.glob(f"{task_id}_raw.*"))
        for f in files:
            if f.suffix in ['.mp4', '.webm', '.mkv']:
                return f
    return None

def get_video_info(url: str) -> dict:
    """Obtiene metadata del video"""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json", "--no-playlist", "--quiet", url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout.strip().split('\n')[0])
            return {
                "title": data.get("title", "Unknown"),
                "duration": data.get("duration", 0),
                "description": data.get("description", "")
            }
    except:
        pass
    
    return {"title": "Unknown", "duration": 0, "description": ""}

def detect_viral_moments(video_path: Path, video_info: dict) -> list:
    """Detección simple de momentos virales"""
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
            "reason": "Hook: Apertura fuerte",
            "type": "hook"
        })
    
    # Momentos del medio
    if duration > 120:
        segment_count = min(4, int(duration / 60))
        for i in range(1, segment_count):
            target_time = duration * (i / segment_count)
            moments.append({
                "start": max(0, target_time - 15),
                "end": min(duration, target_time + 20),
                "score": 75,
                "reason": f"Momento viral {i}",
                "type": "viral"
            })
    
    # CTA
    if duration > 60:
        moments.append({
            "start": max(0, duration - 30),
            "end": duration,
            "score": 80,
            "reason": "CTA: Cierre",
            "type": "cta"
        })
    
    # Remover overlaps
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

def create_simple_clip(video_path: Path, moment: dict, output_path: Path):
    """Crea clip simple sin subtítulos"""
    from moviepy import VideoFileClip
    
    try:
        video = VideoFileClip(str(video_path))
        target_duration = min(45, max(15, moment['end'] - moment['start']))
        actual_end = min(moment['start'] + target_duration, video.duration)
        
        subclip = video.subclipped(moment['start'], actual_end)
        
        subclip.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            threads=2
        )
        
        subclip.close()
        video.close()
        return True
    except Exception as e:
        log(f"Error: {e}")
        return False

def process_video(video_url: str, index: int):
    """Procesa un video"""
    task_id = f"video{index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    log(f"\n{'='*60}")
    log(f"PROCESANDO VIDEO {index}")
    log(f"URL: {video_url}")
    log(f"{'='*60}")
    
    info = get_video_info(video_url)
    log(f"Título: {info['title'][:50]}")
    log(f"Duración: {info['duration']}s")
    
    log(f"\n[1/3] Descargando...")
    video_path = download_video(video_url, task_id)
    if not video_path:
        log("✗ Error descargando")
        return 0
    
    size_mb = video_path.stat().st_size / (1024*1024)
    log(f"✓ Descargado: {size_mb:.1f} MB")
    
    log(f"\n[2/3] Analizando momentos virales...")
    moments = detect_viral_moments(video_path, info)
    log(f"✓ Encontrados {len(moments)} momentos")
    
    for i, m in enumerate(moments, 1):
        log(f"  {i}. {m['start']:.1f}s-{m['end']:.1f}s | {m['type']} | {m['reason']}")
    
    log(f"\n[3/3] Generando clips...")
    clips_created = 0
    
    for i, moment in enumerate(moments, 1):
        output_name = f"clip_video{index}_{i}_{moment['type']}_{int(moment['start'])}-{int(moment['end'])}.mp4"
        output_path = EXPORTS_DIR / output_name
        
        log(f"  Clip {i}/{len(moments)}... ", end="")
        
        if create_simple_clip(video_path, moment, output_path):
            clips_created += 1
            size = output_path.stat().st_size / (1024*1024)
            log(f"✓ ({size:.1f} MB)")
        else:
            log(f"✗ Falló")
    
    if video_path.exists():
        video_path.unlink()
    
    log(f"\n✓ Completo: {clips_created} clips generados")
    return clips_created

def main():
    log("="*60)
    log("VIRACLIP AI - PROCESAMIENTO DE VIDEOS")
    log("="*60)
    
    total_clips = 0
    
    for i, url in enumerate(VIDEO_URLS, 1):
        clips = process_video(url, i)
        total_clips += clips
        
        if i < len(VIDEO_URLS):
            log("\n[Esperando 3s...]")
            import time
            time.sleep(3)
    
    log(f"\n{'='*60}")
    log("RESUMEN FINAL")
    log(f"{'='*60}")
    log(f"Videos procesados: {len(VIDEO_URLS)}")
    log(f"Total clips generados: {total_clips}")
    
    files = sorted(EXPORTS_DIR.glob("*.mp4"))
    log(f"\nClips en exports/clips/ ({len(files)}):")
    for f in files[-12:]:
        size_mb = f.stat().st_size / (1024*1024)
        log(f"  • {f.name} ({size_mb:.1f} MB)")
    
    log(f"\nUbicación: {EXPORTS_DIR}")
    log("="*60)

if __name__ == "__main__":
    main()
