#!/usr/bin/env python3
"""
Test de integración ViraClip + ComfyUI
Ejecutar: python test_comfyui.py
"""

import asyncio
import sys
from pathlib import Path

# Añadir backend al path
sys.path.insert(0, str(Path(__file__).parent / "backend" / "src"))

from services.comfyui.orchestrator import comfyui_orchestrator


async def test_health():
    """Test 1: Verificar ComfyUI responde"""
    print("🧪 Test 1: Health Check...")
    health = await comfyui_orchestrator.health_check()
    
    if health.get("status") == "ok":
        print("✅ ComfyUI está corriendo")
        data = health.get("data", {})
        if "devices" in data:
            for dev in data.get("devices", []):
                print(f"   GPU: {dev.get('name')} - VRAM: {dev.get('vram_total', 0)/1024**3:.1f} GB")
        return True
    else:
        print(f"❌ Error: {health}")
        return False


async def test_workflow_simple():
    """Test 2: Enviar workflow simple de prueba"""
    print("\n🧪 Test 2: Workflow de prueba...")
    
    # Workflow mínimo: generar una imagen vacía
    test_workflow = {
        "1": {
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
            "class_type": "EmptyLatentImage"
        },
        "2": {
            "inputs": {"samples": ["1", 0], "vae_name": "taesd"},
            "class_type": "VAEDecode"
        },
        "3": {
            "inputs": {"filename_prefix": "test", "images": ["2", 0]},
            "class_type": "SaveImage"
        }
    }
    
    try:
        result = await comfyui_orchestrator._execute(test_workflow, "test_task", "png")
        print(f"✅ Workflow ejecutado: {result}")
        return True
    except Exception as e:
        print(f"❌ Error en workflow: {e}")
        return False


async def main():
    """Ejecutar todos los tests"""
    print("="*60)
    print("  Test de Integración ViraClip + ComfyUI")
    print("="*60)
    print()
    
    results = []
    
    # Test 1: Health
    results.append(await test_health())
    
    # Test 2: Solo si health OK
    if results[0]:
        results.append(await test_workflow_simple())
    else:
        print("\n⚠️  Saltando test de workflow (ComfyUI no responde)")
        results.append(False)
    
    # Resumen
    print("\n" + "="*60)
    passed = sum(results)
    total = len(results)
    print(f"  Resultado: {passed}/{total} tests pasaron")
    
    if passed == total:
        print("  ✅ Integración ViraClip + ComfyUI funcionando")
    else:
        print("  ⚠️  Algunos tests fallaron")
    print("="*60)
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
