#!/usr/bin/env python3
"""
ViraClip - Generador REAL de Shorts Virales (Backend + ComfyUI)
Integra: audio, reframe AI, subtítulos, jump cuts, zooms, overlays
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
import subprocess

# Añadir backend al path
sys.path.insert(0, str(Path(__file__).parent / "backend" / "src"))

VIRA_ROOT = Path("/home/_sebastian/proyectos/ViraClip")
VIDEO_PATH = VIRA_ROOT / "inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"
OUTPUT_DIR = VIRA_ROOT / "outputs/instagram_ready"

# Configuración de segmentos para el video (en segundos)
SEGMENTS = [
    {"name": "viral_hook", "start": 0, "end": 15, "desc": "Hook viral inicial"},
    {"name": "viral_value", "start": 30, "end": 55, "desc": "Valor + insight"},
    {"name": "viral_proof", "start": 60, "end": 85, "desc": "Prueba social"},
    {"name": "viral_cta", "start": 90, "end": 125, "desc": "CTA + cierre"},
]

def log(msg, level="INFO"):
    print(f"[{level}] {msg}")

async def process_with_viraclip_backend(video_path: Path, segment: dict, output_dir: Path):
    """Procesar un segmento usando el backend real de ViraClip + ComfyUI"""
    from services.video_service import VideoService
    from services.creative_service import CreativeService
    from services.comfyui_integration import comfyui_integration
    
    name = segment["name"]
    start_sec = segment["start"]
    end_sec = segment["end"]
    duration = end_sec - start_sec
    
    log(f"\n{'='*60}")
    log(f"🎬 {name}: {segment['desc']}")
    log(f"   Segmento: {start_sec}s - {end_sec}s ({duration}s)")
    log(f"{'='*60}")
    
    try:
        # 1. Extraer segmento del video (con audio preservado)
        log("⏳ Extrayendo segmento con audio...")
        from clip_editor import trim_clip_file
        
        segment_path = output_dir / f"{name}_raw.mp4"
        await trim_clip_file(
            str(video_path),
            str(segment_path),
            start_sec,
            end_sec,
            include_audio=True
        )
        
        if not segment_path.exists():
            log("❌ Falló extracción del segmento", "ERROR")
            return False
        
        log(f"✅ Segmento extraído: {segment_path.stat().st_size / (1024*1024):.1f} MB")
        
        # 2. Aplicar reframe AI con ComfyUI (smart face tracking)
        log("⏳ Aplicando reframe 9:16 con ComfyUI...")
        reframe_result = await comfyui_integration.reframe_video(
            input_path=str(segment_path),
            output_path=str(output_dir / f"{name}_reframe.mp4"),
            target_resolution=(1080, 1920),
            smart_tracking=True,
            chunk_size=200  # Optimizado para RTX 5070 8GB
        )
        
        if not reframe_result.get("success"):
            log(f"⚠️ Reframe falló, usando original", "WARNING")
            reframe_path = segment_path
        else:
            reframe_path = Path(reframe_result["output_path"])
            log(f"✅ Reframe completado")
        
        # 3. Generar subtítulos con Whisper + ComfyUI
        log("⏳ Generando subtítulos...")
        subs_result = await comfyui_integration.add_subtitles(
            input_path=str(reframe_path),
            output_path=str(output_dir / f"{name}_subs.mp4"),
            subtitle_style="viral",
            chunk_size=200
        )
        
        if subs_result.get("success"):
            subs_path = Path(subs_result["output_path"])
            log(f"✅ Subtítulos agregados")
        else:
            subs_path = reframe_path
            log("⚠️ Subtítulos omitidos", "WARNING")
        
        # 4. Aplicar jump cuts y zooms (creative pipeline)
        log("⏳ Aplicando jump cuts y zooms virales...")
        creative = CreativeService()
        
        final_result = await creative.enhance_viral_style(
            input_path=str(subs_path),
            output_path=str(output_dir / f"{name}.mp4"),
            enable_jump_cuts=True,
            min_silence_duration=0.3,
            zoom_on_cuts=True,
            zoom_factor=1.08,
            add_overlays=True,
            overlay_frequency="adaptive"
        )
        
        if final_result.get("success"):
            final_path = Path(final_result["output_path"])
            size_mb = final_path.stat().st_size / (1024 * 1024)
            log(f"✅ {name} COMPLETADO: {final_path.name} ({size_mb:.1f} MB)")
            
            # Limpiar intermedios
            for temp in [segment_path, reframe_path, subs_path]:
                if temp != final_path and temp.exists():
                    temp.unlink()
                    
            return True
        else:
            log(f"❌ Enhancement falló: {final_result.get('error')}", "ERROR")
            return False
            
    except Exception as e:
        log(f"❌ Error procesando {name}: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("="*60)
    print("VIRACLIP - Shorts Virales REALES (Backend + ComfyUI)")
    print("="*60)
    
    if not VIDEO_PATH.exists():
        log(f"Video no encontrado: {VIDEO_PATH}", "ERROR")
        return 1
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Video: {VIDEO_PATH.name}")
    log(f"Output: {OUTPUT_DIR}")
    
    # Verificar ComfyUI disponible
    import requests
    try:
        r = requests.get("http://localhost:8188/system_stats", timeout=5)
        if r.status_code == 200:
            gpu = r.json().get('devices', [{}])[0].get('name', 'Unknown')
            log(f"✅ ComfyUI conectado: {gpu}")
        else:
            log("⚠️ ComfyUI no responde, reiniciando...", "WARNING")
            subprocess.run(
                ["docker-compose", "-f", str(VIRA_ROOT.parent / "CascadeProjects/ViraClip/docker-compose.yml"), 
                 "up", "-d", "comfyui"],
                capture_output=True, timeout=30
            )
            await asyncio.sleep(45)
    except Exception as e:
        log(f"⚠️ Error verificando ComfyUI: {e}", "WARNING")
    
    # Procesar cada segmento
    generated = 0
    total = len(SEGMENTS)
    
    for i, segment in enumerate(SEGMENTS, 1):
        log(f"\n🚀 Procesando {i}/{total}")
        
        success = await process_with_viraclip_backend(VIDEO_PATH, segment, OUTPUT_DIR)
        
        if success:
            generated += 1
            log(f"✅ {i}/{total} completado")
        else:
            log(f"❌ {i}/{total} falló", "ERROR")
        
        # Pausa entre clips
        if i < total:
            log("⏸️  Pausa 3s...")
            await asyncio.sleep(3)
    
    # Resumen final
    print("\n" + "="*60)
    print("📊 RESUMEN FINAL")
    print("="*60)
    
    mp4_files = sorted(OUTPUT_DIR.glob("*.mp4"))
    viral_files = [f for f in mp4_files if any(s["name"] in f.name for s in SEGMENTS)]
    
    log(f"Shorts virales generados: {len(viral_files)}/{total}")
    
    total_size = 0
    for f in viral_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        total_size += size_mb
        log(f"  📹 {f.name}")
        log(f"     └─ {size_mb:.1f} MB")
    
    if len(viral_files) == total:
        log(f"\n🎉 ¡ÉXITO! {total} shorts virales listos")
        log(f"💾 Total: {total_size:.1f} MB")
        log(f"📁 Ubicación: {OUTPUT_DIR}")
        return 0
    else:
        log(f"\n⚠️  {len(viral_files)}/{total} generados", "WARNING")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
