# === ViraClip Backend: NVIDIA CUDA + Python 3.11 ===
# CUDA 12.4 runtime with cuDNN — compatible with driver 595.97 (CUDA 13.2)
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# Prevent interactive prompts during apt
ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3.11 + system dependencies
# libsndfile1      — required by librosa for audio file I/O
# libgl1           — required by opencv-python-headless and mediapipe (libGL.so.1)
# libglib2.0-0     — required by mediapipe at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    ffmpeg curl unzip \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && rm -rf /var/lib/apt/lists/*

# Install deno (required by yt-dlp for YouTube JS challenge solving)
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_DIR=/root/.deno
ENV PATH="/root/.deno/bin:${PATH}"

# Install uv package manager
RUN pip install uv

# Set working directory
WORKDIR /app

# Copy pyproject.toml and uv.lock for dependency installation
COPY pyproject.toml uv.lock* ./

# Create virtual environment and install dependencies using uv sync
RUN uv venv .venv && uv sync

# Force update yt-dlp to the absolute latest version to handle YouTube API changes
# [default] extra pulls in mutagen, pycryptodomex, and websockets for full feature support
RUN uv pip install --no-cache --upgrade "yt-dlp[default]"

# === AI MODELS + CUDA-enabled PyTorch ===
# Install faster-whisper (uses CTranslate2 with CUDA support)
# Install transformers, sentencepiece, and librosa for translation and analysis
# Install PyTorch with CUDA 12.4 support
RUN uv pip install --no-cache faster-whisper transformers sentencepiece librosa \
    && uv pip install --no-cache torch torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu124

# === Scene detection + HTTP client for local vision pipeline ===
# scenedetect: shot boundary detection → rhythm scoring (PySceneDetect)
# httpx: async HTTP client for Ollama API calls (local vision model)
RUN uv pip install --no-cache "scenedetect[opencv]>=0.6.5" "httpx>=0.27.0"

# Copy source code
COPY src/ ./src/

# Copy fonts and transitions directories
COPY fonts/ ./fonts/
COPY transitions/ ./transitions/

# Create necessary directories for video processing
RUN mkdir -p /app/uploads /app/clips /app/logs /app/models /tmp

# Expose the port FastAPI will run on
EXPOSE 8000

# Activate virtual environment and start the application
CMD [".venv/bin/uvicorn", "src.main_refactored:app", "--host", "0.0.0.0", "--port", "8000"]