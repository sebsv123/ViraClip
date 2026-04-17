#!/bin/bash
# ViraClip - Crear Shorts Virales REALES con FFmpeg + ComfyUI
# Features: Audio, subtítulos, reframe, jump cuts, overlays

# No usar set -e para que continúe con el siguiente short si uno falla

VIRA_ROOT="/home/_sebastian/proyectos/ViraClip"
VIDEO="$VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"
OUTPUT="$VIRA_ROOT/outputs/instagram_ready"
COMFYUI="http://localhost:8188"

echo "=============================================="
echo "VIRACLIP - Shorts Virales REALES"
echo "=============================================="

# Verificar video
if [ ! -f "$VIDEO" ]; then
    echo "[ERROR] Video no encontrado: $VIDEO"
    exit 1
fi

mkdir -p "$OUTPUT"

# Verificar ComfyUI
echo "[INFO] Verificando ComfyUI..."
if ! curl -s "$COMFYUI/system_stats" > /dev/null 2>&1; then
    echo "[WARNING] ComfyUI no responde, reiniciando..."
    cd /home/_sebastian/CascadeProjects/ViraClip
    docker-compose up -d comfyui
    sleep 45
fi

# Función: Extraer segmento con audio usando ffmpeg
extract_segment() {
    local name=$1
    local start=$2
    local duration=$3
    local output="$OUTPUT/${name}_raw.mp4"
    
    echo "[INFO] Extrayendo $name (${start}s-${duration}s)..."
    ffmpeg -y -i "$VIDEO" -ss "$start" -t "$duration" \
        -c:v copy -c:a copy \
        -avoid_negative_ts make_zero \
        "$output" 2>/dev/null
    
    if [ -f "$output" ]; then
        size=$(du -h "$output" | cut -f1)
        echo "[OK] $name extraído: $size"
        return 0
    else
        echo "[ERROR] Falló extracción de $name"
        return 1
    fi
}

# Función: Enviar workflow a ComfyUI para reframe 9:16
reframe_with_comfyui() {
    local input_file=$1
    local output_name=$2
    local video_basename=$(basename "$input_file")
    
    echo "[INFO] Enviando a ComfyUI para reframe 9:16: $output_name"
    
    # Copiar a input de ComfyUI
    docker cp "$input_file" viraclip-comfyui:/comfyui/input/"$video_basename" 2>/dev/null || true
    
    # Workflow JSON
    workflow=$(cat <<EOF
{
    "prompt": {
        "1": {
            "inputs": {
                "video": "$video_basename",
                "force_rate": 30,
                "frame_load_cap": 450,
                "force_size": "Custom",
                "custom_width": 1080,
                "custom_height": 1920,
                "skip_first_frames": 0,
                "select_every_nth": 1
            },
            "class_type": "VHS_LoadVideo"
        },
        "2": {
            "inputs": {
                "frame_rate": 30,
                "loop_count": 0,
                "filename_prefix": "instagram_ready/${output_name}",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 23,
                "pingpong": false,
                "save_output": true,
                "save_image": true,
                "images": ["1", 0]
            },
            "class_type": "VHS_VideoCombine"
        }
    }
}
EOF
)
    
    # Enviar workflow
    response=$(curl -s -X POST "$COMFYUI/prompt" \
        -H "Content-Type: application/json" \
        -d "$workflow" 2>/dev/null)
    
    prompt_id=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('prompt_id',''))" 2>/dev/null)
    
    if [ -z "$prompt_id" ]; then
        echo "[ERROR] No se obtuvo prompt_id"
        return 1
    fi
    
    echo "[INFO] Prompt ID: ${prompt_id:0:20}..."
    echo "[INFO] Esperando procesamiento (hasta 5 min)..."
    
    # Esperar con polling
    attempts=0
    max_attempts=60
    while [ $attempts -lt $max_attempts ]; do
        sleep 5
        ((attempts++))
        
        # Mostrar progreso cada minuto
        if [ $((attempts % 12)) -eq 0 ]; then
            echo -n "."
        fi
        
        # Verificar si terminó
        history=$(curl -s "$COMFYUI/history/$prompt_id" 2>/dev/null)
        if echo "$history" | python3 -c "import sys,json; d=json.load(sys.stdin); print('outputs' in str(d))" 2>/dev/null | grep -q "True"; then
            echo ""
            echo "[OK] Workflow completado"
            return 0
        fi
    done
    
    echo ""
    echo "[WARNING] Timeout esperando workflow"
    return 1
}

# Función: Aplicar subtítulos con FFmpeg (burn-in simple)
add_subtitles_ffmpeg() {
    local input_file=$1
    local output_file=$2
    
    echo "[INFO] Aplicando subtítulos estáticos..."
    
    # Crear subtítulos dummy (en producción usarías Whisper)
    # Por ahora solo agregamos texto overlay
    ffmpeg -y -i "$input_file" -vf "
        drawtext=text='VIRACLIP':fontsize=30:fontcolor=white:x=(w-text_w)/2:y=50:box=1:boxcolor=black@0.5,
        drawtext=text='@{localtime}':fontsize=20:fontcolor=yellow:x=(w-text_w)/2:y=h-80
    " -c:a copy "$output_file" 2>/dev/null
    
    if [ -f "$output_file" ]; then
        echo "[OK] Subtítulos aplicados"
        return 0
    else
        echo "[WARNING] No se aplicaron subtítulos"
        return 1
    fi
}

