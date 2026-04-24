#!/usr/bin/env python3
"""
Generador REAL de shorts MP4 para Instagram
Usa ComfyUI API para generar archivos físicos .mp4

USO:
    python3 generate_real_shorts.py

REQUIERE:
    - ComfyUI corriendo en http://localhost:8188
    - Docker mapeando: ./outputs:/comfyui/output
    - Video en ~/proyectos/ViraClip/uploads/seguro_3wgwaxIfUJQ.mp4
"""

import json
import time
import sys
import shutil
import subprocess
from pathlib import Path
import requests


# Configuración
VIRA_ROOT = Path("~/proyectos/ViraClip").expanduser()
COMFYUI_URL = "http://localhost:8188"
OUTPUT_DIR = VIRA_ROOT / "outputs" / "instagram_ready"
UPLOADS_DIR = VIRA_ROOT / "uploads"
WORKFLOWS_DIR = VIRA_ROOT / "comfyui" / "workflows"


def log(msg, level="INFO"):
    """Logging simple"""
    print(f"[{level}] {msg}", flush=True)


def check_comfyui():
    """Verificar que ComfyUI está activo"""
    try:
        response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        if response.status_code == 200:
            data = response.json()
            devices = data.get("devices", [])
            if devices:
                gpu = devices[0]
                log(f"ComfyUI activo - GPU: {gpu.get('name', 'Unknown')}")
                return True
    except Exception as e:
        log(f"ComfyUI no responde: {e}", "ERROR")
    return False


def check_video():
    """Verificar que el video existe en uploads"""
    video_path = UPLOADS_DIR / "seguro_3wgwaxIfUJQ.mp4"
    if video_path.exists():
        size_mb = video_path.stat().st_size / 1024**2
        log(f"Video listo: {video_path.name} ({size_mb:.1f} MB)")
        return True

    # Intentar copiar desde inputs
    source = VIRA_ROOT / "inputs" / "test_videos" / "seguro_3wgwaxIfUJQ.mp4"
    if source.exists():
        log(f"Copiando video desde inputs...")
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, video_path)
        log(f"Video copiado a uploads/")
        return True

    log(f"Video NO encontrado en {source}", "ERROR")
    return False


