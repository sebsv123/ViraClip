#!/usr/bin/env fish
# ViraClip Development Environment Configuration for Fish Shell
# Updated: 2026-04-23

# Background Composite (SAM2 + LTX-Video)
set -x BACKGROUND_COMPOSITE_ENABLED true
set -x SAM2_ENABLED true
set -x SAM2_MODEL sam2_hiera_small.pt
set -x SAM2_MIN_VIRAL_SCORE 7.5
set -x SAM2_MIN_DURATION 12.0

# ComfyUI Configuration
set -x COMFYUI_ENABLED true
set -x COMFYUI_HOST http://localhost:8188
set -x COMFYUI_URL http://localhost:8188
set -x COMFYUI_PORT 8188
set -x COMFYUI_WORKFLOW_SAM2 $HOME/ComfyUI/workflows/sam2_ltxvideo.json
set -x COMFYUI_TIMEOUT 600
set -x COMFYUI_INPUT_DIR /comfyui/input
set -x COMFYUI_OUTPUT_DIR /comfyui/output

# LTX-Video Model
set -x COMFYUI_LTX_MODEL ltxv-2b-0.9.8-distilled-fp8.safetensors
set -x BROLL_USE_LTX true

# Database
set -x POSTGRES_DB viraclip
set -x POSTGRES_USER viraclip
set -x POSTGRES_PASSWORD viraclip_password

# Redis
set -x REDIS_PASSWORD ""

# Feature Flags
set -x VOICE_ENHANCEMENT_ENABLED true
set -x SUBTITLE_REALIGN_ENABLED true
set -x MUSIC_DUCKING_ENABLED true
set -x BROLL_ENABLED true

# Paths
set -x VIRA_UPLOADS ./uploads
set -x VIRA_OUTPUTS ./outputs

echo "✅ ViraClip dev environment loaded (Fish Shell)"
echo "   BACKGROUND_COMPOSITE_ENABLED: $BACKGROUND_COMPOSITE_ENABLED"
echo "   COMFYUI_HOST: $COMFYUI_HOST"
echo "   SAM2_MODEL: $SAM2_MODEL"
