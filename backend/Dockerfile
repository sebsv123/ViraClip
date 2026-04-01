# === ViraClip Backend: NVIDIA CUDA + Python 3.11 ===
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies — todo de una vez para minimizar capas
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    ffmpeg curl unzip \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && rm -rf /var/lib/apt/lists/*

# Deno para yt-dlp
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_DIR=/root/.deno
ENV PATH="/root/.deno/bin:${PATH}"

# uv package manager
RUN pip install uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./

RUN uv venv .venv && uv sync

# yt-dlp actualizado
RUN uv pip install --no-cache --upgrade "yt-dlp[default]"

# === Core AI: faster-whisper + transformers + librosa + PyTorch CUDA ===
RUN uv pip install --no-cache \
    faster-whisper \
    transformers \
    sentencepiece \
    librosa \
    scipy \
    numpy \
    && uv pip install --no-cache torch torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu124

# === Scene detection + HTTP ===
RUN uv pip install --no-cache \
    "scenedetect[opencv]>=0.6.5" \
    "httpx>=0.27.0"

# === Nuevos módulos para pipeline viral ===
# sentence-transformers: B-roll semántico (semantic_broll_service.py)
# mediapipe: face detection + crop 9:16
# opencv-python-headless: requerido por mediapipe
# moviepy: non-linear editing, zoom dinámico
# Pillow: thumbnails, hook text overlay
# pydub: background_music_service.py (audio ducking)
RUN uv pip install --no-cache \
    sentence-transformers \
    mediapipe \
    opencv-python-headless \
    "moviepy>=2.0.0" \
    Pillow \
    pydub \
    psutil

COPY src/ ./src/
COPY fonts/ ./fonts/
COPY transitions/ ./transitions/

RUN mkdir -p /app/uploads /app/clips /app/logs /app/models /app/assets/sounds /tmp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD .venv/bin/python -c "import psutil, mediapipe, faster_whisper; print('ok')" || exit 1

EXPOSE 8000

CMD [".venv/bin/uvicorn", "src.main_refactored:app", "--host", "0.0.0.0", "--port", "8000"]