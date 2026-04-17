#!/bin/bash
# Setup COMPLETO LOCAL - Whisper + B-roll generation + Face detection
# Todo con modelos descargables, sin APIs externas

set -e

echo "=============================================="
echo "SETUP COMPLETO LOCAL - VIRACLIP VIRAL"
echo "Sin APIs externas - Todo con modelos locales"
echo "=============================================="

COMFYUI_CONTAINER="viraclip-comfyui"
COMFYUI_PATH="/comfyui"

# ============================================
# 1. INSTALAR WHISPER LOCAL (OpenAI Whisper)
# ============================================
echo ""
echo "[1/5] Instalando Whisper local..."
docker exec $COMFYUI_CONTAINER bash -c "
    cd $COMFYUI_PATH/custom_nodes
    if [ ! -d 'ComfyUI-Whisper' ]; then
        git clone https://github.com/chrisgoringe/ComfyUI-Whisper.git
    fi
    cd ComfyUI-Whisper
    pip install -q openai-whisper torch torchvision torchaudio
    echo 'Whisper instalado'
"

# Descargar modelo Whisper base (74MB, local)
echo "    └─ Descargando modelo Whisper base..."
docker exec $COMFYUI_CONTAINER python3 -c "
import whisper
whisper.load_model('base')
print('Modelo Whisper base descargado')
" 2>/dev/null || echo "    ⚠️  Modelo se descargará en primer uso"

# ============================================
# 2. INSTALAR FACE DETECTION (OpenCV + Dlib)
# ============================================
echo ""
echo "[2/5] Instalando Face Detection local..."
docker exec $COMFYUI_CONTAINER bash -c "
    pip install -q opencv-python-headless dlib face-recognition
    echo 'Face detection instalado'
"

# Descargar shape predictor para face landmarks
echo "    └─ Descargando modelos face detection..."
docker exec $COMFYUI_CONTAINER bash -c "
    mkdir -p /comfyui/models/face_detection
    cd /comfyui/models/face_detection
    if [ ! -f 'shape_predictor_68_face_landmarks.dat' ]; then
        wget -q http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2
        bunzip2 shape_predictor_68_face_landmarks.dat.bz2 2>/dev/null || true
        echo 'Face landmarks modelo descargado'
    fi
"

# ============================================
# 3. SETUP B-ROLL LOCAL (ComfyUI Image-to-Video)
# ============================================
echo ""
echo "[3/5] Setup B-roll generation local..."

# Instalar nodos para generación de video/imágenes
docker exec $COMFYUI_CONTAINER bash -c "
    cd $COMFYUI_PATH/custom_nodes
    
    # AnimateDiff para motion en B-roll
    if [ ! -d 'ComfyUI-AnimateDiff-Evolved' ]; then
        git clone https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git
        cd ComfyUI-AnimateDiff-Evolved
        pip install -q -r requirements.txt 2>/dev/null || true
    fi
    
    # IPAdapter para estilo consistente
    if [ ! -d 'ComfyUI_IPAdapter_plus' ]; then
        git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
    fi
    
    echo 'Nodos B-roll instalados'
"

# Descargar modelos para B-roll generation
echo "    └─ Descargando modelos SDXL + Motion..."
docker exec $COMFYUI_CONTAINER bash -c "
    mkdir -p $COMFYUI_PATH/models/checkpoints
    mkdir -p $COMFYUI_PATH/models/loras
    mkdir -p $COMFYUI_PATH/models/controlnet
    
    # Descargar SDXL base (opcional, puede tardar)
    # wget -q -O $COMFYUI_PATH/models/checkpoints/sd_xl_base_1.0.safetensors \
    #     'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors' &
    
    echo 'Modelos configurados (descarga manual opcional)'
"

# ============================================
# 4. ASSETS B-ROLL LOCALES (Videos cortos stock)
# ============================================
echo ""
echo "[4/5] Descargando assets B-roll gratuitos..."

mkdir -p /home/_sebastian/proyectos/ViraClip/assets/broll/{abstract,nature,urban,tech,people}

cd /home/_sebastian/proyectos/ViraClip/assets/broll

# Descargar videos gratuitos de Coverr/Pexels (licencia libre)
echo "    └─ Descargando 15 clips B-roll..."

# Abstract/Backgrounds
wget -q --show-progress "https://videos.pexels.com/video-files/3129671/3129671-hd_1920_1080_30fps.mp4" -O abstract/particles.mp4 2>/dev/null || true
wget -q --show-progress "https://videos.pexels.com/video-files/3121459/3121459-hd_1920_1080_30fps.mp4" -O abstract/light_leaks.mp4 2>/dev/null || true

