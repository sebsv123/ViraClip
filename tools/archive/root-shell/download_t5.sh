#!/bin/bash
# Descargar modelo T5 para LTX-Video

echo "📥 Descargando T5XXL para LTX-Video..."

# Crear directorio si no existe
mkdir -p ~/CascadeProjects/ViraClip/models/clip

# Descargar desde HuggingFace
cd ~/CascadeProjects/ViraClip/models/clip

# Opción 1: T5XXL FP8 (más pequeño, recomendado para 8GB VRAM)
if [ ! -f "t5xxl_fp8_e4m3fn.safetensors" ]; then
    echo "Descargando t5xxl_fp8_e4m3fn.safetensors..."
    wget -q --show-progress "https://huggingface.co/comfyanonymous/Wuerstchen-3.5/resolve/main/text_encoders/t5xxl_fp8_e4m3fn.safetensors" -O t5xxl_fp8_e4m3fn.safetensors || \
    wget -q --show-progress "https://huggingface.co/Comfyorg/Wan-2_1-T2V-14B-Instruct/resolve/main/t5xxl_fp8_e4m3fn.safetensors" -O t5xxl_fp8_e4m3fn.safetensors || \
    echo "⚠️  No se pudo descargar automáticamente. Descarga manual desde: https://huggingface.co/comfyanonymous"
else
    echo "✅ T5XXL FP8 ya existe"
fi

# Opción 2: T5XXL FP16 (mejor calidad, más pesado)
# if [ ! -f "t5xxl_fp16.safetensors" ]; then
#     wget -q --show-progress "https://huggingface.co/comfyanonymous/Wuerstchen-3.5/resolve/main/text_encoders/t5xxl_fp16.safetensors"
# fi

ls -lh ~/CascadeProjects/ViraClip/models/clip/
echo ""
echo "✅ Modelos T5 listos en ~/CascadeProjects/ViraClip/models/clip/"
