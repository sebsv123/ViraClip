#!/bin/bash
# EJECUTAR MANUALMENTE EN TU TERMINAL FISH
# Estos comandos generarán 4 MP4s reales para Instagram

echo "=========================================="
echo "  VIRACLIP - Generación REAL de 4 MP4s"
echo "=========================================="
echo ""

# Configurar rutas
export VIRA_ROOT=~/proyectos/ViraClip
export COMFYUI_URL="http://localhost:8188"

# Crear directorios necesarios
mkdir -p $VIRA_ROOT/outputs/instagram_ready
mkdir -p $VIRA_ROOT/uploads
mkdir -p $VIRA_ROOT/comfyui/workflows

echo "✅ Directorios creados"

# Paso 1: Verificar video de entrada
echo ""
echo "🔍 Verificando video de entrada..."
if test -f $VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4
    echo "✅ Video encontrado"
else
    echo "❌ Video NO encontrado"
    exit 1
end

# Copiar a uploads (donde ComfyUI puede acceder)
cp $VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4 $VIRA_ROOT/uploads/
echo "✅ Video copiado a uploads/"

# Paso 2: Verificar ComfyUI
echo ""
echo "🔍 Verificando ComfyUI..."
curl -s $COMFYUI_URL/system_stats > /dev/null
if test $status -eq 0
    echo "✅ ComfyUI activo en $COMFYUI_URL"
else
    echo "❌ ComfyUI NO responde"
    echo "💡 Inicia ComfyUI: cd ~/CascadeProjects/ViraClip && docker compose up -d comfyui"
    exit 1
end

# Paso 3: Crear workflows JSON reales
echo ""
echo "📝 Creando workflows..."

# Workflow 1: Reframe básico 9x16
cat > $VIRA_ROOT/comfyui/workflows/short_1_reframe.json << 'WORKFLOW_EOF'
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
        "filename_prefix": "instagram_ready/short_1_reframe",
        "format": "video/h264-mp4",
        "pix_fmt": "yuv420p",
        "crf": 23,
        "save_output": true,
        "images": ["2", 0]
      },
      "class_type": "VHS_VideoCombine"
    }
  }
}
WORKFLOW_EOF

# Workflow 2: Clean lanczos
cat > $VIRA_ROOT/comfyui/workflows/short_2_clean.json << 'WORKFLOW_EOF'
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
        "pix_fmt": "yuv420p",
        "crf": 23,
        "save_output": true,
        "images": ["2", 0]
      },
      "class_type": "VHS_VideoCombine"
    }
  }
}
WORKFLOW_EOF

# Workflow 3: Segmento específico (desde 5s)
cat > $VIRA_ROOT/comfyui/workflows/short_3_segment.json << 'WORKFLOW_EOF'
{
  "prompt": {
    "1": {
      "inputs": {
        "video": "/comfyui/input/seguro_3wgwaxIfUJQ.mp4",
        "force_rate": 30,
        "frame_load_cap": 600,
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
        "filename_prefix": "instagram_ready/short_3_segment",
        "format": "video/h264-mp4",
        "pix_fmt": "yuv420p",
        "crf": 23,
        "save_output": true,
        "images": ["2", 0]
      },
      "class_type": "VHS_VideoCombine"
    }
  }
}
WORKFLOW_EOF

