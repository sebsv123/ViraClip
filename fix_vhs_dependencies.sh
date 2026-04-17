#!/bin/bash
# Script para arreglar dependencias de VideoHelperSuite

LOG="/tmp/vhs_fix_log.txt"
> "$LOG"

echo "=== ARREGLO DE DEPENDENCIAS VHS ===" | tee -a "$LOG"
echo "Timestamp: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "PASO 1: Verificar requirements.txt del nodo VHS" | tee -a "$LOG"
echo "------------------------------------------------" | tee -a "$LOG"
docker exec viraclip-comfyui cat /comfyui/custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt 2>&1 | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "PASO 2: Instalar dependencias principales" | tee -a "$LOG"
echo "------------------------------------------------" | tee -a "$LOG"
docker exec viraclip-comfyui pip install --no-cache-dir \
  av imageio imageio-ffmpeg opencv-python-headless \
  numpy pillow tqdm einops 2>&1 | tail -20 | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "PASO 3: Instalar desde requirements.txt del nodo" | tee -a "$LOG"
echo "------------------------------------------------" | tee -a "$LOG"
docker exec viraclip-comfyui pip install --no-cache-dir \
  -r /comfyui/custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt 2>&1 | tail -20 | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "PASO 4: Reiniciando ComfyUI..." | tee -a "$LOG"
echo "------------------------------------------------" | tee -a "$LOG"
docker restart viraclip-comfyui 2>&1 | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "PASO 5: Esperando 45 segundos para que ComfyUI arranque..." | tee -a "$LOG"
for i in {45..1}; do
  echo -ne "\rEsperando: $i segundos restantes...   "
  sleep 1
done
echo "" | tee -a "$LOG"

echo "PASO 6: Verificando nodo VHS_LoadVideo..." | tee -a "$LOG"
echo "------------------------------------------------" | tee -a "$LOG"
curl -s http://localhost:8188/object_info/VHS_LoadVideo 2>&1 | python3 -m json.tool | head -20 | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "PASO 7: Verificando system_stats (healthcheck)..." | tee -a "$LOG"
echo "------------------------------------------------" | tee -a "$LOG"
curl -s http://localhost:8188/system_stats 2>&1 | python3 -m json.tool | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "=== FIN DEL PROCESO ===" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "Log completo guardado en: $LOG"
echo ""
echo "RESUMEN:"
if curl -s http://localhost:8188/object_info/VHS_LoadVideo 2>&1 | grep -q '"input"'; then
    echo "✅ VHS_LoadVideo FUNCIONA - Nodo detectado correctamente"
else
    echo "❌ VHS_LoadVideo FALLÓ - Ver log para detalles"
fi

if curl -s http://localhost:8188/system_stats 2>&1 | grep -q 'devices'; then
    echo "✅ Healthcheck endpoint responde"
else
    echo "❌ Healthcheck endpoint no responde"
fi

cat "$LOG"
