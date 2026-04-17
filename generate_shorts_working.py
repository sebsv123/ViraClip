#!/usr/bin/env python3
"""
ViraClip - Generador REAL de Shorts MP4 (Versión Estable)
Usa workflows pequeños para evitar crashes de VRAM
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
    """Verificar que ComfyUI está activo"""
    try:
        r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        if r.status_code == 200:
            data = r.json()
            gpu = data.get('devices', [{}])[0].get('name', 'Unknown')
            log(f"ComfyUI activo - GPU: {gpu}")
            return True
    except Exception as e:
        log(f"ComfyUI no responde: {e}", "ERROR")
    return False

def clear_queue():
    """Limpiar cola de ComfyUI"""
    try:
        requests.post(f"{COMFYUI_URL}/queue", json={"clear": True}, timeout=5)
        log("Cola limpiada")
    except:
        pass

def send_workflow(name, workflow_dict):
    """Enviar workflow a ComfyUI y retornar prompt_id"""
    try:
        r = requests.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": workflow_dict},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            prompt_id = data.get("prompt_id")
            log(f"{name}: Prompt ID {prompt_id[:20]}...")
            return prompt_id
        else:
            log(f"{name}: Error {r.status_code} - {r.text[:100]}", "ERROR")
    except Exception as e:
        log(f"{name}: Error enviando - {e}", "ERROR")
    return None

def wait_for_files(expected_prefix, timeout_sec=180):
    """Esperar hasta que aparezcan archivos MP4 en el volumen montado"""
    log(f"Esperando archivos con prefijo '{expected_prefix}'...")
    start = time.time()
    check_interval = 5
    last_count = 0

    while time.time() - start < timeout_sec:
        # Buscar en el volumen montado del HOST (más rápido que consultar API)
        mp4_files = list(OUTPUT_DIR.glob(f"{expected_prefix}*.mp4"))
        if mp4_files:
            log(f"✅ Encontrados {len(mp4_files)} archivo(s)!")
            for f in mp4_files:
                log(f"   → {f.name} ({f.stat().st_size // 1024} KB)")
            return True

        # Mostrar progreso cada 30s
        elapsed = int(time.time() - start)
        if elapsed % 30 == 0 and elapsed != last_count:
            log(f"... {elapsed}s esperando")
            last_count = elapsed

        time.sleep(check_interval)

    log(f"Timeout después de {timeout_sec}s", "WARNING")
    return False

def create_workflow(name, video_file, frames=100, skip=0, crf=23):
    """Crear workflow simple y estable"""
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

def generate_one_short(name, video_file, frames, skip, crf):
    """Generar un solo short de forma segura"""
    log(f"\n🎬 Generando: {name}")
    log(f"   Frames: {frames}, Skip: {skip}, CRF: {crf}")

    # Verificar ComfyUI
    if not check_comfyui():
        log("ComfyUI no disponible, abortando", "ERROR")
        return False

    # Crear y enviar workflow
    workflow = create_workflow(name, video_file, frames, skip, crf)
    prompt_id = send_workflow(name, workflow)

    if not prompt_id:
        return False

    # Esperar a que aparezca el archivo
    if wait_for_files(name, timeout_sec=180):
        return True

    # Si no apareció, verificar si hay error en history
    try:
        r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
        if r.status_code == 200:
            history = r.json()
            if prompt_id in history:
                status = history[prompt_id].get('status', {})
                if status.get('status_str') == 'error':
                    log(f"Workflow falló: {status}", "ERROR")
                else:
                    log(f"Estado: {status}")
    except:
        pass

    return False

def main():
    print("="*60)
    print("VIRACLIP - Generador REAL de Shorts MP4")
    print("="*60)

    # Verificar video
    if not VIDEO_PATH.exists():
        log(f"Video no encontrado: {VIDEO_PATH}", "ERROR")
        return 1

    log(f"Video: {VIDEO_PATH.name}")
    log(f"Output: {OUTPUT_DIR}")

    # Asegurar directorio output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Limpiar cola
    clear_queue()

    # Generar 4 shorts con frames reducidos (evitar OOM)
    # 100 frames ≈ 3-4 segundos de video (suficiente para tests)
    video_name = VIDEO_PATH.name

    tasks = [
        ("short_1_reframe", 100, 0, 23),      # 100 frames, inicio, calidad normal
        ("short_2_clean", 100, 100, 23),      # 100 frames, offset 100
        ("short_3_segment", 100, 200, 23),    # 100 frames, offset 200
        ("short_4_full", 120, 300, 20),       # 120 frames, offset 300, mejor calidad
    ]

    generated = 0
    for name, frames, skip, crf in tasks:
        if generate_one_short(name, video_file=video_name, frames=frames, skip=skip, crf=crf):
            generated += 1
            log(f"✅ {name} completado ({generated}/4)")
        else:
            log(f"❌ {name} falló", "ERROR")

        # Pequeña pausa entre workflows
        time.sleep(2)

    # Resumen final
    print("\n" + "="*60)
    print("RESUMEN FINAL")
    print("="*60)

    mp4_files = list(OUTPUT_DIR.glob("*.mp4"))
    log(f"MP4s generados: {len(mp4_files)}/4")

    for f in sorted(mp4_files):
        size_mb = f.stat().st_size / (1024 * 1024)
        log(f"  📹 {f.name} ({size_mb:.1f} MB)")

    if len(mp4_files) >= 4:
        log("\n🎉 ¡ÉXITO! Todos los shorts generados")
        return 0
    else:
        log(f"\n⚠️  Solo {len(mp4_files)}/4 shorts generados", "WARNING")
        return 1

if __name__ == "__main__":
    sys.exit(main())
