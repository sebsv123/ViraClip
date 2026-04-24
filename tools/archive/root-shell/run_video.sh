#!/bin/bash
# ViraClip Video Processing - Simple y transparente
set -e

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip Video Processing"
echo "=========================================="
echo "📹 URL: $VIDEO_URL"
echo ""

# 1. Descargar
echo "1️⃣  Descargando..."
yt-dlp -f 'best[height<=1080][ext=mp4]/best' -o "$WORKDIR/video.%(ext)s" "$VIDEO_URL" 2>&1 | tail -3
VIDEO=$(ls "$WORKDIR"/*.* | head -1)
echo "   ✅ $(basename $VIDEO)"
echo ""

# 2. Copiar a contenedor
echo "2️⃣  Copiando a contenedor..."
docker cp "$VIDEO" viraclip-worker:/app/uploads/video.mp4
echo "   ✅ Video en worker"
echo ""

# 3. Ejecutar procesamiento
echo "3️⃣  Ejecutando ViraClip..."
echo "   ⏳ Esto tomará varios minutos..."
echo "=========================================="

docker exec viraclip-worker bash -c '
source /app/.venv/bin/activate 2>/dev/null || true
export PYTHONPATH=/app/src
export VIRA_UPLOADS=/app/uploads
export VIRA_OUTPUTS=/app/outputs
export REDIS_URL=redis://viraclip-redis:6379

cd /app

python3 -c "
import asyncio
import json
import sys
import uuid
from redis.asyncio import Redis

sys.path.insert(0, \"/app/src\")

from workers.tasks import process_video_task

async def main():
    task_id = str(uuid.uuid4())
    print(\"🎬 INICIANDO PROCESAMIENTO\")
    print(f\"📹 Video: /app/uploads/video.mp4\")
    print(f\"🆔 Task ID: {task_id}\")
    print()
    
    redis = Redis.from_url(\"redis://viraclip-redis:6379\")
    ctx = {\"redis\": redis}
    
    result = await process_video_task(
        ctx=ctx,
        task_id=task_id,
        url=\"/app/uploads/video.mp4\",
        source_type=\"upload\",
        user_id=\"test_user\",
        target_platform=\"tiktok\",
        num_clips=3
    )
    
    print()
    print(\"✅ COMPLETADO\")
    print(json.dumps(result, indent=2, default=str))
    
    with open(\"/app/result.json\", \"w\") as f:
        json.dump(result, f, default=str)

asyncio.run(main())
" 2>&1
'

echo "=========================================="
echo "🏁 Proceso finalizado"
echo "📁 Archivos en: $WORKDIR"
echo "🎞️  Ver resultados: docker exec viraclip-worker ls -la /app/outputs/"
