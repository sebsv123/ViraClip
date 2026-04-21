#!/bin/bash
# check_health.sh — ViraClip System Health Check
# Verifies GPU, NVENC, and service availability

set -e

echo "=== ViraClip Health Check ==="

# GPU Check
if command -v nvidia-smi &> /dev/null; then
    echo "[GPU] Checking NVIDIA GPU..."
    GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    if [ -n "$GPU_UTIL" ]; then
        echo "[GPU] ✓ $GPU_NAME - Utilization: ${GPU_UTIL}%"
    else
        echo "[GPU] ✗ GPU not responding"
        exit 1
    fi
else
    echo "[GPU] ⚠ nvidia-smi not found"
fi

# NVENC Check
echo "[NVENC] Checking FFmpeg NVENC support..."
if command -v ffmpeg &> /dev/null; then
    if ffmpeg -encoders 2>&1 | grep -q "h264_nvenc"; then
        echo "[NVENC] ✓ h264_nvenc encoder available"
    else
        echo "[NVENC] ✗ h264_nvenc not found in FFmpeg"
        exit 1
    fi
else
    echo "[NVENC] ✗ FFmpeg not found"
    exit 1
fi

# Docker Check
echo "[Docker] Checking Docker daemon..."
if docker info &> /dev/null; then
    echo "[Docker] ✓ Docker daemon running"
else
    echo "[Docker] ✗ Docker daemon not accessible"
    exit 1
fi

echo "=== All Checks Passed ==="
