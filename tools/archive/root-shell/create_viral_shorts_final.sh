#!/bin/bash
# ViraClip - Shorts Virales COMPLETOS (Versión Final Arreglada)
# Whisper + B-roll + Música funcionando

VIRA_ROOT="/home/_sebastian/proyectos/ViraClip"
VIDEO="$VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4"
OUTPUT="$VIRA_ROOT/outputs/instagram_ready"
ASSETS="$VIRA_ROOT/assets"
TEMP="$OUTPUT/.temp_$$"

mkdir -p "$TEMP"

echo "=============================================="
echo "VIRACLIP - SHORTS VIRALES (Versión Final)"
echo "=============================================="

# Verificar prerequisitos
if [ ! -f "$VIDEO" ]; then
    echo "❌ Video no encontrado"
    exit 1
fi

# ============================================
# FUNCIONES
# ============================================

# 1. Transcripción Whisper (ARREGLADO - copiar audio a contenedor)
transcribe_whisper_fixed() {
    local input_video=$1
    local output_srt=$2
    
    echo ""
    echo "[1] TRANSCRIPCIÓN Whisper..."
    
    # Extraer audio WAV
    ffmpeg -y -i "$input_video" -ar 16000 -ac 1 -c:a pcm_s16le "$TEMP/audio.wav" 2>/dev/null
    
    if [ ! -f "$TEMP/audio.wav" ]; then
        echo "    ❌ Extracción de audio falló"
        return 1
    fi
    
    # COPIAR a contenedor ComfyUI (FIX)
    docker exec viraclip-comfyui mkdir -p /comfyui/temp
    docker cp "$TEMP/audio.wav" viraclip-comfyui:/comfyui/temp/audio.wav
    
    # Transcribir dentro del contenedor
    docker exec viraclip-comfyui python3 << 'PYTHON_EOF'
import whisper
import sys

try:
    model = whisper.load_model('base')
    result = model.transcribe('/comfyui/temp/audio.wav', language='es', task='transcribe')
    
    segments = result['segments']
    with open('/comfyui/temp/transcription.srt', 'w') as f:
        for i, seg in enumerate(segments):
            start = seg['start']
            end = seg['end']
            text = seg['text'].strip()
            
            # Formato SRT
            def to_srt_time(t):
                h = int(t // 3600)
                m = int((t % 3600) // 60)
                s = int(t % 60)
                ms = int((t % 1) * 1000)
                return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
            
            f.write(f'{i+1}\n')
            f.write(f'{to_srt_time(start)} --> {to_srt_time(end)}\n')
            f.write(f'{text}\n\n')
    
    print(f'Transcripción exitosa: {len(segments)} segmentos')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
PYTHON_EOF
    
    # Copiar resultado de vuelta
    if docker exec viraclip-comfyui test -f /comfyui/temp/transcription.srt; then
        docker cp viraclip-comfyui:/comfyui/temp/transcription.srt "$output_srt"
        segs=$(grep -c "^$" "$output_srt" 2>/dev/null || echo "0")
        echo "    ✅ Transcripción: $segs líneas"
        return 0
    else
        echo "    ⚠️  Transcripción falló"
        return 1
    fi
}

# 2. Reframe 9:16 con calidad
reframe_quality() {
    local input=$1
    local output=$2
    
    echo ""
    echo "[2] REFRAME 9:16..."
    
    ffmpeg -y -i "$input" -vf "
        crop=ih*9/16:ih:(iw-ih*9/16)/2:0,
        scale=1080:1920:flags=lanczos,
        unsharp=3:3:0.5:3:3:0.5,
        fps=30
    " -c:v libx264 -preset slow -crf 18 \
      -pix_fmt yuv420p \
      -c:a aac -b:a 192k \
      -movflags +faststart \
      "$output" 2>&1 | grep -E "(frame|size)" | tail -2
    
    if [ -f "$output" ]; then
        res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$output" 2>/dev/null)
        if [ "$res" = "1080x1920" ]; then
            echo "    ✅ Reframe: 1080x1920"
            return 0
        fi
    fi
    return 1
}

# 3. Insertar B-roll (SIMPLIFICADO)
insert_broll_fixed() {
    local input=$1
    local output=$2
    local keyword=$3
    
    echo ""
    echo "[3] B-ROLL: $keyword..."
    
    # Buscar clip B-roll
    broll_clip=$(find "$ASSETS/broll" -name "*.mp4" | shuf | head -1)
    
    if [ -z "$broll_clip" ]; then
        echo "    ⚠️  No hay B-roll, usando original"
        cp "$input" "$output"
        return 0
    fi
    
    # Método simple: fade in/out con B-roll en el medio
    duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$input" 2>/dev/null | cut -d. -f1)
    
    if [ "$duration" -lt 10 ]; then
        # Video corto, no insertar B-roll
        cp "$input" "$output"
        echo "    ℹ️  Video corto, sin B-roll"
        return 0
    fi
    
    # Crear versión con B-roll: inicio -> B-roll -> final
    # Usar fade simple
    ffmpeg -y -i "$input" -i "$broll_clip" -filter_complex "
        [0:v]split[main1][main2];
        [main1]trim=0:2,fade=t=out:st=1.5:d=0.5[part1];
        [1:v]trim=0:3,scale=1080:1920,fade=t=in:st=0:d=0.5,fade=t=out:st=2.5:d=0.5[brollv];
        [main2]trim=2:$duration,fade=t=in:st=0:d=0.5[part2];
        [part1][brollv][part2]concat=n=3:v=1:a=0[video];
        [0:a]asplit[main_a1][main_a2];
        [main_a1]atrim=0:2,afade=t=out:st=1.5:d=0.5[audio1];
        [main_a2]atrim=2:$duration,afade=t=in:st=0:d=0.5[audio2];
        [audio1][audio2]concat=n=2:v=0:a=1[audio]
    " -map "[video]" -map "[audio]" \
      -c:v libx264 -preset slow -crf 18 \
      -c:a aac -b:a 192k \
      "$output" 2>&1 | grep -E "(frame|size)" | tail -2 || cp "$input" "$output"
    
    if [ -f "$output" ]; then
        echo "    ✅ B-roll insertado: $(basename "$broll_clip")"
        return 0
    else
        cp "$input" "$output"
        echo "    ⚠️  B-roll falló, usando original"
        return 0
    fi
}

# 4. Añadir música
add_music_fixed() {
    local input=$1
    local output=$2
    local mood=$3
    
    echo ""
    echo "[4] MÚSICA: $mood..."
    
    # Buscar música
    music_file=$(find "$ASSETS/music/$mood" -name "*.mp3" -o -name "*.wav" 2>/dev/null | shuf | head -1)
    
    if [ -z "$music_file" ]; then
        # Buscar en cualquier subdirectorio
        music_file=$(find "$ASSETS/music" -name "*.mp3" 2>/dev/null | shuf | head -1)
    fi
    
    if [ -z "$music_file" ]; then
        echo "    ⚠️  No hay música disponible"
        cp "$input" "$output"
        return 0
    fi
    
    # Mezclar
    duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$input" 2>/dev/null)
    
    ffmpeg -y -i "$input" -i "$music_file" -filter_complex "
        [1:a]aloop=loop=-1:size=2e+09,atrim=0:$duration,volume=0.2[music];
        [0:a][music]amix=inputs=2:duration=first:dropout_transition=2[outa]
    " -map 0:v -map "[outa]" \
      -c:v copy -c:a aac -b:a 192k \
      "$output" 2>&1 | grep -E "(size)" | tail -1 || cp "$input" "$output"
    
    if [ -f "$output" ]; then
        echo "    ✅ Música añadida: $(basename "$music_file")"
        return 0
    else
        cp "$input" "$output"
        return 0
    fi
}

# 5. Render final con subtítulos
render_final() {
    local input=$1
    local srt=$2
    local output=$3
    local title=$4
    
    echo ""
    echo "[5] RENDER FINAL..."
    
    if [ -f "$srt" ] && [ -s "$srt" ]; then
        # Subtítulos reales
        ffmpeg -y -i "$input" -vf "
            subtitles='$srt':force_style='FontSize=36,FontName=Arial Bold,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&,OutlineThickness=3,ShadowColour=&H80000000&,ShadowDepth=2,Alignment=2,MarginV=80'
        " -c:v libx264 -preset slow -crf 18 \
          -c:a aac -b:a 192k -movflags +faststart \
          "$output" 2>&1 | grep -E "(frame|size)" | tail -2
    else
        # Placeholder
        ffmpeg -y -i "$input" -vf "
            drawtext=text='$title':fontsize=48:fontcolor=white:x=(w-text_w)/2:y=100:
                shadowcolor=black@0.9:shadowx=4:shadowy=4:
                borderw=3:bordercolor=black@0.8,
            format=yuv420p
        " -c:v libx264 -preset slow -crf 18 \
          -c:a aac -b:a 192k -movflags +faststart \
          "$output" 2>&1 | grep -E "(frame|size)" | tail -2
    fi
    
    if [ -f "$output" ]; then
        res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$output" 2>/dev/null)
        dur=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$output" 2>/dev/null | cut -d. -f1)
        audio=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$output" 2>/dev/null | wc -l)
        echo "    ✅ Render: $res, ${dur}s, Audio: $([ $audio -gt 0 ] && echo 'SÍ' || echo 'NO')"
        return 0
    fi
    return 1
}

# ============================================
# PROCESAR SHORT
# ============================================
process_short() {
    local name=$1
    local start=$2
    local duration=$3
    local desc=$4
    local keyword=$5
    local mood=$6
    local title=$7
    
    echo ""
    echo "=============================================="
    echo "🎬 $name - $desc"
    echo "=============================================="
    
    local final="$OUTPUT/${name}.mp4"
    local current="$TEMP/${name}_step0.mp4"
    
    # 0: Extraer
    echo ""
    echo "[0] EXTRACCIÓN..."
    ffmpeg -y -ss "$start" -i "$VIDEO" -t "$duration" \
        -c:v libx264 -preset medium -crf 20 -c:a aac -b:a 192k -r 30 \
        -movflags +faststart "$current" 2>&1 | tail -3
    
    # 1: Transcripción
    transcribe_whisper_fixed "$current" "$TEMP/${name}.srt" || true
    
    # 2: Reframe
    reframe_quality "$current" "$TEMP/${name}_step2.mp4" && current="$TEMP/${name}_step2.mp4"
    
    # 3: B-roll
    insert_broll_fixed "$current" "$TEMP/${name}_step3.mp4" "$keyword" && current="$TEMP/${name}_step3.mp4"
    
    # 4: Música
    add_music_fixed "$current" "$TEMP/${name}_step4.mp4" "$mood" && current="$TEMP/${name}_step4.mp4"
    
    # 5: Render final
    if render_final "$current" "$TEMP/${name}.srt" "$final" "$title"; then
        rm -f "$TEMP/${name}"*
        size=$(du -h "$final" | cut -f1)
        echo ""
        echo "✅ $name COMPLETADO: $size"
        return 0
    else
        echo "❌ $name falló"
        return 1
    fi
}

# ============================================
# 4 SHORTS
# ============================================
SHORTS=(
    "viral_hook:0:15:Hook viral:success:upbeat:👉 ¡ATENCIÓN!"
    "viral_value:30:25:Valor/Insight:idea:calm:💡 EL SECRETO"
    "viral_proof:60:25:Prueba Social:achievement:epic:🔥 RESULTADO"
    "viral_cta:90:35:CTA Final:action:dramatic:⚡ ACTÚA AHORA"
)

generated=0
total=${#SHORTS[@]}

echo ""
echo "🎬 GENERANDO $total SHORTS..."
echo ""

for cfg in "${SHORTS[@]}"; do
    IFS=':' read -r name start duration desc keyword mood title <<< "$cfg"
    echo ""
    echo "🚀 $((generated+1))/$total: $name"
    
    if process_short "$name" "$start" "$duration" "$desc" "$keyword" "$mood" "$title"; then
        ((generated++))
    fi
done

# Limpiar
rm -rf "$TEMP"

# ============================================
# RESUMEN
# ============================================
echo ""
echo "=============================================="
echo "📊 RESUMEN FINAL"
echo "=============================================="
echo ""
echo "Generados: $generated/$total"
echo ""

for f in "$OUTPUT"/viral_*.mp4; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$f" 2>/dev/null)
    size=$(du -h "$f" | cut -f1)
    echo "📹 $name - $res - $size"
done

echo ""
[ $generated -eq $total ] && echo "🎉 ÉXITO!" || echo "⚠️  $generated/$total generados"
