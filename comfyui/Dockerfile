# ViraClip ComfyUI — builds ComfyUI from source with GPU + custom nodes
# Base: PyTorch 2.3 + CUDA 12.1 (NVIDIA runtime required on host)
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home/comfy

# ── ComfyUI core ──────────────────────────────────────────────────────────────
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git . \
    && pip install --no-cache-dir -r requirements.txt

# ── Custom nodes ──────────────────────────────────────────────────────────────
WORKDIR /home/comfy/custom_nodes

# VideoHelperSuite — VHS_LoadVideo, VHS_VideoCombine
RUN git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
    && pip install --no-cache-dir -r ComfyUI-VideoHelperSuite/requirements.txt

# AnimateDiff-Evolved — ADE_AnimateDiffLoaderWithContext
RUN git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git \
    && pip install --no-cache-dir -r ComfyUI-AnimateDiff-Evolved/requirements.txt

WORKDIR /home/comfy

# ── ViraClip custom nodes (bind-mounted at runtime) ───────────────────────────
# The viraclip_nodes directory is mounted at start via docker-compose volumes.

EXPOSE 8188

# ENTRYPOINT reads CLI_ARGS env var, falls back to sensible defaults
CMD ["sh", "-c", "python main.py --listen 0.0.0.0 --port 8188 ${CLI_ARGS:-}"]
