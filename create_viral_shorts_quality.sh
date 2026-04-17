#!/bin/bash
# ViraClip - Shorts Virales CALIDAD PROFESIONAL
# Prioridad: CALIDAD > velocidad
# Features: 1080x1920, audio HQ, subtítulos profesionales, zoom cinematográfico

VIRA_ROOT="/home/_sebastian/proyectos/ViraClip"
VIDEO="$VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"
OUTPUT="$VIRA_ROOT/outputs/instagram_ready"
TEMP="$OUTPUT/.temp_$$"
COMFYUI="http://localhost:8188"

mkdir -p "$TEMP"

echo "=============================================="
echo "VIRACLIP - Shorts Virales CALIDAD PROFESIONAL"
echo "Prioridad: CALIDAD > Velocidad"
echo "=============================================="

# Verificar video
if [ ! -f "$VIDEO" ]; then
    echo "[ERROR] Video no encontrado: $VIDEO"
    exit 1
fi

# Función: Extraer segmento con calidad máxima
extract_segment_quality() {
    local name=$1
    local start=$2
    local duration=$3
    local output="$TEMP/${name}_raw.mp4"
    
    echo ""
    echo "[1] EXTRACCIÓN - $name (${duration}s desde ${start}s)"
    echo "    └─ Usando keyframes precisos + audio original..."
    
    # Extraer con seeking preciso (más lento pero exacto)
    ffmpeg -y -ss "$start" -i "$VIDEO" -t "$duration" \
        -c:v libx264 -preset slow -crf 18 \
        -pix_fmt yuv420p \
        -c:a aac -b:a 192k \
        -r 30 \
        -movflags +faststart \
        "$output" 2>&1 | grep -E "(frame|size|time)" | tail -3
    
    if [ ! -f "$output" ]; then
        echo "    ❌ Extracción falló"
        return 1
    fi
    
    # Verificar
    actual_duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$output" 2>/dev/null | cut -d. -f1)
    size=$(du -h "$output" | cut -f1)
    echo "    ✅ Extraído: ${actual_duration}s, $size"
    return 0
}

# Función: Reframe 9:16 con calidad profesional
reframe_quality() {
    local input_file=$1
    local output_file=$2
    
    echo ""
    echo "[2] REFRAME 9:16 - Smart crop + upscale profesional"
    echo "    └─ Lanczos + Sharpen + 1080x1920 exacto..."
    
    # Detectar resolución de entrada
    src_width=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null)
    src_height=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null)
    echo "    └─ Input: ${src_width}x${src_height}"
    
    # Si es 1920x1080 (16:9), calcular crop 9:16 desde centro
    # Si es otra resolución, adaptar
    if [ "$src_width" -gt "$src_height" ]; then
        # Landscape - crop a 9:16
        crop_width=$((src_height * 9 / 16))
        crop_x=$(((src_width - crop_width) / 2))
        
        ffmpeg -y -i "$input_file" -vf "
            crop=${crop_width}:${src_height}:${crop_x}:0,
            scale=1080:1920:flags=lanczos,
            unsharp=3:3:0.5:3:3:0.5,
            fps=30
        " -c:v libx264 -preset slow -crf 18 \
          -pix_fmt yuv420p \
          -c:a aac -b:a 192k \
          -movflags +faststart \
          "$output_file" 2>&1 | grep -E "(frame|size|time)" | tail -3
    else
        # Portrait o cuadrado - upscale directo
        ffmpeg -y -i "$input_file" -vf "
            scale=1080:1920:flags=lanczos:force_original_aspect_ratio=decrease,
            pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,
            unsharp=3:3:0.5:3:3:0.5
        " -c:v libx264 -preset slow -crf 18 \
          -pix_fmt yuv420p \
          -c:a aac -b:a 192k \
          -movflags +faststart \
          "$output_file" 2>&1 | grep -E "(frame|size|time)" | tail -3
    fi
    
    if [ ! -f "$output_file" ]; then
        echo "    ❌ Reframe falló"
        return 1
    fi
    
    # Verificación estricta
    out_width=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=noprint_wrappers=1:nokey=1 "$output_file" 2>/dev/null)
    out_height=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=noprint_wrappers=1:nokey=1 "$output_file" 2>/dev/null)
    
    if [ "$out_width" -ne 1080 ] || [ "$out_height" -ne 1920 ]; then
        echo "    ❌ Resolución incorrecta: ${out_width}x${out_height} (esperado 1080x1920)"
        rm -f "$output_file"
        return 1
    fi
    
    size=$(du -h "$output_file" | cut -f1)
    echo "    ✅ Reframe: 1080x1920, $size"
    return 0
}

