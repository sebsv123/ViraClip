#!/bin/bash
# ViraClip E2E Processing Script - Flujo original con worker
set -e

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip E2E Video Processing"
echo "=========================================="
echo "📹 URL: $VIDEO_URL"
echo ""

# 1. Iniciar infraestructura
echo "🚀 Paso 1: Iniciando infraestructura..."
cd /home/_sebastian/CascadeProjects/ViraClip
docker-compose up -d --build 2>&1 | tail -10
echo "   ✅ Docker services started"
echo ""

# 2. Descargar video
echo "⬇️  Paso 2: Descargando video..."
yt-dlp -f 'best[height<=1080]' -o "$WORKDIR/video.%(ext)s" "$VIDEO_URL" 2>&1 | tail -5
VIDEO_FILE=$(ls "$WORKDIR/video".* 2>/dev/null | head -1)
echo "   ✅ Descargado: $(basename $VIDEO_FILE)"
echo ""

# 3. Copiar al contenedor
echo "📦 Paso 3: Copiando a ViraClip..."
docker cp "$VIDEO_FILE" viraclip-backend-1:/app/uploads/input_video.mp4
docker exec viraclip-backend-1 ls -la /app/uploads/
echo "   ✅ Video en contenedor"
echo ""

# 4. Crear JSON de tarea
echo "📝 Paso 4: Creando tarea..."
cat > "$WORKDIR/task.json" <<'EOF'
{
  "source_type": "upload",
  "video_filename": "input_video.mp4",
  "platform": "tiktok",
  "options": {
    "max_clips": 5,
    "min_duration": 15,
    "max_duration": 60,
    "background_composite_enabled": true,
    "sam2_enabled": true,
    "generate_captions": true,
    "virality_threshold": 7.0
  }
}
EOF
echo "   📄 Task JSON:"
cat "$WORKDIR/task.json" | jq . 2>/dev/null || cat "$WORKDIR/task.json"
echo ""

# 5. Enviar tarea a la API
echo "🎯 Paso 5: Enviando tarea a la API..."
TASK_RESPONSE=$(curl -s -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d @"$WORKDIR/task.json" 2>/dev/null)

echo "   📤 Response: $TASK_RESPONSE"

TASK_ID=$(echo "$TASK_RESPONSE" | grep -o '"id":"[^"]*"' | cut -d'"' -f4 || \
          echo "$TASK_RESPONSE" | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4 || \
          echo "")

if [ -z "$TASK_ID" ]; then
    echo "   ⚠️  No se pudo extraer task_id, intentando procesamiento directo..."
    # Procesamiento directo sin API
    TASK_ID="manual-$(date +%s)"
fi

echo "   ✅ Task ID: $TASK_ID"
echo ""

# 6. Iniciar worker en foreground para ver logs en tiempo real
echo "⚙️  Paso 6: Iniciando worker..."
echo "   📝 Los logs aparecerán a continuación:"
echo "   ⏱️  Procesando (esto puede tomar 10-30 minutos)..."
echo ""
echo "=========================================="
echo "WORKER LOGS - Presiona Ctrl+C para detener"
echo "=========================================="

# Ejecutar worker y mostrar logs
cd /home/_sebastian/CascadeProjects/ViraClip/backend
source .venv/bin/activate 2>/dev/null || true

# Si hay task_id de API, usarlo. Si no, procesar directamente
if [ "$TASK_ID" != "manual-$(date +%s)" ]; then
    # Modo API - el worker procesará de la cola
    arq src.workers.tasks.WorkerSettings --watch 2>&1 | tee "$WORKDIR/worker.log" &
    WORKER_PID=$!
    
    # Monitorear progreso
    for i in {1..180}; do  # 30 min max
        sleep 10
        STATUS=$(curl -s http://localhost:8000/api/tasks/$TASK_ID 2>/dev/null | grep -o '"status":"[^"]*"' | cut -d'"' -f4 || echo "processing")
        echo "   ⏳ Minuto $((i/6)) - Status: $STATUS"
        
        if [[ "$STATUS" == "completed" ]] || [[ "$STATUS" == "done" ]]; then
            echo "   ✅ Completado!"
            break
        fi
        if [[ "$STATUS" == "failed" ]] || [[ "$STATUS" == "error" ]]; then
            echo "   ❌ Falló!"
            break
        fi
    done
    
    kill $WORKER_PID 2>/dev/null || true
else
    # Modo directo - crear script de procesamiento
    echo "   🔧 Ejecutando procesamiento directo..."
    python3 << 'PYEOF'
import asyncio
import sys
sys.path.insert(0, '/home/_sebastian/CascadeProjects/ViraClip/backend/src')

from workers.tasks import process_video_task

async def main():
    task_data = {
        "source_type": "upload",
        "video_filename": "input_video.mp4",
        "platform": "tiktok",
        "options": {
            "max_clips": 3,
            "min_duration": 15,
            "max_duration": 60,
            "background_composite_enabled": True,
            "sam2_enabled": True,
        }
    }
    
    print("🎬 Iniciando procesamiento directo...")
    try:
        result = await process_video_task(task_data)
        print(f"✅ Resultado: {result}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(main())
PYEOF
fi

echo ""
echo "=========================================="
echo "🏁 PROCESO COMPLETADO"
echo "=========================================="
echo ""
echo "📁 Archivos:"
echo "   • Video: $WORKDIR/"
echo "   • Logs: $WORKDIR/worker.log"
echo ""
echo "🎞️  Clips generados en:"
docker exec viraclip-backend-1 ls -la /app/outputs/ 2>/dev/null || echo "   (verificar contenedor)"
echo ""
echo "🗑️  Para limpiar: rm -rf $WORKDIR"
