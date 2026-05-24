# === ViraClip Backend: Optimized Multi-Stage Build ===
# CUDA 13.2 base + cu132 PyTorch for RTX 5070 (Blackwell sm_120) support
# cu130 REQUIRED — cu128 crashes on RTX 5070 with "CUDA unknown error"
# Strategy:
#   Stage 1 (builder): Layered dependency installation for Docker cache efficiency
#     Layer 1: uv sync from pyproject.toml (rebuilds only when deps change)
#     Layer 2: ML deps (faster-whisper, mediapipe, etc. — rarely change)
#     Layer 3: whisperx + TTS (rarely change)
#     Source code is NOT copied here — only pyproject.toml for dep resolution.
#   Stage 2 (runtime): Minimal image — copy only .venv + app code from builder
#   Result: ~6-8GB final image instead of 42GB
#   Rebuild times: code change = ~30s, dep change = ~5min, torch change = ~50min
#
# NVENC strategy:
#   FFmpeg is compiled from source in the builder stage against CUDA 13.2 headers
#   (matching the host driver's CUDA 13.2). Dynamic linking is used so that
#   the binary loads libcuda.so from the NVIDIA container toolkit at runtime,
#   ensuring compatibility with the host driver (595.71.05 / CUDA 13.2).
#   This avoids the "cuInit(0) failed -> CUDA_ERROR_UNKNOWN" error that occurs
#   with CUDA-version-mismatched binaries (e.g. BtbN builds or distro ffmpeg).

# ── Stage 1: Builder ──────────────────────────────────────────────────
FROM nvidia/cuda:13.2.0-devel-ubuntu22.04 AS builder


ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DEFAULT_TIMEOUT=600

