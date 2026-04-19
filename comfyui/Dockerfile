# ViraClip ComfyUI Optimizado para RTX 5070 8GB VRAM
# CUDA 12.8 + PyTorch 2.7 para Blackwell (RTX 50-series)
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512,garbage_collection_threshold:0.6
ENV CUDA_MODULE_LOADING=LAZY
ENV OMP_NUM_THREADS=8

RUN apt-get update && apt-get install -y \
    python3 python3-pip git wget curl ffmpeg \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /comfyui

# PyTorch 2.7 con CUDA 12.8 para Blackwell/RTX 5070
RUN pip3 install --no-cache-dir \
    torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 \
    --index-url https://download.pytorch.org/whl/cu128

# ComfyUI core
RUN git clone https://github.com/comfyanonymous/ComfyUI.git . \
    && pip3 install --no-cache-dir -r requirements.txt

# Instalar dependencias comunes de VideoHelperSuite (por si el volumen no está listo inmediatamente)
RUN pip3 install --no-cache-dir \
    opencv-python-headless \
    imageio-ffmpeg \
    Pillow \
    numpy \
    typing-extensions

# Script de entrypoint que instala deps de custom_nodes al iniciar
COPY entrypoint.sh /comfyui/entrypoint.sh
RUN chmod +x /comfyui/entrypoint.sh

EXPOSE 8188

# Entrypoint que instala deps y luego inicia ComfyUI
ENTRYPOINT ["/comfyui/entrypoint.sh"]