def create_workflow_files():
    """Crear archivos JSON de workflows"""
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

    workflows = {
        "short_1_reframe.json": {
            "prompt": {
                "1": {
                    "inputs": {
                        "video": "seguro_3wgwaxIfUJQ.mp4",
                        "force_rate": 30,
                        "frame_load_cap": 750,
                        "force_size": "Custom",
                        "custom_width": 1080,
                        "custom_height": 1920,
                        "skip_first_frames": 0,
                        "select_every_nth": 1
                    },
                    "class_type": "VHS_LoadVideo"
                },
                "2": {
                    "inputs": {
                        "frame_rate": 30,
                        "loop_count": 0,
                        "filename_prefix": "instagram_ready/short_1_reframe",
                        "format": "video/h264-mp4",
                        "pix_fmt": "yuv420p",
                        "crf": 23,
                        "pingpong": False,
                        "save_output": True,
                        "save_image": True,
                        "images": ["1", 0]
                    },
                    "class_type": "VHS_VideoCombine"
                }
            }
        },
        "short_2_clean.json": {
            "prompt": {
                "1": {
                    "inputs": {
                        "video": "seguro_3wgwaxIfUJQ.mp4",
                        "force_rate": 30,
                        "frame_load_cap": 600,
                        "force_size": "Custom",
                        "custom_width": 1080,
                        "custom_height": 1920,
                        "skip_first_frames": 0,
                        "select_every_nth": 1
                    },
                    "class_type": "VHS_LoadVideo"
                },
                "2": {
                    "inputs": {
                        "frame_rate": 30,
                        "loop_count": 0,
                        "filename_prefix": "instagram_ready/short_2_clean",
                        "format": "video/h264-mp4",
                        "pix_fmt": "yuv420p",
                        "crf": 23,
                        "pingpong": False,
                        "save_output": True,
                        "save_image": True,
                        "images": ["1", 0]
                    },
                    "class_type": "VHS_VideoCombine"
                }
            }
        },
        "short_3_segment.json": {
            "prompt": {
                "1": {
                    "inputs": {
                        "video": "seguro_3wgwaxIfUJQ.mp4",
                        "force_rate": 30,
                        "frame_load_cap": 600,
                        "skip_first_frames": 150,
                        "select_every_nth": 1,
                        "force_size": "Custom",
                        "custom_width": 1080,
                        "custom_height": 1920
                    },
                    "class_type": "VHS_LoadVideo"
                },
                "2": {
                    "inputs": {
                        "frame_rate": 30,
                        "loop_count": 0,
                        "filename_prefix": "instagram_ready/short_3_segment",
                        "format": "video/h264-mp4",
                        "pix_fmt": "yuv420p",
                        "crf": 23,
                        "pingpong": False,
                        "save_output": True,
                        "save_image": True,
                        "images": ["1", 0]
                    },
                    "class_type": "VHS_VideoCombine"
                }
            }
        },
        "short_4_full.json": {
            "prompt": {
                "1": {
                    "inputs": {
                        "video": "seguro_3wgwaxIfUJQ.mp4",
                        "force_rate": 30,
                        "frame_load_cap": 900,
                        "force_size": "Custom",
                        "custom_width": 1080,
                        "custom_height": 1920,
                        "skip_first_frames": 0,
                        "select_every_nth": 1
                    },
                    "class_type": "VHS_LoadVideo"
                },
                "2": {
                    "inputs": {
                        "frame_rate": 30,
                        "loop_count": 0,
                        "filename_prefix": "instagram_ready/short_4_full",
                        "format": "video/h264-mp4",
                        "pix_fmt": "yuv420p",
                        "crf": 20,
                        "pingpong": False,
                        "save_output": True,
                        "save_image": True,
                        "images": ["1", 0]
                    },
                    "class_type": "VHS_VideoCombine"
                }
            }
        }
    }

    created = 0
    for filename, workflow in workflows.items():
        filepath = WORKFLOWS_DIR / filename
        with open(filepath, 'w') as f:
            json.dump(workflow, f, indent=2)
        created += 1
        log(f"Workflow creado: {filename}")

    return created == 4


def execute_workflow(workflow_file, description):
    """Ejecutar un workflow y esperar resultado"""
    log(f"\n🎬 {description}")

    # Cargar workflow
    with open(workflow_file, 'r') as f:
        workflow = json.load(f)

    try:
        # El workflow ya tiene la estructura correcta: { "prompt": { "1": {...}, ... } }
        response = requests.post(
            f"{COMFYUI_URL}/prompt",
            json=workflow,
            timeout=30
        )
        if response.status_code != 200:
            log(f"Error HTTP: {response.status_code}", "ERROR")
            log(f"Respuesta: {response.text[:500]}", "ERROR")
            return False

        result = response.json()
        prompt_id = result.get("prompt_id")

        if not prompt_id:
            log("No se obtuvo prompt_id", "ERROR")
            return False

        log(f"Prompt ID: {prompt_id[:20]}...")

    except Exception as e:
        log(f"Error enviando workflow: {e}", "ERROR")
        return False

    # Polling de estado
    print("[INFO] ⏳ Esperando procesamiento...", end="", flush=True)
    max_attempts = 240  # 20 minutos máximo (5s x 240)
    attempts = 0
    completed = False
    status_checked = 0

    while attempts < max_attempts and not completed:
        time.sleep(5)
        attempts += 1
        if attempts % 12 == 0:  # Cada minuto mostrar punto
            print(".", end="", flush=True)
            status_checked += 1
            if status_checked % 5 == 0:
                print(f"[{status_checked}m]", end="", flush=True)

        try:
            # ComfyUI history endpoint
            response = requests.get(
                f"{COMFYUI_URL}/history/{prompt_id}",
                timeout=10
            )
            if response.status_code == 200:
                history = response.json()
                # Verificar si el prompt_id está en el history
                if prompt_id in history:
                    item = history[prompt_id]
                    # Verificar si tiene outputs o status completado
                    if item.get("outputs") or item.get("status", {}).get("completed", False):
                        completed = True
                        break
                    # También verificar si hay error
                    if item.get("status", {}).get("status_str") == "error":
                        log(f"\n[ERROR] Workflow falló: {item.get('status', {})}", "ERROR")
                        return False
        except Exception as e:
            if attempts % 20 == 0:  # Log errores cada 100s
                print(f"[e:{type(e).__name__[:3]}]", end="", flush=True)
            pass

    print()  # Nueva línea después de los puntos

    if not completed:
        log(f"Timeout esperando resultado después de {attempts*5//60} minutos", "WARNING")
        # Intentar verificar una última vez
        try:
            response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            if response.status_code == 200:
                history = response.json()
                if prompt_id in history and history[prompt_id].get("outputs"):
                    log("✅ Workflow completado (verificación final)")
                    return True
        except:
            pass
        return False

    log("✅ Workflow completado")
    return True


