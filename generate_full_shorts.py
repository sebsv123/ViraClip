#!/usr/bin/env python3
"""
ViraClip - Generador de Shorts Instagram COMPLETOS (15-30s)
Video: seguro_3wgwaxIfUJQ.mp4
"""
import json
import time
import subprocess
import sys
from pathlib import Path
import requests

VIRA_ROOT = Path("/home/_sebastian/proyectos/ViraClip")
VIDEO_PATH = VIRA_ROOT / "inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"
OUTPUT_DIR = VIRA_ROOT / "outputs/instagram_ready"
COMFYUI_URL = "http://localhost:8188"

def log(msg, level="INFO"):
    print(f"[{level}] {msg}")

def check_comfyui():
    """Verificar que ComfyUI está activo y responde"""
    try:
        r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        if r.status_code == 200:
            return True
    except:
        pass
    return False

def ensure_comfyui_running():
    """Asegurar que ComfyUI está corriendo"""
    if check_comfyui():
        return True
    
    log("ComfyUI no responde, reiniciando...", "WARNING")
    try:
        subprocess.run(
            ["docker-compose", "-f", str(VIRA_ROOT.parent / "CascadeProjects/ViraClip/docker-compose.yml"), "up", "-d", "comfyui"],
            cwd=str(VIRA_ROOT.parent / "CascadeProjects/ViraClip"),
            capture_output=True, timeout=30
        )
        log("Esperando 45s para inicialización...")
        time.sleep(45)
        return check_comfyui()
    except Exception as e:
        log(f"Error reiniciando: {e}", "ERROR")
        return False

def clear_queue():
    """Limpiar cola de ComfyUI"""
    try:
        requests.post(f"{COMFYUI_URL}/queue", json={"clear": True}, timeout=5)
    except:
        pass

def send_workflow(name, workflow_dict):
    """Enviar workflow a ComfyUI"""
    try:
        r = requests.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": workflow_dict},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("prompt_id")
        else:
            log(f"Error HTTP {r.status_code}: {r.text[:100]}", "ERROR")
    except Exception as e:
        log(f"Error enviando: {e}", "ERROR")
    return None

def wait_for_completion(prompt_id, timeout_sec=300):
    """Esperar a que el workflow termine usando history API"""
    start = time.time()
    last_status = None
    dots = 0

    while time.time() - start < timeout_sec:
        try:
            r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            if r.status_code == 200:
                history = r.json()
                if prompt_id in history:
                    item = history[prompt_id]
                    status = item.get('status', {})
                    
                    # Verificar si completó
                    if status.get('completed') or item.get('outputs'):
                        return True, "completed"
                    
                    # Verificar si hay error
                    if status.get('status_str') == 'error':
                        return False, f"error: {status}"
                    
                    # Mostrar progreso
                    current = status.get('status_str', 'processing')
                    if current != last_status:
                        log(f"Estado: {current}")
                        last_status = current
        except:
            pass

        # Mostrar puntos cada 10s
        if int(time.time() - start) % 10 == 0:
            dots += 1
            if dots % 6 == 0:  # Cada minuto
                elapsed = int(time.time() - start)
                log(f"... {elapsed//60}min esperando")
        
        time.sleep(2)

    return False, "timeout"

def create_workflow(name, video_file, frames, skip, crf):
    """Crear workflow para short de Instagram (15-30s)"""
    return {
        "1": {
            "inputs": {
                "video": video_file,
                "force_rate": 30,
                "frame_load_cap": frames,
                "force_size": "Custom",
                "custom_width": 1080,
                "custom_height": 1920,
                "skip_first_frames": skip,
                "select_every_nth": 1
            },
            "class_type": "VHS_LoadVideo"
        },
        "2": {
            "inputs": {
                "frame_rate": 30,
                "loop_count": 0,
                "filename_prefix": f"instagram_ready/{name}",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": crf,
                "pingpong": False,
                "save_output": True,
                "save_image": True,
                "images": ["1", 0]
            },
            "class_type": "VHS_VideoCombine"
        }
    }

