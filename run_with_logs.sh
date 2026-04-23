#!/bin/bash
# ViraClip via API con logs en tiempo real
set -e

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip Processing con Logs"
echo "=========================================="
echo "📹 URL: $VIDEO_URL"
echo ""

# 1. Descargar
echo "1️⃣  Descargando..."
yt-dlp -f 'best[height<=1080][ext=mp4]/best' -o "$WORKDIR/video.%(ext)s" "$VIDEO_URL" 2>&1 | tail -3
VIDEO=$(ls "$WORKDIR"/*.* | head -1)
echo "   ✅ $(basename $VIDEO)"
echo ""

# 2. Subir a ViraClip
echo "2️⃣  Subiendo a ViraClip API..."
RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/tasks \
  -F "file=@$VIDEO" \
  -F "platform=tiktok" \
  -F "max_clips=3" 2>&1)

TASK_ID=$(echo "$RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$TASK_ID" ]; then
    echo "   ❌ Error: $RESPONSE"
    exit 1
fi

echo "   ✅ Task ID: $TASK_ID"
echo ""

# 3. Monitorear con logs en tiempo real
echo "3️⃣  Monitoreando (logs en tiempo real)..."
echo "   ⏳ Presiona Ctrl+C para detener monitoreo"
echo "=========================================="

# En segundo plano: mostrar logs del worker
docker-compose logs -f worker &
LOGS_PID=$!

# En primer plano: esperar completado
for i in {1..120}; do
    sleep 5
    STATUS=$(curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/status 2>/dev/null || echo '{}')
    STATE=$(echo "$STATUS" | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
    
    if [ "$STATE" = "completed" ]; then
        echo ""
        echo "✅ COMPLETADO!"
        break
    elif [ "$STATE" = "failed" ]; then
        echo ""
        echo "❌ FALLIDO"
        break
    fi
done

# Detener logs
kill $LOGS_PID 2>/dev/null || true

echo "=========================================="
echo ""

# 4. Mostrar resultado
echo "4️⃣  Resultado:"
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/result | jq . 2>/dev/null || \
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/result
echo ""

# 5. Descargar clips
echo "5️⃣  Descargando clips..."
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/download -o "$WORKDIR/clips.zip" 2>/dev/null || \
echo "   ℹ️  Descarga disponible en: http://localhost:8000/api/v1/tasks/$TASK_ID/download"

echo ""
echo "🏁 PROCESO FINALIZADO"
echo "📁 Archivos en: $WORKDIR"
