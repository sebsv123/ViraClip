#!/bin/bash
# ViraClip Simple - Usando ARQ directamente
set -e

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip Simple Runner"
echo "=========================================="
echo "📹 URL: $VIDEO_URL"
echo ""

# 1. Descargar
echo "1️⃣  Descargando..."
yt-dlp -f 'best[height<=1080][ext=mp4]/best' -o "$WORKDIR/video.%(ext)s" "$VIDEO_URL" 2>&1 | tail -3
VIDEO=$(ls "$WORKDIR"/*.* | head -1)
echo "   ✅ $(basename $VIDEO)"
echo ""

# 2. Copiar al contenedor y ejecutar procesamiento inline
echo "2️⃣  Procesando en contenedor..."
docker cp "$VIDEO" viraclip-worker:/app/uploads/video.mp4

# Ejecutar script inline con todas las dependencias ya configuradas
docker exec viraclip-worker bash -c '
# Usar el entorno virtual del proyecto
source /app/.venv/bin/activate 2>/dev/null || true

# Configurar environment
export PYTHONPATH=/app/src
export VIRA_UPLOADS=/app/uploads
export VIRA_OUTPUTS=/app/outputs
export REDIS_URL=${REDIS_URL:-redis://viraclip-redis:6379}

# Ejecutar tarea directamente
cd /app
python3 << "PYTHON_EOF"
import asyncio
import json
import sys
sys.path.insert(0, "/app/src")

async def process():
    try:
        # Importar dentro del async para manejar mejor errores
        from src.workers.tasks import process_video_task
        
        import uuid
        from redis.asyncio import Redis
        
        task_id = str(uuid.uuid4())
        url = "/app/uploads/video.mp4"
        source_type = "upload"
        user_id = "test_user"
        
        print("🎬 INICIANDO PROCESAMIENTO")
        print("📹 Video:", url)
        print("🆔 Task ID:", task_id)
        
        # Crear contexto con redis
        redis = Redis.from_url("redis://viraclip-redis:6379")
        ctx = {"redis": redis}
        
        result = await process_video_task(
            ctx=ctx,
            task_id=task_id,
            url=url,
            source_type=source_type,
            user_id=user_id,
            target_platform="tiktok",
            num_clips=3
        )
        
        print("\n✅ COMPLETADO")
        print(json.dumps(result, indent=2, default=str))
        
        with open("/app/result.json", "w") as f:
            json.dump(result, f, default=str)
            
    except Exception as e:
        print("\n❌ ERROR:", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)

asyncio.run(process())
PYTHON_EOF
' 2>&1 | tee "$WORKDIR/output.log"

echo ""
echo "=========================================="
echo "🏁 Proceso finalizado"
echo "=========================================="
echo "📁 Archivos en: $WORKDIR"
echo "🎞️  Ver clips en: docker exec viraclip-worker ls -la /app/outputs/"
