#!/bin/bash
# ViraClip ComfyUI Model Downloader
# Run inside the comfyui container: docker exec -it viraclip-comfyui bash /home/user/comfyui/user/default/workflows/download_models.sh

MODELS_DIR="/home/user/comfyui/models"
CHECKPOINTS_DIR="$MODELS_DIR/checkpoints"
UPSCALE_DIR="$MODELS_DIR/upscale_models"
ANIMATEDIFF_DIR="$MODELS_DIR/animatediff_models"

mkdir -p "$CHECKPOINTS_DIR" "$UPSCALE_DIR" "$ANIMATEDIFF_DIR"

echo "=== ViraClip ComfyUI Model Download ==="

# SD 1.5 base (for AnimateDiff)
if [ ! -f "$CHECKPOINTS_DIR/v1-5-pruned-emaonly.ckpt" ]; then
  echo "[1/3] Downloading SD 1.5..."
  wget -q --show-progress -O "$CHECKPOINTS_DIR/v1-5-pruned-emaonly.ckpt" \
    "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.ckpt"
else
  echo "[1/3] SD 1.5 already present"
fi

# RealESRGAN x2plus (upscaling)
if [ ! -f "$UPSCALE_DIR/RealESRGAN_x2plus.pth" ]; then
  echo "[2/3] Downloading RealESRGAN_x2plus..."
  wget -q --show-progress -O "$UPSCALE_DIR/RealESRGAN_x2plus.pth" \
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
else
  echo "[2/3] RealESRGAN_x2plus already present"
fi

# AnimateDiff motion module v2
if [ ! -f "$ANIMATEDIFF_DIR/mm_sd_v15_v2.ckpt" ]; then
  echo "[3/3] Downloading AnimateDiff motion module v2..."
  wget -q --show-progress -O "$ANIMATEDIFF_DIR/mm_sd_v15_v2.ckpt" \
    "https://huggingface.co/guoyww/animatediff/resolve/main/mm_sd_v15_v2.ckpt"
else
  echo "[3/3] AnimateDiff mm_sd_v15_v2 already present"
fi

echo ""
echo "=== Download complete ==="
echo "Models in: $MODELS_DIR"
ls -lh "$CHECKPOINTS_DIR" "$UPSCALE_DIR" "$ANIMATEDIFF_DIR"
