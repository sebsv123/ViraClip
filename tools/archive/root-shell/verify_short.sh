#!/bin/bash
# Verificar calidad del short generado

OUTPUT="/home/_sebastian/proyectos/ViraClip/outputs/instagram_ready"

echo "=============================================="
echo "VERIFICACIÓN DE CALIDAD DEL SHORT"
echo "=============================================="

if [ ! -f "$OUTPUT/viral_hook.mp4" ]; then
    echo "❌ No se encontró viral_hook.mp4"
    exit 1
fi

echo ""
echo "[INFO] Archivo: viral_hook.mp4"
echo "[INFO] Ubicación: $OUTPUT/"

# Verificar duración
echo ""
echo "[1] Verificando duración..."
duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUTPUT/viral_hook.mp4" 2>/dev/null | cut -d. -f1)
echo "   Duración: ${duration}s (esperado: ~15s)"

if [ "$duration" -lt 10 ] || [ "$duration" -gt 20 ]; then
    echo "   ⚠️  Duración inesperada!"
fi

# Verificar resolución
echo ""
echo "[2] Verificando resolución..."
resolution=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$OUTPUT/viral_hook.mp4" 2>/dev/null)
echo "   Resolución: $resolution (esperado: 1080x1920)"

if [ "$resolution" != "1080x1920" ]; then
    echo "   ⚠️  Resolución incorrecta!"
fi

# Verificar audio
echo ""
echo "[3] Verificando audio..."
audio_streams=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$OUTPUT/viral_hook.mp4" 2>/dev/null | wc -l)
if [ "$audio_streams" -gt 0 ]; then
    echo "   ✅ Audio presente ($audio_streams stream(s))"
else
    echo "   ❌ SIN AUDIO!"
fi

# Verificar bitrate
echo ""
echo "[4] Verificando bitrate..."
bitrate=$(ffprobe -v error -show_entries format=bit_rate -of default=noprint_wrappers=1:nokey=1 "$OUTPUT/viral_hook.mp4" 2>/dev/null)
bitrate_mbps=$(echo "scale=2; $bitrate / 1000000" | bc 2>/dev/null || echo "N/A")
echo "   Bitrate: ${bitrate_mbps} Mbps"

# Verificar tamaño
echo ""
echo "[5] Verificando tamaño..."
size=$(du -h "$OUTPUT/viral_hook.mp4" | cut -f1)
echo "   Tamaño: $size"

# Extraer frame para verificar subtítulos
echo ""
echo "[6] Verificando subtítulos (extrayendo frame)..."
ffmpeg -y -i "$OUTPUT/viral_hook.mp4" -ss 2 -vframes 1 -q:v 2 "/tmp/viral_hook_frame.jpg" 2>/dev/null
if [ -f "/tmp/viral_hook_frame.jpg" ]; then
    echo "   ✅ Frame extraído: /tmp/viral_hook_frame.jpg"
    echo "   Ábrelo para verificar si hay texto overlay"
else
    echo "   ⚠️  No se pudo extraer frame"
fi

echo ""
echo "=============================================="
echo "RESUMEN DE VERIFICACIÓN"
echo "=============================================="
echo ""
echo "Para verificar que los efectos se aplicaron:"
echo "1. Reproduce el video: mpv $OUTPUT/viral_hook.mp4"
echo "2. Verifica el audio: ¿Se escucha?"
echo "3. Verifica resolución: ¿Es 9:16 vertical?"
echo "4. Abre el frame: xdg-open /tmp/viral_hook_frame.jpg"
echo ""
echo "Si algo falló, revisa el log: /tmp/viral_generation.log"
