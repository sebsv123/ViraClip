#!/usr/bin/env python3
"""
Script simple para ejecutar worker de ViraClip directamente
"""
import asyncio
import json
import sys
# Estamos en /app/src, agregar al path para imports
if '/app/src' not in sys.path:
    sys.path.insert(0, '/app/src')

# Cambiar al directorio correcto para imports relativos
import os
os.chdir('/app/src')

from workers.tasks import process_video_task

async def main():
    # Cargar tarea
    with open('/app/task.json') as f:
        task = json.load(f)
    
    print("🎬 INICIANDO PROCESAMIENTO VIRACLIP")
    print("=" * 50)
    print(f"📹 Video: {task['video_path']}")
    print(f"🎯 Plataforma: {task['platform']}")
    print(f"⚙️  Opciones: {json.dumps(task['options'], indent=2)}")
    print("=" * 50)
    print("")
    
    # Ejecutar
    try:
        result = await process_video_task(task)
        
        print("")
        print("=" * 50)
        print("✅ RESULTADO:")
        print("=" * 50)
        print(json.dumps(result, indent=2, default=str))
        
        # Guardar resultado
        with open('/app/result.json', 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        print("")
        print("💾 Resultado guardado en: /app/result.json")
        print("🏁 PROCESO COMPLETADO")
        
    except Exception as e:
        print(f"")
        print("=" * 50)
        print("❌ ERROR:")
        print("=" * 50)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
