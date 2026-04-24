#!/bin/bash
set -e

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip Processing"
echo "=========================================="
echo "📹 URL: $VIDEO_URL"
echo ""

# 1. Descargar
echo "1️⃣  Descargando..."
yt-dlp -f 'best[height<=1080][ext=mp4]/best' -o "$WORKDIR/video.%(ext)s" "$VIDEO_URL" 2>&1 | tail -3
VIDEO=$(ls "$WORKDIR"/*.* | head -1)
echo "   ✅ $(basename $VIDEO)"
echo ""

# 2. Copiar video
echo "2️⃣  Copiando video..."
docker cp "$VIDEO" viraclip-worker:/app/uploads/video.mp4
echo "   ✅ Video en contenedor"
echo ""

# 3. Copiar script Python a src para poder ejecutar como modulo
echo "3️⃣  Copiando script..."
docker cp /home/_sebastian/CascadeProjects/ViraClip/process.py viraclip-worker:/app/src/run_process.py
echo "   ✅ Script en /app/src/"
echo ""

# 4. Ejecutar como modulo desde /app/src
echo "4️⃣  Ejecutando ViraClip..."
echo "   ⏳ Esto tomará varios minutos..."
echo "=========================================="
docker exec viraclip-worker bash -c "source /app/.venv/bin/activate && cd /app && PYTHONPATH=/app/src python3 -m src.run_process" 2>&1
echo "=========================================="
echo ""

# 5. Recuperar resultados
echo "5️⃣  Recuperando resultados..."
docker cp viraclip-worker:/app/result.json "$WORKDIR/" 2>/dev/null || true
docker cp viraclip-worker:/app/outputs "$WORKDIR/" 2>/dev/null || true
echo "📁 Archivos en: $WORKDIR"
echo "🎞️  Clips:"
ls -la "$WORKDIR/outputs" 2>/dev/null || echo "   (verificar /app/outputs en contenedor)"
echo ""
echo "🏁 PROCESO FINALIZADO"
