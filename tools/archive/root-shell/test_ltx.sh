#!/usr/bin/env bash
# Test aislado de LTX Text-to-Video contra ComfyUI local.
# Uso:
#   bash test_ltx.sh
# Salida esperada:
#   [OK] prompt_id: xxxx
#   [...] esperando...
#   [OK] Ejecutado correctamente, archivo: /home/.../outputs/test_ltx_basic_00001.mp4
# Si falla:
#   [ERROR] ... -> pega ese error al asistente.

set -u
COMFY_URL="${COMFY_URL:-http://localhost:8188}"
WF_JSON="$(dirname "$0")/test_ltx_workflow.json"

if [[ ! -f "$WF_JSON" ]]; then
    echo "[ERROR] No existe $WF_JSON"
    exit 1
fi

echo "[*] Enviando workflow a $COMFY_URL ..."
PAYLOAD=$(python3 -c "
import json, sys
with open('$WF_JSON') as f:
    wf = json.load(f)
print(json.dumps({'prompt': wf}))
")

RESP=$(curl -s --max-time 10 -X POST -H "Content-Type: application/json" \
    -d "$PAYLOAD" "$COMFY_URL/prompt")

echo "[*] Respuesta inicial: $RESP"
PROMPT_ID=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('prompt_id',''))" 2>/dev/null)

if [[ -z "$PROMPT_ID" ]]; then
    echo "[ERROR] ComfyUI rechazó el workflow. Respuesta:"
    echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
    exit 2
fi

echo "[OK] prompt_id: $PROMPT_ID"
echo "[*] Esperando ejecución (máx 300s)..."

for i in $(seq 1 150); do
    sleep 2
    HIST=$(curl -s --max-time 5 "$COMFY_URL/history/$PROMPT_ID")
    if echo "$HIST" | grep -q "\"$PROMPT_ID\""; then
        STATUS=$(echo "$HIST" | python3 -c "
import sys,json
d = json.load(sys.stdin)
h = d.get('$PROMPT_ID', {})
status = h.get('status', {})
print(json.dumps(status))
" 2>/dev/null)
        echo "[*] status: $STATUS"
        COMPLETED=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('completed', False))" 2>/dev/null)
        if [[ "$COMPLETED" == "True" ]]; then
            OUTS=$(echo "$HIST" | python3 -c "
import sys,json
d = json.load(sys.stdin)
h = d.get('$PROMPT_ID', {})
print(json.dumps(h.get('outputs', {}), indent=2)[:2000])
" 2>/dev/null)
            echo "[OK] Completado."
            echo "[*] Outputs:"
            echo "$OUTS"
            exit 0
        fi
        # Si status indica error
        if echo "$STATUS" | grep -qi "error\|failed"; then
            echo "[ERROR] Workflow falló. Mensajes:"
            echo "$HIST" | python3 -c "
import sys,json
d = json.load(sys.stdin)
h = d.get('$PROMPT_ID', {})
msgs = h.get('status', {}).get('messages', [])
for m in msgs:
    print(' -', m)
" 2>/dev/null
            exit 3
        fi
    fi
    printf '.'
done

echo
echo "[ERROR] Timeout tras 300s sin completar."
echo "[*] Revisa los logs del contenedor ComfyUI:"
echo "    docker logs 923dd1d1f56d_viraclip-comfyui --tail 100 2>&1 | tail -40"
exit 4
