#!/bin/bash
# Ejecutar todos los pasos con evidencia física

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 1 — Test VHS con fix (audio index=2, custom_width/height)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
python3 /tmp/test_vhs_fixed.py
step1_exit=$?
echo ""
echo "Exit code Paso 1: $step1_exit"
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 2 — Verificar MP4 físico"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Búsqueda en host:"
find ~/CascadeProjects/ViraClip/outputs/ \
     ~/proyectos/ViraClip/outputs/ \
     -name "test_fixed*" -ls 2>/dev/null
echo ""

echo "Búsqueda dentro del contenedor:"
docker exec viraclip-comfyui find /comfyui/output/ -name "test_fixed*" -ls 2>/dev/null
echo ""

# Validación: archivo > 500KB
test_file=$(find ~/proyectos/ViraClip/outputs/ -name "test_fixed*.mp4" 2>/dev/null | head -1)
if [ -z "$test_file" ]; then
    test_file=$(find ~/CascadeProjects/ViraClip/outputs/ -name "test_fixed*.mp4" 2>/dev/null | head -1)
fi

if [ -n "$test_file" ] && [ -f "$test_file" ]; then
    size_bytes=$(stat -c%s "$test_file")
    size_kb=$((size_bytes / 1024))
    echo "📁 Archivo encontrado: $test_file"
    echo "📊 Tamaño: $size_kb KB"
    if [ "$size_kb" -gt 500 ]; then
        echo "✅ PASO 2 OK: MP4 > 500KB generado correctamente por VHS"
    else
        echo "❌ PASO 2 FALLÓ: MP4 demasiado pequeño ($size_kb KB)"
    fi
else
    echo "❌ PASO 2 FALLÓ: No se encontró archivo test_fixed*.mp4 en ninguna ubicación"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 3 — Inventario REAL de assets (>0 bytes)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "=== MÚSICA REAL (>0 bytes) ==="
find ~/CascadeProjects/ViraClip/backend/music/bgm/ -name "*.mp3" -size +0c -ls 2>/dev/null
echo ""

echo "=== BROLL REAL (>0 bytes) ==="
find ~/proyectos/ViraClip/assets/broll/ -name "*.mp4" -size +0c -ls 2>/dev/null
echo ""
find ~/CascadeProjects/ViraClip/ -name "*.mp4" -size +0c \
     -not -path "*/outputs/*" \
     -not -path "*/.git/*" \
     -not -path "*/.venv/*" -ls 2>/dev/null
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 4 — Copiar música real a assets/music/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Copiar música real
cp ~/CascadeProjects/ViraClip/backend/music/bgm/bgm_energetic_hype.mp3 \
   ~/proyectos/ViraClip/assets/music/upbeat/upbeat1.mp3 && echo "  ✅ upbeat1.mp3 copiado"

cp ~/CascadeProjects/ViraClip/backend/music/bgm/bgm_upbeat_positive.mp3 \
   ~/proyectos/ViraClip/assets/music/upbeat/upbeat2.mp3 && echo "  ✅ upbeat2.mp3 copiado"

cp ~/CascadeProjects/ViraClip/backend/music/bgm/bgm_cinematic_ambient.mp3 \
   ~/proyectos/ViraClip/assets/music/calm/calm1.mp3 && echo "  ✅ calm1.mp3 copiado"

cp ~/CascadeProjects/ViraClip/backend/music/bgm/bgm_dramatic_tension.mp3 \
   ~/proyectos/ViraClip/assets/music/epic/epic1.mp3 && echo "  ✅ epic1.mp3 copiado"

# Añadir dramatic también
cp ~/CascadeProjects/ViraClip/backend/music/bgm/bgm_dramatic_tension.mp3 \
   ~/proyectos/ViraClip/assets/music/dramatic/dramatic1.mp3 && echo "  ✅ dramatic1.mp3 copiado"

echo ""
echo "=== Verificación tamaños música (no 0 bytes): ==="
echo ""
echo "upbeat/:"
ls -lh ~/proyectos/ViraClip/assets/music/upbeat/
echo ""
echo "calm/:"
ls -lh ~/proyectos/ViraClip/assets/music/calm/
echo ""
echo "epic/:"
ls -lh ~/proyectos/ViraClip/assets/music/epic/
echo ""
echo "dramatic/:"
ls -lh ~/proyectos/ViraClip/assets/music/dramatic/
echo ""

# Limpiar B-roll vacíos
echo ""
echo "=== Limpiando B-roll placeholders (0 bytes) ==="
deleted=$(find ~/proyectos/ViraClip/assets/broll/ -name "*.mp4" -size 0 -delete -print | wc -l)
echo "  Eliminados: $deleted archivos de 0 bytes"
echo ""
echo "B-roll reales restantes:"
find ~/proyectos/ViraClip/assets/broll/ -name "*.mp4" -size +0c -ls
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "RESUMEN FINAL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "A. VHS_LoadVideo responde: SÍ (verificado en bloque anterior)"

if [ -n "$test_file" ] && [ -f "$test_file" ]; then
    size_kb=$(($(stat -c%s "$test_file") / 1024))
    if [ "$size_kb" -gt 500 ]; then
        echo "B. VHS genera MP4 real: SÍ ($size_kb KB en $test_file)"
    else
        echo "B. VHS genera MP4 real: FALLÓ (solo $size_kb KB)"
    fi
else
    echo "B. VHS genera MP4 real: NO"
fi

music_count=$(find ~/proyectos/ViraClip/assets/music -name "*.mp3" -size +0c 2>/dev/null | wc -l)
broll_count=$(find ~/proyectos/ViraClip/assets/broll -name "*.mp4" -size +0c 2>/dev/null | wc -l)
bgm_count=$(find ~/CascadeProjects/ViraClip/backend/music/bgm -name "*.mp3" -size +0c 2>/dev/null | wc -l)

echo "C. Música con tamaño real en assets/music: $music_count archivos"
echo "D. B-roll con tamaño real en assets/broll: $broll_count archivos"
echo "E. Música BGM en backend/music/bgm: $bgm_count archivos"
