"""
render3d — Flask server for Blender-based 3D asset rendering.

Accepts a GLB/GLTF file URL via POST /render, downloads it, invokes Blender
headless with render_asset.py, and returns the rendered PNG path.

Usage:
    curl -X POST http://localhost:5000/render \\
        -H "Content-Type: application/json" \\
        -d '{"glb_url": "https://example.com/model.glb", "output_format": "png"}'

Returns:
    {
        "status": "ok",
        "output_path": "/app/outputs/abc123.png",
        "render_time_seconds": 12.5
    }
"""

import os
import uuid
import time
import logging
import subprocess
import tempfile
from pathlib import Path

import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("render3d")

app = Flask(__name__)

UPLOAD_DIR = Path("/app/uploads")
OUTPUT_DIR = Path("/app/outputs")
BLENDER_PATH = os.environ.get("BLENDER_PATH", "/usr/local/blender/blender")
RENDER_SCRIPT = Path("/app/render_asset.py")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint with Blender availability and GPU detection."""
    blender_available = False
    blender_version = None
    gpu_available = False
    gpu_info = None

    # Check Blender availability
    try:
        result = subprocess.run(
            [BLENDER_PATH, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            blender_available = True
            blender_version = result.stdout.strip().split("\n")[0] if result.stdout.strip() else "unknown"
    except Exception as e:
        logger.warning("Blender check failed: %s", e)

    # Check GPU availability via Blender's cycles device info
    if blender_available:
        try:
            gpu_check_cmd = [
                str(BLENDER_PATH),
                "--background",
                "--python-expr",
                "import bpy; "
                "prefs = bpy.context.preferences.addons['cycles'].preferences; "
                "prefs.get_devices(); "
                "devices = [d for d in prefs.devices if d.type == 'CUDA' and d.use]; "
                "print(f'GPU_COUNT:{len(devices)}'); "
                "for d in devices: print(f'GPU:{d.name}')",
            ]
            gpu_result = subprocess.run(
                gpu_check_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if gpu_result.returncode == 0:
                gpu_lines = [l for l in gpu_result.stdout.strip().split("\n") if l.startswith("GPU:")]
                gpu_count_line = [l for l in gpu_result.stdout.strip().split("\n") if l.startswith("GPU_COUNT:")]
                if gpu_count_line:
                    count = int(gpu_count_line[0].split(":")[1])
                    gpu_available = count > 0
                    gpu_info = {
                        "count": count,
                        "devices": [l.split(":", 1)[1].strip() for l in gpu_lines],
                    }
        except Exception as e:
            logger.warning("GPU detection failed: %s", e)

    return jsonify({
        "status": "ok",
        "service": "render3d",
        "blender_available": blender_available,
        "blender_version": blender_version,
        "gpu_available": gpu_available,
        "gpu_info": gpu_info,
    })


@app.route("/render", methods=["POST"])
def render():
    """
    Render a 3D asset from a GLB/GLTF URL.

    Request JSON:
        - glb_url (str, required): URL to the .glb or .gltf file
        - output_format (str, optional): "png" (default) or "jpg"
        - resolution_x (int, optional): Output width (default: 1920)
        - resolution_y (int, optional): Output height (default: 1080)
        - samples (int, optional): Cycles render samples (default: 128)
        - hdri_url (str, optional): URL to an HDRI environment map

    Returns:
        JSON with status, output_path, and render_time_seconds.
    """
    data = request.get_json(silent=True)
    if not data or "glb_url" not in data:
        return jsonify({"status": "error", "message": "Missing 'glb_url' in request body"}), 400

    glb_url = data["glb_url"]
    output_format = data.get("output_format", "png")
    resolution_x = data.get("resolution_x", 1920)
    resolution_y = data.get("resolution_y", 1080)
    samples = data.get("samples", 128)
    hdri_url = data.get("hdri_url")

    # Generate unique job ID
    job_id = uuid.uuid4().hex[:12]
    glb_path = UPLOAD_DIR / f"{job_id}.glb"
    output_path = OUTPUT_DIR / f"{job_id}.{output_format}"

    # Download the GLB file
    logger.info(f"[{job_id}] Downloading GLB from {glb_url}")
    try:
        resp = requests.get(glb_url, timeout=120, stream=True)
        resp.raise_for_status()
        with open(glb_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"[{job_id}] Downloaded {glb_path.stat().st_size} bytes")
    except Exception as e:
        logger.error(f"[{job_id}] Download failed: {e}")
        return jsonify({"status": "error", "message": f"Download failed: {str(e)}"}), 502

    # Download HDRI if provided
    hdri_path = None
    if hdri_url:
        hdri_path = UPLOAD_DIR / f"{job_id}_hdri.hdr"
        try:
            resp = requests.get(hdri_url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(hdri_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"[{job_id}] Downloaded HDRI {hdri_path.stat().st_size} bytes")
        except Exception as e:
            logger.warning(f"[{job_id}] HDRI download failed, continuing without: {e}")
            hdri_path = None

    # Render with Blender
    logger.info(f"[{job_id}] Starting Blender render (samples={samples}, res={resolution_x}x{resolution_y})")
    start_time = time.time()

    cmd = [
        str(BLENDER_PATH),
        "--background",
        "--python", str(RENDER_SCRIPT),
        "--",
        "--glb_path", str(glb_path),
        "--output_path", str(output_path),
        "--samples", str(samples),
        "--resolution_x", str(resolution_x),
        "--resolution_y", str(resolution_y),
    ]
    if hdri_path:
        cmd.extend(["--hdri_path", str(hdri_path)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max per render
        )
        elapsed = time.time() - start_time
        logger.info(f"[{job_id}] Blender completed in {elapsed:.1f}s")

        if result.returncode != 0:
            logger.error(f"[{job_id}] Blender stderr: {result.stderr[:2000]}")
            return jsonify({
                "status": "error",
                "message": "Blender render failed",
                "stderr": result.stderr[:2000],
                "stdout": result.stdout[:2000],
            }), 500

        if not output_path.exists():
            logger.error(f"[{job_id}] Output file not found at {output_path}")
            return jsonify({
                "status": "error",
                "message": "Output file was not created by Blender",
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
            }), 500

        logger.info(f"[{job_id}] Render successful: {output_path}")
        return jsonify({
            "status": "ok",
            "output_path": str(output_path),
            "render_time_seconds": round(elapsed, 2),
        })

    except subprocess.TimeoutExpired:
        logger.error(f"[{job_id}] Blender render timed out after 600s")
        return jsonify({"status": "error", "message": "Render timed out"}), 504
    except Exception as e:
        logger.error(f"[{job_id}] Render error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
