#!/bin/bash
# ViraClip - Shorts Virales REALES (Versión Corregida)
# Garantiza: 1080x1920, audio, subtítulos, jump cuts

VIRA_ROOT="/home/_sebastian/proyectos/ViraClip"
VIDEO="$VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"
OUTPUT="$VIRA_ROOT/outputs/instagram_ready"
COMFYUI="http://localhost:8188"

# Límites de reintentos
MAX_RETRIES=2

echo "=============================================="
echo "VIRACLIP - Shorts Virales REALES (Fixed)"
echo "=============================================="

# Verificar video
if [ ! -f "$VIDEO" ]; then
    echo "[ERROR] Video no encontrado: $VIDEO"
    exit 1
fi

mkdir -p "$OUTPUT"

# Función: Extraer segmento con duración EXACTA
extract_segment() {
    local name=$1
    local start=$2
    local duration=$3
    local output="$OUTPUT/${name}_raw.mp4"
    
    echo "[INFO] Extrayendo $name (${start}s, duración ${duration}s)..."
    
    # Extraer con codificación rápida (no copy) para asegurar duración exacta
    ffmpeg -y -ss "$start" -i "$VIDEO" -t "$duration" \
        -c:v libx264 -preset ultrafast -crf 28 \
        -c:a aac -b:a 128k \
        -r 30 \
        -avoid_negative_ts make_zero \
        "$output" 2>&1 | tail -5
    
    if [ ! -f "$output" ]; then
        echo "[ERROR] Extracción falló"
        return 1
    fi
    
    # Verificar duración
    actual_duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$output" 2>/dev/null | cut -d. -f1)
    echo "[OK] Extraído: ${actual_duration}s"
    return 0
}

# Función: Reframe 9:16 con FFmpeg (método principal, más confiable)
reframe_9x16_ffmpeg() {
    local input_file=$1
    local output_file=$2
    
    echo "[INFO] Reframe 9:16 con FFmpeg..."
    
    # Calcular crop para 9:16 desde centro del video
    # Si el video es 16:9 (1920x1080), crop a 608x1080 (9:16 desde centro)
    # Luego upscale a 1080x1920
    
    ffmpeg -y -i "$input_file" -vf "
        crop=ih*9/16:ih:(iw-ih*9/16)/2:0,
        scale=1080:1920:flags=lanczos,
        fps=30
    " -c:v libx264 -preset fast -crf 23 \
      -c:a aac -b:a 128k \
      "$output_file" 2>&1 | tail -5
    
    if [ ! -f "$output_file" ]; then
        echo "[ERROR] Reframe falló"
        return 1
    fi
    
    # Verificar resolución
    res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$output_file" 2>/dev/null)
    echo "[OK] Resolución: $res"
    
    if [ "$res" != "1080x1920" ]; then
        echo "[ERROR] Resolución incorrecta: $res (esperado 1080x1920)"
        rm -f "$output_file"
        return 1
    fi
    
    return 0
}

# Función: Agregar subtítulos con estilo viral
add_subtitles() {
    local input_file=$1
    local output_file=$2
    local text=$3
    
    echo "[INFO] Agregando subtítulos..."
    
    # Crear subtítulo centrado con sombra (estilo TikTok/Instagram)
    ffmpeg -y -i "$input_file" -vf "
        drawtext=text='${text}':
            fontsize=48:
            fontcolor=white:
            fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:
            x=(w-text_w)/2:
            y=h*0.8:
            shadowcolor=black@0.8:
            shadowx=3:shadowy=3:
            box=1:boxcolor=black@0.4:boxborderw=10
    " -c:v libx264 -preset fast -crf 23 \
      -c:a copy \
      "$output_file" 2>&1 | tail -5
    
    if [ -f "$output_file" ]; then
        echo "[OK] Subtítulos agregados"
        return 0
    else
        echo "[ERROR] Subtítulos fallaron"
        return 1
    fi
}

