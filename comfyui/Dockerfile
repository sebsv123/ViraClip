# ViraClip ComfyUI — CPU-only fallback for RTX 5070 (Blackwell)
# Host: driver 595.71.05 (CUDA 13.2), RTX 5070 (sm_120 Blackwell)
# PyTorch does not yet ship pre-built wheels for CUDA 13.x / Blackwell.
# Until official cu130 wheels land, we run ComfyUI in CPU-only mode.
# GPU features (LTXV, Flux, etc.) are disabled via COMFYUI_ENABLED=false.
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV OMP_NUM_THREADS=8
ENV PIP_DEFAULT_TIMEOUT=600

RUN apt-get update && apt-get install -y \
    python3 python3-pip git wget ffmpeg \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /comfyui

# Install CPU-only PyTorch (works on any system, no CUDA dependency)
RUN pip3 install --no-cache-dir --default-timeout=600 \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

# ComfyUI core
RUN git clone https://github.com/comfyanonymous/ComfyUI.git . \
    && pip3 install --no-cache-dir -r requirements.txt

# Common dependencies
RUN pip3 install --no-cache-dir \
    opencv-python-headless \
    imageio-ffmpeg \
    Pillow \
    numpy \
    typing-extensions

# Patch ComfyUI to force CPU device (avoids CUDA init crash on Blackwell RTX 5070)
COPY patch_cpu.py /comfyui/patch_cpu.py
RUN python3 /comfyui/patch_cpu.py

# Script de entrypoint que instala deps de custom_nodes al iniciar
COPY entrypoint.sh /comfyui/entrypoint.sh
RUN chmod +x /comfyui/entrypoint.sh

EXPOSE 8188

ENTRYPOINT ["/comfyui/entrypoint.sh"]