# System dependencies (single layer)
# ffmpeg is installed from the NVIDIA CUDA repo (already configured in the
# base image nvidia/cuda:13.2.0-devel-ubuntu22.04). This provides h264_nvenc
# and hevc_nvenc compiled against the same CUDA headers as the host.

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    curl unzip xz-utils \
    libsndfile1 \
    libgl1 libglib2.0-0 \
    libsm6 libxext6 libxrender-dev \
    libavutil-dev libavcodec-dev libavformat-dev \
    ffmpeg \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && rm -rf /var/lib/apt/lists/*

# ── FFmpeg source compilation with NVENC support ──────────────────────
# We compile FFmpeg from source against CUDA 13.2 headers (matching the
# runtime container's CUDA version) with dynamic linking. This ensures the
# binary loads libcuda.so from the NVIDIA container toolkit at runtime,
# making it compatible with any host driver version.
#
# Key flags:
#   --enable-nvenc --enable-cuda-nvcc --enable-ffnvcodec: NVENC encoding
#   --enable-nonfree: required for NVENC (proprietary)
#   --enable-gpl --enable-libx264 --enable-libx265: software encode fallback
#   --enable-shared: dynamic linking against system CUDA libraries
#
# The nv-codec-headers provide the Video Codec SDK headers needed by ffnvcodec.
# We use the latest stable release (n12.2) which supports all NVIDIA GPUs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    nasm \
    yasm \
    pkg-config \
    libx264-dev \
    libx265-dev \
    libnuma-dev \
    libvpx-dev \
    libfdk-aac-dev \
    libmp3lame-dev \
    libopus-dev \
    libvorbis-dev \
    libtheora-dev \
    libass-dev \
    libfreetype6-dev \
    libfontconfig1-dev \
    libfribidi-dev \
    libharfbuzz-dev \
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone nv-codec-headers (NVIDIA Video Codec SDK headers for ffnvcodec)
RUN git clone --depth 1 --branch n12.2.72.0 \
    https://git.videolan.org/git/ffmpeg/nv-codec-headers.git /tmp/nv-codec-headers \
    && cd /tmp/nv-codec-headers \
    && make install \
    && rm -rf /tmp/nv-codec-headers

# Download and compile FFmpeg from source
# We use FFmpeg 7.1 (latest stable release as of 2026-05) with NVENC support.
# The configure flags enable NVENC via ffnvcodec (using the nv-codec-headers
# installed above) and CUDA via nvcc (using the CUDA 13.2 toolkit in the
# devel image). Dynamic linking (-shared) ensures libcuda.so is loaded from
# the NVIDIA container toolkit at runtime.
RUN curl -fsSL "https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz" \
    -o /tmp/ffmpeg-src.tar.xz \
    && tar -xf /tmp/ffmpeg-src.tar.xz -C /tmp/ \
    && cd /tmp/ffmpeg-7.1 \
    && ./configure \
        --prefix=/usr/local \
        --enable-shared \
        --disable-static \
        --enable-nonfree \
        --enable-gpl \
        --enable-version3 \
        --enable-libx264 \
        --enable-libx265 \
        --enable-libvpx \
        --enable-libfdk-aac \
        --enable-libmp3lame \
        --enable-libopus \
        --enable-libvorbis \
        --enable-libtheora \
        --enable-libass \
        --enable-libfreetype \
        --enable-libfontconfig \
        --enable-libfribidi \
        --enable-libharfbuzz \
        --enable-libwebp \
        --enable-nvenc \
        --enable-cuda-nvcc \
        --enable-ffnvcodec \
        --enable-cuvid \
        --nvcc=/usr/local/cuda/bin/nvcc \
        --nvccflags="-gencode arch=compute_89,code=sm_89 -O2" \
        --extra-cflags="-I/usr/local/cuda/include -I/usr/local/include" \
        --extra-ldflags="-L/usr/local/cuda/lib64 -L/usr/local/lib" \
    && make -j$(nproc) \
    && make install \
    && ldconfig \
    && rm -rf /tmp/ffmpeg-src* /tmp/ffmpeg-7.1

# Verify the compiled ffmpeg has NVENC and is dynamically linked
RUN echo "=== FFmpeg version ===" && \
    /usr/local/bin/ffmpeg -version 2>&1 | head -3 && \
    echo "=== NVENC encoders ===" && \
    /usr/local/bin/ffmpeg -hide_banner -encoders 2>&1 | grep -i nvenc || echo "(no NVENC encoders found)" && \
    echo "=== Dynamic linking ===" && \
    ldd /usr/local/bin/ffmpeg | grep -E "(cuda|nvcuvid)" || echo "(no CUDA shared libs linked — NVENC may fail at runtime)"



# Deno for yt-dlp
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_DIR=/root/.deno
ENV PATH="/root/.deno/bin:${PATH}"

# uv package manager
RUN pip install uv

WORKDIR /app

# Create venv with pip included
RUN uv venv --seed .venv

# ── Layer 1: deps pesadas estables (cambian raramente) ─────────────────
# COPY pyproject.toml + uv.lock triggers rebuild only when deps change.
# uv sync installs the project's declared dependencies.
COPY pyproject.toml uv.lock* ./
RUN pip install "protobuf>=3.20.0,<4.0.0" --force-reinstall
ENV UV_HTTP_TIMEOUT=600
RUN uv sync --no-build-isolation --extra-index-url https://download.pytorch.org/whl/cu132 \
    && rm -rf /root/.cache/uv

# ── Layer 2: deps ML secundarias (cambian poco) ───────────────────────
# sentence-transformers, mediapipe, edge-tts, datasets, huggingface-hub,
# pandas, scikit-learn, xgboost, matplotlib, pydub, psutil, etc.
# These are NOT in pyproject.toml — they are installed via pip only.
# Packages already in pyproject.toml (faster-whisper, librosa, opencv,
# moviepy, Pillow, ultralytics, scenedetect, httpx, prometheus-client,
# google-api-python-client, deap, pymilvus, kaggle, redis) are excluded
# here because uv sync already installed them in Layer 1.
RUN .venv/bin/pip install --no-cache-dir --default-timeout=600 \
    "sentence-transformers" \
    "mediapipe>=0.10.18" \
    "pydub" "psutil" \
    "edge-tts>=6.1.9" \
    "datasets>=2.14.0" \
    "huggingface-hub>=0.17.0" \
    "pandas>=2.0.0" \
    "scikit-learn>=1.3.0" \
    "xgboost>=2.0.0" \
    "matplotlib" \
    "protobuf>=3.20.3,<4"

# ── Layer 3: whisperx y sus deps (cambian poco) ───────────────────────
# whisperx → pyannote-audio>=4.0.0 → torchmetrics, speechbrain, etc.
# Installing these separately with bounded versions prevents pip's resolver
# from hitting the maximum depth limit.
RUN .venv/bin/pip install --no-cache-dir --default-timeout=600 \
    "pyannote.audio>=3.1.0" \
    "pyannote.core>=5.0.0" \
    "pyannote.pipeline>=3.0.1" \
    "speechbrain>=1.0.0" \
    "torchmetrics>=1.0.0"

# whisperx and TTS with --no-deps (deps already satisfied above)
# TTS: gruut requiere numpy<2.0, incompatible con numpy==2.2.6
RUN .venv/bin/pip install --no-cache-dir --no-deps "whisperx" \
    && .venv/bin/pip install --no-cache-dir --no-deps "TTS>=0.22.0"

# ── Stage 2: Runtime (minimal) ────────────────────────────────────────
FROM nvidia/cuda:13.2.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV CUDA_MODULE_LOADING=LAZY
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512,garbage_collection_threshold:0.6
ENV NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

# Only essential runtime system deps
# ffmpeg is installed from the NVIDIA CUDA repo (already configured in the
# base image nvidia/cuda:13.2.0-runtime-ubuntu22.04). This provides h264_nvenc
# and hevc_nvenc compiled against the same CUDA headers as the host.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv \
    curl xz-utils \
    libsndfile1 \
    libgl1 libglib2.0-0 \
    libsm6 libxext6 libxrender-dev \
    libavutil-dev libavcodec-dev libavformat-dev \
    ffmpeg \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/* \
    && which ffprobe || (echo "FATAL: ffprobe not found — frozen frame bug will recur" && exit 1)

WORKDIR /app

# Copy .venv from builder (preserves all installed packages)
COPY --from=builder /app/.venv ./.venv

# ── Override distro ffmpeg with source-compiled NVENC build ────────────
# The distro ffmpeg (4.4.2 on ubuntu22.04) is compiled against old CUDA
# headers and fails with "cuInit(0) failed -> CUDA_ERROR_UNKNOWN" on
# driver 595+. We replace it with the FFmpeg 7.1 compiled from source in
# the builder stage against CUDA 13.2 headers with dynamic linking.
# This ensures the binary loads libcuda.so from the NVIDIA container
# toolkit at runtime, making it compatible with any host driver version.
COPY --from=builder /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=builder /usr/local/bin/ffprobe /usr/local/bin/ffprobe
# Copy shared libraries needed by the compiled ffmpeg
# These include libavcodec, libavformat, libavutil, libswresample, etc.
# compiled against CUDA 13.2. The runtime stage already has CUDA 13.2
# runtime libraries from the nvidia/cuda:13.2.0-runtime base image.
COPY --from=builder /usr/local/lib/libavcodec.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libavdevice.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libavfilter.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libavformat.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libavutil.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libpostproc.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libswresample.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libswscale.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libx264.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libx265.so* /usr/local/lib/
# libfdk-aac is installed via apt (libfdk-aac-dev), so it lives in /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libfdk-aac.so* /usr/local/lib/
# Ensure torchcodec can find libavutil.so.60 (FFmpeg 7.1 from builder)
# The system ffmpeg (4.4.2) provides libavutil.so.56 which torchcodec rejects.
# The builder's FFmpeg 7.1 provides libavutil.so.60 in /usr/local/lib/.
RUN ldconfig && ldconfig -p | grep libavutil || true
# Log which ffmpeg we got and verify NVENC
RUN echo "=== FFmpeg version ===" && \
    /usr/local/bin/ffmpeg -version 2>&1 | head -3 && \
    echo "=== NVENC encoders ===" && \
    /usr/local/bin/ffmpeg -hide_banner -encoders 2>&1 | grep -i nvenc || echo "(no NVENC encoders found)" && \
    echo "=== Dynamic linking ===" && \
    ldd /usr/local/bin/ffmpeg | grep -E "(cuda|nvcuvid)" || echo "(no CUDA shared libs linked)"



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
    /app/storage/ingested /app/data /app/data/creator_profiles /app/luts \
    /shared_temp /var/log/worker

# Create temp/output dirs in /tmp so workers always have write access
RUN mkdir -p /tmp/viraclip/temp /tmp/viraclip/outputs /tmp/viraclip/clips /tmp/viraclip/downloads \
    && chmod -R 777 /tmp/viraclip

# Generate SFX assets at build time (fast, pure Python + ffmpeg)
RUN .venv/bin/python /app/scripts/generate_sfx_assets.py || echo "SFX generation skipped"

# Bootstrap LUT files
RUN .venv/bin/python /app/scripts/bootstrap_luts.py || echo "LUT bootstrap skipped"

# Install fontconfig for system font registration
RUN apt-get update && apt-get install -y --no-install-recommends \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Download subtitle fonts (Google Fonts CDN — stable URLs)
# Each font is downloaded to /app/fonts/ AND symlinked into the system font
# directory so libass (used by FFmpeg subtitles filter) can find them by name.
RUN mkdir -p /app/fonts /usr/local/share/fonts/viraclip && \
    curl -fsSL \
    "https://fonts.gstatic.com/s/montserrat/v30/JTUSjIg1_i6t8kCHKm459WlhyyTh89Y.ttf" \
    -o /app/fonts/Montserrat-Regular.ttf && \
    ln -sf /app/fonts/Montserrat-Regular.ttf /usr/local/share/fonts/viraclip/Montserrat-Regular.ttf && \
    curl -fsSL \
    "https://fonts.gstatic.com/s/montserrat/v30/JTUSjIg1_i6t8kCHKm459WlhyyTh89Y.ttf" \
    -o /app/fonts/Montserrat-Bold.ttf && \
    ln -sf /app/fonts/Montserrat-Bold.ttf /usr/local/share/fonts/viraclip/Montserrat-Bold.ttf && \
    curl -fsSL \
    "https://fonts.gstatic.com/s/bebasneue/v15/JTUSjIg1_i6t8kCHKm459WlhyyTh89Y.ttf" \
    -o /app/fonts/BebasNeue-Regular.ttf && \
    ln -sf /app/fonts/BebasNeue-Regular.ttf /usr/local/share/fonts/viraclip/BebasNeue-Regular.ttf && \
    curl -fsSL \
    "https://fonts.gstatic.com/s/inter/v19/UcC73FwrK3iLTeHuS_fctQtRMpLv3Y1k.ttf" \
    -o /app/fonts/Inter-Regular.ttf && \
    ln -sf /app/fonts/Inter-Regular.ttf /usr/local/share/fonts/viraclip/Inter-Regular.ttf && \
    curl -fsSL \
    "https://fonts.gstatic.com/s/poppins/v21/pxiByp8kv8JHgFVrLCz7Z1xlFd2JQEk.ttf" \
    -o /app/fonts/Poppins-Bold.ttf && \
    ln -sf /app/fonts/Poppins-Bold.ttf /usr/local/share/fonts/viraclip/Poppins-Bold.ttf && \
    fc-cache -fv \
    || echo "Font download skipped — Arial fallback"

# Download CC0 background music tracks (YouTube Audio Library / Free Music Archive)
# These are the 5 most-used tracks from the 31-track library
RUN curl -fsSL "https://raw.githubusercontent.com/sebsv123/viraclip-assets/main/music/Sly%20Sky%20-%20Telecasted.mp3" \
    -o /app/assets/sounds/bgm/Sly\ Sky\ -\ Telecasted.mp3 \
    && curl -fsSL "https://raw.githubusercontent.com/sebsv123/viraclip-assets/main/music/No.2%20Remembering%20Her%20-%20Esther%20Abrami.mp3" \
    -o /app/assets/sounds/bgm/No.2\ Remembering\ Her\ -\ Esther\ Abrami.mp3 \
    && curl -fsSL "https://raw.githubusercontent.com/sebsv123/viraclip-assets/main/music/Champion%20-%20Telecasted.mp3" \
    -o /app/assets/sounds/bgm/Champion\ -\ Telecasted.mp3 \
    && curl -fsSL "https://raw.githubusercontent.com/sebsv123/viraclip-assets/main/music/Oh%20Please%20-%20Telecasted.mp3" \
    -o /app/assets/sounds/bgm/Oh\ Please\ -\ Telecasted.mp3 \
    && curl -fsSL "https://raw.githubusercontent.com/sebsv123/viraclip-assets/main/music/Jetski%20-%20Telecasted.mp3" \
    -o /app/assets/sounds/bgm/Jetski\ -\ Telecasted.mp3 \
    && echo "✓ CC0 background music tracks downloaded" \
    || echo "⚠ Music download skipped — will use runtime fallback"

# Health check — runs healthcheck.sh which verifies NVENC, ffmpeg version, torchcodec
# Uses -S flag to bypass OpenTelemetry auto-instrumentation (avoids grpcio/mediapipe issues)
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
  CMD /app/scripts/healthcheck.sh || exit 1

EXPOSE 8000

CMD [".venv/bin/uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "30"]
