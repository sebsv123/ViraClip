# ViraClip ComfyUI Optimizado para RTX 5070 8GB VRAM
# CUDA 12.8 + PyTorch 2.10.0 cu130 para Blackwell (RTX 50-series sm_120)
# PyTorch 2.9.0 cu130 has a known bug with RTX 5070 "CUDA unknown error"
# Upgraded to 2.10.0 cu130 which fixes Blackwell (sm_120) support
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512,garbage_collection_threshold:0.6
ENV CUDA_MODULE_LOADING=LAZY
ENV OMP_NUM_THREADS=8
ENV PIP_DEFAULT_TIMEOUT=600

RUN apt-get update && apt-get install -y \
    python3 python3-pip git wget ffmpeg \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Override pip config to use PyPI directly (nvidia's pypi.nvidia.com proxy times out)
RUN pip3 config set global.index-url https://pypi.org/simple/ && \
    pip3 config set global.extra-index-url https://download.pytorch.org/whl/cu130

WORKDIR /comfyui

# PyTorch 2.10.0 con CUDA 12.8 (compatible con driver CUDA 13.2+)
# 2.10.0 fixes the "CUDA unknown error" on RTX 5070 Blackwell (sm_120)
# PyTorch 2.9.0 cu130 has a known bug with Blackwell GPUs
RUN pip3 install --no-cache-dir --default-timeout=600 \
    torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 \
    --index-url https://download.pytorch.org/whl/cu130

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
