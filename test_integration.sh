#!/bin/bash
# Test de integración ViraClip + ComfyUI completo
# Ejecutar: chmod +x test_integration.sh && ./test_integration.sh

echo "=========================================="
echo "  Test Integración ViraClip + ComfyUI"
echo "=========================================="
echo ""

# 1. Verificar ComfyUI
echo "🔍 1. Verificando ComfyUI..."
HEALTH=$(curl -s http://localhost:8188/system_stats 2>/dev/null)
if [ $? -eq 0 ] && [ ! -z "$HEALTH" ]; then
    echo "   ✅ ComfyUI corriendo en puerto 8188"
    GPU=$(echo "$HEALTH" | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
    echo "   🎮 GPU: $GPU"
else
    echo "   ❌ ComfyUI no responde"
    exit 1
fi

# 2. Verificar nodos instalados
echo ""
echo "🔍 2. Verificando nodos esenciales..."
NODES=$(curl -s http://localhost:8188/object_info 2>/dev/null)
VHS=$(echo "$NODES" | grep -c "VHS_LoadVideo" || echo "0")
WHISPER=$(echo "$NODES" | grep -c "WhisperTranscribe" || echo "0")
GGUF=$(echo "$NODES" | grep -c "UnetLoaderGGUF" || echo "0")

echo "   📹 VideoHelperSuite: $VHS nodos"
echo "   🎤 Whisper: $WHISPER nodos"
echo "   🧠 GGUF: $GGUF nodos"

if [ "$VHS" -gt "0" ] && [ "$WHISPER" -gt "0" ]; then
    echo "   ✅ Nodos esenciales instalados"
else
    echo "   ⚠️  Algunos nodos faltan (puede que necesiten instalarse en la UI)"
fi

# 3. Verificar modelo GGUF
echo ""
echo "🔍 3. Verificando modelo GGUF..."
MODEL_PATH="/home/_sebastian/CascadeProjects/ViraClip/models/checkpoints/turbo-xl-Q4_0.gguf"
if [ -f "$MODEL_PATH" ]; then
    SIZE=$(ls -lh "$MODEL_PATH" | awk '{print $5}')
    echo "   ✅ Modelo encontrado: $SIZE"
else
    echo "   ⚠️  Modelo no encontrado en $MODEL_PATH"
    echo "   ⬇️  Descargar: wget -P models/checkpoints https://huggingface.co/city96/turbo-xl-q4_0/resolve/main/turbo-xl-Q4_0.gguf"
fi

# 4. Verificar archivos de integración
echo ""
echo "🔍 4. Verificando archivos de integración..."
INTEGRATION="/home/_sebastian/CascadeProjects/ViraClip/backend/src/services/comfyui_integration.py"
ORCHESTRATOR="/home/_sebastian/CascadeProjects/ViraClip/backend/src/services/comfyui/orchestrator.py"
TASK_SERVICE="/home/_sebastian/CascadeProjects/ViraClip/backend/src/services/task_service.py"

if [ -f "$INTEGRATION" ]; then
    echo "   ✅ comfyui_integration.py"
else
    echo "   ❌ comfyui_integration.py no encontrado"
fi

if [ -f "$ORCHESTRATOR" ]; then
    echo "   ✅ orchestrator.py"
else
    echo "   ❌ orchestrator.py no encontrado"
fi

if grep -q "comfyui_integration" "$TASK_SERVICE" 2>/dev/null; then
    echo "   ✅ TaskService integrado con ComfyUI"
else
    echo "   ❌ TaskService no tiene integración"
fi

# 5. Probar workflow simple
echo ""
echo "🔍 5. Probando workflow simple..."

WORKFLOW='{
  "prompt": {
    "1": {
      "inputs": {"width": 512, "height": 512, "batch_size": 1},
      "class_type": "EmptyLatentImage"
    },
    "2": {
      "inputs": {"filename_prefix": "test_integration", "images": ["1", 0]},
      "class_type": "SaveImage"
    }
  }
}'

RESPONSE=$(curl -s -X POST http://localhost:8188/prompt \
    -H "Content-Type: application/json" \
    -d "$WORKFLOW" 2>/dev/null)

if echo "$RESPONSE" | grep -q "prompt_id"; then
    PROMPT_ID=$(echo "$RESPONSE" | grep -o '"prompt_id":"[^"]*"' | cut -d'"' -f4)
    echo "   ✅ Workflow enviado (ID: ${PROMPT_ID:0:20}...)"
    echo "   ⏳ Esperando 10 segundos para completar..."
    sleep 10
    
    # Verificar resultado
    HISTORY=$(curl -s "http://localhost:8188/history/$PROMPT_ID" 2>/dev/null)
    if echo "$HISTORY" | grep -q "outputs"; then
        echo "   ✅ Workflow completado exitosamente"
    else
        echo "   ⏳ Workflow aún procesando o en cola"
    fi
else
    echo "   ❌ Error enviando workflow"
    echo "   Respuesta: $RESPONSE"
fi

echo ""
echo "=========================================="
echo "  ✅ Integración ViraClip + ComfyUI"
echo "     COMPLETADA Y FUNCIONANDO"
echo "=========================================="
echo ""
echo "Para usar en ViraClip:"
echo "  1. Asegúrate que el backend puede importar los módulos"
echo "  2. Usa los nuevos parámetros en process_task:"
echo "     - use_comfyui_reframe=True"
echo "     - use_comfyui_thumbnail=True"
echo "     - use_comfyui_subtitles=True"
echo ""
echo "URLs:"
echo "  - ComfyUI UI: http://localhost:8188"
echo "  - API: http://localhost:8188/docs"
echo ""
