#!/bin/bash
# Verificación exhaustiva de las 3 fases pendientes del pipeline ViraClip

PHASE1_STATUS="❌"
PHASE2_STATUS="❌"
PHASE3_STATUS="❌"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "FASE 1 — yt-dlp"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "1.1 Ubicación binario:"
which yt-dlp 2>/dev/null || echo "(no en PATH global)"
echo ""

echo "1.2 Versión pip yt-dlp:"
pip show yt-dlp 2>/dev/null | head -5 || echo "(no instalado con pip del host)"
echo ""

echo "1.3 ¿Está en el backend (.venv)?"
if [ -f ~/CascadeProjects/ViraClip/backend/.venv/bin/yt-dlp ]; then
    ~/CascadeProjects/ViraClip/backend/.venv/bin/yt-dlp --version
    YTDLP_BIN="$HOME/CascadeProjects/ViraClip/backend/.venv/bin/yt-dlp"
else
    YTDLP_BIN=$(which yt-dlp 2>/dev/null)
fi
echo "   Binario a usar: ${YTDLP_BIN:-(ninguno)}"
echo ""

if [ -n "$YTDLP_BIN" ] && [ -x "$YTDLP_BIN" ]; then
    echo "1.4 Descargando audio de test (video corto de 19s)..."
    rm -f /tmp/test_ytdlp.mp3
    "$YTDLP_BIN" --no-playlist \
           --extract-audio \
           --audio-format mp3 \
           --no-warnings \
           --quiet \
           --output "/tmp/test_ytdlp.%(ext)s" \
           "https://www.youtube.com/watch?v=jNQXAC9IVRw" 2>&1 | tail -10
    
    if [ -f /tmp/test_ytdlp.mp3 ]; then
        size=$(du -h /tmp/test_ytdlp.mp3 | cut -f1)
        echo "   ✅ Descargado: /tmp/test_ytdlp.mp3 ($size)"
        PHASE1_STATUS="✅"
    else
        echo "   ❌ Descarga falló"
    fi
else
    echo "   ❌ yt-dlp no disponible"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "FASE 2 — faster-whisper"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Detectar qué python usar
PYTHON_BIN=""
if [ -f ~/CascadeProjects/ViraClip/backend/.venv/bin/python ]; then
    PYTHON_BIN="$HOME/CascadeProjects/ViraClip/backend/.venv/bin/python"
    echo "Usando python del backend: $PYTHON_BIN"
else
    PYTHON_BIN="python3"
    echo "Usando python3 del sistema"
fi
echo ""

echo "2.1 ¿faster-whisper está instalado?"
"$PYTHON_BIN" -c "import faster_whisper; print(f'   ✅ Versión: {faster_whisper.__version__}')" 2>&1
echo ""

echo "2.2 Test de transcripción (modelo tiny, ~80MB)..."
"$PYTHON_BIN" << 'PYEOF' 2>&1
import os, sys

try:
    from faster_whisper import WhisperModel
except ImportError as e:
    print(f"   ❌ faster-whisper no instalado: {e}")
    sys.exit(1)

# Decidir audio de entrada
audio = '/tmp/test_ytdlp.mp3'
if not os.path.exists(audio):
    audio = os.path.expanduser('~/proyectos/ViraClip/uploads/seguro_3wgwaxIfUJQ.mp4')

if not os.path.exists(audio):
    print(f"   ❌ No hay audio para transcribir")
    sys.exit(1)

print(f"   Audio: {audio}")
print(f"   Cargando modelo tiny (int8, CPU)...")

try:
    model = WhisperModel('tiny', device='cpu', compute_type='int8')
    print(f"   Transcribiendo...")
    segments, info = model.transcribe(audio, beam_size=1)
    segs = list(segments)
    print(f"   ✅ Whisper funciona")
    print(f"   Idioma detectado: {info.language} (prob: {info.language_probability:.2f})")
    print(f"   Segmentos: {len(segs)}")
    for s in segs[:3]:
        text = s.text.strip()[:80]
        print(f"     [{s.start:5.1f}s - {s.end:5.1f}s] {text}")
    print("__PHASE2_OK__")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then
    PHASE2_STATUS="✅"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "FASE 3 — Claude API (Anthropic)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "3.1 Buscando API keys en .env files..."
for env_file in \
    ~/CascadeProjects/ViraClip/.env \
    ~/CascadeProjects/ViraClip/backend/.env \
    ~/CascadeProjects/ViraClip/.env.example; do
    if [ -f "$env_file" ]; then
        echo "   [$env_file]:"
        grep -iE "ANTHROPIC|CLAUDE|OPENAI_API_KEY|GOOGLE_API_KEY|GROQ_API_KEY" "$env_file" 2>/dev/null \
          | sed 's/=.*/=***OCULTO***/' | sed 's/^/      /'
    fi
done
echo ""

echo "3.2 Test de llamada a Claude..."
"$PYTHON_BIN" << 'PYEOF' 2>&1
import os, sys

# Cargar .env manualmente
key = os.getenv('ANTHROPIC_API_KEY', '')
if not key:
    for env_file in [
        os.path.expanduser('~/CascadeProjects/ViraClip/.env'),
        os.path.expanduser('~/CascadeProjects/ViraClip/backend/.env'),
    ]:
        if os.path.exists(env_file):
            for line in open(env_file):
                line = line.strip()
                if line.startswith('ANTHROPIC_API_KEY'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        v = parts[1].strip().strip('"').strip("'")
                        if v and v != 'your_api_key_here':
                            key = v
                            break
            if key:
                break

if not key:
    print("   ❌ ANTHROPIC_API_KEY no configurada")
    sys.exit(1)

print(f"   Key encontrada: sk-...{key[-6:]}")

try:
    import anthropic
    print(f"   Librería anthropic: {anthropic.__version__}")
except ImportError as e:
    print(f"   ❌ anthropic no instalado: {e}")
    sys.exit(1)

try:
    client = anthropic.Anthropic(api_key=key)
    # Probar con modelo más común por si claude-sonnet-4-5 no está disponible
    for model_name in ['claude-sonnet-4-5', 'claude-3-5-sonnet-20241022', 'claude-3-haiku-20240307']:
        try:
            msg = client.messages.create(
                model=model_name,
                max_tokens=50,
                messages=[{'role': 'user', 'content': 'responde solo: ok'}]
            )
            print(f"   ✅ Modelo {model_name} responde: {msg.content[0].text.strip()}")
            print("__PHASE3_OK__")
            sys.exit(0)
        except anthropic.NotFoundError:
            continue
        except Exception as e:
            print(f"   ⚠️  {model_name}: {type(e).__name__}: {e}")
            continue
    print("   ❌ Ningún modelo Claude respondió")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ Error: {type(e).__name__}: {e}")
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then
    PHASE3_STATUS="✅"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "REPORTE FINAL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Fase 1 (yt-dlp):      $PHASE1_STATUS"
echo "Fase 2 (whisper):     $PHASE2_STATUS"
echo "Fase 3 (Claude API):  $PHASE3_STATUS"
echo "Fase 4 (ComfyUI):     ✅ (ya verificado con short_comfyui_00001-audio.mp4 1.55MB)"
echo ""
