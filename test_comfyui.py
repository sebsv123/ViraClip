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
    """Test 2: Enviar workflow LTXV de prueba"""
    print("\n🧪 Test 2: Workflow LTXV t2v de prueba...")
    
    # Cargar y modificar el workflow real
    import json
    workflow_path = Path(__file__).parent / "backend" / "comfy_workflows" / "ltxv_t2v_broll.json"
    
    with open(workflow_path) as f:
        workflow = json.load(f)
    
    # Reemplazar placeholders
    wf_str = json.dumps(workflow)
    wf_str = wf_str.replace("__POSITIVE_PROMPT__", "futuristic city neon lights vertical")
    wf_str = wf_str.replace("__THEME__", "tech")
    workflow = json.loads(wf_str)
    
    try:
        result = await comfyui_orchestrator._execute(workflow, "test_ltxv_task", "mp4")
        print(f"✅ Workflow ejecutado: {result}")
        return True
    except Exception as e:
        print(f"❌ Error en workflow: {e}")
        import traceback
        traceback.print_exc()
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
