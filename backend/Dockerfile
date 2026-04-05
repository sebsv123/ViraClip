# === ViraClip Backend: NVIDIA CUDA + Python 3.11 ===
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

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
    psutil \
    "ultralytics>=8.3.0" \
    "deap>=1.4.0" \
    matplotlib \
    "pymilvus>=2.3.0" \
    "redis[asyncio]>=4.5.0"

# === Phase 7: Dataset Integration ===
# HuggingFace datasets library para TikTok-Videos
# Kaggle API para Short Video Engagement
# Google API client para YouTube Trending
# Pandas/scikit-learn para training
RUN uv pip install --no-cache \
    "datasets>=2.14.0" \
    "huggingface-hub>=0.17.0" \
    "kaggle>=1.5.16" \
    "google-api-python-client>=2.100.0" \
    "pandas>=2.0.0" \
    "scikit-learn>=1.3.0" \
    "xgboost>=2.0.0"

# === Phase 2.5: CLAP SFX semantic matching ===
# msclap: LAION CLAP for text-to-audio nearest-neighbor SFX matching
# Optional — falls back to filename matching when not installed
RUN uv pip install --no-cache \
    "msclap>=1.3.3" || true

# === Phase 8.4: ONNX export + fast CPU inference ===
# onnxruntime: 3-5x faster inference vs sklearn/PyTorch; mobile/edge deployable
# skl2onnx: converts sklearn pipelines to ONNX format
# Optional — falls back to sklearn/PyTorch inference when not installed
RUN uv pip install --no-cache \
    "onnxruntime>=1.17.0" \
    "skl2onnx>=1.16.0" \
    "onnx>=1.15.0" || true

# === Phase 3: GPU Generative AI ===
# diffusers: LTX-Video T2V + SD/SDXL pipelines
# peft: LoRA adapters
# accelerate: multi-GPU + mixed precision
# TTS: Coqui XTTS v2 narration
# imageio[ffmpeg]: frame I/O for T2V output
# safetensors: efficient model weight format
# basicsr + realesrgan: Real-ESRGAN upscaling
# Optional (heavy) — falls back gracefully when GPU unavailable
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
# prometheus-client: metrics for monitoring
# google-api-python-client: YouTube API integration
# google-auth: OAuth authentication
RUN uv pip install --no-cache \
    "prometheus-client>=0.19.0" \
    "google-api-python-client>=2.120.0" \
    "google-auth-httplib2>=0.2.0" \
    "google-auth-oauthlib>=1.2.0" || true

COPY src/ ./src/
COPY fonts/ ./fonts/
COPY transitions/ ./transitions/
COPY scripts/ ./scripts/

RUN mkdir -p /app/uploads /app/clips /app/logs /app/models /app/models/onnx /app/assets/sounds /app/assets/sounds/bgm /app/fonts /app/sfx_library /tmp

# Pre-generate synthetic SFX so SoundDesignService has assets at startup
RUN .venv/bin/python /app/scripts/generate_sfx.py || echo "⚠ SFX generation failed — will fall back to loudnorm-only"

# TikTok-style subtitle font — Oswald Bold (Google Fonts, OFL license).
# Saved as TikTokSans-Regular.ttf so existing code finds it without changes.
# Falls back gracefully to Arial if CDN is unreachable at build time.
RUN curl -fsSL \
    "https://fonts.gstatic.com/s/oswald/v53/TK3_WkUHHAIjg75cFRf3bXL8LICs13NvgUFoZAaRliE.ttf" \
    -o /app/fonts/TikTokSans-Regular.ttf \
    || echo "⚠ Font download skipped — Arial fallback will be used"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD .venv/bin/python -c "import psutil, mediapipe, faster_whisper; print('ok')" || exit 1

EXPOSE 8000

CMD [".venv/bin/uvicorn", "src.main_refactored:app", "--host", "0.0.0.0", "--port", "8000"]