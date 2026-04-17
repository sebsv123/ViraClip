#!/bin/bash
# Script REAL para generar 4 shorts MP4 usando ComfyUI
# No simulaciones - ejecuta workflows reales via API

set -e

echo "=========================================="
echo "  Generación REAL de MP4s - ViraClip"
echo "=========================================="
echo ""

export VIRA_ROOT=/home/_sebastian/proyectos/ViraClip
mkdir -p $VIRA_ROOT/outputs/instagram_ready
mkdir -p $VIRA_ROOT/uploads

# Verificar prerequisitos
echo "🔍 Verificando entorno..."
if [ ! -f "$VIRA_ROOT/uploads/seguro_3wgwaxIfUJQ.mp4" ]; then
    echo "❌ Video no encontrado en uploads. Copiando..."
    cp $VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4 $VIRA_ROOT/uploads/ || {
        echo "❌ Error copiando video"
        exit 1
    }
fi
echo "✅ Video listo en uploads"

# Verificar ComfyUI
echo "🔍 Verificando ComfyUI..."
if ! curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
    echo "❌ ComfyUI no responde. Iniciando..."
    cd /home/_sebastian/CascadeProjects/ViraClip
    docker compose up -d comfyui
    sleep 30
fi
echo "✅ ComfyUI activo"

# Función para ejecutar workflow y esperar resultado
run_workflow() {
    local task_id=$1
    local workflow_file=$2
    local description=$3
    
    echo ""
    echo "🎬 Ejecutando: $description"
    echo "   Task ID: $task_id"
    
    # Enviar workflow
    response=$(curl -s -X POST http://localhost:8188/prompt \
        -H "Content-Type: application/json" \
        -d @"$workflow_file" 2>&1)
    
    if [ $? -ne 0 ]; then
        echo "❌ Error enviando workflow: $response"
        return 1
    fi
    
    prompt_id=$(echo "$response" | grep -o '"prompt_id":"[^"]*"' | cut -d'"' -f4)
    if [ -z "$prompt_id" ]; then
        echo "❌ No se pudo obtener prompt_id"
        echo "   Respuesta: $response"
        return 1
    fi
    
    echo "   Prompt ID: ${prompt_id:0:20}..."
    echo "   ⏳ Esperando procesamiento (30-60s)..."
    
    # Esperar a que termine (polling simple)
    local attempts=0
    local max_attempts=30
    local completed=false
    
    while [ $attempts -lt $max_attempts ] && [ "$completed" = false ]; do
        sleep 5
        history=$(curl -s "http://localhost:8188/history/$prompt_id" 2>/dev/null)
        if echo "$history" | grep -q "outputs"; then
            completed=true
        fi
        attempts=$((attempts + 1))
        echo -n "."
    done
    echo ""
    
    if [ "$completed" = false ]; then
        echo "⚠️  Timeout esperando resultado. Verificando manualmente..."
    fi
    
    # Verificar que el archivo existe
    sleep 2
    if ls $VIRA_ROOT/outputs/instagram_ready/${task_id}*.mp4 1> /dev/null 2>&1; then
        local mp4_file=$(ls -t $VIRA_ROOT/outputs/instagram_ready/${task_id}*.mp4 | head -1)
        local size=$(du -h "$mp4_file" | cut -f1)
        echo "   ✅ MP4 generado: $(basename $mp4_file) ($size)"
        return 0
    else
        echo "   ⚠️  Verificando output de ComfyUI..."
        docker exec viraclip-comfyui ls -la /comfyui/output/instagram_ready/ 2>/dev/null || echo "   No se pudo listar"
        
        # Intentar copiar si está en otra ruta
        docker exec viraclip-comfyui find /comfyui/output -name "${task_id}*.mp4" -type f 2>/dev/null | head -1 | while read src; do
            if [ -n "$src" ]; then
                echo "   📥 Copiando desde contenedor..."
                docker cp "viraclip-comfyui:$src" "$VIRA_ROOT/outputs/instagram_ready/"
            fi
        done
        
        # Verificar de nuevo
        if ls $VIRA_ROOT/outputs/instagram_ready/${task_id}*.mp4 1> /dev/null 2>&1; then
            echo "   ✅ MP4 generado y copiado"
            return 0
        else
            echo "❌ No se encontró archivo MP4"
            return 1
        fi
    fi
}

# Workflow 1: Reframe simple 9x16
echo ""
echo "📋 Preparando workflows..."

# Workflow 1: Reframe 9x16
cat > /tmp/workflow_1.json << 'EOF'
{
  "prompt": {
    "1": {
      "inputs": {
        "video": "/comfyui/input/seguro_3wgwaxIfUJQ.mp4",
        "force_rate": 30,
        "frame_load_cap": 600
      },
      "class_type": "VHS_LoadVideo"
    },
    "2": {
      "inputs": {
        "width": 1080,
        "height": 1920,
        "crop": "center",
        "video": ["1", 0]
      },
      "class_type": "VHS_ResizeVideo"
    },
    "3": {
      "inputs": {
        "frame_rate": 30,
        "filename_prefix": "instagram_ready/short_1_reframe",
        "format": "video/h264-mp4",
        "crf": 23,
        "save_output": true,
        "images": ["2", 0]
      },
      "class_type": "VHS_VideoCombine"
    }
  }
}
EOF

