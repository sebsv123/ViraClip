#!/bin/bash
# ViraClip Simple - Ejecución directa como antes
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

# 2. Preparar JSON de tarea
echo "2️⃣  Preparando tarea..."
cat > "$WORKDIR/task.json" <<EOF
{
  "source_type": "upload",
  "video_path": "/app/uploads/video.mp4",
  "platform": "tiktok", 
  "options": {
    "max_clips": 3,
    "min_duration": 15,
    "max_duration": 60,
    "background_composite_enabled": true,
    "sam2_enabled": true,
    "generate_captions": true
  }
}
EOF
echo "   ✅ task.json"
echo ""

# 3. Copiar video al contenedor worker
echo "3️⃣  Copiando a worker..."
docker cp "$VIDEO" viraclip-worker:/app/uploads/video.mp4
docker cp "$WORKDIR/task.json" viraclip-worker:/app/task.json
echo "   ✅ Archivos en worker"
echo ""

# 4. Copiar script de ejecución
echo "4️⃣  Copiando script de ejecución..."
docker cp /home/_sebastian/CascadeProjects/ViraClip/run_worker.py viraclip-worker:/app/run_worker.py
echo "   ✅ Script en worker"
echo ""

# 5. Copiar wrapper al worker
echo "5️⃣  Copiando wrapper..."
docker cp /home/_sebastian/CascadeProjects/ViraClip/backend/src/workers/run_task.py viraclip-worker:/app/src/workers/run_task.py
echo "   ✅ Wrapper en worker"
echo ""

# 6. Ejecutar procesamiento con el entorno virtual del proyecto
echo "6️⃣  Ejecutando worker con entorno virtual..."
echo "   ⏳ Esto tomará varios minutos..."
echo "=========================================="
docker exec viraclip-worker bash -c '
source /app/.venv/bin/activate && \
export PYTHONPATH=/app/src && \
python3 -m workers.run_task /app/task.json' 2>&1
echo "=========================================="
echo "=========================================="
echo ""

# 6. Recuperar resultado
echo "6️⃣  Recuperando resultado..."
docker cp viraclip-worker:/app/result.json "$WORKDIR/result.json" 2>/dev/null || echo "   ⚠️  No se encontró result.json"
docker cp viraclip-worker:/app/outputs "$WORKDIR/outputs" 2>/dev/null || echo "   ⚠️  Revisa clips en el contenedor"
echo ""

echo "📁 Archivos en: $WORKDIR"
echo "🎞️  Clips generados:"
ls -la "$WORKDIR/outputs" 2>/dev/null || echo "   (ver /app/outputs en contenedor)"
