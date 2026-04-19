#!/bin/bash
# Instala dependencias de todos los custom_nodes antes de iniciar ComfyUI

echo "=========================================="
echo "Instalando dependencias de Custom Nodes"
echo "=========================================="

# ── Clone ComfyUI-LTXVideo if not present ────────────────────────────────────
LTXV_DIR="/comfyui/custom_nodes/ComfyUI-LTXVideo"
if [ ! -d "$LTXV_DIR" ]; then
    echo "📦 Cloning ComfyUI-LTXVideo..."
    git clone https://github.com/Lightricks/ComfyUI-LTXVideo "$LTXV_DIR" 2>&1 | tail -3
fi

# ── Install requirements for all custom nodes ────────────────────────────────
for node_dir in /comfyui/custom_nodes/*/; do
    if [ -f "${node_dir}requirements.txt" ]; then
        echo "📦 Instalando: $(basename $node_dir)"
        pip3 install --no-cache-dir -r "${node_dir}requirements.txt" 2>&1 | grep -v "already satisfied" || true
    fi
done

echo "✅ Dependencias instaladas"
echo "=========================================="
