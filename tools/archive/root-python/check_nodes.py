#!/usr/bin/env python3
"""Verificar qué nodos VHS están disponibles en ComfyUI"""
import requests
import json

url = "http://localhost:8188/object_info"
try:
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        vhs_nodes = [k for k in data.keys() if 'VHS' in k or 'Video' in k]
        print("Nodos VHS/Video disponibles:")
        for node in sorted(vhs_nodes):
            print(f"  - {node}")
    else:
        print(f"Error: {resp.status_code}")
except Exception as e:
    print(f"Error: {e}")