# Función: Subtítulos profesionales animados
add_subtitles_quality() {
    local input_file=$1
    local output_file=$2
    local text=$3
    
    echo ""
    echo "[3] SUBTÍTULOS - Estilo profesional TikTok/Instagram"
    echo "    └─ Texto: '$text'"
    
    # Buscar fuente disponible
    font_file=""
    for font in "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"; do
        if [ -f "$font" ]; then
            font_file="$font"
            break
        fi
    done
    
    if [ -z "$font_file" ]; then
        echo "    ⚠️ Fuente no encontrada, usando default"
        font_file="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    fi
    
    # Subtítulos con sombra, borde y animación sutil
    ffmpeg -y -i "$input_file" -vf "
        drawtext=fontfile='$font_file':
            text='$text':
            fontsize=56:
            fontcolor=white:
            x=(w-text_w)/2:
            y=h*0.75:
            shadowcolor=black@0.9:
            shadowx=4:shadowy=4:
            borderw=3:bordercolor=black@0.8,
        format=yuv420p
    " -c:v libx264 -preset slow -crf 18 \
      -c:a aac -b:a 192k \
      -movflags +faststart \
      "$output_file" 2>&1 | grep -E "(frame|size|time)" | tail -3
    
    if [ ! -f "$output_file" ]; then
        echo "    ❌ Subtítulos fallaron"
        return 1
    fi
    
    size=$(du -h "$output_file" | cut -f1)
    echo "    ✅ Subtítulos: $size"
    return 0
}

# Función: Efectos virales cinematográficos
apply_viral_effects_quality() {
    local input_file=$1
    local output_file=$2
    
    echo ""
    echo "[4] EFECTOS VIRALES - Zoom cinematográfico + ritmo"
    echo "    └─ Zoom lento + velocidad dinámica..."
    
    # Zoom cinematográfico lento (1.0 → 1.08 en 3s) + velocidad 1.15x
    ffmpeg -y -i "$input_file" -vf "
        zoompan=z='1.0+0.08*in/90':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',
        setpts=0.87*PTS,
        format=yuv420p
    " -af "atempo=1.15" \
      -c:v libx264 -preset slow -crf 18 \
      -c:a aac -b:a 192k \
      -movflags +faststart \
      "$output_file" 2>&1 | grep -E "(frame|size|time)" | tail -3
    
    if [ ! -f "$output_file" ]; then
        echo "    ❌ Efectos fallaron"
        return 1
    fi
    
    size=$(du -h "$output_file" | cut -f1)
    echo "    ✅ Efectos: $size"
    return 0
}

