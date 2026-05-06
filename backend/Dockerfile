# === ViraClip Backend: NVIDIA CUDA + Python 3.11 ===
FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies — todo de una vez para minimizar capas
# Remove CUDA apt repo to avoid mirror-sync failures (CUDA libs already in base image)
RUN rm -f /etc/apt/sources.list.d/cuda*.list /etc/apt/sources.list.d/nvidia*.list \
    && apt-get update && apt-get install -y --no-install-recommends \
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
    faster-whisper==1.1.1 \
    transformers \
    sentencepiece \
    librosa \
    scipy \
    numpy

# cu128 requerido para Blackwell (compute capability 12.0)
# --index-url (no --extra-index-url) para evitar resolver cu124
RUN uv pip install --no-cache \
    torch==2.8.0+cu128 \
    torchaudio==2.8.0+cu128 \
    --index-url https://download.pytorch.org/whl/cu128

RUN uv pip install --no-cache whisperx

# === Scene detection + HTTP ===
RUN uv pip install --no-cache \
    "scenedetect[opencv]>=0.6.5" \
    "httpx>=0.27.0"

# === Audio: edge-tts (free TTS, zero cost, no API key) ===
RUN uv pip install --no-cache "edge-tts>=6.1.9" || true

# === Nuevos módulos para pipeline viral ===
RUN uv pip install --no-cache \
    sentence-transformers \
    mediapipe \
    opencv-python-headless \
    "moviepy>=2.0.0" \
    Pillow \
    pydub \
    psutil \
    "ultralytics>=8.3.0" \
    "deap>=1.4.0" \
    matplotlib \
    "pymilvus>=2.3.0" \
    "redis[asyncio]>=4.5.0"

# === Phase 7: Dataset Integration ===
RUN uv pip install --no-cache \
    "datasets>=2.14.0" \
    "huggingface-hub>=0.17.0" \
    "kaggle>=1.5.16" \
    "google-api-python-client>=2.100.0" \
    "pandas>=2.0.0" \
    "scikit-learn>=1.3.0" \
    "xgboost>=2.0.0"

# === Phase 2.5: CLAP SFX semantic matching ===
RUN uv pip install --no-cache \
    "msclap>=1.3.3" || true

# === Phase 8.4: ONNX export + fast CPU inference ===
RUN uv pip install --no-cache \
    "onnxruntime>=1.17.0" \
    "skl2onnx>=1.16.0" \
    "onnx>=1.15.0" || true

# === Phase 3: GPU Generative AI ===
RUN uv pip install --no-cache \
    "diffusers>=0.30.0" \
    "accelerate>=0.30.0" \
    "peft>=0.11.0" \
    "safetensors>=0.4.0" \
    "imageio[ffmpeg]>=2.34.0" \
    "imageio-ffmpeg>=0.5.0" || true
RUN uv pip install --no-cache "TTS>=0.22.0" || true
RUN uv pip install --no-cache \
    "basicsr>=1.4.2" \
    "realesrgan>=0.3.0" || true

# === Phase 10: Automation & Monitoring ===
RUN uv pip install --no-cache \
    "prometheus-client>=0.19.0" \
    "google-api-python-client>=2.120.0" \
    "google-auth-httplib2>=0.2.0" \
    "google-auth-oauthlib>=1.2.0" || true

COPY src/ ./src/
COPY fonts/ ./fonts/
COPY transitions/ ./transitions/
COPY scripts/ ./scripts/

RUN mkdir -p /app/uploads /app/clips /app/logs /app/models /app/models/onnx /app/assets/sounds /app/assets/sounds/bgm /app/fonts /app/sfx_library /tmp \
    /app/storage/ingested \
    /app/data \
    /app/data/creator_profiles

# Pre-generate synthetic SFX so SoundDesignService has assets at startup
RUN .venv/bin/python /app/scripts/generate_sfx.py || echo "⚠ SFX generation failed — will fall back to loudnorm-only"

# Bootstrap sample LUT files so lut_service has presets available at startup
RUN mkdir -p /app/luts && .venv/bin/python /app/scripts/bootstrap_luts.py || echo "⚠ LUT bootstrap failed — LUT step will be skipped per-clip"

# TikTok-style subtitle font — Oswald Bold (Google Fonts, OFL license).
RUN curl -fsSL \
    "https://fonts.gstatic.com/s/oswald/v53/TK3_WkUHHAIjg75cFRf3bXL8LICs13NvgUFoZAaRliE.ttf" \
    -o /app/fonts/TikTokSans-Regular.ttf \
    || echo "⚠ Font download skipped — Arial fallback will be used"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD .venv/bin/python -c "import psutil, mediapipe, faster_whisper; print('ok')" || exit 1

EXPOSE 8000

CMD [".venv/bin/uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
