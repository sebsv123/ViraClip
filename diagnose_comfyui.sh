#!/bin/bash
# Diagnóstico exhaustivo de ComfyUI

OUTPUT_FILE="/tmp/viraclip_diagnosis.txt"
> "$OUTPUT_FILE"

echo "=== DIAGNÓSTICO VIRACLIP COMFYUI ===" | tee -a "$OUTPUT_FILE"
echo "Fecha: $(date)" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "1. DOCKER PS STATUS:" | tee -a "$OUTPUT_FILE"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "2. CUSTOM NODES DIRECTORY:" | tee -a "$OUTPUT_FILE"
docker exec viraclip-comfyui ls -la /comfyui/custom_nodes/ 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "3. VIDEOHELPER SUITE DIRECTORY:" | tee -a "$OUTPUT_FILE"
docker exec viraclip-comfyui ls -la /comfyui/custom_nodes/ComfyUI-VideoHelperSuite/ 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "4. PYTHON PACKAGES (video-related):" | tee -a "$OUTPUT_FILE"
docker exec viraclip-comfyui pip list 2>&1 | grep -iE "av|imageio|opencv|numpy|pillow" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "5. COMFYUI API - VHS_LoadVideo NODE:" | tee -a "$OUTPUT_FILE"
curl -s http://localhost:8188/object_info/VHS_LoadVideo 2>&1 | python3 -m json.tool | head -30 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "6. COMFYUI LOGS (últimas 50 líneas con errores):" | tee -a "$OUTPUT_FILE"
docker logs viraclip-comfyui --tail 50 2>&1 | grep -iE "error|warning|VHS|VideoHelper|failed|import" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "7. DOCKER COMPOSE STATUS:" | tee -a "$OUTPUT_FILE"
cd /home/_sebastian/CascadeProjects/ViraClip
docker-compose ps 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "8. COMFYUI HEALTHCHECK:" | tee -a "$OUTPUT_FILE"
docker inspect viraclip-comfyui --format='{{json .State.Health}}' 2>&1 | python3 -m json.tool | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "9. COMFYUI ÚLTIMAS 20 LÍNEAS DE LOG:" | tee -a "$OUTPUT_FILE"
docker logs viraclip-comfyui --tail 20 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "=== FIN DIAGNÓSTICO ===" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"
echo "Resultados guardados en: $OUTPUT_FILE"

cat "$OUTPUT_FILE"
