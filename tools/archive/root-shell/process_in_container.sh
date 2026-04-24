#!/bin/bash
# Script que se ejecuta DENTRO del contenedor para evitar problemas de import

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip E2E Processing"
echo "=========================================="
echo "📹 URL: $VIDEO_URL"
echo ""

# 1. Descargar video
echo "1️⃣  Descargando video..."
yt-dlp -f 'best[height<=1080][ext=mp4]/best' -o "$WORKDIR/video.%(ext)s" "$VIDEO_URL" 2>&1 | tail -3
VIDEO=$(ls "$WORKDIR"/*.* | head -1)
echo "   ✅ $(basename $VIDEO)"
echo ""

# 2. Copiar al contenedor
echo "2️⃣  Copiando a contenedor..."
docker cp "$VIDEO" viraclip-worker:/app/uploads/video.mp4
echo "   ✅ Video en worker"
echo ""

# 3. Crear script de procesamiento dentro del contenedor
echo "3️⃣  Preparando script en contenedor..."
docker exec viraclip-worker bash -c 'cat > /app/process.py << '"'"'PYEOF'"'"'
#!/usr/bin/env python3
import asyncio
import json
import sys
import uuid
from pathlib import Path

# Asegurar que estamos en el path correcto
sys.path.insert(0, "/app/src")

# Importar usando ruta absoluta para evitar imports relativos
from observability import configure_logging, set_trace_id
from workers.tasks import process_video_task
from redis.asyncio import Redis

async def main():
    task_id = str(uuid.uuid4())
    
    print("🎬 INICIANDO PROCESAMIENTO VIRACLIP")
    print("=" * 50)
    print(f"📹 Video: /app/uploads/video.mp4")
    print(f"🆔 Task ID: {task_id}")
    print("=" * 50)
    print()
    
    # Configurar Redis
    redis = Redis.from_url("redis://viraclip-redis:6379")
    ctx = {"redis": redis}
    
    # Ejecutar tarea
    result = await process_video_task(
        ctx=ctx,
        task_id=task_id,
        url="/app/uploads/video.mp4",
        source_type="upload",
        user_id="test_user",
        target_platform="tiktok",
        num_clips=3
    )
    
    print()
    print("=" * 50)
    print("✅ RESULTADO:")
    print("=" * 50)
    print(json.dumps(result, indent=2, default=str))
    
    # Guardar resultado
    with open("/app/result.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    
    print()
    print("💾 Resultado guardado en: /app/result.json")
    print("🏁 PROCESO COMPLETADO")

if __name__ == "__main__":
    asyncio.run(main())
PYEOF'
chmod +x /app/process.py'
echo "   ✅ Script creado"
echo ""

# 4. Ejecutar el script
echo "4️⃣  Ejecutando procesamiento..."
echo "   ⏳ Esto tomará varios minutos..."
echo "=========================================="
docker exec viraclip-worker bash -c '
source /app/.venv/bin/activate 2>/dev/null || true
cd /app/src
export PYTHONPATH=/app/src
export VIRA_UPLOADS=/app/uploads
export VIRA_OUTPUTS=/app/outputs
export REDIS_URL=redis://viraclip-redis:6379
python3 /app/process.py' 2>&1
echo "=========================================="
echo ""

# 5. Recuperar resultados
echo "5️⃣  Recuperando resultados..."
docker cp viraclip-worker:/app/result.json "$WORKDIR/result.json" 2>/dev/null || echo "   ⚠️  No se encontró result.json"
docker cp viraclip-worker:/app/outputs "$WORKDIR/outputs" 2>/dev/null || echo "   ⚠️  Revisa /app/outputs en contenedor"
echo ""

echo "🏁 PROCESO FINALIZADO"
echo "📁 Archivos en: $WORKDIR"
echo "🎞️  Clips generados:"
ls -la "$WORKDIR/outputs" 2>/dev/null || echo "   (verificar en contenedor)"
