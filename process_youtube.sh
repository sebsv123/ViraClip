#!/bin/bash
# Script para procesar videos de YouTube con ViraClip
# Uso: ./process_youtube.sh <youtube_url>

set -e

YOUTUBE_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
VIDEO_ID=$(echo "$YOUTUBE_URL" | sed -n 's/.*youtu\.be\/\([^?]*\).*/\1/p; s/.*v=\([^&]*\).*/\1/p' | head -1)

if [ -z "$VIDEO_ID" ]; then
    echo "❌ No se pudo extraer ID del video de: $YOUTUBE_URL"
    exit 1
fi

echo "=========================================="
echo "🎬 ViraClip YouTube Processor"
echo "=========================================="
echo "📹 Video ID: $VIDEO_ID"
echo "🔗 URL: $YOUTUBE_URL"
echo ""

# Directorios
WORKDIR="/tmp/viraclip_youtube_${VIDEO_ID}"
mkdir -p "$WORKDIR/downloads" "$WORKDIR/outputs" "$WORKDIR/clips"

echo "📁 Directorio de trabajo: $WORKDIR"

# Verificar dependencias
echo ""
echo "🔍 Verificando dependencias..."

if ! command -v yt-dlp &> /dev/null; then
    echo "⚠️  yt-dlp no encontrado. Instalando..."
    pip3 install yt-dlp --break-system-packages 2>/dev/null || pip3 install yt-dlp --user 2>/dev/null || {
        echo "❌ No se pudo instalar yt-dlp"
        exit 1
    }
fi

# Verificar Docker
echo "🐳 Verificando Docker..."
if ! docker ps &>/dev/null; then
    echo "❌ Docker no está corriendo. Iniciando..."
    sudo systemctl start docker || {
        echo "❌ No se pudo iniciar Docker"
        exit 1
    }
fi

# Verificar ViraClip stack
echo "📦 Verificando ViraClip stack..."
cd /home/_sebastian/CascadeProjects/ViraClip

# Verificar si los servicios están corriendo
if ! docker-compose ps | grep -q "Up"; then
    echo "🚀 Iniciando ViraClip services..."
    docker-compose up -d --build 2>&1 | tail -20
    echo "⏳ Esperando 30s para que los servicios estén listos..."
    sleep 30
fi

echo ""
echo "⬇️  Descargando video de YouTube..."
cd "$WORKDIR/downloads"

yt-dlp \
    -f "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
    -o "%(id)s.%(ext)s" \
    --merge-output-format mp4 \
    --no-playlist \
    "$YOUTUBE_URL" 2>&1 | tail -20

VIDEO_FILE=$(ls -t *.mp4 2>/dev/null | head -1)

if [ -z "$VIDEO_FILE" ]; then
    echo "❌ No se pudo descargar el video"
    exit 1
fi

echo "✅ Video descargado: $VIDEO_FILE"
echo ""

# Verificar que el archivo no esté vacío
if [ ! -s "$VIDEO_FILE" ]; then
    echo "❌ El archivo descargado está vacío"
    exit 1
fi

VIDEO_SIZE=$(du -h "$VIDEO_FILE" | cut -f1)
echo "📊 Tamaño del video: $VIDEO_SIZE"
echo ""

# Crear tarea en ViraClip
echo "🎯 Creando tarea de procesamiento..."

# Usar la API de ViraClip para crear una tarea
TASK_PAYLOAD=$(cat <<EOF
{
    "source_url": "$YOUTUBE_URL",
    "video_path": "/app/uploads/$VIDEO_FILE",
    "platform": "tiktok",
    "options": {
        "max_clips": 5,
        "min_duration": 15,
        "max_duration": 60,
        "background_composite_enabled": true,
        "sam2_enabled": true
    }
}
EOF
)

echo "📤 Payload: $TASK_PAYLOAD"
echo ""

# Verificar salud del backend
echo "🏥 Verificando backend health..."
HEALTH_STATUS=$(curl -s http://localhost:8000/health 2>/dev/null || echo "unhealthy")
echo "   Status: $HEALTH_STATUS"

if [ "$HEALTH_STATUS" = "unhealthy" ]; then
    echo "⚠️  Backend no responde. Verificando logs..."
    docker-compose logs backend 2>&1 | tail -30
fi

echo ""
echo "=========================================="
echo "✅ Configuración completa"
echo "=========================================="
echo ""
echo "📋 Resumen:"
echo "   • Video descargado: $WORKDIR/downloads/$VIDEO_FILE"
echo "   • Tamaño: $VIDEO_SIZE"
echo "   • Directorio: $WORKDIR"
echo ""
echo "🚀 Para procesar el video manualmente:"
echo "   1. Copia el video al contenedor:"
echo "      docker cp \"$WORKDIR/downloads/$VIDEO_FILE\" viraclip-backend-1:/app/uploads/"
echo ""
echo "   2. Usa la API para crear tarea:"
echo "      curl -X POST http://localhost:8000/api/tasks \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"source_url\":\"$YOUTUBE_URL\",\"platform\":\"tiktok\"}'"
echo ""
echo "   3. O usa el script de prueba:"
echo "      cd /home/_sebastian/CascadeProjects/ViraClip/backend"
echo "      python3 test_e2e.py --video \"$WORKDIR/downloads/$VIDEO_FILE\""
echo ""
echo "📁 Archivos temporales en: $WORKDIR"
echo "🗑️  Para limpiar: rm -rf $WORKDIR"
echo ""

# Guardar info para uso posterior
cat > "$WORKDIR/process_info.txt" <<EOF
VIDEO_ID=$VIDEO_ID
YOUTUBE_URL=$YOUTUBE_URL
VIDEO_FILE=$VIDEO_FILE
WORKDIR=$WORKDIR
DATE=$(date -Iseconds)
EOF

echo "✨ Listo!"
