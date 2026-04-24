#!/bin/bash
# Verificar qué features REALES de ViraClip están disponibles

echo "=============================================="
echo "VERIFICACIÓN DE FEATURES REALES DE VIRACLIP"
echo "=============================================="

# 1. Verificar Whisper en ComfyUI
echo ""
echo "[1] Whisper (subtítulos reales con transcripción)"
docker exec viraclip-comfyui find /comfyui/custom_nodes -name "*whisper*" -type d 2>/dev/null | head -3
if docker exec viraclip-comfyui python3 -c "import whisper" 2>/dev/null; then
    echo "   ✅ Whisper Python disponible"
else
    echo "   ❌ Whisper no instalado"
fi

# Verificar nodo WhisperTranscribe
whisper_node=$(curl -s http://localhost:8188/object_info 2>/dev/null | grep -i "whisper" | head -3)
if [ -n "$whisper_node" ]; then
    echo "   ✅ Nodo WhisperTranscribe disponible"
    echo "   $whisper_node"
else
    echo "   ❌ Nodo WhisperTranscribe NO disponible"
fi

# 2. Verificar B-roll assets locales
echo ""
echo "[2] B-roll Assets Locales"
if [ -d "/home/_sebastian/proyectos/ViraClip/assets/broll" ]; then
    count=$(find /home/_sebastian/proyectos/ViraClip/assets/broll -type f | wc -l)
    echo "   ✅ Asset bank: $count archivos"
else
    echo "   ❌ No hay asset bank local"
fi

# 3. Verificar API Keys para B-roll externo
echo ""
echo "[3] API Keys para B-roll (Pexels/Pixabay/Coverr)"
if [ -n "$PEXELS_API_KEY" ]; then
    echo "   ✅ Pexels API Key"
else
    echo "   ❌ Pexels API Key no configurada"
fi

if [ -n "$PIXABAY_API_KEY" ]; then
    echo "   ✅ Pixabay API Key"
else
    echo "   ❌ Pixabay API Key no configurada"
fi

if [ -n "$COVERR_API_KEY" ]; then
    echo "   ✅ Coverr API Key"
else
    echo "   ❌ Coverr API Key no configurada"
fi

# 4. Verificar modelos de face detection
echo ""
echo "[4] Smart Face Reframe (face detection)"
docker exec viraclip-comfyui find /comfyui -name "*face*" -o -name "*yolo*" 2>/dev/null | head -3
if docker exec viraclip-comfyui python3 -c "import cv2; print('OpenCV:', cv2.__version__)" 2>/dev/null; then
    echo "   ✅ OpenCV disponible"
else
    echo "   ❌ OpenCV no verificable"
fi

# 5. Verificar integración backend
echo ""
echo "[5] Backend ViraClip"
if [ -f "/home/_sebastian/CascadeProjects/ViraClip/backend/src/services/comfyui_integration.py" ]; then
    echo "   ✅ comfyui_integration.py existe"
fi

if [ -f "/home/_sebastian/CascadeProjects/ViraClip/backend/src/services/contextual_broll.py" ]; then
    echo "   ✅ contextual_broll.py existe"
fi

echo ""
echo "=============================================="
echo "RESUMEN"
echo "=============================================="
echo ""
echo "Para shorts virales COMPLETOS necesitas:"
echo ""
echo "OPCIÓN A - Mínimo viable (ahora):"
echo "  • FFmpeg: recortes + subtítulos placeholder + zoom"
echo "  • ComfyUI VHS: reframe 9:16 básico"
echo "  • Tiempo: Funciona ahora"
echo ""
echo "OPCIÓN B - Completo (requiere setup):"
echo "  • Instalar Whisper en ComfyUI"
echo "  • Configurar API keys (Pexels/Pixabay)"
echo "  • Descargar assets B-roll"
echo "  • Tiempo: 30-60 min de setup"
echo ""
