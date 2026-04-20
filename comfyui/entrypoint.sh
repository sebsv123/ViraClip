#!/bin/sh
# Entrypoint script para ComfyUI con ViraClip
# Instala dependencias de custom_nodes y luego inicia ComfyUI

echo "[ViraClip] Iniciando entrypoint..."

# ── Clone ComfyUI-LTXVideo if not present ────────────────────────────────────
LTXV_DIR="/comfyui/custom_nodes/ComfyUI-LTXVideo"
if [ ! -d "$LTXV_DIR" ]; then
    echo "[ViraClip] Cloning ComfyUI-LTXVideo..."
    git clone https://github.com/Lightricks/ComfyUI-LTXVideo "$LTXV_DIR" 2>&1 | tail -5
fi

# ── Clone ComfyUI-VideoUpscale_WithModel if not present ──────────────────────
UPSCALE_DIR="/comfyui/custom_nodes/ComfyUI-VideoUpscale_WithModel"
if [ ! -d "$UPSCALE_DIR" ]; then
    echo "[ViraClip] Cloning ComfyUI-VideoUpscale_WithModel..."
    git clone https://github.com/ShmuelRonen/ComfyUI-VideoUpscale_WithModel "$UPSCALE_DIR" 2>&1 | tail -5
fi

# ── Download RealESRGAN model if not present ──────────────────────────────────
REALESRGAN_MODEL="/comfyui/models/upscale_models/RealESRGAN_x4plus.pth"
if [ ! -f "$REALESRGAN_MODEL" ]; then
    echo "[ViraClip] Downloading RealESRGAN_x4plus.pth (~65MB)..."
    mkdir -p /comfyui/models/upscale_models
    wget -q --show-progress \
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" \
        -O "$REALESRGAN_MODEL" \
    && echo "[ViraClip] RealESRGAN model downloaded OK" \
    || echo "[ViraClip] WARNING: RealESRGAN download failed (will retry on next start)"
fi

# ── Download LTX-Video model if not present ──────────────────────────────────
LTXV_MODEL="/comfyui/models/checkpoints/ltxv-2b-0.9.8-distilled-fp8.safetensors"
if [ ! -f "$LTXV_MODEL" ]; then
    echo "[ViraClip] Downloading LTX-Video 0.9.8-distilled FP8 (~3.8 GB)..."
    pip3 install --no-cache-dir huggingface_hub 2>/dev/null
    python3 -c "
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id='Lightricks/LTX-Video',
    filename='ltxv-2b-0.9.8-distilled-fp8.safetensors',
    local_dir='/comfyui/models/checkpoints/',
    local_dir_use_symlinks=False
)
print('[ViraClip] LTX-Video model downloaded OK')
" 2>&1 || echo "[ViraClip] WARNING: LTX-Video model download failed (will retry on next start)"
fi

# ── Install requirements for all custom_nodes ────────────────────────────────
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
# Default: --lowvram para 8GB VRAM (RTX 5070 Laptop) — evita OOM en Flux UNET + T5.
#   --lowvram                     : offloadea bloques a RAM, solo el activo vive en GPU
#   --use-split-cross-attention   : reduce picos de VRAM en attention
#   --disable-smart-memory        : no cachea modelos entre prompts (libera T5 tras encode)
: "${COMFYUI_EXTRA_ARGS:=--lowvram --use-split-cross-attention --disable-smart-memory}"

echo "[ViraClip] Iniciando ComfyUI en 0.0.0.0:8188 (args: $COMFYUI_EXTRA_ARGS)"
exec python3 main.py --listen 0.0.0.0 --port 8188 $COMFYUI_EXTRA_ARGS
