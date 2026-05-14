#!/bin/sh
# Entrypoint script para ComfyUI con ViraClip
# Instala dependencias de custom_nodes y luego inicia ComfyUI

echo "[ViraClip] Iniciando entrypoint..."

# Instalar dependencias de custom_nodes si existen
if [ -d "/comfyui/custom_nodes" ]; then
    echo "[ViraClip] Instalando dependencias de custom_nodes..."
    
    for node_dir in /comfyui/custom_nodes/*/; do
        if [ -f "${node_dir}requirements.txt" ]; then
            node_name=$(basename "$node_dir")
            echo "[ViraClip] Instalando: $node_name"
            pip3 install --no-cache-dir -r "${node_dir}requirements.txt" 2>&1 | tail -3
        fi
    done
    
    echo "[ViraClip] Dependencias instaladas"
fi

# Iniciar ComfyUI
# EXTRA_ARGS permite override desde docker-compose sin reconstruir imagen.
# CPU-only mode (RTX 5070 Blackwell no tiene soporte PyTorch CUDA aún).
: "${COMFYUI_EXTRA_ARGS:=--cpu}"

echo "[ViraClip] Iniciando ComfyUI en 0.0.0.0:8188 (args: $COMFYUI_EXTRA_ARGS)"
exec python3 main.py --listen 0.0.0.0 --port 8188 $COMFYUI_EXTRA_ARGS
