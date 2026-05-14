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
python3 -S -c "import psutil; print('psutil OK')" 2>&1 || fail "psutil import failed"

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

# Quick runtime test with h264_nvenc
log "Running NVENC runtime test..."
TEST_OUT=$(mktemp /tmp/nvenc_test_XXXXXX.mp4)
trap 'rm -f "$TEST_OUT"' EXIT

if ! ffmpeg -y -loglevel error -f lavfi -i "color=black:s=256x256:r=1" -t 1 \
    -c:v h264_nvenc -pix_fmt yuv420p "$TEST_OUT" 2>&1; then
    # Fallback to hevc_nvenc
    log "h264_nvenc failed, trying hevc_nvenc..."
    if ! ffmpeg -y -loglevel error -f lavfi -i "color=black:s=256x256:r=1" -t 1 \
        -c:v hevc_nvenc -pix_fmt yuv420p "$TEST_OUT" 2>&1; then
        fail "NVENC runtime test FAILED for both h264_nvenc and hevc_nvenc"
    fi
fi
log "NVENC runtime test PASSED"

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