def verify_outputs():
    """Verificar que los MP4s existen"""
    log("\n📁 Verificando archivos generados...")

    mp4_files = list(OUTPUT_DIR.glob("*.mp4"))

    if not mp4_files:
        log("No se encontraron archivos MP4", "ERROR")

        # Verificar en contenedor
        log("🔍 Verificando contenedor...")
        try:
            result = subprocess.run(
                ["docker", "exec", "viraclip-comfyui", "ls", "-la", "/comfyui/output/instagram_ready/"],
                capture_output=True,
                text=True,
                timeout=10
            )
            log(f"Contenido del contenedor:\n{result.stdout}")
        except Exception as e:
            log(f"No se pudo acceder al contenedor: {e}", "ERROR")

        return 0

    log(f"✅ {len(mp4_files)} MP4s encontrados:")
    for mp4 in sorted(mp4_files):
        size_mb = mp4.stat().st_size / 1024**2
        log(f"   📹 {mp4.name} ({size_mb:.1f} MB)")

    return len(mp4_files)


def main():
    """Función principal"""
    print("="*60)
    print("VIRACLIP - Generador REAL de Shorts MP4")
    print("="*60)

    # 1. Verificar entorno
    log("\n🔍 Verificando entorno...")

    if not check_comfyui():
        log("ComfyUI no está disponible", "ERROR")
        log("Inicia ComfyUI: docker compose up -d comfyui")
        return 1

    if not check_video():
        return 1

    # 2. Crear workflows
    if not create_workflow_files():
        log("Error creando workflows", "ERROR")
        return 1

    # 3. Ejecutar workflows
    log("\n🚀 Generando 4 shorts...")

    workflows = [
        (WORKFLOWS_DIR / "short_1_reframe.json", "Short 1: Reframe 9x16 básico"),
        (WORKFLOWS_DIR / "short_2_clean.json", "Short 2: Clean lanczos"),
        (WORKFLOWS_DIR / "short_3_segment.json", "Short 3: Segmento específico"),
        (WORKFLOWS_DIR / "short_4_full.json", "Short 4: Full quality"),
    ]

    success_count = 0
    for workflow_file, description in workflows:
        if execute_workflow(workflow_file, description):
            success_count += 1

    # 4. Verificar resultados
    mp4_count = verify_outputs()

    # 5. Resumen
    print("\n" + "="*60)
    print("RESUMEN FINAL")
    print("="*60)
    print(f"✅ Workflows ejecutados: {success_count}/4")
    print(f"📹 MP4s generados: {mp4_count}")
    print(f"📁 Ubicación: {OUTPUT_DIR}")

    if mp4_count >= 4:
        print("\n🎉 TODOS LOS SHORTS LISTOS PARA INSTAGRAM!")
        return 0
    else:
        print(f"\n⚠️  Solo {mp4_count}/4 shorts generados")
        print("Revisa los logs de ComfyUI para más detalles")
        return 1


if __name__ == "__main__":
    sys.exit(main())
