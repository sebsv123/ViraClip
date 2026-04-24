#!/bin/bash
# Script completo para ejecutar pruebas ViraClip + ComfyUI
# Uso: ./run_tests.sh

set -e

echo "=========================================="
echo "  ViraClip + ComfyUI - Suite de Pruebas"
echo "=========================================="
echo ""

export VIRA_ROOT=/home/_sebastian/proyectos/ViraClip

# 1. Verificar/Instalar dependencias
echo "🔧 1. Verificando dependencias..."

if ! command -v yt-dlp &> /dev/null; then
    echo "   ⬇️ Instalando yt-dlp..."
    pip3 install --user yt-dlp
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "   ⚠️ ffmpeg no encontrado. Intentando instalar..."
    sudo pacman -S ffmpeg --noconfirm 2>/dev/null || echo "   Instalar manualmente: sudo pacman -S ffmpeg"
fi

echo "   ✅ Dependencias listas"

# 2. Crear estructura de directorios
echo ""
echo "📁 2. Creando estructura de directorios..."
mkdir -p $VIRA_ROOT/inputs/test_videos
mkdir -p $VIRA_ROOT/outputs/test_channel
mkdir -p $VIRA_ROOT/outputs/test_thumbnails
mkdir -p $VIRA_ROOT/outputs/test_subtitles
mkdir -p $VIRA_ROOT/outputs/test_comfy
echo "   ✅ Directorios creados"

# 3. Descargar video de prueba
echo ""
echo "⬇️ 3. Descargando video de prueba..."
VIDEO_URL="https://youtu.be/3wgwaxIfUJQ"
VIDEO_PATH="$VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"

if [ -f "$VIDEO_PATH" ]; then
    echo "   ✅ Video ya existe: $VIDEO_PATH"
else
    echo "   📥 Descargando desde YouTube..."
    if ~/.local/bin/yt-dlp -f "best[height<=720]" -o "$VIDEO_PATH" "$VIDEO_URL" 2>&1 | tail -5; then
        echo "   ✅ Descarga completada"
    else
        echo "   ⚠️ Falló la descarga de YouTube"
        echo "   🎬 Creando video de prueba local..."
        
        if command -v ffmpeg &> /dev/null; then
            ffmpeg -f lavfi -i testsrc=duration=300:size=1280x720:rate=30 \
                -f lavfi -i sine=frequency=1000:duration=300 \
                -pix_fmt yuv420p "$VIDEO_PATH" -y 2>&1 | tail -5
            echo "   ✅ Video de prueba creado (5 min, 720p)"
        else
            echo "   ❌ Error: ni yt-dlp ni ffmpeg funcionaron"
            echo "   💡 Instala ffmpeg: sudo pacman -S ffmpeg"
            exit 1
        fi
    fi
fi

# 4. Verificar ComfyUI
echo ""
echo "🔍 4. Verificando ComfyUI..."
if curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
    echo "   ✅ ComfyUI responde en localhost:8188"
else
    echo "   ⚠️ ComfyUI no responde. Intentando iniciar..."
    cd /home/_sebastian/CascadeProjects/ViraClip && docker compose up -d comfyui
    sleep 10
    
    if curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
        echo "   ✅ ComfyUI iniciado correctamente"
    else
        echo "   ❌ No se pudo iniciar ComfyUI"
        echo "   💡 Verificar: docker ps | grep comfyui"
        exit 1
    fi
fi

# 5. Ejecutar pruebas Python
echo ""
echo "🧪 5. Ejecutando pruebas del pipeline..."
cd /home/_sebastian/CascadeProjects/ViraClip
python3 test_pipeline_real.py 2>&1 | tee /home/_sebastian/proyectos/ViraClip/outputs/test_pipeline_log.txt

# 6. Resumen final
echo ""
echo "=========================================="
echo "  PRUEBAS COMPLETADAS"
echo "=========================================="
echo ""
echo "📁 Resultados guardados en:"
echo "   - outputs/test_channel/"
echo "   - outputs/test_thumbnails/"
echo "   - outputs/test_subtitles/"
echo "   - outputs/test_comfy/"
echo ""
echo "📄 Logs:"
echo "   - outputs/test_pipeline_log.txt"
echo "   - outputs/test_report_final.json"
echo ""
echo "🎉 Revisa los resultados!"
echo ""
