#!/bin/bash
# Verificación exhaustiva con evidencia física

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "BLOQUE A — VERIFICAR VHS_LoadVideo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Output COMPLETO de: curl -s http://localhost:8188/object_info/VHS_LoadVideo"
echo "---"
curl -s http://localhost:8188/object_info/VHS_LoadVideo
echo ""
echo "---"
echo ""

# Verificar si VHS responde
vhs_response=$(curl -s http://localhost:8188/object_info/VHS_LoadVideo)
if [ "$vhs_response" = "{}" ] || echo "$vhs_response" | grep -q "error"; then
    echo "❌ BLOQUE A FALLÓ: VHS_LoadVideo NO responde correctamente"
    echo "DETENIDO aquí. No continúo."
    exit 1
fi

if ! echo "$vhs_response" | grep -q "input"; then
    echo "❌ BLOQUE A FALLÓ: Respuesta no contiene campos de input"
    echo "DETENIDO aquí. No continúo."
    exit 1
fi

echo "✅ BLOQUE A: VHS responde con JSON válido. Continuando..."

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "BLOQUE B — VERIFICAR VIDEO INPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Output COMPLETO de: docker exec viraclip-comfyui ls -lh /comfyui/input/"
echo "---"
docker exec viraclip-comfyui ls -lh /comfyui/input/
echo "---"
echo ""

# Verificar que el video existe
if ! docker exec viraclip-comfyui test -f /comfyui/input/seguro_3wgwaxIfUJQ.mp4; then
    echo "❌ BLOQUE B FALLÓ: seguro_3wgwaxIfUJQ.mp4 NO existe en /comfyui/input/"
    echo "DETENIDO aquí."
    exit 1
fi

echo "✅ BLOQUE B: Video existe. Continuando..."

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "BLOQUE C — TEST REAL CON VHS (150 frames)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Ejecutando: python3 /tmp/test_vhs_minimal.py"
echo "---"

# Marcar tiempo para el Bloque D
touch /tmp/test_vhs_minimal.py

python3 /tmp/test_vhs_minimal.py
vhs_exit_code=$?

echo "---"
echo "Exit code del script: $vhs_exit_code"
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "BLOQUE D — VERIFICAR ARCHIVO FÍSICO"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Buscando archivos .mp4 nuevos generados..."
echo ""

echo "1. En ~/CascadeProjects/ViraClip/outputs/:"
find ~/CascadeProjects/ViraClip/outputs/ -name "*.mp4" -newer /tmp/test_vhs_minimal.py -ls 2>/dev/null
echo ""

echo "2. En ~/proyectos/ViraClip/outputs/:"
find ~/proyectos/ViraClip/outputs/ -name "*.mp4" -newer /tmp/test_vhs_minimal.py -ls 2>/dev/null
echo ""

echo "3. En /comfyui/output dentro del contenedor:"
docker exec viraclip-comfyui find /comfyui/output -name "test_minimal*" -ls 2>/dev/null
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "BLOQUE E — INVENTARIO REAL DE ASSETS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "=== VIDEOS (mp4) - excluyendo outputs y .git ==="
find ~/CascadeProjects/ViraClip -name "*.mp4" -not -path "*/outputs/*" -not -path "*/.git/*" -ls 2>/dev/null
echo ""
find ~/proyectos/ViraClip -name "*.mp4" -not -path "*/outputs/*" -not -path "*/.git/*" -ls 2>/dev/null
echo ""

echo "=== MÚSICA (mp3/wav/ogg) ==="
find ~/CascadeProjects/ViraClip -name "*.mp3" -o -name "*.wav" -o -name "*.ogg" 2>/dev/null | head -20
echo ""
find ~/proyectos/ViraClip -name "*.mp3" -o -name "*.wav" -o -name "*.ogg" 2>/dev/null | head -20
echo ""

echo "=== UPLOADS ==="
echo "~/CascadeProjects/ViraClip/uploads/:"
ls -lh ~/CascadeProjects/ViraClip/uploads/ 2>/dev/null || echo "  (no existe)"
echo ""
echo "~/proyectos/ViraClip/uploads/:"
ls -lh ~/proyectos/ViraClip/uploads/ 2>/dev/null || echo "  (no existe)"
echo ""

echo "=== ASSETS B-ROLL ==="
ls -lhR ~/proyectos/ViraClip/assets/broll/ 2>/dev/null || echo "  (no existe)"
echo ""

echo "=== ASSETS MÚSICA ==="
ls -lhR ~/proyectos/ViraClip/assets/music/ 2>/dev/null || echo "  (no existe)"
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CRITERIOS DE ÉXITO"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Verificación final
echo "A. VHS responde: $(curl -s http://localhost:8188/object_info/VHS_LoadVideo | python3 -c "import sys,json; d=json.load(sys.stdin); print('SÍ' if 'VHS_LoadVideo' in d else 'NO')" 2>/dev/null)"

test_file=$(find ~/proyectos/ViraClip/outputs/ ~/CascadeProjects/ViraClip/outputs/ -name "test_minimal*.mp4" 2>/dev/null | head -1)
if [ -n "$test_file" ] && [ -f "$test_file" ]; then
    size=$(stat -c%s "$test_file" 2>/dev/null)
    size_kb=$((size / 1024))
    echo "B. Archivo test_minimal generado: SÍ ($size_kb KB en $test_file)"
    if [ "$size_kb" -gt 500 ]; then
        echo "   ✅ Tamaño > 500KB - VHS FUNCIONA EN PRODUCCIÓN"
    else
        echo "   ❌ Tamaño muy pequeño (<500KB)"
    fi
else
    echo "B. Archivo test_minimal generado: NO - VHS NO GENERA ARCHIVOS"
fi

broll_count=$(find ~/proyectos/ViraClip/assets/broll -name "*.mp4" 2>/dev/null | wc -l)
music_count=$(find ~/proyectos/ViraClip/assets/music -name "*.mp3" -o -name "*.wav" 2>/dev/null | wc -l)
echo "C. Assets disponibles: $broll_count B-roll clips, $music_count pistas música"
echo ""
