#!/bin/bash
# Verificación exhaustiva de la integración ViraClip + ComfyUI

echo "=============================================="
echo "VERIFICACIÓN DE INTEGRACIÓN"
echo "=============================================="

# 1. Verificar FFmpeg
echo ""
echo "[1] Verificando FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    ffmpeg -version 2>&1 | head -1
    echo "✅ FFmpeg OK"
else
    echo "❌ FFmpeg NO ENCONTRADO"
    exit 1
fi

# 2. Verificar FFprobe
echo ""
echo "[2] Verificando FFprobe..."
if command -v ffprobe &> /dev/null; then
    echo "✅ FFprobe OK"
else
    echo "❌ FFprobe NO ENCONTRADO"
    exit 1
fi

# 3. Verificar ComfyUI
echo ""
echo "[3] Verificando ComfyUI..."
COMFYUI_URL="http://localhost:8188"
response=$(curl -s "$COMFYUI_URL/system_stats" 2>&1)
if [ $? -eq 0 ] && [ -n "$response" ]; then
    gpu=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('devices',[{}])[0].get('name','Unknown'))" 2>/dev/null)
    echo "✅ ComfyUI OK - GPU: $gpu"
else
    echo "❌ ComfyUI NO RESPONDE"
    echo "Reiniciando ComfyUI..."
    cd /home/_sebastian/CascadeProjects/ViraClip
    docker-compose up -d comfyui
    sleep 45
    
    # Verificar nuevamente
    response=$(curl -s "$COMFYUI_URL/system_stats" 2>&1)
    if [ $? -eq 0 ]; then
        echo "✅ ComfyUI reiniciado OK"
    else
        echo "❌ No se pudo reiniciar ComfyUI"
        exit 1
    fi
fi

# 4. Verificar nodos VHS
echo ""
echo "[4] Verificando nodos VideoHelperSuite..."
nodes=$(curl -s "$COMFYUI_URL/object_info" 2>&1 | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    vhs = [k for k in d.keys() if 'VHS' in k]
    print(f'Nodos VHS encontrados: {len(vhs)}')
    for n in vhs[:5]:
        print(f'  - {n}')
except Exception as e:
    print(f'Error: {e}')
" 2>/dev/null)
echo "$nodes"

if echo "$nodes" | grep -q "VHS_LoadVideo" && echo "$nodes" | grep -q "VHS_VideoCombine"; then
    echo "✅ Nodos VHS requeridos OK"
else
    echo "❌ Faltan nodos VHS esenciales"
    exit 1
fi

# 5. Verificar video de entrada
echo ""
echo "[5] Verificando video de entrada..."
VIDEO="/home/_sebastian/proyectos/ViraClip/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"
if [ -f "$VIDEO" ]; then
    duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VIDEO" 2>/dev/null | cut -d. -f1)
    size=$(du -h "$VIDEO" | cut -f1)
    echo "✅ Video OK - Duración: ${duration}s, Tamaño: $size"
else
    echo "❌ Video NO ENCONTRADO: $VIDEO"
    exit 1
fi

# 6. Verificar directorio de salida
echo ""
echo "[6] Verificando directorio de salida..."
OUTPUT="/home/_sebastian/proyectos/ViraClip/outputs/instagram_ready"
mkdir -p "$OUTPUT"
if [ -d "$OUTPUT" ] && [ -w "$OUTPUT" ]; then
    echo "✅ Directorio OK: $OUTPUT"
else
    echo "❌ No se puede escribir en: $OUTPUT"
    exit 1
fi

# 7. Verificar Docker
echo ""
echo "[7] Verificando Docker..."
if docker ps &>/dev/null; then
    echo "✅ Docker OK"
else
    echo "❌ Docker no está corriendo"
    exit 1
fi

# 8. Verificar contenedor ComfyUI
echo ""
echo "[8] Verificando contenedor viraclip-comfyui..."
if docker ps | grep -q "viraclip-comfyui"; then
    echo "✅ Contenedor ComfyUI corriendo"
else
    echo "❌ Contenedor no está corriendo"
    exit 1
fi

# 9. Test de workflow mínimo
echo ""
echo "[9] Test de workflow mínimo en ComfyUI..."
test_workflow='{"prompt":{"1":{"inputs":{"video":"seguro_3wgwaxIfUJQ.mp4","force_rate":30,"frame_load_cap":10,"force_size":"Custom","custom_width":1080,"custom_height":1920,"skip_first_frames":0,"select_every_nth":1},"class_type":"VHS_LoadVideo"},"2":{"inputs":{"frame_rate":30,"loop_count":0,"filename_prefix":"test_verify","format":"video/h264-mp4","pix_fmt":"yuv420p","crf":23,"pingpong":false,"save_output":true,"save_image":true,"images":["1",0]},"class_type":"VHS_VideoCombine"}}}'

response=$(curl -s -X POST "$COMFYUI_URL/prompt" -H "Content-Type: application/json" -d "$test_workflow" 2>&1)
prompt_id=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('prompt_id',''))" 2>/dev/null)

if [ -n "$prompt_id" ]; then
    echo "✅ Workflow enviado OK - Prompt ID: ${prompt_id:0:20}..."
    # Cancelar el test
    curl -s -X POST "$COMFYUI_URL/queue" -H "Content-Type: application/json" -d '{"clear": true}' > /dev/null 2>&1
else
    echo "❌ No se pudo enviar workflow de prueba"
    echo "Respuesta: $response"
    exit 1
fi

# 10. Verificar ffmpeg filters disponibles
echo ""
echo "[10] Verificando filtros FFmpeg requeridos..."
required_filters=("drawtext" "zoompan" "silencedetect" "atempo")
missing=()

for filter in "${required_filters[@]}"; do
    if ! ffmpeg -filters 2>&1 | grep -q "$filter"; then
        missing+=("$filter")
    fi
done

if [ ${#missing[@]} -eq 0 ]; then
    echo "✅ Todos los filtros requeridos disponibles:"
    echo "   - drawtext (subtítulos)"
    echo "   - zoompan (zoom viral)"
    echo "   - silencedetect (jump cuts)"
    echo "   - atempo (velocidad audio)"
else
    echo "❌ Filtros faltantes: ${missing[*]}"
    exit 1
fi

echo ""
echo "=============================================="
echo "✅ VERIFICACIÓN COMPLETADA - TODO INTEGRADO"
echo "=============================================="
echo ""
echo "Efectos de edición que se aplicarán:"
echo "  🎵 Audio: Preservado del original"
echo "  📐 Reframe 9:16: ComfyUI VHS_LoadVideo + resize"
echo "  📝 Subtítulos: FFmpeg drawtext (burn-in)"
echo "  ✂️  Jump cuts: FFmpeg silencedetect + atempo"
echo "  🔍 Zoom viral: FFmpeg zoompan dinámico"
echo ""
echo "Carpeta de salida: $OUTPUT"
echo ""