# Workflow 4: Full quality
cat > $VIRA_ROOT/comfyui/workflows/short_4_full.json << 'WORKFLOW_EOF'
{
  "prompt": {
    "1": {
      "inputs": {
        "video": "/comfyui/input/seguro_3wgwaxIfUJQ.mp4",
        "force_rate": 30,
        "frame_load_cap": 900
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
WORKFLOW_EOF

echo "✅ 4 workflows creados en $VIRA_ROOT/comfyui/workflows/"

# Paso 4: Función para ejecutar workflow
function execute_workflow
    set workflow_file $argv[1]
    set description $argv[2]
    
    echo ""
    echo "🎬 Ejecutando: $description"
    echo "   Workflow: $workflow_file"
    
    # Enviar a ComfyUI
    set response (curl -s -X POST $COMFYUI_URL/prompt \
        -H "Content-Type: application/json" \
        -d @$workflow_file)
    
    if test $status -ne 0
        echo "❌ Error enviando workflow"
        return 1
    end
    
    # Extraer prompt_id
    set prompt_id (echo $response | grep -o '"prompt_id":"[^"]*"' | cut -d'"' -f4)
    
    if test -z "$prompt_id"
        echo "❌ No se pudo obtener prompt_id"
        echo "   Respuesta: $response"
        return 1
    end
    
    echo "   Prompt ID: $prompt_id"
    echo -n "   ⏳ Esperando (polling cada 5s)"
    
    # Esperar con timeout de 5 minutos
    set attempts 0
    set max_attempts 60
    set completed false
    
    while test $attempts -lt $max_attempts -a "$completed" = "false"
        sleep 5
        echo -n "."
        
        # Verificar en history
        set history (curl -s "$COMFYUI_URL/history/$prompt_id" 2>/dev/null)
        if echo "$history" | grep -q '"outputs"'
            set completed true
        end
        
        set attempts (math $attempts + 1)
    end
    
    echo ""
    
    if test "$completed" = "false"
        echo "⚠️  Timeout después de 5 minutos"
        return 1
    end
    
    echo "   ✅ Workflow completado"
    return 0
end

# Paso 5: Ejecutar los 4 workflows
echo ""
echo "🚀 Iniciando generación de 4 shorts..."
echo ""

set success_count 0

execute_workflow $VIRA_ROOT/comfyui/workflows/short_1_reframe.json "Short 1: Reframe 9x16 básico (bicubic)"
if test $status -eq 0
    set success_count (math $success_count + 1)
end

execute_workflow $VIRA_ROOT/comfyui/workflows/short_2_clean.json "Short 2: Clean lanczos (mejor calidad)"
if test $status -eq 0
    set success_count (math $success_count + 1)
end

execute_workflow $VIRA_ROOT/comfyui/workflows/short_3_segment.json "Short 3: Segmento 5s+ (skip frames)"
if test $status -eq 0
    set success_count (math $success_count + 1)
end

execute_workflow $VIRA_ROOT/comfyui/workflows/short_4_full.json "Short 4: Full quality CRF20"
if test $status -eq 0
    set success_count (math $success_count + 1)
end

# Paso 6: Verificar resultados
echo ""
echo "=========================================="
echo "  VERIFICACIÓN DE RESULTADOS"
echo "=========================================="
echo ""

echo "📁 Contenido de $VIRA_ROOT/outputs/instagram_ready/:"
ls -lh $VIRA_ROOT/outputs/instagram_ready/*.mp4 2>/dev/null | while read line
    echo "   📹 $line"
end

set mp4_count (ls -1 $VIRA_ROOT/outputs/instagram_ready/*.mp4 2>/dev/null | wc -l)

echo ""
echo "=========================================="
echo "  RESUMEN FINAL"
echo "=========================================="
echo ""
echo "✅ Shorts generados exitosamente: $mp4_count/4"
echo ""

if test $mp4_count -eq 4
    echo "🎉 TODOS LOS SHORTS LISTOS PARA INSTAGRAM!"
    echo ""
    echo "Ubicación: $VIRA_ROOT/outputs/instagram_ready/"
    echo ""
    echo "Archivos:"
    ls -1 $VIRA_ROOT/outputs/instagram_ready/*.mp4 | while read file
        echo "   📱 $file"
    end
    echo ""
    exit 0
else
    echo "⚠️  Solo $mp4_count/4 shorts generados"
    echo ""
    echo "🔍 Verificando contenedor..."
    docker exec viraclip-comfyui ls -la /comfyui/output/instagram_ready/ 2>/dev/null
    echo ""
    echo "💡 Si hay archivos en el contenedor pero no en el host,"
    echo "   verifica el mapeo de volúmenes en docker-compose.yml"
    exit 1
end
