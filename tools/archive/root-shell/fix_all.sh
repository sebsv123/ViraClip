#!/bin/bash
# Fix exhaustivo:
#   #1  Flux OOM → Flux GGUF Q4_K_S + componentes separados + custom node GGUF
#   #2  RealESRGAN_x2plus.pth faltante
#   #3  enhance_video.json: VHS_BatchManager.frames_per_batch + ruta absoluta

set -u  # no -e porque queremos ver todos los errores

COMFY_CUSTOM_NODES="$HOME/CascadeProjects/ViraClip/comfyui/custom_nodes"

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  FIX #1 — Flux Dev GGUF Q4_K_S + encoders separados (para 8GB VRAM)"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# 1.1 — Instalar ComfyUI-GGUF si no está
echo "─── 1.1 ComfyUI-GGUF custom node ───"
if [ -d "$COMFY_CUSTOM_NODES/ComfyUI-GGUF" ]; then
    echo "  ✅ Ya instalado en $COMFY_CUSTOM_NODES/ComfyUI-GGUF"
else
    echo "  ⏬ Clonando ComfyUI-GGUF..."
    git clone --depth 1 https://github.com/city96/ComfyUI-GGUF "$COMFY_CUSTOM_NODES/ComfyUI-GGUF"
fi

# 1.2 — Instalar dependencia python del nodo GGUF DENTRO del contenedor
echo ""
echo "─── 1.2 Instalando gguf pip package en el contenedor ───"
docker exec viraclip-comfyui pip install --no-cache-dir --quiet 'gguf>=0.13.0' 2>&1 | tail -5
echo "  ✅ pip install gguf completado"

# 1.3 — Descargar los 4 componentes de Flux GGUF
echo ""
echo "─── 1.3 Descargando modelos para Flux GGUF ───"
echo ""

download_in_container() {
    local url="$1"
    local dest="$2"
    local name="$3"
    echo "  ⏬ $name"
    docker exec viraclip-comfyui sh -c "
        mkdir -p \"\$(dirname '$dest')\" && 
        if [ -f '$dest' ] && [ \$(stat -c %s '$dest' 2>/dev/null || echo 0) -gt 1000000 ]; then
            echo '     ✅ ya existe: $(basename $dest)'
        else
            wget -c --tries=3 --timeout=60 -q --show-progress -O '$dest' '$url'
        fi
    "
}

# Flux Dev UNET GGUF Q4_K_S (6.5 GB) — cabe en 8GB VRAM
download_in_container \
    "https://huggingface.co/city96/FLUX.1-dev-gguf/resolve/main/flux1-dev-Q4_K_S.gguf" \
    "/comfyui/models/unet/flux1-dev-Q4_K_S.gguf" \
    "Flux Dev UNET Q4_K_S (6.5 GB)"

# T5-XXL fp8 (5 GB)
download_in_container \
    "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors" \
    "/comfyui/models/text_encoders/t5xxl_fp8_e4m3fn.safetensors" \
    "T5-XXL fp8 (5 GB)"

# CLIP-L (235 MB)
download_in_container \
    "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
    "/comfyui/models/text_encoders/clip_l.safetensors" \
    "CLIP-L (235 MB)"

# VAE (335 MB)
download_in_container \
    "https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" \
    "/comfyui/models/vae/ae.safetensors" \
    "Flux VAE (335 MB)"

echo ""
echo "─── 1.4 Verificando tamaños ───"
docker exec viraclip-comfyui sh -c '
    for f in \
        /comfyui/models/unet/flux1-dev-Q4_K_S.gguf \
        /comfyui/models/text_encoders/t5xxl_fp8_e4m3fn.safetensors \
        /comfyui/models/text_encoders/clip_l.safetensors \
        /comfyui/models/vae/ae.safetensors; do
        if [ -f "$f" ]; then
            ls -lh "$f" | awk "{print \"  ✅ \" \$5 \"\t\" \$9}"
        else
            echo "  ❌ FALTA: $f"
        fi
    done
'

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  FIX #2 — Descargar RealESRGAN_x2plus.pth"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

download_in_container \
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth" \
    "/comfyui/models/upscale_models/RealESRGAN_x2plus.pth" \
    "RealESRGAN_x2plus (67 MB)"

