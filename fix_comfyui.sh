#!/bin/bash
# Script para reparar ComfyUI y activar VHS_LoadVideo

echo "=========================================="
echo "Reparando ComfyUI - VHS_LoadVideo"
echo "=========================================="
echo ""

cd ~/CascadeProjects/ViraClip

# 1. Detener contenedor
echo "[1/6] Deteniendo contenedor..."
docker compose stop comfyui 2>/dev/null || true

# 2. Eliminar contenedor antiguo
echo "[2/6] Eliminando contenedor antiguo..."
docker compose rm -f comfyui 2>/dev/null || true

# 3. Reconstruir con nuevo entrypoint
echo "[3/6] Reconstruyendo imagen..."
docker compose build --no-cache comfyui

# 4. Iniciar
echo "[4/6] Iniciando contenedor..."
docker compose up -d comfyui

# 5. Esperar a que ComfyUI inicie
echo "[5/6] Esperando que ComfyUI inicie (60s)..."
for i in {1..12}; do
    echo -n "."
    sleep 5
    if curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
        echo ""
        echo "[OK] ComfyUI responde!"
        break
    fi
done
echo ""

# 6. Verificar VHS_LoadVideo
echo "[6/6] Verificando VHS_LoadVideo..."
if curl -s http://localhost:8188/object_info 2>/dev/null | grep -q "VHS_LoadVideo"; then
    echo ""
    echo "=========================================="
    echo "✅ VHS_LoadVideo ENCONTRADO!"
    echo "=========================================="
    echo ""
    echo "Ahora puedes ejecutar:"
    echo "  python3 generate_real_shorts.py"
    echo ""
else
    echo ""
    echo "⚠️  VHS_LoadVideo NO encontrado todavía"
    echo "Esperando 30s más..."
    sleep 30
    
    if curl -s http://localhost:8188/object_info 2>/dev/null | grep -q "VHS_LoadVideo"; then
        echo "✅ VHS_LoadVideo ENCONTRADO!"
    else
        echo ""
        echo "❌ Error: Revisa los logs:"
        echo "   docker logs viraclip-comfyui"
    fi
fi