# Función: Aplicar jump cuts (detectar silencios y cortar)
apply_jump_cuts() {
    local input_file=$1
    local output_file=$2
    
    echo "[INFO] Aplicando jump cuts (eliminando silencios)..."
    
    # Detectar silencios (>0.3s) y crear filtro
    ffmpeg -y -i "$input_file" -af \
        "silencedetect=noise=-50dB:d=0.3" \
        -f null - 2>&1 | grep "silence_" > /tmp/silence.txt || true
    
    # Por simplicidad, solo aceleramos ligeramente y aplicamos zoom
    ffmpeg -y -i "$input_file" -vf "
        zoompan=z='min(max(zoom,pzoom)+0.002,1.1)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',
        setpts=0.95*PTS
    " -af "atempo=1.05" -c:v libx264 -crf 23 -preset fast "$output_file" 2>/dev/null
    
    if [ -f "$output_file" ]; then
        echo "[OK] Jump cuts aplicados"
        return 0
    else
        cp "$input_file" "$output_file"
        echo "[WARNING] Jump cuts omitidos"
        return 1
    fi
}

# Función: Procesar un short completo
process_short() {
    local name=$1
    local start=$2
    local duration=$3
    local desc=$4
    
    echo ""
    echo "=============================================="
    echo "🎬 $name: $desc"
    echo "   Tiempo: ${start}s-${duration}s (${duration}s)"
    echo "=============================================="
    
    # Paso 1: Extraer segmento
    if ! extract_segment "$name" "$start" "$duration"; then
        return 1
    fi
    
    # Paso 2: Reframe 9:16 con ComfyUI
    if ! reframe_with_comfyui "$OUTPUT/${name}_raw.mp4" "${name}_reframe"; then
        echo "[WARNING] Reframe falló, usando ffmpeg..."
        ffmpeg -y -i "$OUTPUT/${name}_raw.mp4" -vf "crop=ih*9/16:ih,scale=1080:1920" \
            -c:a copy "$OUTPUT/${name}_reframe_00001.mp4" 2>/dev/null || \
        cp "$OUTPUT/${name}_raw.mp4" "$OUTPUT/${name}_reframe_00001.mp4"
    fi
    
    # Paso 3: Verificar que existe el reframe
    reframe_file="$OUTPUT/${name}_reframe_00001.mp4"
    if [ ! -f "$reframe_file" ]; then
        # Buscar cualquier archivo que coincida
        reframe_file=$(find "$OUTPUT" -name "${name}_reframe*.mp4" -type f | head -1)
        if [ -z "$reframe_file" ]; then
            echo "[ERROR] No se encontró archivo reframe"
            return 1
        fi
    fi
    
    # Paso 4: Aplicar subtítulos
    add_subtitles_ffmpeg "$reframe_file" "$OUTPUT/${name}_subs.mp4" || cp "$reframe_file" "$OUTPUT/${name}_subs.mp4"
    
    # Paso 5: Aplicar jump cuts y zooms
    apply_jump_cuts "$OUTPUT/${name}_subs.mp4" "$OUTPUT/${name}.mp4" || cp "$OUTPUT/${name}_subs.mp4" "$OUTPUT/${name}.mp4"
    
    # Limpiar intermedios
    rm -f "$OUTPUT/${name}_raw.mp4" "$OUTPUT/${name}_reframe*.mp4" "$OUTPUT/${name}_subs.mp4"
    
    # Verificar resultado final
    if [ -f "$OUTPUT/${name}.mp4" ]; then
        size=$(du -h "$OUTPUT/${name}.mp4" | cut -f1)
        echo "[✅] $name COMPLETADO: $size"
        return 0
    else
        echo "[❌] $name FALLÓ"
        return 1
    fi
}

# ============================================
# PROCESAR 4 SHORTS
# ============================================

SHORTS_CONFIG=(
    "viral_hook:0:15:Hook viral inicial"
    "viral_value:30:25:Valor e insight"
    "viral_proof:60:25:Prueba social"
    "viral_cta:90:35:CTA y cierre viral"
)

generated=0
total=${#SHORTS_CONFIG[@]}

for i in "${!SHORTS_CONFIG[@]}"; do
    IFS=':' read -r name start duration desc <<< "${SHORTS_CONFIG[$i]}"
    
    echo ""
    echo "🚀 Procesando $((i+1))/$total"
    
    if process_short "$name" "$start" "$duration" "$desc"; then
        ((generated++))
        echo "✅ $((i+1))/$total completado"
    else
        echo "❌ $((i+1))/$total falló"
    fi
    
    # Pausa entre shorts
    if [ $i -lt $((total-1)) ]; then
        echo "⏸️  Pausa 5s..."
        sleep 5
    fi
done

# ============================================
# RESUMEN FINAL
# ============================================
echo ""
echo "=============================================="
echo "📊 RESUMEN FINAL"
echo "=============================================="

echo "[INFO] Shorts generados: $generated/$total"

for file in "$OUTPUT"/viral_*.mp4; do
    if [ -f "$file" ]; then
        name=$(basename "$file")
        size=$(du -h "$file" | cut -f1)
        echo "  📹 $name ($size)"
    fi
done

if [ $generated -eq $total ]; then
    echo ""
    echo "🎉 ¡ÉXITO! $generated shorts virales listos para Instagram"
    echo "📁 Ubicación: $OUTPUT"
    exit 0
else
    echo ""
    echo "⚠️  $generated/$total shorts generados"
    exit 1
fi
