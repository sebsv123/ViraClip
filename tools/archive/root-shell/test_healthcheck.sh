#!/bin/bash
# Test del healthcheck de ComfyUI

echo "=== TEST HEALTHCHECK COMFYUI ==="
echo ""

echo "1. Test desde FUERA del contenedor:"
curl -sf http://localhost:8188/system_stats
echo ""
echo "Exit code: $?"
echo ""

echo "2. Test desde DENTRO del contenedor (como healthcheck):"
docker exec viraclip-comfyui curl -sf http://localhost:8188/system_stats
echo ""
echo "Exit code: $?"
echo ""

echo "3. Test alternativo /object_info:"
docker exec viraclip-comfyui curl -sf http://localhost:8188/object_info | head -100
echo ""
echo "Exit code: $?"
echo ""

echo "4. Simular healthcheck exacto:"
docker exec viraclip-comfyui sh -c 'curl -sf http://localhost:8188/system_stats || exit 1'
echo "Exit code: $?"
