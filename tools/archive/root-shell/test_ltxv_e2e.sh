#!/bin/bash
# Test End-to-End de LTXV en ComfyUI
# Uso: bash test_ltxv_e2e.sh

cd ~/CascadeProjects/ViraClip

echo "🚀 Enviando workflow LTXV t2v a ComfyUI..."

PROMPT_RESPONSE=$(python3 << 'PYEOF'
import json, urllib.request, sys

# Cargar workflow
with open("backend/comfy_workflows/ltxv_t2v_broll.json") as f:
    workflow = json.load(f)

# Reemplazar placeholders
wf_str = json.dumps(workflow)
wf_str = wf_str.replace("__POSITIVE_PROMPT__", "futuristic city neon lights vertical")
wf_str = wf_str.replace("__THEME__", "tech")
workflow = json.loads(wf_str)

payload = json.dumps({"prompt": workflow}).encode()
req = urllib.request.Request(
    "http://localhost:8188/prompt",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST"
)

try:
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    print(json.dumps(data))
except urllib.error.HTTPError as e:
    error_body = e.read().decode()
    print(f'{{"error": "HTTP {e.code}", "details": "{error_body}"}}', file=sys.stderr)
    sys.exit(1)
PYEOF
)

if [ $? -ne 0 ]; then
    echo "❌ Error al enviar workflow"
    exit 1
fi

PROMPT_ID=$(echo "$PROMPT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('prompt_id',''))")
QUEUE_NUM=$(echo "$PROMPT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('number',''))")

echo "✅ Prompt enviado"
echo "   Prompt ID: $PROMPT_ID"
echo "   Posición en cola: $QUEUE_NUM"
echo ""
echo "⏳ Esperando 60 segundos para que se procese..."
sleep 60

echo ""
echo "📊 Verificando estado del job..."

python3 << PYEOF
import json, urllib.request, sys

prompt_id = "$PROMPT_ID"
url = f"http://localhost:8188/history/{prompt_id}"

try:
    resp = urllib.request.urlopen(url)
    history = json.loads(resp.read())
    
    if not history:
        print("⚠️  No hay historial para este prompt_id (aún procesando o no existe)")
        sys.exit(0)
    
    for job_id, job_data in history.items():
        status = job_data.get('status', {})
        outputs = job_data.get('outputs', {})
        
        print(f"Job ID: {job_id}")
        print(f"Status: {status}")
        print(f"Outputs: {outputs}")
        
        # Verificar si hay archivos de video
        for node_id, node_outputs in outputs.items():
            if isinstance(node_outputs, dict):
                for key, value in node_outputs.items():
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, str) and ('.mp4' in item or '.webm' in item):
                                print(f"🎬 Video generado: {item}")
        
except urllib.error.HTTPError as e:
    print(f"❌ Error al consultar historial: HTTP {e.code}")
except Exception as e:
    print(f"❌ Error: {e}")
PYEOF

echo ""
echo "📋 Verificando cola actual..."
curl -s http://localhost:8188/queue | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('Jobs en cola:', len(data.get('queue_running', [])) + len(data.get('queue_pending', [])))
print('Ejecutando:', data.get('queue_running', []))
print('Pendientes:', data.get('queue_pending', []))
"

echo ""
echo "✅ Test completado"
