#!/bin/bash
# Ejecutar pipeline del backend con el video que ya tenemos

PYTHON_BIN="$HOME/CascadeProjects/ViraClip/backend/.venv/bin/python3"
BACKEND_DIR="$HOME/CascadeProjects/ViraClip/backend"
ENV_FILE="$HOME/CascadeProjects/ViraClip/.env"
VIDEO="$HOME/proyectos/ViraClip/uploads/seguro_3wgwaxIfUJQ.mp4"
LOG="/tmp/pipeline_run.log"

cd "$BACKEND_DIR"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 1 — Verificar config del backend"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$PYTHON_BIN" << 'PYEOF' 2>&1
import sys, os
sys.path.insert(0, 'src')

# Cargar .env
env_file = os.path.expanduser('~/CascadeProjects/ViraClip/.env')
for line in open(env_file):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v.strip().strip('"').strip("'")

# Intentar varias rutas de config
loaded = False
for mod_path in ['src.config', 'config', 'src.core.config', 'core.config']:
    try:
        mod = __import__(mod_path, fromlist=['Config', 'settings', 'get_settings'])
        for name in ['Config', 'settings', 'get_settings']:
            if hasattr(mod, name):
                obj = getattr(mod, name)
                if callable(obj):
                    try:
                        c = obj()
                    except Exception:
                        continue
                else:
                    c = obj
                print(f"Config cargada desde: {mod_path}.{name}")
                # Dump de atributos relevantes
                interesting = ['llm', 'LLM', 'groq_api_key', 'GROQ_API_KEY',
                               'comfyui_url', 'COMFYUI_URL', 'comfyui_host', 'COMFYUI_HOST',
                               'output_dir', 'OUTPUT_DIR', 'upload_dir', 'UPLOAD_DIR',
                               'temp_dir', 'TEMP_DIR']
                for attr in interesting:
                    if hasattr(c, attr):
                        val = getattr(c, attr)
                        if 'key' in attr.lower() or 'secret' in attr.lower():
                            val = f"***{len(str(val))} chars***" if val else "vacía"
                        print(f"  {attr:20s} = {val}")
                loaded = True
                break
        if loaded:
            break
    except ImportError:
        continue
    except Exception as e:
        print(f"  ⚠️ Error probando {mod_path}: {type(e).__name__}: {e}")

if not loaded:
    print("❌ No se encontró módulo de configuración")
    print("Buscando archivos de config...")
    for root, dirs, files in os.walk('src'):
        for f in files:
            if 'config' in f.lower() and f.endswith('.py'):
                print(f"  {root}/{f}")
PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 2 — Inventario de código del backend"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "2.1 ¿Existe viraclip_pipeline.py?"
find "$BACKEND_DIR" -maxdepth 3 -name "viraclip_pipeline.py" -o -name "pipeline.py" -o -name "main.py" 2>/dev/null | head -10
echo ""

echo "2.2 Archivos que llaman a ComfyUI:"
grep -rl "object_info\|/prompt\|VHS_LoadVideo\|comfyui" "$BACKEND_DIR/src/" --include="*.py" 2>/dev/null | head -10
echo ""

echo "2.3 Posibles entrypoints CLI:"
find "$BACKEND_DIR" -maxdepth 2 -name "*.py" -exec grep -l "if __name__" {} \; 2>/dev/null | head -10
echo ""

echo "2.4 Scripts en backend/scripts/:"
ls -la "$BACKEND_DIR/scripts/" 2>/dev/null | head -20
echo ""

echo "2.5 Servicios principales (task_service, comfyui_integration):"
for f in task_service.py comfyui_integration.py; do
    fp=$(find "$BACKEND_DIR/src" -name "$f" 2>/dev/null | head -1)
    if [ -n "$fp" ]; then
        echo "   ${fp}:"
        head -30 "$fp" | sed 's/^/      /'
        echo ""
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 3 — Ejecutar pipeline (intentos)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -f "$VIDEO" ]; then
    echo "❌ Video no existe: $VIDEO"
    exit 1
fi

> "$LOG"

# Intento 1: viraclip_pipeline.py
PIPELINE_SCRIPT="$BACKEND_DIR/viraclip_pipeline.py"
if [ -f "$PIPELINE_SCRIPT" ]; then
    echo "▶ Intento 1: python3 viraclip_pipeline.py $VIDEO"
    "$PYTHON_BIN" "$PIPELINE_SCRIPT" "$VIDEO" 2>&1 | tee "$LOG" | tail -80
    EXIT_CODE=$?
    echo ""
    echo "Exit code: $EXIT_CODE"
else
    echo "❌ No existe $PIPELINE_SCRIPT"
    echo ""
    echo "Buscando script similar:"
    find "$BACKEND_DIR" -maxdepth 2 -name "*pipeline*" -o -name "*run*" -o -name "*cli*" 2>/dev/null | head -5
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 4 — Errores del log (si los hay)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ -f "$LOG" ] && [ -s "$LOG" ]; then
    echo "Últimas líneas con 'error|traceback|failed|exception':"
    grep -niE "error|traceback|failed|exception|missing" "$LOG" | head -30
    echo ""
    echo "Log completo en: $LOG ($(wc -l < "$LOG") líneas)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 5 — ¿Apareció algún MP4 nuevo?"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "MP4 en ~/proyectos/ViraClip/outputs/ (ordenados por modificación):"
ls -laht ~/proyectos/ViraClip/outputs/*.mp4 2>/dev/null | head -10
echo ""

echo "MP4 en backend/exports/clips/:"
ls -laht ~/CascadeProjects/ViraClip/exports/clips/*.mp4 2>/dev/null | head -10
find ~/CascadeProjects/ViraClip/backend/exports -name "*.mp4" -mmin -5 -ls 2>/dev/null | head -10
echo ""

echo "MP4 modificados en los últimos 5 minutos en todo el proyecto:"
find ~/CascadeProjects/ViraClip ~/proyectos/ViraClip -name "*.mp4" -mmin -5 -not -path "*/.git/*" -ls 2>/dev/null | head -20