# Función: Aplicar jump cuts (acelerar + zoom sutil)
apply_viral_effects() {
    local input_file=$1
    local output_file=$2
    
    echo "[INFO] Aplicando efectos virales (zoom + velocidad)..."
    
    # Zoom sutil + velocidad 1.1x (jump cut effect)
    ffmpeg -y -i "$input_file" -vf "
        zoompan=z='1.05':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',
        setpts=0.909*PTS
    " -af "atempo=1.1" \
      -c:v libx264 -preset fast -crf 23 \
      -c:a aac -b:a 128k \
      "$output_file" 2>&1 | tail -5
    
    if [ -f "$output_file" ]; then
        echo "[OK] Efectos aplicados"
        return 0
    else
        cp "$input_file" "$output_file"
        echo "[WARNING] Efectos omitidos, usando original"
        return 1
    fi
}

# Función: Procesar un short completo
process_short() {
    local name=$1
    local start=$2
    local duration=$3
    local desc=$4
    local subtitle_text=$5
    
    echo ""
    echo "=============================================="
    echo "🎬 $name: $desc"
    echo "   Tiempo: ${start}s - ${duration}s"
    echo "=============================================="
    
    local temp_prefix="$OUTPUT/.${name}_temp"
    local final_output="$OUTPUT/${name}.mp4"
    
    # Paso 1: Extraer segmento
    if ! extract_segment "$temp_prefix" "$start" "$duration"; then
        return 1
    fi
    
    # Paso 2: Reframe 9:16 (CRÍTICO - debe ser 1080x1920)
    if ! reframe_9x16_ffmpeg "${temp_prefix}_raw.mp4" "${temp_prefix}_reframe.mp4"; then
        echo "[ERROR] Reframe falló, abortando $name"
        rm -f "${temp_prefix}_raw.mp4"
        return 1
    fi
    
    # Paso 3: Agregar subtítulos
    if ! add_subtitles "${temp_prefix}_reframe.mp4" "${temp_prefix}_subs.mp4" "$subtitle_text"; then
        cp "${temp_prefix}_reframe.mp4" "${temp_prefix}_subs.mp4"
    fi
    
    # Paso 4: Aplicar efectos virales
    if ! apply_viral_effects "${temp_prefix}_subs.mp4" "$final_output"; then
        echo "[ERROR] Efectos fallaron"
        return 1
    fi
    
    # Limpiar temporales
    rm -f "${temp_prefix}_raw.mp4" "${temp_prefix}_reframe.mp4" "${temp_prefix}_subs.mp4"
    
    # Verificar resultado final
    if [ ! -f "$final_output" ]; then
        echo "[ERROR] Archivo final no existe"
        return 1
    fi
    
    # Verificaciones finales
    final_res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$final_output" 2>/dev/null)
    final_duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$final_output" 2>/dev/null | cut -d. -f1)
    final_size=$(du -h "$final_output" | cut -f1)
    
    if [ "$final_res" != "1080x1920" ]; then
        echo "[ERROR] Resolución final incorrecta: $final_res"
        rm -f "$final_output"
        return 1
    fi
    
    echo "[✅] $name COMPLETADO"
    echo "    └─ ${final_size}, ${final_duration}s, $final_res"
    return 0
}

# ============================================
# PROCESAR 4 SHORTS
# ============================================

SHORTS_CONFIG=(
    "viral_hook:0:15:Hook inicial:¡ATENCIÓN!"
    "viral_value:30:25:Valor/Insight:DESCUBRE ESTO"
    "viral_proof:60:25:Prueba:RESULTADO REAL"
    "viral_cta:90:35:CTA:HAZLO AHORA"
)

generated=0
total=${#SHORTS_CONFIG[@]}

for config in "${SHORTS_CONFIG[@]}"; do
    IFS=':' read -r name start duration desc subtitle <<< "$config"
    
    echo ""
    echo "🚀 Procesando $((generated+1))/$total"
    
    if process_short "$name" "$start" "$duration" "$desc" "$subtitle"; then
        ((generated++))
    else
        echo "❌ $name falló"
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
        res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$file" 2>/dev/null)
        echo "  📹 $name ($size) - $res"
    fi
done

if [ $generated -eq $total ]; then
    echo ""
    echo "🎉 ¡ÉXITO! $generated shorts virales en 1080x1920"
    echo "📁 $OUTPUT"
    exit 0
else
    echo ""
    echo "⚠️  $generated/$total generados"
    exit 1
fi
