#!/bin/bash
# Verificación de LLMs disponibles: Groq, Ollama, OpenAI, Google

PYTHON_BIN="$HOME/CascadeProjects/ViraClip/backend/.venv/bin/python3"
ENV_FILE="$HOME/CascadeProjects/ViraClip/.env"

GROQ_STATUS="❌"
OLLAMA_STATUS="❌"
OPENAI_STATUS="❌"
GOOGLE_STATUS="❌"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 1 — Keys con valor real"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

grep -E "^(GROQ_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|OLLAMA)" "$ENV_FILE" 2>/dev/null | \
    awk -F'=' '{
        val = $2
        gsub(/^[[:space:]]*"?|"?[[:space:]]*$/, "", val)
        if (length(val) > 10 && val !~ /^your_/) print $1"=***TIENE_VALOR*** ("length(val)" chars)"
        else if (length(val) > 0) print $1"=PLACEHOLDER ("val")"
        else print $1"=VACÍA"
    }'
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 2 — Verificar Groq"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$PYTHON_BIN" << 'PYEOF' 2>&1
import os, sys

# Cargar .env
env_file = os.path.expanduser('~/CascadeProjects/ViraClip/.env')
for line in open(env_file):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v.strip().strip('"').strip("'")

key = os.environ.get('GROQ_API_KEY', '')
if not key or key.startswith('your_') or len(key) < 10:
    print('❌ GROQ_API_KEY vacía o placeholder')
    sys.exit(1)

print(f'   Key: gsk_...{key[-6:]}')

try:
    from groq import Groq
except ImportError as e:
    print(f'   ❌ Librería groq no instalada: {e}')
    sys.exit(1)

try:
    client = Groq(api_key=key)
    # Probar varios modelos recientes
    for model in ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768']:
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{'role': 'user', 'content': 'responde solo: ok'}],
                max_tokens=10
            )
            print(f'   ✅ Groq funciona con modelo {model}: {r.choices[0].message.content.strip()}')
            print('__GROQ_OK__')
            sys.exit(0)
        except Exception as e:
            print(f'   ⚠️  {model}: {type(e).__name__}')
            continue
    print('   ❌ Ningún modelo Groq respondió')
    sys.exit(1)
except Exception as e:
    print(f'   ❌ Error: {type(e).__name__}: {e}')
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then GROQ_STATUS="✅"; fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 3 — Verificar Ollama (local)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Intentar varios endpoints conocidos
OLLAMA_URL=""
for url in "http://localhost:11434" "http://127.0.0.1:11434"; do
    if curl -s -o /dev/null -w "%{http_code}" "$url/api/tags" 2>/dev/null | grep -q "200"; then
        OLLAMA_URL="$url"
        break
    fi
done

if [ -z "$OLLAMA_URL" ]; then
    echo "❌ Ollama no responde en puerto 11434"
else
    echo "   URL: $OLLAMA_URL"
    curl -s "$OLLAMA_URL/api/tags" | python3 -c "
import json, sys
data = json.load(sys.stdin)
models = data.get('models', [])
if models:
    print(f'   ✅ Ollama activo con {len(models)} modelo(s):')
    for m in models:
        size_gb = m.get('size', 0) / 1024 / 1024 / 1024
        print(f'      - {m[\"name\"]} ({size_gb:.1f}GB)')
    print('__OLLAMA_OK__')
else:
    print('   ⚠️  Ollama responde pero sin modelos instalados')
    print('   Para instalar: ollama pull llama3.2:3b')
"
    if [ $? -eq 0 ] && curl -s "$OLLAMA_URL/api/tags" | grep -q '"models":\[{'; then
        OLLAMA_STATUS="✅"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 3b — Verificar OpenAI"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$PYTHON_BIN" << 'PYEOF' 2>&1
import os, sys
env_file = os.path.expanduser('~/CascadeProjects/ViraClip/.env')
for line in open(env_file):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v.strip().strip('"').strip("'")

