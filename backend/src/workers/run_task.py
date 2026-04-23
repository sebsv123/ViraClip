#!/usr/bin/env python3
"""
Wrapper para ejecutar process_video_task desde línea de comandos
Uso: python -m workers.run_task /path/to/task.json
"""
import asyncio
import json
import sys
from pathlib import Path

# Add src to path para imports absolutos
sys.path.insert(0, '/app')

from src.workers.tasks import process_video_task


async def main():
    task_file = sys.argv[1] if len(sys.argv) > 1 else "/app/task.json"
    
    print("🎬 INICIANDO PROCESAMIENTO VIRACLIP")
    print("=" * 50)
    
    # Cargar tarea
    with open(task_file) as f:
        task = json.load(f)
    
    print(f"📹 Video: {task.get('video_path', 'N/A')}")
    print(f"🎯 Plataforma: {task.get('platform', 'N/A')}")
    print("=" * 50)
    print()
    
    # Ejecutar
    try:
        result = await process_video_task(task)
        
        print()
        print("=" * 50)
        print("✅ RESULTADO:")
        print("=" * 50)
        print(json.dumps(result, indent=2, default=str))
        
        # Guardar resultado
        result_file = task_file.replace('.json', '_result.json')
        with open(result_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        print()
        print(f"💾 Resultado guardado en: {result_file}")
        print("🏁 PROCESO COMPLETADO")
        
    except Exception as e:
        print()
        print("=" * 50)
        print("❌ ERROR:")
        print("=" * 50)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
