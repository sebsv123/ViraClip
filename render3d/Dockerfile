# === render3d: Blender-based 3D asset renderer for ViraClip ===
# Uses linuxserver/blender:latest which includes Blender + CUDA support.
# A lightweight Flask server accepts GLB files and renders them with
# Cycles GPU, returning the rendered PNG.

FROM linuxserver/blender:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV BLENDER_PATH=/usr/local/blender/blender
ENV PYTHONUNBUFFERED=1

# Install Python dependencies for the Flask server
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment and install Flask + requests
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --no-cache-dir flask requests gunicorn

WORKDIR /app

# Copy server code
COPY server.py /app/server.py
COPY render_asset.py /app/render_asset.py

# Create output directory
RUN mkdir -p /app/outputs /app/uploads

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "300", "server:app"]