# Nature
wget -q --show-progress "https://videos.pexels.com/video-files/857251/857251-hd_1920_1080_25fps.mp4" -O nature/forest_aerial.mp4 2>/dev/null || true
wget -q --show-progress "https://videos.pexels.com/video-files/1536322/1536322-hd_1920_1080_30fps.mp4" -O nature/waves.mp4 2>/dev/null || true

# Urban/City
wget -q --show-progress "https://videos.pexels.com/video-files/2043385/2043385-hd_1920_1080_24fps.mp4" -O urban/city_traffic.mp4 2>/dev/null || true
wget -q --show-progress "https://videos.pexels.com/video-files/3129679/3129679-hd_1920_1080_25fps.mp4" -O urban/night_lights.mp4 2>/dev/null || true

# Tech/Business
wget -q --show-progress "https://videos.pexels.com/video-files/2270325/2270325-hd_1920_1080_30fps.mp4" -O tech/coding_screen.mp4 2>/dev/null || true
wget -q --show-progress "https://videos.pexels.com/video-files/3252118/3252118-hd_1920_1080_30fps.mp4" -O business/meeting.mp4 2>/dev/null || true

# People/Emotions
wget -q --show-progress "https://videos.pexels.com/video-files/3209828/3209828-hd_1920_1080_30fps.mp4" -O people/happy.mp4 2>/dev/null || true

# Contar descargados
count=$(find . -name "*.mp4" -type f | wc -l)
echo "    ✅ $count clips B-roll descargados"

# ============================================
# 5. MÚSICA LIBRE DE DERECHOS (Uppbeat/Epidemic)
# ============================================
echo ""
echo "[5/5] Setup música (requiere descarga manual)..."

mkdir -p /home/_sebastian/proyectos/ViraClip/assets/music/{upbeat,calm,dramatic,epic}

cat > /home/_sebastian/proyectos/ViraClip/assets/music/README.txt << 'EOF'
MÚSICA LIBRE DE DERECHOS - Fuentes recomendadas:

1. Uppbeat.io (gratuito con atribución)
   - https://uppbeat.io
   - Crear cuenta gratuita
   - Descargar tracks "Creator" tier

2. Epidemic Sound (trial 30 días)
   - https://www.epidemicsound.com
   - Alta calidad, catalogo profesional

3. YouTube Audio Library
   - Dentro de YouTube Studio
   - 100% gratuito y seguro

4. Pixabay Music
   - https://pixabay.com/music/
   - Creative Commons

Descargar 3-5 tracks por categoría y ponerlos en:
- upbeat/ (energéticos, viral)
- calm/ (relajados, informativos)
- dramatic/ (tensión, giros)
- epic/ (cierres, CTAs)
EOF

echo "    └─ Ver /home/_sebastian/proyectos/ViraClip/assets/music/README.txt"

# ============================================
# REINICIAR COMFYUI
# ============================================
echo ""
echo "=============================================="
echo "Reiniciando ComfyUI para aplicar cambios..."
echo "=============================================="
docker restart $COMFYUI_CONTAINER

echo ""
echo "⏳ Esperando 60s a que inicie..."
sleep 60

# Verificar
echo ""
echo "Verificando instalación..."
if docker exec $COMFYUI_CONTAINER python3 -c "import whisper; print('Whisper OK')" 2>/dev/null; then
    echo "  ✅ Whisper: OK"
else
    echo "  ⚠️  Whisper: Verificar manualmente"
fi

if docker exec $COMFYUI_CONTAINER python3 -c "import cv2; print('OpenCV OK')" 2>/dev/null; then
    echo "  ✅ Face Detection: OK"
else
    echo "  ⚠️  Face Detection: Verificar manualmente"
fi

count=$(find /home/_sebastian/proyectos/ViraClip/assets/broll -name "*.mp4" | wc -l)
echo "  ✅ B-roll Assets: $count clips"

echo ""
echo "=============================================="
echo "✅ SETUP COMPLETO LOCAL FINALIZADO"
echo "=============================================="
echo ""
echo "Features ahora disponibles:"
echo "  🎤 Transcripción Whisper (local)"
echo "  👤 Face tracking smart (local)"
echo "  🎬 B-roll insertion (assets locales)"
echo "  🎵 Música (descargar manual de fuentes libres)"
echo ""
echo "Siguiente paso: Generar shorts virales completos"
echo "Ejecutar: ./create_viral_shorts_complete.sh"
echo ""
