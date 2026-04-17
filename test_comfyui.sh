#!/bin/bash
# Test de integración ViraClip + ComfyUI
# Ejecutar: chmod +x test_comfyui.sh && ./test_comfyui.sh

echo "=================================="
echo "  Test ViraClip + ComfyUI"
echo "=================================="
echo ""

# Test 1: Health Check
echo "🧪 Test 1: Health Check..."
HEALTH=$(curl -s http://localhost:8188/system_stats 2>/dev/null)
if [ $? -eq 0 ] && [ ! -z "$HEALTH" ]; then
    echo "✅ ComfyUI responde"
    echo "$HEALTH" | grep -o '"name":"[^"]*"' | head -1
else
    echo "❌ ComfyUI no responde"
    exit 1
fi

# Test 2: Enviar workflow simple
echo ""
echo "🧪 Test 2: Enviar workflow de prueba..."

WORKFLOW='{"prompt":{"1":{"inputs":{"width":512,"height":512,"batch_size":1},"class_type":"EmptyLatentImage"},"2":{"inputs":{"filename_prefix":"test","images":["1",0]},"class_type":"SaveImage"}}}'

RESPONSE=$(curl -s -X POST http://localhost:8188/prompt \
    -H "Content-Type: application/json" \
    -d "$WORKFLOW" 2>/dev/null)

if echo "$RESPONSE" | grep -q "prompt_id"; then
    PROMPT_ID=$(echo "$RESPONSE" | grep -o '"prompt_id":"[^"]*"' | cut -d'"' -f4)
    echo "✅ Workflow enviado (ID: $PROMPT_ID)"
    echo "   Esperando resultado..."
    
    # Polling por 30 segundos
    for i in {1..15}; do
        sleep 2
        HISTORY=$(curl -s http://localhost:8188/history/$PROMPT_ID 2>/dev/null)
        if echo "$HISTORY" | grep -q "outputs"; then
            echo "✅ Workflow completado"
            break
        fi
        echo "   ...intentando ($i/15)"
    done
else
    echo "❌ Error enviando workflow: $RESPONSE"
fi

# Test 3: Verificar nodos instalados
echo ""
echo "🧪 Test 3: Verificar nodos instalados..."
NODES=$(curl -s http://localhost:8188/object_info 2>/dev/null | grep -c "class_type" || echo "0")
if [ "$NODES" -gt "0" ]; then
    echo "✅ $NODES nodos disponibles"
else
    echo "⚠️  No se pudo verificar nodos"
fi

echo ""
echo "=================================="
echo "  Test completado"
echo "=================================="
echo ""
echo "URLs disponibles:"
echo "  - ComfyUI UI: http://localhost:8188"
echo "  - API: http://localhost:8188/docs"
