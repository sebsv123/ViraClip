#!/usr/bin/env python3
"""Test rápido para verificar si ComfyUI procesa workflows correctamente"""
import requests
import json
import time

COMFYUI_URL = "http://localhost:8188"

# 1. Verificar estado de la cola
print("="*60)
print("1. ESTADO DE LA COLA")
print("="*60)
try:
    r = requests.get(f"{COMFYUI_URL}/queue", timeout=5)
    data = r.json()
    print(f"Running: {len(data.get('queue_running', []))}")
    print(f"Pending: {len(data.get('queue_pending', []))}")
except Exception as e:
    print(f"Error: {e}")

# 2. Verificar history reciente
print("\n" + "="*60)
print("2. HISTORY RECIENTE")
print("="*60)
try:
    r = requests.get(f"{COMFYUI_URL}/history", timeout=10)
    data = r.json()
    print(f"Total items en history: {len(data)}")
    for prompt_id, item in list(data.items())[-3:]:  # Últimos 3
        print(f"\n  ID: {prompt_id[:20]}...")
        print(f"  Status: {item.get('status', {}).get('status_str', 'unknown')}")
        print(f"  Outputs: {len(item.get('outputs', {}))} archivos")
        if item.get('outputs'):
            for node_id, output in item['outputs'].items():
                print(f"    - Node {node_id}: {output}")
except Exception as e:
    print(f"Error: {e}")

# 3. Buscar archivos en el contenedor
print("\n" + "="*60)
print("3. ARCHIVOS EN CONTENEDOR")
print("="*60)
import subprocess
result = subprocess.run(
    ["docker", "exec", "viraclip-comfyui", "find", "/comfyui/output", "-name", "*.mp4", "-o", "-name", "*.png"],
    capture_output=True, text=True, timeout=10
)
if result.stdout.strip():
    print("Archivos encontrados:")
    for line in result.stdout.strip().split('\n'):
        print(f"  {line}")
else:
    print("No se encontraron archivos de salida")

# 4. Enviar workflow MUY simple (10 frames solo)
print("\n" + "="*60)
print("4. TEST WORKFLOW MINI (10 frames)")
print("="*60)
simple_workflow = {
    "prompt": {
        "1": {
            "inputs": {
                "video": "seguro_3wgwaxIfUJQ.mp4",
                "force_rate": 30,
                "frame_load_cap": 10,  # Solo 10 frames!
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
                "filename_prefix": "test_mini",
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
}

try:
    r = requests.post(f"{COMFYUI_URL}/prompt", json=simple_workflow, timeout=10)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        prompt_id = data.get('prompt_id', 'unknown')
        print(f"Prompt ID: {prompt_id[:30]}...")
        print("Esperando 30 segundos...")
        time.sleep(30)
        
        # Verificar si terminó
        r2 = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
        if r2.status_code == 200:
            history = r2.json()
            print(f"\nResultado:")
            print(f"  En history: {prompt_id in history}")
            if prompt_id in history:
                item = history[prompt_id]
                print(f"  Status: {item.get('status', {})}")
                print(f"  Outputs: {item.get('outputs', {})}")
    else:
        print(f"Error: {r.text[:300]}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "="*60)
print("DIAGNÓSTICO COMPLETADO")
print("="*60)
