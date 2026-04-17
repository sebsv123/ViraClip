#!/bin/bash
# Instala dependencias de todos los custom_nodes antes de iniciar ComfyUI

echo "=========================================="
echo "Instalando dependencias de Custom Nodes"
echo "=========================================="

for node_dir in /comfyui/custom_nodes/*/; do
    if [ -f "${node_dir}requirements.txt" ]; then
        echo "📦 Instalando: $(basename $node_dir)"
        pip3 install --no-cache-dir -r "${node_dir}requirements.txt" 2>&1 | grep -v "already satisfied" || true
    fi
done

echo "✅ Dependencias instaladas"
echo "=========================================="
