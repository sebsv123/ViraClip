#!/bin/bash
# ViraClip via API - El método que funciona
set -e

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip via API"
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

echo "   Respuesta: $RESPONSE"

# Extraer task_id
TASK_ID=$(echo "$RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$TASK_ID" ]; then
    echo "   ❌ No se pudo obtener task_id"
    echo "   Respuesta completa: $RESPONSE"
    exit 1
fi

echo "   ✅ Task creado: $TASK_ID"
echo ""

# 3. Esperar resultado
echo "3️⃣  Esperando procesamiento..."
echo "   ⏳ Puedes ver logs en: docker-compose logs -f worker"
echo ""

for i in {1..60}; do
    sleep 10
    STATUS=$(curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/status 2>/dev/null || echo '{}')
    STATE=$(echo "$STATUS" | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
    
    echo "   [$i] Estado: ${STATE:-desconocido}"
    
    if [ "$STATE" = "completed" ]; then
        echo ""
        echo "   ✅ COMPLETADO!"
        break
    elif [ "$STATE" = "failed" ]; then
        echo ""
        echo "   ❌ FALLIDO"
        break
    fi
done

# 4. Descargar resultado
echo ""
echo "4️⃣  Descargando resultado..."
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/result -o "$WORKDIR/result.json"
echo "   ✅ Resultado en: $WORKDIR/result.json"
echo ""

echo "🏁 PROCESO FINALIZADO"
echo "📁 Archivos en: $WORKDIR"
cat "$WORKDIR/result.json" 2>/dev/null | jq . 2>/dev/null || cat "$WORKDIR/result.json"