# Función: Procesar short completo con calidad
process_short_quality() {
    local name=$1
    local start=$2
    local duration=$3
    local desc=$4
    local subtitle=$5
    
    echo ""
    echo "=============================================="
    echo "🎬 $name"
    echo "   $desc (${duration}s desde ${start}s)"
    echo "=============================================="
    
    local final_output="$OUTPUT/${name}.mp4"
    
    # Verificar si ya existe
    if [ -f "$final_output" ]; then
        existing_res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$final_output" 2>/dev/null)
        if [ "$existing_res" = "1080x1920" ]; then
            echo "    ⏭️  Ya existe con calidad correcta, saltando"
            return 0
        else
            echo "    🔄 Existe pero calidad incorrecta, regenerando"
            rm -f "$final_output"
        fi
    fi
    
    # Paso 1: Extraer
    if ! extract_segment_quality "$name" "$start" "$duration"; then
        return 1
    fi
    
    # Paso 2: Reframe
    if ! reframe_quality "$TEMP/${name}_raw.mp4" "$TEMP/${name}_reframe.mp4"; then
        rm -f "$TEMP/${name}_"*.mp4
        return 1
    fi
    rm -f "$TEMP/${name}_raw.mp4"
    
    # Paso 3: Subtítulos
    if ! add_subtitles_quality "$TEMP/${name}_reframe.mp4" "$TEMP/${name}_subs.mp4" "$subtitle"; then
        cp "$TEMP/${name}_reframe.mp4" "$TEMP/${name}_subs.mp4"
    fi
    rm -f "$TEMP/${name}_reframe.mp4"
    
    # Paso 4: Efectos virales
    if ! apply_viral_effects_quality "$TEMP/${name}_subs.mp4" "$final_output"; then
        mv "$TEMP/${name}_subs.mp4" "$final_output"
    fi
    rm -f "$TEMP/${name}_subs.mp4"
    
    # Verificación final exhaustiva
    if [ ! -f "$final_output" ]; then
        echo "    ❌ Archivo final no existe"
        return 1
    fi
    
    final_width=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=noprint_wrappers=1:nokey=1 "$final_output" 2>/dev/null)
    final_height=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=noprint_wrappers=1:nokey=1 "$final_output" 2>/dev/null)
    final_duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$final_output" 2>/dev/null | cut -d. -f1)
    final_size=$(du -h "$final_output" | cut -f1)
    has_audio=$(ffprobe -v error -select_streams a -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 "$final_output" 2>/dev/null | wc -l)
    
    echo ""
    echo "    ✅ COMPLETADO - Verificación final:"
    echo "       └─ Resolución: ${final_width}x${final_height} (esperado 1080x1920)"
    echo "       └─ Duración: ${final_duration}s"
    echo "       └─ Tamaño: $final_size"
    echo "       └─ Audio: $([ $has_audio -gt 0 ] && echo 'SÍ' || echo 'NO')"
    
    if [ "$final_width" -ne 1080 ] || [ "$final_height" -ne 1920 ]; then
        echo "    ❌ ERROR: Resolución incorrecta!"
        rm -f "$final_output"
        return 1
    fi
    
    return 0
}

# ============================================
# PROCESAR SHORTS
# ============================================

SHORTS=(
    "viral_hook:0:15:Hook inicial viral:👉 ¡MIRA ESTO!"
    "viral_value:30:25:Valor e insight:💡 EL SECRETO"
    "viral_proof:60:25:Prueba social:🔥 RESULTADO REAL"
    "viral_cta:90:35:CTA final:⚡ HAZLO AHORA"
)

generated=0
total=${#SHORTS[@]}
start_time=$(date +%s)

echo ""
echo "🎬 INICIANDO GENERACIÓN DE $total SHORTS"
echo "   Estimado: 2-3 min por short = $((total * 2))-$((total * 3)) minutos"
echo ""

for config in "${SHORTS[@]}"; do
    IFS=':' read -r name start duration desc subtitle <<< "$config"
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Procesando: $((generated+1))/$total"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if process_short_quality "$name" "$start" "$duration" "$desc" "$subtitle"; then
        ((generated++))
    else
        echo ""
        echo "    ❌ $name FALLÓ - continuando con siguiente"
    fi
done

# Limpieza
rm -rf "$TEMP"

# ============================================
# RESUMEN FINAL
# ============================================

end_time=$(date +%s)
elapsed=$((end_time - start_time))
elapsed_min=$((elapsed / 60))
elapsed_sec=$((elapsed % 60))

echo ""
echo "=============================================="
echo "📊 RESUMEN FINAL - CALIDAD PROFESIONAL"
echo "=============================================="
echo ""
echo "⏱️  Tiempo total: ${elapsed_min}m ${elapsed_sec}s"
echo "📹 Shorts generados: $generated/$total"
echo ""

all_good=true
for file in "$OUTPUT"/viral_*.mp4; do
    if [ -f "$file" ]; then
        name=$(basename "$file")
        res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$file" 2>/dev/null)
        size=$(du -h "$file" | cut -f1)
        duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null | cut -d. -f1)
        
        status="✅"
        if [ "$res" != "1080x1920" ]; then
            status="❌"
            all_good=false
        fi
        
        echo "$status $name"
        echo "   └─ ${res}, ${duration}s, $size"
    fi
done

echo ""
if [ $generated -eq $total ] && [ "$all_good" = true ]; then
    echo "🎉 ¡ÉXITO! $generated shorts en CALIDAD PROFESIONAL 1080x1920"
    echo "📁 $OUTPUT"
    exit 0
else
    echo "⚠️  Generados: $generated/$total"
    [ "$all_good" = false ] && echo "    Algunos tienen resolución incorrecta"
    exit 1
fi