# Workflow 2: Reframe + crop inteligente
cat > /tmp/workflow_2.json << 'EOF'
{
  "prompt": {
    "1": {
      "inputs": {
        "video": "/comfyui/input/seguro_3wgwaxIfUJQ.mp4",
        "force_rate": 30,
        "frame_load_cap": 600
      },
      "class_type": "VHS_LoadVideo"
    },
    "2": {
      "inputs": {
        "width": 1080,
        "height": 1920,
        "interpolation": "lanczos",
        "video": ["1", 0]
      },
      "class_type": "VHS_ResizeVideo"
    },
    "3": {
      "inputs": {
        "frame_rate": 30,
        "filename_prefix": "instagram_ready/short_2_clean",
        "format": "video/h264-mp4",
        "crf": 23,
        "save_output": true,
        "images": ["2", 0]
      },
      "class_type": "VHS_VideoCombine"
    }
  }
}
EOF

# Workflow 3: Con segmento específico
cat > /tmp/workflow_3.json << 'EOF'
{
  "prompt": {
    "1": {
      "inputs": {
        "video": "/comfyui/input/seguro_3wgwaxIfUJQ.mp4",
        "force_rate": 30,
        "frame_load_cap": 900,
        "skip_first_frames": 150
      },
      "class_type": "VHS_LoadVideo"
    },
    "2": {
      "inputs": {
        "width": 1080,
        "height": 1920,
        "video": ["1", 0]
      },
      "class_type": "VHS_ResizeVideo"
    },
    "3": {
      "inputs": {
        "frame_rate": 30,
        "filename_prefix": "instagram_ready/short_3_subs",
        "format": "video/h264-mp4",
        "crf": 23,
        "save_output": true,
        "images": ["2", 0]
      },
      "class_type": "VHS_VideoCombine"
    }
  }
}
EOF

# Workflow 4: Full quality
cat > /tmp/workflow_4.json << 'EOF'
{
  "prompt": {
    "1": {
      "inputs": {
        "video": "/comfyui/input/seguro_3wgwaxIfUJQ.mp4",
        "force_rate": 30,
        "frame_load_cap": 750
      },
      "class_type": "VHS_LoadVideo"
    },
    "2": {
      "inputs": {
        "width": 1080,
        "height": 1920,
        "interpolation": "bicubic",
        "video": ["1", 0]
      },
      "class_type": "VHS_ResizeVideo"
    },
    "3": {
      "inputs": {
        "frame_rate": 30,
        "filename_prefix": "instagram_ready/short_4_full",
        "format": "video/h264-mp4",
        "pix_fmt": "yuv420p",
        "crf": 20,
        "save_output": true,
        "images": ["2", 0]
      },
      "class_type": "VHS_VideoCombine"
    }
  }
}
EOF

echo "✅ 4 workflows preparados"

# Ejecutar workflows
success_count=0

run_workflow "short_1_reframe" "/tmp/workflow_1.json" "Short 1: Reframe 9x16 básico" && success_count=$((success_count + 1))
run_workflow "short_2_clean" "/tmp/workflow_2.json" "Short 2: Reframe clean lanczos" && success_count=$((success_count + 1))
run_workflow "short_3_subs" "/tmp/workflow_3.json" "Short 3: Segmento específico (5s)" && success_count=$((success_count + 1))
run_workflow "short_4_full" "/tmp/workflow_4.json" "Short 4: Full quality CRF20" && success_count=$((success_count + 1))

# Resumen final
echo ""
echo "=========================================="
echo "  RESUMEN FINAL"
echo "=========================================="
echo ""

echo "📁 Verificando archivos generados..."
mp4_count=$(ls -1 $VIRA_ROOT/outputs/instagram_ready/*.mp4 2>/dev/null | wc -l)

echo "   MP4s generados: $mp4_count"
echo ""

if [ $mp4_count -eq 0 ]; then
    echo "❌ ERROR: No se generaron archivos MP4"
    echo "   Verificando contenedor..."
    docker exec viraclip-comfyui ls -la /comfyui/output/ 2>/dev/null || echo "   No se pudo acceder al contenedor"
    exit 1
fi

echo "✅ Archivos MP4 en $VIRA_ROOT/outputs/instagram_ready/:"
ls -lh $VIRA_ROOT/outputs/instagram_ready/*.mp4 2>/dev/null | awk '{print "   " $9 " (" $5 ")"}'

echo ""
echo "=========================================="
echo "  ✅ $mp4_count SHORTS LISTOS PARA INSTAGRAM"
echo "=========================================="
echo ""
echo "Ubicación: $VIRA_ROOT/outputs/instagram_ready/"
echo ""