key = os.environ.get('OPENAI_API_KEY', '')
if not key or key.startswith('your_') or len(key) < 10:
    print('❌ OPENAI_API_KEY vacía')
    sys.exit(1)

print(f'   Key: sk-...{key[-6:]}')
try:
    from openai import OpenAI
    client = OpenAI(api_key=key)
    for model in ['gpt-4o-mini', 'gpt-3.5-turbo']:
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{'role':'user','content':'di ok'}],
                max_tokens=10
            )
            print(f'   ✅ OpenAI funciona con {model}: {r.choices[0].message.content.strip()}')
            print('__OPENAI_OK__')
            sys.exit(0)
        except Exception as e:
            print(f'   ⚠️  {model}: {type(e).__name__}: {str(e)[:100]}')
            continue
    sys.exit(1)
except ImportError:
    print('   ⚠️  librería openai no instalada')
    sys.exit(1)
except Exception as e:
    print(f'   ❌ {type(e).__name__}: {str(e)[:100]}')
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then OPENAI_STATUS="✅"; fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 3c — Verificar Google Gemini"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$PYTHON_BIN" << 'PYEOF' 2>&1
import os, sys
env_file = os.path.expanduser('~/CascadeProjects/ViraClip/.env')
for line in open(env_file):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v.strip().strip('"').strip("'")

key = os.environ.get('GOOGLE_API_KEY', '')
if not key or key.startswith('your_') or len(key) < 10:
    print('❌ GOOGLE_API_KEY vacía')
    sys.exit(1)

print(f'   Key: ...{key[-6:]}')
try:
    import google.generativeai as genai
except ImportError:
    try:
        from google import genai as genai_new
        print('   ⚠️  Usando google.genai (nuevo SDK)')
    except ImportError:
        print('   ⚠️  google-generativeai no instalado')
        sys.exit(1)

try:
    genai.configure(api_key=key)
    for model_name in ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']:
        try:
            model = genai.GenerativeModel(model_name)
            r = model.generate_content('responde solo: ok')
            print(f'   ✅ Gemini funciona con {model_name}: {r.text.strip()[:30]}')
            print('__GOOGLE_OK__')
            sys.exit(0)
        except Exception as e:
            print(f'   ⚠️  {model_name}: {type(e).__name__}: {str(e)[:100]}')
            continue
    sys.exit(1)
except Exception as e:
    print(f'   ❌ {type(e).__name__}: {str(e)[:100]}')
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then GOOGLE_STATUS="✅"; fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 4 — Configuración de LLM en el backend"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "4.1 Variable LLM en .env:"
grep -E "^LLM=" "$ENV_FILE" 2>/dev/null || echo "   (no definida — se usará default)"
echo ""

echo "4.2 Archivos que hacen selección de LLM:"
grep -rlE "GROQ_API_KEY|groq|ollama_base_url|LLM_PROVIDER|llm_provider" \
    ~/CascadeProjects/ViraClip/backend/src/ --include="*.py" 2>/dev/null | head -10
echo ""

echo "4.3 Lógica relevante de config:"
for f in \
    ~/CascadeProjects/ViraClip/backend/src/config.py \
    ~/CascadeProjects/ViraClip/backend/src/core/config.py \
    ~/CascadeProjects/ViraClip/backend/src/services/llm_service.py \
    ~/CascadeProjects/ViraClip/backend/src/services/llm/__init__.py; do
    if [ -f "$f" ]; then
        echo "   [$f]:"
        grep -niE "groq|ollama|llm.*=|provider" "$f" 2>/dev/null | head -15 | sed 's/^/      /'
        echo ""
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "REPORTE FINAL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Groq API:     $GROQ_STATUS"
echo "Ollama local: $OLLAMA_STATUS"
echo "OpenAI:       $OPENAI_STATUS"
echo "Google Gemini:$GOOGLE_STATUS"
echo ""
echo "Variable LLM configurada:"
grep -E "^LLM=" "$ENV_FILE" 2>/dev/null | sed 's/^/   /' || echo "   (no definida)"
echo ""