docker exec viraclip-comfyui ls -lh /comfyui/models/upscale_models/RealESRGAN_x2plus.pth 2>/dev/null

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  FIX #3 — Parchear enhance_video.json (VHS_BatchManager.frames_per_batch)"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# Buscar enhance_video.json en todo el proyecto
candidates=$(find "$HOME/CascadeProjects/ViraClip" -name "enhance_video.json" -not -path "*/node_modules/*" 2>/dev/null)
if [ -z "$candidates" ]; then
    echo "  ❌ No se encontró enhance_video.json. Ubicaciones comunes:"
    find "$HOME/CascadeProjects/ViraClip/backend" -name "*.json" -path "*workflow*" 2>/dev/null | head -20
else
    echo "  Archivos encontrados:"
    for wf in $candidates; do
        echo "    $wf"
    done
    echo ""
    for wf in $candidates; do
        python3 - "$wf" << 'PYEOF'
import json, sys
wf = sys.argv[1]
print(f"  ── Parcheando {wf} ──")
try:
    with open(wf) as f:
        w = json.load(f)
except Exception as e:
    print(f"    ❌ error leyendo: {e}")
    sys.exit(0)

changed = False
for node_id, node in w.items():
    if not isinstance(node, dict): continue
    ct = node.get("class_type", "")
    if ct == "VHS_BatchManager":
        inp = node.setdefault("inputs", {})
        if "frames_per_batch" not in inp:
            inp["frames_per_batch"] = 16
            print(f"    ✅ node {node_id} VHS_BatchManager.frames_per_batch = 16")
            changed = True
        else:
            print(f"    = node {node_id} VHS_BatchManager.frames_per_batch ya existe = {inp['frames_per_batch']}")

if changed:
    import shutil
    shutil.copy(wf, wf + ".bak")
    with open(wf, "w") as f:
        json.dump(w, f, indent=2)
    print(f"    💾 guardado (backup en {wf}.bak)")
else:
    print("    (sin cambios necesarios)")
PYEOF
    done
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  Reiniciando ComfyUI para que detecte los nuevos modelos + custom node"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
docker restart viraclip-comfyui
echo "  esperando 40 segundos..."
sleep 40

echo ""
echo "━━━ Estado post-restart ━━━"
curl -s -o /dev/null -w "  /system_stats HTTP: %{http_code}\n" http://localhost:8188/system_stats

echo ""
echo "━━━ ¿ComfyUI-GGUF cargó sus nodos? ━━━"
curl -s http://localhost:8188/object_info | python3 -c "
import json, sys
d = json.load(sys.stdin)
gguf_nodes = sorted([k for k in d if 'GGUF' in k or 'gguf' in k.lower()])
if gguf_nodes:
    print('  ✅ Nodos GGUF disponibles:')
    for n in gguf_nodes: print(f'     - {n}')
else:
    print('  ❌ No hay nodos GGUF — revisa logs de ComfyUI')
"

echo ""
echo "━━━ ¿Modelos Flux GGUF visibles? ━━━"
curl -s http://localhost:8188/object_info/UnetLoaderGGUF 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
info = d.get('UnetLoaderGGUF', {})
files = info.get('input', {}).get('required', {}).get('unet_name', [[]])[0]
if files:
    print(f'  UNETs GGUF disponibles: {files}')
else:
    print('  ❌ UnetLoaderGGUF no ve modelos')
" 2>/dev/null || echo "  (UnetLoaderGGUF no existe aún — ComfyUI-GGUF no se cargó bien)"

echo ""
echo "━━━ RealESRGAN detectado? ━━━"
curl -s http://localhost:8188/object_info/UpscaleModelLoader | python3 -c "
import json, sys
d = json.load(sys.stdin)
files = d.get('UpscaleModelLoader', {}).get('input', {}).get('required', {}).get('model_name', [[]])[0]
print(f'  Upscalers: {files}')
if 'RealESRGAN_x2plus.pth' in files:
    print('  ✅ RealESRGAN_x2plus.pth detectado')
else:
    print('  ❌ RealESRGAN_x2plus.pth NO detectado')
"

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  FIX TERMINADO. Próximo paso: actualizar brolls.py para usar GGUF"
echo "════════════════════════════════════════════════════════════════════════"
