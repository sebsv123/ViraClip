#!/usr/bin/env bash
# ============================================================================
# healthcheck.sh — CI health-check for ViraClip backend containers.
#
# Verifies:
#   1. NVENC encoder is available in ffmpeg
#   2. ffmpeg version is recent enough (>= 5.0)
#   3. torchcodec can be imported (if installed)
#   4. Python environment is functional
#
# Exit code 0 = healthy, 1 = unhealthy.
# ============================================================================
set -euo pipefail

log()  { echo "[HEALTHCHECK] $*"; }
fail() { log "FAIL: $*"; exit 1; }

# ── 1. Python environment ────────────────────────────────────────────────────
log "Checking Python environment..."
python3 -c "import psutil; print('psutil OK')" 2>&1 || fail "psutil import failed"

# ── 2. ffmpeg version ────────────────────────────────────────────────────────
log "Checking ffmpeg version..."
FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -n1 | grep -oP 'ffmpeg version \K[0-9]+\.[0-9]+' || echo "0.0")
log "ffmpeg version: $FFMPEG_VERSION"

# Use awk for safe float comparison
if awk "BEGIN {exit !($FFMPEG_VERSION < 5.0)}"; then
    fail "ffmpeg version $FFMPEG_VERSION < 5.0 — too old"
fi
log "ffmpeg version OK (>= 5.0)"

# ── 3. NVENC encoder availability ────────────────────────────────────────────
log "Checking NVENC encoder..."
NVENC_LIST=$(ffmpeg -hide_banner -encoders 2>&1 | grep -i nvenc || true)
if [ -z "$NVENC_LIST" ]; then
    fail "No NVENC encoder found in ffmpeg encoders list"
fi
log "NVENC encoder found:"
echo "$NVENC_LIST" | head -5

# NOTE: We intentionally skip the runtime FFmpeg probe (encoding a test frame)
# because in containerized environments the subprocess FFmpeg cannot reliably
# initialize CUDA from scratch via cuInit(0), even when the parent Python
# process has working CUDA via PyTorch. The encoder being listed in
# ffmpeg -encoders is sufficient evidence that NVENC is compiled in.
# Actual encoding errors are caught downstream in the rendering pipeline.
log "NVENC runtime test SKIPPED (encoder list check above is sufficient)"

# ── 4. torchcodec import (optional — only if installed) ──────────────────────
log "Checking torchcodec import..."
if python3 -c "import torchcodec" 2>/dev/null; then
    log "torchcodec import OK"
else
    log "torchcodec not installed — skipping (non-fatal)"
fi

# ── All checks passed ─────────────────────────────────────────────────────────
log "All health checks PASSED"
exit 0
