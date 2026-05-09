# === ViraClip Backend: TRUE Multi-Stage Build ===
# CUDA 12.8 base + cu130 PyTorch for RTX 5070 (Blackwell sm_120) support
# cu130 REQUIRED — cu128 crashes on RTX 5070 with "CUDA unknown error"
# Strategy:
#   Stage 1 (builder): Install ALL Python deps in one shot, clean caches
#   Stage 2 (runtime): Minimal image — copy only .venv + app code from builder
#   Result: ~6-8GB final image instead of 42GB

# ── Stage 1: Builder ──────────────────────────────────────────────────
FROM nvidia/cuda:12.8.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DEFAULT_TIMEOUT=600

# System dependencies (single layer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    ffmpeg curl unzip \
    libsndfile1 \
    libgl1 libglib2.0-0 \
    libsm6 libxext6 libxrender-dev \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && rm -rf /var/lib/apt/lists/*

# Deno for yt-dlp
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_DIR=/root/.deno
ENV PATH="/root/.deno/bin:${PATH}"

# uv package manager
RUN pip install uv

WORKDIR /app

# Create venv with pip included
RUN uv venv --seed .venv

# ── Install ALL Python dependencies in ONE shot ───────────────────────
# This is the key optimization: one RUN instruction instead of 28
# cu130 PyTorch for RTX 5070 (Blackwell sm_120) support
# cu128 crashes on RTX 5070 — cu130 is REQUIRED
# Optional packages (diffusers, TTS, realesrgan, onnx, msclap) are EXCLUDED
# from the base image — they can be pip-installed at runtime if needed
COPY pyproject.toml uv.lock* ./
RUN .venv/bin/pip install --no-cache-dir --default-timeout=600 \
    torch==2.10.0+cu130 \
    torchvision==0.25.0+cu130 \
    torchaudio==2.10.0+cu130 \
    --index-url https://download.pytorch.org/whl/cu130 \
    && uv sync --no-build-isolation --extra-index-url https://download.pytorch.org/whl/cu130 \
    && .venv/bin/pip install --no-cache-dir --default-timeout=600 \
        torch==2.10.0+cu130 \
        torchvision==0.25.0+cu130 \
        torchaudio==2.10.0+cu130 \
        --index-url https://download.pytorch.org/whl/cu130 \
    && .venv/bin/pip install --no-cache-dir --default-timeout=600 \
        "faster-whisper==1.1.1" \
        "whisperx" \
        "sentence-transformers" \
        "mediapipe" \
        "opencv-python-headless" \
        "moviepy>=2.0.0" \
        "Pillow" "pydub" "psutil" \
        "ultralytics>=8.3.0" \
        "scenedetect[opencv]>=0.6.5" \
        "httpx>=0.27.0" \
        "edge-tts>=6.1.9" \
        "datasets>=2.14.0" \
        "huggingface-hub>=0.17.0" \
        "pandas>=2.0.0" \
        "scikit-learn>=1.3.0" \
        "xgboost>=2.0.0" \
        "prometheus-client>=0.19.0" \
        "deap>=1.4.0" \
        "matplotlib" \
        "pymilvus>=2.3.0" \
        "redis[asyncio]>=4.5.0" \
        "google-api-python-client>=2.100.0" \
        "kaggle>=1.5.16" \
    && rm -rf /root/.cache/pip /root/.cache/uv /tmp/*

# ── Stage 2: Runtime (minimal) ────────────────────────────────────────
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Only essential runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv \
    ffmpeg curl \
    libsndfile1 \
    libgl1 libglib2.0-0 \
    libsm6 libxext6 libxrender-dev \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy .venv from builder (preserves all installed packages)
COPY --from=builder /app/.venv ./.venv

# Copy Deno from builder (required by yt-dlp for JS challenge solving)
COPY --from=builder /root/.deno /root/.deno
ENV PATH="/root/.deno/bin:/app/.venv/bin:${PATH}"

# Copy application code + assets
COPY src/ ./src/
COPY fonts/ ./fonts/
COPY transitions/ ./transitions/
COPY scripts/ ./scripts/

# Create required directories
RUN mkdir -p /app/uploads /app/clips /app/logs /app/models /app/models/onnx \
    /app/assets/sounds /app/assets/sounds/bgm /app/fonts /app/sfx_library /tmp \
    /app/storage/ingested /app/data /app/data/creator_profiles /app/luts

# Generate SFX assets at build time (fast, pure Python + ffmpeg)
RUN .venv/bin/python /app/scripts/generate_sfx_assets.py || echo "SFX generation skipped"

# Bootstrap LUT files
RUN .venv/bin/python /app/scripts/bootstrap_luts.py || echo "LUT bootstrap skipped"

# Download subtitle font (Oswald v57 — verified working URL)
RUN curl -fsSL \
    "https://fonts.gstatic.com/s/oswald/v57/TK3_WkUHHAIjg75cFRf3bXL8LICs1xZogUE.ttf" \
    -o /app/fonts/TikTokSans-Regular.ttf \
    || echo "Font download skipped — Arial fallback"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD .venv/bin/python -c "import psutil, mediapipe, faster_whisper; print('ok')" || exit 1

EXPOSE 8000

CMD [".venv/bin/uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
