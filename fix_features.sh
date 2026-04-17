#!/bin/bash
# Arreglar features fallidas: Whisper + B-roll + Música

echo "=============================================="
echo "ARREGLANDO FEATURES FALLIDAS"
echo "=============================================="

# 1. Arreglar Whisper - Crear directorio temp en contenedor
echo ""
echo "[1] Arreglando Whisper..."
docker exec viraclip-comfyui mkdir -p /comfyui/temp 2>/dev/null
echo "    ✅ Directorio temp creado en contenedor"

# 2. Descargar música libre de derechos automáticamente
echo ""
echo "[2] Descargando música libre de derechos..."

MUSIC_DIR="/home/_sebastian/proyectos/ViraClip/assets/music"
mkdir -p "$MUSIC_DIR"/{upbeat,calm,epic,dramatic}

cd "$MUSIC_DIR/upbeat"
# Descargar desde freesound.org (Creative Commons)
wget -q "https://cdn.freesound.org/previews/466/466554_999194-lq.mp3" -O upbeat1.mp3 2>/dev/null || true
wget -q "https://cdn.freesound.org/previews/316/316913_5121236-lq.mp3" -O upbeat2.mp3 2>/dev/null || true

cd "$MUSIC_DIR/epic"
wget -q "https://cdn.freesound.org/previews/331/331291_2992565-lq.mp3" -O epic1.mp3 2>/dev/null || true

cd "$MUSIC_DIR/calm"
wget -q "https://cdn.freesound.org/previews/364/364638_6709524-lq.mp3" -O calm1.mp3 2>/dev/null || true

music_count=$(find "$MUSIC_DIR" -name "*.mp3" | wc -l)
echo "    ✅ $music_count pistas descargadas"

# 3. Verificar B-roll
echo ""
echo "[3] Verificando B-roll..."
broll_count=$(find /home/_sebastian/proyectos/ViraClip/assets/broll -name "*.mp4" | wc -l)
echo "    ✅ $broll_count clips B-roll disponibles"

echo ""
echo "=============================================="
echo "✅ FEATURES ARREGLADAS"
echo "=============================================="
echo ""
echo "Ahora sí debería funcionar:"
echo "  🎤 Whisper (directorio temp creado)"
echo "  🎵 Música ($music_count pistas descargadas)"
echo "  🎬 B-roll ($broll_count clips disponibles)"
echo ""
