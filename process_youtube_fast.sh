#!/bin/bash
# ViraClip Fast Processing - Usa infraestructura existente
set -e

VIDEO_URL="${1:-https://youtu.be/DvfjmBa3Kvk}"
WORKDIR="/tmp/viraclip_$(date +%s)"
mkdir -p "$WORKDIR"

echo "=========================================="
echo "🎬 ViraClip Fast Processing"
echo "=========================================="
echo "📹 URL: $VIDEO_URL"
echo ""

# Verificar que todo esté corriendo
echo "🔍 Verificando infraestructura..."
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ Backend no responde en :8000"
    exit 1
fi
echo "   ✅ Backend OK (localhost:8000)"

if ! curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
    echo "⚠️  ComfyUI no responde en :8188 (opcional para SAM2)"
else
    echo "   ✅ ComfyUI OK (localhost:8188)"
fi
echo ""

# 1. Descargar video
echo "⬇️  Paso 1: Descargando video..."
yt-dlp -f 'best[height<=1080][ext=mp4]/best[ext=mp4]/best' \
    -o "$WORKDIR/video.%(ext)s" \
    --no-playlist \
    "$VIDEO_URL" 2>&1 | tail -5

VIDEO_FILE=$(ls "$WORKDIR/video".* 2>/dev/null | head -1)
if [ -z "$VIDEO_FILE" ]; then
    echo "❌ No se pudo descargar"
    exit 1
fi

SIZE=$(du -h "$VIDEO_FILE" | cut -f1)
echo "   ✅ Descargado: $(basename $VIDEO_FILE) ($SIZE)"
echo ""

# 2. Copiar al contenedor backend
echo "📦 Paso 2: Subiendo a ViraClip..."
docker cp "$VIDEO_FILE" viraclip-backend:/app/uploads/
echo "   ✅ Video en backend"
echo ""

# 3. Crear y enviar tarea
echo "🎯 Paso 3: Creando tarea..."

TASK_JSON=$(cat <<EOF
{
  "source_type": "upload", 
  "video_path": "/app/uploads/$(basename $VIDEO_FILE)",
  "platform": "tiktok",
  "options": {
    "max_clips": 3,
    "min_duration": 15,
    "max_duration": 60,
    "background_composite_enabled": true,
    "sam2_enabled": true,
    "generate_captions": true,
    "virality_threshold": 7.0
  }
}
EOF
)

echo "$TASK_JSON" > "$WORKDIR/task.json"

# Enviar a la API
RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d "$TASK_JSON" 2>/dev/null || echo "{}")

echo "   📤 Response: $RESPONSE"

TASK_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

if [ -z "$TASK_ID" ]; then
    echo "⚠️  No se obtuvo task_id de API. Procesando directamente con worker..."
    
    # Ejecutar directamente en el contenedor worker
    docker exec viraclip-worker python3 -c "
import asyncio
import sys
sys.path.insert(0, '/app/src')

async def main():
    from workers.tasks import process_video_task
    
    task_data = {
        'source_type': 'upload',
        'video_path': '/app/uploads/$(basename $VIDEO_FILE)',
        'platform': 'tiktok',
        'options': {
            'max_clips': 3,
            'min_duration': 15,
            'max_duration': 60,
            'background_composite_enabled': True,
            'sam2_enabled': True,
            'generate_captions': True,
            'virality_threshold': 7.0
        }
    }
    
    print('🎬 Procesando video...')
    try:
        result = await process_video_task(task_data)
        print(f'✅ Completado: {result}')
        return result
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()
        raise

result = asyncio.run(main())
print(f'Resultado final: {result}')
" 2>&1 | tee "$WORKDIR/processing.log"

else
    echo "   ✅ Task creado: $TASK_ID"
    echo ""
    
    # 4. Monitorear progreso
    echo "⏳ Paso 4: Monitoreando..."
    for i in {1..60}; do  # 10 min max
        sleep 10
        
        STATUS=$(curl -s "http://localhost:8000/api/v1/tasks/$TASK_ID" 2>/dev/null | \
            python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','processing'))" 2>/dev/null || echo "processing")
        
        echo "   ⏱️  $((${i}*10))s - Estado: $STATUS"
        
        if [[ "$STATUS" == "completed" ]] || [[ "$STATUS" == "done" ]] || [[ "$STATUS" == "success" ]]; then
            echo ""
            echo "   ✅ ¡PROCESAMIENTO COMPLETADO!"
            break
        fi
        if [[ "$STATUS" == "failed" ]] || [[ "$STATUS" == "error" ]]; then
            echo ""
            echo "   ❌ PROCESAMIENTO FALLIDO"
            break
        fi
    done
fi

echo ""
echo "=========================================="
echo "🏁 FIN"
echo "=========================================="
echo ""
echo "📁 Archivos en: $WORKDIR"
echo ""
echo "🎞️  Clips generados:"
docker exec viraclip-backend ls -la /app/outputs/ 2>/dev/null || echo "   (ver /app/outputs en contenedor)"
echo ""
echo "Para limpiar: rm -rf $WORKDIR"
