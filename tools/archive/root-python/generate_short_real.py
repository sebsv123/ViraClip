#!/usr/bin/env python3
"""
ViraClip - Generación de un short real 9:16 con audio + música de fondo.

Pipeline:
  A. VHS_LoadVideo + VHS_VideoCombine → short_final.mp4 (1080x1920, 25s, audio)
  B. ffmpeg mezcla música de fondo (bgm_energetic_hype.mp3, volume=0.15)
  C. Verificación final de los MP4 físicos en ~/proyectos/ViraClip/outputs/
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

import requests

# ─────────────────────────────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────────────────────────────
COMFYUI_URL = "http://localhost:8188"
VIDEO_INPUT = "seguro_3wgwaxIfUJQ.mp4"  # Ya está en /comfyui/input/

HOST_OUTPUT_DIR = Path.home() / "proyectos" / "ViraClip" / "outputs"
BGM_PATH = Path.home() / "CascadeProjects" / "ViraClip" / "backend" / "music" / "bgm" / "bgm_energetic_hype.mp3"

FILENAME_PREFIX = "short_final"
FRAME_LOAD_CAP = 750      # 25 segundos a 30 fps
CUSTOM_WIDTH = 1080
CUSTOM_HEIGHT = 1920
POLL_INTERVAL = 5         # segundos
POLL_MAX_ATTEMPTS = 60    # 60 * 5s = 5 minutos


# ─────────────────────────────────────────────────────────────────────────────
# PASO A — Generar short base con VHS_LoadVideo + VHS_VideoCombine
# ─────────────────────────────────────────────────────────────────────────────
def step_a_generate_base_short() -> Path:
    print("━" * 60)
    print("PASO A — Generando short base con ComfyUI VHS")
    print("━" * 60)

    workflow = {
        "prompt": {
            "1": {
                "class_type": "VHS_LoadVideo",
                "inputs": {
                    "video": VIDEO_INPUT,
                    "force_rate": 30,
                    "custom_width": CUSTOM_WIDTH,
                    "custom_height": CUSTOM_HEIGHT,
                    "frame_load_cap": FRAME_LOAD_CAP,
                    "skip_first_frames": 0,
                    "select_every_nth": 1,
                },
            },
            "2": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["1", 0],
                    "audio": ["1", 2],          # índice 2 = AUDIO (confirmado)
                    "frame_rate": 30,
                    "loop_count": 0,
                    "filename_prefix": FILENAME_PREFIX,
                    "format": "video/h264-mp4",
                    "pix_fmt": "yuv420p",
                    "crf": 23,
                    "save_metadata": False,
                    "pingpong": False,
                    "save_output": True,
                },
            },
        }
    }

    print(f"  Video input     : {VIDEO_INPUT}")
    print(f"  Resolución      : {CUSTOM_WIDTH}x{CUSTOM_HEIGHT}")
    print(f"  Frames          : {FRAME_LOAD_CAP} ({FRAME_LOAD_CAP/30:.1f}s @ 30fps)")
    print(f"  Filename prefix : {FILENAME_PREFIX}")
    print()

    # Enviar workflow
    r = requests.post(f"{COMFYUI_URL}/prompt", json=workflow)
    print(f"HTTP Status: {r.status_code}")
    print(f"Response   : {r.text[:400]}")
    if r.status_code != 200:
        print("❌ ERROR: ComfyUI rechazó el workflow")
        sys.exit(1)

    prompt_id = r.json().get("prompt_id")
    print(f"Prompt ID  : {prompt_id}")
    print()

    # Polling
    for i in range(POLL_MAX_ATTEMPTS):
        time.sleep(POLL_INTERVAL)
        hist = requests.get(f"{COMFYUI_URL}/history/{prompt_id}").json()
        if prompt_id in hist:
            status = hist[prompt_id].get("status", {})
            outputs = hist[prompt_id].get("outputs", {})
            if outputs:
                print(f"✅ OUTPUTS recibidos después de {(i+1)*POLL_INTERVAL}s")
                print(json.dumps(outputs, indent=2))
                # Extraer filename del output del nodo 2
                node2 = outputs.get("2", {})
                gifs = node2.get("gifs") or node2.get("videos") or []
                if not gifs:
                    print("❌ No se encontró 'gifs'/'videos' en outputs del nodo 2")
                    sys.exit(1)
                filename = gifs[0]["filename"]
                subfolder = gifs[0].get("subfolder", "")
                # Construir path real en el host
                host_path = HOST_OUTPUT_DIR / subfolder / filename if subfolder else HOST_OUTPUT_DIR / filename
                print(f"\n📁 Archivo generado: {host_path}")
                if not host_path.exists():
                    print(f"❌ Archivo no existe en el host: {host_path}")
                    sys.exit(1)
                size_mb = host_path.stat().st_size / 1024 / 1024
                print(f"📊 Tamaño: {size_mb:.2f} MB")
                return host_path
            if status.get("status_str") == "error":
                print(f"❌ ERROR en ComfyUI:\n{json.dumps(hist[prompt_id], indent=2)}")
                sys.exit(1)
        print(f"  Esperando... {(i+1)*POLL_INTERVAL}s", end="\r", flush=True)

    print("\n❌ Timeout: 5 minutos sin resultado")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# PASO B — Añadir música de fondo con ffmpeg
# ─────────────────────────────────────────────────────────────────────────────
def step_b_add_background_music(input_mp4: Path) -> Path:
    print()
    print("━" * 60)
    print("PASO B — Añadiendo música de fondo con ffmpeg")
    print("━" * 60)

    if not BGM_PATH.exists():
        print(f"❌ BGM no existe: {BGM_PATH}")
        sys.exit(1)

    output_mp4 = input_mp4.with_name(f"{input_mp4.stem}_bgm.mp4")

    print(f"  Input  : {input_mp4}")
    print(f"  BGM    : {BGM_PATH.name} ({BGM_PATH.stat().st_size/1024:.0f} KB)")
    print(f"  Output : {output_mp4}")
    print()

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_mp4),
        "-i", str(BGM_PATH),
        "-filter_complex",
        "[1:a]volume=0.15[bgm];[0:a][bgm]amix=inputs=2:duration=first",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_mp4),
    ]

    print("Ejecutando ffmpeg...")
    print("  " + " ".join(cmd))
    print()

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ ffmpeg falló:")
        print(result.stderr[-2000:])
        sys.exit(1)

    print(result.stderr[-600:])  # ffmpeg escribe en stderr
    print()

    if not output_mp4.exists():
        print(f"❌ Output no existe: {output_mp4}")
        sys.exit(1)

    size_mb = output_mp4.stat().st_size / 1024 / 1024
    print(f"✅ Música añadida: {output_mp4} ({size_mb:.2f} MB)")
    return output_mp4


# ─────────────────────────────────────────────────────────────────────────────
# PASO C — Verificación final
# ─────────────────────────────────────────────────────────────────────────────
def step_c_verify():
    print()
    print("━" * 60)
    print("PASO C — Verificación final (archivos en disco)")
    print("━" * 60)
    print()

    base = HOST_OUTPUT_DIR
    if not base.exists():
        print(f"❌ Directorio no existe: {base}")
        return

    print(f"Contenido de {base}:")
    found_any = False
    for f in sorted(os.listdir(base)):
        full = base / f
        if full.is_file() and f.endswith(".mp4"):
            size_mb = full.stat().st_size / 1024 / 1024
            print(f"  {f}: {size_mb:.1f} MB")
            found_any = True

    if not found_any:
        print("  (no se encontraron MP4 en raíz, listando subdirectorios)")
        for f in sorted(os.listdir(base)):
            full = base / f
            if full.is_dir():
                print(f"  [dir] {f}/")
                for sub in sorted(os.listdir(full)):
                    sub_path = full / sub
                    if sub_path.is_file() and sub.endswith(".mp4"):
                        size_mb = sub_path.stat().st_size / 1024 / 1024
                        print(f"    {sub}: {size_mb:.1f} MB")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # Verificar prerequisitos
    print("Verificando prerequisitos...")
    if not BGM_PATH.exists():
        print(f"❌ BGM no encontrado: {BGM_PATH}")
        sys.exit(1)
    # Verificar ffmpeg
    if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0:
        print("❌ ffmpeg no está instalado en el host")
        print("   Instala con: sudo pacman -S ffmpeg --noconfirm")
        sys.exit(1)
    print("  ffmpeg      : OK")
    print(f"  BGM         : {BGM_PATH.name}")
    print(f"  ComfyUI URL : {COMFYUI_URL}")
    print()

    base_mp4 = step_a_generate_base_short()
    final_mp4 = step_b_add_background_music(base_mp4)
    step_c_verify()

    print()
    print("━" * 60)
    print("RESULTADO FINAL")
    print("━" * 60)
    print(f"✅ Short base     : {base_mp4} ({base_mp4.stat().st_size/1024/1024:.2f} MB)")
    print(f"✅ Short + música : {final_mp4} ({final_mp4.stat().st_size/1024/1024:.2f} MB)")


if __name__ == "__main__":
    main()