def process_short(name, video_file, frames, skip, crf, duration_desc, timeout_override=None):
    """Procesar un solo short completo"""
    log(f"\n{'='*60}")
    log(f"🎬 {name}")
    log(f"   Duración: {duration_desc} ({frames} frames @ 30fps)")
    log(f"   Segmento: {skip//30}s - {(skip+frames)//30}s")
    log(f"{'='*60}")

    # 1. Verificar ComfyUI
    if not ensure_comfyui_running():
        log("ComfyUI no disponible", "ERROR")
        return False

    # 2. Limpiar cola
    clear_queue()
    time.sleep(1)

    # 3. Crear y enviar workflow
    workflow = create_workflow(name, video_file, frames, skip, crf)
    prompt_id = send_workflow(name, workflow)
    
    if not prompt_id:
        return False

    # 4. Calcular timeout dinámico: 10s por cada segundo de video + buffer
    # 15s video = 150s timeout, 30s video = 300s timeout
    base_timeout = timeout_override or (frames // 30 * 10 + 60)  # 10s por segundo + 60s buffer
    log(f"⏳ Timeout configurado: {base_timeout//60}min {base_timeout%60}s")
    
    success, status = wait_for_completion(prompt_id, timeout_sec=base_timeout)
    
    if not success:
        log(f"Falló: {status}", "ERROR")
        return False

    # 5. Verificar archivo generado
    time.sleep(2)  # Dar tiempo para escritura
    mp4_files = list(OUTPUT_DIR.glob(f"{name}*.mp4"))
    
    if mp4_files:
        f = mp4_files[0]
        size_mb = f.stat().st_size / (1024 * 1024)
        log(f"✅ Generado: {f.name} ({size_mb:.1f} MB)")
        return True
    else:
        log("No se encontró archivo de salida", "ERROR")
        return False

def main():
    print("="*60)
    print("VIRACLIP - Shorts Instagram COMPLETOS (15-30s)")
    print("Video: seguro_3wgwaxIfUJQ.mp4")
    print("="*60)

    if not VIDEO_PATH.exists():
        log(f"Video no encontrado: {VIDEO_PATH}", "ERROR")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Output: {OUTPUT_DIR}")

    # Definir 4 shorts de duración real (15-30 segundos cada uno)
    # Asumiendo video de ~5 minutos, extraemos segmentos distribuidos
    video_name = VIDEO_PATH.name

    shorts_config = [
        # (nombre, frames, skip_frames, crf, descripcion)
        ("instagram_hook", 450, 0, 23, "15s - Hook inicial"),           # 0-15s
        ("instagram_mid1", 600, 900, 23, "20s - Segmento medio 1"),   # 30-50s
        ("instagram_mid2", 600, 1800, 23, "20s - Segmento medio 2"),  # 60-80s
        ("instagram_viral", 900, 2700, 20, "30s - Mejor momento"),    # 90-120s (mejor calidad)
    ]

    generated = 0
    total = len(shorts_config)

    for i, (name, frames, skip, crf, desc) in enumerate(shorts_config, 1):
        log(f"\n🚀 Procesando {i}/{total}")
        
        # Para el último short (30s), usar timeout extendido de 8 minutos
        timeout_override = 480 if i == 4 else None
        
        if process_short(name, video_name, frames, skip, crf, desc, timeout_override):
            generated += 1
            log(f"✅ {i}/{total} completado exitosamente")
        else:
            log(f"❌ {i}/{total} falló", "ERROR")
            # Si falló el último, intentar una vez más con timeout aún mayor
            if i == 4:
                log("🔄 Reintentando último short con timeout extendido...")
                time.sleep(10)
                if process_short(name + "_retry", video_name, frames, skip, crf, desc, timeout_override=600):
                    generated += 1
                    log(f"✅ {i}/{total} completado en reintento")

        # Pausa entre shorts para estabilizar
        if i < total:
            log("⏸️  Pausa 5s entre shorts...")
            time.sleep(5)

    # RESUMEN FINAL
    print("\n" + "="*60)
    print("📊 RESUMEN FINAL")
    print("="*60)

    all_mp4s = list(OUTPUT_DIR.glob("*.mp4"))
    new_mp4s = [f for f in all_mp4s if any(s[0] in f.name for s in shorts_config)]
    
    log(f"Shorts generados: {len(new_mp4s)}/{total}")
    
    total_size = 0
    for f in sorted(new_mp4s):
        size_mb = f.stat().st_size / (1024 * 1024)
        total_size += size_mb
        duration_sec = (f.stat().st_size / (1024 * 1024 * 0.1))  # Estimación aproximada
        log(f"  📹 {f.name}")
        log(f"     └─ {size_mb:.1f} MB")

    if len(new_mp4s) == total:
        log(f"\n🎉 ¡ÉXITO TOTAL! {total} shorts listos para Instagram")
        log(f"💾 Tamaño total: {total_size:.1f} MB")
        return 0
    elif new_mp4s:
        log(f"\n⚠️  ÉXITO PARCIAL: {len(new_mp4s)}/{total} shorts generados")
        return 0
    else:
        log("\n❌ FALLA TOTAL: No se generó ningún short", "ERROR")
        return 1

if __name__ == "__main__":
    sys.exit(main())
