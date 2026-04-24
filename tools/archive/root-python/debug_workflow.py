#!/usr/bin/env python3
"""Script de debug para ver el error exacto de ComfyUI"""
import requests
import json

# Test 1: Verificar que ComfyUI responde
print("="*60)
print("TEST 1: Verificando ComfyUI")
print("="*60)
try:
    r = requests.get("http://localhost:8188/system_stats", timeout=5)
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"GPU: {data.get('devices', [{}])[0].get('name', 'N/A')}")
except Exception as e:
    print(f"ERROR: {e}")

# Test 2: Ver nodos VHS disponibles
print("\n" + "="*60)
print("TEST 2: Nodos VHS disponibles")
print("="*60)
try:
    r = requests.get("http://localhost:8188/object_info", timeout=10)
    data = r.json()
    vhs_nodes = [k for k in data.keys() if 'VHS' in k]
    print(f"Total nodos VHS: {len(vhs_nodes)}")
    for node in vhs_nodes[:10]:
        print(f"  - {node}")
except Exception as e:
    print(f"ERROR: {e}")

# Test 3: Enviar workflow simple y ver error exacto
print("\n" + "="*60)
print("TEST 3: Enviando workflow de prueba")
print("="*60)

workflow = {
    "prompt": {
        "1": {
            "inputs": {
                "video": "seguro_3wgwaxIfUJQ.mp4",
                "force_rate": 30,
                "frame_load_cap": 300
            },
            "class_type": "VHS_LoadVideo"
        },
        "2": {
            "inputs": {
                "frame_rate": 30,
                "filename_prefix": "test_output",
                "format": "video/h264-mp4",
                "save_output": True,
                "images": ["1", 0]
            },
            "class_type": "VHS_VideoCombine"
        }
    }
}

print("Payload enviado:")
print(json.dumps(workflow, indent=2))
print()

try:
    r = requests.post(
        "http://localhost:8188/prompt",
        json=workflow,
        timeout=30
    )
    print(f"Status Code: {r.status_code}")
    print(f"Respuesta:")
    try:
        resp_data = r.json()
        print(json.dumps(resp_data, indent=2))
    except:
        print(r.text[:1000])
except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "="*60)
print("DIAGNÓSTICO COMPLETADO")
print("="*60)
