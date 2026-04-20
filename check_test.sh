#!/bin/bash
echo "=== Task progress ==="
docker logs --tail 200 viraclip-worker 2>&1 | grep -E "7cb24297|Step|B-roll slot|BRoll|enhance_pexels|ltxv|broll_source|Creative|progress|error|Error" | tail -40

echo ""
echo "=== ComfyUI entrypoint (VideoUpscale + RealESRGAN) ==="
docker logs viraclip-comfyui 2>&1 | grep -iE "ViraClip|Cloning|Download|RealESRGAN|VideoUpscale|error" | head -20

echo ""
echo "=== ComfyUI loaded nodes check ==="
curl -s http://localhost:8188/object_info 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
nodes = ['VHS_LoadVideo','VHS_VideoCombine','ImageUpscaleWithModel','UpscaleModelLoader','ImageScale']
for n in nodes:
    status = 'OK' if n in data else 'MISSING'
    print(f'  {n}: {status}')
" 2>&1
